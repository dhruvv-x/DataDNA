"""S8: who sees which queries, the 'waiting for me' numbers, and what the server says each person may do."""
from app.tests.s8_helpers import *  # noqa: F401,F403
from app.tests.s8_helpers import MSG, act, decide, get, opened, post


def ids(resp):
    assert resp.status_code == 200, resp.text
    return {q["id"] for q in resp.json()["queries"]}


def test_every_role_sees_only_its_own_scope(client, s8):
    q1 = opened(client, s8["fac_x1"], s8["missing"])
    q2 = opened(client, s8["fac_x2"], s8["missing_x2"])
    q3 = opened(client, s8["fac_y1"], s8["missing_y"])
    assert ids(get(client, s8["fac_x1"], "/queries")) == {q1}
    assert ids(get(client, s8["fac_x2"], "/queries")) == {q2}
    assert ids(get(client, s8["hod_x"], "/queries")) == {q1, q2}
    assert ids(get(client, s8["hod_y"], "/queries")) == {q3}
    assert ids(get(client, s8["dean"], "/queries")) == {q1, q2, q3}


def test_detail_is_404_outside_scope(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    for who in ("fac_x2", "hod_y", "fac_y1"):
        assert get(client, s8[who], f"/queries/{qid}").status_code == 404
    for who in ("fac_x1", "hod_x", "dean"):
        assert get(client, s8[who], f"/queries/{qid}").status_code == 200
    assert get(client, s8["dean"], "/queries/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get(f"/queries/{qid}").status_code == 401


def test_detail_has_flag_context_and_named_steps(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    act(client, s8["hod_x"], qid, "reply", "Can you send the portal receipt?")
    body = get(client, s8["hod_x"], f"/queries/{qid}").json()
    assert body["flag_kind"] == "MISSING" and body["flag_status"] == "OPEN"
    assert body["subject_code"] == s8["sub_x"]["code"] and body["faculty_name"] == s8["fac_x1"]["full_name"]
    assert [(s["action"], s["actor_name"]) for s in body["steps"]] == [
        ("RAISE", s8["fac_x1"]["full_name"]), ("REPLY", s8["hod_x"]["full_name"])]
    assert body["template_code"] == s8["tpl2"]["code"]


def test_abilities_per_person(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    can = lambda who: get(client, s8[who], f"/queries/{qid}").json()["can"]  # noqa: E731
    assert can("fac_x1") == {"reply": True, "escalate": False, "resolve": False, "appeal": False, "override": False}
    assert can("hod_x") == {"reply": True, "escalate": True, "resolve": True, "appeal": False, "override": False}
    assert can("dean") == {"reply": True, "escalate": False, "resolve": True, "appeal": False, "override": True}
    act(client, s8["hod_x"], qid, "escalate", "this needs the Dean's decision")
    assert can("hod_x") == {"reply": False, "escalate": False, "resolve": False, "appeal": False, "override": False}
    assert can("dean") == {"reply": True, "escalate": False, "resolve": True, "appeal": False, "override": False}
    decide(client, s8["dean"], qid, "UPHELD", "Checked, the flag is correct")
    assert not any(can("dean").values()) and not any(can("fac_x1").values())


def test_the_server_answer_matches_the_abilities_it_reports(client, s8):
    """If 'can' says no, the action must be refused. If it says yes, it must work."""
    qid = opened(client, s8["fac_x1"], s8["missing"])
    assert get(client, s8["hod_x"], f"/queries/{qid}").json()["can"]["escalate"] is True
    assert act(client, s8["hod_x"], qid, "escalate", "this needs the Dean's decision").status_code == 200
    assert get(client, s8["hod_x"], f"/queries/{qid}").json()["can"]["escalate"] is False
    assert act(client, s8["hod_x"], qid, "escalate", "this needs the Dean's decision").status_code == 403


def test_filters(client, s8):
    q1 = opened(client, s8["fac_x1"], s8["missing"])
    q2 = opened(client, s8["fac_x2"], s8["missing_x2"])
    decide(client, s8["hod_x"], q2, "UPHELD", "The flag is correct, deadline was clear")
    act(client, s8["hod_x"], q1, "escalate", "this needs the Dean's decision")
    assert ids(get(client, s8["dean"], "/queries", params={"status": "OPEN"})) == {q1}
    assert ids(get(client, s8["dean"], "/queries", params={"status": "RESOLVED_UPHELD"})) == {q2}
    assert ids(get(client, s8["dean"], "/queries", params={"level": "DEAN"})) == {q1}
    assert ids(get(client, s8["dean"], "/queries", params={"course_file_id": str(s8["cf_x2"]["id"])})) == {q2}
    assert ids(get(client, s8["dean"], "/queries", params={"flag_id": str(s8["missing"]["id"])})) == {q1}
    assert get(client, s8["dean"], "/queries", params={"status": "NOPE"}).status_code == 422
    assert get(client, s8["dean"], "/queries", params={"level": "KING"}).status_code == 422


def test_open_queries_come_first_and_paging_works(client, s8):
    q1 = opened(client, s8["fac_x1"], s8["missing"])
    q2 = opened(client, s8["fac_x2"], s8["missing_x2"])
    decide(client, s8["hod_x"], q2, "UPHELD", "The flag is correct, deadline was clear")
    body = get(client, s8["dean"], "/queries").json()
    assert [q["id"] for q in body["queries"]] == [q1, q2] and body["total"] == 2
    page = get(client, s8["dean"], "/queries", params={"limit": 1, "offset": 1}).json()
    assert [q["id"] for q in page["queries"]] == [q2] and page["total"] == 2


def count(client, s8, who):
    resp = get(client, s8[who], "/queries/count")
    assert resp.status_code == 200
    return resp.json()


def test_waiting_for_me_follows_the_ball(client, s8):
    qid = opened(client, s8["fac_x1"], s8["missing"])
    # faculty just spoke: the ball is with the HOD
    assert count(client, s8, "hod_x") == {"waiting_for_me": 1, "open": 1}
    assert count(client, s8, "fac_x1") == {"waiting_for_me": 0, "open": 1}
    assert count(client, s8, "dean")["waiting_for_me"] == 0
    assert count(client, s8, "hod_y") == {"waiting_for_me": 0, "open": 0}
    # HOD answered: the ball is with the faculty
    act(client, s8["hod_x"], qid, "reply", "Can you send the portal receipt?")
    assert count(client, s8, "hod_x")["waiting_for_me"] == 0
    assert count(client, s8, "fac_x1")["waiting_for_me"] == 1
    # faculty answered: back to the HOD, then up to the Dean
    act(client, s8["fac_x1"], qid, "reply", "Receipt attached to the item, see version 1")
    assert count(client, s8, "hod_x")["waiting_for_me"] == 1
    act(client, s8["hod_x"], qid, "escalate", "this needs the Dean's decision")
    assert count(client, s8, "hod_x")["waiting_for_me"] == 0
    assert count(client, s8, "dean")["waiting_for_me"] == 1
    # Dean decided: nobody waits any more
    decide(client, s8["dean"], qid, "UPHELD", "Checked, the flag is correct")
    assert [count(client, s8, w)["waiting_for_me"] for w in ("hod_x", "fac_x1", "dean")] == [0, 0, 0]
    assert count(client, s8, "dean")["open"] == 0


def test_waiting_for_me_list_filter_matches_the_count(client, s8):
    q1 = opened(client, s8["fac_x1"], s8["missing"])
    opened(client, s8["fac_x2"], s8["missing_x2"])
    act(client, s8["hod_x"], q1, "reply", "Can you send the portal receipt?")
    mine = ids(get(client, s8["hod_x"], "/queries", params={"waiting_for_me": "true"}))
    assert len(mine) == count(client, s8, "hod_x")["waiting_for_me"] == 1 and q1 not in mine
    assert ids(get(client, s8["fac_x1"], "/queries", params={"waiting_for_me": "true"})) == {q1}


def test_hod_own_query_waits_for_the_dean_not_for_the_hod(client, s8, pg):
    from app.tests.api_fixtures import make_course_file
    from app.tests.s4_helpers import make_submission
    cf = make_course_file(pg, s8["sub_x"], s8["sem"], s8["hod_x"])
    make_submission(pg, cf, s8["tpl"])
    assert post(client, s8["dean"], "/rules/evaluate").status_code == 200
    flag = pg.execute("SELECT * FROM flags WHERE course_file_id = %s AND status = 'OPEN'", (cf["id"],)).fetchone()
    opened(client, s8["hod_x"], flag)
    assert count(client, s8, "hod_x")["waiting_for_me"] == 0
    assert count(client, s8, "dean")["waiting_for_me"] == 1


def test_count_route_is_not_mistaken_for_a_query_id(client, s8):
    assert get(client, s8["fac_x1"], "/queries/count").status_code == 200
