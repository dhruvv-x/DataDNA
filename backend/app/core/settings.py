"""
Auth settings, read from environment variables at call time (so tests can change them).

JWT_SECRET is required. The app refuses to start without it (see startup_checks).
"""
import os

from app.core import env  # noqa: F401  (loads datadna/.env)


class SettingsError(Exception):
    pass


MIN_SECRET_LENGTH = 32


def _int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number, got '{raw}'")
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}, got {value}")
    return value


def jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH:
        raise SettingsError(
            f"JWT_SECRET is missing or shorter than {MIN_SECRET_LENGTH} characters. "
            "Create one with:  python3 -c \"import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))\" >> ~/datadna/.env"
        )
    return secret


def access_token_minutes() -> int:
    return _int("ACCESS_TOKEN_MINUTES", 30, 1, 24 * 60)


def refresh_token_days() -> int:
    return _int("REFRESH_TOKEN_DAYS", 7, 1, 90)


def bcrypt_cost() -> int:
    return _int("BCRYPT_COST", 12, 4, 15)


def lockout_threshold() -> int:
    return _int("LOCKOUT_THRESHOLD", 5, 1, 100)


def lockout_minutes() -> int:
    return _int("LOCKOUT_MINUTES", 15, 1, 24 * 60)


def cookie_secure() -> bool:
    """True when the site runs on https. Browsers drop Secure cookies on plain http."""
    return os.environ.get("COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes")


def cookie_samesite() -> str:
    value = os.environ.get("COOKIE_SAMESITE", "lax").strip().lower()
    if value not in ("lax", "strict", "none"):
        raise SettingsError("COOKIE_SAMESITE must be lax, strict or none")
    if value == "none" and not cookie_secure():
        raise SettingsError("COOKIE_SAMESITE=none needs COOKIE_SECURE=true")
    return value


def cookie_path() -> str:
    """
    URL path the refresh cookie is sent to. Default "/auth" matches the API's own paths.
    Behind the dev proxy / reverse proxy that adds an "/api" prefix, set COOKIE_PATH=/api/auth,
    otherwise the browser never sends the cookie back and every refresh fails.
    """
    value = os.environ.get("COOKIE_PATH", "").strip() or "/auth"
    if not value.startswith("/") or any(ch in value for ch in " ;,\t\r\n"):
        raise SettingsError("COOKIE_PATH must start with / and contain no spaces, commas or semicolons")
    return value


def storage_dir() -> str:
    """Folder for uploaded files. Must be OUTSIDE the git repo. Default: ~/datadna_storage"""
    from pathlib import Path
    raw = os.environ.get("STORAGE_DIR", "").strip() or "~/datadna_storage"
    return str(Path(raw).expanduser().resolve())


def max_upload_mb() -> int:
    """Global upload cap. A checklist item may set a lower limit, never a higher one."""
    return _int("MAX_UPLOAD_MB", 50, 1, 500)


def rules_sweep_minutes() -> int:
    """How often the API re-checks deadlines by itself. 0 switches the automatic check off."""
    return _int("RULES_SWEEP_MINUTES", 10, 0, 1440)


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def startup_checks() -> None:
    """Called when the API starts. Raises SettingsError so a bad setup fails loudly."""
    jwt_secret()
    cost = bcrypt_cost()
    if cost < 10 and os.environ.get("APP_ENV") != "test":
        raise SettingsError("BCRYPT_COST below 10 is only allowed when APP_ENV=test")
    cookie_samesite()
    cookie_path()
    access_token_minutes()
    refresh_token_days()
    lockout_threshold()
    lockout_minutes()
    max_upload_mb()
    rules_sweep_minutes()
    from pathlib import Path
    root = Path(storage_dir())
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_test"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise SettingsError(f"STORAGE_DIR ({root}) is not writable: {exc}")
