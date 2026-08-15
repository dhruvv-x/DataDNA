"""
Fabric client — wraps `peer chaincode invoke/query` via subprocess, reusing the
exact env vars and command syntax already verified manually on the real 2-org
test-network. HACKATHON SIMPLIFICATION: shells out to peer CLI instead of using
an SDK (fabric-sdk-py is poorly maintained / version-uncertain — not worth the
risk this close to deadline; this reuses commands already proven working).
"""
import subprocess
import json
import os

TEST_NETWORK_DIR = "/home/dhruv/fabric/fabric-samples/test-network"

ORDERER_CA = (
    "{dir}/organizations/ordererOrganizations/example.com/orderers/"
    "orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
).format(dir=TEST_NETWORK_DIR)

ORG1_TLS_ROOTCERT = (
    "{dir}/organizations/peerOrganizations/org1.example.com/peers/"
    "peer0.org1.example.com/tls/ca.crt"
).format(dir=TEST_NETWORK_DIR)

ORG2_TLS_ROOTCERT = (
    "{dir}/organizations/peerOrganizations/org2.example.com/peers/"
    "peer0.org2.example.com/tls/ca.crt"
).format(dir=TEST_NETWORK_DIR)

ORG1_MSPCONFIGPATH = (
    "{dir}/organizations/peerOrganizations/org1.example.com/users/"
    "Admin@org1.example.com/msp"
).format(dir=TEST_NETWORK_DIR)


class FabricError(Exception):
    """Raised when a peer CLI invoke/query fails."""
    pass


def _build_env() -> dict:
    """Env vars matching the manually-verified Org1MSP admin invocation."""
    env = os.environ.copy()
    env["PATH"] = f"{TEST_NETWORK_DIR}/../bin:" + env.get("PATH", "")
    env["FABRIC_CFG_PATH"] = f"{TEST_NETWORK_DIR}/../config/"
    env["CORE_PEER_TLS_ENABLED"] = "true"
    env["CORE_PEER_LOCALMSPID"] = "Org1MSP"
    env["CORE_PEER_TLS_ROOTCERT_FILE"] = ORG1_TLS_ROOTCERT
    env["CORE_PEER_MSPCONFIGPATH"] = ORG1_MSPCONFIGPATH
    env["CORE_PEER_ADDRESS"] = "localhost:7051"
    return env


def invoke(function: str, args: list) -> str:
    """
    Invoke a chaincode function requiring endorsement (both orgs).
    Returns raw stdout+stderr on success. Raises FabricError on failure.
    """
    cc_input = json.dumps({"function": function, "Args": args})
    cmd = [
        "peer", "chaincode", "invoke",
        "-o", "localhost:7050",
        "--ordererTLSHostnameOverride", "orderer.example.com",
        "--tls",
        "--cafile", ORDERER_CA,
        "-C", "mychannel",
        "-n", "datadna",
        "--peerAddresses", "localhost:7051",
        "--tlsRootCertFiles", ORG1_TLS_ROOTCERT,
        "--peerAddresses", "localhost:9051",
        "--tlsRootCertFiles", ORG2_TLS_ROOTCERT,
        "-c", cc_input,
    ]
    result = subprocess.run(
        cmd, cwd=TEST_NETWORK_DIR, env=_build_env(),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise FabricError(f"invoke failed: {result.stderr.strip()}")
    return (result.stdout + result.stderr).strip()


def query(function: str, args: list) -> str:
    """
    Query a chaincode function (no endorsement/ordering needed).
    Returns raw stdout. Raises FabricError on failure.
    """
    cc_input = json.dumps({"function": function, "Args": args})
    cmd = [
        "peer", "chaincode", "query",
        "-C", "mychannel",
        "-n", "datadna",
        "-c", cc_input,
    ]
    result = subprocess.run(
        cmd, cwd=TEST_NETWORK_DIR, env=_build_env(),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise FabricError(f"query failed: {result.stderr.strip()}")
    return result.stdout.strip()
