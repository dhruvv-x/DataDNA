"""
Test-wide settings. Runs before any test module is imported.
The tests never depend on your real .env: auth settings are forced here.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 48)
os.environ["BCRYPT_COST"] = "4"  # fast hashing, tests only (real default is 12)
os.environ["APP_ENV"] = "test"
os.environ["RULES_SWEEP_MINUTES"] = "0"  # no background thread in tests
os.environ["COOKIE_SECURE"] = "false"
os.environ["COOKIE_SAMESITE"] = "lax"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["COOKIE_PATH"] = "/auth"  # the real .env uses /api/auth (S7 proxy); tests must not depend on it
for _name in ("ACCESS_TOKEN_MINUTES", "REFRESH_TOKEN_DAYS", "LOCKOUT_THRESHOLD", "LOCKOUT_MINUTES"):
    os.environ.pop(_name, None)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _private_storage(tmp_path, monkeypatch):
    """Uploaded files in tests go to a temp folder, never to ~/datadna_storage."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))


def pytest_make_parametrize_id(config, val, argname):
    """Never print raw file bytes in test names."""
    if isinstance(val, (bytes, bytearray)):
        return f"{argname}_{len(val)}B"
    return None
