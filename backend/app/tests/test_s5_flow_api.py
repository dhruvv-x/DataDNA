"""S5: flags created by real uploads, sweeps and deadline changes, through the real endpoints."""
import pytest

from app.tests.s5_helpers import (CSV, DAY, DUE, GOOD_REASON, HOUR, SEC, TRUNCATED_PDF, audit, clk, csv_n, flags_of, get,  # noqa: F401
                                  kinds_open, make_pdf, post, put, s5, sweep, upload)
from app.tests.api_fixtures import as_user, client, make_semester, world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import make_template, set_current


# ------------------------------------------------------------ lateness at upload time
def test_upload_before_the_deadline_creates_no_flag(client, pg, s5, clk):
    r = put(client, s5["fac_x1"], s5["sub"], at=DUE - HOUR, clk=clk)
    assert r.status_code == 201 and r.json()["late"] is False and r.json()["flags_raised"] == []
    assert flags_of(pg, s5["sub"]) == []


def test_upload_exactly_at_the_deadline_is_on_time_and_one_second_later_is_late(client, pg, s5, clk):
    assert put(client, s5["fac_x1"], s5["sub"], at=DUE, clk=clk).json()["late"] is False
    r = put(client, s5["fac_x1"], s5["sub2"], at=DUE + SEC, clk=clk)
    assert r.json()["late"] is True and "lateness flag" in r.json()["message"]
    (flag,) = flags_of(pg, s5["sub2"], "LATE")
    assert flag["status"] == "OPEN" and flag["detail"]["late_by_seconds"] == 1
    assert flag["raised_at"] == DUE + SEC and flag["raised_by_version_id"] is not None


def test_late_reason_is_written_for_humans_and_flag_is_explained_in_the_audit(client, pg, s5, clk):
    put(client, s5["fac_x1"], s5["sub"], at=DUE + 2 * HOUR + 10 * 60 * SEC, clk=clk)
    (flag,) = flags_of(pg, s5["sub"], "LATE")
    assert flag["reason"] == "Delivered 2 hours 10 minutes after the deadline (30 Sep 2099 17:00 IST)."
    row = audit(pg, "flag.raise", flag["id"])[0]
    assert row["actor_id"] is None and row["actor_role"] == "SYSTEM" and row["payload"]["trigger"] == "upload"
    assert row["payload"]["kind"] == "LATE" and row["payload"]["by_user"] == str(s5["fac_x1"]["id"])


def test_lateness_stays_after_a_second_upload_and_is_not_duplicated(client, pg, s5, clk):
    put(client, s5["fac_x1"], s5["sub"], 1, at=DUE + HOUR, clk=clk)
    put(client, s5["fac_x1"], s5["sub"], 2, at=DUE + DAY, clk=clk)
    (flag,) = flags_of(pg, s5["sub"], "LATE")
    assert flag["status"] == "OPEN"


def test_on_time_first_file_then_late_replacement_is_not_late(client, pg, s5, clk):
    put(client, s5["fac_x1"], s5["sub"], 1, at=DUE - HOUR, clk=clk)
    put(client, s5["fac_x1"], s5["sub"], 2, at=DUE + DAY, clk=clk)
    assert flags_of(pg, s5["sub"], "LATE") == []


def test_dean_uploading_late_for_the_faculty_still_records_lateness(client, pg, s5, clk):
    r = put(client, s5["dean"], s5["sub"], at=DUE + DAY, clk=clk)
    assert r.status_code == 201 and r.json()["late"] is True and flags_of(pg, s5["sub"], "LATE", "OPEN")


def test_dean_uploading_on_time_for_the_faculty_is_fine(client, pg, s5, clk):
    assert put(client, s5["dean"], s5["sub"], at=DUE - HOUR, clk=clk).json()["late"] is False


def test_item_without_a_deadline_never_gets_timing_flags(client, pg, s5, clk):
    pg.execute("DELETE FROM checklist_deadlines WHERE template_id = %s", (s5["tpl"]["id"],))
    r = put(client, s5["fac_x1"], s5["sub"], at=DUE + 400 * DAY, clk=clk)
    assert r.json()["late"] is False and flags_of(pg, s5["sub"]) == []
    assert sweep(client, s5["dean"]).status_code == 200 and flags_of(pg, s5["subx2"]) == []


def test_upload_in_a_closed_semester_by_the_dean_still_judges_lateness(client, pg, s5, clk):
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))
    r = put(client, s5["dean"], s5["sub"], at=DUE + DAY, clk=clk)
    assert r.json()["late"] is True


# ------------------------------------------------------------ broken files and the format flag
def test_broken_file_on_time_is_format_only(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    r = upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    assert r.json()["flags_raised"] == ["FORMAT"]
    assert kinds_open(pg, s5["sub"]) == ["FORMAT"]


def test_broken_on_time_fixed_after_the_deadline_is_never_late_and_flag_clears(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    clk.set(DUE + 2 * DAY)
    sweep(client, s5["dean"])                                   # deadline passes with an unusable file
    assert kinds_open(pg, s5["sub"]) == ["FORMAT", "INCOMPLETE"]
    r = upload(client, s5["fac_x1"], s5["sub"], "g.pdf", make_pdf())
    assert sorted(r.json()["flags_cleared"]) == ["FORMAT", "INCOMPLETE"] and r.json()["late"] is False
    assert kinds_open(pg, s5["sub"]) == [] and flags_of(pg, s5["sub"], "LATE") == []


def test_first_file_late_and_broken_raises_late_format_and_incomplete(client, pg, s5, clk):
    clk.set(DUE + HOUR)
    r = upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    assert sorted(r.json()["flags_raised"]) == ["FORMAT", "INCOMPLETE", "LATE"]
    r2 = upload(client, s5["fac_x1"], s5["sub"], "g.pdf", make_pdf())
    assert sorted(r2.json()["flags_cleared"]) == ["FORMAT", "INCOMPLETE"]
    assert kinds_open(pg, s5["sub"]) == ["LATE"]                # lateness is the only thing that stays


def test_clearing_records_which_version_cleared_it(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    good = upload(client, s5["fac_x1"], s5["sub"], "g.pdf", make_pdf()).json()
    (flag,) = flags_of(pg, s5["sub"], "FORMAT")
    assert flag["status"] == "CLEARED" and str(flag["cleared_by_version_id"]) == good["id"] and flag["cleared_at"] == DUE - HOUR
    assert audit(pg, "flag.clear", flag["id"])[0]["payload"]["why"] == "a valid file arrived"


# ------------------------------------------------------------ sweep: missing and incomplete
def test_sweep_raises_missing_only_after_the_deadline(client, pg, s5, clk):
    clk.set(DUE)
    sweep(client, s5["dean"])
    assert flags_of(pg, s5["sub"]) == []                        # at the deadline itself: not yet
    clk.set(DUE + SEC)
    r = sweep(client, s5["dean"])
    assert r.status_code == 200 and r.json()["raised"] == 4      # four empty submissions in the fixture
    assert kinds_open(pg, s5["sub"]) == ["MISSING"] and kinds_open(pg, s5["suby"]) == ["MISSING"]


def test_sweep_twice_changes_nothing_the_second_time(client, pg, s5, clk):
    clk.set(DUE + DAY)
    first = sweep(client, s5["dean"]).json()
    second = sweep(client, s5["dean"]).json()
    assert first["raised"] > 0 and second["raised"] == 0 and second["cleared"] == 0
    assert len(flags_of(pg, s5["sub"], "MISSING")) == 1


def test_sweep_writes_audit_rows_with_the_actor(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    row = audit(pg, "rules.sweep")[0]
    assert row["actor_id"] == s5["dean"]["id"] and row["actor_role"] == "DEAN" and row["payload"]["trigger"] == "manual"
    (flag,) = flags_of(pg, s5["sub"], "MISSING")
    assert audit(pg, "flag.raise", flag["id"])[0]["payload"]["trigger"] == "manual"


def test_late_upload_replaces_missing_with_late(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["MISSING"]
    r = put(client, s5["fac_x1"], s5["sub"], at=DUE + DAY + HOUR, clk=clk)
    assert r.json()["late"] is True and r.json()["flags_cleared"] == ["MISSING"]
    assert kinds_open(pg, s5["sub"]) == ["LATE"]
    (missing,) = flags_of(pg, s5["sub"], "MISSING")
    assert missing["status"] == "CLEARED" and missing["cleared_by_version_id"] is not None


def test_missing_does_not_come_back_after_it_cleared(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    put(client, s5["fac_x1"], s5["sub"], at=DUE + DAY + HOUR, clk=clk)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["LATE"] and len(flags_of(pg, s5["sub"], "MISSING")) == 1


def test_sweep_incomplete_when_time_passes_over_a_broken_file(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["FORMAT"]
    clk.set(DUE + SEC)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["FORMAT", "INCOMPLETE"]
    (flag,) = flags_of(pg, s5["sub"], "INCOMPLETE")
    assert "not usable" in flag["reason"] and flag["detail"]["version_no"] == 1


def test_good_on_time_file_is_never_flagged_by_a_sweep(client, pg, s5, clk):
    put(client, s5["fac_x1"], s5["sub"], at=DUE - HOUR, clk=clk)
    clk.set(DUE + 30 * DAY)
    sweep(client, s5["dean"])
    assert flags_of(pg, s5["sub"]) == []


def test_closed_semesters_are_history_and_get_no_new_missing_flags(client, pg, s5, clk):
    clk.set(DUE + DAY)
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))       # our semester is no longer current
    assert sweep(client, s5["dean"]).json()["checked"] == 0
    explicit = sweep(client, s5["dean"], semester_id=str(s5["sem"]["id"]))
    assert explicit.status_code == 200 and explicit.json()["raised"] == 0
    assert flags_of(pg, s5["sub"]) == []


def test_missing_flag_in_a_semester_that_closed_stays_as_history(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))
    sweep(client, s5["dean"], semester_id=str(s5["sem"]["id"]))
    assert kinds_open(pg, s5["sub"]) == ["MISSING"]


def test_switched_off_item_is_not_flagged_and_its_flags_clear(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub2"]) == ["MISSING"]
    r = client.patch(f"/checklist-templates/{s5['tpl2']['id']}", headers=as_user(client, s5["dean"]), json={"is_active": False})
    assert r.status_code == 200 and kinds_open(pg, s5["sub2"]) == []
    (flag,) = flags_of(pg, s5["sub2"], "MISSING")
    assert audit(pg, "flag.clear", flag["id"])[0]["payload"]["why"] == "the item was switched off"
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub2"]) == []


def test_switching_an_item_back_on_flags_again_if_still_empty(client, pg, s5, clk):
    clk.set(DUE + DAY)
    patch = lambda on: client.patch(f"/checklist-templates/{s5['tpl2']['id']}", headers=as_user(client, s5["dean"]), json={"is_active": on})  # noqa: E731
    sweep(client, s5["dean"])
    patch(False)
    patch(True)
    assert kinds_open(pg, s5["sub2"]) == ["MISSING"]


# ------------------------------------------------------------ moving deadlines
def deadlines(client, who, sem, tpl, due, allow_past=False):
    return client.put(f"/semesters/{sem['id']}/deadlines", headers=as_user(client, who),
                      json={"items": [{"template_id": str(tpl["id"]), "due_at": due.isoformat()}], "allow_past": allow_past})


def test_a_deadline_in_the_past_is_refused_unless_you_say_it_is_intended(client, pg, s5, clk):
    clk.set(DUE)
    r = deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE - DAY)
    assert r.status_code == 422 and "allow_past" in r.json()["detail"]
    assert pg.execute("SELECT due_at FROM checklist_deadlines WHERE template_id = %s", (s5["tpl"]["id"],)).fetchone()["due_at"] == DUE
    assert flags_of(pg, s5["sub"]) == []
    assert deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE - DAY, allow_past=True).status_code == 200
    assert kinds_open(pg, s5["sub"]) == ["MISSING"]            # raised right away, because the Dean asked for it


def test_moving_a_deadline_forward_clears_missing(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    assert deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE + 10 * DAY).status_code == 200
    assert kinds_open(pg, s5["sub"]) == [] and kinds_open(pg, s5["sub2"]) == ["MISSING"]    # only the moved item
    (flag,) = flags_of(pg, s5["sub"], "MISSING")
    assert audit(pg, "flag.clear", flag["id"])[0]["payload"]["trigger"] == "deadline_change"


def test_moving_a_deadline_forward_never_erases_lateness(client, pg, s5, clk):
    put(client, s5["fac_x1"], s5["sub"], at=DUE + DAY, clk=clk)
    assert deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE + 10 * DAY).status_code == 200
    assert kinds_open(pg, s5["sub"]) == ["LATE"]
    sweep(client, s5["dean"])
    assert kinds_open(pg, s5["sub"]) == ["LATE"]


def test_moving_a_deadline_earlier_never_makes_an_on_time_upload_late(client, pg, s5, clk):
    put(client, s5["fac_x1"], s5["sub"], at=DUE - DAY, clk=clk)
    clk.set(DUE - HOUR)
    assert deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE - 2 * DAY, allow_past=True).status_code == 200
    sweep(client, s5["dean"])
    assert flags_of(pg, s5["sub"]) == []


def test_moving_a_deadline_earlier_flags_items_that_are_still_empty(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE - 2 * HOUR, allow_past=True)
    assert kinds_open(pg, s5["sub"]) == ["MISSING"] and kinds_open(pg, s5["sub2"]) == []


def test_the_deadline_change_only_touches_the_items_in_the_request(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE - 2 * HOUR, allow_past=True)
    assert audit(pg, "rules.sweep") == []                       # no sweep needed, direct evaluation


# ------------------------------------------------------------ the engine is the only thing that writes rule flags
def test_every_flag_change_is_in_the_audit_log(client, pg, s5, clk):
    clk.set(DUE - HOUR)
    upload(client, s5["fac_x1"], s5["sub"], "b.pdf", TRUNCATED_PDF)
    upload(client, s5["fac_x1"], s5["sub"], "g.pdf", make_pdf())
    for flag in flags_of(pg, s5["sub"]):
        assert audit(pg, "flag.raise", flag["id"])
        if flag["status"] == "CLEARED":
            assert audit(pg, "flag.clear", flag["id"])


def test_an_item_with_a_waived_missing_flag_is_not_flagged_again(client, pg, s5, clk):
    clk.set(DUE + DAY)
    sweep(client, s5["dean"])
    (flag,) = flags_of(pg, s5["sub"], "MISSING")
    assert post(client, s5["dean"], f"/flags/{flag['id']}/waive", json={"reason": GOOD_REASON}).status_code == 200
    sweep(client, s5["dean"])
    deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE + 2 * DAY, allow_past=True)
    deadlines(client, s5["dean"], s5["sem"], s5["tpl"], DUE - DAY, allow_past=True)
    assert [f["status"] for f in flags_of(pg, s5["sub"], "MISSING")] == ["WAIVED"]


def test_even_a_buggy_plan_cannot_clear_a_lateness_flag(client, pg, s5, clk, monkeypatch):
    """Second line of defence: if decide() ever asked for it, the engine and the database still refuse."""
    from app.core import rules

    put(client, s5["fac_x1"], s5["sub"], at=DUE + DAY, clk=clk)
    (late,) = flags_of(pg, s5["sub"], "LATE")
    evil = rules.Plan(clear=[{"flag_id": late["id"], "kind": "LATE", "version_id": None, "why": "bug"}])
    monkeypatch.setattr(rules, "decide", lambda **kw: evil)
    assert rules.evaluate_submission(pg, s5["sub"]["id"], now=DUE + 2 * DAY, trigger="test") == []
    assert flags_of(pg, s5["sub"], "LATE")[0]["status"] == "OPEN"
