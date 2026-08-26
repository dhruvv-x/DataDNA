import sys

path = "/home/dhruv/datadna/chaincode/datadna/datadna_contract.go"

marker = "func (c *DataDNAContract) StakeTokens("

new_code_after_func_marker = '''

// SlashStake penalizes an existing stake by marking it Slashed and zeroing
// its Amount, typically called when a dataset version is found INVALID.
// It fails if no stake exists for this (datasetID, versionID, stakerOrg),
// or if that stake has already been slashed (cannot slash twice).
func (c *DataDNAContract) SlashStake(
\tctx contractapi.TransactionContextInterface,
\tdatasetID string,
\tversionID string,
\tstakerOrg string,
) error {
\tstakeKey, err := ctx.GetStub().CreateCompositeKey("stakeBalance", []string{datasetID, versionID, stakerOrg})
\tif err != nil {
\t\treturn fmt.Errorf("failed to create composite key: %v", err)
\t}

\texisting, err := ctx.GetStub().GetState(stakeKey)
\tif err != nil {
\t\treturn fmt.Errorf("failed to read ledger: %v", err)
\t}
\tif existing == nil {
\t\treturn fmt.Errorf("no stake found for %s on dataset version %s/%s", stakerOrg, datasetID, versionID)
\t}

\tvar sb StakeBalance
\tif err := json.Unmarshal(existing, &sb); err != nil {
\t\treturn fmt.Errorf("failed to unmarshal stake balance: %v", err)
\t}

\tif sb.Slashed {
\t\treturn fmt.Errorf("stake for %s on dataset version %s/%s has already been slashed", stakerOrg, datasetID, versionID)
\t}

\tsb.Slashed = true
\tsb.Amount = 0

\tsbBytes, err := json.Marshal(sb)
\tif err != nil {
\t\treturn fmt.Errorf("failed to marshal stake balance: %v", err)
\t}

\treturn ctx.GetStub().PutState(stakeKey, sbBytes)
}
'''

with open(path, "r") as f:
    content = f.read()

if content.count(marker) != 1:
    print(f"ERROR: expected exactly 1 occurrence of StakeTokens function marker, found {content.count(marker)}. Aborting, nothing was written.")
    sys.exit(1)

if "func (c *DataDNAContract) SlashStake(" in content:
    print("ERROR: SlashStake already appears in the file — looks like this was already applied. Aborting to avoid a duplicate.")
    sys.exit(1)

# Find the end of the StakeTokens function by locating its closing brace
# (the first line that is exactly "}" after the marker).
start = content.index(marker)
end_marker = "\n}\n"
end = content.index(end_marker, start) + len(end_marker) - 1  # position right after the closing "}"

content = content[:end] + new_code_after_func_marker + content[end:]

with open(path, "w") as f:
    f.write(content)

print("Done: SlashStake function inserted successfully.")
