"""
One place for "what time is it". Code calls clock.utcnow() so tests can move time forward
(lockout expiry, refresh token expiry) without sleeping.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
