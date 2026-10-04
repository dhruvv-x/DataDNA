"""
S1b regression tests: strict CSV parsing, JSON nested values in the audit,
atomic upload (dataset + version + records + audit in one transaction),
and repo hygiene (junk files stay deleted).
Uses its own temp DB per test.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.db as db_module
from app.core.db import get_connection, init_db
from app.core.parsing import parse_csv, ParseError
from app.core.audit import analyze_records, run_audit
from app.core.versioning import create_dataset, create_version, get_lineage
import app.core.ingest as ingest_module
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    previous = db_module.DB_PATH
    db_module.DB_PATH = str(tmp_path / "s1b.db")
    init_db()
    yield
    db_module.DB_PATH = previous


def _csv(content: bytes, filename="data.csv"):
    return {"file": (filename, io.BytesIO(content), "text/csv")}


def _json(obj, filename="data.json"):
    return {"file": (filename, io.BytesIO(json.dumps(obj).encode()), "application/json")}


def _count(table: str) -> int:
    conn = get_connection()
    n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    conn.close()
    return n


def _all_counts() -> dict:
    return {t: _count(t) for t in ("datasets", "dataset_versions", "records", "audit_results")}


EMPTY = {"datasets": 0, "dataset_versions": 0, "records": 0, "audit_results": 0}


# ---------- CSV parsing ----------

def test_csv_row_with_extra_column_is_rejected_with_row_number():
    with pytest.raises(ParseError, match="line 3"):
        parse_csv(b"a,b\n1,2\n1,2,3\n")


def test_csv_extra_column_upload_gives_422_and_saves_nothing():
    resp = client.post("/datasets", data={"name": "X"}, files=_csv(b"a,b\n1,2,3\n"))
    assert resp.status_code == 422
    assert "values" in resp.json()["detail"]
    assert _all_counts() == EMPTY


def test_csv_duplicate_header_is_rejected():
    with pytest.raises(ParseError, match="duplicate column header: 'a'"):
        parse_csv(b"a,a\n1,2\n")


def test_csv_duplicate_header_upload_gives_422_and_saves_nothing():
    resp = client.post("/datasets", data={"name": "X"}, files=_csv(b"a,b,a\n1,2,3\n"))
    assert resp.status_code == 422
    assert _all_counts() == EMPTY


def test_csv_header_whitespace_is_stripped_before_duplicate_check():
    with pytest.raises(ParseError, match="duplicate"):
        parse_csv(b"a, a\n1,2\n")


def test_csv_empty_header_cell_is_rejected():
    with pytest.raises(ParseError, match="malformed column headers"):
        parse_csv(b"a,b,\n1,2,3\n")


def test_csv_short_row_is_padded_with_none():
    records = parse_csv(b"a,b,c\n1,2\n4,5,6\n")
    assert records[0] == {"a": "1", "b": "2", "c": None}
    assert records[1] == {"a": "4", "b": "5", "c": "6"}


def test_csv_short_row_upload_succeeds():
    resp = client.post("/datasets", data={"name": "Short"}, files=_csv(b"a,b,c\n1,2\n4,5,6\n"))
    assert resp.status_code == 200
    assert resp.json()["record_count"] == 2


def test_csv_blank_lines_are_skipped():
    records = parse_csv(b"\na,b\n1,2\n\n   \n3,4\n\n")
    assert len(records) == 2


def test_csv_excel_bom_does_not_pollute_first_header():
    records = parse_csv(b"\xef\xbb\xbfname,age\nAlice,30\n")
    assert list(records[0].keys()) == ["name", "age"]


def test_csv_oversized_field_gives_parse_error_not_crash():
    with pytest.raises(ParseError, match="Malformed CSV"):
        parse_csv(b"a\n" + b"x" * 200000 + b"\n")


def test_csv_empty_and_header_only_messages_are_distinct():
    with pytest.raises(ParseError, match="empty"):
        parse_csv(b"")
    with pytest.raises(ParseError, match="no records"):
        parse_csv(b"a,b\n")


# ---------- audit on nested JSON values ----------

def test_audit_counts_duplicate_list_values():
    result = analyze_records([{"a": [1, 2]}, {"a": [1, 2]}, {"a": [3]}])
    assert result["duplicate_count"] == 1


def test_audit_does_not_crash_when_column_mixes_list_and_scalar():
    records = [
        {"a": [1, 2], "b": 1},
        {"a": 3, "b": 2},
        {"a": [4], "b": 3},
        {"a": [1], "b": 4},
    ]
    result = analyze_records(records)
    assert result["total_records"] == 4


def test_audit_handles_dict_values_and_empty_list():
    result = analyze_records([{"a": {"x": 1}}, {"a": {"x": 1}}, {"a": []}])
    assert result["duplicate_count"] == 1


def test_audit_still_reports_list_vs_string_as_schema_issue():
    result = analyze_records([{"a": [1]}, {"a": "x"}])
    assert "list" in result["schema_issues"]["a"]
    assert "str" in result["schema_issues"]["a"]


def test_audit_does_not_modify_the_original_records():
    records = [{"a": [1, 2]}, {"a": {"k": 1}}]
    analyze_records(records)
    assert records == [{"a": [1, 2]}, {"a": {"k": 1}}]


def test_json_upload_with_nested_values_succeeds_end_to_end():
    body = [{"a": [1, 2], "n": 1}, {"a": 3, "n": 2}, {"a": {"k": 1}, "n": 3}, {"a": [1, 2], "n": 4}]
    resp = client.post("/datasets", data={"name": "Nested"}, files=_json(body))
    assert resp.status_code == 200
    version_id = resp.json()["version_id"]
    assert client.get(f"/datasets/versions/{version_id}/audit").status_code == 200
    assert client.get(f"/datasets/versions/{version_id}/trust").status_code == 200


def test_run_audit_releases_connection_when_insert_fails():
    with pytest.raises(Exception):
        run_audit("version-that-does-not-exist", [{"a": 1}])
    # Before the fix the leaked connection kept the DB locked for later writers.
    create_dataset("AfterFailure")
    assert _count("datasets") == 1


# ---------- atomic upload ----------

def test_successful_upload_writes_all_four_tables():
    resp = client.post("/datasets", data={"name": "Ok"}, files=_csv(b"a,b\n1,2\n3,4\n"))
    assert resp.status_code == 200
    assert _all_counts() == {"datasets": 1, "dataset_versions": 1, "records": 2, "audit_results": 1}


def test_audit_insert_failure_rolls_back_new_dataset(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ingest_module, "insert_audit", boom)

    resp = client.post("/datasets", data={"name": "Fail"}, files=_csv(b"a,b\n1,2\n"))
    assert resp.status_code == 500
    assert "nothing was saved" in resp.json()["detail"]
    assert _all_counts() == EMPTY


def test_version_insert_failure_rolls_back_new_dataset(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("write failed")
    monkeypatch.setattr(ingest_module, "insert_version", boom)

    resp = client.post("/datasets", data={"name": "Fail"}, files=_csv(b"a,b\n1,2\n"))
    assert resp.status_code == 500
    assert _all_counts() == EMPTY


def test_analysis_crash_saves_nothing(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("analysis crashed")
    monkeypatch.setattr(ingest_module, "analyze_records", boom)

    resp = client.post("/datasets", data={"name": "Fail"}, files=_csv(b"a,b\n1,2\n"))
    assert resp.status_code == 500
    assert _all_counts() == EMPTY


def test_audit_failure_on_new_version_keeps_lineage_and_counts_unchanged(monkeypatch):
    first = client.post("/datasets", data={"name": "Two"}, files=_csv(b"a,b\n1,2\n"))
    assert first.status_code == 200
    dataset_id = first.json()["dataset_id"]
    before = _all_counts()

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ingest_module, "insert_audit", boom)

    resp = client.post(f"/datasets/{dataset_id}/versions", files=_csv(b"a,b\n5,6\n7,8\n"))
    assert resp.status_code == 500
    assert _all_counts() == before
    assert len(get_lineage(dataset_id)) == 1


def test_new_version_upload_writes_version_records_and_audit_together():
    first = client.post("/datasets", data={"name": "Two"}, files=_csv(b"a,b\n1,2\n"))
    dataset_id = first.json()["dataset_id"]

    resp = client.post(f"/datasets/{dataset_id}/versions", files=_csv(b"a,b\n5,6\n7,8\n"))
    assert resp.status_code == 200
    assert resp.json()["version_number"] == 2
    assert _all_counts() == {"datasets": 1, "dataset_versions": 2, "records": 3, "audit_results": 2}


def test_new_version_extra_column_csv_gives_422_and_adds_nothing():
    first = client.post("/datasets", data={"name": "Two"}, files=_csv(b"a,b\n1,2\n"))
    dataset_id = first.json()["dataset_id"]
    before = _all_counts()

    resp = client.post(f"/datasets/{dataset_id}/versions", files=_csv(b"a,b\n1,2,3\n"))
    assert resp.status_code == 422
    assert _all_counts() == before


def test_create_version_standalone_still_works_after_refactor():
    ds = create_dataset("Plain")
    v1 = create_version(ds, [{"k": 1}])
    v2 = create_version(ds, [{"k": 2}], parent_version_id=v1["version_id"])
    assert (v1["version_number"], v2["version_number"]) == (1, 2)


# ---------- repo hygiene ----------

def test_junk_files_stay_deleted():
    repo_root = Path(__file__).resolve().parents[3]
    backend = repo_root / "backend"
    assert not (backend / "app" / "core" / "audit.py.backup").exists()
    assert not (backend / "cleanup.sql").exists()
    assert not (repo_root / "test_ownership.csv").exists()
    assert list(repo_root.glob("insert_*.py")) == []
