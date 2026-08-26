import sys

path = "/home/dhruv/datadna/chaincode/datadna/datadna_contract_test.go"

new_tests = '''
func TestStakeTokens_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "Org1MSP", "2026-08-13T18:00:00Z",
	))
	err := contract.StakeTokens(ctx, "cropdisease", "v1", "Org1MSP", 100, "2026-08-13T18:05:00Z")
	require.NoError(t, err, "staking against an existing dataset version should succeed")
	sb, err := contract.GetStakeBalance(ctx, "cropdisease", "v1", "Org1MSP")
	require.NoError(t, err)
	require.Equal(t, 100, sb.Amount, "stake amount should match what was staked")
	require.False(t, sb.Slashed, "a fresh stake should not be slashed")
}

func TestStakeTokens_RejectedIfVersionMissing(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	err := contract.StakeTokens(ctx, "cropdisease", "v99", "Org1MSP", 100, "2026-08-13T18:05:00Z")
	require.Error(t, err, "staking against a non-existent dataset version must be rejected")
}

func TestStakeTokens_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "Org1MSP", "2026-08-13T18:00:00Z",
	))
	err1 := contract.StakeTokens(ctx, "cropdisease", "v1", "Org1MSP", 100, "2026-08-13T18:05:00Z")
	require.NoError(t, err1)
	err2 := contract.StakeTokens(ctx, "cropdisease", "v1", "Org1MSP", 50, "2026-08-13T19:00:00Z")
	require.Error(t, err2, "staking twice by the same org on the same version must be rejected")
}

func TestSlashStake_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "Org1MSP", "2026-08-13T18:00:00Z",
	))
	require.NoError(t, contract.StakeTokens(ctx, "cropdisease", "v1", "Org1MSP", 100, "2026-08-13T18:05:00Z"))
	err := contract.SlashStake(ctx, "cropdisease", "v1", "Org1MSP")
	require.NoError(t, err, "slashing an existing, unslashed stake should succeed")
	sb, getErr := contract.GetStakeBalance(ctx, "cropdisease", "v1", "Org1MSP")
	require.NoError(t, getErr)
	require.True(t, sb.Slashed, "stake should be marked Slashed after SlashStake")
	require.Equal(t, 0, sb.Amount, "stake amount should be zeroed after slashing")
}

func TestSlashStake_RejectedIfAlreadySlashed(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "Org1MSP", "2026-08-13T18:00:00Z",
	))
	require.NoError(t, contract.StakeTokens(ctx, "cropdisease", "v1", "Org1MSP", 100, "2026-08-13T18:05:00Z"))
	require.NoError(t, contract.SlashStake(ctx, "cropdisease", "v1", "Org1MSP"))
	err := contract.SlashStake(ctx, "cropdisease", "v1", "Org1MSP")
	require.Error(t, err, "slashing an already-slashed stake must be rejected (cannot slash twice)")
}

func TestSlashStake_RejectedIfNotFound(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	err := contract.SlashStake(ctx, "cropdisease", "v1", "Org1MSP")
	require.Error(t, err, "slashing a stake that does not exist must be rejected")
}

func TestGetStakeBalance_NotFound(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()
	_, err := contract.GetStakeBalance(ctx, "cropdisease", "v1", "Org1MSP")
	require.Error(t, err, "querying a stake balance that does not exist must return an error")
}
'''

with open(path, "r") as f:
    content = f.read()

if "func TestStakeTokens_Success" in content:
    print("ERROR: TestStakeTokens_Success already appears in the file — looks like this was already applied. Aborting to avoid a duplicate.")
    sys.exit(1)

content = content.rstrip("\n") + "\n" + new_tests

with open(path, "w") as f:
    f.write(content)

print("Done: 7 new stake/slash tests appended successfully.")
