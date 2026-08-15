"""
Dataset upload API endpoints.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.core.parsing import parse_upload, ParseError
from app.core.versioning import create_dataset, create_version, get_lineage

router = APIRouter(prefix="/datasets", tags=["datasets"])


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

    return {
        "dataset_id": dataset_id,
        "name": name,
        "filename": file.filename,
        **version_result,
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

    return {
        "dataset_id": dataset_id,
        "filename": file.filename,
        **version_result,
    }
