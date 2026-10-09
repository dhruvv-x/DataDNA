"""S7b: the demo data script. Real PostgreSQL, rolled back after every test."""
from datetime import date, datetime, timezone

import psycopg
import pytest

from app.core import seed_demo as sd
from app.tests.api_fixtures import client, db  # noqa: F401  (pytest fixtures)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401

NOW = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)


def count(db, table):
    return db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_creates_the_expected_data(db):
    result = sd.seed_demo(db, now=NOW)
    assert count(db, "departments") == 2
    assert count(db, "subjects") == 8
    assert count(db, "checklist_templates") == 19
    assert count(db, "course_files") == 8
    assert count(db, "users") == 6
    assert len(result["logins"]) == 6
    assert db.execute("SELECT count(*) AS n FROM semesters WHERE is_current").fetchone()["n"] == 1
    # every course file got its checklist rows up front
    assert count(db, "submissions") > 8 * 10


def test_semester_follows_the_calendar():
    assert sd.semester_dates(date(2026, 10, 8)) == ("2026-27", date(2026, 7, 1), date(2027, 1, 15))
    assert sd.semester_dates(date(2027, 3, 1)) == ("2026-27", date(2026, 7, 1), date(2027, 1, 15))
    assert sd.semester_dates(date(2099, 12, 31))[0] == "2099-00"


def test_passed_deadlines_raise_missing_flags_and_scores_exist(db):
    sd.seed_demo(db, now=NOW)
    missing = db.execute("SELECT count(*) AS n FROM flags WHERE kind = 'MISSING' AND status = 'OPEN'").fetchone()["n"]
    assert missing > 0
    snaps = db.execute("SELECT count(DISTINCT course_file_id) AS n FROM score_snapshots").fetchone()["n"]
    assert snaps == 8
    # a score only goes down when something is open: nothing is late (no file was uploaded)
    assert db.execute("SELECT count(*) AS n FROM flags WHERE kind = 'LATE'").fetchone()["n"] == 0


def test_printed_passwords_really_log_in(db, client):
    result = sd.seed_demo(db, now=NOW)
    for email, password, role in result["logins"]:
        res = client.post("/auth/login", data={"username": email, "password": password})
        assert res.status_code == 200, (email, res.text)
        assert res.json()["must_change_password"] is False
        assert res.json()["user"]["role"] == role


def test_hod_dashboard_is_filled_and_scoped(db, client):
    result = sd.seed_demo(db, now=NOW)
    email, password, _ = next(x for x in result["logins"] if x[0].startswith("hod.it"))
    token = client.post("/auth/login", data={"username": email, "password": password}).json()["access_token"]
    body = client.get("/scores", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["total"] == 4
    assert {r["department_code"] for r in body["scores"]} == {"IT"}
    assert all(r["total"] is not None and r["total"] < 100 for r in body["scores"])


def test_refuses_to_run_twice_and_changes_nothing(db):
    sd.seed_demo(db, now=NOW)
    before = (count(db, "departments"), count(db, "users"), count(db, "audit_log"))
    with pytest.raises(sd.DemoError):
        sd.seed_demo(db, now=NOW)
    assert (count(db, "departments"), count(db, "users"), count(db, "audit_log")) == before


def test_refuses_when_a_current_semester_exists(db):
    db.execute("INSERT INTO semesters (academic_year, term, start_date, end_date, is_current) "
               "VALUES ('2025-26', 'EVEN', '2026-01-01', '2026-06-30', true)")
    with pytest.raises(sd.DemoError):
        sd.seed_demo(db, now=NOW)
    assert count(db, "departments") == 0


def test_refuses_when_the_demo_departments_exist_even_without_a_current_semester(db):
    db.execute("INSERT INTO departments (code, name) VALUES ('IT', 'My real IT department')")
    with pytest.raises(sd.DemoError, match="already have data|already exist"):
        sd.seed_demo(db, now=NOW)
    assert count(db, "departments") == 1
    assert count(db, "users") == 0


def test_refuses_in_production(db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(sd.DemoError, match="production"):
        sd.seed_demo(db, now=NOW)
    assert count(db, "departments") == 0


def test_everything_is_audited_by_the_system(db):
    sd.seed_demo(db, now=NOW)
    rows = db.execute("SELECT DISTINCT actor_id, actor_role, payload->>'via' AS via FROM audit_log "
                      "WHERE payload->>'via' = 'seed_demo'").fetchall()
    assert [(r["actor_id"], r["actor_role"], r["via"]) for r in rows] == [(None, "SYSTEM", "seed_demo")]
    assert db.execute("SELECT count(*) AS n FROM audit_log WHERE action = 'course_file.create'").fetchone()["n"] == 8


def test_main_reports_a_database_that_is_down(capsys):
    def broken():
        raise psycopg.OperationalError("down")

    assert sd.main([], connect_fn=broken) == 1
    assert "cannot reach PostgreSQL" in capsys.readouterr().err
