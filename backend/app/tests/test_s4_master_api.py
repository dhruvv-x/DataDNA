"""S4: master data endpoints. Dean changes, everyone logged in reads (within scope)."""
import uuid

import pytest

from app.tests.api_fixtures import (as_user, audit_actions, client, make_course_file, make_department, make_semester,  # noqa: F401
                                    make_subject, make_user, new_client, uid, world)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import make_template

RAND = str(uuid.uuid4())


def call(client, who, method, path, **kw):
    return client.request(method, path, headers=as_user(client, who), **kw)


# ------------------------------------------------------------ only the Dean may change anything
WRITES = [
    ("POST", "/departments", {"code": "ZZ", "name": "Zed"}),
    ("PATCH", f"/departments/{RAND}", {"name": "New"}),
    ("POST", "/semesters", {"academic_year": "2030-31", "term": "ODD", "start_date": "2030-07-01", "end_date": "2030-12-01"}),
    ("PATCH", f"/semesters/{RAND}", {"start_date": "2030-07-01", "end_date": "2030-12-01"}),
    ("POST", f"/semesters/{RAND}/make-current", None),
    ("POST", "/subjects", {"code": "S", "name": "S", "department_id": RAND, "subject_type": "LAB"}),
    ("PATCH", f"/subjects/{RAND}", {"name": "N"}),
    ("POST", "/checklist-templates", {"code": "T1", "title": "T", "allowed_extensions": ["pdf"]}),
    ("PATCH", f"/checklist-templates/{RAND}", {"title": "N"}),
    ("PUT", f"/semesters/{RAND}/deadlines", {"items": [{"template_id": RAND, "due_at": "2030-01-01T00:00:00+05:30"}]}),
    ("POST", "/course-files", {"subject_id": RAND, "semester_id": RAND, "faculty_id": RAND}),
    ("POST", "/course-files/bulk", {"items": [{"subject_id": RAND, "semester_id": RAND, "faculty_id": RAND}]}),
]


@pytest.mark.parametrize("who", ["hod_x", "fac_x1", "hod_y", "fac_y1"])
@pytest.mark.parametrize("method,path,body", WRITES)
def test_only_the_dean_may_change_master_data(client, world, who, method, path, body):
    r = call(client, world[who], method, path, json=body)
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("method,path,body", WRITES)
def test_changes_need_a_login(client, world, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("path", ["/departments", "/semesters", "/subjects", "/checklist-templates"])
def test_reading_needs_a_login(client, world, path):
    assert client.get(path).status_code == 401


# ------------------------------------------------------------ departments
def test_dean_creates_department_code_is_uppercased_and_audited(client, world, pg):
    r = call(client, world["dean"], "POST", "/departments", json={"code": "civ", "name": "  Civil  "})
    assert r.status_code == 201 and r.json()["code"] == "CIV" and r.json()["name"] == "Civil"
    assert "department.create" in audit_actions(pg, r.json()["id"])


@pytest.mark.parametrize("body", [{"code": "", "name": "x"}, {"code": "has space", "name": "x"}, {"code": "A" * 21, "name": "x"},
                                  {"code": "OK", "name": "   "}, {"code": "OK"}, {"code": "OK", "name": "x", "extra": 1}])
def test_bad_department_input_is_422(client, world, body):
    assert call(client, world["dean"], "POST", "/departments", json=body).status_code == 422


def test_duplicate_department_code_or_name_is_409(client, world):
    first = call(client, world["dean"], "POST", "/departments", json={"code": "DUP", "name": "Dup Dept"})
    assert first.status_code == 201
    assert call(client, world["dean"], "POST", "/departments", json={"code": "dup", "name": "Other"}).status_code == 409
    assert call(client, world["dean"], "POST", "/departments", json={"code": "DUP2", "name": "Dup Dept"}).status_code == 409


def test_department_list_is_scoped(client, world):
    ids = lambda who: {d["id"] for d in call(client, world[who], "GET", "/departments").json()}  # noqa: E731
    assert {str(world["x"]["id"]), str(world["y"]["id"])} <= ids("dean")
    assert ids("hod_x") == {str(world["x"]["id"])} == ids("fac_x1")
    assert ids("fac_y1") == {str(world["y"]["id"])}


def test_rename_department_keeps_code_and_logs_old_and_new(client, world, pg):
    r = call(client, world["dean"], "PATCH", f"/departments/{world['x']['id']}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["code"] == world["x"]["code"]
    row = pg.execute("SELECT payload FROM audit_log WHERE action='department.update' AND entity_id=%s", (str(world["x"]["id"]),)).fetchone()
    assert row["payload"]["new_name"] == "Renamed" and row["payload"]["old_name"] == world["x"]["name"]


def test_code_cannot_be_changed_and_unknown_department_is_404(client, world):
    assert call(client, world["dean"], "PATCH", f"/departments/{world['x']['id']}", json={"name": "N", "code": "NEW"}).status_code == 422
    assert call(client, world["dean"], "PATCH", f"/departments/{RAND}", json={"name": "N"}).status_code == 404


# ------------------------------------------------------------ semesters
SEM = {"academic_year": "2031-32", "term": "ODD", "start_date": "2031-07-01", "end_date": "2031-12-15"}


def test_dean_creates_semester(client, world, pg):
    r = call(client, world["dean"], "POST", "/semesters", json=SEM)
    assert r.status_code == 201 and r.json()["is_current"] is False
    assert "semester.create" in audit_actions(pg, r.json()["id"])


@pytest.mark.parametrize("change", [
    {"academic_year": "2031-33"}, {"academic_year": "2031"}, {"academic_year": "31-32"},
    {"term": "SUMMER"}, {"end_date": "2031-07-01"}, {"end_date": "2031-06-01"}, {"start_date": "not a date"},
])
def test_bad_semester_input_is_422(client, world, change):
    assert call(client, world["dean"], "POST", "/semesters", json={**SEM, **change}).status_code == 422


def test_century_year_wraps_correctly(client, world):
    ok = {**SEM, "academic_year": "2099-00", "start_date": "2099-07-01", "end_date": "2099-12-01"}
    assert call(client, world["dean"], "POST", "/semesters", json=ok).status_code == 201


def test_duplicate_semester_is_409(client, world):
    assert call(client, world["dean"], "POST", "/semesters", json=SEM).status_code == 201
    assert call(client, world["dean"], "POST", "/semesters", json=SEM).status_code == 409


def test_everyone_can_read_semesters_newest_first(client, world):
    call(client, world["dean"], "POST", "/semesters", json=SEM)
    r = call(client, world["fac_x1"], "GET", "/semesters")
    assert r.status_code == 200 and r.json()[0]["academic_year"] == "2031-32"


def test_change_semester_dates_logged_and_validated(client, world, pg):
    sid = world["sem"]["id"]
    r = call(client, world["dean"], "PATCH", f"/semesters/{sid}", json={"start_date": "2026-07-05", "end_date": "2026-12-20"})
    assert r.status_code == 200 and r.json()["start_date"] == "2026-07-05"
    assert "semester.update" in audit_actions(pg, sid)
    bad = call(client, world["dean"], "PATCH", f"/semesters/{sid}", json={"start_date": "2026-12-20", "end_date": "2026-07-05"})
    assert bad.status_code == 422
    assert call(client, world["dean"], "PATCH", f"/semesters/{RAND}", json={"start_date": "2026-07-05", "end_date": "2026-12-20"}).status_code == 404


def test_make_current_leaves_exactly_one_current(client, world, pg):
    other = make_semester(pg, "2027-28", "EVEN", current=True)
    r = call(client, world["dean"], "POST", f"/semesters/{world['sem']['id']}/make-current")
    assert r.status_code == 200 and r.json()["is_current"] is True
    current = pg.execute("SELECT id FROM semesters WHERE is_current").fetchall()
    assert [c["id"] for c in current] == [world["sem"]["id"]]
    assert pg.execute("SELECT is_current FROM semesters WHERE id=%s", (other["id"],)).fetchone()["is_current"] is False


def test_make_current_records_the_previous_current_semester(client, world, pg):
    other = make_semester(pg, "2027-28", "EVEN", current=True)
    call(client, world["dean"], "POST", f"/semesters/{world['sem']['id']}/make-current")
    row = pg.execute("SELECT payload FROM audit_log WHERE action='semester.make_current'").fetchone()
    assert row["payload"]["previous_current"] == str(other["id"])


def test_make_current_unknown_is_404_and_changes_nothing(client, world, pg):
    keep = make_semester(pg, "2027-28", "EVEN", current=True)
    assert call(client, world["dean"], "POST", f"/semesters/{RAND}/make-current").status_code == 404
    assert pg.execute("SELECT is_current FROM semesters WHERE id=%s", (keep["id"],)).fetchone()["is_current"] is True


# ------------------------------------------------------------ subjects
def subj(world, **kw):
    return {"code": "cs101", "name": "Intro", "department_id": str(world["x"]["id"]), "subject_type": "THEORY", **kw}


def test_dean_creates_subject_code_uppercased(client, world, pg):
    r = call(client, world["dean"], "POST", "/subjects", json=subj(world))
    assert r.status_code == 201 and r.json()["code"] == "CS101" and r.json()["is_active"] is True
    assert "subject.create" in audit_actions(pg, r.json()["id"])


@pytest.mark.parametrize("change", [{"code": "  "}, {"name": ""}, {"subject_type": "WORKSHOP"}, {"department_id": "nope"}])
def test_bad_subject_input_is_422(client, world, change):
    assert call(client, world["dean"], "POST", "/subjects", json=subj(world, **change)).status_code == 422


def test_subject_in_unknown_department_is_409_and_duplicate_code_is_409(client, world):
    assert call(client, world["dean"], "POST", "/subjects", json=subj(world, department_id=RAND)).status_code == 409
    assert call(client, world["dean"], "POST", "/subjects", json=subj(world)).status_code == 201
    assert call(client, world["dean"], "POST", "/subjects", json=subj(world, code="CS101")).status_code == 409


def test_subject_list_is_scoped_by_department(client, world):
    codes = lambda who, **p: {s["code"] for s in call(client, world[who], "GET", "/subjects", params=p).json()}  # noqa: E731
    assert world["sub_x"]["code"] in codes("fac_x1") and world["sub_y"]["code"] not in codes("fac_x1")
    assert world["sub_x"]["code"] in codes("hod_x") and world["sub_y"]["code"] not in codes("hod_x")
    assert {world["sub_x"]["code"], world["sub_y"]["code"]} <= codes("dean")
    assert codes("dean", department_id=str(world["y"]["id"])) == {world["sub_y"]["code"]}
    assert codes("fac_x1", department_id=str(world["y"]["id"])) == set()  # asking for another department shows nothing


def test_patch_subject_name_and_switch_off(client, world, pg):
    sid = world["sub_x"]["id"]
    r = call(client, world["dean"], "PATCH", f"/subjects/{sid}", json={"name": "Better Name", "is_active": False})
    assert r.status_code == 200 and r.json()["name"] == "Better Name" and r.json()["is_active"] is False
    assert "subject.update" in audit_actions(pg, sid)


def test_patch_subject_type_blocked_once_course_files_exist(client, world):
    r = call(client, world["dean"], "PATCH", f"/subjects/{world['sub_x']['id']}", json={"subject_type": "LAB"})
    assert r.status_code == 409


def test_patch_subject_type_allowed_when_unused(client, world, pg):
    fresh = make_subject(pg, world["x"]["id"])
    r = call(client, world["dean"], "PATCH", f"/subjects/{fresh['id']}", json={"subject_type": "LAB"})
    assert r.status_code == 200 and r.json()["subject_type"] == "LAB"


@pytest.mark.parametrize("body", [{}, {"department_id": RAND}, {"code": "X"}, {"name": ""}])
def test_patch_subject_rejects_empty_or_forbidden_changes(client, world, body):
    assert call(client, world["dean"], "PATCH", f"/subjects/{world['sub_x']['id']}", json=body).status_code == 422


def test_patch_unknown_subject_is_404(client, world):
    assert call(client, world["dean"], "PATCH", f"/subjects/{RAND}", json={"name": "N"}).status_code == 404


# ------------------------------------------------------------ checklist templates
def tmpl(**kw):
    return {"code": "lp", "title": "Lesson plan", "allowed_extensions": ["pdf", ".DOCX"], "max_size_mb": 5, **kw}


def test_dean_creates_template_extensions_are_cleaned(client, world, pg):
    r = call(client, world["dean"], "POST", "/checklist-templates", json=tmpl())
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == "LP" and body["allowed_extensions"] == ["pdf", "docx"] and body["applies_to"] == "BOTH"
    assert "template.create" in audit_actions(pg, body["id"])


def test_duplicate_extensions_are_merged(client, world):
    r = call(client, world["dean"], "POST", "/checklist-templates", json=tmpl(allowed_extensions=["pdf", "PDF", ".pdf"]))
    assert r.json()["allowed_extensions"] == ["pdf"]


@pytest.mark.parametrize("change", [
    {"allowed_extensions": []}, {"allowed_extensions": ["exe"]}, {"allowed_extensions": ["pdf", "zip"]},
    {"allowed_extensions": ["html"]}, {"max_size_mb": 0}, {"max_size_mb": 501}, {"title": "  "},
    {"code": "bad code"}, {"applies_to": "OTHER"}, {"sort_order": -1},
])
def test_bad_template_input_is_422(client, world, change):
    assert call(client, world["dean"], "POST", "/checklist-templates", json=tmpl(**change)).status_code == 422


def test_duplicate_template_code_is_409(client, world):
    assert call(client, world["dean"], "POST", "/checklist-templates", json=tmpl()).status_code == 201
    assert call(client, world["dean"], "POST", "/checklist-templates", json=tmpl(code="LP")).status_code == 409


def test_everyone_reads_templates_in_sort_order(client, world):
    call(client, world["dean"], "POST", "/checklist-templates", json=tmpl(code="B", sort_order=2))
    call(client, world["dean"], "POST", "/checklist-templates", json=tmpl(code="A", sort_order=1))
    codes = [t["code"] for t in call(client, world["fac_x1"], "GET", "/checklist-templates").json()]
    assert codes.index("A") < codes.index("B")


def test_patch_template_changes_only_what_was_sent(client, world, pg):
    t = make_template(pg, exts=("pdf",), max_mb=10)
    r = call(client, world["dean"], "PATCH", f"/checklist-templates/{t['id']}", json={"max_size_mb": 20, "allowed_extensions": ["XLSX"]})
    assert r.status_code == 200 and r.json()["max_size_mb"] == 20 and r.json()["allowed_extensions"] == ["xlsx"]
    assert r.json()["title"] == t["title"]


@pytest.mark.parametrize("body", [{}, {"applies_to": "LAB"}, {"code": "NEW"}, {"allowed_extensions": ["exe"]}, {"max_size_mb": 0}])
def test_patch_template_rejects_empty_or_forbidden_changes(client, world, pg, body):
    t = make_template(pg)
    assert call(client, world["dean"], "PATCH", f"/checklist-templates/{t['id']}", json=body).status_code == 422


def test_patch_unknown_template_is_404(client, world):
    assert call(client, world["dean"], "PATCH", f"/checklist-templates/{RAND}", json={"title": "N"}).status_code == 404


# ------------------------------------------------------------ rows added when a template appears later
def future_semester(pg, year="2090-91"):
    return pg.execute(
        "INSERT INTO semesters (academic_year, term, start_date, end_date) VALUES (%s,'ODD','2090-07-01','2090-12-15') RETURNING *",
        (year,)).fetchone()


def count_rows(pg, cf):
    return pg.execute("SELECT count(*) AS n FROM submissions WHERE course_file_id=%s", (cf["id"],)).fetchone()["n"]


def test_new_template_adds_rows_to_existing_course_files_of_open_semesters(client, world, pg):
    sem = future_semester(pg)
    cf = make_course_file(pg, world["sub_x"], sem, world["fac_x1"])
    r = call(client, world["dean"], "POST", "/checklist-templates", json=tmpl())
    assert r.json()["submission_rows_added"] >= 1 and count_rows(pg, cf) == 1  # other open course files get a row too


def test_finished_semesters_do_not_get_new_rows(client, world, pg):
    old = pg.execute("SELECT * FROM semesters WHERE id=%s", (world["sem"]["id"],)).fetchone()
    pg.execute("UPDATE semesters SET start_date='2000-01-01', end_date='2000-06-01' WHERE id=%s", (old["id"],))
    r = call(client, world["dean"], "POST", "/checklist-templates", json=tmpl())
    assert r.json()["submission_rows_added"] == 0 and count_rows(pg, world["cf_x1"]) == 0


def test_lab_item_is_not_added_to_theory_course_files(client, world, pg):
    sem = future_semester(pg)
    cf = make_course_file(pg, world["sub_x"], sem, world["fac_x1"])  # THEORY subject
    call(client, world["dean"], "POST", "/checklist-templates", json=tmpl(applies_to="LAB"))
    assert count_rows(pg, cf) == 0


def test_switching_a_template_off_keeps_rows_and_back_on_adds_nothing_twice(client, world, pg):
    sem = future_semester(pg)
    cf = make_course_file(pg, world["sub_x"], sem, world["fac_x1"])
    tid = call(client, world["dean"], "POST", "/checklist-templates", json=tmpl()).json()["id"]
    off = call(client, world["dean"], "PATCH", f"/checklist-templates/{tid}", json={"is_active": False})
    assert off.json()["submission_rows_added"] == 0 and count_rows(pg, cf) == 1
    on = call(client, world["dean"], "PATCH", f"/checklist-templates/{tid}", json={"is_active": True})
    assert on.json()["submission_rows_added"] == 0 and count_rows(pg, cf) == 1


def test_switching_on_a_template_fills_in_missing_rows(client, world, pg):
    t = make_template(pg, active=False)
    sem = future_semester(pg)
    cf = make_course_file(pg, world["sub_x"], sem, world["fac_x1"])
    assert count_rows(pg, cf) == 0
    on = call(client, world["dean"], "PATCH", f"/checklist-templates/{t['id']}", json={"is_active": True})
    assert on.json()["submission_rows_added"] >= 1 and count_rows(pg, cf) == 1


# ------------------------------------------------------------ deadlines
DUE = "2026-09-30T17:00:00+05:30"


def put_deadlines(client, who, sem_id, items):
    return call(client, who, "PUT", f"/semesters/{sem_id}/deadlines", json={"items": items})


def test_dean_sets_deadlines_in_bulk_and_everyone_reads_them(client, world, pg):
    t1, t2 = make_template(pg, sort=1), make_template(pg, sort=2)
    r = put_deadlines(client, world["dean"], world["sem"]["id"], [
        {"template_id": str(t2["id"]), "due_at": DUE}, {"template_id": str(t1["id"]), "due_at": "2026-08-15T10:00:00+00:00"}])
    assert r.status_code == 200 and [d["template_id"] for d in r.json()] == [str(t1["id"]), str(t2["id"])]
    seen = call(client, world["fac_x1"], "GET", f"/semesters/{world['sem']['id']}/deadlines")
    assert seen.status_code == 200 and len(seen.json()) == 2
    assert "deadlines.set" in audit_actions(pg, world["sem"]["id"])


def test_moving_a_deadline_logs_old_and_new(client, world, pg):
    t = make_template(pg)
    put_deadlines(client, world["dean"], world["sem"]["id"], [{"template_id": str(t["id"]), "due_at": DUE}])
    put_deadlines(client, world["dean"], world["sem"]["id"], [{"template_id": str(t["id"]), "due_at": "2026-10-10T17:00:00+05:30"}])
    row = pg.execute("SELECT payload FROM audit_log WHERE action='deadlines.set' ORDER BY id DESC LIMIT 1").fetchone()
    change = row["payload"]["changes"][0]
    assert change["old"].startswith("2026-09-30") and change["new"].startswith("2026-10-10")
    assert pg.execute("SELECT count(*) AS n FROM checklist_deadlines WHERE semester_id=%s", (world["sem"]["id"],)).fetchone()["n"] == 1


def test_a_date_without_time_zone_is_refused(client, world, pg):
    t = make_template(pg)
    assert put_deadlines(client, world["dean"], world["sem"]["id"], [{"template_id": str(t["id"]), "due_at": "2026-09-30T17:00:00"}]).status_code == 422


def test_deadline_batch_is_all_or_nothing(client, world, pg):
    t = make_template(pg)
    r = put_deadlines(client, world["dean"], world["sem"]["id"], [
        {"template_id": str(t["id"]), "due_at": DUE}, {"template_id": RAND, "due_at": DUE}])
    assert r.status_code == 422
    assert pg.execute("SELECT count(*) AS n FROM checklist_deadlines WHERE semester_id=%s", (world["sem"]["id"],)).fetchone()["n"] == 0


def test_bad_deadline_requests(client, world, pg):
    t = make_template(pg)
    item = {"template_id": str(t["id"]), "due_at": DUE}
    assert put_deadlines(client, world["dean"], world["sem"]["id"], []).status_code == 422
    assert put_deadlines(client, world["dean"], world["sem"]["id"], [item, item]).status_code == 422
    assert put_deadlines(client, world["dean"], RAND, [item]).status_code == 404
    assert call(client, world["fac_x1"], "GET", f"/semesters/{RAND}/deadlines").status_code == 404
    assert put_deadlines(client, world["dean"], world["sem"]["id"], [{"template_id": str(t["id"]), "due_at": "garbage"}]).status_code == 422
