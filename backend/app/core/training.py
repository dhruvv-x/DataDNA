"""
Training Run + Model registration for DataDNA.
Intentionally thin: registers provenance metadata only.
No actual ML training happens here — this tracks WHICH dataset version
trained WHICH model, feeding the Impact Engine's dependency graph.
"""

import json
import uuid
from datetime import datetime, timezone

from app.core.db import get_connection


def register_model(name: str, version: str) -> dict:
    """Register a new model identity."""
    model_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        "INSERT INTO models (model_id, name, version, created_at) VALUES (?, ?, ?, ?)",
        (model_id, name, version, created_at),
    )
    conn.commit()
    conn.close()

    return {"model_id": model_id, "name": name, "version": version, "created_at": created_at}


def register_training_run(
    dataset_version_id: str,
    model_id: str,
    hyperparameters: dict = None,
    actor: str = None,
) -> dict:
    """
    Register a training run linking a dataset version to a model.
    Validates that both the dataset_version_id and model_id exist.
    """
    if hyperparameters is None:
        hyperparameters = {}

    conn = get_connection()

    version_row = conn.execute(
        "SELECT version_id FROM dataset_versions WHERE version_id = ?",
        (dataset_version_id,),
    ).fetchone()
    if version_row is None:
        conn.close()
        raise ValueError(f"dataset_version_id {dataset_version_id} not found")

    model_row = conn.execute(
        "SELECT model_id FROM models WHERE model_id = ?", (model_id,)
    ).fetchone()
    if model_row is None:
        conn.close()
        raise ValueError(f"model_id {model_id} not found")

    training_run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO training_runs
           (training_run_id, dataset_version_id, model_id, hyperparameters_json, actor, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (training_run_id, dataset_version_id, model_id, json.dumps(hyperparameters), actor, created_at),
    )
    conn.commit()
    conn.close()

    return {
        "training_run_id": training_run_id,
        "dataset_version_id": dataset_version_id,
        "model_id": model_id,
        "hyperparameters": hyperparameters,
        "actor": actor,
        "created_at": created_at,
    }


def get_training_runs_for_model(model_id: str) -> list:
    """Return all training runs that produced/used this model."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT training_run_id, dataset_version_id, model_id,
                  hyperparameters_json, actor, created_at
           FROM training_runs WHERE model_id = ? ORDER BY created_at ASC""",
        (model_id,),
    ).fetchall()
    conn.close()

    return [
        {
            "training_run_id": r["training_run_id"],
            "dataset_version_id": r["dataset_version_id"],
            "model_id": r["model_id"],
            "hyperparameters": json.loads(r["hyperparameters_json"]),
            "actor": r["actor"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def get_training_runs_for_dataset_version(dataset_version_id: str) -> list:
    """
    Return all training runs that used this dataset version.
    This is the reverse-lookup the Impact Engine needs: given a dataset
    version, find every model potentially affected by it.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT training_run_id, dataset_version_id, model_id,
                  hyperparameters_json, actor, created_at
           FROM training_runs WHERE dataset_version_id = ? ORDER BY created_at ASC""",
        (dataset_version_id,),
    ).fetchall()
    conn.close()

    return [
        {
            "training_run_id": r["training_run_id"],
            "dataset_version_id": r["dataset_version_id"],
            "model_id": r["model_id"],
            "hyperparameters": json.loads(r["hyperparameters_json"]),
            "actor": r["actor"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
