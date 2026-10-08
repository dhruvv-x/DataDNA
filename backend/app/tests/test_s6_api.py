"""S6: the score through the real endpoints, step by step, with the real rule engine feeding it."""
import pytest

from app.core import score_store
from app.tests.api_fixtures import as_user, make_course_file, make_semester
from app.tests.s6_helpers import *  # noqa: F401,F403
from app.tests.s6_helpers import DAY, DUE, HOUR, TRUNCATED_PDF, get, item_of, post, put, put_weights, score, snaps, sweep, upload

PAST = DUE + DAY


# ---------------------------------------------------------------- the score itself
def test_fresh_course_file_with_deadlines_scores_100_all_pending(client, s6):
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["status"] == "SCORED" and body["total"] == 100.0 and body["items_pending"] == 2
    assert body["source"] == "live" and body["semester_is_current"] is True
    assert body["subject_code"] == s6["sub_x"]["code"]


def test_parts_and_weights_are_in_the_answer_and_content_off_is_explained(client, s6):
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["weights"]["completeness"] == 35 and body["content_active"] is False
    assert [body["parts"][p]["effective_weight"] for p in ("completeness", "timeliness", "format", "content")] == [38.89, 38.89, 22.22, 0.0]
    assert "Content checks are not live yet" in body["notes"][0]


def test_on_time_upload_keeps_100(client, s6, clk):
    assert put(client, s6["fac_x1"], s6["sub"], at=DUE - HOUR, clk=clk).status_code == 201
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["total"] == 100.0 and item_of(body, s6["sub"])["state"] == "OK" and body["items_pending"] == 1


def test_late_upload_costs_half_of_timeliness_and_has_a_plain_reason(client, s6, clk):
    assert put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk).status_code == 201
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["total"] == 80.56 and body["parts"]["timeliness"]["points"] == 19.45
    it = item_of(body, s6["sub"])
    assert it["state"] == "LATE" and it["lost"]["timeliness"] == 19.44 and it["lost"]["completeness"] == 0
    assert "Lateness never clears" in it["reasons"][0]


def test_lateness_never_recovers_by_a_better_upload(client, s6, clk):
    put(client, s6["fac_x1"], s6["sub"], n=1, at=PAST, clk=clk)
    put(client, s6["fac_x1"], s6["sub"], n=2, at=PAST + HOUR, clk=clk)
    assert score(client, s6["fac_x1"], s6["cf_x1"])["total"] == 80.56


def test_format_failed_file_costs_format_then_a_valid_file_restores_it(client, s6, clk, pg):
    clk.set(DUE - DAY)
    assert upload(client, s6["fac_x1"], s6["sub"], "x.pdf", TRUNCATED_PDF).status_code == 201
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["total"] == 88.89 and item_of(body, s6["sub"])["state"] == "FORMAT"
    assert put(client, s6["fac_x1"], s6["sub"], at=DUE - HOUR, clk=clk).status_code == 201
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["total"] == 100.0 and item_of(body, s6["sub"])["state"] == "OK"
    assert [float(s["total"]) for s in snaps(pg, s6["cf_x1"])] == [88.89, 100.0]


def test_format_failed_after_the_deadline_is_half_completeness_plus_zero_format(client, s6, clk):
    clk.set(PAST)
    assert upload(client, s6["fac_x1"], s6["sub"], "x.pdf", TRUNCATED_PDF).status_code == 201
    assert sweep(client, s6["dean"]).status_code == 200
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    it = item_of(body, s6["sub"])
    kinds = sorted(f["kind"] for f in it["flags"])
    assert kinds == ["FORMAT", "INCOMPLETE", "LATE"]
    assert it["credits"] == {"completeness": 0.5, "timeliness": 0.0, "format": 0.0, "content": 1.0}
    # the other item is MISSING after the sweep: completeness 0, timeliness 0
    other = item_of(body, s6["sub2"])
    assert other["state"] == "MISSING" and other["credits"]["completeness"] == 0
    assert body["parts"]["completeness"]["points"] == 9.72  # (0.5 + 0) / 2 of 38.89
    assert body["parts"]["format"]["points"] == 11.11


def test_missing_items_after_the_deadline_keep_only_format_points(client, s6, clk):
    clk.set(PAST)
    assert sweep(client, s6["dean"]).status_code == 200
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["total"] == 22.22 and body["parts"]["format"]["points"] == 22.22
    assert {i["state"] for i in body["items"]} == {"MISSING"}


def test_waiving_a_late_flag_restores_the_score_and_adds_a_snapshot(client, s6, clk, pg):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    flag = pg.execute("SELECT id FROM flags WHERE submission_id = %s AND kind = 'LATE'", (s6["sub"]["id"],)).fetchone()
    r = post(client, s6["hod_x"], f"/flags/{flag['id']}/waive", json={"reason": "network was down on campus"})
    assert r.status_code == 200, r.text
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["total"] == 100.0 and item_of(body, s6["sub"])["state"] == "WAIVED"
    assert [s["trigger"] for s in snaps(pg, s6["cf_x1"])] == ["upload", "waiver"]


def test_an_extension_that_covers_the_upload_restores_the_score(client, s6, clk, pg):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    assert score(client, s6["fac_x1"], s6["cf_x1"])["total"] == 80.56
    r = post(client, s6["dean"], f"/submissions/{s6['sub']['id']}/extensions",
             json={"new_due_at": (PAST + DAY).isoformat(), "reason": "exam duty, approved by the HOD"})
    assert r.status_code == 201, r.text
    assert score(client, s6["fac_x1"], s6["cf_x1"])["total"] == 100.0
    assert snaps(pg, s6["cf_x1"])[-1]["trigger"] == "extension"


def test_bulk_waiver_of_one_item_rescores_every_affected_course_file(client, s6, clk, pg):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    put(client, s6["fac_x2"], s6["subx2"], at=PAST, clk=clk)
    assert score(client, s6["fac_x2"], s6["cf_x2"])["total"] == 61.11  # one item, late: timeliness gone
    r = post(client, s6["dean"], f"/semesters/{s6['sem']['id']}/waive-late",
             json={"template_id": str(s6["tpl"]["id"]), "reason": "portal was down for the whole week"})
    assert r.status_code == 200 and r.json()["waived"] == 2
    assert score(client, s6["fac_x1"], s6["cf_x1"])["total"] == 100.0
    assert score(client, s6["fac_x2"], s6["cf_x2"])["total"] == 100.0
    # the history of BOTH course files recorded the waiver, not only the live answer
    for cf in (s6["cf_x1"], s6["cf_x2"]):
        assert [s["trigger"] for s in snaps(pg, cf)] == ["upload", "waiver"]


def test_switching_a_template_off_removes_it_from_the_score(client, s6, clk, pg):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    r = client.patch(f"/checklist-templates/{s6['tpl']['id']}", json={"is_active": False},
                     headers=as_user(client, s6["dean"]))
    assert r.status_code == 200, r.text
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["items_total"] == 1 and body["total"] == 100.0
    assert snaps(pg, s6["cf_x1"])[-1]["trigger"] == "template_change"


def test_no_deadline_anywhere_means_no_score_not_100(client, s6, pg):
    pg.execute("DELETE FROM checklist_deadlines WHERE semester_id = %s", (s6["sem"]["id"],))
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["status"] == "NO_DEADLINES" and body["total"] is None
    assert "No deadline is set" in body["notes"][-1]


def test_content_scoring_switch_uses_all_four_weights(client, s6, monkeypatch):
    monkeypatch.setenv("CONTENT_SCORING_ENABLED", "true")
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["content_active"] is True and body["notes"] == []
    assert [body["parts"][p]["effective_weight"] for p in ("completeness", "timeliness", "format", "content")] == [35.0, 35.0, 20.0, 10.0]


# ---------------------------------------------------------------- history = only real changes
def test_reading_never_writes_a_snapshot(client, s6, pg):
    for _ in range(3):
        score(client, s6["fac_x1"], s6["cf_x1"])
    assert snaps(pg, s6["cf_x1"]) == []


def test_snapshot_written_only_when_the_score_changed(client, s6, clk, pg):
    put(client, s6["fac_x1"], s6["sub"], n=1, at=DUE - HOUR, clk=clk)      # still 100, but the first snapshot
    put(client, s6["fac_x1"], s6["sub"], n=2, at=DUE - HOUR, clk=clk)      # new version, same score
    assert len(snaps(pg, s6["cf_x1"])) == 1
    clk.set(PAST)
    for _ in range(3):
        sweep(client, s6["dean"])                                             # sub2 becomes MISSING once
    rows = snaps(pg, s6["cf_x1"])
    assert [float(r["total"]) for r in rows] == [100.0, 61.12]


def test_two_identical_refreshes_make_one_snapshot(s6, pg, clk):
    now = clk.now
    a = score_store.refresh_course_files(pg, [s6["cf_x1"]["id"]], trigger="test", now=now)
    b = score_store.refresh_course_files(pg, [s6["cf_x1"]["id"]], trigger="test", now=now)
    assert (a["written"], b["written"], b["unchanged"]) == (1, 0, 1)


def test_history_endpoint_is_newest_first_and_scoped(client, s6, clk):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    post(client, s6["dean"], f"/submissions/{s6['sub']['id']}/extensions",
         json={"new_due_at": (PAST + DAY).isoformat(), "reason": "exam duty, approved by the HOD"})
    r = get(client, s6["fac_x1"], f"/course-files/{s6['cf_x1']['id']}/score/history")
    assert r.status_code == 200
    totals = [s["total"] for s in r.json()["snapshots"]]
    assert totals == [100.0, 80.56] and "breakdown" not in r.json()["snapshots"][0]
    assert get(client, s6["fac_x2"], f"/course-files/{s6['cf_x1']['id']}/score/history").status_code == 404


def test_snapshot_detail_has_the_full_breakdown_and_is_scoped(client, s6, clk, pg):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    sid = snaps(pg, s6["cf_x1"])[0]["id"]
    body = get(client, s6["fac_x1"], f"/score-snapshots/{sid}").json()
    assert body["total"] == 80.56 and len(body["items"]) == 2 and body["source"] == "snapshot"
    assert get(client, s6["hod_y"], f"/score-snapshots/{sid}").status_code == 404
    assert get(client, s6["fac_x2"], f"/score-snapshots/{sid}").status_code == 404


def test_sweep_is_a_safety_net_for_flags_added_by_other_code(client, s6, pg, clk):
    pg.execute("INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s, %s, 'MISMATCH', 'marks differ')",
               (s6["cf_x1"]["id"], s6["sub"]["id"]))
    assert sweep(client, s6["dean"]).status_code == 200
    rows = snaps(pg, s6["cf_x1"])
    assert rows and rows[-1]["trigger"] == "manual"  # content is off, so total stays 100 but the state is recorded
    assert rows[-1]["total"] == 100


# ---------------------------------------------------------------- scope
@pytest.mark.parametrize("who,expected", [("fac_x1", 200), ("hod_x", 200), ("dean", 200),
                                         ("fac_x2", 404), ("hod_y", 404), ("fac_y1", 404)])
def test_score_scope(client, s6, who, expected):
    assert get(client, s6[who], f"/course-files/{s6['cf_x1']['id']}/score").status_code == expected


def test_score_needs_login(client, s6):
    assert client.get(f"/course-files/{s6['cf_x1']['id']}/score").status_code == 401
    assert client.get("/scores").status_code == 401
    assert client.get("/score-weights").status_code == 401


def test_unknown_course_file_is_404(client, s6):
    import uuid
    assert get(client, s6["dean"], f"/course-files/{uuid.uuid4()}/score").status_code == 404


def test_score_list_is_scoped(client, s6):
    def ids(who):
        return {s["course_file_id"] for s in get(client, s6[who], "/scores").json()["scores"]}
    a, b, c = str(s6["cf_x1"]["id"]), str(s6["cf_x2"]["id"]), str(s6["cf_y1"]["id"])
    assert ids("fac_x1") == {a}
    assert ids("hod_x") == {a, b}
    assert ids("hod_y") == {c}
    assert ids("dean") == {a, b, c}


def test_score_list_filters_and_paging_and_shape(client, s6):
    r = get(client, s6["dean"], "/scores", params={"department_id": str(s6["x"]["id"]), "limit": 1})
    body = r.json()
    assert body["total"] == 2 and len(body["scores"]) == 1 and body["semester_id"] == str(s6["sem"]["id"])
    row = body["scores"][0]
    assert set(row["parts"]) == {"completeness", "timeliness", "format", "content"}
    assert {"total", "status", "items_total", "items_pending", "open_problems", "faculty_name", "subject_code"} <= set(row)
    assert get(client, s6["dean"], "/scores", params={"semester_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_score_list_without_a_current_semester_is_empty(client, s6, pg):
    pg.execute("UPDATE semesters SET is_current = false")
    body = get(client, s6["dean"], "/scores").json()
    assert body["scores"] == [] and body["semester_id"] is None


# ---------------------------------------------------------------- course file creation
def test_new_course_file_gets_its_first_snapshot(client, s6, pg):
    r = post(client, s6["dean"], "/course-files",
             json={"subject_id": str(s6["sub_x"]["id"]), "semester_id": str(s6["sem"]["id"]),
                   "faculty_id": str(s6["fac_x1"]["id"]), "division": "Z"})
    assert r.status_code == 201, r.text
    rows = pg.execute("SELECT * FROM score_snapshots WHERE course_file_id = %s", (r.json()["id"],)).fetchall()
    assert len(rows) == 1 and rows[0]["trigger"] == "course_file_created" and rows[0]["total"] == 100


# ---------------------------------------------------------------- weights
def test_everyone_logged_in_can_read_weights(client, s6):
    for who in ("fac_x1", "hod_x", "dean"):
        body = get(client, s6[who], "/score-weights").json()
        assert body["latest"]["completeness"] == 35 and body["content_scoring_enabled"] is False
        assert body["effective_for_current_semester"]["completeness"] == 38.89


@pytest.mark.parametrize("who", ["fac_x1", "hod_x"])
def test_only_dean_changes_weights(client, s6, who):
    assert put_weights(client, s6[who], 40, 30, 20, 10).status_code == 403


@pytest.mark.parametrize("args,why", [
    ((40, 30, 20, 20), "sum 110"),
    ((30, 30, 10, 20), "sum 90"),
    ((10, 10, 20, 60), "content over half"),
    ((-5, 55, 40, 10), "negative"),
    ((35, 35, 20, 10), "same as now"),
])
def test_bad_weights_are_refused(client, s6, args, why):
    assert put_weights(client, s6["dean"], *args).status_code in (409, 422), why


def test_weights_need_a_reason_and_no_unknown_fields(client, s6):
    assert put_weights(client, s6["dean"], 40, 30, 20, 10, reason="short").status_code == 422
    assert put_weights(client, s6["dean"], 40, 30, 20, 10, bonus=1).status_code == 422


def test_dean_sets_weights_append_only_audited_current_semester_unchanged(client, s6, pg, clk):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    before = score(client, s6["fac_x1"], s6["cf_x1"])
    r = put_weights(client, s6["dean"], 20, 60, 10, 10)
    assert r.status_code == 201, r.text
    assert r.json()["applied_to_current_semester"] is False
    assert r.json()["latest"]["timeliness"] == 60 and r.json()["current_semester"]["weights"]["timeliness"] == 35
    after = score(client, s6["fac_x1"], s6["cf_x1"])
    assert after["total"] == before["total"] and after["weights"]["id"] == before["weights"]["id"]
    assert pg.execute("SELECT count(*) AS n FROM score_weights").fetchone()["n"] == 2
    log = pg.execute("SELECT * FROM audit_log WHERE action = 'score_weights.set'").fetchall()
    assert len(log) == 1 and log[0]["payload"]["new"]["timeliness"] == 60 and log[0]["payload"]["apply_now"] is False


def test_apply_now_rescores_the_current_semester_and_records_why(client, s6, pg, clk):
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    r = put_weights(client, s6["dean"], 20, 60, 10, 10, apply_now=True)
    assert r.status_code == 201 and r.json()["applied_to_current_semester"] is True
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    # content off: 20/60/10 shared as 22.22/66.67/11.11; half of timeliness lost
    assert body["parts"]["timeliness"]["effective_weight"] == 66.67 and body["total"] == 66.67
    assert snaps(pg, s6["cf_x1"])[-1]["trigger"] == "weights_change"
    assert pg.execute("SELECT count(*) AS n FROM semester_weights WHERE semester_id = %s", (s6["sem"]["id"],)).fetchone()["n"] == 2
    hist = get(client, s6["fac_x1"], "/score-weights/history").json()
    assert len(hist["weights"]) == 2 and hist["semester_assignments"][0]["weights_id"] == hist["weights"][0]["id"]


def test_apply_now_without_a_current_semester_is_refused(client, s6, pg):
    pg.execute("UPDATE semesters SET is_current = false")
    assert put_weights(client, s6["dean"], 20, 60, 10, 10, apply_now=True).status_code == 409


# ---------------------------------------------------------------- semester close and history
def _new_semester_world(pg, s6):
    sem2 = make_semester(pg, "2027-28", "ODD")
    cf2 = make_course_file(pg, s6["sub_x"], sem2, s6["fac_x1"])
    from app.tests.s4_helpers import make_submission
    make_submission(pg, cf2, s6["tpl"])
    make_submission(pg, cf2, s6["tpl2"])
    for t in (s6["tpl"], s6["tpl2"]):
        pg.execute("INSERT INTO checklist_deadlines (semester_id, template_id, due_at) VALUES (%s, %s, %s)",
                   (sem2["id"], t["id"], DUE + 200 * DAY))
    return sem2, cf2


def test_closing_a_semester_writes_final_snapshots_with_a_last_deadline_check(client, s6, pg, clk):
    sem2, cf2 = _new_semester_world(pg, s6)
    clk.set(PAST)  # deadlines passed, nobody swept yet
    r = post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current")
    assert r.status_code == 200, r.text
    for cf in (s6["cf_x1"], s6["cf_x2"], s6["cf_y1"]):
        last = snaps(pg, cf)[-1]
        assert last["is_final"] and last["trigger"] == "semester_close"
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["source"] == "snapshot" and body["is_final"] is True and body["total"] == 22.22  # MISSING raised at close
    assert pg.execute("SELECT 1 FROM audit_log WHERE action = 'scores.semester_final'").fetchone()
    assert len(snaps(pg, cf2)) == 1 and snaps(pg, cf2)[0]["trigger"] == "semester_open"


def test_past_semester_never_drags_the_current_score(client, s6, pg, clk):
    sem2, cf2 = _new_semester_world(pg, s6)
    clk.set(PAST)
    post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current")
    assert score(client, s6["fac_x1"], s6["cf_x1"])["total"] == 22.22
    assert score(client, s6["fac_x1"], cf2)["total"] == 100.0
    listing = get(client, s6["fac_x1"], "/scores").json()
    assert [s["total"] for s in listing["scores"]] == [100.0]


def test_closed_semester_keeps_its_weights_when_weights_change_later(client, s6, pg, clk):
    sem2, _ = _new_semester_world(pg, s6)
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current")
    old = score(client, s6["fac_x1"], s6["cf_x1"])
    assert put_weights(client, s6["dean"], 20, 60, 10, 10, apply_now=True).status_code == 201
    after = score(client, s6["fac_x1"], s6["cf_x1"])
    assert after["total"] == old["total"] and after["weights"] == old["weights"]


def test_new_semester_uses_the_weights_in_force_when_it_became_current(client, s6, pg, clk):
    sem2, cf2 = _new_semester_world(pg, s6)
    put_weights(client, s6["dean"], 20, 60, 10, 10)            # next-semester weights
    post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current")
    assert score(client, s6["fac_x1"], cf2)["weights"]["timeliness"] == 60
    assert score(client, s6["fac_x1"], s6["cf_x1"])["weights"]["timeliness"] == 35


def test_bulk_changes_do_not_rewrite_closed_history(client, s6, pg, clk):
    sem2, _ = _new_semester_world(pg, s6)
    post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current")
    n = len(snaps(pg, s6["cf_x1"]))
    pg.execute("INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s, %s, 'FORMAT', 'bad file')",
               (s6["cf_x1"]["id"], s6["sub"]["id"]))
    r = score_store.refresh_course_files(pg, [s6["cf_x1"]["id"]], trigger="sweep", now=clk.now)
    assert r["skipped"] == 1 and len(snaps(pg, s6["cf_x1"])) == n
    r = score_store.refresh_course_files(pg, [s6["cf_x1"]["id"]], trigger="waiver", now=clk.now)
    assert r["written"] == 1 and snaps(pg, s6["cf_x1"])[-1]["trigger"] == "waiver"
    assert snaps(pg, s6["cf_x1"])[n - 1]["is_final"] is True  # the final snapshot stays in the history


def test_dean_can_correct_a_closed_semester_and_the_old_snapshot_stays(client, s6, pg, clk):
    sem2, _ = _new_semester_world(pg, s6)
    put(client, s6["fac_x1"], s6["sub"], at=PAST, clk=clk)
    post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current")
    flag = pg.execute("SELECT id FROM flags WHERE submission_id = %s AND kind = 'LATE'", (s6["sub"]["id"],)).fetchone()
    assert post(client, s6["dean"], f"/flags/{flag['id']}/waive", json={"reason": "audit found the portal was down"}).status_code == 200
    rows = snaps(pg, s6["cf_x1"])
    assert rows[-1]["trigger"] == "waiver" and rows[-1]["is_final"] is False
    assert any(r["is_final"] and r["total"] < rows[-1]["total"] for r in rows)
    assert score(client, s6["fac_x1"], s6["cf_x1"])["total"] > score_of_final(rows)


def score_of_final(rows):
    return next(float(r["total"]) for r in rows if r["is_final"])


def test_closed_semester_without_any_snapshot_is_computed_and_marked_unfrozen(client, s6, pg):
    pg.execute("UPDATE semesters SET is_current = false")
    body = score(client, s6["fac_x1"], s6["cf_x1"])
    assert body["source"] == "live_unfrozen" and body["total"] == 100.0


def test_make_current_of_the_same_semester_again_changes_nothing(client, s6, pg, clk):
    n = pg.execute("SELECT count(*) AS n FROM score_snapshots").fetchone()["n"]
    assert post(client, s6["dean"], f"/semesters/{s6['sem']['id']}/make-current").status_code == 200
    assert not pg.execute("SELECT 1 FROM score_snapshots WHERE is_final").fetchone()
    assert pg.execute("SELECT count(*) AS n FROM semester_weights WHERE semester_id = %s", (s6["sem"]["id"],)).fetchone()["n"] == 1
    assert pg.execute("SELECT count(*) AS n FROM score_snapshots").fetchone()["n"] >= n


def test_closed_semester_stays_on_the_weights_it_was_scored_with_even_without_a_semester_row(client, s5, pg, clk):
    """s5 (not s6): the old semester has NO semester_weights row, only its snapshots remember the weights."""
    sem2, _ = _new_semester_world(pg, s5)
    put(client, s5["fac_x1"], s5["sub"], at=PAST, clk=clk)
    post(client, s5["dean"], f"/semesters/{sem2['id']}/make-current")
    assert pg.execute("SELECT count(*) AS n FROM semester_weights WHERE semester_id = %s", (s5["sem"]["id"],)).fetchone()["n"] == 0
    old = score(client, s5["fac_x1"], s5["cf_x1"])
    assert put_weights(client, s5["dean"], 20, 60, 10, 10).status_code == 201   # the latest weights now differ
    assert pg.execute("SELECT count(*) AS n FROM score_weights").fetchone()["n"] == 2
    after = score(client, s5["fac_x1"], s5["cf_x1"])
    assert after["weights"]["id"] == old["weights"]["id"] and after["total"] == old["total"]
    # a correction on the closed semester is also scored with the frozen weights
    flag = pg.execute("SELECT id FROM flags WHERE submission_id = %s AND kind = 'LATE'", (s5["sub"]["id"],)).fetchone()
    assert post(client, s5["dean"], f"/flags/{flag['id']}/waive", json={"reason": "audit found the portal was down"}).status_code == 200
    assert snaps(pg, s5["cf_x1"])[-1]["weights_id"] == old["weights"]["id"]


def test_new_semester_with_overdue_items_is_flagged_and_scored_at_once(client, s6, pg, clk):
    sem2, cf2 = _new_semester_world(pg, s6)
    clk.set(DUE + 300 * DAY)  # the new semester's deadlines (DUE + 200 days) are already over
    assert post(client, s6["dean"], f"/semesters/{sem2['id']}/make-current").status_code == 200
    kinds = pg.execute("SELECT kind, status FROM flags WHERE course_file_id = %s", (cf2["id"],)).fetchall()
    assert sorted(k["kind"] for k in kinds) == ["MISSING", "MISSING"]  # no sweep was needed
    body = score(client, s6["fac_x1"], cf2)
    assert body["total"] == 22.22
    assert snaps(pg, cf2)[-1]["trigger"] == "semester_open" and float(snaps(pg, cf2)[-1]["total"]) == 22.22
