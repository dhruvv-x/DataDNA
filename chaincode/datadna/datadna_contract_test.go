package main

import (
	"testing"

	"datadna/mocks"

	"github.com/hyperledger/fabric-chaincode-go/v2/shim"
	"github.com/hyperledger/fabric-protos-go-apiv2/ledger/queryresult"
	"github.com/stretchr/testify/require"
)

func newMockContext() (*mocks.TransactionContext, *mocks.ChaincodeStub) {
	stub := &mocks.ChaincodeStub{}
	ledger := map[string][]byte{}

	stub.CreateCompositeKeyStub = func(objType string, attrs []string) (string, error) {
		key := objType
		for _, a := range attrs {
			key += "~" + a
		}
		return key, nil
	}

	stub.PutStateStub = func(key string, value []byte) error {
		ledger[key] = value
		return nil
	}

	stub.GetStateStub = func(key string) ([]byte, error) {
		return ledger[key], nil
	}

	ctx := &mocks.TransactionContext{}
	ctx.GetStubReturns(stub)

	return ctx, stub
}

func TestRegisterDatasetVersion_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterDatasetVersion(
		ctx,
		"cropdisease",
		"v1",
		"",
		"fingerprint-abc123",
		"merkleroot-xyz789",
		"dhruv",
		"2026-08-13T18:00:00Z",
	)

	require.NoError(t, err, "first registration should succeed")
}

func TestRegisterDatasetVersion_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err1 := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "dhruv", "2026-08-13T18:00:00Z",
	)
	require.NoError(t, err1, "first registration should succeed")

	err2 := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-DIFFERENT", "merkleroot-DIFFERENT", "attacker", "2026-08-13T19:00:00Z",
	)
	require.Error(t, err2, "duplicate registration must be rejected (immutability)")
}

func TestRegisterTransformation_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterTransformation(
		ctx,
		"cropdisease",
		"v1",
		"v2",
		"remove_duplicates",
		`{"threshold":0.95}`,
		"dhruv",
		"2026-08-13T18:30:00Z",
	)

	require.NoError(t, err, "transformation registration should succeed")
}

func TestRegisterTransformation_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err1 := contract.RegisterTransformation(
		ctx, "cropdisease", "v1", "v2", "remove_duplicates", `{"threshold":0.95}`, "dhruv", "2026-08-13T18:30:00Z",
	)
	require.NoError(t, err1)

	err2 := contract.RegisterTransformation(
		ctx, "cropdisease", "v1", "v2", "normalize", `{}`, "attacker", "2026-08-13T19:00:00Z",
	)
	require.Error(t, err2, "duplicate transformation for the same target version must be rejected")
}

func TestRegisterTrainingRun_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterTrainingRun(
		ctx,
		"run-12",
		"cropdisease",
		"v3",
		"model-cropnet",
		"v4",
		`{"epochs":50,"lr":0.001}`,
		"dhruv",
		"2026-08-13T20:00:00Z",
	)

	require.NoError(t, err, "training run registration should succeed")
}

func TestRegisterTrainingRun_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err1 := contract.RegisterTrainingRun(
		ctx, "run-12", "cropdisease", "v3", "model-cropnet", "v4", `{"epochs":50}`, "dhruv", "2026-08-13T20:00:00Z",
	)
	require.NoError(t, err1)

	err2 := contract.RegisterTrainingRun(
		ctx, "run-12", "cropdisease", "v3", "model-cropnet", "v5", `{"epochs":100}`, "attacker", "2026-08-13T21:00:00Z",
	)
	require.Error(t, err2, "duplicate training run ID must be rejected")
}

func TestVerifyIntegrity_Match(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "dhruv", "2026-08-13T18:00:00Z",
	)
	require.NoError(t, err)

	ok, err := contract.VerifyIntegrity(ctx, "cropdisease", "v1", "fingerprint-abc123")
	require.NoError(t, err)
	require.True(t, ok, "matching fingerprint should verify as intact")
}

func TestVerifyIntegrity_Mismatch(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "dhruv", "2026-08-13T18:00:00Z",
	)
	require.NoError(t, err)

	ok, err := contract.VerifyIntegrity(ctx, "cropdisease", "v1", "fingerprint-TAMPERED")
	require.NoError(t, err, "mismatch is not an error, just a false result")
	require.False(t, ok, "tampered fingerprint should NOT verify as intact")
}

func TestVerifyIntegrity_NotFound(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	_, err := contract.VerifyIntegrity(ctx, "cropdisease", "v99", "anything")
	require.Error(t, err, "verifying a non-existent version must return an error")
}

func TestGetDatasetVersionHistory_ReturnsAllVersions(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContext()

	// Register 3 versions of the same dataset
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fp-v1", "root-v1", "dhruv", "2026-08-13T18:00:00Z",
	))
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v2", "v1", "fp-v2", "root-v2", "dhruv", "2026-08-13T18:10:00Z",
	))
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v3", "v2", "fp-v3", "root-v3", "dhruv", "2026-08-13T18:20:00Z",
	))

	// Wire GetStateByPartialCompositeKey to scan the same in-memory ledger
	// used by PutStateStub/GetStateStub inside newMockContext.
	stub.GetStateByPartialCompositeKeyStub = func(objType string, attrs []string) (shim.StateQueryIteratorInterface, error) {
		return newMockIterator(stub, objType, attrs), nil
	}

	versions, err := contract.GetDatasetVersionHistory(ctx, "cropdisease")
	require.NoError(t, err)
	require.Len(t, versions, 3, "should return all 3 registered versions")
}

func TestGetDatasetVersionHistory_EmptyForUnknownDataset(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContext()

	stub.GetStateByPartialCompositeKeyStub = func(objType string, attrs []string) (shim.StateQueryIteratorInterface, error) {
		return newMockIterator(stub, objType, attrs), nil
	}

	versions, err := contract.GetDatasetVersionHistory(ctx, "nonexistent")
	require.NoError(t, err)
	require.Len(t, versions, 0, "unknown dataset should return empty list, not an error")
}

// newMockIterator builds a mocks.StateQueryIterator backed by a static snapshot
// of matching keys/values from the given stub's ledger, filtered by composite-key prefix.
func newMockIterator(stub *mocks.ChaincodeStub, objType string, attrs []string) *mocks.StateQueryIterator {
	prefix := objType
	for _, a := range attrs {
		prefix += "~" + a
	}

	type kv struct {
		key   string
		value []byte
	}
	var matches []kv

	// Re-derive the ledger contents via GetStateStub's closure is not possible directly,
	// so instead we recover matches by calling PutStateArgsForCall history.
	for i := 0; i < stub.PutStateCallCount(); i++ {
		key, value := stub.PutStateArgsForCall(i)
		if len(key) >= len(prefix) && key[:len(prefix)] == prefix {
			matches = append(matches, kv{key: key, value: value})
		}
	}

	iter := &mocks.StateQueryIterator{}
	idx := 0

	iter.HasNextStub = func() bool {
		return idx < len(matches)
	}
	iter.NextStub = func() (*queryresult.KV, error) {
		m := matches[idx]
		idx++
		return &queryresult.KV{Key: m.key, Value: m.value}, nil
	}
	iter.CloseStub = func() error {
		return nil
	}

	return iter
}
