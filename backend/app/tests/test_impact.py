import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import tempfile
import pytest
import app.core.db as db_module
db_module.DB_PATH = tempfile.mktemp(suffix=".db")
db_module.init_db()
from app.core.versioning import create_dataset, create_version
from app.core.training import register_model, register_training_run
from app.core.impact import analyze_impact


def _make_version(dataset_id=None, parent_version_id=None):
    if dataset_id is None:
        dataset_id = create_dataset("ImpactTestSet")
    result = create_version(dataset_id, [{"name": "Alice", "age": "30"}], parent_version_id)
    return dataset_id, result["version_id"]


def test_isolated_version_is_low_severity():
    _, version_id = _make_version()
    result = analyze_impact(version_id)
    assert result["severity"] == "LOW"
    assert result["confidence"] == "LOW"
    assert result["recommendation"] == "VERIFY"
    assert result["affected_training_runs"] == []
    assert result["affected_model_ids"] == []
    assert result["affected_child_versions"] == []


def test_version_with_training_run_is_high_severity():
    _, version_id = _make_version()
    model = register_model("TestModel", "v1")
    register_training_run(version_id, model["model_id"])
    result = analyze_impact(version_id)
    assert result["severity"] == "HIGH"
    assert result["confidence"] == "HIGH"
    assert result["recommendation"] == "RETRAIN"
    assert result["affected_model_ids"] == [model["model_id"]]
    assert len(result["affected_training_runs"]) == 1


def test_version_with_child_only_is_medium_severity():
    dataset_id, version_id = _make_version()
    _make_version(dataset_id=dataset_id, parent_version_id=version_id)
    result = analyze_impact(version_id)
    assert result["severity"] == "MEDIUM"
    assert result["confidence"] == "HIGH"
    assert result["recommendation"] == "REBUILD_DATASET"
    assert len(result["affected_child_versions"]) == 1


def test_training_run_takes_priority_over_child_version():
    dataset_id, version_id = _make_version()
    _make_version(dataset_id=dataset_id, parent_version_id=version_id)
    model = register_model("TestModel2", "v1")
    register_training_run(version_id, model["model_id"])
    result = analyze_impact(version_id)
    assert result["severity"] == "HIGH"
    assert result["recommendation"] == "RETRAIN"


def test_nonexistent_version_raises():
    with pytest.raises(ValueError, match="not found"):
        analyze_impact("nonexistent-id")


def test_current_integrity_status_reflected_in_result():
    _, version_id = _make_version()
    result = analyze_impact(version_id)
    assert result["current_integrity_status"] == "VERIFIED"
