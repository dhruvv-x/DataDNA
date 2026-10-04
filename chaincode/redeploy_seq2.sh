#!/bin/bash
# Deploys the datadna chaincode as version 2.0 on the running test-network.
# The sequence number is detected automatically: 1 if nothing is committed yet, else committed + 1.
# The channel and all existing ledger data stay. It never runs `network.sh down`.
# Run from anywhere:  bash ~/datadna/chaincode/redeploy_seq2.sh
set -e

TN="${TEST_NETWORK_HOME:-$HOME/fabric/fabric-samples/test-network}"
CC_DIR="${CC_DIR:-$HOME/datadna/chaincode/datadna}"

if [ ! -d "$TN" ]; then
  echo "ERROR: test-network not found at $TN"
  exit 1
fi
if [ ! -f "$CC_DIR/datadna_contract.go" ]; then
  echo "ERROR: chaincode source not found at $CC_DIR"
  exit 1
fi
for c in peer0.org1.example.com peer0.org2.example.com orderer.example.com; do
  if ! docker ps --format '{{.Names}}' | grep -qx "$c"; then
    echo "ERROR: container $c is not running."
    echo "Start them with:"
    echo "  docker start peer0.org1.example.com peer0.org2.example.com orderer.example.com ca_org1 ca_org2 ca_orderer"
    exit 1
  fi
done

cd "$TN"

export PATH="$TN/../bin:$PATH"
export FABRIC_CFG_PATH="$TN/../config/"
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ROOTCERT_FILE="$TN/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
export CORE_PEER_MSPCONFIGPATH="$TN/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
export CORE_PEER_ADDRESS=localhost:7051

CUR=$(peer lifecycle chaincode querycommitted -C mychannel -n datadna 2>/dev/null | grep -oE 'Sequence: [0-9]+' | grep -oE '[0-9]+' || true)
CURV=$(peer lifecycle chaincode querycommitted -C mychannel -n datadna 2>/dev/null | grep -oE 'Version: [0-9.]+' | head -1 | sed 's/Version: //' || true)
if [ -z "$CUR" ]; then
  SEQ=1
  echo "Nothing committed yet for datadna. Using sequence 1."
elif [ "$CURV" = "2.0" ]; then
  echo "datadna 2.0 is already committed (sequence $CUR). Nothing to do."
  exit 0
else
  SEQ=$((CUR + 1))
  echo "Found committed sequence $CUR (version $CURV). Using sequence $SEQ."
fi

echo "=== Deploying datadna 2.0 (sequence $SEQ) from $CC_DIR ==="
./network.sh deployCC -ccn datadna -ccp "$CC_DIR" -ccl go -ccv 2.0 -ccs "$SEQ"

echo
echo "=== Committed chaincode definition (expect Version: 2.0) ==="
peer lifecycle chaincode querycommitted -C mychannel -n datadna
