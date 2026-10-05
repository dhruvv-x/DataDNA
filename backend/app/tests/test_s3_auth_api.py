"""S3: login, lockout, refresh rotation, logout, change password, access control basics."""
import hashlib
from datetime import timedelta

import pytest

from app.core import auditlog, clock, security
from app.api.auth import COOKIE_NAME, GENERIC_LOGIN_ERROR
from app.tests.api_fixtures import (  # noqa: F401
    NEW_PASSWORD, PASSWORD, as_user, audit_actions, auth, client, db, login, make_course_file,
    make_department, make_user, new_client, token_for, uid, world,
)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401


def faculty(db_):
    return make_user(db_, "FACULTY", make_department(db_)["id"])


def new_client_for(client):
    return client.__class__(client.app)


def refresh_with(c, raw):
    """Send a specific refresh cookie value (bypasses the client's cookie jar)."""
    return c.post("/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={raw}"})


def user_row(db_, user_id):
    return db_.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def jump(monkeypatch, **delta):
    real = clock.utcnow
    monkeypatch.setattr(clock, "utcnow", lambda: real() + timedelta(**delta))


# ---------------------------------------------------------------- login
def test_login_success_shape(client, db):
    u = faculty(db)
    r = login(client, u)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["must_change_password"] is False
    assert body["user"]["email"] == u["email"] and body["user"]["role"] == "FACULTY"
    assert "password" not in r.text.lower().replace("must_change_password", "")


def test_refresh_token_is_only_in_cookie_not_in_body(client, db):
    r = login(client, faculty(db))
    raw = client.cookies.get(COOKIE_NAME)
    assert raw and raw not in r.text
    assert "refresh" not in r.json()


def test_cookie_flags(client, db):
    r = login(client, faculty(db))
    header = r.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in header
    assert "httponly" in header
    assert "path=/auth" in header
    assert "samesite=lax" in header
    assert "; secure" not in header
    assert f"max-age={7 * 86400}" in header


def test_cookie_is_secure_when_configured(client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    r = login(client, faculty(db))
    assert "; secure" in r.headers["set-cookie"].lower()


def test_refresh_token_stored_only_as_hash(client, db):
    u = faculty(db)
    login(client, u)
    raw = client.cookies.get(COOKIE_NAME)
    row = db.execute("SELECT * FROM refresh_tokens WHERE user_id = %s", (u["id"],)).fetchone()
    assert row["token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in str(dict(row))


def test_email_is_case_and_space_insensitive(client, db):
    u = faculty(db)
    r = client.post("/auth/login", data={"username": "  " + u["email"].upper() + " ", "password": PASSWORD})
    assert r.status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client, db):
    u = faculty(db)
    wrong = login(client, u, "Not-The-Password-1")
    unknown = client.post("/auth/login", data={"username": f"nobody{uid()}@example.edu", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": GENERIC_LOGIN_ERROR}


def test_unknown_email_still_burns_a_bcrypt_check(client, monkeypatch):
    seen = []
    real = security.verify_password
    monkeypatch.setattr(security, "verify_password", lambda p, h: seen.append(h) or real(p, h))
    client.post("/auth/login", data={"username": f"ghost{uid()}@example.edu", "password": PASSWORD})
    assert seen == [security.dummy_hash()]


def test_inactive_user_cannot_login_even_with_right_password(client, db):
    u = make_user(db, "FACULTY", make_department(db)["id"], active=False)
    r = login(client, u)
    assert r.status_code == 401 and r.json() == {"detail": GENERIC_LOGIN_ERROR}


def test_missing_form_fields_is_422(client):
    assert client.post("/auth/login", data={"username": "a@b.co"}).status_code == 422


def test_failed_attempt_is_counted_and_kept_despite_401(client, db):
    u = faculty(db)
    assert login(client, u, "Wrong-Password-1").status_code == 401
    assert user_row(db, u["id"])["failed_login_count"] == 1
    assert login(client, u, "Wrong-Password-2").status_code == 401
    assert user_row(db, u["id"])["failed_login_count"] == 2


def test_success_resets_the_counter_and_sets_last_login(client, db):
    u = faculty(db)
    login(client, u, "Wrong-Password-1")
    login(client, u, "Wrong-Password-2")
    assert login(client, u).status_code == 200
    row = user_row(db, u["id"])
    assert row["failed_login_count"] == 0 and row["last_login_at"] is not None


def test_account_locks_after_five_wrong_passwords(client, db):
    u = faculty(db)
    for i in range(5):
        assert login(client, u, f"Wrong-Password-{i}").status_code == 401
    row = user_row(db, u["id"])
    assert row["locked_until"] is not None and row["failed_login_count"] == 0
    assert "ACCOUNT_LOCKED" in audit_actions(db, u["id"])


def test_four_wrong_passwords_do_not_lock(client, db):
    u = faculty(db)
    for i in range(4):
        login(client, u, f"Wrong-Password-{i}")
    assert login(client, u).status_code == 200


def test_correct_password_is_refused_while_locked_with_same_message(client, db):
    u = faculty(db)
    for i in range(5):
        login(client, u, f"Wrong-Password-{i}")
    r = login(client, u)
    assert r.status_code == 401 and r.json() == {"detail": GENERIC_LOGIN_ERROR}
    assert "LOGIN_BLOCKED" in audit_actions(db, u["id"])


def test_more_attempts_while_locked_do_not_extend_the_lock(client, db):
    u = faculty(db)
    for i in range(5):
        login(client, u, f"Wrong-Password-{i}")
    first = user_row(db, u["id"])["locked_until"]
    login(client, u, "Wrong-Again-12")
    assert user_row(db, u["id"])["locked_until"] == first


def test_lock_expires_after_fifteen_minutes(client, db, monkeypatch):
    u = faculty(db)
    for i in range(5):
        login(client, u, f"Wrong-Password-{i}")
    jump(monkeypatch, minutes=14)
    assert login(client, u).status_code == 401
    jump(monkeypatch, minutes=16)
    assert login(client, u).status_code == 200
    row = user_row(db, u["id"])
    assert row["locked_until"] is None and row["failed_login_count"] == 0


def test_lockout_is_per_account(client, db):
    a, b = faculty(db), faculty(db)
    for i in range(5):
        login(client, a, f"Wrong-Password-{i}")
    assert login(client, b).status_code == 200


def test_login_events_are_audited_without_secrets(client, db):
    u = faculty(db)
    login(client, u, "Wrong-Password-1")
    login(client, u)
    assert audit_actions(db, u["id"]) == ["LOGIN_FAILED", "LOGIN_SUCCESS"]
    blob = " ".join(str(dict(r)) for r in db.execute("SELECT * FROM audit_log").fetchall())
    assert PASSWORD not in blob and "Wrong-Password-1" not in blob


def test_unknown_email_audit_has_no_actor_and_no_raw_email(client, db):
    email = f"ghost{uid()}@example.edu"
    client.post("/auth/login", data={"username": email, "password": PASSWORD})
    row = db.execute(
        "SELECT * FROM audit_log WHERE payload->>'email_hmac' = %s", (auditlog.email_fingerprint(email),)
    ).fetchone()
    assert row["action"] == "LOGIN_FAILED" and row["actor_id"] is None
    assert email not in str(dict(row))


# ---------------------------------------------------------------- /auth/me and access tokens
def test_me_returns_profile(client, db):
    u = faculty(db)
    r = client.get("/auth/me", headers=as_user(client, u))
    assert r.status_code == 200
    assert r.json()["email"] == u["email"] and r.json()["role"] == "FACULTY"
    assert r.json()["department_id"] == str(u["department_id"])


def test_me_without_token_is_401(client):
    r = client.get("/auth/me")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_garbage_and_wrong_scheme_tokens_are_401(client):
    assert client.get("/auth/me", headers=auth("garbage")).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_expired_access_token_is_401(client, db):
    u = faculty(db)
    old = clock.utcnow() - timedelta(hours=2)
    token = security.create_access_token(u["id"], u["password_changed_at"], now=old)
    assert client.get("/auth/me", headers=auth(token)).status_code == 401


def test_token_for_deleted_or_unknown_user_is_401(client, db):
    import uuid
    token = security.create_access_token(uuid.uuid4(), clock.utcnow())
    assert client.get("/auth/me", headers=auth(token)).status_code == 401


def test_deactivated_user_token_stops_working_immediately(client, db):
    u = faculty(db)
    headers = as_user(client, u)
    assert client.get("/auth/me", headers=headers).status_code == 200
    db.execute("UPDATE users SET is_active = false WHERE id = %s", (u["id"],))
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_role_comes_from_database_not_from_token(client, world, db):
    headers = as_user(client, world["hod_x"])
    assert client.get("/users", headers=headers).status_code == 200
    db.execute("UPDATE users SET role = 'FACULTY' WHERE id = %s", (world["hod_x"]["id"],))
    assert client.get("/users", headers=headers).status_code == 403


def test_openapi_exposes_login_for_the_authorize_button(client):
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert any(s.get("flows", {}).get("password", {}).get("tokenUrl") == "auth/login" for s in schemes.values())


# ---------------------------------------------------------------- must change password
def test_temporary_password_account_is_limited_until_changed(client, db):
    dep = make_department(db)
    u = make_user(db, "FACULTY", dep["id"], must_change=True)
    r = login(client, u)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    headers = auth(r.json()["access_token"])
    assert client.get("/auth/me", headers=headers).json()["must_change_password"] is True
    blocked = client.get("/course-files", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "Password change required."
    assert client.get("/users", headers=headers).status_code == 403

    changed = client.post("/auth/change-password", headers=headers,
                          json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    assert client.get("/course-files", headers=auth(changed.json()["access_token"])).status_code == 200


# ---------------------------------------------------------------- refresh
def test_refresh_gives_new_access_token_and_rotates_cookie(client, db):
    u = faculty(db)
    login(client, u)
    first = client.cookies.get(COOKIE_NAME)
    r = client.post("/auth/refresh")
    assert r.status_code == 200
    second = client.cookies.get(COOKIE_NAME)
    assert second and second != first
    assert client.get("/auth/me", headers=auth(r.json()["access_token"])).status_code == 200
    used = db.execute(
        "SELECT used_at FROM refresh_tokens WHERE token_hash = %s", (security.hash_refresh_token(first),)
    ).fetchone()
    assert used["used_at"] is not None


def test_refresh_without_cookie_is_401(client):
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_with_unknown_cookie_is_401_and_clears_it(client):
    r = client.post("/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}=made-up-value"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Session expired. Please log in again."
    assert "max-age=0" in r.headers["set-cookie"].lower()


def test_reusing_an_old_refresh_token_logs_the_user_out_everywhere(client, new_client, db):
    u = faculty(db)
    login(client, u)
    stolen = client.cookies.get(COOKIE_NAME)
    assert client.post("/auth/refresh").status_code == 200
    newest = client.cookies.get(COOKIE_NAME)

    attacker = new_client()
    assert refresh_with(attacker, stolen).status_code == 401
    assert "REFRESH_REUSE_DETECTED" in audit_actions(db, u["id"])
    # the legitimate newest token is dead too
    assert refresh_with(new_client(), newest).status_code == 401
    open_tokens = db.execute(
        "SELECT count(*) AS n FROM refresh_tokens WHERE user_id = %s AND revoked_at IS NULL AND used_at IS NULL",
        (u["id"],),
    ).fetchone()["n"]
    assert open_tokens == 0


def test_refresh_still_works_just_before_seven_days(client, db, monkeypatch):
    login(client, faculty(db))
    raw = client.cookies.get(COOKIE_NAME)
    jump(monkeypatch, days=6, hours=23)
    assert refresh_with(new_client_for(client), raw).status_code == 200


def test_expired_refresh_token_is_401(client, db, monkeypatch):
    login(client, faculty(db))
    raw = client.cookies.get(COOKIE_NAME)
    jump(monkeypatch, days=8)
    r = refresh_with(new_client_for(client), raw)
    assert r.status_code == 401


def test_refresh_for_deactivated_user_is_401_and_revokes_all(client, db):
    u = faculty(db)
    login(client, u)
    raw = client.cookies.get(COOKIE_NAME)
    db.execute("UPDATE users SET is_active = false WHERE id = %s", (u["id"],))
    assert refresh_with(new_client_for(client), raw).status_code == 401
    n = db.execute(
        "SELECT count(*) AS n FROM refresh_tokens WHERE user_id = %s AND revoked_at IS NULL", (u["id"],)
    ).fetchone()["n"]
    assert n == 0


# ---------------------------------------------------------------- logout
def test_logout_revokes_token_and_clears_cookie(client, db):
    u = faculty(db)
    login(client, u)
    raw = client.cookies.get(COOKIE_NAME)
    r = client.post("/auth/logout")
    assert r.status_code == 200 and "max-age=0" in r.headers["set-cookie"].lower()
    row = db.execute(
        "SELECT revoked_at FROM refresh_tokens WHERE token_hash = %s", (security.hash_refresh_token(raw),)
    ).fetchone()
    assert row["revoked_at"] is not None
    assert refresh_with(new_client_for(client), raw).status_code == 401
    assert "LOGOUT" in audit_actions(db, u["id"])


def test_logout_after_logout_is_not_an_attack(client, db):
    u = faculty(db)
    login(client, u)
    raw = client.cookies.get(COOKIE_NAME)
    client.post("/auth/logout")
    refresh_with(new_client_for(client), raw)
    assert "REFRESH_REUSE_DETECTED" not in audit_actions(db, u["id"])


def test_logout_without_cookie_is_fine(client):
    assert client.post("/auth/logout").status_code == 200


def test_logout_only_ends_this_session(client, new_client, db):
    u = faculty(db)
    phone, laptop = new_client(), new_client()
    login(phone, u)
    login(laptop, u)
    phone.post("/auth/logout")
    assert laptop.post("/auth/refresh").status_code == 200


# ---------------------------------------------------------------- change password
def test_change_password_success(client, db):
    u = faculty(db)
    headers = as_user(client, u)
    old_hash = user_row(db, u["id"])["password_hash"]
    r = client.post("/auth/change-password", headers=headers,
                    json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    row = user_row(db, u["id"])
    assert row["password_hash"] != old_hash and security.verify_password(NEW_PASSWORD, row["password_hash"])
    assert login(client, u).status_code == 401
    assert login(client, u, NEW_PASSWORD).status_code == 200
    assert "PASSWORD_CHANGED" in audit_actions(db, u["id"])


def test_change_password_kills_old_access_token_and_other_devices(client, new_client, db):
    u = faculty(db)
    other = new_client()
    login(other, u)
    other_cookie = other.cookies.get(COOKIE_NAME)
    old_headers = as_user(client, u)
    r = client.post("/auth/change-password", headers=old_headers,
                    json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert client.get("/auth/me", headers=old_headers).status_code == 401
    assert refresh_with(new_client(), other_cookie).status_code == 401
    # this device stays logged in with the new tokens
    assert client.get("/auth/me", headers=auth(r.json()["access_token"])).status_code == 200
    assert client.post("/auth/refresh").status_code == 200


def test_change_password_wrong_current_is_400_and_counts_as_failure(client, db):
    u = faculty(db)
    headers = as_user(client, u)
    r = client.post("/auth/change-password", headers=headers,
                    json={"current_password": "Wrong-Current-1", "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert user_row(db, u["id"])["failed_login_count"] == 1
    assert security.verify_password(PASSWORD, user_row(db, u["id"])["password_hash"])


def test_change_password_locks_after_repeated_wrong_current(client, db):
    u = faculty(db)
    headers = as_user(client, u)
    body = {"current_password": "Wrong-Current-1", "new_password": NEW_PASSWORD}
    for _ in range(5):
        assert client.post("/auth/change-password", headers=headers, json=body).status_code == 400
    right = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert client.post("/auth/change-password", headers=headers, json=right).status_code == 429


def test_change_password_rejects_weak_new_password(client, db):
    headers = as_user(client, faculty(db))
    r = client.post("/auth/change-password", headers=headers,
                    json={"current_password": PASSWORD, "new_password": "short"})
    assert r.status_code == 422


def test_change_password_rejects_same_password(client, db):
    headers = as_user(client, faculty(db))
    r = client.post("/auth/change-password", headers=headers,
                    json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert r.status_code == 400


def test_change_password_needs_login(client):
    r = client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 401


def test_passwords_never_appear_in_audit_log(client, db):
    u = faculty(db)
    headers = as_user(client, u)
    client.post("/auth/change-password", headers=headers,
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    blob = " ".join(str(dict(r)) for r in db.execute("SELECT * FROM audit_log").fetchall())
    assert PASSWORD not in blob and NEW_PASSWORD not in blob


# ---------------------------------------------------------------- CORS
def test_cors_allows_frontend_origin_with_credentials(client):
    r = client.options("/auth/login", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_other_origins(client):
    r = client.options("/auth/login", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in r.headers
