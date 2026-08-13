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

// DatasetVersion represents an immutable, on-chain record of one dataset version
type DatasetVersion struct {
	DocType         string `json:"docType"` // "datasetVersion" - used to distinguish record types in the ledger
	DatasetID       string `json:"datasetId"`
	VersionID       string `json:"versionId"`
	ParentVersionID string `json:"parentVersionId"` // empty string if this is V1
	Fingerprint     string `json:"fingerprint"`      // dataset-level SHA-256 fingerprint
	MerkleRoot      string `json:"merkleRoot"`
	Actor           string `json:"actor"`
	Timestamp       string `json:"timestamp"` // RFC3339 string, set by caller (not chaincode) for determinism
}

// RegisterDatasetVersion writes a new, immutable dataset version record to the ledger.
// It fails if a version with the same compound key already exists (immutability guarantee).
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
	}

	dvBytes, err := json.Marshal(dv)
	if err != nil {
		return fmt.Errorf("failed to marshal dataset version: %v", err)
	}

	return ctx.GetStub().PutState(key, dvBytes)
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
