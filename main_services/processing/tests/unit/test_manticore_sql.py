"""Golden-string tests for the Manticore DDL and DML fragments.

A mis-quoted MVA literal or a drifted column list is otherwise only visible as a
runtime Manticore syntax error; these pin the exact strings.
"""

import pytest

from database.manticore import (
    DATE_UNKNOWN,
    DOCUMENT_COLUMNS,
    SIZE_UNKNOWN,
    pages_table_ddl,
    vectors_table_ddl,
    vfs_table_ddl,
    vfs_table_name,
)
from tasks.P6_index_data.activities import (
    pages_row_id,
    repr_manticore_tuple,
    repr_manticore_vector,
    vectors_row_id,
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
            ner_misc multi64,
            file_types multi64,
            file_mime_types multi64,
            file_extensions multi64,
            file_paths multi64,
            dates multi64,
            date_min bigint,
            date_max bigint,
            file_size_bytes bigint,
            struct_flags bigint,
            primary_filename string,
            email_from multi64,
            email_to multi64,
            re_email multi64,
            re_phone multi64,
            re_bank_account multi64,
            re_company_id multi64,
            re_money multi64,
            re_crypto_wallet multi64,
            mentioned_dates multi64,
            mentioned_date_min bigint,
            mentioned_date_max bigint
        ) engine='columnar' min_infix_len='3'
    """)


def test_the_shard_table_carries_every_document_column():
    """One table per shard, so a document column missing from the DDL is not a JOIN that
    returns nothing. It is a Manticore error on every query that names it."""
    ddl = pages_table_ddl("testdata_1_pages")
    for column in DOCUMENT_COLUMNS:
        assert f"{column} " in ddl, column


def test_page_text_is_the_only_full_text_field():
    """`primary_filename` must be a string ATTRIBUTE. Manticore can ORDER BY an
    attribute and cannot ORDER BY a text field, and the name sort is what needs it.
    Filename MATCHING goes through the `filename_index` row's `page_text` instead."""
    ddl = pages_table_ddl("testdata_1_pages")
    assert ddl.count(" text") == 1
    assert "page_text text" in ddl
    assert "primary_filename string" in ddl


def test_the_shard_table_carries_signed_columns_for_dates_and_sizes():
    """Manticore's own `timestamp` is 32-bit UNSIGNED (1970..2106), useless for a corpus
    with pre-1970 material, so this uses bigint seconds and a multi64 MVA."""
    ddl = pages_table_ddl("testdata_1_pages")
    for signed in ("dates multi64", "date_min bigint", "date_max bigint",
                   "file_size_bytes bigint"):
        assert signed in ddl
    assert "timestamp" not in ddl


def test_the_unknown_sentinels_cannot_collide_with_real_values():
    # i64::MIN, which no real date can be; and -1, which no real size can be (0 is a
    # legitimate size, so it cannot double as "unknown").
    assert DATE_UNKNOWN == -(2 ** 63)
    assert SIZE_UNKNOWN == -1


def test_vfs_table_ddl_golden():
    assert _normalize(vfs_table_ddl("testdata_vfs")) == _normalize("""
        create table if not exists testdata_vfs(
            collection_dataset string,
            container_hash string,
            node_key string,
            parent_key string,
            ancestor_keys multi64,
            name text,
            path string,
            kind int,
            file_hash string,
            file_size_bytes bigint,
            depth int
        ) engine='columnar' min_infix_len='3'
    """)


def test_the_vfs_table_is_named_so_the_shard_regex_cannot_match_it():
    """It is one table per COLLECTION, not per shard. Everything that iterates shards,
    the ledger equality check in verify-stack, the per-shard search fan-out. Must not
    see it, and the shard regex requires a numeric segment."""
    import re

    from database.manticore import _SHARD_TABLE_RE_TEMPLATE

    name = vfs_table_name("testdata")
    assert name == "testdata_vfs"
    pattern = re.compile(_SHARD_TABLE_RE_TEMPLATE.format(coll="testdata"))
    assert not pattern.match(name)


def test_the_vfs_name_is_infix_indexed_because_that_is_what_folder_search_matches():
    ddl = vfs_table_ddl("testdata_vfs")
    assert "name text" in ddl
    assert "min_infix_len='3'" in ddl


def test_repr_manticore_tuple():
    assert repr_manticore_tuple([]) == "()"
    assert repr_manticore_tuple([7]) == "(7)"
    assert repr_manticore_tuple([1, 22, 333]) == "(1,22,333)"


def test_row_ids_are_deterministic_and_distinct():
    # Same input -> same id, across calls. This is what makes REPLACE INTO an
    # overwrite rather than a duplicate.
    assert pages_row_id("testdata_testfiles", "h1", "tika", 1) == \
        pages_row_id("testdata_testfiles", "h1", "tika", 1)

    ids = {
        pages_row_id("testdata_testfiles", "h1", "tika", 1),
        pages_row_id("testdata_testfiles", "h1", "tika", 2),   # other page
        pages_row_id("testdata_testfiles", "h1", "pdf", 1),    # other extractor
        pages_row_id("testdata_testfiles", "h2", "tika", 1),   # other document
        pages_row_id("other_testfiles", "h1", "tika", 1),      # other dataset
    }
    assert len(ids) == 5
    # Manticore ids must be positive signed 64-bit integers.
    assert all(0 < i < 2**63 for i in ids)


def test_vectors_table_ddl_golden():
    assert _normalize(vectors_table_ddl("testdata_1_vectors", 384)) == _normalize("""
        create table if not exists testdata_1_vectors(
            collection_dataset string,
            file_hash string,
            extracted_by string,
            page_id int,
            chunk_index int,
            embedding float_vector knn_type='hnsw' knn_dims='384' hnsw_similarity='COSINE'
        )
    """)


def test_vectors_table_ddl_validates_dims():
    # knn_dims cannot be altered after creation; a bad value must fail here, not as a
    # Manticore syntax error at plan time.
    for bad in (0, -1, 70000, 1.5, True, "384"):
        with pytest.raises(ValueError):
            vectors_table_ddl("testdata_1_vectors", bad)


def test_repr_manticore_vector():
    assert repr_manticore_vector([0.1, 0.2]) == "(0.1,0.2)"
    assert repr_manticore_vector([1, -2]) == "(1.0,-2.0)"  # floats stay floats


def test_vectors_row_id_is_deterministic_and_model_scoped():
    assert vectors_row_id("ds", "h1", "tika", 1, 0, "e5-small") == \
        vectors_row_id("ds", "h1", "tika", 1, 0, "e5-small")
    ids = {
        vectors_row_id("ds", "h1", "tika", 1, 0, "e5-small"),
        vectors_row_id("ds", "h1", "tika", 1, 1, "e5-small"),   # other chunk
        vectors_row_id("ds", "h1", "tika", 1, 0, "e5-large"),   # other model: must NOT collide
        vectors_row_id("ds", "h1", "ocr_tesseract_eng", 1, 0, "e5-small"),  # other variant
    }
    assert len(ids) == 4
    assert all(0 < i < 2**63 for i in ids)
