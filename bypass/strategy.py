"""
Multi-strategy waterfall — thử từng approach theo thứ tự.
Khi tất cả fail → AI Healer.
"""

import asyncio
import logging
import aiohttp
from bs4 import BeautifulSoup
from .utils import async_get, async_post, find_redirect, parse_input, HEADERS, TIMEOUT, run_in_executor, scraper_get
import json
import re

log = logging.getLogger("strategy")


async def strategy_redirect(url: str) -> str:
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(url, allow_redirects=True, max_redirects=15,
                         timeout=TIMEOUT, ssl=False) as r:
            final = str(r.url)
            if final.rstrip("/") != url.rstrip("/"):
                return final
            raise RuntimeError("No redirect")


async def strategy_form_submit(url: str) -> str:
    _, final_url, html = await async_get(url)
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form")
    if not form:
        raise RuntimeError("No form found")
    action = form.get("action") or final_url
    if not action.startswith("http"):
        action = "/".join(final_url.split("/")[:3]) + action
    fields = {i["name"]: i.get("value", "")
              for i in form.find_all("input") if i.get("name")}
    _, resp = await async_post(action, data=fields, referer=url)
    r = find_redirect(resp)
    if r:
        return r
    soup2 = BeautifulSoup(resp, "lxml")
    for a in soup2.find_all("a", href=re.compile(r"^https?://")):
        if url.split("/")[2] not in a["href"]:
            return a["href"]
    raise RuntimeError("Form submit: no target")


async def strategy_api_token(url: str) -> str:
    _, final_url, html = await async_get(url)
    base = "/".join(final_url.split("/")[:3])
    token = parse_input(html, "_token") or parse_input(html, "token")
    slug = url.rstrip("/").split("/")[-1]

    if not token:
        raise RuntimeError("No token found")

    for ep in ("/api/go", "/api/link/go", "/links/go", "/go"):
        try:
            _, resp = await async_post(
                f"{base}{ep}",
                data={"_token": token, "token": token, "slug": slug, "link": slug},
                referer=url
            )
            try:
                data = json.loads(resp)
                for k in ("url", "link", "redirect", "target"):
                    if data.get(k, "").startswith("http"):
                        return data[k]
            except Exception:
                pass
            r = find_redirect(resp)
            if r:
                return r
        except Exception:
            continue
    raise RuntimeError("API token: all endpoints failed")


async def strategy_js_parse(url: str) -> str:
    _, _, html = await async_get(url)
    r = find_redirect(html)
    if r:
        return r
    # Tìm data-* attributes
    soup = BeautifulSoup(html, "lxml")
    for attr in ("data-link", "data-url", "data-href", "data-redirect"):
        tag = soup.find(attrs={attr: re.compile(r"^https?://")})
        if tag:
            return tag[attr]
    raise RuntimeError("JS parse: no URL found")


async def strategy_cloudscraper(url: str) -> str:
    status, final_url, html = await run_in_executor(scraper_get, url)
    if final_url.rstrip("/") != url.rstrip("/"):
        return final_url
    r = find_redirect(html)
    if r:
        return r
    raise RuntimeError("Cloudscraper: no redirect")


# Thứ tự waterfall: nhanh → chậm → AI
WATERFALL = [
    ("redirect",     strategy_redirect),
    ("js_parse",     strategy_js_parse),
    ("form_submit",  strategy_form_submit),
    ("api_token",    strategy_api_token),
    ("cloudscraper", strategy_cloudscraper),
]


async def run_waterfall(url: str) -> tuple[str, str]:
    """Thử từng strategy, trả về (result, strategy_name)."""
    last_errors = []
    for name, fn in WATERFALL:
        try:
            result = await asyncio.wait_for(fn(url), timeout=18)
            if result and result.startswith("http"):
                log.debug(f"[{name}] ✓ {url[:60]}")
                return result, name
        except asyncio.TimeoutError:
            last_errors.append(f"{name}: timeout")
        except Exception as e:
            last_errors.append(f"{name}: {e}")
    raise RuntimeError(" | ".join(last_errors[-3:]))
