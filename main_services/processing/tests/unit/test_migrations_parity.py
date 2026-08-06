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
    "db_global_migrations": 20,
    "db_collection_migrations": 31,
}

EXPECTED_GLOBAL_TABLES = {
    "api_events",
    "chat_message_stream",
    "chat_messages",
    "chat_sessions",
    "collection_group_permissions",
    "collections",
    "dataset",
    "dataset_jobs",
    "dataset_settings",
    "llm_call_events",
    "llm_models",
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
    "file_types",
    "image",
    "index_state",
    "manticore_shard_assignments",
    "manticore_shards",
    "nlp_processed",
    "pdf_metadata",
    "pdf_ocr_results",
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
    "text_chunk_vectors",
    "text_chunks",
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


@pytest.mark.parametrize(
    "path", [GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH]
)
def test_no_comment_only_statement_fragment(path):
    """A trailing comment after the last `;` is its own fragment, and it is empty SQL.

    Third variant of the same splitter hazard, and the one the other two do not catch:
    the file contains no stray semicolon at all, it just has prose *after* the final
    statement terminator. ClickHouse answers `Code: 62, Empty query`, naming neither the
    file nor the comment, and the failure surfaces only when a collection database is
    created — long after the unit tests were green.

    Caught for real when the re-collapse removed 00031's backfill INSERT and left the
    paragraph explaining the removal below the CREATE. Put explanatory comments ABOVE
    the statement they describe.
    """
    for f in _sql_files(path):
        for index, fragment in enumerate(f.read_text().split(";")):
            if not fragment.strip():
                continue
            executable = "\n".join(
                line for line in fragment.splitlines()
                if not line.strip().startswith("--")
            ).strip()
            assert executable, (
                f"{f.name}: statement fragment {index} is comments only, which reaches "
                f"ClickHouse as an empty query. Move it above the preceding statement."
            )


def test_global_tables_match_expected():
    assert set(_table_names(GLOBAL_MIGRATIONS_PATH)) == EXPECTED_GLOBAL_TABLES


def test_collection_tables_match_expected():
    assert set(_table_names(COLLECTION_MIGRATIONS_PATH)) == EXPECTED_COLLECTION_TABLES


#: Tables that must not reappear. The Milvus alignment trio was created by
#: 00023/00024 and dropped again by 00031 until the re-collapse removed all three files:
#: nothing ever wrote them, and the Milvus tier that would have read them is gone. The
#: vector store that replaced them is `text_chunk_vectors` in ClickHouse plus a
#: disposable Manticore HNSW copy.
FORBIDDEN_TABLES = {
    "text_chunks_milvus",
    "entity_hits_milvus",
    "entity_hits_milvus_unique",
    "collection_datasets",
}


def test_no_migration_recreates_a_removed_table():
    """Guards the re-collapse against a revert that reintroduces dead schema.

    Without this, restoring one of the deleted Milvus migrations would only fail
    `test_collection_tables_match_expected` with a diff that reads like a missing entry
    in the expected set — an inviting thing to "fix" by adding it back.
    """
    all_tables = set(_table_names(GLOBAL_MIGRATIONS_PATH)) | set(
        _table_names(COLLECTION_MIGRATIONS_PATH)
    )
    back = FORBIDDEN_TABLES & all_tables
    assert not back, f"deliberately removed table is back: {sorted(back)}"


def test_no_migration_drops_a_table():
    """After the re-collapse there is no create-then-drop pair left in either directory.

    A DROP in a collapsed tree means someone edited history halfway: the CREATE it undoes
    should have been deleted instead. A genuinely new migration above the baseline may
    still drop a table — hence the baseline check rather than a flat ban.
    """
    for path in (GLOBAL_MIGRATIONS_PATH, COLLECTION_MIGRATIONS_PATH):
        baseline = COLLAPSED_BASELINE[Path(path).name]
        for f in _sql_files(path):
            if not DROP_TABLE_RE.search(f.read_text()):
                continue
            number = int(f.name.split("_", 1)[0])
            assert number > baseline, (
                f"{f.name} drops a table but is part of the collapsed baseline "
                f"(<= {baseline:05d}); a collapsed tree never creates what it drops"
            )


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

    "Last table-creating file" rather than plain "last file": a migration that only drops
    or backfills is a legitimate way to end the sequence and creates nothing, and
    anchoring on the literal last file would fail on it. Readiness means "the schema is
    fully built", which is decided by the last CREATE. The collapsed tree has no such
    trailing file today — `index_state` is both the last CREATE and the last file — but
    the distinction is what keeps the next one from making every collection report
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


def test_new_part2_tables_are_in_the_right_directory():
    """The Part 2 tables split across both directories, which is the exact mistake this
    module exists to catch.

    Per-dataset settings and job status are global — the admin UI edits them before the
    collection database is necessarily built, and workers read them across collections.
    Chunks, vectors and derived-PDF records are per collection because they are corpus
    data. Getting either backwards produces a migration that applies cleanly and a table
    the reading code never finds.
    """
    global_tables = set(_table_names(GLOBAL_MIGRATIONS_PATH))
    collection_tables = set(_table_names(COLLECTION_MIGRATIONS_PATH))

    for name in ("dataset_settings", "dataset_jobs", "chat_message_stream",
                 "llm_models", "llm_call_events"):
        assert name in global_tables, f"{name} must be a global table"

    for name in ("text_chunks", "text_chunk_vectors", "pdf_ocr_results"):
        assert name in collection_tables, f"{name} must be a collection table"
