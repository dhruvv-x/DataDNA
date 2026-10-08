"""Fixtures and helpers for the S6 tests (score)."""
import pytest

from app.core import score_store
from app.tests.s5_helpers import *  # noqa: F401,F403
from app.tests.s5_helpers import DAY, DUE, HOUR, get, post, put, s5, sweep  # noqa: F401


@pytest.fixture
def s6(s5, pg):  # noqa: F811
    """The S5 world, with the semester already on its starting weights (as the real make-current does)."""
    score_store.ensure_semester_weights(pg, s5["sem"]["id"], reason="test setup")
    return s5


def score(client, who, cf):
    resp = get(client, who, f"/course-files/{cf['id']}/score")
    assert resp.status_code == 200, resp.text
    return resp.json()


def snaps(pg, cf):
    return pg.execute("SELECT * FROM score_snapshots WHERE course_file_id = %s ORDER BY id", (cf["id"],)).fetchall()


def item_of(body, sub):
    return next(i for i in body["items"] if i["submission_id"] == str(sub["id"]))


def put_weights(client, who, c, t, f, k, reason="recalibrated after the audit cycle", **extra):
    return post(client, who, "/score-weights", json={"completeness": c, "timeliness": t, "format": f, "content": k,
                                                     "reason": reason, **extra})
