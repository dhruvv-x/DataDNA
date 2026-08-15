import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import tempfile
import pytest

import app.core.db as db_module
db_module.DB_PATH = tempfile.mktemp(suffix=".db")
db_module.init_db()

from app.core.audit import run_audit, get_audit
from app.core.versioning import create_dataset, create_version


def _make_version(records):
    """Helper: create a dataset+version so audit_results has a valid FK target."""
    dataset_id = create_dataset("AuditTestSet")
    result = create_version(dataset_id, records)
    return result["version_id"]


def test_audit_detects_missing_values():
    records = [
        {"name": "Alice", "age": "30"},
        {"name": "", "age": "25"},
        {"name": "Charlie", "age": ""},
    ]
    version_id = _make_version(records)
    result = run_audit(version_id, records)

    assert result["missing_values"]["name"] == 1
    assert result["missing_values"]["age"] == 1


def test_audit_detects_no_missing_when_clean():
    records = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
    version_id = _make_version(records)
    result = run_audit(version_id, records)

    assert result["missing_values"] == {}


def test_audit_detects_exact_duplicates():
    records = [
        {"name": "Alice", "age": "30"},
        {"name": "Alice", "age": "30"},
        {"name": "Bob", "age": "25"},
    ]
    version_id = _make_version(records)
    result = run_audit(version_id, records)

    assert result["duplicate_count"] == 1


def test_audit_detects_numeric_outliers():
    records = [
        {"name": "A", "score": "10"},
        {"name": "B", "score": "12"},
        {"name": "C", "score": "11"},
        {"name": "D", "score": "13"},
        {"name": "E", "score": "9999"},  # extreme outlier
    ]
    version_id = _make_version(records)
    result = run_audit(version_id, records)

    assert "score" in result["outliers"]
    assert len(result["outliers"]["score"]) >= 1


def test_audit_no_false_positive_outliers_on_uniform_data():
    records = [{"name": f"P{i}", "score": "50"} for i in range(5)]
    version_id = _make_version(records)
    result = run_audit(version_id, records)

    assert result["outliers"] == {}


def test_audit_detects_schema_type_inconsistency():
    records = [
        {"name": "A", "value": 10},
        {"name": "B", "value": "ten"},
        {"name": "C", "value": 15},
    ]
    version_id = _make_version(records)
    result = run_audit(version_id, records)

    assert "value" in result["schema_issues"]


def test_audit_empty_records_raises():
    version_id = _make_version([{"name": "placeholder"}])
    with pytest.raises(ValueError):
        run_audit(version_id, [])


def test_get_audit_retrieves_saved_result():
    records = [{"name": "Alice", "age": "30"}]
    version_id = _make_version(records)
    run_audit(version_id, records)

    retrieved = get_audit(version_id)
    assert retrieved is not None
    assert retrieved["dataset_version_id"] == version_id
    assert retrieved["total_records"] == 1


def test_get_audit_nonexistent_version_returns_none():
    result = get_audit("nonexistent-version-id")
    assert result is None
