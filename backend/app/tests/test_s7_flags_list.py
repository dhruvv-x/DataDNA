"""S7: GET /flags, the scoped list of flags that the dashboards use."""
from app.core.scope import DEAN  # noqa: F401
from app.tests.s5_helpers import *  # noqa: F401,F403
from app.tests.s5_helpers import DAY, DUE, HOUR, get, kinds_open, put, sweep

LATE_AT = DUE + DAY


def _make_flags(client, s5, clk):
    """x1 uploads late (LATE flag). Sweep then raises MISSING for the other items, in all departments."""
    assert put(client, s5["fac_x1"], s5["sub"], at=LATE_AT, clk=clk).status_code == 201
    assert sweep(client, s5["dean"]).status_code == 200


def test_faculty_sees_only_own_flags(client, s5, clk):
    _make_flags(client, s5, clk)
    body = get(client, s5["fac_x1"], "/flags").json()
    assert body["total"] > 0
    assert {f["faculty_id"] for f in body["flags"]} == {str(s5["fac_x1"]["id"])}


def test_hod_sees_own_department_only(client, s5, clk):
    _make_flags(client, s5, clk)
    body = get(client, s5["hod_x"], "/flags").json()
    assert {f["department_id"] for f in body["flags"]} == {str(s5["x"]["id"])}
    assert {f["faculty_id"] for f in body["flags"]} >= {str(s5["fac_x1"]["id"]), str(s5["fac_x2"]["id"])}


def test_dean_sees_all_departments(client, s5, clk):
    _make_flags(client, s5, clk)
    body = get(client, s5["dean"], "/flags").json()
    assert {f["department_id"] for f in body["flags"]} == {str(s5["x"]["id"]), str(s5["y"]["id"])}


def test_filter_by_kind_and_status(client, s5, clk):
    _make_flags(client, s5, clk)
    late = get(client, s5["dean"], "/flags", params={"kind": "LATE", "status": "OPEN"}).json()
    assert late["total"] == 1 and late["flags"][0]["kind"] == "LATE"
    assert late["flags"][0]["subject_code"] == s5["sub_x"]["code"]
    assert get(client, s5["dean"], "/flags", params={"status": "CLEARED"}).json()["total"] == 0


def test_filter_by_department_for_dean(client, s5, clk):
    _make_flags(client, s5, clk)
    body = get(client, s5["dean"], "/flags", params={"department_id": str(s5["y"]["id"])}).json()
    assert body["total"] > 0 and {f["department_id"] for f in body["flags"]} == {str(s5["y"]["id"])}


def test_hod_cannot_widen_scope_with_department_filter(client, s5, clk):
    _make_flags(client, s5, clk)
    body = get(client, s5["hod_x"], "/flags", params={"department_id": str(s5["y"]["id"])}).json()
    assert body["total"] == 0 and body["flags"] == []


def test_bad_filter_values_are_422(client, s5):
    assert get(client, s5["dean"], "/flags", params={"kind": "NOPE"}).status_code == 422
    assert get(client, s5["dean"], "/flags", params={"status": "NOPE"}).status_code == 422
    assert get(client, s5["dean"], "/flags", params={"limit": 0}).status_code == 422


def test_unknown_semester_is_404(client, s5):
    import uuid
    assert get(client, s5["dean"], "/flags", params={"semester_id": str(uuid.uuid4())}).status_code == 404


def test_paging_and_total(client, s5, clk):
    _make_flags(client, s5, clk)
    full = get(client, s5["dean"], "/flags").json()
    page = get(client, s5["dean"], "/flags", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == full["total"] and len(page["flags"]) == 1
    assert page["flags"][0]["id"] == full["flags"][1]["id"]


def test_needs_login(client, s5):
    assert client.get("/flags").status_code == 401


def test_flags_carry_exceptions_after_a_waiver(client, s5, clk):
    _make_flags(client, s5, clk)
    late = get(client, s5["dean"], "/flags", params={"kind": "LATE"}).json()["flags"][0]
    from app.tests.s5_helpers import post
    assert post(client, s5["dean"], f"/flags/{late['id']}/waive",
                json={"reason": "approved after checking with the faculty"}).status_code == 200
    waived = get(client, s5["dean"], "/flags", params={"status": "WAIVED"}).json()["flags"]
    assert len(waived) == 1 and waived[0]["exceptions"][0]["kind"] == "WAIVER"


def test_no_current_semester_gives_empty_list(client, s5, pg):
    pg.execute("UPDATE semesters SET is_current = false")
    body = get(client, s5["dean"], "/flags").json()
    assert body["total"] == 0 and body["flags"] == []
