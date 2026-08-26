import sys

path = "/home/dhruv/datadna/chaincode/datadna/datadna_contract.go"

marker = "// GetDatasetVersionHistory returns all dataset version records for a given"

new_code = '''// GetStakeBalance returns the current StakeBalance for a given
// (datasetID, versionID, stakerOrg). Read-only query, mirrors the pattern
// used by GetTokenOwner and GetDatasetOwner.
func (c *DataDNAContract) GetStakeBalance(
\tctx contractapi.TransactionContextInterface,
\tdatasetID string,
\tversionID string,
\tstakerOrg string,
) (*StakeBalance, error) {
\tstakeKey, err := ctx.GetStub().CreateCompositeKey("stakeBalance", []string{datasetID, versionID, stakerOrg})
\tif err != nil {
\t\treturn nil, fmt.Errorf("failed to create composite key: %v", err)
\t}

\texisting, err := ctx.GetStub().GetState(stakeKey)
\tif err != nil {
\t\treturn nil, fmt.Errorf("failed to read ledger: %v", err)
\t}
\tif existing == nil {
\t\treturn nil, fmt.Errorf("no stake found for %s on dataset version %s/%s", stakerOrg, datasetID, versionID)
\t}

\tvar sb StakeBalance
\tif err := json.Unmarshal(existing, &sb); err != nil {
\t\treturn nil, fmt.Errorf("failed to unmarshal stake balance: %v", err)
\t}

\treturn &sb, nil
}

'''

with open(path, "r") as f:
    content = f.read()

if marker not in content:
    print("ERROR: marker not found — file may have changed. Aborting, nothing was written.")
    sys.exit(1)

if "func (c *DataDNAContract) GetStakeBalance(" in content:
    print("ERROR: GetStakeBalance already appears in the file — looks like this was already applied. Aborting to avoid a duplicate.")
    sys.exit(1)

content = content.replace(marker, new_code + marker, 1)

with open(path, "w") as f:
    f.write(content)

print("Done: GetStakeBalance function inserted successfully.")
