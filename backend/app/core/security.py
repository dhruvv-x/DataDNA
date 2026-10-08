"""
Passwords (bcrypt) and tokens (JWT access token, random refresh token). S3.

bcrypt only looks at the first 72 BYTES of a password and ignores the rest without telling you.
So passwords longer than 72 bytes are rejected here instead of being silently cut.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
import jwt

from app.core import clock, settings

MIN_PASSWORD_CHARS = 10
MAX_PASSWORD_BYTES = 72
ALGORITHM = "HS256"
ACCESS_TYPE = "access"

# Letters and digits without look-alikes (no 0/O, 1/l/I), for temporary passwords.
_TEMP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


class PasswordPolicyError(ValueError):
    pass


class TokenError(Exception):
    """The access token is missing, expired, tampered with, or not ours."""


# ---------------------------------------------------------------- passwords
def validate_new_password(password: str, *, email: str | None = None) -> None:
    if len(password) < MIN_PASSWORD_CHARS:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_CHARS} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError(
            f"Password is too long (limit is {MAX_PASSWORD_BYTES} bytes; some characters use more than one byte)."
        )
    if len(set(password)) < 4:
        raise PasswordPolicyError("Password is too repetitive.")
    if email and password.strip().lower() == email.strip().lower():
        raise PasswordPolicyError("Password must not be the same as the email address.")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=settings.bcrypt_cost())).decode("ascii")


_dummy_cache: dict[int, str] = {}


def dummy_hash() -> str:
    """A real hash of a throwaway password, used to burn the same time as a real check."""
    cost = settings.bcrypt_cost()
    if cost not in _dummy_cache:
        _dummy_cache[cost] = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=cost)).decode("ascii")
    return _dummy_cache[cost]


def verify_password(password: str, password_hash: str) -> bool:
    """True only for a correct password. Never raises on odd input."""
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"x", dummy_hash().encode("ascii"))  # keep the timing the same
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def generate_temporary_password() -> str:
    while True:
        candidate = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(14))
        try:
            validate_new_password(candidate)
            return candidate
        except PasswordPolicyError:
            continue


# ---------------------------------------------------------------- access token (JWT)
def password_version(password_changed_at: datetime) -> int:
    """A number that changes whenever the password changes. Stored inside the access token."""
    return int(password_changed_at.timestamp() * 1_000_000)


def create_access_token(user_id: uuid.UUID, password_changed_at: datetime, now: datetime | None = None) -> str:
    now = now or clock.utcnow()
    payload = {
        "sub": str(user_id),
        "typ": ACCESS_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes())).timestamp()),
        "jti": uuid.uuid4().hex,
        "pv": password_version(password_changed_at),
    }
    return jwt.encode(payload, settings.jwt_secret(), algorithm=ALGORITHM)


# Newer PyJWT versions refuse a token whose issue time lies even one second in the future. A computer clock
# that steps back a little (WSL2 after sleep, a time sync) would then reject a token that was just issued.
CLOCK_LEEWAY_SECONDS = 10


def decode_access_token(token: str) -> dict:
    """Returns the claims, or raises TokenError. Only HS256 is accepted (never 'none')."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "typ", "pv"]},
            leeway=CLOCK_LEEWAY_SECONDS,
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims.get("typ") != ACCESS_TYPE:
        raise TokenError("wrong token type")
    try:
        uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise TokenError("bad subject") from exc
    if not isinstance(claims["pv"], int):
        raise TokenError("bad password version")
    return claims


# ---------------------------------------------------------------- refresh token
def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the cookie, SHA-256 hex to store in the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
