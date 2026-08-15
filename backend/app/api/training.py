"""
Training run and model registration API endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.training import (
    register_model,
    register_training_run,
    get_training_runs_for_model,
    get_training_runs_for_dataset_version,
)

router = APIRouter(tags=["training"])


class ModelCreate(BaseModel):
    name: str
    version: str


class TrainingRunCreate(BaseModel):
    dataset_version_id: str
    model_id: str
    hyperparameters: dict = {}
    actor: str = None


@router.post("/models")
def create_model(payload: ModelCreate):
    return register_model(payload.name, payload.version)


@router.post("/training-runs")
def create_training_run(payload: TrainingRunCreate):
    try:
        return register_training_run(
            payload.dataset_version_id,
            payload.model_id,
            hyperparameters=payload.hyperparameters,
            actor=payload.actor,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/models/{model_id}/training-runs")
def list_training_runs_for_model(model_id: str):
    return {"model_id": model_id, "training_runs": get_training_runs_for_model(model_id)}


@router.get("/datasets/versions/{version_id}/training-runs")
def list_training_runs_for_version(version_id: str):
    return {
        "dataset_version_id": version_id,
        "training_runs": get_training_runs_for_dataset_version(version_id),
    }
