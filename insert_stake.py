import sys

path = "/home/dhruv/datadna/chaincode/datadna/datadna_contract.go"

marker = "// GetDatasetVersionHistory returns all dataset version records for a given"

new_code = '''// StakeBalance represents tokens an org has put up as collateral when
// registering a dataset version — the cryptocurrency half of the system.
// If the underlying dataset version is later marked INVALID, this stake
// can be slashed (see SlashStake). One stake record per (dataset version, staker).
type StakeBalance struct {
\tDocType   string `json:"docType"` // "stakeBalance" - used to distinguish record types in the ledger
\tDatasetID string `json:"datasetId"`
\tVersionID string `json:"versionId"`
\tStakerOrg string `json:"stakerOrg"`
\tAmount    int    `json:"amount"`
\tSlashed   bool   `json:"slashed"`
\tTimestamp string `json:"timestamp"` // RFC3339 string, set by caller for determinism
}

// StakeTokens records a new stake of `amount` tokens by stakerOrg against an
// already-registered dataset version. It fails if the underlying dataset
// version does not exist on-chain (mirrors MintDatasetToken's guard), if
// amount is not positive, or if this org has already staked on this version
// (mint-once, mirrors the immutability guarantee used elsewhere).
func (c *DataDNAContract) StakeTokens(
\tctx contractapi.TransactionContextInterface,
\tdatasetID string,
\tversionID string,
\tstakerOrg string,
\tamount int,
\ttimestamp string,
) error {
\tif amount <= 0 {
\t\treturn fmt.Errorf("stake amount must be positive, got %d", amount)
\t}

\tversionKey, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
\tif err != nil {
\t\treturn fmt.Errorf("failed to create composite key: %v", err)
\t}

\tversionExisting, err := ctx.GetStub().GetState(versionKey)
\tif err != nil {
\t\treturn fmt.Errorf("failed to read ledger: %v", err)
\t}
\tif versionExisting == nil {
\t\treturn fmt.Errorf("cannot stake: dataset version %s/%s not found on-chain", datasetID, versionID)
\t}

\tstakeKey, err := ctx.GetStub().CreateCompositeKey("stakeBalance", []string{datasetID, versionID, stakerOrg})
\tif err != nil {
\t\treturn fmt.Errorf("failed to create composite key: %v", err)
\t}

\tstakeExisting, err := ctx.GetStub().GetState(stakeKey)
\tif err != nil {
\t\treturn fmt.Errorf("failed to read ledger: %v", err)
\t}
\tif stakeExisting != nil {
\t\treturn fmt.Errorf("%s has already staked on dataset version %s/%s", stakerOrg, datasetID, versionID)
\t}

\tsb := StakeBalance{
\t\tDocType:   "stakeBalance",
\t\tDatasetID: datasetID,
\t\tVersionID: versionID,
\t\tStakerOrg: stakerOrg,
\t\tAmount:    amount,
\t\tSlashed:   false,
\t\tTimestamp: timestamp,
\t}

\tsbBytes, err := json.Marshal(sb)
\tif err != nil {
\t\treturn fmt.Errorf("failed to marshal stake balance: %v", err)
\t}

\treturn ctx.GetStub().PutState(stakeKey, sbBytes)
}

'''

with open(path, "r") as f:
    content = f.read()

if marker not in content:
    print("ERROR: marker not found — file may have changed. Aborting, nothing was written.")
    sys.exit(1)

if "StakeBalance struct" in content:
    print("ERROR: StakeBalance already appears in the file — looks like this was already applied. Aborting to avoid a duplicate.")
    sys.exit(1)

content = content.replace(marker, new_code + marker, 1)

with open(path, "w") as f:
    f.write(content)

print("Done: StakeBalance struct and StakeTokens function inserted successfully.")
