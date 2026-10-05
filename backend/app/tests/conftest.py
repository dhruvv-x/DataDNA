"""
Test-wide settings. Runs before any test module is imported.
The tests never depend on your real .env: auth settings are forced here.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 48)
os.environ["BCRYPT_COST"] = "4"  # fast hashing, tests only (real default is 12)
os.environ["APP_ENV"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["COOKIE_SAMESITE"] = "lax"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
for _name in ("ACCESS_TOKEN_MINUTES", "REFRESH_TOKEN_DAYS", "LOCKOUT_THRESHOLD", "LOCKOUT_MINUTES"):
    os.environ.pop(_name, None)
