"""
Atomic ingestion: dataset row + version + record fingerprints + audit result
are written in ONE transaction. Either everything is saved or nothing is.

The audit is computed first (pure, no DB), so a crash in the analysis can never
leave a half-written dataset behind.
"""

from app.core.db import get_connection
from app.core.audit import analyze_records, insert_audit
from app.core.versioning import insert_dataset, insert_version


def _commit_atomically(write_fn):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = write_fn(conn)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ingest_new_dataset(name: str, records: list) -> dict:
    """Create dataset + V1 + audit atomically."""
    analysis = analyze_records(records)

    def write(conn):
        dataset_id = insert_dataset(conn, name)
        version = insert_version(conn, dataset_id, records, None)
        audit = insert_audit(conn, version["version_id"], analysis)
        return {"dataset_id": dataset_id, **version, "audit": audit}

    return _commit_atomically(write)


def ingest_new_version(dataset_id: str, records: list, parent_version_id: str) -> dict:
    """Add a version + audit to an existing dataset atomically."""
    analysis = analyze_records(records)

    def write(conn):
        version = insert_version(conn, dataset_id, records, parent_version_id)
        audit = insert_audit(conn, version["version_id"], analysis)
        return {"dataset_id": dataset_id, **version, "audit": audit}

    return _commit_atomically(write)
