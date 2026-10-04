#!/bin/bash
# End-to-end check after the redeploy. The backend must be running (uvicorn on port 8000).
#   bash ~/datadna/chaincode/smoke_onchain.sh
# Steps: upload a tiny CSV, register it on-chain, verify it, then read the ledger record
# and confirm the recorded author is Org1MSP (taken from the certificate, not from the request).
set -e

API="${API_BASE:-http://localhost:8000}"
BACKEND_DIR="${BACKEND_DIR:-$HOME/datadna/backend}"
TMPCSV="$(mktemp --suffix=.csv)"
printf 'a,b\n1,2\n3,4\n' > "$TMPCSV"

call() {  # call METHOD PATH [extra curl args]; prints body; on non-200 prints the error to stderr and returns 1
  local out code body
  out=$(curl -sS -w '\n%{http_code}' -X "$1" "$API$2" "${@:3}") || { echo "FAILED: curl could not reach $API" >&2; return 1; }
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  if [ "$code" != "200" ]; then
    echo "FAILED: HTTP $code on $1 $2" >&2
    echo "$body" >&2
    return 1
  fi
  echo "$body"
}
# Same as call, but retries a few times. The first chaincode query after a deploy can fail
# once while the chaincode container is starting.
call_retry() {
  local n
  for n in 1 2 3 4; do
    if call "$@"; then return 0; fi
    echo "retry $n in 5s..." >&2
    sleep 5
  done
  return 1
}
field() { python3 -c "import sys,json; print(json.load(sys.stdin)['$1'])"; }

echo "--- 1. upload"
UP=$(call POST /datasets -F "name=smoke-$(date +%s)" -F "file=@$TMPCSV;type=text/csv")
echo "$UP"
VID=$(echo "$UP" | field version_id)
DID=$(echo "$UP" | field dataset_id)

echo "--- 2. register on-chain"
call POST "/datasets/versions/$VID/register-onchain"

echo "--- 3. verify on-chain"
VER=$(call_retry GET "/datasets/versions/$VID/verify-onchain") || { echo "SMOKE FAILED: verify call failed"; exit 1; }
echo "$VER"
echo "$VER" | grep -Eq '"verified": ?"true"' || { echo "SMOKE FAILED: verify did not return true"; exit 1; }

echo "--- 4. read ledger record, check author"
cd "$BACKEND_DIR"
REC=$(python3 -c "from app.core.fabric_client import query; print(query('GetDatasetVersionHistory', ['$DID']))")
echo "$REC"
echo "$REC" | grep -Eq '"actor": ?"Org1MSP"' || { echo "SMOKE FAILED: actor is not Org1MSP"; exit 1; }

rm -f "$TMPCSV"
echo "SMOKE OK"
