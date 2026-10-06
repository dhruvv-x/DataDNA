"""
Background deadline check inside the API process (S5). Every RULES_SWEEP_MINUTES minutes (0 = off) it runs
rules.sweep(). Two API workers cannot run it at once (database lock). A failure is logged and retried at the
next round; it never stops the API.
"""
import logging
import threading

from app.core import clock, rules, settings
from app.core.pool import get_pool

log = logging.getLogger("rules.scheduler")
FIRST_RUN_DELAY = 30  # seconds after start

_stop = threading.Event()
_thread: threading.Thread | None = None


def run_once() -> dict | None:
    with get_pool().connection() as db:
        return rules.sweep(db, now=clock.utcnow(), trigger="schedule")


def _loop(minutes: int) -> None:
    wait = FIRST_RUN_DELAY
    while not _stop.wait(wait):
        try:
            result = run_once()
            if result:
                log.info("deadline check: %s", result)
        except Exception:
            log.exception("deadline check failed; will retry")
        wait = minutes * 60


def start() -> None:
    global _thread
    minutes = settings.rules_sweep_minutes()
    if minutes <= 0 or _thread is not None:
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(minutes,), name="rules-sweep", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None
