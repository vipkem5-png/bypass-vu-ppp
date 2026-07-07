import asyncio
import logging
from urllib.parse import urlparse

from .cache import get_cached, set_cached
from .health import record_success, record_fail, is_dead, register_heal_callback
from .strategy import run_waterfall
from .ai_healer import heal, load_dynamic_handlers
from .handlers.vn import (
    bypass_traffic, bypass_synurl, bypass_layma,
    bypass_seotimtim, bypass_yeulink, bypass_uptolink,
    bypass_linkngon, bypass_linktop, bypass_4mmo, bypass_simple
)
from .handlers.international import (
    bypass_linkvertise, bypass_ouo,
    bypass_cloudflare_generic, bypass_adfly
)

log = logging.getLogger("router")

DOMAIN_MAP: dict[str, callable] = {
    "trafficvn.net":     bypass_traffic,
    "trafficviet.com":   bypass_traffic,
    "traffichub.net":    bypass_traffic,
    "synurl.com":        bypass_synurl,
    "layma.net":         bypass_layma,
    "taplayma.com":      bypass_layma,
    "nhapma.com":        bypass_layma,
    "seotimtim.com":     bypass_seotimtim,
    "yeulink.vn":        bypass_yeulink,
    "yeulink.net":       bypass_yeulink,
    "uptolink.one":      bypass_uptolink,
    "linkngon.io":       bypass_linkngon,
    "linktop.one":       bypass_linktop,
    "4mmo.vn":           bypass_4mmo,
    "linkuser.net":      bypass_simple,
    "link4sub.com":      bypass_simple,
    "linkfree.vn":       bypass_simple,
    "linkvertise.com":   bypass_linkvertise,
    "link-target.net":   bypass_linkvertise,
    "ouo.io":            bypass_ouo,
    "ouo.press":         bypass_ouo,
    "adf.ly":            bypass_adfly,
    "bit.ly":            bypass_simple,
    "tinyurl.com":       bypass_simple,
    "t.co":              bypass_simple,
    "exe.io":            bypass_cloudflare_generic,
    "fc.lc":             bypass_cloudflare_generic,
    "za.gl":             bypass_cloudflare_generic,
    "bc.vc":             bypass_simple,
}

ALL_DOMAINS = set(DOMAIN_MAP.keys())
_dynamic_handlers: dict = {}

# Last-known working URL per domain (để AI heal có sample URL)
_sample_urls: dict[str, str] = {}


def reload_dynamic():
    global _dynamic_handlers
    _dynamic_handlers = load_dynamic_handlers()
    log.info(f"[DYNAMIC] Loaded {len(_dynamic_handlers)} AI handlers")


reload_dynamic()


def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower().lstrip("www.")


def is_shortlink(url: str) -> bool:
    d = get_domain(url)
    return any(d == s or d.endswith("." + s)
               for s in ALL_DOMAINS | set(_dynamic_handlers.keys()))


def _get_handler(domain: str):
    # 1. Dynamic AI handler ưu tiên nếu đang có
    for k, fn in _dynamic_handlers.items():
        if domain == k or domain.endswith("." + k):
            return fn, "ai_dynamic"
    # 2. Static handler
    for k, fn in DOMAIN_MAP.items():
        if domain == k or domain.endswith("." + k):
            return fn, "static"
    return None, "none"


async def _try_handler(handler, url: str, retries: int = 2) -> str:
    last = None
    for i in range(retries + 1):
        try:
            return await asyncio.wait_for(handler(url), timeout=22)
        except Exception as e:
            last = e
        if i < retries:
            await asyncio.sleep(1.2 ** i)
    raise last


# ── Heal callback (được gọi khi domain die) ───────────────────────

async def _on_domain_dead(domain: str, reason: str):
    """Khi domain die, tự động trigger AI heal."""
    sample = _sample_urls.get(domain)
    if not sample:
        log.warning(f"[HEAL] No sample URL for {domain}, cannot heal")
        return

    log.info(f"[HEAL] Auto-healing {domain}")
    result = await heal(domain, sample, reason)

    if result["success"]:
        reload_dynamic()
        log.info(f"[HEAL] ✅ {domain} healed — new handler registered")
    else:
        log.error(f"[HEAL] ❌ {domain} heal failed: {result['reason']}")

    # Alert Discord (bot instance inject callback sau)
    for cb in _alert_callbacks:
        try:
            await cb(domain, result)
        except Exception:
            pass


_alert_callbacks: list = []


def register_alert_callback(fn):
    _alert_callbacks.append(fn)


register_heal_callback(_on_domain_dead)


# ── Main bypass function ──────────────────────────────────────────

async def bypass(url: str) -> dict:
    cached = get_cached(url)
    if cached:
        return {**cached, "cached": True}

    domain = get_domain(url)
    _sample_urls[domain] = url

    handler, handler_type = _get_handler(domain)
    final = None
    method = None

    # Phase 1: static/AI handler
    if handler and not is_dead(domain):
        try:
            final = await _try_handler(handler, url)
            method = handler_type
        except Exception as e:
            record_fail(domain, str(e))
            log.warning(f"[{domain}] handler failed: {e} — falling to waterfall")

    # Phase 2: waterfall (nếu handler fail hoặc không có handler)
    if not final:
        try:
            final, method = await run_waterfall(url)
        except Exception as e:
            # Phase 3: AI heal (async, không block response)
            asyncio.create_task(_on_domain_dead(domain, str(e)))
            return {
                "original": url, "final": None,
                "changed": False, "domain": domain,
                "status": "error",
                "error": str(e),
                "cached": False, "method": "all_failed",
                "healing": True,  # Bot sẽ thông báo đang heal
            }

    record_success(domain)
    result = {
        "original": url,
        "final": final,
        "changed": url.rstrip("/") != str(final).rstrip("/"),
        "domain": domain,
        "status": "ok",
        "cached": False,
        "method": method,
        "healing": False,
    }
    if result["changed"]:
        set_cached(url, result)
    return result
