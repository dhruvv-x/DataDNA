package main

import (
	"log"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

func main() {
	chaincode, err := contractapi.NewChaincode(&DataDNAContract{})
	if err != nil {
		log.Panicf("Error creating datadna chaincode: %v", err)
	}

	if err := chaincode.Start(); err != nil {
		log.Panicf("Error starting datadna chaincode: %v", err)
	}
}
