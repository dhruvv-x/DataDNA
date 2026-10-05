"""
S3 hardening, added after review:
  keyed hash for emails in the audit log, NUL/oversize input, cookie path setting, no-store headers,
  server-side password reset, the "last Dean" rule (including a real race), dev proxy config.
"""
import hashlib
import threading
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.auth import COOKIE_NAME, GENERIC_LOGIN_ERROR
from app.core import auditlog, security, settings
from app.core.reset_password import ResetError, main as reset_main, reset_user_password
from app.main import app
from app.tests.api_fixtures import (  # noqa: F401
    NEW_PASSWORD, PASSWORD, as_user, audit_actions, auth, client, db, login, make_department, make_user,
    new_client, password_hash, token_for, uid, world,
)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.test_s3_real_pool import real  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[3]


def faculty(db_):
    return make_user(db_, "FACULTY", make_department(db_)["id"])


# ---------------------------------------------------------------- audit email fingerprint
def test_email_fingerprint_is_not_a_plain_sha256():
    email = "someone@ppsu.example"
    assert auditlog.email_fingerprint(email) != hashlib.sha256(email.encode()).hexdigest()


def test_email_fingerprint_is_stable_and_ignores_case_and_spaces():
    a = auditlog.email_fingerprint("Someone@PPSU.example ")
    assert a == auditlog.email_fingerprint("someone@ppsu.example")
    assert len(a) == 64 and "someone" not in a


def test_email_fingerprint_depends_on_the_secret(monkeypatch):
    before = auditlog.email_fingerprint("someone@ppsu.example")
    monkeypatch.setenv("JWT_SECRET", "another-secret-" + "y" * 40)
    assert auditlog.email_fingerprint("someone@ppsu.example") != before


def test_unknown_email_audit_uses_the_keyed_hash(client, db):
    email = f"ghost{uid()}@example.edu"
    client.post("/auth/login", data={"username": email, "password": PASSWORD})
    row = db.execute("SELECT payload FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["payload"]["email_hmac"] == auditlog.email_fingerprint(email)
    assert "email_sha256" not in row["payload"]


# ---------------------------------------------------------------- NUL byte and oversize input
def test_login_with_nul_byte_email_is_a_plain_401_not_a_500(client, db):
    r = client.post("/auth/login", data={"username": "a\x00b@example.edu", "password": PASSWORD})
    assert r.status_code == 401 and r.json() == {"detail": GENERIC_LOGIN_ERROR}
    assert "LOGIN_FAILED" in audit_actions(db)


def test_login_with_oversized_email_is_a_plain_401(client):
    r = client.post("/auth/login", data={"username": "a" * 400 + "@example.edu", "password": PASSWORD})
    assert r.status_code == 401 and r.json() == {"detail": GENERIC_LOGIN_ERROR}


def test_nul_email_still_burns_a_bcrypt_check(client, monkeypatch):
    seen = []
    original = security.verify_password
    monkeypatch.setattr(security, "verify_password", lambda p, h: seen.append(h) or original(p, h))
    client.post("/auth/login", data={"username": "a\x00b@example.edu", "password": PASSWORD})
    assert seen == [security.dummy_hash()]


@pytest.mark.parametrize("field,value", [
    ("email", "a\x00b@example.edu"), ("full_name", "Bad\x00Name"), ("employee_code", "E\x0012"),
])
def test_create_user_rejects_nul_bytes(client, world, field, value):
    payload = {"email": f"ok{uid()}@example.edu", "full_name": "Fine Name", "role": "FACULTY",
               "department_id": str(world["x"]["id"]), "employee_code": "E1"}
    payload[field] = value
    r = client.post("/users", headers=as_user(client, world["dean"]), json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------- cookie path
def test_cookie_path_defaults_to_auth(client, db):
    r = login(client, faculty(db))
    assert "path=/auth" in r.headers["set-cookie"].lower()


def test_cookie_path_can_follow_a_proxy_prefix(client, db, monkeypatch):
    monkeypatch.setenv("COOKIE_PATH", "/api/auth")
    u = faculty(db)
    r = login(client, u)
    assert "path=/api/auth" in r.headers["set-cookie"].lower()
    raw = client.cookies.get(COOKIE_NAME)
    out = client.post("/auth/logout", headers={"Cookie": f"{COOKIE_NAME}={raw}"})
    assert "path=/api/auth" in out.headers["set-cookie"].lower()


@pytest.mark.parametrize("bad", ["auth", "/a b", "/a;b", "/a,b"])
def test_bad_cookie_path_stops_startup(monkeypatch, bad):
    monkeypatch.setenv("COOKIE_PATH", bad)
    with pytest.raises(settings.SettingsError):
        settings.startup_checks()


def test_blank_cookie_path_means_default(monkeypatch):
    monkeypatch.setenv("COOKIE_PATH", "  ")
    assert settings.cookie_path() == "/auth"


# ---------------------------------------------------------------- no-store
def test_account_responses_are_never_cacheable(client, world, db):
    dean = as_user(client, world["dean"])
    login_resp = login(client, faculty(db))
    me = client.get("/auth/me", headers=dean)
    users = client.get("/users", headers=dean)
    created = client.post("/users", headers=dean, json={
        "email": f"n{uid()}@example.edu", "full_name": "New", "role": "FACULTY",
        "department_id": str(world["x"]["id"])})
    reset = client.post(f"/users/{world['fac_x1']['id']}/reset-password", headers=dean)
    unauth = client.get("/auth/me")
    for resp in (login_resp, me, users, created, reset, unauth):
        assert resp.headers["cache-control"] == "no-store", resp.request.url


def test_health_is_not_marked_no_store(client):
    assert "cache-control" not in client.get("/health").headers


# ---------------------------------------------------------------- server-side password reset
class _FakeConn:
    def __init__(self, real_conn):
        self.real, self.committed, self.closed = real_conn, False, False

    def execute(self, *a, **k):
        return self.real.execute(*a, **k)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.real.rollback()

    def close(self):
        self.closed = True


def _answers(*values):
    it = iter(values)
    return lambda prompt: next(it)


def test_cli_reset_sets_password_unlocks_and_ends_sessions(pg, capsys):
    dean = make_user(pg, "DEAN")
    pg.execute("UPDATE users SET failed_login_count = 3, locked_until = now() + interval '1 hour', "
               "must_change_password = true WHERE id = %s", (dean["id"],))
    pg.execute("INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, now() + interval '1 day')",
               (dean["id"], hashlib.sha256(b"t").hexdigest()))
    fake = _FakeConn(pg)
    code = reset_main(["--email", dean["email"].upper()], getpass_fn=_answers(NEW_PASSWORD, NEW_PASSWORD),
                      connect_fn=lambda: fake)
    assert code == 0 and fake.committed and fake.closed
    row = pg.execute("SELECT * FROM users WHERE id = %s", (dean["id"],)).fetchone()
    assert security.verify_password(NEW_PASSWORD, row["password_hash"])
    assert not security.verify_password(PASSWORD, row["password_hash"])
    assert row["locked_until"] is None and row["failed_login_count"] == 0 and not row["must_change_password"]
    assert pg.execute("SELECT revoked_at FROM refresh_tokens WHERE user_id = %s", (dean["id"],)).fetchone()["revoked_at"]
    assert "Password updated" in capsys.readouterr().out


def test_cli_reset_old_access_token_stops_working(client, db):
    dean = make_user(db, "DEAN")
    header = as_user(client, dean)
    assert client.get("/auth/me", headers=header).status_code == 200
    reset_user_password(db, email=dean["email"], password=NEW_PASSWORD)
    assert client.get("/auth/me", headers=header).status_code == 401
    assert login(client, dean, NEW_PASSWORD).status_code == 200


def test_cli_reset_is_audited_without_the_password(pg):
    dean = make_user(pg, "DEAN")
    reset_user_password(pg, email=dean["email"], password=NEW_PASSWORD)
    row = pg.execute("SELECT * FROM audit_log WHERE action = 'PASSWORD_RESET' ORDER BY id DESC LIMIT 1").fetchone()
    assert row["entity_id"] == str(dean["id"]) and row["actor_id"] is None
    assert row["payload"] == {"via": "server_cli", "target_role": "DEAN"}
    assert NEW_PASSWORD not in str(dict(row))


def test_cli_reset_does_not_reactivate_an_inactive_user(pg):
    user = make_user(pg, "FACULTY", make_department(pg)["id"], active=False)
    reset_user_password(pg, email=user["email"], password=NEW_PASSWORD)
    assert pg.execute("SELECT is_active FROM users WHERE id = %s", (user["id"],)).fetchone()["is_active"] is False


def test_cli_reset_unknown_email_and_weak_password_are_refused(pg, capsys):
    with pytest.raises(ResetError, match="No user"):
        reset_user_password(pg, email="nobody@example.edu", password=NEW_PASSWORD)
    with pytest.raises(ResetError, match="No user"):
        reset_user_password(pg, email="a\x00b@example.edu", password=NEW_PASSWORD)
    dean = make_user(pg, "DEAN")
    with pytest.raises(ResetError, match="at least"):
        reset_user_password(pg, email=dean["email"], password="short")
    fake = _FakeConn(pg)
    assert reset_main(["--email", "nobody@example.edu"], getpass_fn=_answers(NEW_PASSWORD, NEW_PASSWORD),
                      connect_fn=lambda: fake) == 1
    assert not fake.committed and "No user" in capsys.readouterr().err


def test_cli_reset_password_mismatch_and_unreachable_db(pg, capsys):
    fake = _FakeConn(pg)
    assert reset_main(["--email", "x@example.edu"], getpass_fn=_answers(NEW_PASSWORD, NEW_PASSWORD + "x"),
                      connect_fn=lambda: fake) == 1
    assert not fake.committed and "do not match" in capsys.readouterr().err

    def boom():
        raise psycopg.OperationalError("connection refused")

    assert reset_main(["--email", "x@example.edu"], getpass_fn=_answers(NEW_PASSWORD, NEW_PASSWORD),
                      connect_fn=boom) == 1
    assert "cannot reach PostgreSQL" in capsys.readouterr().err


# ---------------------------------------------------------------- the last Dean
def test_dean_can_deactivate_another_dean_while_one_stays(client, world, db):
    other = make_user(db, "DEAN")
    r = client.patch(f"/users/{other['id']}/active", headers=as_user(client, world["dean"]), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False


def test_the_remaining_dean_cannot_deactivate_themselves(client, world, db):
    other = make_user(db, "DEAN")
    client.patch(f"/users/{other['id']}/active", headers=as_user(client, world["dean"]), json={"is_active": False})
    r = client.patch(f"/users/{world['dean']['id']}/active", headers=as_user(client, world["dean"]),
                     json={"is_active": False})
    assert r.status_code == 400


def test_two_deans_deactivating_each_other_at_once_never_leaves_nobody(real):
    """Run through the real pool with real threads. Without the row lock both requests could win."""
    client0, admin = real
    created = []
    try:
        for _ in range(8):
            # Only this round's two Deans may be active, otherwise the "another Dean remains" rule never bites.
            admin.execute("UPDATE users SET is_active = false WHERE role = 'DEAN' AND is_active")
            a, b = (admin.execute(
                """
                INSERT INTO users (email, password_hash, full_name, role, department_id)
                VALUES (%s, %s, 'Race Dean', 'DEAN', NULL) RETURNING id, email
                """, (f"race.{uid()}@example.edu", password_hash())).fetchone() for _ in range(2))
            created += [a["id"], b["id"]]
            tok = {}
            for who in (a, b):
                tok[who["id"]] = token_for(client0, who)
            barrier = threading.Barrier(2)
            statuses = []

            def attack(actor, victim):
                c = TestClient(app)
                barrier.wait()
                statuses.append(c.patch(f"/users/{victim['id']}/active", headers=auth(tok[actor["id"]]),
                                        json={"is_active": False}).status_code)

            threads = [threading.Thread(target=attack, args=(a, b)), threading.Thread(target=attack, args=(b, a))]
            [t.start() for t in threads]
            [t.join() for t in threads]
            still_active = admin.execute(
                "SELECT count(*) AS n FROM users WHERE id = ANY(%s) AND is_active", ([a["id"], b["id"]],)
            ).fetchone()["n"]
            assert statuses.count(200) == 1, statuses
            assert still_active == 1, statuses
    finally:
        if created:  # leave no active Deans behind for the other tests
            admin.execute("UPDATE users SET is_active = false WHERE id = ANY(%s)", (created,))


# ---------------------------------------------------------------- dev proxy for the cookie setup
def test_vite_dev_proxy_and_cookie_notes_exist():
    vite = (ROOT / "frontend" / "vite.config.ts").read_text()
    assert "proxy" in vite and "'/api'" in vite
    env = (ROOT / ".env.example").read_text()
    assert "COOKIE_PATH" in env and "/api/auth" in env
