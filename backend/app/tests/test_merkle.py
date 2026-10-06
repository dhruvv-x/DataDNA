import hashlib

from app.core.fingerprint import merkle_root


def test_merkle_root_deterministic():
    assert merkle_root(["a", "b", "c", "d"]) == merkle_root(["a", "b", "c", "d"])


def test_merkle_root_changes_with_data():
    assert merkle_root(["a", "b", "c", "d"]) != merkle_root(["a", "b", "c", "X"])


def test_merkle_root_depends_on_order():
    assert merkle_root(["a", "b"]) != merkle_root(["b", "a"])


def test_merkle_root_of_nothing_is_hash_of_empty():
    assert merkle_root([]) == hashlib.sha256(b"").hexdigest()


def test_merkle_single_and_odd_counts():
    assert merkle_root(["a"]) == "a"
    assert merkle_root(["a", "b", "c"]) == merkle_root(["a", "b", "c", "c"])
