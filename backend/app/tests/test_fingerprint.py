import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.fingerprint import fingerprint_record, merkle_root, fingerprint_dataset


def test_same_record_same_fingerprint():
    record = {"name": "Alice", "age": 30}
    fp1 = fingerprint_record(record)
    fp2 = fingerprint_record(record)
    assert fp1 == fp2


def test_column_order_independent():
    record_a = {"name": "Alice", "age": 30}
    record_b = {"age": 30, "name": "Alice"}
    assert fingerprint_record(record_a) == fingerprint_record(record_b)


def test_modified_record_different_fingerprint():
    record_a = {"name": "Alice", "age": 30}
    record_b = {"name": "Alice", "age": 31}
    assert fingerprint_record(record_a) != fingerprint_record(record_b)


def test_whitespace_normalized():
    record_a = {"name": "Alice"}
    record_b = {"name": "  Alice  "}
    assert fingerprint_record(record_a) == fingerprint_record(record_b)


def test_null_variants_normalized():
    record_a = {"name": "Alice", "email": None}
    record_b = {"name": "Alice", "email": ""}
    assert fingerprint_record(record_a) == fingerprint_record(record_b)


def test_merkle_root_deterministic():
    fps = ["a", "b", "c", "d"]
    root1 = merkle_root(fps)
    root2 = merkle_root(fps)
    assert root1 == root2


def test_merkle_root_changes_with_data():
    fps1 = ["a", "b", "c", "d"]
    fps2 = ["a", "b", "c", "X"]
    assert merkle_root(fps1) != merkle_root(fps2)


def test_fingerprint_dataset_structure():
    records = [{"id": 1}, {"id": 2}, {"id": 3}]
    result = fingerprint_dataset(records)
    assert len(result["record_fingerprints"]) == 3
    assert "dataset_fingerprint" in result
