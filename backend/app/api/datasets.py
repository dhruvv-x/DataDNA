"""
Dataset upload API endpoints.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.core.parsing import parse_upload, ParseError
from app.core.ingest import ingest_new_dataset, ingest_new_version
from app.core.versioning import get_lineage, invalidate_version, get_version, list_all_datasets, mark_registered_onchain
from app.core.impact import analyze_impact
from app.core.fabric_client import invoke, query, FabricError
from app.core.audit import get_audit

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def list_datasets():
    """List every dataset with its latest version summary — powers the dashboard history panel."""
    return {"datasets": list_all_datasets()}


def _audit_summary(audit: dict) -> dict:
    return {
        "duplicate_count": audit["duplicate_count"],
        "missing_values": audit["missing_values"],
        "outliers": audit["outliers"],
        "schema_issues": audit["schema_issues"],
    }


@router.post("")
async def upload_dataset(name: str = Form(...), file: UploadFile = File(...)):
    """
    Create a new dataset from an uploaded CSV or JSON file.
    Dataset, V1, record fingerprints and audit are saved in ONE transaction:
    if anything fails, nothing is saved and the caller gets a visible error.
    """
    raw_bytes = await file.read()

    try:
        records = parse_upload(file.filename, raw_bytes)
    except ParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        result = ingest_new_dataset(name, records)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed, nothing was saved: {e}")

    audit = result.pop("audit")
    return {
        "name": name,
        "filename": file.filename,
        **result,
        "audit": _audit_summary(audit),
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
    Add a new immutable version to an existing dataset (atomic with its audit).
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
        result = ingest_new_version(dataset_id, records, parent_version_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed, nothing was saved: {e}")

    audit = result.pop("audit")
    return {
        "filename": file.filename,
        **result,
        "audit": _audit_summary(audit),
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
    The author recorded on-chain is the MSP of the peer identity that signs the
    transaction (chaincode reads it from the certificate). It is not a request field.
    HACKATHON SIMPLIFICATION: explicit trigger, not automatic on upload —
    keeps blockchain registration deliberate and demo-controllable.

    Idempotent: if this version is already marked REGISTERED in the local DB,
    skips the Fabric call entirely and returns the existing status, instead of
    hitting chaincode's immutability rejection (which surfaces as a 502).
    """
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if version["onchain_status"] == "REGISTERED":
        return {
            "version_id": version_id,
            "status": "already_registered",
            "fabric_output": None,
        }

    try:
        result = invoke(
            "RegisterDatasetVersion",
            [
                version["dataset_id"],
                str(version["version_number"]),
                version["parent_version_id"] or "",
                version["dataset_fingerprint"],
                "",
                version["created_at"],
            ],
        )
        mark_registered_onchain(version_id)
        return {"version_id": version_id, "status": "registered", "fabric_output": result}
    except FabricError as e:
        if "already registered on-chain" in str(e):
            # Never trust the error text alone: confirm the on-chain fingerprint
            # really equals ours before marking this version REGISTERED locally.
            try:
                matches = query(
                    "VerifyIntegrity",
                    [version["dataset_id"], str(version["version_number"]), version["dataset_fingerprint"]],
                ).strip().lower() == "true"
            except FabricError as verify_err:
                raise HTTPException(status_code=502, detail=str(verify_err))
            if not matches:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A different fingerprint is already registered on-chain for this "
                        "dataset/version number; refusing to mark it REGISTERED."
                    ),
                )
            mark_registered_onchain(version_id)
            return {
                "version_id": version_id,
                "status": "already_registered",
                "fabric_output": None,
            }
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
