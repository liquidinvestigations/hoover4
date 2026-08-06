"""Golden-string tests for the Manticore DDL and DML fragments.

A mis-quoted MVA literal or a drifted column list is otherwise only visible as a
runtime Manticore syntax error; these pin the exact strings.
"""

from database.manticore import meta_table_ddl, pages_table_ddl
from tasks.P6_index_data.activities import (
    metadata_row_id,
    pages_row_id,
    repr_manticore_tuple,
)


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


def test_pages_table_ddl_golden():
    assert _normalize(pages_table_ddl("testdata_1_pages")) == _normalize("""
        create table if not exists testdata_1_pages(
            collection_dataset string,
            file_hash string,
            extracted_by string,
            page_id int,
            page_text text,
            ner_per multi64,
            ner_org multi64,
            ner_loc multi64,
            ner_misc multi64
        ) engine='columnar' min_infix_len='3'
    """)


def test_meta_table_ddl_golden():
    assert _normalize(meta_table_ddl("testdata_1_meta")) == _normalize("""
        create table if not exists testdata_1_meta(
            collection_dataset string,
            file_hash string,
            file_types multi64,
            file_mime_types multi64,
            file_extensions multi64,
            file_paths multi64,
            filenames text,
            metadata_values text
        ) engine='columnar' min_infix_len='3'
    """)


def test_repr_manticore_tuple():
    assert repr_manticore_tuple([]) == "()"
    assert repr_manticore_tuple([7]) == "(7)"
    assert repr_manticore_tuple([1, 22, 333]) == "(1,22,333)"


def test_row_ids_are_deterministic_and_distinct():
    # Same input -> same id, across calls. This is what makes REPLACE INTO an
    # overwrite rather than a duplicate.
    assert pages_row_id("testdata_testfiles", "h1", "tika", 1) == \
        pages_row_id("testdata_testfiles", "h1", "tika", 1)
    assert metadata_row_id("testdata_testfiles", "h1") == \
        metadata_row_id("testdata_testfiles", "h1")

    ids = {
        pages_row_id("testdata_testfiles", "h1", "tika", 1),
        pages_row_id("testdata_testfiles", "h1", "tika", 2),   # other page
        pages_row_id("testdata_testfiles", "h1", "pdf", 1),    # other extractor
        pages_row_id("testdata_testfiles", "h2", "tika", 1),   # other document
        pages_row_id("other_testfiles", "h1", "tika", 1),      # other dataset
        metadata_row_id("testdata_testfiles", "h1"),
    }
    assert len(ids) == 6
    # Manticore ids must be positive signed 64-bit integers.
    assert all(0 < i < 2**63 for i in ids)
