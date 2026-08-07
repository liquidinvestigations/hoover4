"""Golden tests for the indexing writers' Manticore DML and deterministic row ids.

The DDL has golden tests in test_manticore_sql.py; this is the DML half, which is
where the MVA tuple interpolation lives. A drift here only fails at runtime
against Manticore, so the exact strings are pinned.
"""

import pytest

from tasks.P6_index_data.activities import (
    FILENAME_EXTRACTED_BY,
    FILENAME_PAGE_ID,
    metadata_row_id,
    meta_replace_params,
    meta_replace_sql,
    pages_replace_sql,
    pages_row_id,
    primary_filename,
    repr_manticore_tuple,
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


class TestPagesReplaceSql:
    def test_golden_with_entities(self):
        row = {
            "ner_per": "(11,22)",
            "ner_org": "(33)",
            "ner_loc": "()",
            "ner_misc": "(44)",
        }
        sql = pages_replace_sql("testdata_1_pages", row)
        assert _normalize(sql) == _normalize("""
            REPLACE INTO testdata_1_pages (
                id, collection_dataset, file_hash, extracted_by, page_id, page_text,
                ner_per, ner_org, ner_loc, ner_misc
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                (11,22), (33), (), (44)
            )
        """)

    def test_missing_ner_fields_default_to_empty_mva(self):
        # A segment with no entities interpolates () — the `{row.get(...) or '()'}`
        # behaviour is load-bearing.
        sql = pages_replace_sql("testdata_1_pages", {})
        normalized = _normalize(sql)
        assert "%s, %s, %s, %s, %s, %s, (), (), (), ()" in normalized
        assert "None" not in normalized


def _meta_row(**overrides):
    row = {
        "collection_dataset": "testdata_testfiles",
        "file_hash": "abc123",
        "file_types": "(5)",
        "file_mime_types": "(6,7)",
        "file_extensions": "()",
        "file_paths": "(8,9)",
        "dates": "(-3786825600,1370000000)",
        "email_from": "(11)",
        "email_to": "()",
        "date_min": -3786825600,
        "date_max": 1370000000,
        "file_size_bytes": 1024,
        "struct_flags": 0,
        "primary_filename": "easychair.docx",
    }
    row.update(overrides)
    return row


class TestMetaReplaceSql:
    def test_golden(self):
        sql = meta_replace_sql("testdata_1_meta", _meta_row())
        assert _normalize(sql) == _normalize("""
            REPLACE INTO testdata_1_meta (
                id, collection_dataset, file_hash, date_min, date_max,
                file_size_bytes, struct_flags, primary_filename,
                file_types, file_mime_types, file_extensions, file_paths,
                dates, email_from, email_to
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                (5), (6,7), (), (8,9), (-3786825600,1370000000), (11), ()
            )
        """)

    def test_the_dropped_text_columns_are_gone(self):
        """`filenames` and `metadata_values` no longer exist on the table.

        `metadata_values` was written as "" since the day it was created;
        `filenames` is covered twice over by the filename_index pages row and
        `primary_filename`. Naming either one is a Manticore error, not a no-op.
        """
        sql = meta_replace_sql("testdata_1_meta", _meta_row())
        assert "filenames" not in sql
        assert "metadata_values" not in sql

    def test_params_are_in_column_order(self):
        """The bound parameters and the placeholder list are two halves of one
        statement written in two places. Getting them out of step swaps
        `file_size_bytes` and `struct_flags` — same type, no error, wrong data."""
        row = _meta_row()
        params = meta_replace_params("testdata_testfiles", row)
        assert params == (
            metadata_row_id("testdata_testfiles", "abc123"),
            "testdata_testfiles",
            "abc123",
            -3786825600,
            1370000000,
            1024,
            0,
            "easychair.docx",
        )
        sql = meta_replace_sql("testdata_1_meta", row)
        assert sql.count("%s") == len(params)

    def test_negative_dates_render_verbatim_in_the_mva(self):
        # Pre-1970 documents are the whole reason `dates` is a signed bigint MVA.
        sql = meta_replace_sql("testdata_1_meta", _meta_row(dates="(-3786825600)"))
        assert "(-3786825600)" in sql

    def test_empty_mvas_render_as_empty_tuples(self):
        sql = meta_replace_sql("testdata_1_meta", _meta_row(
            dates="()", email_from="()", email_to="()", file_paths="()"))
        assert "None" not in sql
        assert sql.count("()") >= 4


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
        assert metadata_row_id("testdata_testfiles", "abc123") == 2067464481974511151

    def test_ids_fit_in_63_bits(self):
        for value in ["", "a", "testdata_testfiles|abc123|tika|0", "ünïcode"]:
            assert 0 <= hash_string_to_uint63(value) < 2**63

    def test_ids_distinguish_page_extractor_and_dataset(self):
        base = pages_row_id("testdata_testfiles", "abc123", "tika", 0)
        assert base != pages_row_id("testdata_testfiles", "abc123", "tika", 1)
        assert base != pages_row_id("testdata_testfiles", "abc123", "ocr", 0)
        assert base != pages_row_id("other_emails", "abc123", "tika", 0)
        assert base != metadata_row_id("testdata_testfiles", "abc123")

    def test_no_collisions_over_realistic_keys(self):
        # 24k realistic (dataset, hash, extractor, page) keys must be distinct.
        # With crc32|adler32 this class of check is what failed review (B11).
        seen = set()
        for ds in ("testdata_testfiles", "other_emails"):
            for i in range(2000):
                file_hash = f"{i:064x}"
                for extractor in ("tika", "pdf"):
                    for page_id in range(3):
                        seen.add(pages_row_id(ds, file_hash, extractor, page_id))
        assert len(seen) == 24000
