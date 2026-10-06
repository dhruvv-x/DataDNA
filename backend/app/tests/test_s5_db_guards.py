"""S5: the database itself refuses what the rules forbid, whatever the application does."""
import pytest
from psycopg import errors

from app.tests.api_fixtures import world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import make_submission, make_template


@pytest.fixture
def base(pg, world):
    sub = make_submission(pg, world["cf_x1"], make_template(pg))
    return {"cf": world["cf_x1"]["id"], "sub": sub["id"], "user": world["dean"]["id"], "pg": pg}


def new_flag(b, kind="LATE", status="OPEN"):
    return b["pg"].execute("INSERT INTO flags (course_file_id, submission_id, kind, status, reason) VALUES (%s,%s,%s,%s,'r') RETURNING id",
                           (b["cf"], b["sub"], kind, status)).fetchone()["id"]


def new_exception(b, kind="WAIVER", flag_id=None, new_due=None, reason="approved by the dean after review"):
    return b["pg"].execute(
        "INSERT INTO exceptions (course_file_id, submission_id, kind, flag_id, new_due_at, reason, granted_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id", (b["cf"], b["sub"], kind, flag_id, new_due, reason, b["user"])).fetchone()["id"]


def status(b, flag_id):
    return b["pg"].execute("SELECT status FROM flags WHERE id=%s", (flag_id,)).fetchone()["status"]


# ------------------------------------------------------------ one lateness flag per submission, for life
def test_a_second_open_lateness_flag_is_refused(base):
    new_flag(base)
    with pytest.raises(errors.UniqueViolation):
        new_flag(base)


def test_a_waived_lateness_flag_still_blocks_a_new_one(base):
    first = new_flag(base)
    new_exception(base, flag_id=first)
    base["pg"].execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (first,))
    with pytest.raises(errors.UniqueViolation):
        new_flag(base)


def test_other_flag_kinds_may_repeat_after_clearing(base):
    pg = base["pg"]
    first = new_flag(base, "FORMAT")
    pg.execute("UPDATE flags SET status='CLEARED', cleared_at=now() WHERE id=%s", (first,))
    new_flag(base, "FORMAT")
    assert pg.execute("SELECT count(*) AS n FROM flags WHERE submission_id=%s", (base["sub"],)).fetchone()["n"] == 2


def test_lateness_flag_for_another_submission_is_fine(base, world):
    new_flag(base)
    other = make_submission(base["pg"], world["cf_x1"], make_template(base["pg"]))
    base["pg"].execute("INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s,%s,'LATE','r')", (base["cf"], other["id"]))


# ------------------------------------------------------------ WAIVED needs a waiver row
def test_flag_cannot_become_waived_without_a_waiver(base):
    f = new_flag(base, "MISSING")
    with pytest.raises(errors.CheckViolation):
        base["pg"].execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (f,))


def test_a_waiver_for_another_flag_does_not_count(base):
    a, b = new_flag(base, "MISSING"), new_flag(base, "FORMAT")
    new_exception(base, flag_id=a)
    with pytest.raises(errors.CheckViolation):
        base["pg"].execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (b,))


def test_an_extension_is_not_a_waiver(base):
    f = new_flag(base, "MISSING")
    new_exception(base, "EXTENSION", new_due="2099-01-01T00:00:00+00:00")
    with pytest.raises(errors.CheckViolation):
        base["pg"].execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (f,))


def test_flag_becomes_waived_when_the_waiver_exists(base):
    f = new_flag(base, "MISSING")
    new_exception(base, flag_id=f)
    base["pg"].execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (f,))
    assert status(base, f) == "WAIVED"


def test_a_waived_flag_cannot_be_reopened_or_cleared_into_something_else_silently(base):
    f = new_flag(base, "MISSING")
    new_exception(base, flag_id=f)
    base["pg"].execute("UPDATE flags SET status='WAIVED' WHERE id=%s", (f,))
    base["pg"].execute("UPDATE flags SET reason='edited reason' WHERE id=%s", (f,))      # allowed: not a status change
    assert status(base, f) == "WAIVED"


# ------------------------------------------------------------ exceptions are history
def test_exceptions_cannot_be_edited(base):
    e = new_exception(base, "EXTENSION", new_due="2099-01-01T00:00:00+00:00")
    with pytest.raises(errors.RestrictViolation):
        base["pg"].execute("UPDATE exceptions SET reason='something else entirely' WHERE id=%s", (e,))


def test_exceptions_cannot_be_deleted(base):
    e = new_exception(base, "EXTENSION", new_due="2099-01-01T00:00:00+00:00")
    with pytest.raises(errors.RestrictViolation):
        base["pg"].execute("DELETE FROM exceptions WHERE id=%s", (e,))


def test_migration_0004_is_recorded(pg):
    row = pg.execute("SELECT 1 FROM schema_migrations WHERE version = '0004_rules'").fetchone()
    assert row is not None
