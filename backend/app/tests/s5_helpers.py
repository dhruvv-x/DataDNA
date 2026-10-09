"""Fixtures and helpers for the S5 tests: a controllable clock and a ready-made checklist with deadlines."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.tests.api_fixtures import as_user, client, world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import CSV, TRUNCATED_PDF, make_pdf, make_submission, make_template, set_current, upload  # noqa: F401

UTC = timezone.utc
DUE = datetime(2099, 9, 30, 11, 30, tzinfo=UTC)     # 17:00 IST
SEC = timedelta(seconds=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
GOOD_REASON = "approved after checking with the faculty"


class FakeClock:
    """Moves 'now' for the app code that decides lateness. Logins keep using the real clock."""

    def __init__(self):
        self.now = DUE - DAY

    def set(self, moment):
        self.now = moment
        return self


@pytest.fixture
def clk(monkeypatch):
    clock = FakeClock()
    fake = SimpleNamespace(utcnow=lambda: clock.now)
    for module in ("app.api.submissions", "app.api.rules", "app.api.master", "app.api.queries"):
        monkeypatch.setattr(f"{module}.clock", fake)
    return clock


@pytest.fixture
def s5(pg, world, clk):  # noqa: F811
    """Current semester; two checklist items with the same deadline; submissions for three course files."""
    set_current(pg, world["sem"])
    w = dict(world)
    w["tpl"] = make_template(pg, exts=("pdf", "csv"), sort=1)
    w["tpl2"] = make_template(pg, exts=("csv",), sort=2)
    for t in (w["tpl"], w["tpl2"]):
        pg.execute("INSERT INTO checklist_deadlines (semester_id, template_id, due_at) VALUES (%s, %s, %s)",
                   (world["sem"]["id"], t["id"], DUE))
    w["sub"] = make_submission(pg, world["cf_x1"], w["tpl"])        # faculty x1
    w["sub2"] = make_submission(pg, world["cf_x1"], w["tpl2"])
    w["subx2"] = make_submission(pg, world["cf_x2"], w["tpl"])      # faculty x2, same department
    w["suby"] = make_submission(pg, world["cf_y1"], w["tpl"])       # other department
    return w


def flags_of(pg, sub, kind=None, status=None):
    q, a = "SELECT * FROM flags WHERE submission_id = %s", [sub["id"]]
    if kind:
        q, a = q + " AND kind = %s", a + [kind]
    if status:
        q, a = q + " AND status = %s", a + [status]
    return pg.execute(q + " ORDER BY raised_at, id", a).fetchall()


def kinds_open(pg, sub):
    return sorted(f["kind"] for f in flags_of(pg, sub, status="OPEN"))


def exceptions_of(pg, sub, kind=None):
    q, a = "SELECT * FROM exceptions WHERE submission_id = %s", [sub["id"]]
    if kind:
        q, a = q + " AND kind = %s", a + [kind]
    return pg.execute(q + " ORDER BY granted_at, id", a).fetchall()


def csv_n(n: int) -> bytes:
    return CSV + f"row{n},{n}\n".encode()


def put(client, who, sub, n=1, at=None, clk=None, name="a.csv", data=None):
    """Upload a valid CSV as `who` at fake time `at`."""
    if clk is not None and at is not None:
        clk.set(at)
    return upload(client, who, sub, name, data if data is not None else csv_n(n),
                  reason="uploaded for the faculty member" if who["role"] == "DEAN" else None)


def audit(pg, action, entity_id=None):
    q, a = "SELECT * FROM audit_log WHERE action = %s", [action]
    if entity_id is not None:
        q, a = q + " AND entity_id = %s", a + [str(entity_id)]
    return pg.execute(q + " ORDER BY id", a).fetchall()


def post(client, who, path, **kw):
    return client.post(path, headers=as_user(client, who), **kw)


def get(client, who, path, **kw):
    return client.get(path, headers=as_user(client, who), **kw)


def sweep(client, who, **params):
    return post(client, who, "/rules/evaluate", params=params)
