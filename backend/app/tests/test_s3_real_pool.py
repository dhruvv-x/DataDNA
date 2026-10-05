"""
S3: the few tests that use the REAL connection pool and the real get_db (no test wrapper).
They prove that "wrong password" is saved even though the answer is 401.
They leave a few committed rows behind in the test database; it is wiped at the next test session.
"""
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core import auditlog, pool as pool_module
from app.main import app
from app.tests.api_fixtures import PASSWORD, login, make_department, make_user, uid
from app.tests.pg_fixtures import pg_url  # noqa: F401


@pytest.fixture
def real(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    pool_module.close_pool()
    with psycopg.connect(pg_url, autocommit=True, row_factory=dict_row) as admin:
        yield TestClient(app), admin
    pool_module.close_pool()


def committed_faculty(admin):
    dep = admin.execute(
        "INSERT INTO departments (code, name) VALUES (%s, %s) RETURNING id", (f"R{uid()}", f"Real {uid()}")
    ).fetchone()
    from app.tests.api_fixtures import password_hash
    return admin.execute(
        """
        INSERT INTO users (email, password_hash, full_name, role, department_id)
        VALUES (%s, %s, 'Real Pool User', 'FACULTY', %s) RETURNING *
        """,
        (f"real.{uid()}@example.edu", password_hash(), dep["id"]),
    ).fetchone()


def test_failed_login_counter_survives_the_401(real):
    client, admin = real
    u = committed_faculty(admin)
    assert login(client, u, "Wrong-Password-1").status_code == 401
    assert login(client, u, "Wrong-Password-2").status_code == 401
    count = admin.execute("SELECT failed_login_count FROM users WHERE id = %s", (u["id"],)).fetchone()
    assert count["failed_login_count"] == 2
    actions = [r["action"] for r in admin.execute(
        "SELECT action FROM audit_log WHERE entity_id = %s ORDER BY id", (str(u["id"]),)).fetchall()]
    assert actions == ["LOGIN_FAILED", "LOGIN_FAILED"]


def test_unknown_email_audit_row_is_saved(real):
    client, admin = real
    email = f"ghost.{uid()}@example.edu"
    assert client.post("/auth/login", data={"username": email, "password": PASSWORD}).status_code == 401
    row = admin.execute(
        "SELECT action FROM audit_log WHERE payload->>'email_hmac' = %s", (auditlog.email_fingerprint(email),)
    ).fetchone()
    assert row["action"] == "LOGIN_FAILED"


def test_lockout_persists_across_requests(real):
    client, admin = real
    u = committed_faculty(admin)
    for i in range(5):
        login(client, u, f"Wrong-Password-{i}")
    assert login(client, u).status_code == 401  # correct password, still locked
    locked = admin.execute("SELECT locked_until FROM users WHERE id = %s", (u["id"],)).fetchone()
    assert locked["locked_until"] is not None


def test_full_session_with_real_pool(real):
    client, admin = real
    u = committed_faculty(admin)
    r = login(client, u)
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/auth/refresh").status_code == 200
    assert client.post("/auth/logout").status_code == 200
    assert client.post("/auth/refresh").status_code == 401


def test_forbidden_action_changes_nothing_with_real_pool(real):
    """A refused action leaves the target untouched."""
    client, admin = real
    u = committed_faculty(admin)
    token = login(client, u).json()["access_token"]
    other = committed_faculty(admin)
    r = client.patch(f"/users/{other['id']}/active", headers={"Authorization": f"Bearer {token}"},
                     json={"is_active": False})
    assert r.status_code == 403
    still = admin.execute("SELECT is_active FROM users WHERE id = %s", (other["id"],)).fetchone()
    assert still["is_active"] is True


def test_database_down_gives_503_not_a_crash(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/none")
    monkeypatch.setattr(pool_module, "OPEN_TIMEOUT", 1)
    pool_module.close_pool()
    try:
        r = TestClient(app).post("/auth/login", data={"username": "a@b.co", "password": PASSWORD})
        assert r.status_code == 503
        assert r.json()["detail"] == "Database is not available."
    finally:
        pool_module.close_pool()
