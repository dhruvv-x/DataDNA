"""S4: downloads (scope, integrity, audit) and proof that the old unprotected DataDNA code is gone."""
import importlib.util
import uuid
from pathlib import Path

import pytest

from app.core import settings
from app.tests.api_fixtures import as_user, audit_actions, client, make_semester, make_user, new_client, uid, world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import CSV, TRUNCATED_PDF, make_pdf, make_submission, make_template, set_current, upload


@pytest.fixture
def stored(client, pg, world):
    set_current(pg, world["sem"])
    sub = make_submission(pg, world["cf_x1"], make_template(pg, exts=("csv", "pdf")))
    v1 = upload(client, world["fac_x1"], sub, "marks.csv", CSV).json()
    v2 = upload(client, world["fac_x1"], sub, "marks v2.csv", CSV + b"Kiran,9\n").json()
    return {**world, "sub": sub, "v1": v1, "v2": v2}


def get(client, who, version_id):
    return client.get(f"/submission-versions/{version_id}/download", headers=as_user(client, who))


def test_owner_downloads_the_exact_bytes_with_safe_headers(client, stored):
    r = get(client, stored["fac_x1"], stored["v2"]["id"])
    assert r.status_code == 200 and r.content == CSV + b"Kiran,9\n"
    assert r.headers["content-disposition"].startswith("attachment") and "marks" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert r.headers["x-file-sha256"] == stored["v2"]["sha256"]


def test_old_versions_stay_downloadable(client, stored):
    r = get(client, stored["fac_x1"], stored["v1"]["id"])
    assert r.status_code == 200 and r.content == CSV


def test_a_flagged_unreadable_version_can_still_be_downloaded(client, pg, world):
    set_current(pg, world["sem"])
    sub = make_submission(pg, world["cf_x1"], make_template(pg, exts=("pdf",)))
    v = upload(client, world["fac_x1"], sub, "broken.pdf", TRUNCATED_PDF).json()
    assert get(client, world["fac_x1"], v["id"]).content == TRUNCATED_PDF


@pytest.mark.parametrize("who,status", [("fac_x1", 200), ("hod_x", 200), ("dean", 200),
                                        ("fac_x2", 404), ("hod_y", 404), ("fac_y1", 404)])
def test_download_follows_the_scope_rules(client, stored, who, status):
    assert get(client, stored[who], stored["v1"]["id"]).status_code == status


def test_download_needs_a_login_and_unknown_id_is_404(client, stored):
    assert client.get(f"/submission-versions/{stored['v1']['id']}/download").status_code == 401
    assert get(client, stored["dean"], uuid.uuid4()).status_code == 404


def test_every_download_is_audited_with_who_did_it(client, pg, stored):
    get(client, stored["hod_x"], stored["v1"]["id"])
    row = pg.execute("SELECT actor_id, actor_role FROM audit_log WHERE action='version.download' AND entity_id=%s", (stored["v1"]["id"],)).fetchone()
    assert row["actor_id"] == stored["hod_x"]["id"] and row["actor_role"] == "HOD"


def test_a_file_changed_on_disk_is_never_served(client, pg, stored):
    key = pg.execute("SELECT storage_key FROM submission_versions WHERE id=%s", (stored["v1"]["id"],)).fetchone()["storage_key"]
    Path(settings.storage_dir(), key).write_bytes(b"quietly edited")
    r = get(client, stored["fac_x1"], stored["v1"]["id"])
    assert r.status_code == 500 and b"quietly edited" not in r.content and "SHA-256" in r.json()["detail"]
    row = pg.execute("SELECT payload FROM audit_log WHERE action='version.download_failed' AND entity_id=%s", (stored["v1"]["id"],)).fetchone()
    assert row["payload"]["reason"] == "hash_mismatch"


def test_a_missing_file_is_reported_not_hidden(client, pg, stored):
    key = pg.execute("SELECT storage_key FROM submission_versions WHERE id=%s", (stored["v1"]["id"],)).fetchone()["storage_key"]
    Path(settings.storage_dir(), key).unlink()
    r = get(client, stored["fac_x1"], stored["v1"]["id"])
    assert r.status_code == 500 and "missing" in r.json()["detail"]
    assert "version.download_failed" in audit_actions(pg, stored["v1"]["id"])


def test_unicode_and_odd_file_names_download_fine(client, pg, world):
    set_current(pg, world["sem"])
    sub = make_submission(pg, world["cf_x1"], make_template(pg, exts=("csv",)))
    v = upload(client, world["fac_x1"], sub, 'रिपोर्ट "final" ;v2.csv', CSV).json()
    r = get(client, world["fac_x1"], v["id"])
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")


# ------------------------------------------------------------ the old DataDNA code is really gone
@pytest.mark.parametrize("method,path", [
    ("GET", "/datasets"), ("POST", "/datasets"), ("GET", f"/datasets/{uuid.uuid4()}/lineage"), ("GET", "/models"),
    ("POST", "/models"), ("GET", "/training-runs"), ("POST", "/training-runs"), ("GET", "/datasets/anything/versions"),
])
def test_old_unprotected_endpoints_no_longer_exist(client, world, method, path):
    assert client.request(method, path, headers=as_user(client, world["dean"])).status_code in (404, 405)
    assert client.request(method, path).status_code in (401, 404, 405)  # and never an open 200


def test_no_old_dataset_code_is_left_to_import():
    for name in ("api.datasets", "api.training", "core.db", "core.ingest", "core.parsing", "core.audit",
                 "core.training", "core.versioning", "core.impact", "core.trust", "core.canonicalize"):
        assert importlib.util.find_spec(f"app.{name}") is None, f"app.{name} should have been deleted"


def test_nothing_in_the_app_uses_sqlite_any_more():
    root = Path(__file__).resolve().parents[1]
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if "tests" not in p.parts and "sqlite3" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_route_in_the_app_requires_login_except_health_and_auth_entry_points():
    from app.main import app
    public = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/auth/login", "/auth/refresh", "/auth/logout"}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in public:
            continue
        for method in getattr(route, "methods", None) or []:
            if method in ("HEAD", "OPTIONS"):
                continue
            body = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
            url = path
            for part in ("submission_id", "version_id", "course_file_id", "semester_id", "department_id", "subject_id", "template_id", "user_id"):
                url = url.replace("{" + part + "}", str(uuid.uuid4()))
            from fastapi.testclient import TestClient
            r = TestClient(app).request(method, url, **body)
            assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a login"
