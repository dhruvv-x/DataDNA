#!/bin/bash
# S4 cleanup: removes the old unprotected sqlite DataDNA code. Run from ~/datadna AFTER unzipping.
set -e
cd "$(dirname "$0")"
git tag -f pre-s4-datadna >/dev/null 2>&1 && echo "Safety tag pre-s4-datadna set (go back with: git checkout pre-s4-datadna)" || echo "NOTE: no git tag made (is this a git repo?)"
cd backend
rm -v -f app/api/datasets.py app/api/training.py \
  app/core/db.py app/core/ingest.py app/core/parsing.py app/core/audit.py app/core/training.py \
  app/core/versioning.py app/core/impact.py app/core/trust.py app/core/canonicalize.py cleanup_datasets.py \
  app/tests/test_audit.py app/tests/test_datasets_api.py app/tests/test_impact.py app/tests/test_invalidate.py \
  app/tests/test_parsing.py app/tests/test_s1a_lineage_impact_register.py app/tests/test_s1b_parsing_audit_atomic.py \
  app/tests/test_s1c_chaincode_cleanup.py app/tests/test_training.py app/tests/test_trust.py \
  app/tests/test_versioning.py app/tests/test_fingerprint.py
mkdir -p ~/datadna_old_sqlite
mv -v *.db ~/datadna_old_sqlite/ 2>/dev/null || echo "(no old .db files to move)"
find . -name __pycache__ -type d -prune -exec rm -rf {} +
echo "Cleanup done."
