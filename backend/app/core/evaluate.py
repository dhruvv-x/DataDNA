"""
Run the deadline check once from the command line:   python -m app.core.evaluate
(The API also does this by itself every RULES_SWEEP_MINUTES minutes.)
"""
import sys

import app.core.env  # noqa: F401  (loads .env)
from app.core import clock, rules
from app.core.pool import close_pool, get_pool


def main() -> int:
    try:
        with get_pool().connection() as db:
            result = rules.sweep(db, now=clock.utcnow(), trigger="cli")
    except Exception as exc:
        print(f"Could not run the check: {exc}", file=sys.stderr)
        return 1
    finally:
        close_pool()
    if result is None:
        print("Another check is already running.")
        return 1
    print(f"Checked {result['checked']} items: {result['raised']} flags raised, {result['cleared']} cleared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
