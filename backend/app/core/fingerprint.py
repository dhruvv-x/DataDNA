"""
Fingerprinting module for DataDNA.

record_fingerprint = SHA256(canonical_json(record))
dataset_fingerprint = MerkleRoot(all record_fingerprints, sorted by row_index)
"""

import hashlib
from typing import List

from app.core.canonicalize import to_canonical_json


def fingerprint_record(record: dict) -> str:
    """SHA-256 hash of a single canonicalized record."""
    canonical = to_canonical_json(record)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_pair(left: str, right: str) -> str:
    combined = (left + right).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def merkle_root(fingerprints: List[str]) -> str:
    """
    Compute Merkle root from a list of record fingerprints.
    Order matters: caller must pass fingerprints sorted by row_index.
    """
    if not fingerprints:
        return hashlib.sha256(b"").hexdigest()

    level = list(fingerprints)

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last if odd count

        next_level = []
        for i in range(0, len(level), 2):
            next_level.append(_hash_pair(level[i], level[i + 1]))
        level = next_level

    return level[0]


def fingerprint_dataset(records: List[dict]) -> dict:
    """
    Given ordered records (by row_index), compute per-record fingerprints
    and the dataset-level Merkle root.
    """
    record_fingerprints = [fingerprint_record(r) for r in records]
    root = merkle_root(record_fingerprints)
    return {
        "record_fingerprints": record_fingerprints,
        "dataset_fingerprint": root,
    }
