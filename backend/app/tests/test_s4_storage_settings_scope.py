"""S4: storage helpers, new settings, new scope helpers, migration 0003 rules. Mostly no HTTP."""
import hashlib
import io
import uuid
from pathlib import Path

import pytest
from psycopg import errors

from app.core import settings, storage
from app.core.scope import (DEAN, FACULTY, HOD, CurrentUser, can_upload, department_filter, subject_filter)
from app.tests.api_fixtures import world  # noqa: F401
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401
from app.tests.s4_helpers import make_submission, make_template


# ------------------------------------------------------------ storage
def test_receive_hashes_and_counts_the_bytes():
    data = b"abc" * 1000
    tmp, size, sha = storage.receive(io.BytesIO(data), 10_000)
    assert size == len(data) and sha == hashlib.sha256(data).hexdigest()
    assert tmp.read_bytes() == data


def test_receive_stops_at_the_limit_and_leaves_no_temp_file():
    with pytest.raises(storage.TooLarge):
        storage.receive(io.BytesIO(b"x" * 101), 100)
    assert list((storage.root() / ".tmp").iterdir()) == []


def test_receive_accepts_exactly_the_limit():
    _, size, _ = storage.receive(io.BytesIO(b"x" * 100), 100)
    assert size == 100


def test_receive_cleans_up_when_the_stream_breaks():
    class Broken:
        def read(self, n):
            raise OSError("client went away")

    with pytest.raises(OSError):
        storage.receive(Broken(), 100)
    assert list((storage.root() / ".tmp").iterdir()) == []


def test_place_uses_ids_and_hash_never_the_user_file_name():
    tmp, size, sha = storage.receive(io.BytesIO(b"hello"), 100)
    cf, sub = uuid.uuid4(), uuid.uuid4()
    key = storage.place(tmp, cf, sub, 3, sha, "pdf")
    assert key == f"{cf}/{sub}/v3_{sha[:12]}.pdf"
    assert storage.resolve(key).read_bytes() == b"hello" and not tmp.exists()


def test_place_never_overwrites_an_existing_file():
    cf, sub = uuid.uuid4(), uuid.uuid4()
    for expected in (None, FileExistsError):
        tmp, _, sha = storage.receive(io.BytesIO(b"same"), 100)
        if expected is None:
            storage.place(tmp, cf, sub, 1, sha, "pdf")
        else:
            with pytest.raises(FileExistsError):
                storage.place(tmp, cf, sub, 1, sha, "pdf")


@pytest.mark.parametrize("key", ["../outside.txt", "a/../../outside.txt", "/etc/passwd"])
def test_resolve_refuses_paths_that_escape_the_storage_folder(key):
    with pytest.raises(ValueError):
        storage.resolve(key)


def test_remove_and_discard_ignore_missing_files():
    storage.remove("nope/nothing.pdf")
    storage.remove(None)
    storage.discard(None)
    storage.discard(Path("/definitely/not/here"))


# ------------------------------------------------------------ settings
def test_storage_dir_defaults_to_home_and_is_outside_the_repo(monkeypatch):
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    assert settings.storage_dir() == str(Path("~/datadna_storage").expanduser().resolve())


def test_storage_dir_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "x"))
    assert settings.storage_dir() == str((tmp_path / "x").resolve())


def test_max_upload_default_and_bounds(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    assert settings.max_upload_mb() == 50
    for bad in ("0", "501", "abc"):
        monkeypatch.setenv("MAX_UPLOAD_MB", bad)
        with pytest.raises(settings.SettingsError):
            settings.max_upload_mb()


def test_startup_fails_loudly_when_storage_is_not_writable(monkeypatch, tmp_path):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")
    monkeypatch.setenv("STORAGE_DIR", str(blocker / "inside"))  # a folder under a file can never exist
    with pytest.raises(settings.SettingsError, match="not writable"):
        settings.startup_checks()


def test_startup_creates_the_storage_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "fresh" / "store"))
    settings.startup_checks()
    assert (tmp_path / "fresh" / "store").is_dir()


# ------------------------------------------------------------ scope helpers
def user(role, dept=None):
    return CurrentUser(id=uuid.uuid4(), email="a@b.c", full_name="N", role=role, department_id=dept)


def test_department_and_subject_filters():
    d = uuid.uuid4()
    assert department_filter(user(DEAN)) == ("TRUE", ())
    assert department_filter(user(HOD, d)) == ("d.id = %s", (d,))
    assert department_filter(user(FACULTY, d)) == ("d.id = %s", (d,))
    assert department_filter(user("X")) == ("FALSE", ())
    assert subject_filter(user(DEAN)) == ("TRUE", ())
    assert subject_filter(user(HOD, d)) == ("s.department_id = %s", (d,))
    assert subject_filter(user("X")) == ("FALSE", ())


def test_only_faculty_and_dean_can_upload():
    assert can_upload(user(FACULTY, uuid.uuid4())) and can_upload(user(DEAN))
    assert not can_upload(user(HOD, uuid.uuid4())) and not can_upload(user("X"))


# ------------------------------------------------------------ migration 0003: who uploaded
def version_sql(pg, w, role, reason, n=1):
    sub = make_submission(pg, w["cf_x1"], make_template(pg))
    return pg.execute(
        """INSERT INTO submission_versions (submission_id, version_no, storage_key, original_filename, size_bytes,
                                            sha256, uploaded_by, uploaded_by_role, on_behalf_reason)
           VALUES (%s, %s, 'k', 'f.pdf', 1, %s, %s, %s, %s) RETURNING id""",
        (sub["id"], n, "a" * 64, w["dean"]["id"], role, reason))


def test_faculty_upload_has_no_reason(pg, world):
    version_sql(pg, world, "FACULTY", None)


@pytest.mark.parametrize("role,reason", [
    ("FACULTY", "faculty must not carry a reason"),
    ("DEAN", None), ("DEAN", ""), ("DEAN", "   "), ("DEAN", "too short"),
    ("HOD", None), ("HOD", "hod cannot upload at all"), ("ADMIN", "this role does not exist"),
])
def test_database_refuses_untraceable_or_wrong_role_uploads(pg, world, role, reason):
    with pytest.raises(errors.CheckViolation):
        version_sql(pg, world, role, reason)


def test_dean_upload_with_a_real_reason_is_accepted(pg, world):
    version_sql(pg, world, "DEAN", "Faculty on medical leave, uploaded at her request")
