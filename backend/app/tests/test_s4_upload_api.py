"""S4: upload, versions, flags, who-may-upload, failure cleanup."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import settings, storage
from app.main import app
from app.tests.api_fixtures import (as_user, audit_actions, client, make_semester, make_user, new_client, uid, world)  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import (CSV, FAKE_EXE, TRUNCATED_PDF, make_docx, make_jpg, make_pdf, make_png, make_pptx,
                                  make_submission, make_template, make_xlsx, set_current, stored_files, upload)

ALL_EXT = ("pdf", "docx", "xlsx", "pptx", "csv", "txt", "png", "jpg", "jpeg")


@pytest.fixture
def up(pg, world):
    """Current semester; one item allowing everything (1 MB cap); submissions for 3 course files."""
    set_current(pg, world["sem"])
    w = dict(world)
    w["tpl"] = make_template(pg, exts=ALL_EXT, max_mb=1)
    w["tpl_pdf"] = make_template(pg, exts=("pdf",), max_mb=5)
    w["sub1"] = make_submission(pg, world["cf_x1"], w["tpl"])
    w["sub1_pdf"] = make_submission(pg, world["cf_x1"], w["tpl_pdf"])
    w["sub2"] = make_submission(pg, world["cf_x2"], w["tpl"])
    w["subY"] = make_submission(pg, world["cf_y1"], w["tpl"])
    return w


def versions(pg, sub):
    return pg.execute("SELECT * FROM submission_versions WHERE submission_id=%s ORDER BY version_no", (sub["id"],)).fetchall()


def flags(pg, sub, kind=None):
    q, a = "SELECT * FROM flags WHERE submission_id=%s", [sub["id"]]
    if kind:
        q, a = q + " AND kind=%s", a + [kind]
    return pg.execute(q + " ORDER BY raised_at, id", a).fetchall()


def on_disk():
    return stored_files(settings.storage_dir())


# ------------------------------------------------------------ a good upload
def test_faculty_uploads_a_good_file(client, pg, up):
    data = make_pdf()
    r = upload(client, up["fac_x1"], up["sub1_pdf"], "Lesson Plan.pdf", data)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["version_no"] == 1 and v["validation_status"] == "OK" and v["is_current"] is True
    assert v["sha256"] == hashlib.sha256(data).hexdigest() and v["size_bytes"] == len(data)
    assert v["uploaded_by"] == str(up["fac_x1"]["id"]) and v["uploaded_by_role"] == "FACULTY" and v["on_behalf_reason"] is None
    assert v["original_filename"] == "Lesson Plan.pdf" and v["format_flag_raised"] is False
    row = versions(pg, up["sub1_pdf"])[0]
    assert Path(settings.storage_dir(), row["storage_key"]).read_bytes() == data      # real bytes on disk
    assert row["storage_key"] == f"{up['cf_x1']['id']}/{up['sub1_pdf']['id']}/v1_{v['sha256'][:12]}.pdf"
    cur = pg.execute("SELECT current_version_id FROM submissions WHERE id=%s", (up["sub1_pdf"]["id"],)).fetchone()
    assert cur["current_version_id"] == row["id"]


@pytest.mark.parametrize("name,data", [
    ("a.xlsx", make_xlsx()), ("a.docx", make_docx()), ("a.pptx", make_pptx()), ("a.csv", CSV),
    ("a.txt", b"notes"), ("a.png", make_png()), ("a.jpg", make_jpg()), ("a.jpeg", make_jpg()), ("A.PDF", make_pdf()),
])
def test_every_supported_type_is_accepted(client, pg, up, name, data):
    r = upload(client, up["fac_x1"], up["sub1"], name, data)
    assert r.status_code == 201 and r.json()["validation_status"] == "OK", r.text


def test_upload_is_audited_with_the_hash(client, pg, up):
    r = upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV)
    row = pg.execute("SELECT * FROM audit_log WHERE action='submission.upload' AND entity_id=%s", (str(up["sub1"]["id"]),)).fetchone()
    assert row["actor_id"] == up["fac_x1"]["id"] and row["actor_role"] == "FACULTY"
    assert row["payload"]["sha256"] == r.json()["sha256"] and row["payload"]["version_no"] == 1


def test_the_users_file_name_is_never_used_on_disk(client, pg, up):
    r = upload(client, up["fac_x1"], up["sub1"], "../../../etc/evil.csv", CSV)
    assert r.status_code == 201 and r.json()["original_filename"] == "evil.csv"
    assert all("evil" not in str(p) and ".." not in p.name for p in on_disk())
    assert all(str(p).startswith(settings.storage_dir()) for p in on_disk())


def test_uploaded_at_is_the_time_the_file_arrived(client, pg, up, monkeypatch):
    moment = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    from types import SimpleNamespace

    headers = as_user(client, up["fac_x1"])                      # log in first with the real clock
    monkeypatch.setattr("app.api.submissions.clock", SimpleNamespace(utcnow=lambda: moment))
    pg.execute("INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s,%s,'FORMAT','x')", (up["cf_x1"]["id"], up["sub1"]["id"]))
    r = client.post(f"/submissions/{up['sub1']['id']}/versions", headers=headers, files={"file": ("a.csv", CSV)})
    assert r.status_code == 201 and datetime.fromisoformat(r.json()["uploaded_at"]) == moment
    assert flags(pg, up["sub1"], "FORMAT")[0]["cleared_at"] == moment      # flag times use the same moment


# ------------------------------------------------------------ versions
def test_reupload_makes_version_2_and_keeps_version_1_forever(client, pg, up):
    first = upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV).json()
    second = upload(client, up["fac_x1"], up["sub1"], "b.csv", CSV + b"Kiran,9\n").json()
    assert (first["version_no"], second["version_no"]) == (1, 2)
    rows = versions(pg, up["sub1"])
    assert [r["version_no"] for r in rows] == [1, 2] and len(on_disk()) == 2
    assert Path(settings.storage_dir(), rows[0]["storage_key"]).read_bytes() == CSV
    cur = pg.execute("SELECT current_version_id FROM submissions WHERE id=%s", (up["sub1"]["id"],)).fetchone()
    assert cur["current_version_id"] == rows[1]["id"]
    history = client.get(f"/submissions/{up['sub1']['id']}/versions", headers=as_user(client, up["fac_x1"])).json()
    assert [(h["version_no"], h["is_current"]) for h in history] == [(2, True), (1, False)]


def test_exactly_the_same_file_again_is_refused_and_nothing_changes(client, pg, up):
    upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV)
    r = upload(client, up["fac_x1"], up["sub1"], "other-name.csv", CSV)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "same_file"
    assert len(versions(pg, up["sub1"])) == 1 and len(on_disk()) == 1
    assert "submission.upload_rejected" in audit_actions(pg, up["sub1"]["id"])


def test_going_back_to_an_older_file_is_allowed(client, pg, up):
    a, b = CSV, CSV + b"x,1\n"
    upload(client, up["fac_x1"], up["sub1"], "a.csv", a)
    upload(client, up["fac_x1"], up["sub1"], "b.csv", b)
    r = upload(client, up["fac_x1"], up["sub1"], "a.csv", a)
    assert r.status_code == 201 and r.json()["version_no"] == 3


def test_same_bytes_in_two_different_checklist_items_are_both_stored(client, pg, up):
    assert upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV).status_code == 201
    other = make_submission(pg, up["cf_x1"], make_template(pg, exts=("csv",)))
    assert upload(client, up["fac_x1"], other, "a.csv", CSV).status_code == 201


def test_version_list_is_scoped(client, pg, up):
    upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV)
    path = f"/submissions/{up['sub1']['id']}/versions"
    code = lambda who: client.get(path, headers=as_user(client, up[who])).status_code  # noqa: E731
    assert code("fac_x1") == code("hod_x") == code("dean") == 200
    assert code("fac_x2") == code("hod_y") == code("fac_y1") == 404
    assert client.get(path).status_code == 401


# ------------------------------------------------------------ refused outright: nothing stored
@pytest.mark.parametrize("name,data,status,code", [
    ("virus.exe", FAKE_EXE, 415, "extension_not_allowed"),
    ("report.docx", make_docx(), 415, "extension_not_allowed"),     # pdf-only item
    ("fake.pdf", FAKE_EXE, 415, "content_mismatch"),
    ("fake.pdf", b"this is not a pdf", 415, "content_mismatch"),
    ("noext", make_pdf(), 415, "no_extension"),
    ("empty.pdf", b"", 422, "empty_file"),
])
def test_bad_type_is_refused_and_nothing_is_stored(client, pg, up, name, data, status, code):
    r = upload(client, up["fac_x1"], up["sub1_pdf"], name, data)
    assert r.status_code == status and r.json()["detail"]["code"] == code
    assert versions(pg, up["sub1_pdf"]) == [] and on_disk() == []
    assert not list((Path(settings.storage_dir()) / ".tmp").iterdir())
    assert "submission.upload_rejected" in audit_actions(pg, up["sub1_pdf"]["id"])
    assert pg.execute("SELECT current_version_id FROM submissions WHERE id=%s", (up["sub1_pdf"]["id"],)).fetchone()["current_version_id"] is None


def test_size_limit_is_exact(client, pg, up):
    limit = 1024 * 1024
    ok = upload(client, up["fac_x1"], up["sub1"], "ok.csv", b"a,b\n" + b"1" * (limit - 4))
    assert ok.status_code == 201 and ok.json()["size_bytes"] == limit
    big = upload(client, up["fac_x1"], up["sub1"], "big.csv", b"a,b\n" + b"1" * (limit - 3))
    assert big.status_code == 413 and big.json()["detail"]["code"] == "too_large"
    assert len(versions(pg, up["sub1"])) == 1 and len(on_disk()) == 1


def test_global_cap_wins_over_a_bigger_item_limit(client, pg, up, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    r = upload(client, up["fac_x1"], up["sub1_pdf"], "a.pdf", make_pdf() + b"\n" * (1024 * 1024))    # item allows 5 MB
    assert r.status_code == 413 and on_disk() == []


def test_missing_file_field_is_422(client, up):
    r = client.post(f"/submissions/{up['sub1']['id']}/versions", headers=as_user(client, up["fac_x1"]))
    assert r.status_code == 422


# ------------------------------------------------------------ stored but marked FORMAT_FAILED
def test_unreadable_file_is_stored_flagged_and_says_so(client, pg, up):
    r = upload(client, up["fac_x1"], up["sub1_pdf"], "broken.pdf", TRUNCATED_PDF)
    assert r.status_code == 201
    v = r.json()
    assert v["validation_status"] == "FORMAT_FAILED" and v["format_flag_raised"] is True and "problem" in v["message"]
    assert v["validation_detail"]["problem"]
    row = versions(pg, up["sub1_pdf"])[0]
    assert Path(settings.storage_dir(), row["storage_key"]).read_bytes() == TRUNCATED_PDF
    f = flags(pg, up["sub1_pdf"])
    assert len(f) == 1 and f[0]["kind"] == "FORMAT" and f[0]["status"] == "OPEN" and f[0]["raised_by_version_id"] == row["id"]
    assert f[0]["course_file_id"] == up["cf_x1"]["id"]


def test_password_protected_pdf_is_flagged_with_a_clear_reason(client, pg, up):
    r = upload(client, up["fac_x1"], up["sub1_pdf"], "locked.pdf", make_pdf(password="secret"))
    assert r.json()["validation_status"] == "FORMAT_FAILED" and "password" in r.json()["validation_detail"]["problem"]


def test_second_failure_adds_a_version_but_not_a_second_flag(client, pg, up):
    upload(client, up["fac_x1"], up["sub1_pdf"], "b1.pdf", TRUNCATED_PDF)
    r = upload(client, up["fac_x1"], up["sub1_pdf"], "b2.pdf", TRUNCATED_PDF + b"more")
    assert r.status_code == 201 and r.json()["format_flag_raised"] is False and r.json()["version_no"] == 2
    assert len(flags(pg, up["sub1_pdf"], "FORMAT")) == 1 and len(versions(pg, up["sub1_pdf"])) == 2


def test_a_valid_reupload_clears_the_format_flag_and_keeps_the_history(client, pg, up):
    bad = upload(client, up["fac_x1"], up["sub1_pdf"], "b.pdf", TRUNCATED_PDF).json()
    good = upload(client, up["fac_x1"], up["sub1_pdf"], "g.pdf", make_pdf()).json()
    assert good["format_flags_cleared"] == 1 and good["validation_status"] == "OK"
    (f,) = flags(pg, up["sub1_pdf"], "FORMAT")
    assert f["status"] == "CLEARED" and str(f["cleared_by_version_id"]) == good["id"] and str(f["raised_by_version_id"]) == bad["id"]
    assert f["cleared_at"] is not None
    assert [v["validation_status"] for v in versions(pg, up["sub1_pdf"])] == ["FORMAT_FAILED", "OK"]
    items = client.get(f"/course-files/{up['cf_x1']['id']}/submissions", headers=as_user(client, up["fac_x1"])).json()
    assert [i for i in items if i["submission_id"] == str(up["sub1_pdf"]["id"])][0]["open_flags"] == []


def test_a_new_failure_after_a_clear_raises_a_fresh_flag(client, pg, up):
    upload(client, up["fac_x1"], up["sub1_pdf"], "b.pdf", TRUNCATED_PDF)
    upload(client, up["fac_x1"], up["sub1_pdf"], "g.pdf", make_pdf())
    again = upload(client, up["fac_x1"], up["sub1_pdf"], "b2.pdf", TRUNCATED_PDF + b"2")
    assert again.json()["format_flag_raised"] is True
    assert [f["status"] for f in flags(pg, up["sub1_pdf"], "FORMAT")] == ["CLEARED", "OPEN"]


def test_a_valid_upload_never_touches_lateness_or_waived_flags(client, pg, up):
    late = pg.execute(
        "INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s,%s,'LATE','Due 1 Sep, nothing by then') RETURNING id",
        (up["cf_x1"]["id"], up["sub1_pdf"]["id"])).fetchone()
    pg.execute(
        "INSERT INTO flags (course_file_id, submission_id, kind, status, reason) VALUES (%s,%s,'CONTENT','WAIVED','waived earlier')",
        (up["cf_x1"]["id"], up["sub1_pdf"]["id"]))
    upload(client, up["fac_x1"], up["sub1_pdf"], "b.pdf", TRUNCATED_PDF)
    upload(client, up["fac_x1"], up["sub1_pdf"], "g.pdf", make_pdf())
    state = {(f["kind"], f["status"]) for f in flags(pg, up["sub1_pdf"])}
    assert ("LATE", "OPEN") in state and ("CONTENT", "WAIVED") in state and ("FORMAT", "CLEARED") in state
    assert pg.execute("SELECT status FROM flags WHERE id=%s", (late["id"],)).fetchone()["status"] == "OPEN"


def test_clearing_only_touches_this_submissions_flags(client, pg, up):
    other = make_submission(pg, up["cf_x1"], make_template(pg, exts=("pdf",)))
    pg.execute("INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s,%s,'FORMAT','other file broken')",
               (up["cf_x1"]["id"], other["id"]))
    upload(client, up["fac_x1"], up["sub1_pdf"], "g.pdf", make_pdf())
    assert flags(pg, other, "FORMAT")[0]["status"] == "OPEN"


def test_good_first_upload_creates_no_flags(client, pg, up):
    upload(client, up["fac_x1"], up["sub1_pdf"], "g.pdf", make_pdf())
    assert flags(pg, up["sub1_pdf"]) == []


# ------------------------------------------------------------ who may upload
def test_hod_cannot_upload_even_in_own_department(client, pg, up):
    r = upload(client, up["hod_x"], up["sub1"], "a.csv", CSV)
    assert r.status_code == 403 and versions(pg, up["sub1"]) == [] and on_disk() == []


@pytest.mark.parametrize("who,sub", [("fac_x2", "sub1"), ("fac_y1", "sub1"), ("hod_y", "sub1"), ("fac_x1", "subY"), ("fac_x1", "sub2")])
def test_nobody_uploads_into_a_file_they_cannot_see(client, pg, up, who, sub):
    r = upload(client, up[who], up[sub], "a.csv", CSV)
    assert r.status_code == 404 and versions(pg, up[sub]) == [] and on_disk() == []


def test_unknown_submission_is_404_and_no_login_is_401(client, up):
    import uuid
    assert upload(client, up["fac_x1"], uuid.uuid4(), "a.csv", CSV).status_code == 404
    r = client.post(f"/submissions/{up['sub1']['id']}/versions", files={"file": ("a.csv", CSV)})
    assert r.status_code == 401


def test_faculty_cannot_upload_after_the_semester_is_closed(client, pg, up):
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))                    # a newer semester takes over
    r = upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV)
    assert r.status_code == 409 and "closed" in r.json()["detail"] and versions(pg, up["sub1"]) == []


def test_switched_off_checklist_item_takes_no_uploads(client, pg, up):
    pg.execute("UPDATE checklist_templates SET is_active=false WHERE id=%s", (up["tpl"]["id"],))
    assert upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV).status_code == 409
    assert upload(client, up["dean"], up["sub1"], "a.csv", CSV, reason="long enough reason").status_code == 409


def test_switched_off_faculty_cannot_upload(client, pg, up):
    token = as_user(client, up["fac_x1"])
    pg.execute("UPDATE users SET is_active=false WHERE id=%s", (up["fac_x1"]["id"],))
    r = client.post(f"/submissions/{up['sub1']['id']}/versions", headers=token, files={"file": ("a.csv", CSV)})
    assert r.status_code == 401


# ------------------------------------------------------------ the Dean uploads: allowed, reason compulsory, traced
def test_dean_upload_needs_a_reason(client, pg, up):
    for reason in (None, "", "   ", "too short"):
        r = upload(client, up["dean"], up["sub1"], "a.csv", CSV, reason=reason)
        assert r.status_code == 422, reason
    assert versions(pg, up["sub1"]) == [] and on_disk() == []


def test_dean_upload_is_traced_as_the_dean_on_behalf_of_the_faculty(client, pg, up):
    why = "Faculty is on medical leave; sent the file by email"
    r = upload(client, up["dean"], up["sub1"], "a.csv", CSV, reason=f"  {why}  ")
    assert r.status_code == 201
    v = r.json()
    assert v["uploaded_by"] == str(up["dean"]["id"]) and v["uploaded_by_role"] == "DEAN" and v["on_behalf_reason"] == why
    history = client.get(f"/submissions/{up['sub1']['id']}/versions", headers=as_user(client, up["fac_x1"])).json()[0]
    assert history["uploaded_by_name"] == up["dean"]["full_name"] and history["uploaded_by_role"] == "DEAN"
    assert history["on_behalf_reason"] == why                                  # the faculty member sees it too
    owner = pg.execute("SELECT faculty_id FROM course_files WHERE id=%s", (up["cf_x1"]["id"],)).fetchone()
    assert owner["faculty_id"] == up["fac_x1"]["id"]                           # ownership does not move
    log = pg.execute("SELECT actor_role, payload FROM audit_log WHERE action='submission.upload' AND entity_id=%s", (str(up["sub1"]["id"]),)).fetchone()
    assert log["actor_role"] == "DEAN" and log["payload"]["on_behalf_reason"] == why


def test_dean_may_upload_into_a_closed_semester_and_any_department(client, pg, up):
    set_current(pg, make_semester(pg, "2027-28", "EVEN"))
    assert upload(client, up["dean"], up["sub1"], "a.csv", CSV, reason="late correction for audit").status_code == 201
    assert upload(client, up["dean"], up["subY"], "a.csv", CSV, reason="late correction for audit").status_code == 201


def test_a_reason_sent_by_faculty_is_ignored(client, pg, up):
    r = upload(client, up["fac_x1"], up["sub1"], "a.csv", CSV, reason="pretend I am the dean")
    assert r.status_code == 201 and r.json()["on_behalf_reason"] is None and r.json()["uploaded_by_role"] == "FACULTY"


def test_dean_upload_does_not_hide_a_lateness_flag(client, pg, up):
    pg.execute("INSERT INTO flags (course_file_id, submission_id, kind, reason) VALUES (%s,%s,'LATE','missed the date')",
               (up["cf_x1"]["id"], up["sub1"]["id"]))
    upload(client, up["dean"], up["sub1"], "a.csv", CSV, reason="uploaded for the faculty member")
    assert flags(pg, up["sub1"], "LATE")[0]["status"] == "OPEN"


# ------------------------------------------------------------ failures must not leave half-saved uploads
def test_if_saving_fails_no_file_and_no_row_is_left(pg, up, monkeypatch):
    from app.api import submissions as module
    from app.tests.api_fixtures import SavepointConn
    from app.api.deps import get_db

    wrapper = SavepointConn(pg)

    def override():
        wrapper.commit()
        try:
            yield wrapper
        finally:
            wrapper.rollback()

    app.dependency_overrides[get_db] = override
    try:
        c = TestClient(app, raise_server_exceptions=False)
        token = as_user(c, up["fac_x1"])
        monkeypatch.setattr(module.auditlog, "write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk of the audit log is full")))
        r = c.post(f"/submissions/{up['sub1']['id']}/versions", headers=token, files={"file": ("a.csv", CSV)})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 500
    assert versions(pg, up["sub1"]) == [] and on_disk() == []
    assert not list((Path(settings.storage_dir()) / ".tmp").iterdir())
    assert pg.execute("SELECT current_version_id FROM submissions WHERE id=%s", (up["sub1"]["id"],)).fetchone()["current_version_id"] is None


def test_if_the_file_cannot_be_placed_nothing_is_saved(pg, up, monkeypatch):
    from app.tests.api_fixtures import SavepointConn
    from app.api.deps import get_db

    wrapper = SavepointConn(pg)

    def override():
        wrapper.commit()
        try:
            yield wrapper
        finally:
            wrapper.rollback()

    app.dependency_overrides[get_db] = override
    try:
        c = TestClient(app, raise_server_exceptions=False)
        token = as_user(c, up["fac_x1"])
        monkeypatch.setattr(storage, "place", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        r = c.post(f"/submissions/{up['sub1']['id']}/versions", headers=token, files={"file": ("a.csv", CSV)})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 500 and versions(pg, up["sub1"]) == [] and on_disk() == []
    assert not list((Path(settings.storage_dir()) / ".tmp").iterdir())
