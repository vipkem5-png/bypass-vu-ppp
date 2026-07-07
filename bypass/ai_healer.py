"""
🧠 AI Healer — Dùng Claude API để:
1. Nhận HTML của trang lỗi
2. Phân tích cấu trúc
3. Tự viết Python handler mới
4. Test handler
5. Ghi vào data/dynamic_handlers.py nếu pass
"""

import re
import ast
import asyncio
import logging
import importlib
import traceback
from pathlib import Path

import anthropic

from .utils import async_get
import config

log = logging.getLogger("ai_healer")
DYNAMIC_FILE = Path("data/dynamic_handlers.py")
DYNAMIC_FILE.parent.mkdir(exist_ok=True)

if not DYNAMIC_FILE.exists():
    DYNAMIC_FILE.write_text(
        '"""\nAI-generated handlers. Auto-managed. Do not edit manually.\n"""\n\n'
        'from bypass.utils import async_get, async_post, find_redirect, parse_input\n'
        'import re, json\n\nHANDLERS = {}\n'
    )

_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """
You are an expert Python web scraping engineer specializing in bypass shortlink handlers.

Given the HTML source of a Vietnamese/international shortlink page, you must write a single
async Python function to extract the final destination URL.

Rules:
1. Function signature: `async def handler(url: str) -> str:`
2. You can use: `async_get`, `async_post`, `find_redirect`, `parse_input`, `re`, `json`, `BeautifulSoup`
3. Always import what you use inside the function
4. Raise RuntimeError if bypass fails — never return empty string
5. Return ONLY the Python function code, no explanation, no markdown, no backticks
6. Study the HTML carefully: find form tokens, API endpoints, JS variables, hidden inputs
7. Try the most direct route first (POST to an API), fall back to form submit
""".strip()


async def _fetch_page_html(url: str) -> str:
    try:
        _, _, html = await async_get(url)
        return html[:15000]
    except Exception as e:
        raise RuntimeError(f"Cannot fetch page: {e}")


def _extract_code(response_text: str) -> str:
    """Lấy code Python thuần từ response Claude."""
    code = response_text.strip()
    # Strip markdown nếu có
    code = re.sub(r'^```(?:python)?\s*', '', code, flags=re.MULTILINE)
    code = re.sub(r'```\s*$', '', code, flags=re.MULTILINE)
    return code.strip()


def _validate_code(code: str) -> bool:
    """Validate syntax trước khi chạy."""
    try:
        tree = ast.parse(code)
        # Phải có function tên handler
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
        return "handler" in funcs
    except SyntaxError:
        return False


async def _test_handler(code: str, test_url: str) -> tuple[bool, str]:
    """Chạy thử handler trong sandbox, timeout 20s."""
    namespace = {}
    try:
        exec(compile(code, "<ai_handler>", "exec"), namespace)
        handler_fn = namespace.get("handler")
        if not handler_fn:
            return False, "No handler function found"
        result = await asyncio.wait_for(handler_fn(test_url), timeout=20)
        if result and result.startswith("http"):
            return True, result
        return False, f"Bad result: {result}"
    except asyncio.TimeoutError:
        return False, "Timeout 20s"
    except Exception as e:
        return False, str(e)


def _register_to_file(domain: str, code: str):
    """Ghi handler vào dynamic_handlers.py."""
    current = DYNAMIC_FILE.read_text()

    # Xoá handler cũ của domain này nếu có
    pattern = rf'# HANDLER::{re.escape(domain)}.*?# END::{re.escape(domain)}\n'
    current = re.sub(pattern, '', current, flags=re.DOTALL)

    # Thêm handler mới
    block = (
        f"\n# HANDLER::{domain}\n"
        f"{code}\n"
        f'HANDLERS["{domain}"] = handler\n'
        f"# END::{domain}\n"
    )

    # Ghi trước dòng HANDLERS = {}
    current = current.replace("HANDLERS = {}", "HANDLERS = {}" + block)
    DYNAMIC_FILE.write_text(current)
    log.info(f"[AI] Registered handler for {domain}")


def load_dynamic_handlers() -> dict:
    """Load handlers đã được AI tạo từ file."""
    try:
        spec = importlib.util.spec_from_file_location("dynamic_handlers", DYNAMIC_FILE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "HANDLERS", {})
    except Exception as e:
        log.error(f"Cannot load dynamic handlers: {e}")
        return {}


async def heal(domain: str, sample_url: str, reason: str = "") -> dict:
    """
    Main healing loop:
    1. Fetch HTML
    2. Ask Claude
    3. Validate
    4. Test
    5. Register nếu pass
    """
    log.info(f"[HEAL] Starting for {domain} | reason: {reason}")

    if not config.AI_HEAL_ENABLED or not config.ANTHROPIC_API_KEY:
        return {"success": False, "reason": "AI heal disabled"}

    try:
        html = await _fetch_page_html(sample_url)
    except Exception as e:
        return {"success": False, "reason": str(e)}

    prompt = (
        f"Domain: {domain}\n"
        f"Sample URL: {sample_url}\n"
        f"Previous error: {reason}\n\n"
        f"HTML (first 12000 chars):\n{html[:12000]}\n\n"
        f"Write the handler function."
    )

    try:
        message = await _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        code = _extract_code(message.content[0].text)
    except Exception as e:
        return {"success": False, "reason": f"Claude API error: {e}"}

    if not _validate_code(code):
        return {"success": False, "reason": "Generated code failed syntax/validation"}

    passed, test_result = await _test_handler(code, sample_url)
    if not passed:
        return {"success": False, "reason": f"Handler test failed: {test_result}"}

    _register_to_file(domain, code)
    return {"success": True, "final_url": test_result, "code_length": len(code)}
