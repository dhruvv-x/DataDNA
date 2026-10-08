"""S6: the score maths alone (no database). Every row of the design table has a test."""
import random
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.core import scoring

W = {"id": 1, "completeness": 35, "timeliness": 35, "format": 20, "content": 10}
DUE = datetime(2099, 1, 1, tzinfo=timezone.utc)
_n = 0


def flag(kind, status="OPEN", reason="because"):
    global _n
    _n += 1
    return {"id": f"f{_n}", "kind": kind, "status": status, "reason": reason}


def item(flags=(), has_file=False, due=DUE, due_passed=False, code="A"):
    global _n
    _n += 1
    return {"submission_id": f"s{_n}", "code": code, "title": "Item " + code, "sort_order": _n, "has_file": has_file,
            "newest_ok": has_file, "due_at": due, "due_passed": due_passed, "flags": list(flags)}


def credits(it):
    return {k: float(v) for k, v in scoring.score_item(it)["credits"].items()}


# ------------------------------------------------------------ per-item credits (the design table)
def test_valid_file_on_time_is_full_credit():
    r = scoring.score_item(item(has_file=True))
    assert r["state"] == "OK" and all(v == 1 for v in r["credits"].values())


def test_pending_no_file_not_due_is_full_credit():
    r = scoring.score_item(item())
    assert r["state"] == "PENDING" and all(v == 1 for v in r["credits"].values())
    assert "Not due yet" in r["reasons"][0]


def test_pending_without_any_deadline_says_so():
    r = scoring.score_item(item(due=None))
    assert r["state"] == "PENDING" and "No deadline" in r["reasons"][0]


def test_pending_after_deadline_but_not_flagged_yet_says_so():
    r = scoring.score_item(item(due_passed=True))
    assert r["state"] == "PENDING" and "not flagged it yet" in r["reasons"][0]


def test_missing_open_zeroes_completeness_and_timeliness_but_not_format():
    assert credits(item([flag("MISSING")])) == {"completeness": 0, "timeliness": 0, "format": 1, "content": 1}


def test_late_open_zeroes_only_timeliness():
    assert credits(item([flag("LATE")], has_file=True)) == {"completeness": 1, "timeliness": 0, "format": 1, "content": 1}


def test_incomplete_open_is_half_completeness_only():
    assert credits(item([flag("INCOMPLETE")], has_file=True)) == {"completeness": 0.5, "timeliness": 1, "format": 1, "content": 1}


def test_format_open_zeroes_only_format():
    assert credits(item([flag("FORMAT")], has_file=True)) == {"completeness": 1, "timeliness": 1, "format": 0, "content": 1}


def test_format_plus_incomplete_is_not_a_double_loss():
    it = item([flag("FORMAT"), flag("INCOMPLETE")], has_file=True)
    assert credits(it) == {"completeness": 0.5, "timeliness": 1, "format": 0, "content": 1}
    assert any("once more under Format" in r for r in scoring.score_item(it)["reasons"])


def test_late_plus_format_plus_incomplete_adds_up_part_by_part():
    c = credits(item([flag("LATE"), flag("FORMAT"), flag("INCOMPLETE")], has_file=True))
    assert c == {"completeness": 0.5, "timeliness": 0, "format": 0, "content": 1}


@pytest.mark.parametrize("kind", ["MISSING", "INCOMPLETE", "LATE", "FORMAT", "CONTENT", "MISMATCH"])
def test_waived_flag_is_full_credit(kind):
    r = scoring.score_item(item([flag(kind, "WAIVED")], has_file=True))
    assert all(v == 1 for v in r["credits"].values()) and r["state"] == "WAIVED"


@pytest.mark.parametrize("kind", ["MISSING", "INCOMPLETE", "FORMAT"])
def test_cleared_flag_is_full_credit(kind):
    r = scoring.score_item(item([flag(kind, "CLEARED")], has_file=True))
    assert all(v == 1 for v in r["credits"].values()) and r["state"] == "OK"
    assert any("cleared" in x for x in r["reasons"])


def test_late_waived_but_other_late_open_is_still_penalised_by_the_open_one():
    r = scoring.score_item(item([flag("LATE", "WAIVED"), flag("LATE", "OPEN")], has_file=True))
    assert r["credits"]["timeliness"] == 0


def test_anomaly_flags_never_count():
    r = scoring.score_item(item([flag("ANOMALY")], has_file=True))
    assert all(v == 1 for v in r["credits"].values()) and r["state"] == "OK"


@pytest.mark.parametrize("kind", ["CONTENT", "MISMATCH"])
def test_content_flags_zero_the_content_credit(kind):
    assert credits(item([flag(kind)], has_file=True))["content"] == 0


def test_state_precedence_missing_beats_everything():
    assert scoring.score_item(item([flag("LATE"), flag("MISSING")]))["state"] == "MISSING"
    assert scoring.score_item(item([flag("LATE"), flag("FORMAT")], has_file=True))["state"] == "FORMAT"


def test_every_open_flag_has_a_plain_reason_with_its_own_text():
    r = scoring.score_item(item([flag("LATE", reason="Arrived 2 days after the deadline.")], has_file=True))
    assert "Arrived 2 days after the deadline." in r["reasons"][0] and "never clears" in r["reasons"][0]


# ------------------------------------------------------------ apportion and weights
def test_apportion_adds_up_exactly():
    out = scoring.apportion([D(100) / 3] * 3, D(100))
    assert sum(out) == D(100) and sorted(out) == [D("33.33"), D("33.33"), D("33.34")]


def test_apportion_never_gives_a_cent_to_a_zero_entry():
    out = scoring.apportion([D(0), D("0.005"), D("0.004")], D("0.01"))
    assert out[0] == 0 and sum(out) == D("0.01")


def test_apportion_can_also_take_cents_away():
    out = scoring.apportion([D("10.01"), D("10.01")], D("20.00"))
    assert sum(out) == D("20.00") and all(v > 0 for v in out)


def test_effective_weights_with_content_on_are_the_weights():
    e = scoring.effective_weights(W, True)
    assert [float(e[p]) for p in scoring.PARTS] == [35, 35, 20, 10]


def test_effective_weights_with_content_off_share_the_ten_points():
    e = scoring.effective_weights(W, False)
    assert [float(e[p]) for p in scoring.PARTS] == [38.89, 38.89, 22.22, 0]
    assert sum(e.values()) == 100


def test_effective_weights_always_add_up_to_100():
    rnd = random.Random(7)
    for _ in range(300):
        c = rnd.randint(0, 50)
        a, b = rnd.randint(0, 100 - c), None
        rest = 100 - c - a
        b = rnd.randint(0, rest)
        f = rest - b
        if a + b + f < 50:
            continue
        w = {"completeness": a, "timeliness": b, "format": f, "content": c}
        for active in (True, False):
            assert sum(scoring.effective_weights(w, active).values()) == 100


def test_effective_weights_refuse_when_the_three_main_parts_are_all_zero():
    with pytest.raises(ValueError):
        scoring.effective_weights({"completeness": 0, "timeliness": 0, "format": 0, "content": 100}, False)


# ------------------------------------------------------------ whole course file
def test_all_good_scores_100_and_parts_add_up():
    r = scoring.compute([item(has_file=True, code="A"), item(has_file=True, code="B")], W, False)
    assert r["status"] == "SCORED" and r["total"] == 100.0
    assert sum(p["points"] for p in r["parts"].values()) == 100.0


def test_nothing_submitted_yet_but_deadlines_set_is_100_with_all_pending():
    r = scoring.compute([item(), item()], W, False)
    assert r["total"] == 100.0 and r["items_pending"] == 2


def test_one_late_item_of_two_costs_half_of_timeliness():
    r = scoring.compute([item([flag("LATE")], has_file=True), item(has_file=True)], W, False)
    assert r["parts"]["timeliness"]["points"] == 19.45 and r["parts"]["timeliness"]["lost"] == 19.44
    assert r["total"] == 80.56
    assert r["items"][0]["lost"]["timeliness"] == 19.44 and r["items"][1]["lost"]["timeliness"] == 0


def test_all_missing_keeps_only_the_format_points():
    r = scoring.compute([item([flag("MISSING")]), item([flag("MISSING")])], W, False)
    assert r["total"] == 22.22 and r["parts"]["completeness"]["points"] == 0 and r["parts"]["timeliness"]["points"] == 0


def test_format_failed_item_after_deadline_loses_format_and_half_completeness():
    r = scoring.compute([item([flag("FORMAT"), flag("INCOMPLETE")], has_file=True), item(has_file=True)], W, False)
    assert r["parts"]["completeness"]["points"] == 29.17
    assert r["parts"]["format"]["points"] == 11.11
    assert r["parts"]["timeliness"]["points"] == 38.89
    assert r["total"] == 79.17


def test_content_on_uses_all_four_weights_and_no_note():
    r = scoring.compute([item([flag("MISMATCH")], has_file=True), item(has_file=True)], W, True)
    assert r["parts"]["content"]["points"] == 5.0 and r["total"] == 95.0 and r["notes"] == []


def test_content_off_ignores_a_content_flag_and_says_why():
    r = scoring.compute([item([flag("MISMATCH")], has_file=True)], W, False)
    assert r["total"] == 100.0 and "Content checks are not live yet" in r["notes"][0] and "10 points" in r["notes"][0]


def test_no_deadline_and_no_flag_means_no_score():
    r = scoring.compute([item(due=None, has_file=True), item(due=None)], W, False)
    assert r["status"] == "NO_DEADLINES" and r["total"] is None
    assert all(p["points"] is None for p in r["parts"].values())


def test_an_anomaly_flag_alone_does_not_turn_a_no_deadline_file_into_a_scored_one():
    r = scoring.compute([item([flag("ANOMALY")], due=None, has_file=True)], W, False)
    assert r["status"] == "NO_DEADLINES" and r["items"][0]["flags"] == []


def test_no_deadline_but_a_flag_exists_is_still_scored():
    r = scoring.compute([item([flag("FORMAT")], due=None, has_file=True), item(due=None)], W, False)
    assert r["status"] == "SCORED" and r["parts"]["format"]["points"] == 11.11


def test_one_item_with_a_deadline_is_enough_to_score():
    r = scoring.compute([item(due=None), item()], W, False)
    assert r["status"] == "SCORED" and r["total"] == 100.0


def test_no_items_means_no_score():
    r = scoring.compute([], W, False)
    assert r["status"] == "NO_ITEMS" and r["total"] is None and r["items_total"] == 0


def test_lateness_cannot_recover_even_if_everything_else_is_fixed():
    items = [item([flag("LATE"), flag("FORMAT", "CLEARED")], has_file=True)]
    r = scoring.compute(items, W, False)
    assert r["parts"]["timeliness"]["points"] == 0 and r["parts"]["format"]["points"] == 22.22


def test_waiving_the_late_flag_restores_timeliness():
    r = scoring.compute([item([flag("LATE", "WAIVED")], has_file=True)], W, False)
    assert r["total"] == 100.0


def test_fingerprint_is_stable_and_ignores_wording():
    a = scoring.compute([item([flag("LATE", reason="one wording")], has_file=True)], W, False)
    b = {**a, "items": [{**a["items"][0], "reasons": ["other words"]}], "notes": ["x"]}
    assert scoring.fingerprint(b) == a["fingerprint"]


def test_fingerprint_changes_when_a_credit_weights_or_content_switch_changes():
    base = [item([flag("LATE")], has_file=True)]
    fp = scoring.compute(base, W, False)["fingerprint"]
    assert scoring.compute([item(has_file=True)], W, False)["fingerprint"] != fp
    assert scoring.compute(base, {**W, "id": 2, "timeliness": 40, "content": 5}, False)["fingerprint"] != fp
    assert scoring.compute(base, W, True)["fingerprint"] != fp


def test_invariants_hold_for_random_course_files():
    rnd = random.Random(2026)
    kinds = ["LATE", "MISSING", "INCOMPLETE", "FORMAT", "MISMATCH", "CONTENT"]
    for case in range(400):
        n = rnd.randint(1, 19)
        items = []
        for i in range(n):
            fl = [flag(rnd.choice(kinds), rnd.choice(["OPEN", "OPEN", "CLEARED", "WAIVED"])) for _ in range(rnd.randint(0, 3))]
            items.append(item(fl, has_file=rnd.random() < 0.7, due=DUE if rnd.random() < 0.8 else None, code=str(i)))
        w = rnd.choice([W, {"id": 3, "completeness": 40, "timeliness": 30, "format": 20, "content": 10},
                        {"id": 4, "completeness": 50, "timeliness": 50, "format": 0, "content": 0}])
        active = rnd.random() < 0.5
        r = scoring.compute(items, w, active)
        if r["status"] != "SCORED":
            continue
        parts = r["parts"]
        assert 0 <= r["total"] <= 100
        assert round(sum(p["points"] for p in parts.values()), 2) == r["total"]
        assert round(sum(p["effective_weight"] for p in parts.values()), 2) == 100.0
        for p in scoring.PARTS:
            assert round(parts[p]["points"] + parts[p]["lost"], 2) == parts[p]["effective_weight"]
            assert round(sum(i["lost"][p] for i in r["items"]), 2) == parts[p]["lost"], (case, p)
            assert all(i["lost"][p] >= 0 for i in r["items"])
