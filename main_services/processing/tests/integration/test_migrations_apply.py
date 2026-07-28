"""Integration tests: migrations against a fresh collection database.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import re
from pathlib import Path

import pytest

from database.clickhouse import (
    COLLECTION_MIGRATIONS_PATH,
    get_collection_client,
    migrate_collection,
)

pytestmark = pytest.mark.integration

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+[`\"]?(\w+)[`\"]?", re.IGNORECASE
)


def _expected_tables() -> set[str]:
    """Table names declared by the collection migrations, parsed from the SQL files.

    A migration file may create more than one table.
    """
    tables = set()
    for path in sorted(Path(COLLECTION_MIGRATIONS_PATH).glob("*.sql")):
        found = _CREATE_TABLE_RE.findall(path.read_text())
        assert found, f"no CREATE TABLE found in {path.name}"
        tables.update(found)
    return tables


def test_fresh_collection_has_exact_table_set(temp_collection):
    """A migrated collection DB has exactly the migration tables plus schema_versions."""
    expected = _expected_tables()
    assert len(expected) > 20, "migration parsing must find the full table set"
    with get_collection_client(temp_collection) as client:
        actual = {row[0] for row in client.query("SHOW TABLES").result_rows}
    assert actual == expected | {"schema_versions"}


def test_schema_versions_records_every_migration(temp_collection):
    """One schema_versions row per migration file, with matching versions.

    This clickhouse-migrations version records (version, md5, script, created_at)
    and raises on failure instead of recording non-success rows, so the parity of
    versions and files is the "nothing failed, nothing skipped" check.
    """
    files = sorted(Path(COLLECTION_MIGRATIONS_PATH).glob("*.sql"))
    expected_versions = sorted(int(f.name.split("_")[0]) for f in files)
    with get_collection_client(temp_collection) as client:
        rows = client.query("SELECT version FROM schema_versions").result_rows
    assert sorted(row[0] for row in rows) == expected_versions


def test_migrate_twice_applies_nothing_new(temp_collection):
    """Migrate is idempotent: a second run records no additional migrations."""
    with get_collection_client(temp_collection) as client:
        before = client.query("SELECT count() FROM schema_versions").result_rows[0][0]
    migrate_collection(temp_collection)
    with get_collection_client(temp_collection) as client:
        after = client.query("SELECT count() FROM schema_versions").result_rows[0][0]
    assert before == after
