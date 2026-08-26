import sys

path = "/home/dhruv/datadna/backend/app/api/datasets.py"

marker = '''@router.get("/tokens/{token_id}/owner")
async def get_token_owner(token_id: str):
    """Query Fabric ledger for a DatasetToken's current owner."""
    try:
        result = query("GetTokenOwner", [token_id])
        return {"token_id": token_id, "owner": result}
    except FabricError as e:
        raise HTTPException(status_code=502, detail=str(e))'''

new_code = '''


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
'''

with open(path, "r") as f:
    content = f.read()

if content.count(marker) != 1:
    print(f"ERROR: expected exactly 1 occurrence of the get_token_owner marker, found {content.count(marker)}. Aborting, nothing was written.")
    sys.exit(1)

if "async def stake_tokens" in content:
    print("ERROR: stake_tokens already appears in the file — looks like this was already applied. Aborting to avoid a duplicate.")
    sys.exit(1)

content = content.replace(marker, marker + new_code, 1)

with open(path, "w") as f:
    f.write(content)

print("Done: stake, slash-stake, and stake-balance endpoints inserted successfully.")
