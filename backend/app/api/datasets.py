"""
Dataset upload API endpoints.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
import json
from datetime import datetime, timezone
from app.core.parsing import parse_upload, ParseError
from app.core.versioning import create_dataset, create_version, get_lineage, invalidate_version, get_version, list_all_datasets, mark_registered_onchain
from app.core.impact import analyze_impact
from app.core.fabric_client import invoke, invoke_as_org2, query, FabricError
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


class RegisterOnChainRequest(BaseModel):
    org: str = "Org1MSP"


@router.post("/versions/{version_id}/register-onchain")
async def register_onchain(version_id: str, body: RegisterOnChainRequest = RegisterOnChainRequest()):
    """
    Manually register this dataset version's provenance on the Fabric ledger.
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
                body.org,
                version["created_at"],
            ],
        )
        mark_registered_onchain(version_id)
        return {"version_id": version_id, "status": "registered", "fabric_output": result}
    except FabricError as e:
        if "already registered on-chain" in str(e):
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


class TransferOwnershipRequest(BaseModel):
    new_owner_org: str
    caller_org: str = "Org1MSP"


@router.post("/versions/{version_id}/transfer-ownership")
async def transfer_ownership(version_id: str, body: TransferOwnershipRequest):
    """
    Transfer on-chain ownership of this dataset version to a new org.
    Rejected by chaincode unless caller_org matches the current OwnerOrg.
    """
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    invoke_fn = invoke_as_org2 if body.caller_org == "Org2MSP" else invoke

    try:
        result = invoke_fn(
            "TransferDatasetOwnership",
            [
                version["dataset_id"],
                str(version["version_number"]),
                body.new_owner_org,
                body.caller_org,
            ],
        )
        return {
            "version_id": version_id,
            "status": "transferred",
            "new_owner": body.new_owner_org,
            "fabric_output": result,
        }
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/versions/{version_id}/owner")
async def get_owner(version_id: str):
    """Query Fabric ledger for this version's current OwnerOrg."""
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        result = query(
            "GetDatasetOwner",
            [version["dataset_id"], str(version["version_number"])],
        )
        return {"version_id": version_id, "owner": result}
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))
    

class MintTokenRequest(BaseModel):
    token_id: str
    owner: str = "Org1MSP"
    caller_org: str = "Org1MSP"


@router.post("/versions/{version_id}/mint-token")
async def mint_token(version_id: str, body: MintTokenRequest):
    """
    Mint a new DatasetToken (NFT-equivalent) for this dataset version.
    Fails if the underlying version isn't registered on-chain yet, or if
    token_id has already been minted (mint-once, enforced by chaincode).
    """
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    invoke_fn = invoke_as_org2 if body.caller_org == "Org2MSP" else invoke

    try:
        result = invoke_fn(
            "MintDatasetToken",
            [
                body.token_id,
                version["dataset_id"],
                str(version["version_number"]),
                body.owner,
                body.caller_org,
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return {
            "version_id": version_id,
            "token_id": body.token_id,
            "status": "minted",
            "owner": body.owner,
            "fabric_output": result,
        }
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


class TransferTokenRequest(BaseModel):
    new_owner: str
    caller_org: str = "Org1MSP"


@router.post("/tokens/{token_id}/transfer")
async def transfer_token(token_id: str, body: TransferTokenRequest):
    """
    Transfer ownership of a minted DatasetToken to a new org.
    Rejected by chaincode unless caller_org matches the token's current owner.
    """
    invoke_fn = invoke_as_org2 if body.caller_org == "Org2MSP" else invoke

    try:
        result = invoke_fn(
            "TransferToken",
            [token_id, body.new_owner, body.caller_org],
        )
        return {
            "token_id": token_id,
            "status": "transferred",
            "new_owner": body.new_owner,
            "fabric_output": result,
        }
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/tokens/{token_id}/owner")
async def get_token_owner(token_id: str):
    """Query Fabric ledger for a DatasetToken's current owner."""
    try:
        result = query("GetTokenOwner", [token_id])
        return {"token_id": token_id, "owner": result}
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


class StakeTokensRequest(BaseModel):
    staker_org: str = "Org1MSP"
    amount: int
    caller_org: str = "Org1MSP"


@router.post("/versions/{version_id}/stake")
async def stake_tokens(version_id: str, body: StakeTokensRequest):
    """
    Stake tokens against this dataset version as collateral. Fails if the
    version isn't registered on-chain yet, or if staker_org has already
    staked on this version (enforced by chaincode).
    """
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    invoke_fn = invoke_as_org2 if body.caller_org == "Org2MSP" else invoke
    try:
        result = invoke_fn(
            "StakeTokens",
            [
                version["dataset_id"],
                str(version["version_number"]),
                body.staker_org,
                str(body.amount),
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        return {
            "version_id": version_id,
            "staker_org": body.staker_org,
            "amount": body.amount,
            "status": "staked",
            "fabric_output": result,
        }
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


class SlashStakeRequest(BaseModel):
    staker_org: str = "Org1MSP"
    caller_org: str = "Org1MSP"


@router.post("/versions/{version_id}/slash-stake")
async def slash_stake(version_id: str, body: SlashStakeRequest):
    """
    Slash an existing stake on this dataset version (e.g. after it's been
    marked INVALID). Fails if no stake exists, or if it was already slashed.
    """
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    invoke_fn = invoke_as_org2 if body.caller_org == "Org2MSP" else invoke
    try:
        result = invoke_fn(
            "SlashStake",
            [version["dataset_id"], str(version["version_number"]), body.staker_org],
        )
        return {
            "version_id": version_id,
            "staker_org": body.staker_org,
            "status": "slashed",
            "fabric_output": result,
        }
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/versions/{version_id}/stake-balance")
async def get_stake_balance(version_id: str, staker_org: str = "Org1MSP"):
    """Query Fabric ledger for a StakeBalance on this dataset version."""
    try:
        version = get_version(version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        result = query(
            "GetStakeBalance",
            [version["dataset_id"], str(version["version_number"]), staker_org],
        )
        stake_balance = json.loads(result)
        return {"version_id": version_id, "staker_org": staker_org, "stake_balance": stake_balance}
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"failed to parse stake balance from chaincode: {e}")
