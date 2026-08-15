import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import tempfile
import pytest

import app.core.db as db_module
db_module.DB_PATH = tempfile.mktemp(suffix=".db")
db_module.init_db()

from app.core.trust import compute_trust_score
from app.core.versioning import create_dataset, create_version
from app.core.audit import run_audit


def _make_version_with_audit(records, parent_version_id=None, dataset_id=None):
    if dataset_id is None:
        dataset_id = create_dataset("TrustTestSet")
    result = create_version(dataset_id, records, parent_version_id=parent_version_id)
    run_audit(result["version_id"], records)
    return dataset_id, result["version_id"]


def test_clean_data_gets_high_score():
    records = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
    _, version_id = _make_version_with_audit(records)

    result = compute_trust_score(version_id)

    assert result["overall_score"] > 85  # clean V1 data should score high
    assert result["breakdown"]["integrity"]["score"] == 100.0


def test_dirty_data_gets_penalized():
    records = [
        {"name": "Alice", "age": "30"},
        {"name": "", "age": "25"},       # missing
        {"name": "Alice", "age": "30"},  # duplicate
        {"name": "Eve", "age": "9999"},  # outlier
    ]
    _, version_id = _make_version_with_audit(records)

    result = compute_trust_score(version_id)

    assert result["overall_score"] < 90  # should be penalized vs clean data
    assert result["breakdown"]["quality"]["score"] < 100.0


def test_score_breakdown_has_all_four_components():
    records = [{"name": "Alice", "age": "30"}]
    _, version_id = _make_version_with_audit(records)

    result = compute_trust_score(version_id)
    breakdown = result["breakdown"]

    assert set(breakdown.keys()) == {"integrity", "quality", "provenance", "anomaly_risk"}
    for component in breakdown.values():
        assert "score" in component
        assert "weight" in component
        assert "explanation" in component


def test_weights_sum_to_one():
    records = [{"name": "Alice", "age": "30"}]
    _, version_id = _make_version_with_audit(records)

    result = compute_trust_score(version_id)
    total_weight = sum(c["weight"] for c in result["breakdown"].values())

    assert abs(total_weight - 1.0) < 0.0001


def test_provenance_increases_with_version_depth():
    records_v1 = [{"name": "Alice", "age": "30"}]
    dataset_id, v1_id = _make_version_with_audit(records_v1)

    records_v2 = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
    _, v2_id = _make_version_with_audit(records_v2, parent_version_id=v1_id, dataset_id=dataset_id)

    score_v1 = compute_trust_score(v1_id)
    score_v2 = compute_trust_score(v2_id)

    assert score_v2["breakdown"]["provenance"]["score"] > score_v1["breakdown"]["provenance"]["score"]


def test_overall_score_within_valid_range():
    records = [{"name": "Alice", "age": "30"}]
    _, version_id = _make_version_with_audit(records)

    result = compute_trust_score(version_id)

    assert 0 <= result["overall_score"] <= 100


def test_missing_version_raises():
    with pytest.raises(ValueError):
        compute_trust_score("nonexistent-version-id")


def test_missing_audit_raises():
    # Create a version WITHOUT running audit
    dataset_id = create_dataset("NoAuditSet")
    result = create_version(dataset_id, [{"name": "Alice", "age": "30"}])

    with pytest.raises(ValueError):
        compute_trust_score(result["version_id"])
