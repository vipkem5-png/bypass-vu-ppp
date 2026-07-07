import re
import asyncio
import aiohttp
import cloudscraper
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
}

async def async_get(url: str, **kwargs) -> aiohttp.ClientResponse:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(url, timeout=timeout, allow_redirects=True, **kwargs) as r:
            return r.status, str(r.url), await r.text()

async def async_post(url: str, data: dict, referer: str = "") -> tuple:
    h = {**HEADERS, "Referer": referer, "X-Requested-With": "XMLHttpRequest",
         "Content-Type": "application/x-www-form-urlencoded"}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(headers=h) as s:
        async with s.post(url, data=data, timeout=timeout) as r:
            return r.status, await r.text()

def scraper_get(url: str) -> tuple[int, str, str]:
    """Sync cloudscraper GET — chạy trong thread pool."""
    sc = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    r = sc.get(url, timeout=20, allow_redirects=True)
    return r.status_code, r.url, r.text

def parse_input(html: str, name: str) -> str | None:
    """Lấy value của hidden input theo name."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("input", {"name": name})
    return tag["value"] if tag else None

def find_redirect(html: str) -> str | None:
    """Tìm URL trong window.location hoặc meta refresh."""
    patterns = [
        r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
        r'location\.replace\(["\']([^"\']+)["\']\)',
        r'<meta[^>]+content=["\'][^"\']*url=([^"\']+)["\']',
        r'var\s+url\s*=\s*["\']([^"\']+)["\']',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None
