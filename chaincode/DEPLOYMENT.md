# DataDNA Chaincode Deployment Notes

Deployed to local Hyperledger Fabric test-network (2-org, `mychannel`).
Fabric version: v2.5.16. Network location: /home/dhruv/fabric/fabric-samples/test-network

## Sequence 1 (original)
- Chaincode label: datadna_1.0, Sequence: 1, Version: 1.0
- Approved by Org1MSP and Org2MSP, committed on mychannel
- Verified: RegisterDatasetVersion invoke gives status 200, VerifyIntegrity gives true for a
  matching fingerprint and false for a tampered one.

## Sequence 2 (S1c): identity comes from the certificate
Changes:
- RegisterDatasetVersion, RegisterTransformation, RegisterTrainingRun no longer take an
  `actor` argument. The author is read from `ctx.GetClientIdentity().GetMSPID()`.
  A transaction without a valid client identity is rejected and writes nothing.
- Removed: ownership, token, stake and slash functions, and the OwnerOrg field.
- Kept: VerifyIntegrity, GetDatasetVersionHistory.
- RegisterDatasetVersion now takes 6 arguments:
  datasetID, versionID (the version number), parentVersionID, fingerprint, merkleRoot, timestamp.

Records written under sequence 1 stay on the ledger and still verify. Their `actor` value
was supplied by the caller, so treat it as unverified. Records written from sequence 2
onward carry the MSP from the certificate.

Deploy (upgrade, keeps the channel and ledger):

    bash ~/datadna/chaincode/redeploy_seq2.sh

Check:

    bash ~/datadna/chaincode/smoke_onchain.sh      # backend must be running

Never run `network.sh down`: it destroys the channel and ledger state.

## Restart after a laptop restart
If containers were stopped:

    docker start peer0.org1.example.com peer0.org2.example.com orderer.example.com ca_org1 ca_org2 ca_orderer

## Known limits (planned for S12)
- Any identity of a channel member org can register. Role based checks (who may write what)
  come with the Fabric work in S12.
- The timestamp is supplied by the caller, not by the transaction.
