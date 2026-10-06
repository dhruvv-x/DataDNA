"""S5: extensions, waivers, bulk waiver, reading flags. Who may do what, and what it does."""
import uuid
from datetime import timedelta

import pytest

from app.tests.api_fixtures import as_user, client, make_semester, world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import make_submission, make_template, set_current
from app.tests.s5_helpers import (DAY, DUE, GOOD_REASON, HOUR, SEC, TRUNCATED_PDF, audit, clk, exceptions_of, flags_of, get,  # noqa: F401
                                  kinds_open, post, put, s5, sweep, upload)

RAND = str(uuid.uuid4())


def extend(client, who, sub, new_due, reason=GOOD_REASON):
    return post(client, who, f"/submissions/{sub['id']}/extensions", json={"new_due_at": new_due.isoformat(), "reason": reason})


def waive(client, who, flag_id, reason=GOOD_REASON):
    return post(client, who, f"/flags/{flag_id}/waive", json={"reason": reason})


def make_late(client, pg, s5, clk, sub="sub", who="fac_x1", at=None):
    put(client, s5[who], s5[sub], at=at or DUE + DAY, clk=clk)
    return flags_of(pg, s5[sub], "LATE")[0]


# ============================================================ extensions: who
@pytest.mark.parametrize("who", ["dean", "hod_x"])
def test_dean_and_own_hod_can_grant_an_extension(client, pg, s5, clk, who):
    r = extend(client, s5[who], s5["sub"], DUE + 2 * DAY)
    assert r.status_code == 201, r.text
    (exc,) = exceptions_of(pg, s5["sub"], "EXTENSION")
    assert exc["new_due_at"] == DUE + 2 * DAY and exc["granted_by"] == s5[who]["id"] and exc["reason"] == GOOD_REASON
    row = audit(pg, "extension.grant", s5["sub"]["id"])[0]
    assert row["actor_id"] == s5[who]["id"] and row["payload"]["old_due_at"] == DUE.isoformat()


def test_faculty_cannot_extend_their_own_deadline(client, pg, s5, clk):
    assert extend(client, s5["fac_x1"], s5["sub"], DUE + DAY).status_code == 403
    assert exceptions_of(pg, s5["sub"]) == []


@pytest.mark.parametrize("who", ["hod_y", "fac_y1", "fac_x2"])
def test_out_of_scope_users_see_a_plain_404(client, pg, s5, clk, who):
    assert extend(client, s5[who], s5["sub"], DUE + DAY).status_code == 404
    assert exceptions_of(pg, s5["sub"]) == []


def test_needs_login_and_unknown_submission(client, s5):
    assert client.post(f"/submissions/{s5['sub']['id']}/extensions", json={"new_due_at": DUE.isoformat(), "reason": GOOD_REASON}).status_code == 401
    assert extend(client, s5["dean"], {"id": uuid.uuid4()}, DUE + DAY).status_code == 404


# ============================================================ extensions: rules
@pytest.mark.parametrize("delta", [-DAY, 0 * SEC, -SEC])
def test_new_date_must_be_after_the_current_deadline(client, pg, s5, clk, delta):
    r = extend(client, s5["dean"], s5["sub"], DUE + delta)
    assert r.status_code == 422 and "after the current deadline" in r.json()["detail"]


def test_one_second_later_is_enough(client, s5, clk):
    assert extend(client, s5["dean"], s5["sub"], DUE + SEC).status_code == 201


def test_extension_needs_a_reason_of_ten_characters(client, pg, s5, clk):
    for reason in ("", "   ", "short", "123456789"):
        assert extend(client, s5["dean"], s5["sub"], DUE + DAY, reason).status_code == 422
    assert extend(client, s5["dean"], s5["sub"], DUE + DAY, "1234567890").status_code == 201
    assert len(exceptions_of(pg, s5["sub"])) == 1


def test_naive_dates_and_unknown_fields_are_refused(client, s5):
    assert post(client, s5["dean"], f"/submissions/{s5['sub']['id']}/extensions", json={"new_due_at": "2099-10-05T10:00:00", "reason": GOOD_REASON}).status_code == 422
    assert post(client, s5["dean"], f"/submissions/{s5['sub']['id']}/extensions", json={"new_due_at": (DUE + DAY).isoformat(), "reason": GOOD_REASON, "granted_by": RAND}).status_code == 422


def test_no_deadline_means_nothing_to_extend(client, pg, s5, clk):
    pg.execute("DELETE FROM checklist_deadlines WHERE template_id = %s", (s5["tpl"]["id"],))
    r = extend(client, s5["dean"], s5["sub"], DUE + DAY)
    assert r.status_code == 422 and "no deadline" in r.json()["detail"]


def test_extensions_stack_and_each_must_beat_the_current_effective_date(client, pg, s5, clk):
    assert extend(client, s5["dean"], s5["sub"], DUE + 3 * DAY).status_code == 201
    assert extend(client, s5["dean"], s5["sub"], DUE + 2 * DAY).status_code == 422
    assert extend(client, s5["dean"], s5["sub"], DUE + 5 * DAY).status_code == 201
    items = get(client, s5["fac_x1"], f"/course-files/{s5['cf_x1']['id']}/submissions").json()
    mine = [i for i in items if i["submission_id"] == str(s5["sub"]["id"])][0]
    assert mine["effective_due_at"].startswith("2099-10-05") and mine["extended_to"].startswith("2099-10-05")
    assert mine["due_at"].startswith("2099-09-30")
    other = [i for i in items if i["submission_id"] == str(s5["sub2"]["id"])][0]
    assert other["extended_to"] is None and other["effective_due_at"].startswith("2099-09-30")


def test_extension_covers_only_that_submission(client, pg, s5, clk):
    extend(client, s5["dean"], s5["sub"], DUE + 3 * DAY)
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == [] and kinds_open(pg, s5["sub2"]) == ["MISSING"] and kinds_open(pg, s5["subx2"]) == ["MISSING"]


def test_extension_before_the_deadline_prevents_missing_until_the_new_date(client, pg, s5, clk):
    extend(client, s5["dean"], s5["sub"], DUE + 3 * DAY)
    clk.set(DUE + 3 * DAY)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == []
    clk.set(DUE + 3 * DAY + SEC)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["MISSING"]


def test_extension_clears_an_existing_missing_flag(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["MISSING"]
    r = extend(client, s5["dean"], s5["sub"], DUE + 3 * DAY)
    assert r.status_code == 201 and kinds_open(pg, s5["sub"]) == [] and r.json()["changes"][0]["kind"] == "MISSING"


def test_extension_in_a_closed_semester_is_for_the_dean_only(client, pg, s5, clk):
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))
    assert extend(client, s5["hod_x"], s5["sub"], DUE + DAY).status_code == 409
    assert extend(client, s5["dean"], s5["sub"], DUE + DAY).status_code == 201


def test_extension_for_a_switched_off_item_is_refused(client, pg, s5, clk):
    pg.execute("UPDATE checklist_templates SET is_active = false WHERE id = %s", (s5["tpl"]["id"],))
    assert extend(client, s5["dean"], s5["sub"], DUE + DAY).status_code == 409


# ============================================================ extension and an existing lateness flag
def test_extension_that_covers_the_delivery_waives_the_lateness_flag_with_its_own_record(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk, at=DUE + DAY)
    r = extend(client, s5["hod_x"], s5["sub"], DUE + 2 * DAY, "faculty was at the NAAC visit")
    assert r.status_code == 201 and r.json()["late_flag_waived"] == str(late["id"])
    (flag,) = flags_of(pg, s5["sub"], "LATE")
    assert flag["status"] == "WAIVED"
    (waiver,) = exceptions_of(pg, s5["sub"], "WAIVER")
    assert waiver["flag_id"] == flag["id"] and waiver["granted_by"] == s5["hod_x"]["id"] and "faculty was at the NAAC visit" in waiver["reason"]
    row = audit(pg, "flag.waive", flag["id"])[0]
    assert row["payload"]["automatic"] is True and row["actor_id"] == s5["hod_x"]["id"]


def test_extension_that_does_not_reach_the_delivery_leaves_lateness_alone(client, pg, s5, clk):
    make_late(client, pg, s5, clk, at=DUE + 3 * DAY)
    r = extend(client, s5["dean"], s5["sub"], DUE + 1 * DAY)
    assert r.status_code == 201 and r.json()["late_flag_waived"] is None
    assert kinds_open(pg, s5["sub"]) == ["LATE"] and exceptions_of(pg, s5["sub"], "WAIVER") == []


def test_extension_exactly_equal_to_the_delivery_time_covers_it(client, pg, s5, clk):
    make_late(client, pg, s5, clk, at=DUE + DAY)
    assert extend(client, s5["dean"], s5["sub"], DUE + DAY).json()["late_flag_waived"] is not None


def test_extension_does_not_touch_other_flags_of_the_same_item(client, pg, s5, clk):
    clk.set(DUE + HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)         # LATE + FORMAT + INCOMPLETE
    extend(client, s5["dean"], s5["sub"], DUE + 2 * DAY)
    assert kinds_open(pg, s5["sub"]) == ["FORMAT"]                         # LATE waived, INCOMPLETE gone (deadline in future), FORMAT stays


# ============================================================ waivers
@pytest.mark.parametrize("who", ["dean", "hod_x"])
def test_dean_and_own_hod_can_waive_a_flag(client, pg, s5, clk, who):
    late = make_late(client, pg, s5, clk)
    r = waive(client, s5[who], late["id"])
    assert r.status_code == 200 and r.json()["status"] == "WAIVED"
    (flag,) = flags_of(pg, s5["sub"], "LATE")
    assert flag["status"] == "WAIVED"
    (exc,) = exceptions_of(pg, s5["sub"], "WAIVER")
    assert exc["flag_id"] == flag["id"] and exc["granted_by"] == s5[who]["id"] and exc["reason"] == GOOD_REASON
    row = audit(pg, "flag.waive", flag["id"])[0]
    assert row["actor_id"] == s5[who]["id"] and row["payload"]["automatic"] is False


def test_faculty_cannot_waive_even_their_own_flag(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    assert waive(client, s5["fac_x1"], late["id"]).status_code == 403
    assert flags_of(pg, s5["sub"], "LATE")[0]["status"] == "OPEN"


@pytest.mark.parametrize("who", ["hod_y", "fac_y1", "fac_x2"])
def test_waiving_a_flag_you_cannot_see_is_a_404(client, pg, s5, clk, who):
    late = make_late(client, pg, s5, clk)
    assert waive(client, s5[who], late["id"]).status_code == 404
    assert flags_of(pg, s5["sub"], "LATE")[0]["status"] == "OPEN"


def test_waiver_reason_rules_and_unknown_flag(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    for reason in ("", "  ", "too short", "123456789"):
        assert waive(client, s5["dean"], late["id"], reason).status_code == 422
    assert post(client, s5["dean"], f"/flags/{late['id']}/waive", json={"reason": GOOD_REASON, "extra": 1}).status_code == 422
    assert waive(client, s5["dean"], RAND).status_code == 404
    assert client.post(f"/flags/{late['id']}/waive", json={"reason": GOOD_REASON}).status_code == 401
    assert exceptions_of(pg, s5["sub"]) == []


def test_a_flag_can_only_be_waived_once_and_only_while_open(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    assert waive(client, s5["dean"], late["id"]).status_code == 200
    again = waive(client, s5["dean"], late["id"])
    assert again.status_code == 409 and "WAIVED" in again.json()["detail"]
    assert len(exceptions_of(pg, s5["sub"], "WAIVER")) == 1


def test_a_cleared_flag_cannot_be_waived(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    put(client, s5["fac_x1"], s5["sub"], 2)
    (flag,) = flags_of(pg, s5["sub"], "FORMAT")
    assert flag["status"] == "CLEARED"
    assert waive(client, s5["dean"], flag["id"]).status_code == 409


def test_hod_cannot_waive_in_a_closed_semester_but_the_dean_can(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))
    assert waive(client, s5["hod_x"], late["id"]).status_code == 409
    assert waive(client, s5["dean"], late["id"]).status_code == 200


def test_waived_lateness_never_comes_back(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    waive(client, s5["dean"], late["id"])
    put(client, s5["fac_x1"], s5["sub"], 2, at=DUE + 5 * DAY, clk=clk)
    sweep(client, s5["dean"])
    client.put(f"/semesters/{s5['sem']['id']}/deadlines", headers=as_user(client, s5["dean"]),
               json={"items": [{"template_id": str(s5["tpl"]["id"]), "due_at": (DUE - 3 * DAY).isoformat()}], "allow_past": True})
    assert [f["status"] for f in flags_of(pg, s5["sub"], "LATE")] == ["WAIVED"]


def test_a_waived_format_flag_does_not_stop_a_new_one_for_a_new_broken_file(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    (first,) = flags_of(pg, s5["sub"], "FORMAT")
    assert waive(client, s5["dean"], first["id"]).status_code == 200
    clk.set(DUE - HOUR + 5 * SEC)                                  # a later moment, so the order is not a tie
    r = upload(client, s5["fac_x1"], s5["sub"], "b2.pdf", TRUNCATED_PDF + b"2")
    assert r.json()["flags_raised"] == ["FORMAT"]
    assert [f["status"] for f in flags_of(pg, s5["sub"], "FORMAT")] == ["WAIVED", "OPEN"]


# ============================================================ bulk waiver
def test_dean_waives_every_open_late_flag_of_one_item_in_one_semester(client, pg, s5, clk):
    make_late(client, pg, s5, clk, "sub", "fac_x1", DUE + DAY)
    make_late(client, pg, s5, clk, "subx2", "fac_x2", DUE + 2 * DAY)
    make_late(client, pg, s5, clk, "suby", "fac_y1", DUE + 2 * DAY)
    make_late(client, pg, s5, clk, "sub2", "fac_x1", DUE + DAY)                      # different item: untouched
    r = post(client, s5["dean"], f"/semesters/{s5['sem']['id']}/waive-late", json={"template_id": str(s5["tpl"]["id"]), "reason": "deadline moved for everyone"})
    assert r.status_code == 200 and r.json() == {"waived": 3}
    assert [f["status"] for f in flags_of(pg, s5["sub"], "LATE") + flags_of(pg, s5["subx2"], "LATE") + flags_of(pg, s5["suby"], "LATE")] == ["WAIVED"] * 3
    assert flags_of(pg, s5["sub2"], "LATE")[0]["status"] == "OPEN"
    assert len(audit(pg, "flag.waive")) == 3 and audit(pg, "flags.waive_late_bulk")[0]["payload"]["count"] == 3


def test_bulk_waiver_twice_waives_nothing_new(client, pg, s5, clk):
    make_late(client, pg, s5, clk)
    body = {"template_id": str(s5["tpl"]["id"]), "reason": "deadline moved for everyone"}
    post(client, s5["dean"], f"/semesters/{s5['sem']['id']}/waive-late", json=body)
    assert post(client, s5["dean"], f"/semesters/{s5['sem']['id']}/waive-late", json=body).json() == {"waived": 0}


@pytest.mark.parametrize("who,status", [("hod_x", 403), ("fac_x1", 403)])
def test_bulk_waiver_is_dean_only(client, pg, s5, clk, who, status):
    make_late(client, pg, s5, clk)
    r = post(client, s5[who], f"/semesters/{s5['sem']['id']}/waive-late", json={"template_id": str(s5["tpl"]["id"]), "reason": GOOD_REASON})
    assert r.status_code == status and flags_of(pg, s5["sub"], "LATE")[0]["status"] == "OPEN"


def test_bulk_waiver_bad_input(client, s5):
    body = {"template_id": str(s5["tpl"]["id"]), "reason": GOOD_REASON}
    assert post(client, s5["dean"], f"/semesters/{RAND}/waive-late", json=body).status_code == 404
    assert post(client, s5["dean"], f"/semesters/{s5['sem']['id']}/waive-late", json={**body, "template_id": RAND}).status_code == 422
    assert post(client, s5["dean"], f"/semesters/{s5['sem']['id']}/waive-late", json={**body, "reason": "short"}).status_code == 422


# ============================================================ reading flags
def test_faculty_reads_own_flags_with_explanations_and_history(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    waive(client, s5["dean"], late["id"])
    r = get(client, s5["fac_x1"], f"/course-files/{s5['cf_x1']['id']}/flags")
    assert r.status_code == 200 and len(r.json()) == 1
    flag = r.json()[0]
    assert flag["kind"] == "LATE" and flag["status"] == "WAIVED" and "after the deadline" in flag["reason"]
    assert flag["template_code"] == s5["tpl"]["code"] and flag["detail"]["late_by_seconds"] == 86400
    (exc,) = flag["exceptions"]
    assert exc["kind"] == "WAIVER" and exc["reason"] == GOOD_REASON and exc["granted_by_name"] == s5["dean"]["full_name"]


def test_flag_list_status_filter(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    put(client, s5["fac_x1"], s5["sub"], 2)
    upload(client, s5["fac_x1"], s5["sub2"], "b.csv", b"   ")                         # empty csv: format problem
    path = f"/course-files/{s5['cf_x1']['id']}/flags"
    assert [f["status"] for f in get(client, s5["dean"], path, params={"status": "CLEARED"}).json()] == ["CLEARED"]
    assert [f["status"] for f in get(client, s5["dean"], path, params={"status": "OPEN"}).json()] == ["OPEN"]
    assert get(client, s5["dean"], path, params={"status": "WAIVED"}).json() == []
    assert get(client, s5["dean"], path, params={"status": "BOGUS"}).status_code == 422


@pytest.mark.parametrize("who,code", [("fac_x1", 200), ("hod_x", 200), ("dean", 200), ("fac_x2", 404), ("hod_y", 404), ("fac_y1", 404)])
def test_flag_reading_follows_the_scope_rules(client, pg, s5, clk, who, code):
    late = make_late(client, pg, s5, clk)
    assert get(client, s5[who], f"/course-files/{s5['cf_x1']['id']}/flags").status_code == code
    assert get(client, s5[who], f"/flags/{late['id']}").status_code == code


def test_flag_reading_needs_login_and_unknown_ids_are_404(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    assert client.get(f"/flags/{late['id']}").status_code == 401
    assert client.get(f"/course-files/{s5['cf_x1']['id']}/flags").status_code == 401
    assert get(client, s5["dean"], f"/flags/{RAND}").status_code == 404
    assert get(client, s5["dean"], f"/course-files/{RAND}/flags").status_code == 404


def test_single_flag_shows_every_exception_in_order(client, pg, s5, clk):
    late = make_late(client, pg, s5, clk)
    extend(client, s5["hod_x"], s5["sub"], DUE + 2 * DAY)       # waives the lateness automatically
    flag = get(client, s5["fac_x1"], f"/flags/{late['id']}").json()
    assert flag["status"] == "WAIVED" and [e["kind"] for e in flag["exceptions"]] == ["WAIVER"]
    assert flag["exceptions"][0]["granted_by_name"] == s5["hod_x"]["full_name"]


# ============================================================ manual evaluation endpoint
@pytest.mark.parametrize("who,code", [("hod_x", 403), ("fac_x1", 403)])
def test_only_the_dean_can_run_the_deadline_check(client, s5, who, code):
    assert sweep(client, s5[who]).status_code == code


def test_deadline_check_needs_login_and_known_semester(client, s5):
    assert client.post("/rules/evaluate").status_code == 401
    assert sweep(client, s5["dean"], semester_id=RAND).status_code == 404
    assert sweep(client, s5["dean"], semester_id="nope").status_code == 422


def test_deadline_check_result_counts(client, pg, s5, clk):
    clk.set(DUE + DAY)
    first = sweep(client, s5["dean"]).json()
    assert first == {"checked": 4, "raised": 4, "cleared": 0}
    assert sweep(client, s5["dean"]).json() == {"checked": 4, "raised": 0, "cleared": 0}
