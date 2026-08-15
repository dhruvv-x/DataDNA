"""
SQLite database setup for DataDNA.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "datadna.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    version_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    parent_version_id TEXT,
    version_number INTEGER NOT NULL,
    schema_fingerprint TEXT NOT NULL,
    dataset_fingerprint TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    integrity_status TEXT NOT NULL DEFAULT 'PENDING',
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (parent_version_id) REFERENCES dataset_versions (version_id)
);

CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL,
    record_fingerprint TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'VALID',
    invalidated_reason TEXT,
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (version_id)
);
CREATE TABLE IF NOT EXISTS audit_results (
    audit_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL,
    total_records INTEGER NOT NULL,
    missing_values_json TEXT NOT NULL,
    duplicate_count INTEGER NOT NULL,
    outliers_json TEXT NOT NULL,
    schema_issues_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (version_id)
);
CREATE TABLE IF NOT EXISTS models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_runs (
    training_run_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    hyperparameters_json TEXT NOT NULL DEFAULT '{}',
    actor TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (version_id),
    FOREIGN KEY (model_id) REFERENCES models (model_id)
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
