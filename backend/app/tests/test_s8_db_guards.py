"""S8: the database itself refuses illegal moves on queries and steps (migration 0006), whatever the Python does."""
import pytest
from psycopg import errors

from app.tests.api_fixtures import world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401


def rejects(conn, exc, sql, params=()):
    """The statement must fail with `exc`. The failed statement is rolled back (savepoint)."""
    with pytest.raises(exc):
        with conn.transaction():
            conn.execute(sql, params)


def new_query(pg, w, level="HOD"):
    flag = pg.execute(
        "INSERT INTO flags (course_file_id, kind, reason) VALUES (%s, 'CONTENT', 'because') RETURNING id",
        (w["cf_x1"]["id"],)).fetchone()["id"]
    qid = pg.execute(
        "INSERT INTO queries (flag_id, raised_by, current_level) VALUES (%s, %s, %s) RETURNING id",
        (flag, w["fac_x1"]["id"], level)).fetchone()["id"]
    return flag, qid


def step(pg, qid, user, action="REPLY", role="FACULTY", level="HOD", outcome=None, override=False):
    return pg.execute(
        """INSERT INTO query_steps (query_id, actor_id, actor_role, level, action, message, outcome, override)
           VALUES (%s, %s, %s, %s, %s, 'some words here', %s, %s) RETURNING id""",
        (qid, user["id"], role, level, action, outcome, override)).fetchone()["id"]


def decide(pg, qid, by, status="RESOLVED_UPHELD", level="HOD"):
    pg.execute(
        "UPDATE queries SET status = %s, resolved_at = now(), resolved_by = %s, resolved_level = %s WHERE id = %s",
        (status, by["id"], level, qid))


# ---------------------------------------------------------------- steps are history
def test_a_step_can_never_be_changed_or_deleted(pg, world):
    _, qid = new_query(pg, world)
    sid = step(pg, qid, world["fac_x1"], "RAISE")
    rejects(pg, errors.RestrictViolation, "UPDATE query_steps SET message = 'edited later' WHERE id = %s", (sid,))
    rejects(pg, errors.RestrictViolation, "DELETE FROM query_steps WHERE id = %s", (sid,))


def test_steps_come_back_in_the_order_they_happened(pg, world):
    _, qid = new_query(pg, world)
    ids = [step(pg, qid, world["fac_x1"], a) for a in ("RAISE", "REPLY", "REPLY")]
    rows = pg.execute("SELECT id FROM query_steps WHERE query_id = %s ORDER BY seq", (qid,)).fetchall()
    assert [r["id"] for r in rows] == ids


def test_only_a_resolve_step_carries_an_outcome(pg, world):
    _, qid = new_query(pg, world)
    rejects(pg, errors.CheckViolation,
            """INSERT INTO query_steps (query_id, actor_id, actor_role, level, action, message, outcome)
               VALUES (%s, %s, 'HOD', 'HOD', 'REPLY', 'some words here', 'UPHELD')""", (qid, world["hod_x"]["id"]))
    rejects(pg, errors.CheckViolation,
            """INSERT INTO query_steps (query_id, actor_id, actor_role, level, action, message)
               VALUES (%s, %s, 'HOD', 'HOD', 'RESOLVE', 'some words here')""", (qid, world["hod_x"]["id"]))
    step(pg, qid, world["hod_x"], "RESOLVE", "HOD", outcome="UPHELD")


def test_only_the_dean_can_override(pg, world):
    _, qid = new_query(pg, world)
    rejects(pg, errors.CheckViolation,
            """INSERT INTO query_steps (query_id, actor_id, actor_role, level, action, message, override)
               VALUES (%s, %s, 'HOD', 'HOD', 'REPLY', 'some words here', true)""", (qid, world["hod_x"]["id"]))
    step(pg, qid, world["dean"], "REPLY", "DEAN", override=True)


def test_appeal_is_a_known_step_action(pg, world):
    _, qid = new_query(pg, world)
    step(pg, qid, world["fac_x1"], "APPEAL")


# ---------------------------------------------------------------- queries only move legally
def test_a_query_is_never_deleted(pg, world):
    _, qid = new_query(pg, world)
    rejects(pg, errors.RestrictViolation, "DELETE FROM queries WHERE id = %s", (qid,))


def test_a_flag_has_one_query_for_life_even_after_it_is_decided(pg, world):
    flag, qid = new_query(pg, world)
    decide(pg, qid, world["hod_x"])
    rejects(pg, errors.UniqueViolation,
            "INSERT INTO queries (flag_id, raised_by) VALUES (%s, %s)", (flag, world["fac_x1"]["id"]))


def test_flag_and_author_of_a_query_never_change(pg, world):
    flag, qid = new_query(pg, world)
    other = pg.execute(
        "INSERT INTO flags (course_file_id, kind, reason) VALUES (%s, 'CONTENT', 'other') RETURNING id",
        (world["cf_x1"]["id"],)).fetchone()["id"]
    rejects(pg, errors.RestrictViolation, "UPDATE queries SET flag_id = %s WHERE id = %s", (other, qid))
    rejects(pg, errors.RestrictViolation,
            "UPDATE queries SET raised_by = %s WHERE id = %s", (world["fac_x2"]["id"], qid))


def test_escalation_goes_hod_to_dean_and_never_back(pg, world):
    _, qid = new_query(pg, world)
    pg.execute("UPDATE queries SET current_level = 'DEAN' WHERE id = %s", (qid,))
    rejects(pg, errors.RestrictViolation, "UPDATE queries SET current_level = 'HOD' WHERE id = %s", (qid,))


def test_a_decision_does_not_change_level_or_appeal(pg, world):
    _, qid = new_query(pg, world)
    rejects(pg, errors.RestrictViolation,
            """UPDATE queries SET status = 'RESOLVED_UPHELD', current_level = 'DEAN', resolved_at = now(),
                   resolved_by = %s, resolved_level = 'DEAN' WHERE id = %s""", (world["dean"]["id"], qid))


def test_a_decision_names_who_decided(pg, world):
    _, qid = new_query(pg, world)
    rejects(pg, errors.CheckViolation,
            "UPDATE queries SET status = 'RESOLVED_UPHELD', resolved_at = now() WHERE id = %s", (qid,))


def test_an_open_query_carries_no_decision(pg, world):
    _, qid = new_query(pg, world)
    rejects(pg, errors.CheckViolation,
            "UPDATE queries SET resolved_by = %s, resolved_level = 'HOD' WHERE id = %s", (world["hod_x"]["id"], qid))


def test_dean_decision_is_final(pg, world):
    _, qid = new_query(pg, world, level="DEAN")
    decide(pg, qid, world["dean"], "RESOLVED_UPHELD", "DEAN")
    rejects(pg, errors.RestrictViolation, "UPDATE queries SET status = 'RESOLVED_OVERTURNED' WHERE id = %s", (qid,))
    rejects(pg, errors.RestrictViolation,
            "UPDATE queries SET status = 'OPEN', current_level = 'DEAN', appealed = true, resolved_at = NULL, "
            "resolved_by = NULL, resolved_level = NULL WHERE id = %s", (qid,))


def test_overturned_stays_overturned(pg, world):
    _, qid = new_query(pg, world)
    decide(pg, qid, world["hod_x"], "RESOLVED_OVERTURNED", "HOD")
    rejects(pg, errors.RestrictViolation, "UPDATE queries SET status = 'RESOLVED_UPHELD' WHERE id = %s", (qid,))
    rejects(pg, errors.RestrictViolation,
            "UPDATE queries SET status = 'OPEN', current_level = 'DEAN', appealed = true, resolved_at = NULL, "
            "resolved_by = NULL, resolved_level = NULL WHERE id = %s", (qid,))


def test_one_appeal_after_a_hod_upheld_and_only_one(pg, world):
    _, qid = new_query(pg, world)
    decide(pg, qid, world["hod_x"], "RESOLVED_UPHELD", "HOD")
    reopen = ("UPDATE queries SET status = 'OPEN', current_level = 'DEAN', appealed = true, resolved_at = NULL, "
              "resolved_by = NULL, resolved_level = NULL WHERE id = %s")
    # the appeal must go to the Dean and be marked as an appeal
    rejects(pg, errors.RestrictViolation,
            "UPDATE queries SET status = 'OPEN', current_level = 'HOD', resolved_at = NULL, resolved_by = NULL, "
            "resolved_level = NULL WHERE id = %s", (qid,))
    pg.execute(reopen, (qid,))
    decide(pg, qid, world["dean"], "RESOLVED_UPHELD", "DEAN")
    rejects(pg, errors.RestrictViolation, reopen, (qid,))


def test_an_appeal_cannot_be_taken_back(pg, world):
    _, qid = new_query(pg, world)
    decide(pg, qid, world["hod_x"], "RESOLVED_UPHELD", "HOD")
    pg.execute("UPDATE queries SET status = 'OPEN', current_level = 'DEAN', appealed = true, resolved_at = NULL, "
               "resolved_by = NULL, resolved_level = NULL WHERE id = %s", (qid,))
    rejects(pg, errors.RestrictViolation, "UPDATE queries SET appealed = false WHERE id = %s", (qid,))
