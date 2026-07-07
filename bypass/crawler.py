"""
🔍 GitHub Crawler — Tự tìm bypass handler mới từ public repos.
Chạy mỗi 6 tiếng. Chỉ import code an toàn (read-only analysis).
"""

import re
import asyncio
import logging
import aiohttp

log = logging.getLogger("crawler")

# Repos công khai hay update bypass VN
TARGET_REPOS = [
    "Amm0ni4/bypass-all-shortlinks-debloated",
    "gongchandang49/bypass-all-shortlinks-debloated",
    "misike12/bypass-all-shortlinks-debloated",
]

GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"

HEADERS = {"User-Agent": "bypass-bot-crawler/1.0"}


async def _fetch_text(url: str) -> str | None:
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.text()
    except Exception as e:
        log.error(f"Fetch error {url}: {e}")
    return None


async def _get_repo_files(repo: str) -> list[str]:
    """Lấy danh sách JS files từ repo (bypass scripts thường là .js hoặc .py)."""
    url = f"{GITHUB_API}/repos/{repo}/git/trees/main?recursive=1"
    text = await _fetch_text(url)
    if not text:
        return []
    import json
    try:
        data = json.loads(text)
        return [
            item["path"] for item in data.get("tree", [])
            if item["path"].endswith((".py", ".js"))
            and any(kw in item["path"].lower() for kw in ("bypass", "shortlink", "handler"))
        ]
    except Exception:
        return []


def _extract_domains_from_code(code: str) -> list[str]:
    """Parse domain names từ code."""
    patterns = [
        r'["\']([a-zA-Z0-9\-]+\.[a-zA-Z]{2,6})["\']',
        r'hostname\s*[=:]\s*["\']([^"\']+)["\']',
        r'domain\s*[=:]\s*["\']([^"\']+)["\']',
    ]
    domains = set()
    for p in patterns:
        for m in re.finditer(p, code):
            d = m.group(1).lower()
            if "." in d and len(d) > 4 and not d.startswith("."):
                domains.add(d)
    return list(domains)


async def crawl_new_domains() -> list[str]:
    """
    Crawl GitHub, trả về list domain mới chưa có trong DOMAIN_MAP.
    Bot admin sẽ nhận alert và quyết định add hay không.
    """
    from bypass.router import DOMAIN_MAP
    known = set(DOMAIN_MAP.keys())
    new_domains = set()

    for repo in TARGET_REPOS:
        files = await _get_repo_files(repo)
        for file_path in files[:10]:  # max 10 files/repo
            url = f"{GITHUB_RAW}/{repo}/main/{file_path}"
            code = await _fetch_text(url)
            if code:
                domains = _extract_domains_from_code(code)
                for d in domains:
                    if d not in known:
                        new_domains.add(d)
        await asyncio.sleep(2)  # rate limit

    log.info(f"[CRAWLER] Found {len(new_domains)} new domains: {new_domains}")
    return list(new_domains)
