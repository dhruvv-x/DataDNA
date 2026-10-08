"""S3: user management, with every role boundary tested."""
import pytest

from app.core import security
from app.tests.api_fixtures import (  # noqa: F401
    PASSWORD, as_user, audit_actions, auth, client, db, login, make_department, make_user, new_client,
    token_for, uid, world,
)
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401


def body(department_id, role="FACULTY", email=None, **extra):
    return {"email": email or f"new.{uid()}@example.edu", "full_name": "New Person", "role": role,
            "department_id": str(department_id), **extra}


def create(client, who, **kw):
    return client.post("/users", headers=as_user(client, who), json=body(**kw))


def row(db_, user_id):
    return db_.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


# ---------------------------------------------------------------- create: who may create what
def test_dean_creates_faculty_in_department_with_existing_hod(client, world):
    r = create(client, world["dean"], department_id=world["x"]["id"], role="FACULTY")
    assert r.status_code == 201 and r.json()["role"] == "FACULTY"


def test_dean_creates_hod_in_department_without_one(client, world, db):
    fresh = make_department(db)
    r = create(client, world["dean"], department_id=fresh["id"], role="HOD")
    assert r.status_code == 201 and r.json()["role"] == "HOD"


def test_dean_creates_faculty_in_other_department(client, world):
    r = create(client, world["dean"], department_id=world["y"]["id"])
    assert r.status_code == 201 and r.json()["department_id"] == str(world["y"]["id"])


def test_nobody_can_create_a_dean_through_the_api(client, world):
    for who in (world["dean"], world["hod_x"], world["fac_x1"]):
        r = client.post("/users", headers=as_user(client, who), json=body(world["x"]["id"], role="DEAN"))
        assert r.status_code == 422, who["role"]


def test_hod_creates_faculty_in_own_department(client, world):
    r = create(client, world["hod_x"], department_id=world["x"]["id"])
    assert r.status_code == 201


def test_hod_cannot_create_faculty_in_other_department(client, world):
    assert create(client, world["hod_x"], department_id=world["y"]["id"]).status_code == 403


def test_hod_cannot_create_hod(client, world, db):
    fresh = make_department(db)
    assert create(client, world["hod_x"], department_id=world["x"]["id"], role="HOD").status_code == 403
    assert create(client, world["hod_x"], department_id=fresh["id"], role="HOD").status_code == 403


def test_faculty_cannot_create_anyone(client, world):
    assert create(client, world["fac_x1"], department_id=world["x"]["id"]).status_code == 403


def test_create_needs_login(client, world):
    assert client.post("/users", json=body(world["x"]["id"])).status_code == 401


def test_create_in_missing_department_is_404(client, world):
    import uuid
    assert create(client, world["dean"], department_id=uuid.uuid4()).status_code == 404


def test_created_user_gets_one_time_temporary_password(client, world, db):
    r = create(client, world["hod_x"], department_id=world["x"]["id"])
    data = r.json()
    temp = data["temporary_password"]
    assert len(temp) == 14 and "password_hash" not in data
    stored = row(db, data["id"])
    assert stored["must_change_password"] is True
    assert security.verify_password(temp, stored["password_hash"])
    assert login(client, {"email": data["email"]}, temp).json()["must_change_password"] is True


def test_temporary_password_is_not_stored_in_audit_or_returned_by_get(client, world, db):
    r = create(client, world["dean"], department_id=world["y"]["id"])
    temp = r.json()["temporary_password"]
    blob = " ".join(str(dict(x)) for x in db.execute("SELECT * FROM audit_log").fetchall())
    assert temp not in blob
    got = client.get(f"/users/{r.json()['id']}", headers=as_user(client, world["dean"]))
    assert temp not in got.text and "temporary_password" not in got.json()


def test_creation_is_audited_with_actor(client, world, db):
    r = create(client, world["hod_x"], department_id=world["x"]["id"])
    entry = db.execute(
        "SELECT * FROM audit_log WHERE entity_id = %s AND action = 'USER_CREATED'", (r.json()["id"],)
    ).fetchone()
    assert entry["actor_id"] == world["hod_x"]["id"] and entry["actor_role"] == "HOD"


def test_duplicate_email_is_409_even_with_different_case(client, world):
    first = create(client, world["dean"], department_id=world["x"]["id"], email="same.person@example.edu")
    again = create(client, world["dean"], department_id=world["y"]["id"], email="SAME.Person@Example.edu")
    assert first.status_code == 201 and again.status_code == 409


def test_second_active_hod_in_department_is_409(client, world):
    assert create(client, world["dean"], department_id=world["x"]["id"], role="HOD").status_code == 409


def test_duplicate_employee_code_is_409(client, world):
    a = create(client, world["dean"], department_id=world["x"]["id"], employee_code="EMP-1" + uid())
    code = a.json()["employee_code"]
    b = create(client, world["dean"], department_id=world["x"]["id"], employee_code=code)
    assert a.status_code == 201 and b.status_code == 409


def test_bad_email_and_blank_name_are_422(client, world):
    h = as_user(client, world["dean"])
    assert client.post("/users", headers=h, json={**body(world["x"]["id"]), "email": "nope"}).status_code == 422
    assert client.post("/users", headers=h, json={**body(world["x"]["id"]), "full_name": "  "}).status_code == 422


def test_failed_create_leaves_no_half_user(client, world, db):
    email = f"dup.{uid()}@example.edu"
    create(client, world["dean"], department_id=world["x"]["id"], email=email)
    create(client, world["dean"], department_id=world["y"]["id"], email=email)
    n = db.execute("SELECT count(*) AS n FROM users WHERE email = %s", (email,)).fetchone()["n"]
    assert n == 1


# ---------------------------------------------------------------- list scope
def ids(resp):
    return {u["id"] for u in resp.json()}


def test_dean_lists_everyone(client, world):
    r = client.get("/users", headers=as_user(client, world["dean"]))
    got = ids(r)
    for key in ("dean", "hod_x", "hod_y", "fac_x1", "fac_x2", "fac_y1"):
        assert str(world[key]["id"]) in got


def test_hod_lists_only_own_department(client, world):
    got = ids(client.get("/users", headers=as_user(client, world["hod_x"])))
    assert {str(world[k]["id"]) for k in ("hod_x", "fac_x1", "fac_x2")} <= got
    for k in ("hod_y", "fac_y1", "dean"):
        assert str(world[k]["id"]) not in got


def test_hod_cannot_widen_scope_with_department_filter(client, world):
    r = client.get("/users", headers=as_user(client, world["hod_x"]), params={"department_id": str(world["y"]["id"])})
    assert r.status_code == 200 and r.json() == []


def test_faculty_cannot_list_users(client, world):
    assert client.get("/users", headers=as_user(client, world["fac_x1"])).status_code == 403


def test_list_needs_login(client):
    assert client.get("/users").status_code == 401


def test_list_filters_and_paging(client, world):
    h = as_user(client, world["dean"])
    only_hod = client.get("/users", headers=h, params={"role": "HOD"}).json()
    assert only_hod and all(u["role"] == "HOD" for u in only_hod)
    assert len(client.get("/users", headers=h, params={"limit": 2}).json()) == 2
    assert client.get("/users", headers=h, params={"limit": 0}).status_code == 422
    assert client.get("/users", headers=h, params={"role": "ADMIN"}).status_code == 422


def test_list_never_exposes_password_hash(client, world):
    assert "password_hash" not in client.get("/users", headers=as_user(client, world["dean"])).text


# ---------------------------------------------------------------- get one
def test_faculty_sees_only_self(client, world):
    h = as_user(client, world["fac_x1"])
    assert client.get(f"/users/{world['fac_x1']['id']}", headers=h).status_code == 200
    assert client.get(f"/users/{world['fac_x2']['id']}", headers=h).status_code == 404
    assert client.get(f"/users/{world['fac_y1']['id']}", headers=h).status_code == 404


def test_hod_sees_own_department_not_others(client, world):
    h = as_user(client, world["hod_x"])
    assert client.get(f"/users/{world['fac_x2']['id']}", headers=h).status_code == 200
    assert client.get(f"/users/{world['fac_y1']['id']}", headers=h).status_code == 404
    assert client.get(f"/users/{world['dean']['id']}", headers=h).status_code == 404


def test_dean_sees_anyone(client, world):
    h = as_user(client, world["dean"])
    for k in ("fac_x1", "fac_y1", "hod_y", "dean"):
        assert client.get(f"/users/{world[k]['id']}", headers=h).status_code == 200


def test_out_of_scope_looks_like_missing(client, world):
    import uuid
    h = as_user(client, world["fac_x1"])
    hidden = client.get(f"/users/{world['fac_y1']['id']}", headers=h)
    missing = client.get(f"/users/{uuid.uuid4()}", headers=h)
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()


def test_bad_uuid_is_422(client, world):
    assert client.get("/users/not-a-uuid", headers=as_user(client, world["dean"])).status_code == 422


# ---------------------------------------------------------------- deactivate / reactivate
def set_active(client, who, target, value):
    return client.patch(f"/users/{target['id']}/active", headers=as_user(client, who), json={"is_active": value})


def test_dean_deactivates_anyone_but_self(client, world, db):
    assert set_active(client, world["dean"], world["fac_y1"], False).status_code == 200
    assert row(db, world["fac_y1"]["id"])["is_active"] is False
    assert set_active(client, world["dean"], world["hod_y"], False).status_code == 200
    assert set_active(client, world["dean"], world["dean"], False).status_code == 400
    assert row(db, world["dean"]["id"])["is_active"] is True


def test_hod_deactivates_faculty_in_own_department(client, world, db):
    assert set_active(client, world["hod_x"], world["fac_x1"], False).status_code == 200
    assert row(db, world["fac_x1"]["id"])["is_active"] is False


def test_hod_cannot_touch_other_department(client, world, db):
    assert set_active(client, world["hod_x"], world["fac_y1"], False).status_code == 404
    assert row(db, world["fac_y1"]["id"])["is_active"] is True


def test_hod_cannot_deactivate_self_or_dean(client, world):
    assert set_active(client, world["hod_x"], world["hod_x"], False).status_code == 403
    assert set_active(client, world["hod_x"], world["dean"], False).status_code == 404


def test_faculty_cannot_deactivate_anyone(client, world):
    assert set_active(client, world["fac_x1"], world["fac_x2"], False).status_code == 403
    assert set_active(client, world["fac_x1"], world["fac_x1"], False).status_code == 403


def test_deactivation_revokes_sessions_and_blocks_login(client, new_client, world, db):
    victim = new_client()
    token = login(victim, world["fac_x1"]).json()["access_token"]
    assert set_active(client, world["hod_x"], world["fac_x1"], False).status_code == 200  # if this is 401, the HOD token failed, not the revoke
    assert victim.get("/auth/me", headers=auth(token)).status_code == 401
    assert victim.post("/auth/refresh").status_code == 401
    assert login(client, world["fac_x1"]).status_code == 401
    assert "USER_DEACTIVATED" in audit_actions(db, world["fac_x1"]["id"])


def test_reactivation_works_and_unlocks(client, world, db):
    set_active(client, world["hod_x"], world["fac_x1"], False)
    db.execute("UPDATE users SET failed_login_count = 3, locked_until = now() + interval '1 hour' WHERE id = %s",
               (world["fac_x1"]["id"],))
    assert set_active(client, world["hod_x"], world["fac_x1"], True).status_code == 200
    r = row(db, world["fac_x1"]["id"])
    assert r["is_active"] and r["locked_until"] is None and r["failed_login_count"] == 0
    assert login(client, world["fac_x1"]).status_code == 200
    assert "USER_ACTIVATED" in audit_actions(db, world["fac_x1"]["id"])


def test_reactivating_a_second_hod_is_409(client, world, db):
    old = make_user(db, "HOD", world["x"]["id"], active=False)
    assert set_active(client, world["dean"], old, True).status_code == 409
    assert row(db, old["id"])["is_active"] is False


def test_setting_same_state_is_a_quiet_no_op(client, world, db):
    before = len(audit_actions(db))
    r = set_active(client, world["hod_x"], world["fac_x1"], True)
    assert r.status_code == 200
    assert "USER_ACTIVATED" not in audit_actions(db, world["fac_x1"]["id"])
    assert len(audit_actions(db)) == before + 1  # only the login of the HOD


def test_active_endpoint_needs_login(client, world):
    r = client.patch(f"/users/{world['fac_x1']['id']}/active", json={"is_active": False})
    assert r.status_code == 401


# ---------------------------------------------------------------- reset password
def reset(client, who, target):
    return client.post(f"/users/{target['id']}/reset-password", headers=as_user(client, who))


def test_dean_resets_anyone_else(client, world, db):
    r = reset(client, world["dean"], world["hod_y"])
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    stored = row(db, world["hod_y"]["id"])
    assert stored["must_change_password"] is True and security.verify_password(temp, stored["password_hash"])
    assert "PASSWORD_RESET" in audit_actions(db, world["hod_y"]["id"])


def test_hod_resets_faculty_in_own_department_only(client, world):
    assert reset(client, world["hod_x"], world["fac_x2"]).status_code == 200
    assert reset(client, world["hod_x"], world["fac_y1"]).status_code == 404


def test_hod_cannot_reset_hod_or_dean(client, world):
    assert reset(client, world["hod_x"], world["hod_x"]).status_code == 403
    assert reset(client, world["hod_x"], world["dean"]).status_code == 404


def test_faculty_cannot_reset_anyone(client, world):
    assert reset(client, world["fac_x1"], world["fac_x2"]).status_code == 403


def test_nobody_resets_own_password_this_way(client, world):
    assert reset(client, world["dean"], world["dean"]).status_code == 400


def test_reset_kills_old_sessions_and_old_password(client, new_client, world, db):
    victim = new_client()
    token = login(victim, world["fac_x1"]).json()["access_token"]
    reset(client, world["hod_x"], world["fac_x1"])
    assert victim.get("/auth/me", headers=auth(token)).status_code == 401
    assert victim.post("/auth/refresh").status_code == 401
    assert login(client, world["fac_x1"]).status_code == 401


def test_reset_clears_a_lockout(client, world, db):
    for i in range(5):
        login(client, world["fac_x1"], f"Wrong-Password-{i}")
    temp = reset(client, world["hod_x"], world["fac_x1"]).json()["temporary_password"]
    assert login(client, world["fac_x1"], temp).status_code == 200
