import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import tempfile
import pytest
import app.core.db as db_module
db_module.DB_PATH = tempfile.mktemp(suffix=".db")
db_module.init_db()
from app.core.versioning import create_dataset, create_version, invalidate_version


def _make_version():
    dataset_id = create_dataset("InvalidateTestSet")
    result = create_version(dataset_id, [{"name": "Alice", "age": "30"}])
    return result["version_id"]


def test_invalidate_sets_status_invalid():
    version_id = _make_version()
    result = invalidate_version(version_id)
    assert result["version_id"] == version_id
    assert result["integrity_status"] == "INVALID"


def test_invalidate_returns_previous_status():
    version_id = _make_version()
    result = invalidate_version(version_id)
    assert result["previous_status"] == "VERIFIED"


def test_invalidate_persists_to_db():
    version_id = _make_version()
    invalidate_version(version_id)
    conn = db_module.get_connection()
    row = conn.execute(
        "SELECT integrity_status FROM dataset_versions WHERE version_id = ?",
        (version_id,),
    ).fetchone()
    conn.close()
    assert row["integrity_status"] == "INVALID"


def test_invalidate_nonexistent_version_raises():
    with pytest.raises(ValueError, match="not found"):
        invalidate_version("nonexistent-id")


def test_invalidate_twice_is_idempotent():
    version_id = _make_version()
    invalidate_version(version_id)
    result = invalidate_version(version_id)
    assert result["previous_status"] == "INVALID"
    assert result["integrity_status"] == "INVALID"
