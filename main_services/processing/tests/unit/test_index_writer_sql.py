"""Golden tests for the indexing writers' Manticore DML and deterministic row ids.

The DDL has golden tests in test_manticore_sql.py; this is the DML half, which is
where the MVA tuple interpolation lives. A drift here only fails at runtime
against Manticore, so the exact strings are pinned.
"""

import pytest

from tasks.P6_index_data.activities import (
    metadata_row_id,
    meta_replace_sql,
    pages_replace_sql,
    pages_row_id,
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


class TestMetaReplaceSql:
    def test_golden(self):
        row = {
            "file_types": "(5)",
            "file_mime_types": "(6,7)",
            "file_extensions": "()",
            "file_paths": "(8,9)",
        }
        sql = meta_replace_sql("testdata_1_meta", row)
        assert _normalize(sql) == _normalize("""
            REPLACE INTO testdata_1_meta (
                id, collection_dataset, file_hash, filenames, metadata_values,
                file_types, file_mime_types, file_extensions, file_paths
            ) VALUES (
                %s, %s, %s, %s, %s,
                (5), (6,7), (), (8,9)
            )
        """)


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
