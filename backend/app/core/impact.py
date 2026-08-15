"""
Impact Engine — traces downstream effects of an invalidated (or hypothetically
invalidated) dataset version: which training runs used it, which models are
affected, and how severe the impact is.
"""
from app.core.versioning import get_version, get_lineage
from app.core.training import get_training_runs_for_dataset_version


def analyze_impact(version_id: str) -> dict:
    """
    Trace downstream impact of a dataset version being (or becoming) invalid.
    Works on ANY version regardless of current integrity_status (preview mode) —
    lets the demo show "what would happen" before actually invalidating.
    Raises ValueError if version_id not found.
    """
    version = get_version(version_id)  # raises ValueError if not found
    dataset_id = version["dataset_id"]

    direct_training_runs = get_training_runs_for_dataset_version(version_id)

    affected_model_ids = sorted({
        run["model_id"] for run in direct_training_runs
    })

    lineage = get_lineage(dataset_id)
    child_versions = [
        v for v in lineage if v["parent_version_id"] == version_id
    ]

    if direct_training_runs:
        severity = "HIGH"
        confidence = "HIGH"
        recommendation = "RETRAIN"
    elif child_versions:
        severity = "MEDIUM"
        confidence = "HIGH"
        recommendation = "REBUILD_DATASET"
    else:
        severity = "LOW"
        confidence = "LOW"
        recommendation = "VERIFY"

    return {
        "version_id": version_id,
        "dataset_id": dataset_id,
        "current_integrity_status": version["integrity_status"],
        "severity": severity,
        "confidence": confidence,
        "recommendation": recommendation,
        "affected_training_runs": direct_training_runs,
        "affected_model_ids": affected_model_ids,
        "affected_child_versions": [
            {
                "version_id": v["version_id"],
                "version_number": v["version_number"],
            }
            for v in child_versions
        ],
    }
