"""
Dataset upload API endpoints.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.core.parsing import parse_upload, ParseError
from app.core.versioning import create_dataset, create_version, get_lineage, invalidate_version, get_version, list_all_datasets
from app.core.impact import analyze_impact
from app.core.fabric_client import invoke, query, FabricError
from app.core.audit import run_audit, get_audit

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def list_datasets():
    """List every dataset with its latest version summary — powers the dashboard history panel."""
    return {"datasets": list_all_datasets()}


@router.post("")
async def upload_dataset(name: str = Form(...), file: UploadFile = File(...)):
    """
    Create a new dataset from an uploaded CSV or JSON file.
    This creates the dataset AND its first version (V1) in one call.
    """
    raw_bytes = await file.read()

    try:
        records = parse_upload(file.filename, raw_bytes)
    except ParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    dataset_id = create_dataset(name)

    try:
        version_result = create_version(dataset_id, records, parent_version_id=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create version: {e}")

    audit_result = run_audit(version_result["version_id"], records)

    return {
        "dataset_id": dataset_id,
        "name": name,
        "filename": file.filename,
        **version_result,
        "audit": {
            "duplicate_count": audit_result["duplicate_count"],
            "missing_values": audit_result["missing_values"],
            "outliers": audit_result["outliers"],
            "schema_issues": audit_result["schema_issues"],
        },
    }


@router.get("/{dataset_id}/lineage")
def dataset_lineage(dataset_id: str):
    """Return the full version history for a dataset."""
    lineage = get_lineage(dataset_id)
    if not lineage:
        raise HTTPException(status_code=404, detail="Dataset not found or has no versions")
    return {"dataset_id": dataset_id, "versions": lineage}


@router.post("/{dataset_id}/versions")
async def upload_new_version(
    dataset_id: str,
    file: UploadFile = File(...),
    parent_version_id: str = Form(default=None),
):
    """
    Add a new immutable version to an existing dataset.
    If parent_version_id is not given, uses the latest existing version as parent.
    """
    raw_bytes = await file.read()

    try:
        records = parse_upload(file.filename, raw_bytes)
    except ParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    lineage = get_lineage(dataset_id)
    if not lineage:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if parent_version_id is None:
        parent_version_id = lineage[-1]["version_id"]  # latest version

    try:
        version_result = create_version(dataset_id, records, parent_version_id=parent_version_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create version: {e}")

    audit_result = run_audit(version_result["version_id"], records)

    return {
        "dataset_id": dataset_id,
        "filename": file.filename,
        **version_result,
        "audit": {
            "duplicate_count": audit_result["duplicate_count"],
            "missing_values": audit_result["missing_values"],
            "outliers": audit_result["outliers"],
            "schema_issues": audit_result["schema_issues"],
        },
    }


@router.get("/versions/{version_id}/audit")
def get_version_audit(version_id: str):
    """Retrieve the AI audit results for a specific dataset version."""
    result = get_audit(version_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No audit found for this version")
    return result


@router.get("/versions/{version_id}/trust")
def get_version_trust_score(version_id: str):
    """Compute and return the explainable trust score for a dataset version."""
    from app.core.trust import compute_trust_score
    try:
        return compute_trust_score(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/versions/{version_id}/invalidate")
async def invalidate_dataset_version(version_id: str):
    """Mark a dataset version as INVALID, for impact analysis testing/demo."""
    try:
        return invalidate_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/versions/{version_id}/impact")
async def get_impact_analysis(version_id: str):
    """
    Trace downstream impact if this dataset version is (or becomes) invalid.
    Works regardless of current integrity_status — preview mode.
    """
    try:
        return analyze_impact(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/versions/{version_id}/register-onchain")
async def register_onchain(version_id: str):
    """
    Manually register this dataset version's provenance on the Fabric ledger.
    HACKATHON SIMPLIFICATION: explicit trigger, not automatic on upload —
    keeps blockchain registration deliberate and demo-controllable.
    """
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        result = invoke(
            "RegisterDatasetVersion",
            [
                version["dataset_id"],
                str(version["version_number"]),
                version["parent_version_id"] or "",
                version["dataset_fingerprint"],
                "",
                "dhruv",
                version["created_at"],
            ],
        )
        return {"version_id": version_id, "status": "registered", "fabric_output": result}
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/versions/{version_id}/verify-onchain")
async def verify_onchain(version_id: str):
    """Query Fabric ledger to verify this version's fingerprint matches on-chain record."""
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        result = query(
            "VerifyIntegrity",
            [version["dataset_id"], str(version["version_number"]), version["dataset_fingerprint"]],
        )
        return {"version_id": version_id, "verified": result}
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))