"""
Theo dõi success/fail rate từng domain.
Khi domain die → trigger AI healer.
"""

import json
import time
import logging
import asyncio
from pathlib import Path
from collections import defaultdict

log = logging.getLogger("health")
DATA_FILE = Path("data/domain_health.json")
DATA_FILE.parent.mkdir(exist_ok=True)

# In-memory stats
_stats: dict[str, dict] = defaultdict(lambda: {
    "success": 0, "fail": 0,
    "consecutive_fail": 0,
    "last_fail_reason": "",
    "last_success": 0,
    "status": "ok",        # ok | degraded | dead
})

_heal_callbacks: list = []  # functions to call khi domain die


def load():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text())
            for k, v in data.items():
                _stats[k].update(v)
        except Exception:
            pass


def save():
    DATA_FILE.write_text(json.dumps(dict(_stats), indent=2))


def record_success(domain: str):
    s = _stats[domain]
    s["success"] += 1
    s["consecutive_fail"] = 0
    s["last_success"] = int(time.time())
    s["status"] = "ok"
    save()


def record_fail(domain: str, reason: str):
    s = _stats[domain]
    s["fail"] += 1
    s["consecutive_fail"] += 1
    s["last_fail_reason"] = reason[:300]

    if s["consecutive_fail"] >= 3:
        prev = s["status"]
        s["status"] = "dead"
        if prev != "dead":
            log.warning(f"[DEAD] {domain} — {reason}")
            asyncio.create_task(_notify_dead(domain, reason))
    elif s["consecutive_fail"] >= 1:
        s["status"] = "degraded"

    save()


async def _notify_dead(domain: str, reason: str):
    for cb in _heal_callbacks:
        try:
            await cb(domain, reason)
        except Exception as e:
            log.error(f"heal callback error: {e}")


def register_heal_callback(fn):
    _heal_callbacks.append(fn)


def get_stats() -> dict:
    return dict(_stats)


def is_dead(domain: str) -> bool:
    return _stats[domain]["status"] == "dead"


load()
