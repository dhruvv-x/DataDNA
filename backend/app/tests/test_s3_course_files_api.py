"""S3: read-only course file endpoints. Every scope boundary."""
import uuid

from app.tests.api_fixtures import (  # noqa: F401
    as_user, auth, client, db, login, make_course_file, make_department, make_semester, make_subject,
    make_user, new_client, uid, world,
)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401


def listed(client, who, **params):
    r = client.get("/course-files", headers=as_user(client, who), params=params)
    assert r.status_code == 200, r.text
    return {c["id"] for c in r.json()}


def one(client, who, cf):
    return client.get(f"/course-files/{cf['id']}", headers=as_user(client, who))


# ---------------------------------------------------------------- FACULTY: own files only
def test_faculty_lists_only_own_course_files(client, world):
    assert listed(client, world["fac_x1"]) == {str(world["cf_x1"]["id"])}
    assert listed(client, world["fac_x2"]) == {str(world["cf_x2"]["id"])}
    assert listed(client, world["fac_y1"]) == {str(world["cf_y1"]["id"])}


def test_faculty_gets_own_course_file(client, world):
    r = one(client, world["fac_x1"], world["cf_x1"])
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == str(world["cf_x1"]["id"])
    assert data["subject_code"] == world["sub_x"]["code"] and data["faculty_name"] == world["fac_x1"]["full_name"]
    assert data["academic_year"] == "2026-27" and data["term"] == "ODD"


def test_faculty_cannot_open_colleague_in_same_department(client, world):
    assert one(client, world["fac_x1"], world["cf_x2"]).status_code == 404


def test_faculty_cannot_open_other_department(client, world):
    assert one(client, world["fac_x1"], world["cf_y1"]).status_code == 404


def test_faculty_cannot_widen_scope_with_filters(client, world):
    got = listed(client, world["fac_x1"], faculty_id=str(world["fac_x2"]["id"]))
    assert got == set()
    got = listed(client, world["fac_x1"], department_id=str(world["y"]["id"]))
    assert got == set()


# ---------------------------------------------------------------- HOD: own department only
def test_hod_lists_all_files_of_own_department(client, world):
    assert listed(client, world["hod_x"]) == {str(world["cf_x1"]["id"]), str(world["cf_x2"]["id"])}
    assert listed(client, world["hod_y"]) == {str(world["cf_y1"]["id"])}


def test_hod_opens_any_file_in_own_department(client, world):
    assert one(client, world["hod_x"], world["cf_x1"]).status_code == 200
    assert one(client, world["hod_x"], world["cf_x2"]).status_code == 200


def test_hod_cannot_open_other_department(client, world):
    assert one(client, world["hod_x"], world["cf_y1"]).status_code == 404
    assert one(client, world["hod_y"], world["cf_x1"]).status_code == 404


def test_hod_cannot_widen_scope_with_department_filter(client, world):
    assert listed(client, world["hod_x"], department_id=str(world["y"]["id"])) == set()


def test_hod_scope_uses_course_file_department_not_faculty_current_department(client, world, db):
    # Faculty Y1 later moved to department X, but this course file was created under department Y.
    db.execute("UPDATE users SET department_id = %s WHERE id = %s", (world["x"]["id"], world["fac_y1"]["id"]))
    assert one(client, world["hod_y"], world["cf_y1"]).status_code == 200
    assert one(client, world["hod_x"], world["cf_y1"]).status_code == 404
    assert str(world["cf_y1"]["id"]) in listed(client, world["hod_y"])
    assert str(world["cf_y1"]["id"]) not in listed(client, world["hod_x"])


def test_faculty_keeps_seeing_own_file_after_moving_department(client, world, db):
    db.execute("UPDATE users SET department_id = %s WHERE id = %s", (world["x"]["id"], world["fac_y1"]["id"]))
    assert one(client, world["fac_y1"], world["cf_y1"]).status_code == 200


# ---------------------------------------------------------------- DEAN: everything
def test_dean_lists_all_course_files(client, world):
    got = listed(client, world["dean"])
    assert {str(world[k]["id"]) for k in ("cf_x1", "cf_x2", "cf_y1")} <= got


def test_dean_opens_any_course_file(client, world):
    for k in ("cf_x1", "cf_x2", "cf_y1"):
        assert one(client, world["dean"], world[k]).status_code == 200


def test_dean_can_filter_by_department_faculty_and_semester(client, world, db):
    assert listed(client, world["dean"], department_id=str(world["y"]["id"])) == {str(world["cf_y1"]["id"])}
    assert listed(client, world["dean"], faculty_id=str(world["fac_x2"]["id"])) == {str(world["cf_x2"]["id"])}
    other = make_semester(db, "2025-26", "EVEN")
    cf_old = make_course_file(db, world["sub_x"], other, world["fac_x1"])
    only_old = listed(client, world["dean"], semester_id=str(other["id"]))
    assert only_old == {str(cf_old["id"])}


# ---------------------------------------------------------------- general access rules
def test_course_files_need_login(client, world):
    assert client.get("/course-files").status_code == 401
    assert client.get(f"/course-files/{world['cf_x1']['id']}").status_code == 401


def test_out_of_scope_looks_exactly_like_missing(client, world):
    h = as_user(client, world["fac_x1"])
    hidden = client.get(f"/course-files/{world['cf_y1']['id']}", headers=h)
    missing = client.get(f"/course-files/{uuid.uuid4()}", headers=h)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_bad_uuid_is_422(client, world):
    assert client.get("/course-files/abc", headers=as_user(client, world["dean"])).status_code == 422


def test_inactive_user_cannot_read(client, world, db):
    h = as_user(client, world["fac_x1"])
    db.execute("UPDATE users SET is_active = false WHERE id = %s", (world["fac_x1"]["id"],))
    assert client.get("/course-files", headers=h).status_code == 401


def test_hod_demoted_in_database_loses_department_view_immediately(client, world, db):
    h = as_user(client, world["hod_x"])
    assert client.get("/course-files", headers=h).json()
    db.execute("UPDATE users SET role = 'FACULTY' WHERE id = %s", (world["hod_x"]["id"],))
    assert client.get("/course-files", headers=h).json() == []  # now a plain faculty with no files


def test_temporary_password_user_cannot_read_until_changed(client, db):
    dep = make_department(db)
    u = make_user(db, "FACULTY", dep["id"], must_change=True)
    r = login(client, u)
    assert client.get("/course-files", headers=auth(r.json()["access_token"])).status_code == 403


def test_paging_limits(client, world):
    h = as_user(client, world["dean"])
    assert len(client.get("/course-files", headers=h, params={"limit": 1}).json()) == 1
    assert client.get("/course-files", headers=h, params={"limit": 5000}).status_code == 422
    assert client.get("/course-files", headers=h, params={"offset": -1}).status_code == 422


def test_newest_semester_comes_first(client, world, db):
    older = make_semester(db, "2024-25", "ODD")
    db.execute("UPDATE semesters SET start_date = '2024-07-01', end_date = '2024-12-15' WHERE id = %s", (older["id"],))
    make_course_file(db, world["sub_x"], older, world["fac_x1"])
    rows = client.get("/course-files", headers=as_user(client, world["fac_x1"])).json()
    assert [r["academic_year"] for r in rows] == ["2026-27", "2024-25"]


def test_same_subject_two_divisions_both_listed(client, world):
    got = client.get("/course-files", headers=as_user(client, world["hod_x"])).json()
    divisions = {c["division"] for c in got}
    assert None in divisions and "B" in divisions
