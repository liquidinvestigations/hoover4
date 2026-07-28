"""Schema parity checks over the two migration directories.

The single most likely mistake in the database split is a table landing in the wrong
directory, which no test elsewhere would catch: the migration would apply cleanly and
the table would simply never be found by the code that reads it.
"""

import re
from pathlib import Path

import pytest

from database.clickhouse import COLLECTION_MIGRATIONS_PATH, GLOBAL_MIGRATIONS_PATH

CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_]+)", re.IGNORECASE
)
DROP_TABLE_RE = re.compile(
    r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_]+)", re.IGNORECASE
)
ALTER_TABLE_RE = re.compile(r"ALTER\s+TABLE", re.IGNORECASE)

#: Highest migration number that existed when each directory was collapsed into its
#: current form. Files at or below these numbers are *history*: the runner records an
#: md5 per applied migration, so editing one breaks every existing deployment. A schema
#: change from here on is a NEW numbered file — which, for adding a column to a table
#: that already exists, has to be an ALTER. See `test_alter_table_only_in_new_files`.
COLLAPSED_BASELINE = {
    "db_global_migrations": 10,
    "db_collection_migrations": 30,
}

EXPECTED_GLOBAL_TABLES = {
    "api_events",
    "chat_messages",
    "chat_sessions",
    "collection_group_permissions",
    "collections",
    "dataset",
    "processing_eta_samples",
    "search_manticore_cache",
    "server_settings",
    "usage_events",
    "temp_chat_json_objects",
    "user_group_membership",
    "user_groups",
    "users",
    "web_sessions",
}

EXPECTED_COLLECTION_TABLES = {
    "archives",
    "audio_metadata",
    "blob_values",
    "blobs",
    "email_headers",
    "emails",
    "entity_hit",
    "entity_hits_milvus",
    "entity_hits_milvus_unique",
    "file_types",
    "image",
    "index_state",
    "manticore_shard_assignments",
    "manticore_shards",
    "nlp_processed",
    "pdf_metadata",
    "pdf_to_html_cache",
    "pdfs",
    "pdfs_image",
    "processing_errors",
    "processing_plan_finished",
    "processing_plan_hits",
    "processing_plans",
    "raw_ocr_results",
    "string_term_id_to_text",
    "string_term_text_to_id",
    "text_chunks_milvus",
    "text_content",
    "tika_metadata",
    "vfs_directories",
    "vfs_files",
    "video_metadata",
}


def _sql_files(path: str) -> list[Path]:
    files = sorted(Path(path).glob("*.sql"))
    assert files, f"no migrations found in {path}"
    return files


def _table_names(path: str) -> list[str]:
    names: list[str] = []
    for f in _sql_files(path):
        names.extend(CREATE_TABLE_RE.findall(f.read_text()))
    return names


def _dropped_table_names(path: str) -> set[str]:
    names: set[str] = set()
    for f in _sql_files(path):
        names.update(DROP_TABLE_RE.findall(f.read_text()))
    return names


@pytest.mark.parametrize(
    "path", [GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH]
)
def test_alter_table_only_in_new_files(path):
    """An ALTER inside a collapsed migration means someone edited history.

    The collapsed files (see `COLLAPSED_BASELINE`) describe the schema as one set of
    CREATE TABLEs and must never change — the runner stores an md5 per applied
    migration, so an edit fails on every deployment that already ran it. A *new*
    numbered file adding a column to an existing table has no choice but to use ALTER,
    and that is allowed.
    """
    baseline = COLLAPSED_BASELINE[Path(path).name]
    for f in _sql_files(path):
        if not ALTER_TABLE_RE.search(f.read_text()):
            continue
        number = int(f.name.split("_", 1)[0])
        assert number > baseline, (
            f"{f.name} contains ALTER TABLE but is part of the collapsed baseline "
            f"(<= {baseline:05d}); collapsed migrations must stay CREATE-only"
        )


@pytest.mark.parametrize(
    "path", [GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH]
)
def test_table_names_unique_within_directory(path):
    names = _table_names(path)
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate CREATE TABLE in {path}: {sorted(duplicates)}"


@pytest.mark.parametrize(
    "path", [GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH]
)
def test_migrations_are_numbered_contiguously_from_one(path):
    numbers = [int(f.name.split("_", 1)[0]) for f in _sql_files(path)]
    assert numbers == list(range(1, len(numbers) + 1)), f"gap in numbering in {path}"


@pytest.mark.parametrize(
    "path", [GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH]
)
def test_no_semicolon_inside_string_literals(path):
    """`multi_statement=True` splits files on `;` without parsing SQL, so a semicolon
    inside a COMMENT string cuts the statement in half and the migration fails with an
    unclosed-quote syntax error."""
    for f in _sql_files(path):
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            for literal in re.findall(r"'([^']*)'", line):
                assert ";" not in literal, (
                    f"{f.name}:{lineno} has a ';' inside a string literal: {literal!r}"
                )


@pytest.mark.parametrize(
    "path", [GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH]
)
def test_no_semicolon_inside_line_comments(path):
    """Same splitter hazard as above, on the other side of the syntax.

    `multi_statement=True` splits on `;` without parsing SQL, so it does not know a
    `--` comment from executable text. A semicolon in a comment cuts the file there and
    the leading fragment — comment only — reaches ClickHouse as `Code: 62, Empty query`,
    which names neither the file nor the comment. Caught for real writing 00031.
    """
    for f in _sql_files(path):
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            comment = line.split("--", 1)
            if len(comment) == 2:
                assert ";" not in comment[1], (
                    f"{f.name}:{lineno} has a ';' inside a comment: {comment[1].strip()!r}"
                )


def test_global_tables_match_expected():
    assert set(_table_names(GLOBAL_MIGRATIONS_PATH)) == EXPECTED_GLOBAL_TABLES


def test_collection_tables_match_expected():
    assert set(_table_names(COLLECTION_MIGRATIONS_PATH)) == EXPECTED_COLLECTION_TABLES


#: Tables a collapsed migration creates and a later migration drops again. They stay in
#: EXPECTED_COLLECTION_TABLES above — the CREATEs are history and cannot be edited out —
#: so this is the set that says "expected to be absent from a migrated database".
DROPPED_COLLECTION_TABLES = {
    "text_chunks_milvus",
    "entity_hits_milvus",
    "entity_hits_milvus_unique",
}


def test_milvus_tables_are_dropped_by_a_later_migration():
    """The Milvus alignment tables must not survive a fresh migration run.

    00023/00024 still CREATE them and always will: editing an applied migration changes
    its md5 and breaks every existing deployment. The removal is therefore a DROP in a
    later file, and this test is what ties the two halves together — without it, deleting
    the DROP migration would leave `test_collection_tables_match_expected` perfectly
    happy and the dead tables silently back.
    """
    dropped = _dropped_table_names(COLLECTION_MIGRATIONS_PATH)
    missing = DROPPED_COLLECTION_TABLES - dropped
    assert not missing, f"created but never dropped: {sorted(missing)}"


def test_the_two_sets_are_disjoint():
    overlap = set(_table_names(GLOBAL_MIGRATIONS_PATH)) & set(
        _table_names(COLLECTION_MIGRATIONS_PATH)
    )
    assert not overlap, f"table declared in both directories: {sorted(overlap)}"


def test_readiness_sentinel_matches_last_collection_migration():
    """The website reports a collection "ready" once one sentinel table exists, chosen as
    the table the last *table-creating* collection migration creates. Appending a
    migration without updating that sentinel would make the admin UI report ready too
    early.

    "Last table-creating file" rather than plain "last file": a DROP-only migration
    (00031 removes the Milvus tables) is a legitimate way to end the sequence and creates
    nothing. Anchoring on the literal last file would fail on it, and the obvious "fix" —
    making the sentinel point at something 00031 touches — would be wrong, because
    readiness means "the schema is fully built", which is still decided by the last
    CREATE. A migration that only drops tables must not make every collection report
    un-ready.

    The sentinel name is checked in next to the migrations (READINESS_SENTINEL) so this
    test does not depend on the website sources being mounted — the old version read
    collections.rs and could never run inside the worker image. The Rust side reads its
    own checked-in copy (website/backend/src/db_auth/READINESS_SENTINEL) and a host-side
    cargo test keeps the two copies in sync."""
    sentinel_file = Path(COLLECTION_MIGRATIONS_PATH) / "READINESS_SENTINEL"
    sentinel = sentinel_file.read_text().strip()
    assert sentinel, "READINESS_SENTINEL must not be empty"

    creating = [
        f for f in _sql_files(COLLECTION_MIGRATIONS_PATH)
        if CREATE_TABLE_RE.search(f.read_text())
    ]
    assert creating, "no collection migration creates a table"
    last_file = creating[-1]
    assert sentinel in CREATE_TABLE_RE.findall(last_file.read_text()), (
        f"READINESS_SENTINEL points at {sentinel!r}, but the last table-creating "
        f"migration ({last_file.name}) does not create it"
    )


def test_collection_datasets_table_is_gone():
    """Deleted by the split: the mapping is a column on `dataset` now (D1)."""
    all_tables = set(_table_names(GLOBAL_MIGRATIONS_PATH)) | set(
        _table_names(COLLECTION_MIGRATIONS_PATH)
    )
    assert "collection_datasets" not in all_tables
