import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import io
import tempfile
import pytest
from fastapi.testclient import TestClient

import app.core.db as db_module
db_module.DB_PATH = tempfile.mktemp(suffix=".db")
db_module.init_db()

from app.main import app

client = TestClient(app)


def _csv_file(content: str, filename: str = "data.csv"):
    return {"file": (filename, io.BytesIO(content.encode("utf-8")), "text/csv")}


# --- POST /datasets ---

def test_upload_dataset_creates_v1():
    resp = client.post(
        "/datasets",
        data={"name": "TestSet"},
        files=_csv_file("name,age\nAlice,30\nBob,25\n"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["version_number"] == 1
    assert body["record_count"] == 2
    assert "dataset_id" in body
    assert "dataset_fingerprint" in body


def test_upload_dataset_bad_extension_rejected():
    resp = client.post(
        "/datasets",
        data={"name": "BadSet"},
        files={"file": ("data.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 422


def test_upload_dataset_empty_csv_rejected():
    resp = client.post(
        "/datasets",
        data={"name": "EmptySet"},
        files=_csv_file(""),
    )
    assert resp.status_code == 422


def test_upload_dataset_missing_name_rejected():
    resp = client.post(
        "/datasets",
        files=_csv_file("name,age\nAlice,30\n"),
    )
    assert resp.status_code == 422  # FastAPI validation: name is required


# --- GET /datasets/{id}/lineage ---

def test_lineage_returns_version_history():
    upload = client.post(
        "/datasets",
        data={"name": "LineageSet"},
        files=_csv_file("name,age\nAlice,30\n"),
    )
    dataset_id = upload.json()["dataset_id"]

    resp = client.get(f"/datasets/{dataset_id}/lineage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_id"] == dataset_id
    assert len(body["versions"]) == 1
    assert body["versions"][0]["version_number"] == 1


def test_lineage_nonexistent_dataset_404():
    resp = client.get("/datasets/nonexistent-id-123/lineage")
    assert resp.status_code == 404


# --- POST /datasets/{id}/versions ---

def test_new_version_increments_and_links_parent():
    upload = client.post(
        "/datasets",
        data={"name": "VersionSet"},
        files=_csv_file("name,age\nAlice,30\n"),
    )
    dataset_id = upload.json()["dataset_id"]
    v1_id = upload.json()["version_id"]

    resp = client.post(
        f"/datasets/{dataset_id}/versions",
        files=_csv_file("name,age\nAlice,30\nBob,25\n"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["version_number"] == 2
    assert body["record_count"] == 2

    lineage = client.get(f"/datasets/{dataset_id}/lineage").json()
    assert len(lineage["versions"]) == 2
    assert lineage["versions"][1]["parent_version_id"] == v1_id


def test_new_version_nonexistent_dataset_404():
    resp = client.post(
        "/datasets/nonexistent-id-456/versions",
        files=_csv_file("name,age\nAlice,30\n"),
    )
    assert resp.status_code == 404


def test_new_version_different_fingerprint_from_parent():
    upload = client.post(
        "/datasets",
        data={"name": "FingerprintSet"},
        files=_csv_file("name,age\nAlice,30\n"),
    )
    dataset_id = upload.json()["dataset_id"]
    v1_fp = upload.json()["dataset_fingerprint"]

    v2 = client.post(
        f"/datasets/{dataset_id}/versions",
        files=_csv_file("name,age\nAlice,31\n"),  # changed data
    )
    v2_fp = v2.json()["dataset_fingerprint"]

    assert v1_fp != v2_fp
