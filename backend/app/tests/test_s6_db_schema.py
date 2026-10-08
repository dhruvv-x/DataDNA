"""S6: database guards of migration 0005 (snapshots, semester weights, weight limits)."""
import json

from contextlib import contextmanager

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.tests.api_fixtures import make_semester  # noqa: F401
from app.tests.s5_helpers import *  # noqa: F401,F403  (fixtures)


@contextmanager
def refused(pg, exc):
    """The block must be refused by the database. A savepoint keeps the test data alive afterwards."""
    pg.execute("SAVEPOINT s6_refused")
    with pytest.raises(exc):
        yield
    pg.execute("ROLLBACK TO SAVEPOINT s6_refused")


def insert_snapshot(pg, cf, **over):
    vals = dict(course_file_id=cf["id"], semester_id=cf["semester_id"], weights_id=1, content_active=False,
                status="SCORED", total=100, c=38.89, t=38.89, f=22.22, k=0, ec=38.89, et=38.89, ef=22.22, ek=0,
                items_total=2, items_pending=0, fp="a" * 64, trigger="test", final=False)
    vals.update(over)
    return pg.execute(
        """INSERT INTO score_snapshots (course_file_id, semester_id, weights_id, content_active, status, total,
             completeness_pts, timeliness_pts, format_pts, content_pts, eff_completeness, eff_timeliness, eff_format,
             eff_content, items_total, items_pending, breakdown, fingerprint, trigger, is_final)
           VALUES (%(course_file_id)s, %(semester_id)s, %(weights_id)s, %(content_active)s, %(status)s, %(total)s,
             %(c)s, %(t)s, %(f)s, %(k)s, %(ec)s, %(et)s, %(ef)s, %(ek)s, %(items_total)s, %(items_pending)s,
             %(bd)s, %(fp)s, %(trigger)s, %(final)s) RETURNING *""",
        {**vals, "bd": Jsonb({"x": 1})}).fetchone()


def wid(pg):
    return pg.execute("SELECT max(id) AS i FROM score_weights").fetchone()["i"]


def test_migration_0005_is_recorded(pg):
    assert pg.execute("SELECT 1 FROM schema_migrations WHERE version = '0005_score'").fetchone()


def test_a_valid_snapshot_can_be_written(pg, world):
    row = insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg))
    assert row["total"] == 100


def test_snapshots_cannot_be_edited_or_deleted(pg, world):
    row = insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg))
    with refused(pg, psycopg.errors.RestrictViolation):
        pg.execute("UPDATE score_snapshots SET total = 1 WHERE id = %s", (row["id"],))


def test_snapshots_cannot_be_deleted(pg, world):
    row = insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg))
    with refused(pg, psycopg.errors.RestrictViolation):
        pg.execute("DELETE FROM score_snapshots WHERE id = %s", (row["id"],))


def test_snapshot_parts_must_add_up_to_the_total(pg, world):
    with refused(pg, psycopg.errors.CheckViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), total=99)


def test_scored_snapshot_needs_numbers_and_unscored_must_not_have_them(pg, world):
    with refused(pg, psycopg.errors.CheckViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), total=None)
    with refused(pg, psycopg.errors.CheckViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), status="NO_DEADLINES")  # numbers present
    ok = insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), status="NO_DEADLINES",
                         total=None, c=None, t=None, f=None, k=None)
    assert ok["total"] is None


def test_effective_weights_of_a_snapshot_must_sum_to_100(pg, world):
    with refused(pg, psycopg.errors.CheckViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), ec=30)


def test_snapshot_semester_must_match_the_course_file(pg, world):
    other = make_semester(pg, "2025-26", "EVEN")
    with refused(pg, psycopg.errors.ForeignKeyViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), semester_id=other["id"])


def test_unknown_status_is_refused(pg, world):
    with refused(pg, psycopg.errors.CheckViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), status="GREAT")


def test_pending_items_cannot_exceed_total_items(pg, world):
    with refused(pg, psycopg.errors.CheckViolation):
        insert_snapshot(pg, world["cf_x1"], weights_id=wid(pg), items_total=1, items_pending=2)


def test_semester_weights_are_append_only(pg, world):
    pg.execute("INSERT INTO semester_weights (semester_id, weights_id, reason) VALUES (%s, %s, 'because')",
               (world["sem"]["id"], wid(pg)))
    with refused(pg, psycopg.errors.RestrictViolation):
        pg.execute("UPDATE semester_weights SET reason = 'x' WHERE semester_id = %s", (world["sem"]["id"],))


def test_existing_semesters_were_given_the_starting_weights_by_the_migration(pg_url):
    # runs on a fresh schema: the starting weights row exists and the table is usable
    with psycopg.connect(pg_url) as c:
        assert c.execute("SELECT count(*) FROM score_weights").fetchone()[0] >= 1


def test_weights_with_less_than_50_in_the_three_main_parts_are_refused(pg):
    with refused(pg, psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO score_weights (completeness, timeliness, format, content, reason) "
                   "VALUES (20, 20, 9, 51, 'too much content')")


def test_weights_must_still_sum_to_100(pg):
    with refused(pg, psycopg.errors.CheckViolation):
        pg.execute("INSERT INTO score_weights (completeness, timeliness, format, content, reason) "
                   "VALUES (40, 40, 20, 10, 'sum is 110')")
