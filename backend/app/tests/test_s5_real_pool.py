"""
S5 with the REAL connection pool and real commits: races between uploads and sweeps, the sweep lock,
the background scheduler and the command line tool. Committed rows stay in the test database, so every
test uses its own never-current semester, and the one test that needs a current semester switches it off again.
"""
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core import clock, pool as pool_module, rules, scheduler
from app.core.pool import get_pool
from app.main import app
from app.tests.api_fixtures import password_hash, uid
from app.tests.pg_fixtures import pg_url  # noqa: F401
from app.tests.s4_helpers import CSV
from app.tests.api_fixtures import world  # noqa: F401
from app.tests.s5_helpers import DAY, DUE, HOUR


@pytest.fixture
def real(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    pool_module.close_pool()
    created = {"semesters": []}
    with psycopg.connect(pg_url, autocommit=True, row_factory=dict_row) as admin:
        dep = admin.execute("INSERT INTO departments (code, name) VALUES (%s,%s) RETURNING id", (f"R{uid()}", f"Real {uid()}")).fetchone()
        mk = lambda role, d: admin.execute(  # noqa: E731
            "INSERT INTO users (email, password_hash, full_name, role, department_id) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (f"{role.lower()}.{uid()}@example.edu", password_hash(), f"{role} {uid()}", role, d)).fetchone()
        dean, fac = mk("DEAN", None), mk("FACULTY", dep["id"])
        year = random.randint(2100, 9000)
        sem = admin.execute("INSERT INTO semesters (academic_year, term, start_date, end_date) VALUES (%s,'ODD','2087-07-01','2087-12-01') RETURNING id",
                            (f"{year}-{(year + 1) % 100:02d}",)).fetchone()
        subj = admin.execute("INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s,'n',%s,'THEORY') RETURNING id", (f"R{uid()}", dep["id"])).fetchone()
        cf = admin.execute("INSERT INTO course_files (subject_id, semester_id, faculty_id, department_id) VALUES (%s,%s,%s,%s) RETURNING id",
                           (subj["id"], sem["id"], fac["id"], dep["id"])).fetchone()
        tpl = admin.execute("INSERT INTO checklist_templates (code, title, allowed_extensions) VALUES (%s,'t','{csv}') RETURNING id", (f"T{uid()}",)).fetchone()
        admin.execute("INSERT INTO checklist_deadlines (semester_id, template_id, due_at) VALUES (%s,%s,%s)", (sem["id"], tpl["id"], clock.utcnow() - DAY))
        subs = [admin.execute("INSERT INTO submissions (course_file_id, template_id) VALUES (%s,%s) RETURNING id", (cf["id"], tpl["id"])).fetchone()["id"]
                for _ in range(1)]
        token = TestClient(app).post("/auth/login", data={"username": dean["email"], "password": "Correct-Horse-42"}).json()["access_token"]
        ctx = {"url": pg_url, "admin": admin, "sem": sem["id"], "sub": subs[0], "headers": {"Authorization": f"Bearer {token}"}, "dean": dean}
        yield ctx
        admin.execute("UPDATE semesters SET is_current = false WHERE id = %s", (sem["id"],))
    pool_module.close_pool()


def open_flags(admin, sub, kind=None):
    q = "SELECT kind, status FROM flags WHERE submission_id = %s"
    a = [sub]
    if kind:
        q, a = q + " AND kind = %s", a + [kind]
    return admin.execute(q, a).fetchall()


def test_sweep_and_upload_at_the_same_moment_never_leave_a_stale_missing_flag(real):
    """The deadline is already past. An upload races a sweep: afterwards a file exists, so MISSING must not be open."""
    admin, sub, headers = real["admin"], real["sub"], real["headers"]
    admin.execute("UPDATE semesters SET is_current = false")
    admin.execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))

    def upload():
        return TestClient(app).post(f"/submissions/{sub}/versions", headers=headers, files={"file": ("a.csv", CSV)},
                                    data={"reason": "uploaded in a race test"})

    def do_sweep():
        with get_pool().connection() as db:
            return rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test")

    with ThreadPoolExecutor(4) as ex:
        futures = [ex.submit(do_sweep), ex.submit(upload), ex.submit(do_sweep), ex.submit(do_sweep)]
        results = [f.result() for f in futures]
    assert results[1].status_code == 201, results[1].text
    with get_pool().connection() as db:
        rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test")
    flags = open_flags(admin, sub)
    assert [f for f in flags if f["kind"] == "MISSING" and f["status"] == "OPEN"] == []
    assert len([f for f in flags if f["kind"] == "LATE"]) == 1 and len([f for f in flags if f["kind"] == "MISSING"]) <= 1


def test_many_parallel_sweeps_never_duplicate_a_flag(real):
    admin, sub = real["admin"], real["sub"]
    admin.execute("UPDATE semesters SET is_current = false")
    admin.execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))

    def do_sweep(_):
        with get_pool().connection() as db:
            return rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test")

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(do_sweep, range(6)))
    assert any(r is not None for r in results)
    assert len(open_flags(admin, sub, "MISSING")) == 1


def test_a_running_sweep_makes_the_second_one_answer_409(real):
    holder = psycopg.connect(real["url"], autocommit=True)
    try:
        holder.execute("SELECT pg_advisory_lock(%s)", (rules.SWEEP_LOCK_KEY,))
        r = TestClient(app).post("/rules/evaluate", headers=real["headers"])
        assert r.status_code == 409 and "already running" in r.json()["detail"]
        with get_pool().connection() as db:
            assert rules.sweep(db, now=clock.utcnow(), trigger="test") is None
    finally:
        holder.execute("SELECT pg_advisory_unlock(%s)", (rules.SWEEP_LOCK_KEY,))
        holder.close()
    assert TestClient(app).post("/rules/evaluate", headers=real["headers"]).status_code == 200      # lock released: runs again


def test_the_sweep_lock_is_released_even_when_the_sweep_fails(real, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database hiccup")

    original = rules.evaluate_many
    monkeypatch.setattr(rules, "evaluate_many", boom)
    admin = real["admin"]
    admin.execute("UPDATE semesters SET is_current = false")
    admin.execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))
    with pytest.raises(RuntimeError):
        with get_pool().connection() as db:
            rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test")
    monkeypatch.setattr(rules, "evaluate_many", original)
    with get_pool().connection() as db:
        assert rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test") is not None


def test_one_failing_item_does_not_stop_the_flags_already_saved(real, monkeypatch):
    admin = real["admin"]
    tpl2 = admin.execute("INSERT INTO checklist_templates (code, title, allowed_extensions) VALUES (%s,'t2','{csv}') RETURNING id", (f"T{uid()}",)).fetchone()
    cf = admin.execute("SELECT id FROM course_files WHERE semester_id = %s", (real["sem"],)).fetchone()
    admin.execute("INSERT INTO checklist_deadlines (semester_id, template_id, due_at) VALUES (%s,%s,%s)", (real["sem"], tpl2["id"], clock.utcnow() - DAY))
    second = admin.execute("INSERT INTO submissions (course_file_id, template_id) VALUES (%s,%s) RETURNING id", (cf["id"], tpl2["id"])).fetchone()["id"]
    first = real["sub"]
    admin.execute("UPDATE semesters SET is_current = false")
    admin.execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))
    original = rules.evaluate_many
    seen = []

    def flaky(db, ids, **kw):
        seen.append(ids[0])
        if len(seen) == 2:
            raise RuntimeError("second item exploded")
        return original(db, ids, **kw)

    monkeypatch.setattr(rules, "evaluate_many", flaky)
    with pytest.raises(RuntimeError):
        with get_pool().connection() as db:
            rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test")
    done = [s for s in (first, second) if open_flags(admin, s, "MISSING")]
    assert len(done) == 1                                        # the first item's flag was committed before the failure


# ------------------------------------------------------------ scheduler
def test_scheduler_is_off_in_tests_and_when_set_to_zero(monkeypatch):
    monkeypatch.setenv("RULES_SWEEP_MINUTES", "0")
    scheduler.start()
    assert scheduler._thread is None


def test_scheduler_runs_the_check_and_stops_cleanly(monkeypatch):
    calls = threading.Event()
    monkeypatch.setenv("RULES_SWEEP_MINUTES", "1")
    monkeypatch.setattr(scheduler, "FIRST_RUN_DELAY", 0)
    monkeypatch.setattr(scheduler, "run_once", lambda: calls.set())
    scheduler.start()
    try:
        assert calls.wait(5), "the scheduler never ran"
        assert scheduler._thread.is_alive()
        scheduler.start()                                         # a second start does nothing
    finally:
        scheduler.stop()
    assert scheduler._thread is None


def test_scheduler_survives_a_failing_check(monkeypatch):
    seen = []

    def flaky():
        seen.append(1)
        raise RuntimeError("database down")

    monkeypatch.setenv("RULES_SWEEP_MINUTES", "1")
    monkeypatch.setattr(scheduler, "FIRST_RUN_DELAY", 0)
    monkeypatch.setattr(scheduler, "run_once", flaky)
    scheduler.start()
    try:
        for _ in range(50):
            if seen:
                break
            threading.Event().wait(0.1)
        assert seen and scheduler._thread.is_alive()
    finally:
        scheduler.stop()


def test_scheduler_run_once_uses_the_real_pool(real):
    real["admin"].execute("UPDATE semesters SET is_current = false")
    real["admin"].execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))
    result = scheduler.run_once()
    assert result["raised"] == 1 and open_flags(real["admin"], real["sub"], "MISSING")
    row = real["admin"].execute("SELECT payload FROM audit_log WHERE action = 'rules.sweep' ORDER BY id DESC LIMIT 1").fetchone()
    assert row["payload"]["trigger"] == "schedule"


def test_api_startup_starts_the_scheduler_only_when_enabled(monkeypatch):
    started = []
    monkeypatch.setattr(scheduler, "start", lambda: started.append(1))
    monkeypatch.setattr(scheduler, "stop", lambda: started.append("stop"))
    with TestClient(app):
        pass
    assert started == [1, "stop"]


# ------------------------------------------------------------ command line
def test_cli_runs_one_check_and_reports(real, capsys):
    from app.core import evaluate

    real["admin"].execute("UPDATE semesters SET is_current = false")
    real["admin"].execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))
    assert evaluate.main() == 0
    assert "1 flags raised" in capsys.readouterr().out
    assert evaluate.main() == 0 and "0 flags raised" in capsys.readouterr().out      # second run: nothing new


def test_cli_reports_an_unreachable_database(monkeypatch, capsys):
    from app.core import evaluate

    pool_module.close_pool()
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    monkeypatch.setattr(pool_module, "OPEN_TIMEOUT", 1)
    assert evaluate.main() == 1
    assert "Could not run the check" in capsys.readouterr().err
    pool_module.close_pool()
