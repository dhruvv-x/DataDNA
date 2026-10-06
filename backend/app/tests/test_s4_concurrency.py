"""
S4: uploads at the same moment, with the REAL connection pool and real commits.
They leave a few committed rows in the test database; it is wiped at the next test session.
The semester used is never "current", so these rows cannot disturb other tests.
"""
import random
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core import pool as pool_module, settings
from app.main import app
from app.tests.api_fixtures import password_hash, uid
from app.tests.pg_fixtures import pg_url  # noqa: F401
from app.tests.s4_helpers import CSV, stored_files


@pytest.fixture
def real(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    pool_module.close_pool()
    with psycopg.connect(pg_url, autocommit=True, row_factory=dict_row) as admin:
        dep = admin.execute("INSERT INTO departments (code, name) VALUES (%s,%s) RETURNING id", (f"C{uid()}", f"Conc {uid()}")).fetchone()
        mk = lambda role, d: admin.execute(  # noqa: E731
            "INSERT INTO users (email, password_hash, full_name, role, department_id) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (f"{role.lower()}.{uid()}@example.edu", password_hash(), f"{role} {uid()}", role, d)).fetchone()
        dean, fac = mk("DEAN", None), mk("FACULTY", dep["id"])
        year = random.randint(2100, 9000)   # a different, never-current semester for every test
        sem = admin.execute("INSERT INTO semesters (academic_year, term, start_date, end_date) VALUES (%s,'ODD','2087-07-01','2087-12-01') RETURNING id",
                            (f"{year}-{(year + 1) % 100:02d}",)).fetchone()
        subj = admin.execute("INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s,'n',%s,'THEORY') RETURNING id", (f"C{uid()}", dep["id"])).fetchone()
        cf = admin.execute("INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id) VALUES (%s,%s,%s,%s) RETURNING id",
                           (subj["id"], sem["id"], fac["id"], dep["id"])).fetchone()
        tpl = admin.execute("INSERT INTO checklist_templates (code, title, allowed_extensions) VALUES (%s,'t','{csv}') RETURNING id", (f"T{uid()}",)).fetchone()
        sub = admin.execute("INSERT INTO submissions (course_file_id, template_id) VALUES (%s,%s) RETURNING id", (cf["id"], tpl["id"])).fetchone()
        token = TestClient(app).post("/auth/login", data={"username": dean["email"], "password": "Correct-Horse-42"}).json()["access_token"]
        yield admin, sub["id"], {"Authorization": f"Bearer {token}"}
    pool_module.close_pool()


def push(sub_id, headers, data):
    c = TestClient(app)
    return c.post(f"/submissions/{sub_id}/versions", headers=headers,
                  files={"file": ("a.csv", data)}, data={"reason": "uploaded in a concurrency test"})


def test_simultaneous_different_uploads_get_distinct_version_numbers(real):
    admin, sub_id, headers = real
    payloads = [CSV + f"row{i},{i}\n".encode() for i in range(6)]
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda d: push(sub_id, headers, d), payloads))
    assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
    nos = sorted(r.json()["version_no"] for r in results)
    assert nos == [1, 2, 3, 4, 5, 6]
    rows = admin.execute("SELECT version_no, id FROM submission_versions WHERE submission_id=%s ORDER BY version_no", (sub_id,)).fetchall()
    assert [r["version_no"] for r in rows] == nos
    current = admin.execute("SELECT current_version_id FROM submissions WHERE id=%s", (sub_id,)).fetchone()["current_version_id"]
    assert current == rows[-1]["id"]                    # the last one in line is the current one
    assert len(stored_files(settings.storage_dir())) == 6


def test_simultaneous_identical_uploads_store_it_only_once(real):
    admin, sub_id, headers = real
    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(lambda _: push(sub_id, headers, CSV), range(2)))
    assert sorted(r.status_code for r in results) == [201, 409]
    assert admin.execute("SELECT count(*) AS n FROM submission_versions WHERE submission_id=%s", (sub_id,)).fetchone()["n"] == 1
    assert len(stored_files(settings.storage_dir())) == 1
