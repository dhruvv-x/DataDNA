"""
Impact Engine: traces downstream effects of an invalidated (or hypothetically
invalidated) dataset version: which training runs used it or any version derived
from it, which models are affected, and how severe the impact is.
"""
from collections import deque

from app.core.versioning import get_version, get_lineage
from app.core.training import get_training_runs_for_dataset_version


def _descendants(lineage: list, root_version_id: str) -> list:
    """
    All versions derived (directly or transitively) from root_version_id,
    breadth-first, each with its depth (1 = direct child). Cycle-safe.
    """
    children = {}
    for v in lineage:
        children.setdefault(v["parent_version_id"], []).append(v)

    found = []
    seen = {root_version_id}
    queue = deque([(root_version_id, 0)])
    while queue:
        current, depth = queue.popleft()
        for child in children.get(current, []):
            if child["version_id"] in seen:
                continue
            seen.add(child["version_id"])
            found.append({
                "version_id": child["version_id"],
                "version_number": child["version_number"],
                "depth": depth + 1,
            })
            queue.append((child["version_id"], depth + 1))
    return found


def analyze_impact(version_id: str) -> dict:
    """
    Trace downstream impact of a dataset version being (or becoming) invalid.
    Works on ANY version regardless of current integrity_status (preview mode),
    which lets the demo show "what would happen" before actually invalidating.
    Raises ValueError if version_id not found.

    Training runs on the version itself are DIRECT (confidence HIGH). Runs on
    versions derived from it are DOWNSTREAM: the child was built from invalid
    data, so affected is likely, but not certain (confidence MEDIUM).
    """
    version = get_version(version_id)  # raises ValueError if not found
    dataset_id = version["dataset_id"]

    lineage = get_lineage(dataset_id)
    descendants = _descendants(lineage, version_id)

    direct_runs = [
        {**run, "via_version_id": version_id, "depth": 0}
        for run in get_training_runs_for_dataset_version(version_id)
    ]
    downstream_runs = []
    for d in descendants:
        for run in get_training_runs_for_dataset_version(d["version_id"]):
            downstream_runs.append(
                {**run, "via_version_id": d["version_id"], "depth": d["depth"]}
            )

    all_runs = direct_runs + downstream_runs
    affected_model_ids = sorted({run["model_id"] for run in all_runs})

    if direct_runs:
        severity, confidence, recommendation = "HIGH", "HIGH", "RETRAIN"
    elif downstream_runs:
        severity, confidence, recommendation = "HIGH", "MEDIUM", "REBUILD_AND_RETRAIN"
    elif descendants:
        severity, confidence, recommendation = "MEDIUM", "HIGH", "REBUILD_DATASET"
    else:
        severity, confidence, recommendation = "LOW", "LOW", "VERIFY"

    return {
        "version_id": version_id,
        "dataset_id": dataset_id,
        "current_integrity_status": version["integrity_status"],
        "severity": severity,
        "confidence": confidence,
        "recommendation": recommendation,
        "affected_training_runs": all_runs,
        "direct_training_run_count": len(direct_runs),
        "downstream_training_run_count": len(downstream_runs),
        "affected_model_ids": affected_model_ids,
        "affected_child_versions": [
            {"version_id": d["version_id"], "version_number": d["version_number"]}
            for d in descendants if d["depth"] == 1
        ],
        "affected_descendant_versions": descendants,
    }
