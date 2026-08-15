"""
Trust Engine for DataDNA.
Computes an explainable trust score for a dataset version.
Every sub-score is derived from raw data already in dataset_versions + audit_results.
No black-box ML — fully transparent, formula-based.
"""

from app.core.db import get_connection
from app.core.audit import get_audit


def _integrity_score(integrity_status: str) -> float:
    """100 if verified, 0 if not (e.g. PENDING or TAMPERED)."""
    return 100.0 if integrity_status == "VERIFIED" else 0.0


def _quality_score(audit: dict, record_count: int) -> float:
    """
    Penalize based on proportion of records affected by missing values,
    duplicates, and outliers. Floors at 0.
    """
    if record_count == 0:
        return 0.0

    total_missing = sum(audit["missing_values"].values())
    missing_pct = total_missing / record_count

    duplicate_pct = audit["duplicate_count"] / record_count

    total_outliers = sum(len(v) for v in audit["outliers"].values())
    outlier_pct = total_outliers / record_count

    score = 100.0 - (missing_pct * 50) - (duplicate_pct * 30) - (outlier_pct * 20)
    return max(0.0, min(100.0, score))


def _provenance_score(version_number: int) -> float:
    """
    Base 70 for any registered version, +10 per prior version in the chain
    (documented lineage increases confidence), capped at 100.
    """
    prior_versions = version_number - 1
    score = 70.0 + (prior_versions * 10.0)
    return min(100.0, score)


def _anomaly_risk_score(audit: dict) -> float:
    """
    100 minus penalty per flagged column (outlier columns + schema issue columns).
    Each flagged column costs 15 points, floored at 0.
    """
    flagged_columns = len(audit["outliers"]) + len(audit["schema_issues"])
    score = 100.0 - (flagged_columns * 15.0)
    return max(0.0, score)


def compute_trust_score(version_id: str) -> dict:
    """
    Compute the full explainable trust score for a dataset version.
    Raises ValueError if the version or its audit is not found.
    """
    conn = get_connection()
    row = conn.execute(
        """SELECT version_id, version_number, record_count, integrity_status
           FROM dataset_versions WHERE version_id = ?""",
        (version_id,),
    ).fetchone()
    conn.close()

    if row is None:
        raise ValueError(f"Dataset version {version_id} not found")

    audit = get_audit(version_id)
    if audit is None:
        raise ValueError(f"No audit results found for version {version_id} — cannot compute trust score")

    integrity = _integrity_score(row["integrity_status"])
    quality = _quality_score(audit, row["record_count"])
    provenance = _provenance_score(row["version_number"])
    anomaly_risk = _anomaly_risk_score(audit)

    overall = (
        integrity * 0.30
        + quality * 0.30
        + provenance * 0.20
        + anomaly_risk * 0.20
    )

    return {
        "version_id": version_id,
        "overall_score": round(overall, 1),
        "breakdown": {
            "integrity": {
                "score": round(integrity, 1),
                "weight": 0.30,
                "explanation": f"Integrity status: {row['integrity_status']}",
            },
            "quality": {
                "score": round(quality, 1),
                "weight": 0.30,
                "explanation": (
                    f"{sum(audit['missing_values'].values())} missing values, "
                    f"{audit['duplicate_count']} duplicates, "
                    f"{sum(len(v) for v in audit['outliers'].values())} outliers "
                    f"out of {row['record_count']} records"
                ),
            },
            "provenance": {
                "score": round(provenance, 1),
                "weight": 0.20,
                "explanation": f"Version {row['version_number']} in documented lineage chain",
            },
            "anomaly_risk": {
                "score": round(anomaly_risk, 1),
                "weight": 0.20,
                "explanation": (
                    f"{len(audit['outliers'])} column(s) with outliers, "
                    f"{len(audit['schema_issues'])} column(s) with schema issues"
                ),
            },
        },
    }
