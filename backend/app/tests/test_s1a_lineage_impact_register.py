"""
S1a regression tests: FK enforcement, lineage validation, unique version numbers,
transitive impact analysis, and the register-onchain fingerprint guard.
Uses its own temp DB (fixture) so it does not depend on import order of other test modules.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import io
import sqlite3
import pytest
from fastapi.testclient import TestClient

import app.core.db as db_module
from app.core.db import get_connection, init_db
from app.core.versioning import create_dataset, create_version, get_lineage, get_version
from app.core.training import register_model, register_training_run
from app.core.impact import analyze_impact
from app.core.fabric_client import FabricError
import app.api.datasets as datasets_api
from app.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    previous = db_module.DB_PATH
    db_module.DB_PATH = str(tmp_path / "s1a.db")
    init_db()
    yield
    db_module.DB_PATH = previous


def _v(dataset_id, parent=None, val=1):
    return create_version(dataset_id, [{"k": val}], parent_version_id=parent)


# ---------- foreign keys ----------

def test_foreign_keys_are_enforced():
    conn = get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO training_runs VALUES ('x','nope','nope','{}',NULL,'t')")
    conn.close()


# ---------- lineage validation ----------

def test_unknown_dataset_rejected():
    with pytest.raises(ValueError, match="dataset_id not found"):
        create_version("no-such-dataset", [{"k": 1}])


def test_cross_dataset_parent_rejected():
    a = create_dataset("A")
    b = create_dataset("B")
    va = _v(a)
    with pytest.raises(ValueError, match="different dataset"):
        _v(b, parent=va["version_id"])


def test_second_root_rejected():
    ds = create_dataset("OneRoot")
    _v(ds)
    with pytest.raises(ValueError, match="parent_version_id is required"):
        _v(ds, parent=None, val=2)


def test_branching_never_reuses_version_numbers():
    ds = create_dataset("Branch")
    v1 = _v(ds)
    v2a = _v(ds, parent=v1["version_id"], val=2)
    v2b = _v(ds, parent=v1["version_id"], val=3)
    assert [v1["version_number"], v2a["version_number"], v2b["version_number"]] == [1, 2, 3]
    assert [v["version_number"] for v in get_lineage(ds)] == [1, 2, 3]


def test_unique_index_blocks_duplicate_numbers_at_db_level():
    ds = create_dataset("Unique")
    v1 = _v(ds)
    conn = get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO dataset_versions
               (version_id, dataset_id, parent_version_id, version_number,
                schema_fingerprint, dataset_fingerprint, record_count, created_at)
               VALUES ('dup', ?, ?, 1, 's', 'd', 1, 't')""",
            (ds, v1["version_id"]),
        )
    conn.close()


def test_failed_create_version_leaves_no_partial_rows():
    ds = create_dataset("Atomic")
    v1 = _v(ds)
    before = len(get_lineage(ds))
    with pytest.raises(ValueError):
        _v(ds, parent="fake-parent")
    assert len(get_lineage(ds)) == before


# ---------- transitive impact ----------

def test_impact_is_transitive_through_grandchildren():
    ds = create_dataset("Chain")
    v1 = _v(ds)
    v2 = _v(ds, parent=v1["version_id"], val=2)
    v3 = _v(ds, parent=v2["version_id"], val=3)
    model = register_model("M", "1")
    register_training_run(v3["version_id"], model["model_id"])

    res = analyze_impact(v1["version_id"])
    assert res["severity"] == "HIGH"
    assert res["confidence"] == "MEDIUM"
    assert res["recommendation"] == "REBUILD_AND_RETRAIN"
    assert res["affected_model_ids"] == [model["model_id"]]
    assert res["direct_training_run_count"] == 0
    assert res["downstream_training_run_count"] == 1
    assert [d["depth"] for d in res["affected_descendant_versions"]] == [1, 2]
    assert len(res["affected_child_versions"]) == 1  # direct children only
    run = res["affected_training_runs"][0]
    assert run["via_version_id"] == v3["version_id"] and run["depth"] == 2


def test_direct_run_keeps_high_confidence_and_retrain():
    ds = create_dataset("Direct")
    v1 = _v(ds)
    v2 = _v(ds, parent=v1["version_id"], val=2)
    m1, m2 = register_model("M1", "1"), register_model("M2", "1")
    register_training_run(v1["version_id"], m1["model_id"])
    register_training_run(v2["version_id"], m2["model_id"])

    res = analyze_impact(v1["version_id"])
    assert (res["severity"], res["confidence"], res["recommendation"]) == ("HIGH", "HIGH", "RETRAIN")
    assert res["affected_model_ids"] == sorted([m1["model_id"], m2["model_id"]])
    assert len(res["affected_training_runs"]) == 2


def test_impact_covers_both_branches_and_ignores_siblings_and_ancestors():
    ds = create_dataset("Tree")
    v1 = _v(ds)
    v2a = _v(ds, parent=v1["version_id"], val=2)
    v2b = _v(ds, parent=v1["version_id"], val=3)
    v3 = _v(ds, parent=v2a["version_id"], val=4)
    model = register_model("MT", "1")
    register_training_run(v3["version_id"], model["model_id"])

    from_v1 = analyze_impact(v1["version_id"])
    assert {d["version_id"] for d in from_v1["affected_descendant_versions"]} == {
        v2a["version_id"], v2b["version_id"], v3["version_id"]}

    assert analyze_impact(v2b["version_id"])["severity"] == "LOW"        # sibling branch, nothing downstream
    assert analyze_impact(v3["version_id"])["recommendation"] == "RETRAIN"  # leaf with its own run


def test_leaf_without_runs_is_low():
    ds = create_dataset("Leaf")
    v1 = _v(ds)
    assert analyze_impact(v1["version_id"])["severity"] == "LOW"


# ---------- register-onchain guard ----------

client = TestClient(app)


def _upload():
    resp = client.post(
        "/datasets",
        data={"name": "Reg"},
        files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n3,4\n"), "text/csv")},
    )
    assert resp.status_code == 200
    return resp.json()["version_id"]


ALREADY = FabricError("invoke failed: ... already registered on-chain (immutable)")


def test_register_normal_success_marks_registered(monkeypatch):
    vid = _upload()
    monkeypatch.setattr(datasets_api, "invoke", lambda fn, args: "status:200")
    resp = client.post(f"/datasets/versions/{vid}/register-onchain")
    assert resp.status_code == 200 and resp.json()["status"] == "registered"
    assert get_version(vid)["onchain_status"] == "REGISTERED"


def test_register_already_onchain_with_matching_fingerprint_is_marked(monkeypatch):
    vid = _upload()
    def boom(fn, args): raise ALREADY
    monkeypatch.setattr(datasets_api, "invoke", boom)
    monkeypatch.setattr(datasets_api, "query", lambda fn, args: "true")
    resp = client.post(f"/datasets/versions/{vid}/register-onchain")
    assert resp.status_code == 200 and resp.json()["status"] == "already_registered"
    assert get_version(vid)["onchain_status"] == "REGISTERED"


def test_register_already_onchain_with_different_fingerprint_is_refused(monkeypatch):
    vid = _upload()
    def boom(fn, args): raise ALREADY
    monkeypatch.setattr(datasets_api, "invoke", boom)
    monkeypatch.setattr(datasets_api, "query", lambda fn, args: "false")
    resp = client.post(f"/datasets/versions/{vid}/register-onchain")
    assert resp.status_code == 409
    assert get_version(vid)["onchain_status"] == "NOT_REGISTERED"


def test_register_verify_query_failure_is_502_and_not_marked(monkeypatch):
    vid = _upload()
    def boom(fn, args): raise ALREADY
    def qboom(fn, args): raise FabricError("query failed: peer down")
    monkeypatch.setattr(datasets_api, "invoke", boom)
    monkeypatch.setattr(datasets_api, "query", qboom)
    resp = client.post(f"/datasets/versions/{vid}/register-onchain")
    assert resp.status_code == 502
    assert get_version(vid)["onchain_status"] == "NOT_REGISTERED"


def test_new_version_api_rejects_foreign_parent():
    vid_a = _upload()
    other = client.post(
        "/datasets", data={"name": "Other"},
        files={"file": ("o.csv", io.BytesIO(b"a,b\n9,9\n"), "text/csv")},
    ).json()
    resp = client.post(
        f"/datasets/{other['dataset_id']}/versions",
        data={"parent_version_id": vid_a},
        files={"file": ("n.csv", io.BytesIO(b"a,b\n5,5\n"), "text/csv")},
    )
    assert resp.status_code == 400
    assert "different dataset" in resp.json()["detail"]
