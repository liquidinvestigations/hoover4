"""Golden-string tests for the Manticore DDL and DML fragments.

A mis-quoted MVA literal or a drifted column list is otherwise only visible as a
runtime Manticore syntax error; these pin the exact strings.
"""

import pytest

from database.manticore import meta_table_ddl, pages_table_ddl, vectors_table_ddl
from tasks.P6_index_data.activities import (
    metadata_row_id,
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
