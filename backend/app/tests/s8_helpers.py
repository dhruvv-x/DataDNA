"""Fixtures and helpers for the S8 tests (queries)."""
import pytest

from app.tests.s6_helpers import *  # noqa: F401,F403
from app.tests.s6_helpers import DAY, DUE, HOUR, get, post, put, s6, score, snaps, sweep  # noqa: F401
from app.tests.s5_helpers import flags_of

LATE_AT = DUE + DAY
MSG = "please look again, the file reached the portal on time"


@pytest.fixture
def s8(s6, client, clk, pg):  # noqa: F811
    """
    The S6 world after the deadline:
      late        LATE flag on x1's first item (x1 uploaded a day late)
      missing     MISSING flag on x1's second item
      missing_x2  MISSING flag of the other faculty in the same department
      missing_y   MISSING flag in the other department
    """
    assert put(client, s6["fac_x1"], s6["sub"], at=LATE_AT, clk=clk).status_code == 201
    assert sweep(client, s6["dean"]).status_code == 200
    w = dict(s6)
    w["late"] = flags_of(pg, s6["sub"], "LATE", "OPEN")[0]
    w["missing"] = flags_of(pg, s6["sub2"], "MISSING", "OPEN")[0]
    w["missing_x2"] = flags_of(pg, s6["subx2"], "MISSING", "OPEN")[0]
    w["missing_y"] = flags_of(pg, s6["suby"], "MISSING", "OPEN")[0]
    return w


def raise_q(client, who, flag, message=MSG):
    return post(client, who, f"/flags/{flag['id']}/queries", json={"message": message})


def act(client, who, qid, what, message=MSG, **extra):
    return post(client, who, f"/queries/{qid}/{what}", json={"message": message, **extra})


def decide(client, who, qid, outcome, message=MSG):
    return post(client, who, f"/queries/{qid}/resolve", json={"outcome": outcome, "message": message})


def opened(client, who, flag, message=MSG) -> str:
    """Raise a query and return its id."""
    resp = raise_q(client, who, flag, message)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def steps_of(pg, qid):
    return pg.execute("SELECT * FROM query_steps WHERE query_id = %s ORDER BY seq", (qid,)).fetchall()


def query_row(pg, qid):
    return pg.execute("SELECT * FROM queries WHERE id = %s", (qid,)).fetchone()


def flag_row(pg, flag):
    return pg.execute("SELECT * FROM flags WHERE id = %s", (flag["id"],)).fetchone()
