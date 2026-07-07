import aiohttp
import asyncio
import cloudscraper
from .utils import HEADERS, find_redirect

CLOUDFLARE_DOMAINS = {"ouo.io", "ouo.press", "exe.io", "fc.lc", "za.gl", "link1s.com"}

async def bypass_generic(url: str) -> str:
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower().lstrip("www.")

    if domain in CLOUDFLARE_DOMAINS:
        return await _cloudscraper_bypass(url)
    return await _redirect_follow(url)

async def _redirect_follow(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(url, allow_redirects=True, max_redirects=15, timeout=timeout) as r:
            return str(r.url)

async def _cloudscraper_bypass(url: str) -> str:
    def _do():
        sc = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        r = sc.get(url, timeout=20, allow_redirects=True)
        return r.url
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do)
