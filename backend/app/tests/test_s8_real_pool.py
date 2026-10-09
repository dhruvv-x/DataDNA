"""
S8 with the REAL connection pool and real commits: handlers really commit, and two people acting at the
same moment still leave one honest history. (Same pattern as the S5 and S6 real-pool tests.)
"""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core import clock, rules
from app.core.pool import get_pool
from app.main import app
from app.tests.api_fixtures import PASSWORD, password_hash, uid, world  # noqa: F401
from app.tests.pg_fixtures import pg_url  # noqa: F401
from app.tests.test_s5_real_pool import real  # noqa: F401  (fixture)

MSG = "please look again, the file reached the portal on time"


def bearer(email):
    resp = TestClient(app).post("/auth/login", data={"username": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def setup(real):
    """A MISSING flag in the real database, a faculty owner, a HOD of the same department, and the Dean."""
    admin = real["admin"]
    admin.execute("UPDATE semesters SET is_current = false")
    admin.execute("UPDATE semesters SET is_current = true WHERE id = %s", (real["sem"],))
    with get_pool().connection() as db:
        rules.sweep(db, now=clock.utcnow(), semester_id=real["sem"], trigger="test")
    flag = admin.execute("SELECT * FROM flags WHERE submission_id = %s AND kind = 'MISSING'", (real["sub"],)).fetchone()
    cf = admin.execute("SELECT * FROM course_files WHERE id = %s", (flag["course_file_id"],)).fetchone()
    fac = admin.execute("SELECT * FROM users WHERE id = %s", (cf["faculty_id"],)).fetchone()
    hod = admin.execute(
        "INSERT INTO users (email, password_hash, full_name, role, department_id) VALUES (%s,%s,%s,'HOD',%s) RETURNING *",
        (f"hod.{uid()}@example.edu", password_hash(), f"HOD {uid()}", cf["department_id"])).fetchone()
    return {"flag": flag, "fac": bearer(fac["email"]), "hod": bearer(hod["email"]), "dean": real["headers"]}


def test_a_raised_query_is_really_committed_with_its_step_and_audit_row(real):
    s = setup(real)
    resp = TestClient(app).post(f"/flags/{s['flag']['id']}/queries", headers=s["fac"], json={"message": MSG})
    assert resp.status_code == 201, resp.text
    admin, qid = real["admin"], resp.json()["id"]                       # admin is a different connection
    assert admin.execute("SELECT count(*) AS n FROM query_steps WHERE query_id = %s", (qid,)).fetchone()["n"] == 1
    assert admin.execute("SELECT count(*) AS n FROM audit_log WHERE action = 'query.raise' AND entity_id = %s",
                         (qid,)).fetchone()["n"] == 1


def test_six_raises_at_once_make_exactly_one_query(real):
    s = setup(real)

    def raise_it():
        return TestClient(app).post(f"/flags/{s['flag']['id']}/queries", headers=s["fac"], json={"message": MSG}).status_code

    with ThreadPoolExecutor(6) as ex:
        codes = [f.result() for f in [ex.submit(raise_it) for _ in range(6)]]
    assert sorted(codes) == [201] + [409] * 5
    assert real["admin"].execute("SELECT count(*) AS n FROM queries WHERE flag_id = %s", (s["flag"]["id"],)).fetchone()["n"] == 1


def test_hod_and_dean_deciding_at_the_same_moment_leave_one_decision_and_a_matching_flag(real):
    s = setup(real)
    qid = TestClient(app).post(f"/flags/{s['flag']['id']}/queries", headers=s["fac"], json={"message": MSG}).json()["id"]

    def decide(who, outcome):
        return TestClient(app).post(f"/queries/{qid}/resolve", headers=s[who],
                                    json={"outcome": outcome, "message": "decided at the very same moment"}).status_code

    with ThreadPoolExecutor(2) as ex:
        codes = [f.result() for f in [ex.submit(decide, "hod", "OVERTURNED"), ex.submit(decide, "dean", "UPHELD")]]
    assert sorted(codes) == [200, 409]
    admin = real["admin"]
    q = admin.execute("SELECT * FROM queries WHERE id = %s", (qid,)).fetchone()
    flag = admin.execute("SELECT status FROM flags WHERE id = %s", (s["flag"]["id"],)).fetchone()
    resolves = admin.execute("SELECT count(*) AS n FROM query_steps WHERE query_id = %s AND action = 'RESOLVE'", (qid,)).fetchone()["n"]
    waivers = admin.execute("SELECT count(*) AS n FROM exceptions WHERE flag_id = %s AND kind = 'WAIVER'", (s["flag"]["id"],)).fetchone()["n"]
    assert resolves == 1
    if q["status"] == "RESOLVED_OVERTURNED":
        assert flag["status"] == "WAIVED" and waivers == 1 and q["exception_id"] is not None
    else:
        assert q["status"] == "RESOLVED_UPHELD" and flag["status"] == "OPEN" and waivers == 0


def test_two_appeals_at_once_make_one_appeal(real):
    s = setup(real)
    client = TestClient(app)
    qid = client.post(f"/flags/{s['flag']['id']}/queries", headers=s["fac"], json={"message": MSG}).json()["id"]
    assert client.post(f"/queries/{qid}/resolve", headers=s["hod"],
                       json={"outcome": "UPHELD", "message": "the flag is correct, deadline was clear"}).status_code == 200

    def appeal():
        return TestClient(app).post(f"/queries/{qid}/appeal", headers=s["fac"],
                                    json={"message": "I have the receipt, please check it"}).status_code

    with ThreadPoolExecutor(2) as ex:
        codes = [f.result() for f in [ex.submit(appeal), ex.submit(appeal)]]
    assert sorted(codes) == [200, 409]
    assert real["admin"].execute("SELECT count(*) AS n FROM query_steps WHERE query_id = %s AND action = 'APPEAL'",
                                 (qid,)).fetchone()["n"] == 1
