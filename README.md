# DataDNA


DataDNA gives every AI training dataset a verifiable digital identity — a cryptographic "DNA" — and tracks it through its entire lifecycle: from raw upload, through every transformation and version, into the models it trains, with tamper-evident proof recorded on a permissioned blockchain.


---

## The problem

AI models are only as trustworthy as the data they're trained on. Today, most organizations can't answer basic questions about their training data:

- Where did this dataset actually come from?
- Has it been modified since ingestion, and by whom?
- Which specific model versions were trained on which dataset versions?
- If a batch of training data turns out to be corrupted, biased, or poisoned — **which deployed models are affected, and what should be done about it?**

DataDNA answers all of these, with cryptographic proof at every step rather than trust-me assertions.

---

## Core flow

```
Upload dataset (CSV/JSON)
        │
        ▼
Canonicalize + fingerprint every record (SHA-256)
        │
        ▼
Merkle root = dataset fingerprint  ──────────►  Registered on Hyperledger Fabric
        │                                              (tamper-evident, 2-org network)
        ▼
AI Audit runs automatically
  (missing values, duplicates, outliers, schema issues)
        │
        ▼
Explainable Trust Score computed
  (Integrity / Quality / Provenance / Anomaly Risk — fully transparent formula)
        │
        ▼
Dataset version linked to Training Runs → Models
        │
        ▼
If a version is later marked INVALID:
  Impact Engine traces every affected training run and model,
  reports severity, and recommends an action (RETRAIN / REBUILD / VERIFY)
```

---

## Why this design

**Why fingerprint at the record level, not just the file level?**
A single-file hash tells you *if* anything changed, not *what*. Record-level fingerprints plus a Merkle root let the system point to exactly which rows changed between versions, while keeping the tree structure cheap to verify.

**Why store only fingerprints on-chain, never raw data?**
Blockchain storage is expensive and public data on a shared ledger is a liability. The chain holds cryptographic proof of what a dataset version *was* at a point in time — not the data itself. Raw values never leave local storage; even the local database stores fingerprints for individual records, not the original values.

**Why Hyperledger Fabric instead of a public chain?**
This is a multi-organization provenance problem (data providers, model trainers, auditors), not a public currency or open-participation problem. Fabric's permissioned model, private channels, and lack of transaction fees fit a supply-chain-style, invitation-only network far better than a public chain like Ethereum would.

**What does the blockchain record prove — and what does it *not* prove?**
It proves a specific fingerprint was registered by a specific organization at a specific time, and that the fingerprint hasn't been altered since. It does **not** prove the original data was accurate, unbiased, or truthful — only that whatever was registered has not been silently tampered with afterward.

**Why is the Trust Score a plain formula instead of a machine-learning model?**
A trust score that judges can't audit is not trustworthy. Every sub-score (Integrity, Quality, Provenance, Anomaly Risk) is computed from raw numbers already stored in the database, with the exact formula and weights disclosed in the API response itself — no black box.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | Python, FastAPI |
| Database | SQLite |
| Data analysis | pandas, NumPy, scikit-learn |
| Cryptography | SHA-256, Merkle trees |
| Blockchain | Hyperledger Fabric v2.5, Go chaincode, 2-org permissioned network |
| Frontend | React, TypeScript, Vite |
| Testing | pytest |

---

## Architecture

```
backend/
├── app/
│   ├── main.py              FastAPI app entrypoint
│   ├── api/                 HTTP route handlers
│   │   ├── datasets.py      upload, versioning, lineage, audit, trust, impact, blockchain
│   │   └── training.py      model + training run registration
│   ├── core/                 core business logic (framework-independent)
│   │   ├── canonicalize.py  deterministic record canonicalization
│   │   ├── fingerprint.py   SHA-256 record hashing + Merkle root
│   │   ├── versioning.py    immutable dataset version chain
│   │   ├── parsing.py       CSV/JSON upload parsing + validation
│   │   ├── audit.py         statistical data quality auditing
│   │   ├── trust.py         explainable trust score calculation
│   │   ├── training.py      model + training run provenance
│   │   ├── impact.py        downstream impact analysis
│   │   └── db.py            SQLite schema + connection handling
│   └── tests/                pytest suite (77 tests)
└── requirements.txt

chaincode/
└── datadna/                  Go chaincode: RegisterDatasetVersion,
                               RegisterTransformation, RegisterTrainingRun,
                               VerifyIntegrity, GetDatasetVersionHistory

frontend/
└── src/
    ├── App.tsx                dashboard UI
    └── App.css
```

---

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs` once running.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard available at `http://localhost:5173`.

### Blockchain (Hyperledger Fabric)

Requires an existing Fabric test-network with the DataDNA chaincode already installed, approved, and committed on a channel. See `chaincode/DEPLOYMENT.md` for full deployment notes.

If the network was previously running and the machine restarted, bring the containers back up (do **not** run `network.sh down`, which destroys ledger state):

```bash
docker start peer0.org1.example.com peer0.org2.example.com orderer.example.com ca_org1 ca_org2 ca_orderer
```

---

## API reference

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/datasets` | Upload a new dataset (creates dataset + Version 1) |
| `POST` | `/datasets/{id}/versions` | Add a new version to an existing dataset |
| `GET` | `/datasets` | List all datasets with summary info |
| `GET` | `/datasets/{id}/lineage` | Full version history for a dataset |
| `GET` | `/datasets/versions/{id}/audit` | AI audit results for a version |
| `GET` | `/datasets/versions/{id}/trust` | Explainable trust score for a version |
| `POST` | `/datasets/versions/{id}/invalidate` | Mark a version as INVALID |
| `GET` | `/datasets/versions/{id}/impact` | Downstream impact analysis |
| `POST` | `/datasets/versions/{id}/register-onchain` | Register version fingerprint on Hyperledger Fabric |
| `GET` | `/datasets/versions/{id}/verify-onchain` | Verify local fingerprint matches the blockchain record |
| `POST` | `/models` | Register a model |
| `GET` | `/models` | List all registered models |
| `POST` | `/training-runs` | Link a dataset version to a model as a training run |
| `GET` | `/models/{id}/training-runs` | All training runs for a model |
| `GET` | `/datasets/versions/{id}/training-runs` | All training runs that used a dataset version |

---

## Testing

```bash
cd backend
python -m pytest app/tests/ -v
```

77 tests covering fingerprinting, canonicalization, versioning, upload parsing, AI auditing, trust score calculation, training/model registration, impact analysis, invalidation, and Fabric client integration — all passing.

---

## Scope notes

Built and prioritized under a hard deadline. The following are intentionally out of scope for this version, in favor of getting the core provenance → trust → impact pipeline fully working and tested:

- Data poisoning detection beyond basic statistical outlier flagging
- Distribution drift analysis across versions
- Formal bias/fairness indicators
- Federated / fully decentralized multi-organization deployment (the underlying Fabric network is genuinely 2-org; the UI demonstrates a single-org view)
- Zero-knowledge proofs for privacy-preserving verification

These are natural extensions once the core pipeline is validated, not fundamental limitations of the architecture.
