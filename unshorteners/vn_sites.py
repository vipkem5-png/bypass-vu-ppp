import asyncio
import cloudscraper
from urllib.parse import urlparse

# Các domain VN cần xử lý đặc biệt (có Cloudflare / JS redirect)
VN_CLOUDSCRAPER_DOMAINS = {
    "ouo.io",
    "ouo.press",
    "link1s.com",
    "shortlink.asia",
    "shorten.vn",
    "za.gl",
    "cut-urls.com",
    "exe.io",
    "fc.lc",
    "clik.pw",
}

def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower().lstrip("www.")

def needs_cloudscraper(url: str) -> bool:
    return get_domain(url) in VN_CLOUDSCRAPER_DOMAINS

async def bypass_with_cloudscraper(url: str) -> str:
    """
    Chạy cloudscraper trong thread pool vì nó là sync.
    Dùng cho các site Cloudflare-protected.
    """
    def _scrape():
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        resp = scraper.get(url, timeout=20, allow_redirects=True)
        return resp.url

    loop = asyncio.get_event_loop()
    final_url = await loop.run_in_executor(None, _scrape)
    return final_url
