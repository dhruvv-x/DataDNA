"""S3: password and token helpers. No database needed."""
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core import security, settings
from app.core.settings import SettingsError

PW = "Correct-Horse-42"
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------- passwords
def test_hash_and_verify_roundtrip():
    h = security.hash_password(PW)
    assert h.startswith("$2")
    assert security.verify_password(PW, h) is True


def test_wrong_password_is_false():
    assert security.verify_password("Wrong-Horse-42x", security.hash_password(PW)) is False


def test_hash_is_salted_so_two_hashes_differ():
    assert security.hash_password(PW) != security.hash_password(PW)


def test_hash_uses_configured_cost(monkeypatch):
    monkeypatch.setenv("BCRYPT_COST", "5")
    assert security.hash_password(PW).startswith("$2b$05$")


def test_too_short_password_rejected():
    with pytest.raises(security.PasswordPolicyError):
        security.validate_new_password("Short-1")


def test_exactly_ten_chars_accepted():
    security.validate_new_password("Abcdefgh-1")


def test_72_byte_password_accepted_and_73_rejected():
    security.validate_new_password("Abc1" * 18)  # 72 bytes
    with pytest.raises(security.PasswordPolicyError):
        security.validate_new_password("Abc1" * 18 + "x")


def test_multibyte_password_over_72_bytes_rejected_even_if_few_characters():
    password = "\u00e9\u00e8\u00ea\u00eb" * 10  # 40 characters, 80 bytes
    assert len(password) < 72
    with pytest.raises(security.PasswordPolicyError):
        security.validate_new_password(password)


def test_repetitive_password_rejected():
    with pytest.raises(security.PasswordPolicyError):
        security.validate_new_password("aaaaaaaaaaaa")


def test_password_equal_to_email_rejected():
    with pytest.raises(security.PasswordPolicyError):
        security.validate_new_password("Dean@ppsu.example", email="dean@ppsu.example")


def test_verify_never_raises_on_garbage_hash():
    assert security.verify_password(PW, "not-a-bcrypt-hash") is False
    assert security.verify_password(PW, "") is False


def test_verify_overlong_password_is_false_not_error():
    assert security.verify_password("x" * 200, security.hash_password(PW)) is False


def test_temporary_password_meets_policy_and_is_random():
    a, b = security.generate_temporary_password(), security.generate_temporary_password()
    assert a != b
    assert len(a) == 14
    security.validate_new_password(a)
    assert not re.search(r"[0O1lI]", a)


# ---------------------------------------------------------------- access token
def test_access_token_roundtrip():
    uid = uuid.uuid4()
    token = security.create_access_token(uid, NOW)
    claims = security.decode_access_token(token)
    assert claims["sub"] == str(uid)
    assert claims["typ"] == "access"
    assert claims["pv"] == security.password_version(NOW)


def test_access_token_expires_after_configured_minutes(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_MINUTES", "10")
    claims = security.decode_access_token(security.create_access_token(uuid.uuid4(), NOW))
    assert claims["exp"] - claims["iat"] == 600


def test_expired_token_rejected():
    token = security.create_access_token(uuid.uuid4(), NOW, now=NOW - timedelta(hours=2))
    with pytest.raises(security.TokenError):
        security.decode_access_token(token)


def test_tampered_token_rejected():
    token = security.create_access_token(uuid.uuid4(), NOW)
    head, body, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    with pytest.raises(security.TokenError):
        security.decode_access_token(f"{head}.{body}.{flipped}")


def test_token_signed_with_other_secret_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access", "iat": int(NOW.timestamp()),
         "exp": int((NOW + timedelta(minutes=5)).timestamp()), "pv": 1},
        "some-other-secret-that-is-long-enough-12345", algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(forged)


def test_alg_none_token_rejected():
    payload = {"sub": str(uuid.uuid4()), "typ": "access", "iat": int(NOW.timestamp()),
               "exp": int((NOW + timedelta(minutes=5)).timestamp()), "pv": 1}
    unsigned = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(security.TokenError):
        security.decode_access_token(unsigned)


def test_wrong_token_type_rejected():
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "refresh", "iat": int(NOW.timestamp()),
         "exp": int((NOW + timedelta(minutes=5)).timestamp()), "pv": 1},
        settings.jwt_secret(), algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(token)


def test_token_without_expiry_rejected():
    token = jwt.encode({"sub": str(uuid.uuid4()), "typ": "access", "iat": 1, "pv": 1},
                       settings.jwt_secret(), algorithm="HS256")
    with pytest.raises(security.TokenError):
        security.decode_access_token(token)


def test_token_with_bad_subject_rejected():
    token = jwt.encode(
        {"sub": "not-a-uuid", "typ": "access", "iat": int(NOW.timestamp()),
         "exp": int((NOW + timedelta(minutes=5)).timestamp()), "pv": 1},
        settings.jwt_secret(), algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(token)


def test_garbage_string_is_not_a_token():
    with pytest.raises(security.TokenError):
        security.decode_access_token("not.a.jwt")


# ---------------------------------------------------------------- refresh token
def test_refresh_token_is_random_and_only_hash_matches():
    raw1, hash1 = security.new_refresh_token()
    raw2, hash2 = security.new_refresh_token()
    assert raw1 != raw2 and hash1 != hash2
    assert len(raw1) >= 60
    assert re.fullmatch(r"[0-9a-f]{64}", hash1)
    assert security.hash_refresh_token(raw1) == hash1
    assert raw1 != hash1


# ---------------------------------------------------------------- settings
def test_missing_jwt_secret_stops_the_app(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(SettingsError):
        settings.startup_checks()


def test_short_jwt_secret_stops_the_app(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(SettingsError):
        settings.startup_checks()


def test_low_bcrypt_cost_refused_outside_tests(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BCRYPT_COST", "4")
    with pytest.raises(SettingsError):
        settings.startup_checks()


def test_bcrypt_cost_out_of_range_is_an_error(monkeypatch):
    monkeypatch.setenv("BCRYPT_COST", "40")
    with pytest.raises(SettingsError):
        settings.bcrypt_cost()


def test_samesite_none_needs_secure(monkeypatch):
    monkeypatch.setenv("COOKIE_SAMESITE", "none")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with pytest.raises(SettingsError):
        settings.cookie_samesite()


def test_valid_setup_passes_startup_checks():
    settings.startup_checks()


def test_cors_origins_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example , http://b.example")
    assert settings.cors_origins() == ["http://a.example", "http://b.example"]
