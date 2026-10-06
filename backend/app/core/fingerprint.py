"""
Merkle root over a list of hashes (kept from DataDNA for S11/S12: audit-log chain head and on-chain anchoring).
File hashes themselves are plain SHA-256 of the file bytes (see storage.py).
"""
import hashlib
from typing import List


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode("utf-8")).hexdigest()


def merkle_root(fingerprints: List[str]) -> str:
    """Order matters. An odd last item is paired with itself."""
    if not fingerprints:
        return hashlib.sha256(b"").hexdigest()
    level = list(fingerprints)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]
