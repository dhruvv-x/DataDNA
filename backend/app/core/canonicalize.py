"""
Canonicalization module for DataDNA record fingerprinting.

Rules (documented, not arbitrary):
1. Column order: order-independent (sorted keys)
2. Nulls: NaN/None/""/null -> single sentinel "\u0000NULL"
3. Whitespace: stripped from string fields
4. Floats: fixed to 6 decimal places
5. Serialization: canonical JSON, sorted keys, no extra whitespace
"""

import json
import math

NULL_SENTINEL = "\u0000NULL"
FLOAT_PRECISION = 6


def _normalize_value(value):
    if value is None:
        return NULL_SENTINEL

    if isinstance(value, float):
        if math.isnan(value):
            return NULL_SENTINEL
        return round(value, FLOAT_PRECISION)

    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return NULL_SENTINEL
        return stripped

    if isinstance(value, dict):
        return canonicalize_record(value)

    if isinstance(value, list):
        return [_normalize_value(v) for v in value]

    return value


def canonicalize_record(record: dict) -> dict:
    """Normalize a single record's values. Does not serialize."""
    return {key: _normalize_value(value) for key, value in record.items()}


def to_canonical_json(record: dict) -> str:
    """
    Produce the canonical JSON string for a record.
    Same logical record -> same string, always.
    """
    normalized = canonicalize_record(record)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))
