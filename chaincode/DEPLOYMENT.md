# DataDNA Chaincode Deployment Notes

Deployed to local Hyperledger Fabric test-network (2-org, `mychannel`).

- Fabric version: v2.5.16
- Chaincode label: datadna_1.0
- Package ID: datadna_1.0:d97e77d6bf9c8ac02e206b390917c8d31bda06746373ec0431047bdfdd90b977
- Sequence: 1, Version: 1.0
- Approved by: Org1MSP, Org2MSP
- Committed on channel: mychannel

## Verified on real network
- `RegisterDatasetVersion` invoke -> status:200
- `VerifyIntegrity` query with matching fingerprint -> true
- `VerifyIntegrity` query with tampered fingerprint -> false (tamper detection confirmed)

## Redeploy notes
Network location: /home/dhruv/fabric/fabric-samples/test-network
If containers were stopped (e.g. after laptop restart), restart with:
  docker start peer0.org1.example.com peer0.org2.example.com orderer.example.com ca_org1 ca_org2 ca_orderer
Do NOT run `network.sh down` -- it destroys the channel and ledger state.
