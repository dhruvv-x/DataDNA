"""
Dataset versioning engine.
Versions are immutable: creating a new version never modifies an old one.
"""

import json
import uuid
from datetime import datetime, timezone

from app.core.db import get_connection
from app.core.fingerprint import fingerprint_dataset


def _schema_fingerprint(records: list) -> str:
    """Hash of sorted column names — represents schema shape."""
    import hashlib
    if not records:
        return hashlib.sha256(b"").hexdigest()
    columns = sorted(records[0].keys())
    return hashlib.sha256(json.dumps(columns).encode("utf-8")).hexdigest()


def create_dataset(name: str) -> str:
    dataset_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO datasets (dataset_id, name, created_at) VALUES (?, ?, ?)",
        (dataset_id, name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return dataset_id


def create_version(dataset_id: str, records: list, parent_version_id: str = None) -> dict:
    """
    Create a new immutable dataset version from a list of records (dicts).
    Records must already be in row_index order.
    """
    conn = get_connection()

    version_number = 1
    if parent_version_id:
        row = conn.execute(
            "SELECT version_number FROM dataset_versions WHERE version_id = ?",
            (parent_version_id,),
        ).fetchone()
        if row is None:
            conn.close()
            raise ValueError("parent_version_id not found")
        version_number = row["version_number"] + 1

    fp_result = fingerprint_dataset(records)
    version_id = str(uuid.uuid4())
    schema_fp = _schema_fingerprint(records)

    conn.execute(
        """INSERT INTO dataset_versions
           (version_id, dataset_id, parent_version_id, version_number,
            schema_fingerprint, dataset_fingerprint, record_count,
            created_at, integrity_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            version_id, dataset_id, parent_version_id, version_number,
            schema_fp, fp_result["dataset_fingerprint"], len(records),
            datetime.now(timezone.utc).isoformat(), "VERIFIED",
        ),
    )

    for idx, rec_fp in enumerate(fp_result["record_fingerprints"]):
        conn.execute(
            """INSERT INTO records
               (record_id, dataset_version_id, record_fingerprint, row_index, status)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), version_id, rec_fp, idx, "VALID"),
        )

    conn.commit()
    conn.close()

    return {
        "version_id": version_id,
        "version_number": version_number,
        "dataset_fingerprint": fp_result["dataset_fingerprint"],
        "record_count": len(records),
    }


def list_all_datasets() -> list:
    """
    Return a summary of every dataset with its latest version info,
    newest dataset first. Powers the dashboard history panel so users
    never need to manually paste a version_id.
    HACKATHON SIMPLIFICATION: N+1 query via get_lineage() per dataset —
    fine at demo scale (tens of datasets), would need a single JOIN
    query at real production scale.
    """
    from app.core.audit import get_audit

    conn = get_connection()
    rows = conn.execute(
        "SELECT dataset_id, name, created_at FROM datasets ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    datasets = []
    for row in rows:
        dataset_id = row["dataset_id"]
        lineage = get_lineage(dataset_id)
        latest = lineage[-1] if lineage else None
        latest_has_audit = False
        if latest:
            latest_has_audit = get_audit(latest["version_id"]) is not None
        datasets.append({
            "dataset_id": dataset_id,
            "name": row["name"],
            "created_at": row["created_at"],
            "version_count": len(lineage),
            "latest_version_id": latest["version_id"] if latest else None,
            "latest_version_number": latest["version_number"] if latest else None,
            "latest_integrity_status": latest["integrity_status"] if latest else None,
            "latest_has_audit": latest_has_audit,
        })
    return datasets


def get_lineage(dataset_id: str) -> list:
    """Return full version chain for a dataset, oldest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT version_id, parent_version_id, version_number,
                  dataset_fingerprint, record_count, created_at, integrity_status, onchain_status
           FROM dataset_versions
           WHERE dataset_id = ?
           ORDER BY version_number ASC""",
        (dataset_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def invalidate_version(version_id: str) -> dict:
    """Mark a dataset version as INVALID. Raises ValueError if not found."""
    conn = get_connection()
    row = conn.execute(
        "SELECT version_id, integrity_status FROM dataset_versions WHERE version_id = ?",
        (version_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError("version_id not found")
    conn.execute(
        "UPDATE dataset_versions SET integrity_status = ? WHERE version_id = ?",
        ("INVALID", version_id),
    )
    conn.commit()
    conn.close()
    return {
        "version_id": version_id,
        "previous_status": row["integrity_status"],
        "integrity_status": "INVALID",
    }


def get_version(version_id: str) -> dict:
    """Fetch a single dataset_version row. Raises ValueError if not found."""
    conn = get_connection()
    row = conn.execute(
        """SELECT version_id, dataset_id, parent_version_id, version_number,
                  dataset_fingerprint, record_count, created_at, integrity_status, onchain_status
           FROM dataset_versions WHERE version_id = ?""",
        (version_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise ValueError("version_id not found")
    return dict(row)

def mark_registered_onchain(version_id: str) -> None:
    """
    Mark a dataset version as successfully registered on the Fabric ledger.
    Called after a successful chaincode invoke, so the backend stays in sync
    with on-chain state and doesn't attempt duplicate (rejected) registrations.
    """
    conn = get_connection()
    conn.execute(
        "UPDATE dataset_versions SET onchain_status = 'REGISTERED' WHERE version_id = ?",
        (version_id,),
    )
    conn.commit()
    conn.close()
