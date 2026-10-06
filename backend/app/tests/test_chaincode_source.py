"""Checks on the Go chaincode source (kept from S1c). Fabric itself is covered by the Go tests."""
from pathlib import Path

import app.core.fabric_client as fabric_client

CHAINCODE_SRC = Path(__file__).resolve().parents[3] / "chaincode" / "datadna" / "datadna_contract.go"


def test_org2_invoker_is_removed_from_fabric_client():
    assert not hasattr(fabric_client, "invoke_as_org2")
    assert not hasattr(fabric_client, "_build_env_org2")


def test_chaincode_source_has_no_removed_features_or_trusted_org_params():
    src = CHAINCODE_SRC.read_text()
    for banned in [
        "TransferDatasetOwnership", "GetDatasetOwner", "MintDatasetToken", "TransferToken",
        "GetTokenOwner", "StakeTokens", "SlashStake", "GetStakeBalance",
        "OwnerOrg", "callerOrg", "stakerOrg", "mintedBy",
    ]:
        assert banned not in src, f"{banned} must not be in the chaincode"


def test_chaincode_reads_identity_from_the_certificate():
    src = CHAINCODE_SRC.read_text()
    assert "GetClientIdentity()" in src
    assert "GetMSPID()" in src
    assert src.count("callerMSP(ctx)") == 3
