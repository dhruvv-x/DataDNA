import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import tempfile
import pytest

import app.core.db as db_module
db_module.DB_PATH = tempfile.mktemp(suffix=".db")
db_module.init_db()

from app.core.training import (
    register_model,
    register_training_run,
    get_training_runs_for_model,
    get_training_runs_for_dataset_version,
)
from app.core.versioning import create_dataset, create_version


def _make_version():
    dataset_id = create_dataset("TrainingTestSet")
    result = create_version(dataset_id, [{"name": "Alice", "age": "30"}])
    return result["version_id"]


def test_register_model_returns_id():
    result = register_model("CropDiseaseClassifier", "v1")
    assert "model_id" in result
    assert result["name"] == "CropDiseaseClassifier"
    assert result["version"] == "v1"


def test_register_training_run_links_version_and_model():
    version_id = _make_version()
    model = register_model("TestModel", "v1")

    run = register_training_run(version_id, model["model_id"], hyperparameters={"lr": 0.01})

    assert run["dataset_version_id"] == version_id
    assert run["model_id"] == model["model_id"]
    assert run["hyperparameters"] == {"lr": 0.01}


def test_register_training_run_invalid_dataset_version_raises():
    model = register_model("TestModel", "v1")
    with pytest.raises(ValueError):
        register_training_run("nonexistent-version-id", model["model_id"])


def test_register_training_run_invalid_model_raises():
    version_id = _make_version()
    with pytest.raises(ValueError):
        register_training_run(version_id, "nonexistent-model-id")


def test_register_training_run_default_empty_hyperparameters():
    version_id = _make_version()
    model = register_model("TestModel", "v1")
    run = register_training_run(version_id, model["model_id"])
    assert run["hyperparameters"] == {}


def test_get_training_runs_for_model_returns_all_runs():
    version_id = _make_version()
    model = register_model("TestModel", "v1")
    register_training_run(version_id, model["model_id"])
    register_training_run(version_id, model["model_id"])

    runs = get_training_runs_for_model(model["model_id"])
    assert len(runs) == 2


def test_get_training_runs_for_model_empty_when_none():
    model = register_model("UnusedModel", "v1")
    runs = get_training_runs_for_model(model["model_id"])
    assert runs == []


def test_get_training_runs_for_dataset_version_returns_all_runs():
    version_id = _make_version()
    model_a = register_model("ModelA", "v1")
    model_b = register_model("ModelB", "v1")

    register_training_run(version_id, model_a["model_id"])
    register_training_run(version_id, model_b["model_id"])

    runs = get_training_runs_for_dataset_version(version_id)
    assert len(runs) == 2
    model_ids = {r["model_id"] for r in runs}
    assert model_ids == {model_a["model_id"], model_b["model_id"]}


def test_get_training_runs_for_dataset_version_empty_when_none():
    version_id = _make_version()
    runs = get_training_runs_for_dataset_version(version_id)
    assert runs == []
