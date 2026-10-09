"""S8: raise, reply, escalate, resolve, appeal, through the real endpoints with the real rule engine and score."""
from app.tests.api_fixtures import as_user, make_course_file, make_user  # noqa: F401
from app.tests.s5_helpers import audit, exceptions_of
from app.tests.s8_helpers import *  # noqa: F401,F403
from app.tests.s8_helpers import (DAY, MSG, act, decide, flag_row, get, opened, post, put, query_row, raise_q, score,
                                  snaps, steps_of, sweep)


# ================================================================ raise
def test_faculty_raises_a_query_on_own_open_flag(client, s8, pg):
    before = score(client, s8["fac_x1"], s8["cf_x1"])["total"]
    resp = raise_q(client, s8["fac_x1"], s8["missing"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "OPEN" and body["current_level"] == "HOD" and body["appealed"] is False
    assert [st["action"] for st in body["steps"]] == ["RAISE"] and body["steps"][0]["actor_role"] == "FACULTY"
    assert body["can"] == {"reply": True, "escalate": False, "resolve": False, "appeal": False, "override": False}
    assert flag_row(pg, s8["missing"])["status"] == "OPEN"                    # a query alone changes nothing
    assert score(client, s8["fac_x1"], s8["cf_x1"])["total"] == before
    assert [r["action"] for r in audit(pg, "query.raise", body["id"])] == ["query.raise"]


def test_late_flag_can_be_disputed_too(client, s8):
    assert raise_q(client, s8["fac_x1"], s8["late"]).status_code == 201


def test_other_faculty_cannot_see_or_raise_on_a_colleagues_flag(client, s8):
    assert raise_q(client, s8["fac_x2"], s8["missing"]).status_code == 404   # same department, still not theirs


def test_hod_and_dean_cannot_raise_a_query_but_can_see_the_flag(client, s8):
    assert raise_q(client, s8["hod_x"], s8["missing"]).status_code == 403
    assert raise_q(client, s8["dean"], s8["missing"]).status_code == 403


def test_hod_of_another_department_gets_404(client, s8):
    assert raise_q(client, s8["hod_y"], s8["missing"]).status_code == 404


def test_cannot_dispute_a_flag_that_is_not_open(client, s8, pg):
    assert post(client, s8["dean"], f"/flags/{s8['missing']['id']}/waive",
                json={"reason": "leave approved by the Dean"}).status_code == 200
    resp = raise_q(client, s8["fac_x1"], s8["missing"])
    assert resp.status_code == 409 and "WAIVED" in resp.json()["detail"]


def test_only_in_the_current_semester(client, s8, pg):
    pg.execute("UPDATE semesters SET is_current = false WHERE id = %s", (s8["sem"]["id"],))
    resp = raise_q(client, s8["fac_x1"], s8["missing"])
    assert resp.status_code == 409 and "closed" in resp.json()["detail"]


def test_a_flag_gets_one_query_only(client, s8):
    opened(client, s8["fac_x1"], s8["missing"])
    assert raise_q(client, s8["fac_x1"], s8["missing"]).status_code == 409


def test_a_decided_flag_is_not_argued_again(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["hod_x"], qid, "UPHELD").status_code == 200
    resp = raise_q(client, s8["fac_x1"], s8["missing"])
    assert resp.status_code == 409 and "already has a query" in resp.json()["detail"]


def test_message_rules(client, s8):
    assert raise_q(client, s8["fac_x1"], s8["missing"], "short").status_code == 422
    assert raise_q(client, s8["fac_x1"], s8["missing"], "   " + "x" * 5 + "   ").status_code == 422
    assert raise_q(client, s8["fac_x1"], s8["missing"], "x" * 2001).status_code == 422
    resp = post(client, s8["fac_x1"], f"/flags/{s8['missing']['id']}/queries", json={"message": MSG, "level": "DEAN"})
    assert resp.status_code == 422                                           # no way to pick the level yourself
    assert client.post(f"/flags/{s8['missing']['id']}/queries", json={"message": MSG}).status_code == 401


def test_hod_who_owns_a_course_file_cannot_review_their_own_query(client, s8, pg, clk):
    cf = make_course_file(pg, s8["sub_x"], s8["sem"], s8["hod_x"])
    from app.tests.s4_helpers import make_submission
    make_submission(pg, cf, s8["tpl"])
    assert sweep(client, s8["dean"]).status_code == 200
    flag = pg.execute("SELECT * FROM flags WHERE course_file_id = %s AND status = 'OPEN'", (cf["id"],)).fetchone()
    resp = raise_q(client, s8["hod_x"], flag)
    assert resp.status_code == 201 and resp.json()["current_level"] == "DEAN"
    qid = resp.json()["id"]
    assert decide(client, s8["hod_x"], qid, "OVERTURNED").status_code == 403    # not their own
    assert act(client, s8["hod_x"], qid, "reply", "I can add more detail here").status_code == 200
    assert decide(client, s8["dean"], qid, "OVERTURNED").status_code == 200


# ================================================================ reply
def test_hod_and_faculty_talk_in_order(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["hod_x"], qid, "reply", "Can you send the portal receipt?").status_code == 200
    assert act(client, s8["fac_x1"], qid, "reply", "Receipt attached to the item, see version 1").status_code == 200
    rows = steps_of(pg, qid)
    assert [(r["action"], r["actor_role"], r["level"]) for r in rows] == [
        ("RAISE", "FACULTY", "HOD"), ("REPLY", "HOD", "HOD"), ("REPLY", "FACULTY", "HOD")]
    assert len(audit(pg, "query.reply", qid)) == 2


def test_a_short_reply_is_fine_but_not_empty(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["hod_x"], qid, "reply", "ok!").status_code == 200
    assert act(client, s8["hod_x"], qid, "reply", "  ").status_code == 422


def test_outsiders_cannot_reply(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["fac_x2"], qid, "reply").status_code == 404
    assert act(client, s8["hod_y"], qid, "reply").status_code == 404
    assert act(client, s8["fac_y1"], qid, "reply").status_code == 404


def test_hod_cannot_reply_after_it_reached_the_dean(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["hod_x"], qid, "escalate", "I cannot decide this one").status_code == 200
    assert act(client, s8["hod_x"], qid, "reply").status_code == 403
    assert act(client, s8["fac_x1"], qid, "reply", "waiting for the Dean now").status_code == 200
    assert act(client, s8["dean"], qid, "reply", "looking at it today").status_code == 200


# ================================================================ escalate
def test_only_the_hod_escalates_and_only_once(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["fac_x1"], qid, "escalate").status_code == 403
    assert act(client, s8["dean"], qid, "escalate").status_code == 403
    assert act(client, s8["fac_x2"], qid, "escalate").status_code == 404
    resp = act(client, s8["hod_x"], qid, "escalate", "this needs the Dean's decision")
    assert resp.status_code == 200 and resp.json()["current_level"] == "DEAN"
    assert [(r["action"], r["level"]) for r in steps_of(pg, qid)] == [("RAISE", "HOD"), ("ESCALATE", "HOD")]
    assert len(audit(pg, "query.escalate", qid)) == 1
    assert act(client, s8["hod_x"], qid, "escalate").status_code == 403         # no longer theirs


# ================================================================ resolve
def test_faculty_cannot_resolve_their_own_query(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["fac_x1"], qid, "OVERTURNED").status_code == 403


def test_upheld_keeps_flag_and_score(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    before = score(client, s8["fac_x1"], s8["cf_x1"])["total"]
    resp = decide(client, s8["hod_x"], qid, "UPHELD", "The deadline was real, the flag is correct")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "RESOLVED_UPHELD" and body["resolved_level"] == "HOD" and body["flag_change"] == "none"
    assert flag_row(pg, s8["missing"])["status"] == "OPEN"
    assert exceptions_of(pg, s8["sub2"], "WAIVER") == []
    assert score(client, s8["fac_x1"], s8["cf_x1"])["total"] == before
    assert body["steps"][-1]["outcome"] == "UPHELD"


def test_overturned_waives_the_flag_with_a_reason_and_the_score_recovers(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    before = score(client, s8["fac_x1"], s8["cf_x1"])["total"]
    n_snaps = len(snaps(pg, s8["cf_x1"]))
    resp = decide(client, s8["hod_x"], qid, "OVERTURNED", "The portal was down, the faculty is right")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "RESOLVED_OVERTURNED" and body["flag_change"] == "waived"
    assert flag_row(pg, s8["missing"])["status"] == "WAIVED"
    [exc] = exceptions_of(pg, s8["sub2"], "WAIVER")
    assert exc["granted_by"] == s8["hod_x"]["id"]
    assert "Query overturned by the HOD" in exc["reason"] and "portal was down" in exc["reason"]
    assert query_row(pg, qid)["exception_id"] == exc["id"]
    after = score(client, s8["fac_x1"], s8["cf_x1"])["total"]
    assert after > before
    assert len(snaps(pg, s8["cf_x1"])) == n_snaps + 1
    assert audit(pg, "flag.waive", s8["missing"]["id"]) and len(audit(pg, "query.resolve", qid)) == 1


def test_overturned_late_flag_becomes_waived_and_stays_waived_after_a_sweep(client, s8, pg, clk):
    qid = opened(client, s8["fac_x1"], s8["late"])
    assert decide(client, s8["hod_x"], qid, "OVERTURNED", "The server clock was wrong that day").status_code == 200
    assert flag_row(pg, s8["late"])["status"] == "WAIVED"
    clk.set(clk.now + DAY)
    assert sweep(client, s8["dean"]).status_code == 200
    assert flag_row(pg, s8["late"])["status"] == "WAIVED"


def test_resolve_needs_a_real_message_and_outcome(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["hod_x"], qid, "UPHELD", "no").status_code == 422
    assert post(client, s8["hod_x"], f"/queries/{qid}/resolve",
                json={"outcome": "MAYBE", "message": MSG}).status_code == 422
    assert post(client, s8["hod_x"], f"/queries/{qid}/resolve", json={"message": MSG}).status_code == 422


def test_decided_query_accepts_nothing_more(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["hod_x"], qid, "OVERTURNED").status_code == 200
    assert act(client, s8["fac_x1"], qid, "reply").status_code == 409
    assert act(client, s8["hod_x"], qid, "escalate").status_code == 409
    assert decide(client, s8["dean"], qid, "UPHELD").status_code == 409


def test_hod_of_another_department_cannot_decide(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["hod_y"], qid, "OVERTURNED").status_code == 404


def test_hod_cannot_decide_at_the_dean_level_but_dean_can(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["hod_x"], qid, "escalate", "this needs the Dean's decision").status_code == 200
    assert decide(client, s8["hod_x"], qid, "OVERTURNED").status_code == 403
    resp = decide(client, s8["dean"], qid, "OVERTURNED", "Dean decision after reading both sides")
    assert resp.status_code == 200
    last = steps_of(pg, qid)[-1]
    assert (last["actor_role"], last["level"], last["override"]) == ("DEAN", "DEAN", False)
    assert query_row(pg, qid)["resolved_level"] == "DEAN"


def test_dean_can_step_in_at_the_hod_level_and_it_is_marked_as_override(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    body = get(client, s8["dean"], f"/queries/{qid}").json()
    assert body["can"]["resolve"] and body["can"]["override"] and not body["can"]["escalate"]
    assert act(client, s8["dean"], qid, "reply", "HOD is on leave, I am handling this").status_code == 200
    assert decide(client, s8["dean"], qid, "OVERTURNED", "Decided by the Dean while the HOD is away").status_code == 200
    rows = steps_of(pg, qid)
    assert [(r["action"], r["level"], r["override"]) for r in rows] == [
        ("RAISE", "HOD", False), ("REPLY", "HOD", True), ("RESOLVE", "HOD", True)]
    assert audit(pg, "query.resolve", qid)[0]["payload"]["override"] is True
    assert query_row(pg, qid)["resolved_level"] == "DEAN"                       # a Dean decision, so it is final


def test_hod_cannot_overturn_in_a_closed_semester_but_the_dean_can(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    pg.execute("UPDATE semesters SET is_current = false WHERE id = %s", (s8["sem"]["id"],))
    resp = decide(client, s8["hod_x"], qid, "OVERTURNED")
    assert resp.status_code == 409 and "Only the Dean" in resp.json()["detail"]
    assert decide(client, s8["hod_x"], qid, "UPHELD").status_code == 200        # keeping a flag is not a change
    qid2 = opened_in_closed(client, s8, pg)
    assert decide(client, s8["dean"], qid2, "OVERTURNED", "Dean corrects the closed semester").status_code == 200
    assert flag_row(pg, s8["late"])["status"] == "WAIVED"


def opened_in_closed(client, s8, pg):
    """A query opened while the semester was still current, decided after it closed."""
    pg.execute("UPDATE semesters SET is_current = true WHERE id = %s", (s8["sem"]["id"],))
    qid = opened(client, s8["fac_x1"], s8["late"])
    pg.execute("UPDATE semesters SET is_current = false WHERE id = %s", (s8["sem"]["id"],))
    return qid


def test_overturn_when_the_flag_was_already_waived_elsewhere_adds_no_second_waiver(client, s8, pg):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert post(client, s8["dean"], f"/flags/{s8['missing']['id']}/waive",
                json={"reason": "leave approved by the Dean"}).status_code == 200
    resp = decide(client, s8["hod_x"], qid, "OVERTURNED")
    assert resp.status_code == 200 and resp.json()["flag_change"] == "already waived"
    assert len(exceptions_of(pg, s8["sub2"], "WAIVER")) == 1
    assert query_row(pg, qid)["exception_id"] is None


# ================================================================ appeal
def upheld_by_hod(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["hod_x"], qid, "UPHELD", "The deadline was real, the flag is correct").status_code == 200
    return qid


def test_faculty_appeals_a_hod_decision_once_and_the_dean_decides(client, s8, pg):
    qid = upheld_by_hod(client, s8)
    body = get(client, s8["fac_x1"], f"/queries/{qid}").json()
    assert body["can"]["appeal"] is True
    resp = act(client, s8["fac_x1"], qid, "appeal", "I have the portal receipt, please look at it")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["status"], body["current_level"], body["appealed"]) == ("OPEN", "DEAN", True)
    assert body["resolved_at"] is None and body["resolved_by"] is None
    assert [r["action"] for r in steps_of(pg, qid)] == ["RAISE", "RESOLVE", "APPEAL"]
    assert len(audit(pg, "query.appeal", qid)) == 1
    assert act(client, s8["hod_x"], qid, "reply").status_code == 403            # the HOD is out of it now
    assert decide(client, s8["hod_x"], qid, "OVERTURNED").status_code == 403
    assert decide(client, s8["dean"], qid, "OVERTURNED", "Receipt checked, the faculty is right").status_code == 200
    assert flag_row(pg, s8["missing"])["status"] == "WAIVED"


def test_dean_upheld_after_appeal_is_final(client, s8):
    qid = upheld_by_hod(client, s8)
    assert act(client, s8["fac_x1"], qid, "appeal", "I have the portal receipt, please look at it").status_code == 200
    assert decide(client, s8["dean"], qid, "UPHELD", "Checked again, the flag stands").status_code == 200
    resp = act(client, s8["fac_x1"], qid, "appeal", "one more time please, it matters")
    assert resp.status_code == 409 and "final" in resp.json()["detail"]


def test_a_second_appeal_while_the_first_is_open_is_refused(client, s8):
    qid = upheld_by_hod(client, s8)
    assert act(client, s8["fac_x1"], qid, "appeal", "I have the portal receipt, please look at it").status_code == 200
    assert act(client, s8["fac_x1"], qid, "appeal", "asking again before an answer").status_code == 409


def test_appeal_window_is_seven_days(client, s8, clk):
    qid = upheld_by_hod(client, s8)
    clk.set(clk.now + 8 * DAY)
    resp = act(client, s8["fac_x1"], qid, "appeal", "I only saw the decision today")
    assert resp.status_code == 409 and "7 days" in resp.json()["detail"]
    assert get(client, s8["fac_x1"], f"/queries/{qid}").json()["can"]["appeal"] is False


def test_appeal_on_the_last_day_still_works(client, s8, clk):
    qid = upheld_by_hod(client, s8)
    clk.set(clk.now + 6 * DAY)
    assert act(client, s8["fac_x1"], qid, "appeal", "Just inside the window, please check").status_code == 200


def test_only_the_author_appeals(client, s8):
    qid = upheld_by_hod(client, s8)
    assert act(client, s8["fac_x2"], qid, "appeal").status_code == 404
    assert act(client, s8["hod_x"], qid, "appeal").status_code == 403
    assert act(client, s8["dean"], qid, "appeal").status_code == 403


def test_nothing_to_appeal_when_open_or_overturned_or_decided_by_the_dean(client, s8):
    open_q = opened(client, s8["fac_x1"], s8["missing"])
    assert act(client, s8["fac_x1"], open_q, "appeal").status_code == 409
    won = opened(client, s8["fac_x1"], s8["late"])
    assert decide(client, s8["hod_x"], won, "OVERTURNED").status_code == 200
    assert act(client, s8["fac_x1"], won, "appeal").status_code == 409


def test_a_dean_override_decision_cannot_be_appealed(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert decide(client, s8["dean"], qid, "UPHELD", "Decided by the Dean while the HOD is away").status_code == 200
    assert act(client, s8["fac_x1"], qid, "appeal", "I disagree with this decision").status_code == 409
