#!/bin/bash
cd /home/dhruv/fabric/fabric-samples/test-network
export PATH=${PWD}/../bin:$PATH
export FABRIC_CFG_PATH=$PWD/../config/
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID="Org1MSP"
export CORE_PEER_TLS_ROOTCERT_FILE=${PWD}/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt
export CORE_PEER_MSPCONFIGPATH=${PWD}/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp
export CORE_PEER_ADDRESS=localhost:7051

echo ""
echo "=== DataDNA Chaincode — Multi-Org Blockchain Proof ==="
echo ""
peer lifecycle chaincode querycommitted --channelID mychannel --name datadna
echo ""
echo "^ Notice: BOTH Org1MSP and Org2MSP show 'true' — this chaincode"
echo "  could only go live because two independent organizations"
echo "  each approved it. No single party controls this ledger."
echo ""
