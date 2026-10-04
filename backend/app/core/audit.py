"""
AI Data Auditor for DataDNA.
Runs statistical checks on records at ingestion time (before raw data is discarded).
Real pandas/statistical analysis — no generic AI chatbot logic.
"""

import json
import uuid
from datetime import datetime, timezone

import pandas as pd
import numpy as np

from app.core.db import get_connection


def _detect_missing_values(df: pd.DataFrame) -> dict:
    """Count null/empty values per column."""
    missing = {}
    for col in df.columns:
        # Treat None, NaN, and empty string as missing
        null_count = df[col].isna().sum() + (df[col] == "").sum()
        if null_count > 0:
            missing[col] = int(null_count)
    return missing


def _detect_duplicates(records: list) -> int:
    """Count exact duplicate records (same values across all columns)."""
    if not records:
        return 0
    df = pd.DataFrame(records)
    return int(df.duplicated().sum())


def _detect_outliers(df: pd.DataFrame) -> dict:
    """
    IQR-based outlier detection for numeric columns.
    Returns {column: [row_indices]} for columns with detected outliers.
    """
    outliers = {}
    numeric_cols = df.select_dtypes(include=[np.number]).columns

    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 4:  # not enough data for meaningful IQR
            continue

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1

        if iqr == 0:  # no spread, skip (avoids false positives on constant columns)
            continue

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        outlier_mask = (df[col] < lower_bound) | (df[col] > upper_bound)
        outlier_indices = df[outlier_mask].index.tolist()

        if outlier_indices:
            outliers[col] = outlier_indices

    return outliers


def _is_numeric_like(val) -> bool:
    """True if val is a number, or a string that parses cleanly as one."""
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        try:
            float(val)
            return True
        except ValueError:
            return False
    return False


def _detect_schema_issues(records: list) -> dict:
    """
    Flag columns where value types are inconsistent across records.

    Two cases are covered:
    1. Genuine mixed Python types (e.g. int vs str) — the original check.
    2. CSV-sourced columns, where every value arrives as a string, but a
       column is "mostly numeric" (e.g. heart_rate_bpm) except for a stray
       non-numeric entry (e.g. "seventy-eight"). Without this, a text value
       hiding in a numeric CSV column would never be flagged, since
       csv.DictReader makes every value type(str) regardless of content.
    """
    if not records:
        return {}

    issues = {}
    columns = records[0].keys()

    for col in columns:
        types_seen = set()
        numeric_like_count = 0
        non_numeric_like_count = 0
        non_numeric_example = None

        for r in records:
            val = r.get(col)
            if val is None or val == "":
                continue
            types_seen.add(type(val).__name__)

            if _is_numeric_like(val):
                numeric_like_count += 1
            else:
                non_numeric_like_count += 1
                if non_numeric_example is None:
                    non_numeric_example = val

        if len(types_seen) > 1:
            issues[col] = f"mixed types: {', '.join(sorted(types_seen))}"
        elif numeric_like_count > 0 and non_numeric_like_count > 0:
            issues[col] = (
                f"mixed types: numeric and non-numeric "
                f"(e.g. '{non_numeric_example}')"
            )

    return issues


def _to_analyzable(value):
    """
    JSON uploads can hold lists/dicts as cell values. pandas cannot hash those
    (duplicated() crashes when a column mixes lists with other values), so they
    are turned into a stable JSON string for the pandas based checks only.
    The original records are never modified.
    """
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return value


def _prepare_for_analysis(records: list) -> list:
    return [{k: _to_analyzable(v) for k, v in r.items()} for r in records]


def analyze_records(records: list) -> dict:
    """
    Pure computation: run all checks on in-memory records, touch no database.
    Kept separate from persistence so an upload can compute the audit BEFORE
    it writes anything.
    """
    if not records:
        raise ValueError("Cannot audit empty record set")

    flat = _prepare_for_analysis(records)

    # Attempt numeric coercion for outlier detection (CSV values arrive as strings)
    df = pd.DataFrame(flat)
    df_numeric = df.copy()
    for col in df_numeric.columns:
        coerced = pd.to_numeric(df_numeric[col], errors="coerce")
        # Only replace the column if coercion actually produced mostly-numeric data
        # (avoids turning a genuinely text column into all-NaN)
        if coerced.notna().sum() >= len(coerced) * 0.5:
            df_numeric[col] = coerced

    return {
        "total_records": len(records),
        "missing_values": _detect_missing_values(df),
        "duplicate_count": _detect_duplicates(flat),
        "outliers": _detect_outliers(df_numeric),
        # Schema check uses the ORIGINAL records so "list vs str" is still reported.
        "schema_issues": _detect_schema_issues(records),
    }


def insert_audit(conn, dataset_version_id: str, analysis: dict) -> dict:
    """
    Write one audit row using the caller's connection. Does NOT commit, so it
    can be part of a larger transaction (see app/core/ingest.py).
    """
    audit_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO audit_results
           (audit_id, dataset_version_id, total_records, missing_values_json,
            duplicate_count, outliers_json, schema_issues_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_id, dataset_version_id, analysis["total_records"],
            json.dumps(analysis["missing_values"]), analysis["duplicate_count"],
            json.dumps(analysis["outliers"]), json.dumps(analysis["schema_issues"]),
            created_at,
        ),
    )

    return {
        "audit_id": audit_id,
        "dataset_version_id": dataset_version_id,
        "total_records": analysis["total_records"],
        "missing_values": analysis["missing_values"],
        "duplicate_count": analysis["duplicate_count"],
        "outliers": analysis["outliers"],
        "schema_issues": analysis["schema_issues"],
        "created_at": created_at,
    }


def run_audit(dataset_version_id: str, records: list) -> dict:
    """
    Analyze records and persist the result in its own transaction.
    The connection is always released, even when the insert fails.
    """
    analysis = analyze_records(records)

    conn = get_connection()
    try:
        result = insert_audit(conn, dataset_version_id, analysis)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return result


def get_audit(dataset_version_id: str) -> dict:
    """Retrieve the most recent audit result for a dataset version."""
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM audit_results
           WHERE dataset_version_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (dataset_version_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "audit_id": row["audit_id"],
        "dataset_version_id": row["dataset_version_id"],
        "total_records": row["total_records"],
        "missing_values": json.loads(row["missing_values_json"]),
        "duplicate_count": row["duplicate_count"],
        "outliers": json.loads(row["outliers_json"]),
        "schema_issues": json.loads(row["schema_issues_json"]),
        "created_at": row["created_at"],
    }
