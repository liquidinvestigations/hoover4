"""Golden tests for the indexing writers' Manticore DML and deterministic row ids.

The DDL has golden tests in test_manticore_sql.py; this is the DML half, which is
where the MVA tuple interpolation lives. A drift here only fails at runtime
against Manticore, so the exact strings are pinned.
"""

import pytest

from tasks.P6_index_data.activities import (
    FILENAME_EXTRACTED_BY,
    VFS_SCAN_PAGE,
    _scan_indexed_vfs_rows,
    FILENAME_PAGE_ID,
    OPTIMIZE_DISK_CHUNKS,
    OPTIMIZE_KILLED_RATE_PERCENT,
    empty_document_metadata,
    index_vfs_structure,
    pages_replace_params,
    pages_replace_sql,
    pages_row_id,
    primary_filename,
    repr_manticore_tuple,
    should_optimize,
    vfs_delete_ids_sql,
    vfs_replace_sql,
    vfs_scan_page_sql,
    vfs_stale_ids,
)
from tasks.P6_index_data.string_term_encodings import hash_string_to_uint63


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


class TestReprManticoreTuple:
    def test_empty_list_renders_empty_mva(self):
        # The empty MVA is () — never "(,)" and never an omitted column.
        assert repr_manticore_tuple([]) == "()"

    def test_values_render_as_csv_tuple(self):
        assert repr_manticore_tuple([1]) == "(1)"
        assert repr_manticore_tuple([42, 7, 99]) == "(42,7,99)"


def _page_row(**overrides):
    row = {
        "collection_dataset": "testdata_testfiles",
        "file_hash": "abc123",
        "extracted_by": "tika",
        "page_id": 0,
        "page_text": "hello",
        "date_min": -3786825600,
        "date_max": 1370000000,
        "file_size_bytes": 1024,
        "struct_flags": 0,
        "primary_filename": "easychair.docx",
        "mentioned_date_min": -3786825600,
        "mentioned_date_max": 1370000000,
        "ner_per": "(11,22)",
        "ner_org": "(33)",
        "ner_loc": "()",
        "ner_misc": "(44)",
        "file_types": "(5)",
        "file_mime_types": "(6,7)",
        "file_extensions": "()",
        "file_paths": "(8,9)",
        "dates": "(-3786825600,1370000000)",
        "email_from": "(11)",
        "email_to": "()",
        "re_email": "(51)",
        "re_phone": "()",
        "re_bank_account": "()",
        "re_company_id": "()",
        "re_money": "(52,53)",
        "re_crypto_wallet": "()",
        "mentioned_dates": "(-3786825600,1370000000)",
    }
    row.update(overrides)
    return row


class TestPagesReplaceSql:
    def test_golden(self):
        sql = pages_replace_sql("testdata_1_pages", _page_row())
        assert _normalize(sql) == _normalize("""
            REPLACE INTO testdata_1_pages (id, collection_dataset, file_hash,
                extracted_by, page_id, page_text, date_min, date_max, file_size_bytes,
                struct_flags, primary_filename, mentioned_date_min, mentioned_date_max,
                ner_per, ner_org, ner_loc, ner_misc,
                file_types, file_mime_types, file_extensions, file_paths, dates,
                email_from, email_to,
                re_email, re_phone, re_bank_account, re_company_id, re_money,
                re_crypto_wallet, mentioned_dates)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                (11,22), (33), (), (44),
                (5), (6,7), (), (8,9), (-3786825600,1370000000), (11), (),
                (51), (), (), (), (52,53), (), (-3786825600,1370000000))
        """)

    def test_missing_mva_fields_default_to_empty_mva(self):
        # A segment with no entities and a document with no metadata interpolate ()
        # rather than None — the `row.get(...) or '()'` behaviour is load-bearing.
        sql = pages_replace_sql("testdata_1_pages", {})
        assert "None" not in sql
        assert sql.count("()") == 18

    def test_params_are_in_column_order(self):
        """The bound parameters and the placeholder list are two halves of one
        statement written in two places. Getting them out of step swaps
        `file_size_bytes` and `struct_flags`: same type, no error, wrong data."""
        row = _page_row()
        params = pages_replace_params("testdata_testfiles", row)
        assert params == (
            pages_row_id("testdata_testfiles", "abc123", "tika", 0),
            "testdata_testfiles",
            "abc123",
            "tika",
            0,
            "hello",
            -3786825600,
            1370000000,
            1024,
            0,
            "easychair.docx",
            -3786825600,
            1370000000,
        )
        sql = pages_replace_sql("testdata_1_pages", row)
        assert sql.count("%s") == len(params)

    def test_negative_dates_render_verbatim_in_the_mva(self):
        # Pre-1970 documents are the whole reason `dates` is a signed bigint MVA.
        sql = pages_replace_sql("testdata_1_pages", _page_row(dates="(-3786825600)"))
        assert "(-3786825600)" in sql

    def test_the_dropped_text_columns_are_gone(self):
        """`filenames` and `metadata_values` are not columns. `metadata_values` was
        written as "" for as long as it existed; filenames are covered twice over by
        the filename_index row and `primary_filename`. Naming either is a Manticore
        error, not a no-op."""
        sql = pages_replace_sql("testdata_1_pages", _page_row())
        assert "filenames" not in sql
        assert "metadata_values" not in sql


class TestEmptyDocumentMetadata:
    def test_every_column_has_a_value(self):
        # Manticore attributes are not nullable: a missing column is an error, and a
        # wrong default is a document with a date it does not have.
        from database.manticore import DATE_UNKNOWN, DOCUMENT_COLUMNS, SIZE_UNKNOWN

        row = empty_document_metadata()
        for column in DOCUMENT_COLUMNS:
            assert column in row, column
        assert row["date_min"] == DATE_UNKNOWN
        assert row["date_max"] == DATE_UNKNOWN
        assert row["file_size_bytes"] == SIZE_UNKNOWN
        assert row["primary_filename"] == ""
        assert row["file_types"] == "()"

    def test_a_page_of_an_unknown_document_still_renders(self):
        row = dict(empty_document_metadata())
        row.update({
            "collection_dataset": "testdata_testfiles", "file_hash": "h",
            "extracted_by": "tika", "page_id": 3, "page_text": "text",
        })
        sql = pages_replace_sql("testdata_1_pages", row)
        assert "None" not in sql
        assert len(pages_replace_params("testdata_testfiles", row)) == sql.count("%s")


class TestShouldOptimize:
    def test_killed_rate_is_a_percentage_string(self):
        # SHOW TABLE ... STATUS reports `34.22%`. Read as a fraction it is 34, and
        # every table would look like it needs compacting forever.
        assert should_optimize({"killed_rate": "34.22%", "disk_chunks": "0"})
        assert not should_optimize({"killed_rate": "0.50%", "disk_chunks": "0"})

    def test_chunk_count_alone_is_enough(self):
        assert should_optimize({"killed_rate": "0.00%", "disk_chunks": "20"})
        assert not should_optimize({"killed_rate": "0.00%", "disk_chunks": "3"})

    def test_an_unreadable_status_is_not_a_reason_to_compact(self):
        assert not should_optimize({})
        assert not should_optimize({"killed_rate": "-", "disk_chunks": "-"})

    def test_the_thresholds_are_the_measured_ones(self):
        assert OPTIMIZE_KILLED_RATE_PERCENT == 20.0
        assert OPTIMIZE_DISK_CHUNKS == 12


class TestPrimaryFilename:
    def test_first_under_a_case_folded_ordering(self):
        # `alpha.PDF` wins over `Mid.txt` and `Zebra.pdf` because the ORDER ignores case;
        # it comes back spelled the way the filesystem spells it.
        assert primary_filename({"Zebra.pdf", "alpha.PDF", "Mid.txt"}) == "alpha.PDF"

    def test_the_display_name_keeps_its_original_case(self):
        # This is the result-card title and the file-browser link text. `/README` is not
        # called `readme`.
        assert primary_filename({"README"}) == "README"
        assert primary_filename({"IMG_0042.JPG"}) == "IMG_0042.JPG"

    def test_case_only_twins_pick_the_same_name_either_way(self):
        # Two paths, same name, different case: the winner must not depend on set order.
        assert primary_filename({"README", "readme"}) == primary_filename({"readme", "README"})

    def test_nfkc_normalised(self):
        # Composed and decomposed forms of the same name must not sort apart.
        assert primary_filename({"cafe\u0301.pdf"}) == primary_filename({"caf\u00e9.pdf"})

    def test_empty_input_is_empty_not_none(self):
        # It goes into a non-nullable Manticore string attribute.
        assert primary_filename(set()) == ""
        assert primary_filename({""}) == ""


class TestFilenameRowIdentity:
    def test_the_filename_row_has_its_own_reserved_identity(self):
        """`page_id = -1` is what keeps it from colliding with page 0 of a real
        extractor, and `extracted_by` is what every reader excludes on."""
        assert FILENAME_PAGE_ID == -1
        assert FILENAME_EXTRACTED_BY == "filename_index"
        real = pages_row_id("testdata_testfiles", "abc123", "tika", 0)
        synthetic = pages_row_id(
            "testdata_testfiles", "abc123", FILENAME_EXTRACTED_BY, FILENAME_PAGE_ID)
        assert real != synthetic


class TestRowIds:
    """Deterministic Manticore row ids (blake2b-63 since the 2026-07 bugfix round —
    see hash_string_to_uint63's docstring for the required reindex)."""

    def test_golden_ids(self):
        assert pages_row_id("testdata_testfiles", "abc123", "tika", 0) == 1497199510838567760
        assert pages_row_id("testdata_testfiles", "abc123", "tika", 1) == 1608295272350595380

    def test_ids_fit_in_63_bits(self):
        for value in ["", "a", "testdata_testfiles|abc123|tika|0", "ünïcode"]:
            assert 0 <= hash_string_to_uint63(value) < 2**63

    def test_ids_distinguish_page_extractor_and_dataset(self):
        base = pages_row_id("testdata_testfiles", "abc123", "tika", 0)
        assert base != pages_row_id("testdata_testfiles", "abc123", "tika", 1)
        assert base != pages_row_id("testdata_testfiles", "abc123", "ocr", 0)
        assert base != pages_row_id("other_emails", "abc123", "tika", 0)
        assert base != pages_row_id("testdata_testfiles", "abc123", "filename_index", -1)

    def test_no_collisions_over_realistic_keys(self):
        # 24k realistic (dataset, hash, extractor, page) keys must be distinct.
        # A crc32|adler32 composite fails this: the two checksums correlate.
        seen = set()
        for ds in ("testdata_testfiles", "other_emails"):
            for i in range(2000):
                file_hash = f"{i:064x}"
                for extractor in ("tika", "pdf"):
                    for page_id in range(3):
                        seen.add(pages_row_id(ds, file_hash, extractor, page_id))
        assert len(seen) == 24000


def _vfs_row(node_key="k1", ancestors="()", **overrides):
    row = {
        "id": 11,
        "collection_dataset": "testdata_testfiles",
        "container_hash": "",
        "node_key": node_key,
        "parent_key": "p",
        "ancestor_keys": ancestors,
        "name": "inbox",
        "path": "/inbox",
        "kind": 1,
        "file_hash": "",
        "file_size_bytes": 0,
        "depth": 1,
    }
    row.update(overrides)
    return row


class TestVfsReplaceSql:
    def test_one_statement_per_chunk_not_per_node(self):
        sql, params = vfs_replace_sql("testdata_vfs", [
            _vfs_row(id=11, node_key="k1", ancestors="(1,2)"),
            _vfs_row(id=22, node_key="k2", ancestors="()"),
        ])
        assert sql.count("REPLACE INTO") == 1
        assert sql.count("%s") == 22  # 11 bound columns x 2 rows
        assert "(1,2)" in sql
        assert params[0] == 11 and params[11] == 22
        assert "VALUES" in sql and sql.count("), (") == 1

    def test_empty_chunk_is_refused(self):
        with pytest.raises(ValueError):
            vfs_replace_sql("testdata_vfs", [])


class TestVfsReconciliation:
    def test_stale_ids_are_those_missing_from_clickhouse(self):
        indexed = [(11, "keep"), (22, "gone"), (33, "also-gone")]
        assert vfs_stale_ids(indexed, {"keep", "new"}) == [22, 33]

    def test_delete_sql_is_by_id_never_dataset_wide(self):
        sql = vfs_delete_ids_sql("testdata_vfs", [22, 33])
        assert sql == "DELETE FROM testdata_vfs WHERE id IN (22,33)"
        assert "collection_dataset" not in sql

    def test_index_vfs_structure_does_not_wipe_the_dataset(self):
        import inspect
        src = inspect.getsource(index_vfs_structure)
        assert "DELETE FROM {vfs_table} WHERE collection_dataset" not in src
        assert "vfs_delete_ids_sql" in src
        assert "vfs_replace_sql" in src


class TestVfsStaleScan:
    """The stale sweep must see the WHOLE tree.

    Manticore applies an implicit ``LIMIT 20`` to a SELECT with no limit clause,
    and caps any result set at ``max_matches`` (default 1000). A sweep that reads
    an unbounded SELECT therefore inspects twenty arbitrary nodes and silently
    leaves every other removed node in the index.
    """

    def test_page_sql_bounds_the_result_set_it_asks_for(self):
        sql = _normalize(vfs_scan_page_sql("bench_vfs"))
        assert sql == (
            "SELECT id, node_key FROM bench_vfs "
            "WHERE collection_dataset = %s AND id > %s "
            f"ORDER BY id ASC LIMIT {VFS_SCAN_PAGE} OPTION max_matches={VFS_SCAN_PAGE}"
        )

    def test_scan_pages_past_the_first_result_set(self):
        rows = [(i, f"key-{i}") for i in range(1, 2 * VFS_SCAN_PAGE + 7)]

        class Cursor:
            def __init__(self):
                self.page = []
                self.calls = []

            def execute(self, sql, params):
                self.calls.append(params)
                last_id = params[1]
                self.page = [r for r in rows if r[0] > last_id][:VFS_SCAN_PAGE]

            def fetchall(self):
                return self.page

        cursor = Cursor()
        assert _scan_indexed_vfs_rows(cursor, "bench_vfs", "bench_smoke") == rows
        # First page starts at 0, each later page resumes past the highest id seen.
        assert [p[1] for p in cursor.calls] == [0, VFS_SCAN_PAGE, 2 * VFS_SCAN_PAGE]

    def test_a_short_page_ends_the_scan_without_another_round_trip(self):
        class Cursor:
            def __init__(self):
                self.calls = 0

            def execute(self, sql, params):
                self.calls += 1

            def fetchall(self):
                return [(1, "only")]

        cursor = Cursor()
        assert _scan_indexed_vfs_rows(cursor, "bench_vfs", "bench_smoke") == [(1, "only")]
        assert cursor.calls == 1
