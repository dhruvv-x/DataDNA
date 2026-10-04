"""
S1c regression tests (backend side):
- register-onchain no longer sends a caller supplied org; chaincode takes the author
  from the transaction certificate (6 args, not 7)
- token / stake / slash / ownership endpoints and the Org2 invoker are gone
- the Go chaincode source no longer contains the removed features or trusted params
Fabric itself is mocked here. The chaincode behaviour is covered by the Go tests.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.db as db_module
from app.core.db import init_db
import app.core.fabric_client as fabric_client
import app.api.datasets as datasets_api
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

CHAINCODE_SRC = Path(__file__).resolve().parents[3] / "chaincode" / "datadna" / "datadna_contract.go"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    previous = db_module.DB_PATH
    db_module.DB_PATH = str(tmp_path / "s1c.db")
    init_db()
    yield
    db_module.DB_PATH = previous


def _new_version():
    resp = client.post(
        "/datasets",
        data={"name": "S1c"},
        files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    assert resp.status_code == 200
    return resp.json()


def test_register_sends_six_args_without_org(monkeypatch):
    body = _new_version()
    seen = {}

    def fake_invoke(fn, args):
        seen["fn"] = fn
        seen["args"] = args
        return "status:200"

    monkeypatch.setattr(datasets_api, "invoke", fake_invoke)
    resp = client.post(f"/datasets/versions/{body['version_id']}/register-onchain")
    assert resp.status_code == 200
    assert seen["fn"] == "RegisterDatasetVersion"
    assert len(seen["args"]) == 6
    assert seen["args"][0] == body["dataset_id"]
    assert seen["args"][1] == "1"
    assert seen["args"][3] == body["dataset_fingerprint"]


def test_register_ignores_a_spoofed_org_in_the_request_body(monkeypatch):
    body = _new_version()
    seen = {}
    monkeypatch.setattr(datasets_api, "invoke", lambda fn, args: seen.update(args=args) or "status:200")
    resp = client.post(
        f"/datasets/versions/{body['version_id']}/register-onchain",
        json={"org": "Org2MSP"},
    )
    assert resp.status_code == 200
    assert "Org2MSP" not in seen["args"]
    assert len(seen["args"]) == 6


@pytest.mark.parametrize("method,path", [
    ("post", "/datasets/versions/x/transfer-ownership"),
    ("get", "/datasets/versions/x/owner"),
    ("post", "/datasets/versions/x/mint-token"),
    ("post", "/datasets/tokens/t1/transfer"),
    ("get", "/datasets/tokens/t1/owner"),
    ("post", "/datasets/versions/x/stake"),
    ("post", "/datasets/versions/x/slash-stake"),
    ("get", "/datasets/versions/x/stake-balance"),
])
def test_removed_endpoints_are_gone(method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code in (404, 405)


def test_kept_onchain_endpoints_still_exist():
    paths = set(app.openapi()["paths"].keys())
    assert "/datasets/versions/{version_id}/register-onchain" in paths
    assert "/datasets/versions/{version_id}/verify-onchain" in paths


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
    # Every write function must call callerMSP before touching state.
    assert src.count("callerMSP(ctx)") == 3
