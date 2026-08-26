package main

import (
	"encoding/json"
	"fmt"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

// DataDNAContract provides functions for managing dataset provenance
type DataDNAContract struct {
	contractapi.Contract
}

// DatasetVersion represents an immutable, on-chain record of one dataset version.
// OwnerOrg is the org that currently owns/controls this version (NFT-style ownership) —
// it starts as the registering actor and can change via TransferDatasetOwnership.
type DatasetVersion struct {
	DocType         string `json:"docType"` // "datasetVersion" - used to distinguish record types in the ledger
	DatasetID       string `json:"datasetId"`
	VersionID       string `json:"versionId"`
	ParentVersionID string `json:"parentVersionId"` // empty string if this is V1
	Fingerprint     string `json:"fingerprint"`      // dataset-level SHA-256 fingerprint
	MerkleRoot      string `json:"merkleRoot"`
	Actor           string `json:"actor"`
	Timestamp       string `json:"timestamp"` // RFC3339 string, set by caller (not chaincode) for determinism
	OwnerOrg        string `json:"ownerOrg"`   // current owner of this dataset version (NFT-style ownership)
}

// RegisterDatasetVersion writes a new, immutable dataset version record to the ledger.
// It fails if a version with the same compound key already exists (immutability guarantee).
// The registering actor becomes the initial OwnerOrg.
func (c *DataDNAContract) RegisterDatasetVersion(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
	parentVersionID string,
	fingerprint string,
	merkleRoot string,
	actor string,
	timestamp string,
) error {
	key, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(key)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing != nil {
		return fmt.Errorf("dataset version %s/%s already registered on-chain (immutable)", datasetID, versionID)
	}

	dv := DatasetVersion{
		DocType:         "datasetVersion",
		DatasetID:       datasetID,
		VersionID:       versionID,
		ParentVersionID: parentVersionID,
		Fingerprint:     fingerprint,
		MerkleRoot:      merkleRoot,
		Actor:           actor,
		Timestamp:       timestamp,
		OwnerOrg:        actor, // whoever registers a version is its initial owner
	}

	dvBytes, err := json.Marshal(dv)
	if err != nil {
		return fmt.Errorf("failed to marshal dataset version: %v", err)
	}

	return ctx.GetStub().PutState(key, dvBytes)
}

// TransferDatasetOwnership changes the OwnerOrg of an existing dataset version,
// but only if callerOrg matches the CURRENT recorded owner. This is the core
// NFT-style mechanic: a unique, immutable asset with verifiable, transferable
// ownership. It does not touch Fingerprint, MerkleRoot, or any other field —
// only OwnerOrg changes, so the provenance/integrity guarantees are untouched.
func (c *DataDNAContract) TransferDatasetOwnership(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
	newOwnerOrg string,
	callerOrg string,
) error {
	key, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(key)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return fmt.Errorf("dataset version %s/%s not found on-chain", datasetID, versionID)
	}

	var dv DatasetVersion
	if err := json.Unmarshal(existing, &dv); err != nil {
		return fmt.Errorf("failed to unmarshal dataset version: %v", err)
	}

	if dv.OwnerOrg != callerOrg {
		return fmt.Errorf(
			"transfer rejected: %s is not the current owner of dataset version %s/%s (current owner: %s)",
			callerOrg, datasetID, versionID, dv.OwnerOrg,
		)
	}

	dv.OwnerOrg = newOwnerOrg

	dvBytes, err := json.Marshal(dv)
	if err != nil {
		return fmt.Errorf("failed to marshal dataset version: %v", err)
	}

	return ctx.GetStub().PutState(key, dvBytes)
}

// GetDatasetOwner returns the current OwnerOrg for a given dataset version.
// Read-only query, mirrors the pattern used by VerifyIntegrity.
func (c *DataDNAContract) GetDatasetOwner(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
) (string, error) {
	key, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
	if err != nil {
		return "", fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(key)
	if err != nil {
		return "", fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return "", fmt.Errorf("dataset version %s/%s not found on-chain", datasetID, versionID)
	}

	var dv DatasetVersion
	if err := json.Unmarshal(existing, &dv); err != nil {
		return "", fmt.Errorf("failed to unmarshal dataset version: %v", err)
	}

	return dv.OwnerOrg, nil
}

// Transformation represents an immutable, on-chain record of one transformation
// event that produced a new dataset version from a parent version.
type Transformation struct {
	DocType             string `json:"docType"` // "transformation"
	DatasetID           string `json:"datasetId"`
	FromVersionID       string `json:"fromVersionId"`
	ToVersionID         string `json:"toVersionId"`
	TransformationType  string `json:"transformationType"` // e.g. "remove_duplicates", "normalize"
	Parameters          string `json:"parameters"`          // JSON-encoded params, stored as string (chaincode does not interpret it)
	Actor               string `json:"actor"`
	Timestamp           string `json:"timestamp"`
}

// RegisterTransformation writes a new, immutable transformation record to the ledger.
// It fails if a transformation for the same (datasetId, toVersionId) already exists,
// since each dataset version may only be produced by exactly one transformation.
func (c *DataDNAContract) RegisterTransformation(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	fromVersionID string,
	toVersionID string,
	transformationType string,
	parameters string,
	actor string,
	timestamp string,
) error {
	key, err := ctx.GetStub().CreateCompositeKey("transformation", []string{datasetID, toVersionID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(key)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing != nil {
		return fmt.Errorf("transformation producing %s/%s already registered on-chain (immutable)", datasetID, toVersionID)
	}

	tr := Transformation{
		DocType:            "transformation",
		DatasetID:          datasetID,
		FromVersionID:      fromVersionID,
		ToVersionID:        toVersionID,
		TransformationType: transformationType,
		Parameters:         parameters,
		Actor:              actor,
		Timestamp:          timestamp,
	}

	trBytes, err := json.Marshal(tr)
	if err != nil {
		return fmt.Errorf("failed to marshal transformation: %v", err)
	}

	return ctx.GetStub().PutState(key, trBytes)
}

// TrainingRun represents an immutable, on-chain record linking a training run
// to the dataset version it consumed and the model it produced.
type TrainingRun struct {
	DocType         string `json:"docType"` // "trainingRun"
	TrainingRunID   string `json:"trainingRunId"`
	DatasetID       string `json:"datasetId"`
	VersionID       string `json:"versionId"`
	ModelID         string `json:"modelId"`
	ModelVersion    string `json:"modelVersion"`
	Hyperparameters string `json:"hyperparameters"` // JSON-encoded, stored as string
	Actor           string `json:"actor"`
	Timestamp       string `json:"timestamp"`
}

// RegisterTrainingRun writes a new, immutable training run record to the ledger,
// linking a specific dataset version to a specific model version.
func (c *DataDNAContract) RegisterTrainingRun(
	ctx contractapi.TransactionContextInterface,
	trainingRunID string,
	datasetID string,
	versionID string,
	modelID string,
	modelVersion string,
	hyperparameters string,
	actor string,
	timestamp string,
) error {
	key, err := ctx.GetStub().CreateCompositeKey("trainingRun", []string{trainingRunID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(key)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing != nil {
		return fmt.Errorf("training run %s already registered on-chain (immutable)", trainingRunID)
	}

	tr := TrainingRun{
		DocType:         "trainingRun",
		TrainingRunID:   trainingRunID,
		DatasetID:       datasetID,
		VersionID:       versionID,
		ModelID:         modelID,
		ModelVersion:    modelVersion,
		Hyperparameters: hyperparameters,
		Actor:           actor,
		Timestamp:       timestamp,
	}

	trBytes, err := json.Marshal(tr)
	if err != nil {
		return fmt.Errorf("failed to marshal training run: %v", err)
	}

	return ctx.GetStub().PutState(key, trBytes)
}

// VerifyIntegrity checks whether a given fingerprint matches the fingerprint
// recorded on-chain for a specific dataset version. It returns true if they
// match (data is intact), false if they differ (data was modified/tampered),
// and an error only if the version was never registered on-chain.
func (c *DataDNAContract) VerifyIntegrity(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
	fingerprintToCheck string,
) (bool, error) {
	key, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
	if err != nil {
		return false, fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(key)
	if err != nil {
		return false, fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return false, fmt.Errorf("dataset version %s/%s not found on-chain", datasetID, versionID)
	}

	var dv DatasetVersion
	if err := json.Unmarshal(existing, &dv); err != nil {
		return false, fmt.Errorf("failed to unmarshal dataset version: %v", err)
	}

	return dv.Fingerprint == fingerprintToCheck, nil
}

// DatasetToken represents a mintable, transferable digital asset ("NFT") tied
// to a specific, already-registered dataset version. Unlike DatasetVersion's
// OwnerOrg (which tracks provenance/control of the version itself), a
// DatasetToken is a distinct minted asset with its own ID — the classic NFT
// pattern of a unique token pointing at an underlying asset.
type DatasetToken struct {
	DocType   string `json:"docType"` // "datasetToken" - used to distinguish record types in the ledger
	TokenID   string `json:"tokenId"`
	DatasetID string `json:"datasetId"`
	VersionID string `json:"versionId"`
	Owner     string `json:"owner"` // current owner org of this token
	MintedBy  string `json:"mintedBy"`
	Timestamp string `json:"timestamp"` // RFC3339 string, set by caller for determinism
}

// MintDatasetToken creates a new DatasetToken for an already-registered
// dataset version. It fails if the underlying dataset version does not exist
// on-chain (a token must point at a real asset), or if a token for this
// tokenID has already been minted (mint-once, mirrors the immutability
// guarantee used by RegisterDatasetVersion).
func (c *DataDNAContract) MintDatasetToken(
	ctx contractapi.TransactionContextInterface,
	tokenID string,
	datasetID string,
	versionID string,
	owner string,
	mintedBy string,
	timestamp string,
) error {
	versionKey, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	versionExisting, err := ctx.GetStub().GetState(versionKey)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if versionExisting == nil {
		return fmt.Errorf("cannot mint token: dataset version %s/%s not found on-chain", datasetID, versionID)
	}

	tokenKey, err := ctx.GetStub().CreateCompositeKey("datasetToken", []string{tokenID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	tokenExisting, err := ctx.GetStub().GetState(tokenKey)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if tokenExisting != nil {
		return fmt.Errorf("token %s already minted on-chain (immutable)", tokenID)
	}

	dt := DatasetToken{
		DocType:   "datasetToken",
		TokenID:   tokenID,
		DatasetID: datasetID,
		VersionID: versionID,
		Owner:     owner,
		MintedBy:  mintedBy,
		Timestamp: timestamp,
	}

	dtBytes, err := json.Marshal(dt)
	if err != nil {
		return fmt.Errorf("failed to marshal dataset token: %v", err)
	}

	return ctx.GetStub().PutState(tokenKey, dtBytes)
}

// TransferToken changes the Owner of an existing DatasetToken, but only if
// callerOrg matches the CURRENT recorded owner. Mirrors the guard pattern
// used by TransferDatasetOwnership.
func (c *DataDNAContract) TransferToken(
	ctx contractapi.TransactionContextInterface,
	tokenID string,
	newOwner string,
	callerOrg string,
) error {
	tokenKey, err := ctx.GetStub().CreateCompositeKey("datasetToken", []string{tokenID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(tokenKey)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return fmt.Errorf("token %s not found on-chain", tokenID)
	}

	var dt DatasetToken
	if err := json.Unmarshal(existing, &dt); err != nil {
		return fmt.Errorf("failed to unmarshal dataset token: %v", err)
	}

	if dt.Owner != callerOrg {
		return fmt.Errorf(
			"transfer rejected: %s is not the current owner of token %s (current owner: %s)",
			callerOrg, tokenID, dt.Owner,
		)
	}

	dt.Owner = newOwner

	dtBytes, err := json.Marshal(dt)
	if err != nil {
		return fmt.Errorf("failed to marshal dataset token: %v", err)
	}

	return ctx.GetStub().PutState(tokenKey, dtBytes)
}

// GetTokenOwner returns the current Owner for a given token. Read-only query,
// mirrors the pattern used by GetDatasetOwner.
func (c *DataDNAContract) GetTokenOwner(
	ctx contractapi.TransactionContextInterface,
	tokenID string,
) (string, error) {
	tokenKey, err := ctx.GetStub().CreateCompositeKey("datasetToken", []string{tokenID})
	if err != nil {
		return "", fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(tokenKey)
	if err != nil {
		return "", fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return "", fmt.Errorf("token %s not found on-chain", tokenID)
	}

	var dt DatasetToken
	if err := json.Unmarshal(existing, &dt); err != nil {
		return "", fmt.Errorf("failed to unmarshal dataset token: %v", err)
	}

	return dt.Owner, nil
}

// StakeBalance represents tokens an org has put up as collateral when
// registering a dataset version — the cryptocurrency half of the system.
// If the underlying dataset version is later marked INVALID, this stake
// can be slashed (see SlashStake). One stake record per (dataset version, staker).
type StakeBalance struct {
	DocType   string `json:"docType"` // "stakeBalance" - used to distinguish record types in the ledger
	DatasetID string `json:"datasetId"`
	VersionID string `json:"versionId"`
	StakerOrg string `json:"stakerOrg"`
	Amount    int    `json:"amount"`
	Slashed   bool   `json:"slashed"`
	Timestamp string `json:"timestamp"` // RFC3339 string, set by caller for determinism
}

// StakeTokens records a new stake of `amount` tokens by stakerOrg against an
// already-registered dataset version. It fails if the underlying dataset
// version does not exist on-chain (mirrors MintDatasetToken's guard), if
// amount is not positive, or if this org has already staked on this version
// (mint-once, mirrors the immutability guarantee used elsewhere).
func (c *DataDNAContract) StakeTokens(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
	stakerOrg string,
	amount int,
	timestamp string,
) error {
	if amount <= 0 {
		return fmt.Errorf("stake amount must be positive, got %d", amount)
	}

	versionKey, err := ctx.GetStub().CreateCompositeKey("datasetVersion", []string{datasetID, versionID})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	versionExisting, err := ctx.GetStub().GetState(versionKey)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if versionExisting == nil {
		return fmt.Errorf("cannot stake: dataset version %s/%s not found on-chain", datasetID, versionID)
	}

	stakeKey, err := ctx.GetStub().CreateCompositeKey("stakeBalance", []string{datasetID, versionID, stakerOrg})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	stakeExisting, err := ctx.GetStub().GetState(stakeKey)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if stakeExisting != nil {
		return fmt.Errorf("%s has already staked on dataset version %s/%s", stakerOrg, datasetID, versionID)
	}

	sb := StakeBalance{
		DocType:   "stakeBalance",
		DatasetID: datasetID,
		VersionID: versionID,
		StakerOrg: stakerOrg,
		Amount:    amount,
		Slashed:   false,
		Timestamp: timestamp,
	}

	sbBytes, err := json.Marshal(sb)
	if err != nil {
		return fmt.Errorf("failed to marshal stake balance: %v", err)
	}

	return ctx.GetStub().PutState(stakeKey, sbBytes)
}

// SlashStake penalizes an existing stake by marking it Slashed and zeroing
// its Amount, typically called when a dataset version is found INVALID.
// It fails if no stake exists for this (datasetID, versionID, stakerOrg),
// or if that stake has already been slashed (cannot slash twice).
func (c *DataDNAContract) SlashStake(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
	stakerOrg string,
) error {
	stakeKey, err := ctx.GetStub().CreateCompositeKey("stakeBalance", []string{datasetID, versionID, stakerOrg})
	if err != nil {
		return fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(stakeKey)
	if err != nil {
		return fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return fmt.Errorf("no stake found for %s on dataset version %s/%s", stakerOrg, datasetID, versionID)
	}

	var sb StakeBalance
	if err := json.Unmarshal(existing, &sb); err != nil {
		return fmt.Errorf("failed to unmarshal stake balance: %v", err)
	}

	if sb.Slashed {
		return fmt.Errorf("stake for %s on dataset version %s/%s has already been slashed", stakerOrg, datasetID, versionID)
	}

	sb.Slashed = true
	sb.Amount = 0

	sbBytes, err := json.Marshal(sb)
	if err != nil {
		return fmt.Errorf("failed to marshal stake balance: %v", err)
	}

	return ctx.GetStub().PutState(stakeKey, sbBytes)
}


// GetStakeBalance returns the current StakeBalance for a given
// (datasetID, versionID, stakerOrg). Read-only query, mirrors the pattern
// used by GetTokenOwner and GetDatasetOwner.
func (c *DataDNAContract) GetStakeBalance(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
	versionID string,
	stakerOrg string,
) (*StakeBalance, error) {
	stakeKey, err := ctx.GetStub().CreateCompositeKey("stakeBalance", []string{datasetID, versionID, stakerOrg})
	if err != nil {
		return nil, fmt.Errorf("failed to create composite key: %v", err)
	}

	existing, err := ctx.GetStub().GetState(stakeKey)
	if err != nil {
		return nil, fmt.Errorf("failed to read ledger: %v", err)
	}
	if existing == nil {
		return nil, fmt.Errorf("no stake found for %s on dataset version %s/%s", stakerOrg, datasetID, versionID)
	}

	var sb StakeBalance
	if err := json.Unmarshal(existing, &sb); err != nil {
		return nil, fmt.Errorf("failed to unmarshal stake balance: %v", err)
	}

	return &sb, nil
}

// GetDatasetVersionHistory returns all dataset version records for a given
// datasetID, in the order the ledger's iterator returns them (not guaranteed
// to be chronological -- callers should sort by Timestamp or walk ParentVersionID
// links if strict ordering is required).
func (c *DataDNAContract) GetDatasetVersionHistory(
	ctx contractapi.TransactionContextInterface,
	datasetID string,
) ([]*DatasetVersion, error) {
	iterator, err := ctx.GetStub().GetStateByPartialCompositeKey("datasetVersion", []string{datasetID})
	if err != nil {
		return nil, fmt.Errorf("failed to query ledger: %v", err)
	}
	defer iterator.Close()

	var versions []*DatasetVersion

	for iterator.HasNext() {
		queryResponse, err := iterator.Next()
		if err != nil {
			return nil, fmt.Errorf("failed to iterate results: %v", err)
		}

		var dv DatasetVersion
		if err := json.Unmarshal(queryResponse.Value, &dv); err != nil {
			return nil, fmt.Errorf("failed to unmarshal dataset version: %v", err)
		}

		versions = append(versions, &dv)
	}

	return versions, nil
}