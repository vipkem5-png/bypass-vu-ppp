import aiohttp

async def follow_redirects(url: str, max_redirects: int = 15) -> str:
    """Follow HTTP redirects đến URL cuối cùng."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                allow_redirects=True,
                max_redirects=max_redirects,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                return str(resp.url)
    except Exception as e:
        raise RuntimeError(f"Không follow được redirect: {e}")
