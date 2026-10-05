"""
Fixtures and builders for the S3 API tests.

The API test client uses your rolled-back test connection, but wrapped so that
db.commit() and db.rollback() behave like the real thing for the handler:
  commit()   keeps the work so far (a SAVEPOINT is released and a new one opened)
  rollback() throws away the work since the last commit()
So "this failed login must be saved even though the answer is 401" is really tested.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core import security
from app.main import app
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401  (pytest fixtures)

PASSWORD = "Correct-Horse-42"
NEW_PASSWORD = "Another-Phrase-77"
_PASSWORD_HASH = None


def password_hash() -> str:
    global _PASSWORD_HASH
    if _PASSWORD_HASH is None:
        _PASSWORD_HASH = security.hash_password(PASSWORD)
    return _PASSWORD_HASH


class SavepointConn:
    def __init__(self, conn):
        self._c = conn
        self._n = 0
        self._open()

    def _open(self):
        self._n += 1
        self._name = f"api_sp_{self._n}"
        self._c.execute(f"SAVEPOINT {self._name}")

    def commit(self):
        self._c.execute(f"RELEASE SAVEPOINT {self._name}")
        self._open()

    def rollback(self):
        self._c.execute(f"ROLLBACK TO SAVEPOINT {self._name}")

    def __getattr__(self, name):
        return getattr(self._c, name)


@pytest.fixture
def db(pg):  # noqa: F811
    return pg


@pytest.fixture
def client(pg):  # noqa: F811
    wrapper = SavepointConn(pg)

    def _override():
        wrapper.commit()  # whatever the test set up before this request counts as already saved
        try:
            yield wrapper
        finally:
            wrapper.rollback()  # like the real get_db: unsaved work of this request is discarded

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def new_client(client):
    """Makes extra clients (own cookie jar each), all on the same test transaction."""
    return lambda: TestClient(app)


# ---------------------------------------------------------------- builders
def uid() -> str:
    return uuid.uuid4().hex[:10]


def make_department(conn, code: str | None = None) -> dict:
    code = code or f"D{uid()}"
    return conn.execute(
        "INSERT INTO departments (code, name) VALUES (%s, %s) RETURNING *", (code, f"Dept {code}")
    ).fetchone()


def make_user(conn, role: str, department_id=None, *, email=None, active=True, must_change=False,
              password_hash_value=None, employee_code=None) -> dict:
    email = email or f"{role.lower()}.{uid()}@example.edu"
    return conn.execute(
        """
        INSERT INTO users (email, password_hash, full_name, role, department_id, is_active,
                           must_change_password, employee_code)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
        """,
        (email, password_hash_value or password_hash(), f"{role.title()} {uid()}", role, department_id,
         active, must_change, employee_code),
    ).fetchone()


def make_semester(conn, year="2026-27", term="ODD", current=False) -> dict:
    return conn.execute(
        """
        INSERT INTO semesters (academic_year, term, start_date, end_date, is_current)
        VALUES (%s, %s, '2026-07-01', '2026-12-15', %s) RETURNING *
        """,
        (f"{year[:4]}-{year[-2:]}", term, current),
    ).fetchone()


def make_subject(conn, department_id, code=None) -> dict:
    code = code or f"S{uid()}"
    return conn.execute(
        "INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s, %s, %s, 'THEORY') RETURNING *",
        (code, f"Subject {code}", department_id),
    ).fetchone()


def make_course_file(conn, subject, semester, faculty, department_id=None, division=None) -> dict:
    return conn.execute(
        """
        INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id, division)
        VALUES (%s, %s, %s, %s, %s) RETURNING *
        """,
        (subject["id"], semester["id"], faculty["id"], department_id or faculty["department_id"], division),
    ).fetchone()


def login(client, user: dict, password: str = PASSWORD):
    return client.post("/auth/login", data={"username": user["email"], "password": password})


def token_for(client, user: dict, password: str = PASSWORD) -> str:
    resp = login(client, user, password)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def as_user(client, user: dict) -> dict:
    """Header for a user, logging in through the real endpoint."""
    return auth(token_for(client, user))


def audit_actions(conn, entity_id=None) -> list[str]:
    if entity_id is None:
        rows = conn.execute("SELECT action FROM audit_log ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT action FROM audit_log WHERE entity_id = %s ORDER BY id", (str(entity_id),)
        ).fetchall()
    return [r["action"] for r in rows]


@pytest.fixture
def world(pg):  # noqa: F811
    """Two departments, a Dean, HOD and two faculty in dept X, one HOD and faculty in dept Y, a semester."""
    w = {}
    w["x"] = make_department(pg, "X" + uid())
    w["y"] = make_department(pg, "Y" + uid())
    w["dean"] = make_user(pg, "DEAN")
    w["hod_x"] = make_user(pg, "HOD", w["x"]["id"])
    w["hod_y"] = make_user(pg, "HOD", w["y"]["id"])
    w["fac_x1"] = make_user(pg, "FACULTY", w["x"]["id"])
    w["fac_x2"] = make_user(pg, "FACULTY", w["x"]["id"])
    w["fac_y1"] = make_user(pg, "FACULTY", w["y"]["id"])
    w["sem"] = make_semester(pg, "2026-27", "ODD", current=False)
    w["sub_x"] = make_subject(pg, w["x"]["id"])
    w["sub_y"] = make_subject(pg, w["y"]["id"])
    w["cf_x1"] = make_course_file(pg, w["sub_x"], w["sem"], w["fac_x1"])
    w["cf_x2"] = make_course_file(pg, w["sub_x"], w["sem"], w["fac_x2"], division="B")
    w["cf_y1"] = make_course_file(pg, w["sub_y"], w["sem"], w["fac_y1"])
    return w
