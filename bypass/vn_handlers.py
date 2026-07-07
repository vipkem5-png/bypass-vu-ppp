"""
Handler riêng cho từng site VN trong danh sách.
Mỗi hàm nhận url: str, trả về str (URL đích) hoặc raise RuntimeError.

Sites:
- TrafficVN / TrafficViet / TrafficHub  → cùng engine (paid4link style)
- Synurl.com
- Layma.net / Taplayma.com / Nhapma.com
- Seotimtim.com
- Yeulink.vn
- Uptolink.one
- Linkngon.io
- Linktop.one
- 4MMO.vn
- LinkUser / Link4sub / Linkfree         → shortlink đơn giản
"""

import asyncio
import re
import json
from .utils import async_get, async_post, scraper_get, parse_input, find_redirect, HEADERS
from bs4 import BeautifulSoup
import aiohttp


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

async def _run_sync(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


# ─────────────────────────────────────────────────────────────────
# TrafficVN / TrafficViet / TrafficHub
# Pattern: GET page → lấy token → POST /go → parse redirect
# ─────────────────────────────────────────────────────────────────

async def bypass_traffic(url: str) -> str:
    status, final_url, html = await async_get(url)
    soup = BeautifulSoup(html, "lxml")

    # Tìm token ẩn (thường là input[name=token] hoặc data-token)
    token = parse_input(html, "token") or parse_input(html, "_token")
    link_id = parse_input(html, "id") or parse_input(html, "link_id")

    if not token or not link_id:
        # Thử lấy từ JS
        m = re.search(r'token["\s:]+["\']([a-zA-Z0-9_\-]+)["\']', html)
        if m:
            token = m.group(1)
        m2 = re.search(r'"id"\s*:\s*"?(\d+)"?', html)
        if m2:
            link_id = m2.group(1)

    if not token:
        raise RuntimeError("Không tìm được token trong trang traffic")

    base = url.split("/")[0] + "//" + url.split("/")[2]
    _, resp_text = await async_post(
        f"{base}/go",
        data={"token": token, "id": link_id or ""},
        referer=url
    )

    try:
        data = json.loads(resp_text)
        if data.get("url"):
            return data["url"]
        if data.get("link"):
            return data["link"]
    except Exception:
        pass

    result = find_redirect(resp_text)
    if result:
        return result

    raise RuntimeError("TrafficVN: không parse được URL đích")


# ─────────────────────────────────────────────────────────────────
# Synurl.com
# Pattern: GET → lấy _token + id → POST /go-link → JSON url
# ─────────────────────────────────────────────────────────────────

async def bypass_synurl(url: str) -> str:
    status, final_url, html = await async_get(url)
    _token = parse_input(html, "_token")
    link_id = parse_input(html, "link_id") or re.search(r'/([a-zA-Z0-9]+)$', url)
    if isinstance(link_id, re.Match):
        link_id = link_id.group(1)

    if not _token:
        raise RuntimeError("Synurl: không tìm được CSRF token")

    _, resp = await async_post(
        "https://synurl.com/go-link",
        data={"_token": _token, "link_id": link_id or ""},
        referer=url
    )
    try:
        data = json.loads(resp)
        return data.get("url") or data.get("link") or data["target_url"]
    except Exception:
        raise RuntimeError(f"Synurl: parse thất bại — {resp[:200]}")


# ─────────────────────────────────────────────────────────────────
# Layma.net / Taplayma.com / Nhapma.com
# Pattern: có 5s timer → POST /links/go → JSON
# ─────────────────────────────────────────────────────────────────

async def bypass_layma(url: str) -> str:
    status, final_url, html = await async_get(url)
    soup = BeautifulSoup(html, "lxml")

    _token = parse_input(html, "_token")
    # link slug từ URL
    slug = url.rstrip("/").split("/")[-1]

    if not _token:
        raise RuntimeError("Layma: không có CSRF token")

    base_domain = final_url.split("/")[0] + "//" + final_url.split("/")[2]

    _, resp = await async_post(
        f"{base_domain}/links/go",
        data={"_token": _token, "link": slug},
        referer=url
    )

    try:
        data = json.loads(resp)
        for key in ("url", "link", "target", "redirect"):
            if data.get(key):
                return data[key]
    except Exception:
        pass

    result = find_redirect(resp)
    if result:
        return result

    raise RuntimeError(f"Layma: bypass thất bại — {resp[:200]}")


# ─────────────────────────────────────────────────────────────────
# Seotimtim.com
# Pattern: GET → có form với hidden fields → POST
# ─────────────────────────────────────────────────────────────────

async def bypass_seotimtim(url: str) -> str:
    status, final_url, html = await async_get(url)
    soup = BeautifulSoup(html, "lxml")

    form = soup.find("form")
    if not form:
        raise RuntimeError("Seotimtim: không tìm được form")

    action = form.get("action") or url
    fields = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}

    _, resp = await async_post(action, data=fields, referer=url)

    result = find_redirect(resp)
    if result:
        return result

    soup2 = BeautifulSoup(resp, "lxml")
    a = soup2.find("a", {"id": "go-link"}) or soup2.find("a", {"class": re.compile("btn")})
    if a and a.get("href"):
        return a["href"]

    raise RuntimeError("Seotimtim: không tìm được URL đích")


# ─────────────────────────────────────────────────────────────────
# Yeulink.vn
# Pattern: GET page → JS parse "data-link" → follow
# ─────────────────────────────────────────────────────────────────

async def bypass_yeulink(url: str) -> str:
    status, final_url, html = await async_get(url)
    soup = BeautifulSoup(html, "lxml")

    # Tìm data-link hoặc data-url trong HTML
    for attr in ("data-link", "data-url", "data-href"):
        tag = soup.find(attrs={attr: True})
        if tag:
            return tag[attr]

    # Thử tìm trong JS
    patterns = [
        r'data[_-]link\s*[=:]\s*["\']([^"\']+)["\']',
        r'"link"\s*:\s*"([^"]+)"',
        r'redirect\s*=\s*["\']([^"\']+)["\']',
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            return m.group(1)

    # Fallback: follow redirect từ final_url
    if final_url != url:
        return final_url

    raise RuntimeError("Yeulink: không tìm được URL đích")


# ─────────────────────────────────────────────────────────────────
# Uptolink.one
# Pattern: cloudscraper → parse URL từ response
# ─────────────────────────────────────────────────────────────────

async def bypass_uptolink(url: str) -> str:
    def _do():
        return scraper_get(url)

    status, final_url, html = await _run_sync(_do)
    soup = BeautifulSoup(html, "lxml")

    # Tìm nút "Tiếp tục" hoặc link đích
    for tag in soup.find_all("a"):
        href = tag.get("href", "")
        if href.startswith("http") and "uptolink" not in href:
            return href

    result = find_redirect(html)
    if result:
        return result

    raise RuntimeError("Uptolink: không tìm được URL đích")


# ─────────────────────────────────────────────────────────────────
# Linkngon.io
# Pattern: GET → POST /api/link/go với token
# ─────────────────────────────────────────────────────────────────

async def bypass_linkngon(url: str) -> str:
    status, final_url, html = await async_get(url)

    token = parse_input(html, "_token") or parse_input(html, "token")
    slug = url.rstrip("/").split("/")[-1]

    # Thử endpoint API trực tiếp
    try:
        _, resp = await async_post(
            "https://linkngon.io/api/link/go",
            data={"token": token or "", "slug": slug},
            referer=url
        )
        data = json.loads(resp)
        for k in ("url", "link", "redirect", "target"):
            if data.get(k):
                return data[k]
    except Exception:
        pass

    result = find_redirect(html)
    if result:
        return result

    raise RuntimeError("Linkngon: bypass thất bại")


# ─────────────────────────────────────────────────────────────────
# Linktop.one
# Pattern: tương tự Linkngon — POST /api/go
# ─────────────────────────────────────────────────────────────────

async def bypass_linktop(url: str) -> str:
    status, final_url, html = await async_get(url)
    token = parse_input(html, "_token") or parse_input(html, "token")
    slug = url.rstrip("/").split("/")[-1]

    try:
        _, resp = await async_post(
            "https://linktop.one/api/go",
            data={"token": token or "", "slug": slug},
            referer=url
        )
        data = json.loads(resp)
        for k in ("url", "link", "redirect"):
            if data.get(k):
                return data[k]
    except Exception:
        pass

    result = find_redirect(html)
    if result:
        return result

    raise RuntimeError("Linktop: bypass thất bại")


# ─────────────────────────────────────────────────────────────────
# 4MMO.vn
# Pattern: GET → parse "go_link" form → POST
# ─────────────────────────────────────────────────────────────────

async def bypass_4mmo(url: str) -> str:
    status, final_url, html = await async_get(url)
    soup = BeautifulSoup(html, "lxml")

    form = soup.find("form", {"id": re.compile("go|link|form", re.I)}) or soup.find("form")
    if not form:
        # Thử parse trực tiếp JS
        result = find_redirect(html)
        if result:
            return result
        raise RuntimeError("4MMO: không tìm được form")

    action = form.get("action") or url
    fields = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}

    _, resp = await async_post(action, data=fields, referer=url)

    result = find_redirect(resp)
    if result:
        return result

    soup2 = BeautifulSoup(resp, "lxml")
    for a in soup2.find_all("a"):
        href = a.get("href", "")
        if href.startswith("http") and "4mmo" not in href.lower():
            return href

    raise RuntimeError("4MMO: không parse được URL đích")


# ─────────────────────────────────────────────────────────────────
# LinkUser / Linkfree / Link4sub
# Pattern: đơn giản — GET → follow redirect
# ─────────────────────────────────────────────────────────────────

async def bypass_simple_redirect(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(url, allow_redirects=True, max_redirects=15, timeout=timeout) as r:
            final = str(r.url)
            if final != url:
                return final
            html = await r.text()

    result = find_redirect(html)
    if result:
        return result

    raise RuntimeError("Simple bypass: URL không thay đổi sau redirect")
