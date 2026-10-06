"""S4: creating course files (Dean only) and the checklist rows that appear with them."""
import uuid

import pytest

from app.tests.api_fixtures import (as_user, audit_actions, client, make_department, make_semester, make_subject,  # noqa: F401
                                    make_user, new_client, uid, world)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import CSV, make_pdf, make_template, make_submission, set_current, upload

RAND = str(uuid.uuid4())


def post(client, who, body, path="/course-files"):
    return client.post(path, headers=as_user(client, who), json=body)


def body(subject, sem, faculty, **kw):
    return {"subject_id": str(subject["id"]), "semester_id": str(sem["id"]), "faculty_id": str(faculty["id"]), **kw}


@pytest.fixture
def setup(pg, world):
    """A fresh semester and three subject types in department X, plus 4 templates (one inactive)."""
    w = dict(world)
    w["sem2"] = make_semester(pg, "2028-29", "ODD")
    for kind in ("THEORY", "LAB", "THEORY_LAB"):
        w[f"s_{kind}"] = pg.execute(
            "INSERT INTO subjects (code, name, department_id, subject_type) VALUES (%s,'n',%s,%s) RETURNING *",
            (f"{kind[:3]}{uid()}", w["x"]["id"], kind)).fetchone()
    w["t_theory"] = make_template(pg, applies_to="THEORY")
    w["t_lab"] = make_template(pg, applies_to="LAB")
    w["t_both"] = make_template(pg, applies_to="BOTH")
    w["t_off"] = make_template(pg, applies_to="BOTH", active=False)
    return w


def rows_for(pg, cf_id):
    return {r["template_id"] for r in pg.execute("SELECT template_id FROM submissions WHERE course_file_id=%s", (cf_id,)).fetchall()}


@pytest.mark.parametrize("kind,expected", [("THEORY", {"t_theory", "t_both"}), ("LAB", {"t_lab", "t_both"}),
                                           ("THEORY_LAB", {"t_theory", "t_lab", "t_both"})])
def test_all_applicable_checklist_rows_exist_the_moment_the_course_file_does(client, pg, setup, kind, expected):
    old = {r["id"] for r in pg.execute("SELECT id FROM checklist_templates").fetchall()} - {setup[k]["id"] for k in ("t_theory", "t_lab", "t_both", "t_off")}
    r = post(client, setup["dean"], body(setup[f"s_{kind}"], setup["sem2"], setup["fac_x1"]))
    assert r.status_code == 201, r.text
    got = rows_for(pg, r.json()["id"]) - old
    assert got == {setup[k]["id"] for k in expected}      # inactive item never appears
    assert r.json()["submission_rows"] >= len(expected)


def test_response_and_copied_department_and_audit(client, pg, setup):
    r = post(client, setup["dean"], body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"], division="  A "))
    d = r.json()
    assert d["department_id"] == str(setup["x"]["id"]) and d["division"] == "A" and d["faculty_name"] == setup["fac_x1"]["full_name"]
    assert "course_file.create" in audit_actions(pg, d["id"])


@pytest.mark.parametrize("make_body,code", [
    (lambda s: body(s["sub_y"], s["sem2"], s["fac_x1"]), 422),           # subject and faculty in different departments
    (lambda s: body(s["s_THEORY"], s["sem2"], s["hod_x"]), 422),          # not a FACULTY user
    (lambda s: body(s["s_THEORY"], s["sem2"], s["dean"]), 422),
    (lambda s: {**body(s["s_THEORY"], s["sem2"], s["fac_x1"]), "faculty_id": RAND}, 422),
    (lambda s: {**body(s["s_THEORY"], s["sem2"], s["fac_x1"]), "subject_id": RAND}, 422),
    (lambda s: {**body(s["s_THEORY"], s["sem2"], s["fac_x1"]), "semester_id": RAND}, 422),
    (lambda s: {**body(s["s_THEORY"], s["sem2"], s["fac_x1"]), "faculty_id": "nope"}, 422),
    (lambda s: {**body(s["s_THEORY"], s["sem2"], s["fac_x1"]), "department_id": str(s["y"]["id"])}, 422),  # cannot be forced
    (lambda s: {**body(s["s_THEORY"], s["sem2"], s["fac_x1"]), "division": "D" * 41}, 422),
])
def test_wrong_links_are_refused_and_create_nothing(client, pg, setup, make_body, code):
    before = pg.execute("SELECT count(*) AS n FROM course_files").fetchone()["n"]
    assert post(client, setup["dean"], make_body(setup)).status_code == code
    assert pg.execute("SELECT count(*) AS n FROM course_files").fetchone()["n"] == before


def test_inactive_faculty_and_inactive_subject_are_refused(client, pg, setup):
    off = make_user(pg, "FACULTY", setup["x"]["id"], active=False)
    assert post(client, setup["dean"], body(setup["s_THEORY"], setup["sem2"], off)).status_code == 422
    pg.execute("UPDATE subjects SET is_active=false WHERE id=%s", (setup["s_LAB"]["id"],))
    assert post(client, setup["dean"], body(setup["s_LAB"], setup["sem2"], setup["fac_x1"])).status_code == 422


def test_same_faculty_subject_semester_division_twice_is_409(client, setup):
    b = body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"])
    assert post(client, setup["dean"], b).status_code == 201
    assert post(client, setup["dean"], b).status_code == 409
    assert post(client, setup["dean"], {**b, "division": "  "}).status_code == 409      # blank division equals no division
    assert post(client, setup["dean"], {**b, "division": "B"}).status_code == 201       # another division is fine


def test_two_faculty_can_share_one_subject(client, setup):
    assert post(client, setup["dean"], body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"])).status_code == 201
    assert post(client, setup["dean"], body(setup["s_THEORY"], setup["sem2"], setup["fac_x2"])).status_code == 201


# ------------------------------------------------------------ bulk
def test_bulk_creates_everything_in_one_go(client, pg, setup):
    items = [body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"]), body(setup["s_LAB"], setup["sem2"], setup["fac_x1"]),
             body(setup["s_THEORY"], setup["sem2"], setup["fac_x2"])]
    r = post(client, setup["dean"], {"items": items}, "/course-files/bulk")
    assert r.status_code == 201 and r.json()["created"] == 3
    for cf in r.json()["course_files"]:
        assert cf["submission_rows"] >= 2 and "course_file.create" in audit_actions(pg, cf["id"])


def test_bulk_is_all_or_nothing_and_names_the_bad_item(client, pg, setup):
    before = pg.execute("SELECT count(*) AS n FROM course_files").fetchone()["n"]
    items = [body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"]), body(setup["s_LAB"], setup["sem2"], setup["fac_x1"]),
             body(setup["sub_y"], setup["sem2"], setup["fac_x1"])]
    r = post(client, setup["dean"], {"items": items}, "/course-files/bulk")
    assert r.status_code == 422 and "Item 3" in r.json()["detail"]
    assert pg.execute("SELECT count(*) AS n FROM course_files").fetchone()["n"] == before
    assert "course_file.create" not in audit_actions(pg)


def test_bulk_duplicate_inside_one_request_is_409_with_item_number(client, setup):
    b = body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"])
    r = post(client, setup["dean"], {"items": [b, b]}, "/course-files/bulk")
    assert r.status_code == 409 and "Item 2" in r.json()["detail"]


@pytest.mark.parametrize("items", [[], [{"subject_id": RAND}]])
def test_bulk_bad_shape_is_422(client, setup, items):
    assert post(client, setup["dean"], {"items": items}, "/course-files/bulk").status_code == 422


# ------------------------------------------------------------ the checklist view of one course file
def test_checklist_shows_every_row_with_deadline_and_no_version_yet(client, pg, setup):
    cf = post(client, setup["dean"], body(setup["s_THEORY"], setup["sem2"], setup["fac_x1"])).json()
    client.put(f"/semesters/{setup['sem2']['id']}/deadlines", headers=as_user(client, setup["dean"]),
               json={"items": [{"template_id": str(setup["t_both"]["id"]), "due_at": "2099-09-30T17:00:00+05:30"}]})
    items = client.get(f"/course-files/{cf['id']}/submissions", headers=as_user(client, setup["fac_x1"])).json()
    mine = {i["template_id"]: i for i in items if i["template_id"] in (str(setup["t_theory"]["id"]), str(setup["t_both"]["id"]))}
    assert len(mine) == 2 and str(setup["t_lab"]["id"]) not in {i["template_id"] for i in items}
    both = mine[str(setup["t_both"]["id"])]
    assert both["due_at"].startswith("2099-09-30") and both["current_version_id"] is None and both["version_count"] == 0
    assert mine[str(setup["t_theory"]["id"])]["due_at"] is None and both["open_flags"] == []


def test_checklist_follows_the_scope_rules(client, world):
    path = f"/course-files/{world['cf_x1']['id']}/submissions"
    ok = lambda who: client.get(path, headers=as_user(client, world[who])).status_code  # noqa: E731
    assert ok("fac_x1") == ok("hod_x") == ok("dean") == 200
    assert ok("fac_x2") == ok("hod_y") == ok("fac_y1") == 404
    assert client.get(path).status_code == 401
    assert client.get(f"/course-files/{RAND}/submissions", headers=as_user(client, world["dean"])).status_code == 404


def test_checklist_shows_the_current_version_and_open_flags(client, pg, world):
    set_current(pg, world["sem"])
    t = make_template(pg, exts=("pdf",))
    sub = make_submission(pg, world["cf_x1"], t)
    upload(client, world["fac_x1"], sub, "bad.pdf", b"%PDF-1.4 broken")
    item = [i for i in client.get(f"/course-files/{world['cf_x1']['id']}/submissions", headers=as_user(client, world["fac_x1"])).json()
            if i["submission_id"] == str(sub["id"])][0]
    assert item["version_no"] == 1 and item["validation_status"] == "FORMAT_FAILED" and item["open_flags"] == ["FORMAT"]
    assert item["uploaded_by_name"] == world["fac_x1"]["full_name"] and item["uploaded_by_role"] == "FACULTY"
