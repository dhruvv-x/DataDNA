"""
S6 with the REAL connection pool and real commits: many writers at once must still leave one honest history.
(Same pattern as the S5 real-pool tests: committed rows stay in the test database, each test uses its own semester.)
"""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core import clock, rules, score_store
from app.core.pool import get_pool
from app.main import app
from app.tests.s4_helpers import CSV
from app.tests.api_fixtures import world  # noqa: F401
from app.tests.pg_fixtures import pg_url  # noqa: F401
from app.tests.test_s5_real_pool import real  # noqa: F401  (fixture)


def _cf(admin, sub):
    return admin.execute("SELECT course_file_id FROM submissions WHERE id = %s", (sub,)).fetchone()["course_file_id"]


def _snaps(admin, cf):
    return admin.execute("SELECT id, total, fingerprint, trigger FROM score_snapshots WHERE course_file_id = %s ORDER BY id",
                         (cf,)).fetchall()


def test_eight_refreshes_at_once_write_exactly_one_snapshot(real):
    cf = _cf(real["admin"], real["sub"])

    def refresh():
        with get_pool().connection() as db:
            out = score_store.refresh_course_files(db, [cf], trigger="race", now=clock.utcnow())
            db.commit()
            return out["written"]

    with ThreadPoolExecutor(8) as ex:
        written = [f.result() for f in [ex.submit(refresh) for _ in range(8)]]
    assert sum(written) == 1
    assert len(_snaps(real["admin"], cf)) == 1


def test_upload_racing_sweeps_ends_with_a_snapshot_equal_to_the_live_score(real):
    admin, sub, headers = real["admin"], real["sub"], real["headers"]
    cf = _cf(admin, sub)
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
        live = score_store.compute_many(db, [cf], clock.utcnow())[cf]
    rows = _snaps(admin, cf)
    assert rows, "the score changed, so there must be a snapshot"
    assert rows[-1]["fingerprint"] == live["fingerprint"]       # history ends exactly at the truth
    assert float(rows[-1]["total"]) == live["total"] == 61.11   # one item, late: Timeliness gone
    fingerprints = [r["fingerprint"] for r in rows]
    assert all(a != b for a, b in zip(fingerprints, fingerprints[1:]))  # never two equal snapshots in a row
