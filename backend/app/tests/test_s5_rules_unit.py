"""S5: the decision function, with no database. Every boundary is exact to the second."""
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.rules import decide, effective_due, human_delta, human_time

UTC = timezone.utc
DUE = datetime(2099, 9, 30, 11, 30, tzinfo=UTC)          # 17:00 IST
SEC = timedelta(seconds=1)


def vid():
    return uuid.uuid4()


def ver(n, at, status="OK"):
    return {"id": vid(), "version_no": n, "uploaded_at": at, "validation_status": status}


def flag(kind, status="OPEN"):
    return {"id": vid(), "kind": kind, "status": status}


def run(*, due=DUE, ext=None, active=True, current=True, versions=(), flags=(), now=None, new=None):
    now = now or DUE + timedelta(days=1)
    return decide(due_at=due, ext_due=ext, template_active=active, semester_is_current=current,
                  versions=list(versions), flags=list(flags), now=now, new_version=new)


def kinds(plan):
    return sorted(r["kind"] for r in plan.raise_)


def cleared(plan):
    return sorted(c["kind"] for c in plan.clear)


def upload_plan(n, at, status="OK", versions=(), flags=(), now=None, **kw):
    """Plan for the moment version n was uploaded at time `at`."""
    new = ver(n, at, status)
    new["problem"] = "broken" if status == "FORMAT_FAILED" else None
    prior = list(versions)
    return run(versions=prior + [new], flags=flags, now=now or at, new=new, **kw), new


# ------------------------------------------------------------ helpers
def test_effective_due_is_the_latest_date_and_none_without_deadline():
    assert effective_due(DUE, None) == DUE
    assert effective_due(DUE, DUE + timedelta(days=2)) == DUE + timedelta(days=2)
    assert effective_due(DUE, DUE - timedelta(days=2)) == DUE            # an earlier extension never shortens
    assert effective_due(None, DUE) is None


@pytest.mark.parametrize("seconds,text", [(0, "0 seconds"), (1, "1 second"), (59, "59 seconds"), (60, "1 minute"),
                                          (130 * 60, "2 hours 10 minutes"), (3600, "1 hour"), (86400 + 4 * 3600, "1 day 4 hours"),
                                          (3 * 86400, "3 days"), (86400 + 5, "1 day")])
def test_human_delta(seconds, text):
    assert human_delta(seconds) == text


def test_human_time_is_shown_in_indian_time():
    assert human_time(DUE) == "30 Sep 2099 17:00 IST"


# ------------------------------------------------------------ LATE: the exact boundary
def test_upload_exactly_at_the_deadline_is_on_time():
    plan, _ = upload_plan(1, DUE)
    assert kinds(plan) == []


def test_one_second_after_the_deadline_is_late():
    plan, new = upload_plan(1, DUE + SEC)
    assert kinds(plan) == ["LATE"]
    late = plan.raise_[0]
    assert late["detail"]["late_by_seconds"] == 1 and late["version_id"] == new["id"]
    assert "1 second after the deadline" in late["reason"] and "17:00 IST" in late["reason"]


def test_one_microsecond_after_is_still_late_and_one_before_is_not():
    assert kinds(upload_plan(1, DUE + timedelta(microseconds=1))[0]) == ["LATE"]
    assert kinds(upload_plan(1, DUE - timedelta(microseconds=1))[0]) == []


def test_lateness_reason_is_explainable():
    plan, _ = upload_plan(1, DUE + timedelta(hours=2, minutes=10))
    assert plan.raise_[0]["reason"].startswith("Delivered 2 hours 10 minutes after the deadline")


def test_no_deadline_means_nothing_can_be_late_missing_or_incomplete():
    plan, _ = upload_plan(1, DUE + timedelta(days=400), due=None)
    assert kinds(plan) == []
    assert kinds(run(due=None, now=DUE + timedelta(days=400))) == []
    assert kinds(run(due=None, versions=[ver(1, DUE, "FORMAT_FAILED")], now=DUE + timedelta(days=400))) == []


def test_only_the_first_delivery_can_be_late():
    first = ver(1, DUE - timedelta(days=1))
    plan, _ = upload_plan(2, DUE + timedelta(days=3), versions=[first])
    assert kinds(plan) == []                                              # on-time first file, late replacement


def test_a_second_late_version_does_not_add_a_second_lateness_flag():
    first = ver(1, DUE + timedelta(hours=1))
    plan, _ = upload_plan(2, DUE + timedelta(days=3), versions=[first], flags=[flag("LATE")])
    assert kinds(plan) == []


@pytest.mark.parametrize("status", ["OPEN", "WAIVED"])
def test_an_existing_lateness_flag_blocks_a_new_one_whatever_its_status(status):
    plan, _ = upload_plan(1, DUE + timedelta(hours=1), flags=[flag("LATE", status)])
    assert "LATE" not in kinds(plan)


def test_an_extension_moves_the_lateness_line():
    ext = DUE + timedelta(days=2)
    assert kinds(upload_plan(1, DUE + timedelta(days=1), ext=ext)[0]) == []
    assert kinds(upload_plan(1, ext, ext=ext)[0]) == []
    assert kinds(upload_plan(1, ext + SEC, ext=ext)[0]) == ["LATE"]


def test_lateness_is_measured_against_the_deadline_in_force_at_upload_time():
    """A deadline moved EARLIER later must not turn an on-time upload into a late one: sweeps never raise LATE."""
    v1 = ver(1, DUE - timedelta(days=3))
    plan = run(due=DUE - timedelta(days=10), versions=[v1], now=DUE)      # no new_version: not an upload event
    assert "LATE" not in kinds(plan)


# ------------------------------------------------------------ broken files on time or late
def test_broken_file_on_time_gets_format_but_not_late_or_incomplete():
    plan, _ = upload_plan(1, DUE - timedelta(hours=1), "FORMAT_FAILED")
    assert kinds(plan) == ["FORMAT"] and plan.raise_[0]["reason"] == "broken"


def test_broken_on_time_then_fixed_after_the_deadline_is_never_late():
    broken = ver(1, DUE - timedelta(hours=1), "FORMAT_FAILED")
    fixed_at = DUE + timedelta(days=2)
    plan, _ = upload_plan(2, fixed_at, versions=[broken], flags=[flag("FORMAT"), flag("INCOMPLETE")])
    assert kinds(plan) == [] and cleared(plan) == ["FORMAT", "INCOMPLETE"]


def test_first_file_late_and_broken_gets_late_format_and_incomplete():
    plan, _ = upload_plan(1, DUE + timedelta(hours=3), "FORMAT_FAILED")
    assert kinds(plan) == ["FORMAT", "INCOMPLETE", "LATE"]


def test_second_broken_upload_does_not_duplicate_an_open_format_flag():
    plan, _ = upload_plan(2, DUE - SEC * 5, "FORMAT_FAILED", versions=[ver(1, DUE - SEC * 50, "FORMAT_FAILED")], flags=[flag("FORMAT")])
    assert kinds(plan) == []


def test_a_waived_format_flag_does_not_stop_a_new_one_for_a_new_broken_file():
    plan, _ = upload_plan(2, DUE - SEC * 5, "FORMAT_FAILED", versions=[ver(1, DUE - SEC * 50, "FORMAT_FAILED")], flags=[flag("FORMAT", "WAIVED")])
    assert kinds(plan) == ["FORMAT"]


# ------------------------------------------------------------ MISSING
def test_missing_needs_the_deadline_to_be_strictly_past():
    assert kinds(run(now=DUE)) == []
    assert kinds(run(now=DUE + SEC)) == ["MISSING"]
    assert kinds(run(now=DUE - SEC)) == []


def test_missing_reason_names_the_deadline():
    assert "Nothing was submitted by the deadline (30 Sep 2099 17:00 IST)" in run(now=DUE + SEC).raise_[0]["reason"]


def test_missing_follows_the_extension():
    ext = DUE + timedelta(days=2)
    assert kinds(run(ext=ext, now=DUE + timedelta(days=1))) == []
    assert kinds(run(ext=ext, now=ext + SEC)) == ["MISSING"]


@pytest.mark.parametrize("kw", [{"current": False}, {"active": False}])
def test_no_state_flags_in_a_closed_semester_or_for_a_switched_off_item(kw):
    assert kinds(run(**kw)) == []
    assert kinds(run(versions=[ver(1, DUE - SEC, "FORMAT_FAILED")], **kw)) == []


def test_missing_is_not_raised_twice_or_after_a_waiver():
    assert kinds(run(flags=[flag("MISSING")])) == []
    assert kinds(run(flags=[flag("MISSING", "WAIVED")])) == []


def test_missing_clears_when_a_file_arrives_even_if_it_is_broken():
    plan = run(versions=[ver(1, DUE + timedelta(hours=1))], flags=[flag("MISSING")])
    assert cleared(plan) == ["MISSING"]


def test_missing_clears_when_the_deadline_moves_forward():
    plan = run(due=DUE + timedelta(days=30), flags=[flag("MISSING")])
    assert cleared(plan) == ["MISSING"] and "no longer in the past" in plan.clear[0]["why"]


def test_missing_clears_when_the_item_is_switched_off_but_stays_otherwise():
    assert cleared(run(active=False, flags=[flag("MISSING")])) == ["MISSING"]
    assert cleared(run(flags=[flag("MISSING")])) == []


def test_missing_stays_in_a_closed_semester_as_history():
    assert cleared(run(current=False, flags=[flag("MISSING")])) == []


# ------------------------------------------------------------ INCOMPLETE
def test_incomplete_when_deadline_passed_and_newest_file_is_unusable():
    plan = run(versions=[ver(1, DUE - timedelta(days=1), "FORMAT_FAILED")])
    assert kinds(plan) == ["INCOMPLETE"] and plan.raise_[0]["detail"]["version_no"] == 1


def test_incomplete_looks_at_the_newest_file_not_at_any_file():
    ok_then_broken = [ver(1, DUE - timedelta(days=2)), ver(2, DUE - timedelta(days=1), "FORMAT_FAILED")]
    assert kinds(run(versions=ok_then_broken)) == ["INCOMPLETE"]
    broken_then_ok = [ver(1, DUE - timedelta(days=2), "FORMAT_FAILED"), ver(2, DUE - timedelta(days=1))]
    assert kinds(run(versions=broken_then_ok)) == []


def test_incomplete_not_before_the_deadline():
    assert kinds(run(versions=[ver(1, DUE - timedelta(days=2), "FORMAT_FAILED")], now=DUE)) == []


def test_incomplete_clears_when_a_valid_file_is_newest_or_deadline_moves():
    open_flag = flag("INCOMPLETE")
    assert cleared(run(versions=[ver(1, DUE - SEC, "FORMAT_FAILED"), ver(2, DUE + SEC)], flags=[open_flag])) == ["INCOMPLETE"]
    assert cleared(run(due=DUE + timedelta(days=9), versions=[ver(1, DUE - SEC, "FORMAT_FAILED")], flags=[open_flag])) == ["INCOMPLETE"]
    assert cleared(run(versions=[ver(1, DUE - SEC, "FORMAT_FAILED")], flags=[open_flag])) == []


def test_waived_incomplete_is_not_raised_again():
    assert kinds(run(versions=[ver(1, DUE - SEC, "FORMAT_FAILED")], flags=[flag("INCOMPLETE", "WAIVED")])) == []


# ------------------------------------------------------------ FORMAT clearing
def test_valid_newest_file_clears_open_format_at_any_time_but_never_late():
    flags = [flag("FORMAT"), flag("LATE")]
    plan = run(versions=[ver(1, DUE + timedelta(days=1), "FORMAT_FAILED"), ver(2, DUE + timedelta(days=5))], flags=flags,
               now=DUE + timedelta(days=5))
    assert cleared(plan) == ["FORMAT"]
    assert flags[1]["id"] not in {c["flag_id"] for c in plan.clear}


def test_format_stays_open_while_the_newest_file_is_still_broken():
    plan = run(versions=[ver(1, DUE - SEC, "FORMAT_FAILED")], flags=[flag("FORMAT")])
    assert cleared(plan) == []


def test_cleared_by_points_at_the_valid_version():
    good = ver(2, DUE + SEC)
    plan = run(versions=[ver(1, DUE - SEC, "FORMAT_FAILED"), good], flags=[flag("FORMAT")])
    assert plan.clear[0]["version_id"] == good["id"]


# ------------------------------------------------------------ invariants over thousands of random situations
def apply(flags, plan):
    flags = [dict(f) for f in flags]
    ids = {c["flag_id"] for c in plan.clear}
    for f in flags:
        if f["id"] in ids:
            f["status"] = "CLEARED"
    for r in plan.raise_:
        flags.append({"id": vid(), "kind": r["kind"], "status": "OPEN"})
    return flags


def random_case(rng):
    base = DUE
    due = None if rng.random() < 0.1 else base
    ext = base + timedelta(hours=rng.randint(1, 100)) if due and rng.random() < 0.3 else None
    n = rng.randint(0, 4)
    versions, t = [], base - timedelta(hours=rng.randint(0, 100))
    for i in range(n):
        t += timedelta(hours=rng.randint(0, 60), seconds=rng.randint(0, 3))
        versions.append(ver(i + 1, t, rng.choice(["OK", "FORMAT_FAILED"])))
    flags = []
    for kind in ("LATE", "MISSING", "INCOMPLETE", "FORMAT"):
        if rng.random() < 0.3:
            flags.append(flag(kind, rng.choice(["OPEN", "OPEN", "WAIVED", "CLEARED"] if kind != "LATE" else ["OPEN", "WAIVED"])))
    return dict(due=due, ext=ext, active=rng.random() > 0.15, current=rng.random() > 0.2, versions=versions, flags=flags,
                now=base + timedelta(hours=rng.randint(-50, 300), seconds=rng.randint(0, 3)))


def test_random_invariants_lateness_never_cleared_and_evaluation_is_idempotent():
    rng = random.Random(20260930)
    for _ in range(4000):
        case = random_case(rng)
        plan = run(**case)
        late_ids = {f["id"] for f in case["flags"] if f["kind"] == "LATE"}
        assert not ({c["flag_id"] for c in plan.clear} & late_ids), "a lateness flag was cleared"
        assert "LATE" not in kinds(plan), "a sweep raised a lateness flag"
        if not case["current"] or not case["active"]:
            assert not (set(kinds(plan)) & {"MISSING", "INCOMPLETE"}), "state flag raised where it must not be"
        after = apply(case["flags"], plan)
        again = run(**{**case, "flags": after})
        assert again.raise_ == [] and again.clear == [], f"not idempotent: {case}"
        opens = [f["kind"] for f in after if f["status"] == "OPEN" and f["kind"] in ("MISSING", "INCOMPLETE", "FORMAT", "LATE")]
        assert len(opens) == len(set(opens)), "duplicate open flag of one kind"


def test_random_invariants_for_upload_events():
    rng = random.Random(7)
    for _ in range(3000):
        case = random_case(rng)
        if not case["versions"]:
            continue
        new = case["versions"][-1]
        new = {**new, "problem": "x"}
        case = {**case, "now": new["uploaded_at"], "new": new}
        plan = run(**case)
        late_ids = {f["id"] for f in case["flags"] if f["kind"] == "LATE"}
        assert not ({c["flag_id"] for c in plan.clear} & late_ids)
        if "LATE" in kinds(plan):
            assert new["version_no"] == 1 and not late_ids
        after = apply(case["flags"], plan)
        again = run(**{**case, "flags": after, "new": None})
        assert again.raise_ == [] and again.clear == [], f"not idempotent after upload: {case}"
