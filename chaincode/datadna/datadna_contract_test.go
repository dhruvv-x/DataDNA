package main

import (
	"crypto/x509"
	"encoding/json"
	"fmt"
	"reflect"
	"testing"

	"datadna/mocks"

	"github.com/hyperledger/fabric-chaincode-go/v2/pkg/cid"
	"github.com/hyperledger/fabric-chaincode-go/v2/shim"
	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
	"github.com/hyperledger/fabric-protos-go-apiv2/ledger/queryresult"
	"github.com/stretchr/testify/require"
)

// fakeIdentity is a minimal cid.ClientIdentity for tests.
type fakeIdentity struct {
	msp    string
	mspErr error
}

func (f fakeIdentity) GetID() (string, error)    { return "fake-id", nil }
func (f fakeIdentity) GetMSPID() (string, error) { return f.msp, f.mspErr }
func (f fakeIdentity) GetAttributeValue(attrName string) (string, bool, error) {
	return "", false, nil
}
func (f fakeIdentity) AssertAttributeValue(attrName, attrValue string) error { return nil }
func (f fakeIdentity) GetX509Certificate() (*x509.Certificate, error)        { return nil, nil }

var _ cid.ClientIdentity = fakeIdentity{}

// newMockContextWith builds a mock context whose caller identity is `identity`
// (nil means "no identity available").
func newMockContextWith(identity cid.ClientIdentity) (*mocks.TransactionContext, *mocks.ChaincodeStub) {
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
	ctx.GetClientIdentityReturns(identity)

	return ctx, stub
}

// newMockContext is the default: caller is a valid Org1MSP member.
func newMockContext() (*mocks.TransactionContext, *mocks.ChaincodeStub) {
	return newMockContextWith(fakeIdentity{msp: "Org1MSP"})
}

// --- RegisterDatasetVersion ---

func TestRegisterDatasetVersion_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "2026-08-13T18:00:00Z",
	)

	require.NoError(t, err, "first registration should succeed")
}

func TestRegisterDatasetVersion_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err1 := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "2026-08-13T18:00:00Z",
	)
	require.NoError(t, err1, "first registration should succeed")

	err2 := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-DIFFERENT", "merkleroot-DIFFERENT", "2026-08-13T19:00:00Z",
	)
	require.Error(t, err2, "duplicate registration must be rejected (immutability)")
}

func TestRegisterDatasetVersion_ActorComesFromCallerMSP(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(fakeIdentity{msp: "Org2MSP"})

	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fp-v1", "root-v1", "2026-08-13T18:00:00Z",
	))

	stub.GetStateByPartialCompositeKeyStub = func(objType string, attrs []string) (shim.StateQueryIteratorInterface, error) {
		return newMockIterator(stub, objType, attrs), nil
	}
	versions, err := contract.GetDatasetVersionHistory(ctx, "cropdisease")
	require.NoError(t, err)
	require.Len(t, versions, 1)
	require.Equal(t, "Org2MSP", versions[0].Actor, "actor must be the MSP from the certificate")
}

func TestRegisterDatasetVersion_DifferentOrgsGetTheirOwnActor(t *testing.T) {
	contract := &DataDNAContract{}
	ctx1, stub1 := newMockContextWith(fakeIdentity{msp: "Org1MSP"})
	require.NoError(t, contract.RegisterDatasetVersion(ctx1, "ds", "1", "", "fp1", "", "t1"))

	var stored DatasetVersion
	_, raw := stub1.PutStateArgsForCall(0)
	require.NoError(t, json.Unmarshal(raw, &stored))
	require.Equal(t, "Org1MSP", stored.Actor)

	ctx2, stub2 := newMockContextWith(fakeIdentity{msp: "Org2MSP"})
	require.NoError(t, contract.RegisterDatasetVersion(ctx2, "ds", "1", "", "fp1", "", "t1"))
	_, raw2 := stub2.PutStateArgsForCall(0)
	require.NoError(t, json.Unmarshal(raw2, &stored))
	require.Equal(t, "Org2MSP", stored.Actor)
}

func TestRegisterDatasetVersion_NoIdentityRejectedAndNothingWritten(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(nil)

	err := contract.RegisterDatasetVersion(ctx, "ds", "1", "", "fp", "", "t")
	require.Error(t, err, "a write without a client identity must be rejected")
	require.Equal(t, 0, stub.PutStateCallCount(), "nothing may be written")
}

func TestRegisterDatasetVersion_EmptyMSPRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(fakeIdentity{msp: ""})

	err := contract.RegisterDatasetVersion(ctx, "ds", "1", "", "fp", "", "t")
	require.Error(t, err)
	require.Equal(t, 0, stub.PutStateCallCount())
}

func TestRegisterDatasetVersion_MSPLookupErrorRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(fakeIdentity{mspErr: fmt.Errorf("bad certificate")})

	err := contract.RegisterDatasetVersion(ctx, "ds", "1", "", "fp", "", "t")
	require.Error(t, err)
	require.Contains(t, err.Error(), "bad certificate")
	require.Equal(t, 0, stub.PutStateCallCount())
}

// --- RegisterTransformation ---

func TestRegisterTransformation_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterTransformation(
		ctx, "cropdisease", "v1", "v2", "remove_duplicates", `{"threshold":0.95}`, "2026-08-13T18:30:00Z",
	)

	require.NoError(t, err, "transformation registration should succeed")
}

func TestRegisterTransformation_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err1 := contract.RegisterTransformation(
		ctx, "cropdisease", "v1", "v2", "remove_duplicates", `{"threshold":0.95}`, "2026-08-13T18:30:00Z",
	)
	require.NoError(t, err1)

	err2 := contract.RegisterTransformation(
		ctx, "cropdisease", "v1", "v2", "normalize", `{}`, "2026-08-13T19:00:00Z",
	)
	require.Error(t, err2, "duplicate transformation for the same target version must be rejected")
}

func TestRegisterTransformation_ActorComesFromCallerMSP(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(fakeIdentity{msp: "Org2MSP"})

	require.NoError(t, contract.RegisterTransformation(ctx, "ds", "1", "2", "normalize", "{}", "t"))

	var stored Transformation
	_, raw := stub.PutStateArgsForCall(0)
	require.NoError(t, json.Unmarshal(raw, &stored))
	require.Equal(t, "Org2MSP", stored.Actor)
}

func TestRegisterTransformation_NoIdentityRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(nil)

	require.Error(t, contract.RegisterTransformation(ctx, "ds", "1", "2", "normalize", "{}", "t"))
	require.Equal(t, 0, stub.PutStateCallCount())
}

// --- RegisterTrainingRun ---

func TestRegisterTrainingRun_Success(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterTrainingRun(
		ctx, "run-12", "cropdisease", "v3", "model-cropnet", "v4", `{"epochs":50,"lr":0.001}`, "2026-08-13T20:00:00Z",
	)

	require.NoError(t, err, "training run registration should succeed")
}

func TestRegisterTrainingRun_DuplicateRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err1 := contract.RegisterTrainingRun(
		ctx, "run-12", "cropdisease", "v3", "model-cropnet", "v4", `{"epochs":50}`, "2026-08-13T20:00:00Z",
	)
	require.NoError(t, err1)

	err2 := contract.RegisterTrainingRun(
		ctx, "run-12", "cropdisease", "v3", "model-cropnet", "v5", `{"epochs":100}`, "2026-08-13T21:00:00Z",
	)
	require.Error(t, err2, "duplicate training run ID must be rejected")
}

func TestRegisterTrainingRun_ActorComesFromCallerMSP(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(fakeIdentity{msp: "Org2MSP"})

	require.NoError(t, contract.RegisterTrainingRun(ctx, "run-1", "ds", "1", "m", "1", "{}", "t"))

	var stored TrainingRun
	_, raw := stub.PutStateArgsForCall(0)
	require.NoError(t, json.Unmarshal(raw, &stored))
	require.Equal(t, "Org2MSP", stored.Actor)
}

func TestRegisterTrainingRun_NoIdentityRejected(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContextWith(nil)

	require.Error(t, contract.RegisterTrainingRun(ctx, "run-1", "ds", "1", "m", "1", "{}", "t"))
	require.Equal(t, 0, stub.PutStateCallCount())
}

// --- VerifyIntegrity (read-only, needs no identity) ---

func TestVerifyIntegrity_Match(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, _ := newMockContext()

	err := contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "2026-08-13T18:00:00Z",
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
		ctx, "cropdisease", "v1", "", "fingerprint-abc123", "merkleroot-xyz789", "2026-08-13T18:00:00Z",
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

func TestVerifyIntegrity_WorksWithoutIdentity(t *testing.T) {
	contract := &DataDNAContract{}
	writeCtx, _ := newMockContext()
	require.NoError(t, contract.RegisterDatasetVersion(writeCtx, "ds", "1", "", "fp", "", "t"))

	// Same ledger is not shared between mock contexts, so verify on the same one
	// but with the identity removed.
	writeCtx.GetClientIdentityReturns(nil)
	ok, err := contract.VerifyIntegrity(writeCtx, "ds", "1", "fp")
	require.NoError(t, err)
	require.True(t, ok)
}

// --- GetDatasetVersionHistory ---

func TestGetDatasetVersionHistory_ReturnsAllVersions(t *testing.T) {
	contract := &DataDNAContract{}
	ctx, stub := newMockContext()

	// Register 3 versions of the same dataset
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v1", "", "fp-v1", "root-v1", "2026-08-13T18:00:00Z",
	))
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v2", "v1", "fp-v2", "root-v2", "2026-08-13T18:10:00Z",
	))
	require.NoError(t, contract.RegisterDatasetVersion(
		ctx, "cropdisease", "v3", "v2", "fp-v3", "root-v3", "2026-08-13T18:20:00Z",
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

// --- the contract must load the way the peer loads it ---

func TestContractLoadsAsChaincode(t *testing.T) {
	cc, err := contractapi.NewChaincode(&DataDNAContract{})
	require.NoError(t, err, "contract signatures must be valid for the Fabric contract API")
	require.NotNil(t, cc)
}

// --- removed features must stay removed ---

func TestDeadFeaturesAreGone(t *testing.T) {
	var c interface{} = &DataDNAContract{}
	for _, name := range []string{
		"TransferDatasetOwnership", "GetDatasetOwner", "MintDatasetToken",
		"TransferToken", "GetTokenOwner", "StakeTokens", "SlashStake", "GetStakeBalance",
	} {
		found := reflect.ValueOf(c).MethodByName(name).IsValid()
		require.False(t, found, "%s must not exist any more", name)
	}
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
