import sys
import os
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import app.core.db as db_module

# Use a temp DB for tests so we don't pollute the real datadna.db
db_module.DB_PATH = tempfile.mktemp(suffix=".db")

from app.core.db import init_db
from app.core.versioning import create_dataset, create_version, get_lineage

init_db()


def test_create_dataset_returns_id():
    ds_id = create_dataset("Test")
    assert ds_id is not None


def test_first_version_number_is_one():
    ds = create_dataset("DS1")
    v1 = create_version(ds, [{"a": 1}])
    assert v1["version_number"] == 1


def test_child_version_increments():
    ds = create_dataset("DS2")
    v1 = create_version(ds, [{"a": 1}])
    v2 = create_version(ds, [{"a": 2}], parent_version_id=v1["version_id"])
    assert v2["version_number"] == 2


def test_different_data_different_fingerprint():
    ds = create_dataset("DS3")
    v1 = create_version(ds, [{"a": 1}])
    v2 = create_version(ds, [{"a": 2}], parent_version_id=v1["version_id"])
    assert v1["dataset_fingerprint"] != v2["dataset_fingerprint"]


def test_invalid_parent_raises():
    ds = create_dataset("DS4")
    try:
        create_version(ds, [{"a": 1}], parent_version_id="fake-id")
        assert False, "should have raised"
    except ValueError:
        pass


def test_lineage_order():
    ds = create_dataset("DS5")
    v1 = create_version(ds, [{"a": 1}])
    v2 = create_version(ds, [{"a": 2}], parent_version_id=v1["version_id"])
    v3 = create_version(ds, [{"a": 3}], parent_version_id=v2["version_id"])
    lineage = get_lineage(ds)
    assert [v["version_number"] for v in lineage] == [1, 2, 3]
    assert lineage[2]["parent_version_id"] == v2["version_id"]
