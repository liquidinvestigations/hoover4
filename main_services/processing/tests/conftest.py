"""Pytest configuration for the processing test suite.

Layout:

- ``tests/unit/``. Pure-function tests; must pass with no services running
  (``uv run pytest tests/unit -q`` on a bare laptop).
- ``tests/integration/``. Tests against the live docker stack; marked
  ``integration`` and skipped unless ``--integration`` (or
  ``HOOVER4_INTEGRATION=1``) is given. Run them inside the worker container:
  ``docker exec -it hoover4-worker uv run pytest tests --integration -q``.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TINY_DATASET_PATH = Path(__file__).resolve().parent / "fixtures" / "tiny"


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run integration tests (requires the docker stack)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires the docker stack (skipped unless --integration "
        "or HOOVER4_INTEGRATION=1)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration") or os.environ.get("HOOVER4_INTEGRATION"):
        return
    skip = pytest.mark.skip(
        reason="integration test: pass --integration (or HOOVER4_INTEGRATION=1) "
        "with the docker stack up"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def tiny_dataset() -> Path:
    """Path to the checked-in ~6-file fixture dataset."""
    assert TINY_DATASET_PATH.is_dir(), f"missing fixture dataset: {TINY_DATASET_PATH}"
    return TINY_DATASET_PATH


@pytest.fixture
def temp_collection():
    """A throwaway collection: registry row plus a migrated database.

    Yields the collectionname; on teardown drops the Manticore shard tables,
    the ClickHouse database and the global registry rows. Never touches
    ``testdata`` or any other real collection.
    """
    from database.clickhouse import (
        drop_collection_db,
        get_global_client,
        migrate_collection,
        validate_collectionname,
    )
    from database.manticore import drop_collection_tables

    # 'x' after the '_', never all digits: a '_<digits>' tail would be rejected by
    # validate_collectionname (shard-name collision) and an all-digit hex suffix
    # makes that ~2.3% likely per draw. ('-' is not an option: collection names
    # are [a-z0-9_] only, because Manticore table names are unquoted identifiers.)
    collectionname = f"test_x{uuid.uuid4().hex[:7]}"
    try:
        # Validate before writing anything: a rejected name must not leave an
        # orphan registry row behind.
        validate_collectionname(collectionname)
        with get_global_client() as client:
            client.command(
                "INSERT INTO collections (collectionname, fullname) "
                "VALUES ({name:String}, {fullname:String})",
                parameters={"name": collectionname, "fullname": f"temp {collectionname}"},
            )
        migrate_collection(collectionname)
        yield collectionname
    finally:
        try:
            drop_collection_tables(collectionname)
        except Exception as e:
            print(f"teardown: drop_collection_tables failed: {e}")
        try:
            drop_collection_db(collectionname)
        except Exception as e:
            print(f"teardown: drop_collection_db failed: {e}")
        with get_global_client() as client:
            client.command(
                "DELETE FROM dataset WHERE collectionname = {name:String}",
                parameters={"name": collectionname},
            )
            client.command(
                "DELETE FROM collections WHERE collectionname = {name:String}",
                parameters={"name": collectionname},
            )
