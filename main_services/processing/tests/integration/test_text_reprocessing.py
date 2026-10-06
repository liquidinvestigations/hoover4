"""Verify source replacement against a test-owned ClickHouse and Manticore collection."""

import pytest
import pyarrow as pa

from database.clickhouse import get_collection_client, insert_arrow_durable
from database.manticore import create_shard_tables, get_manticore_client
from tasks.P3_parse_files import parse_pdf
from tasks.P3_parse_files.document_dates import (
    ResolveDocumentDatesParams, resolve_document_dates,
)
from tasks.P3_parse_files.parse_common import insert_text_chunks, insert_text_pages
from tasks.P6_index_data import activities
from tasks.P6_index_data.activities import index_text_pages
from tasks.P6_index_data.params import IndexShardParams, PlanShardsParams
from tasks.P6_index_data.shard_planner import plan_shards


pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]


def test_index_planner_flushes_pending_stage_rows(temp_collection):
    collection = temp_collection
    dataset = f"{collection}_barrier"
    with get_collection_client(collection) as client:
        insert_arrow_durable(client, "nlp_processed", pa.table({
            "collection_dataset": pa.array([dataset]),
            "file_hash": pa.array(["barrier-file"]),
            "extracted_by": pa.array(["raw_text"]),
            "page_id": pa.array([1], type=pa.uint32()),
            "nlp_model": pa.array(["barrier-model"]),
            "text_bytes": pa.array([12], type=pa.uint64()),
        }))
        insert_arrow_durable(client, "document_dates", pa.table({
            "collection_dataset": pa.array([dataset]),
            "hash": pa.array(["barrier-file"]),
            "date": pa.array([1], type=pa.int64()),
            "source": pa.array(["barrier"]),
        }))

    assignments = plan_shards(PlanShardsParams(collection, dataset, "probe", ["barrier-file"]))
    assert len(assignments) == 1
    with get_collection_client(collection) as client:
        assert client.query(
            "SELECT count() FROM nlp_processed WHERE collection_dataset = {ds:String}",
            parameters={"ds": dataset},
        ).result_rows == [(1,)]
        assert client.query(
            "SELECT count() FROM document_dates WHERE collection_dataset = {ds:String}",
            parameters={"ds": dataset},
        ).result_rows == [(1,)]


def test_reprocessing_replaces_only_successful_source_pages(temp_collection, monkeypatch):
    collection = temp_collection
    dataset = f"{collection}_reprocessing"
    file_hash = "reprocessing-fixture"
    other_hash = "unrelated-fixture"
    shard = f"{collection}_1"
    table = create_shard_tables(collection, 1)
    metadata = activities.empty_document_metadata()
    metadata["basenames"] = ["reprocessing.txt"]
    other_metadata = activities.empty_document_metadata()
    other_metadata["basenames"] = ["unrelated.txt"]
    monkeypatch.setattr(activities, "document_metadata", lambda _params: {
        file_hash: metadata, other_hash: other_metadata,
    })
    params = IndexShardParams(collection, dataset, "probe", shard, [file_hash, other_hash])

    def write(source, pages, hash=file_hash):
        insert_text_pages(collection, dataset, hash, source, pages)

    def stored(source):
        with get_collection_client(collection) as client:
            return client.query(
                "SELECT page_id, text FROM text_content FINAL "
                "WHERE collection_dataset = {ds:String} AND file_hash = {fh:String} "
                "AND extracted_by = {source:String} ORDER BY page_id",
                parameters={"ds": dataset, "fh": file_hash, "source": source},
            ).result_rows

    def indexed(source):
        with get_manticore_client() as client:
            cursor = client.cursor()
            cursor.execute(
                f"SELECT page_id, page_text FROM {table} "
                "WHERE collection_dataset = %s AND file_hash = %s AND extracted_by = %s "
                "LIMIT 100 OPTION max_matches=100",
                (dataset, file_hash, source),
            )
            return sorted(cursor.fetchall())

    def check(source, expected):
        assert [(int(page), text) for page, text in stored(source)] == expected
        assert [(int(page), text) for page, text in indexed(source)] == expected

    def matches(term):
        with get_manticore_client() as client:
            cursor = client.cursor()
            cursor.execute(
                f"SELECT file_hash, extracted_by FROM {table} "
                "WHERE collection_dataset = %s AND MATCH(%s) "
                "LIMIT 100 OPTION max_matches=100",
                (dataset, term),
            )
            return cursor.fetchall()

    write("pdftotext", [(1, "oldalpha"), (2, "oldbeta"), (3, "oldgamma")])
    write("extractous", [(1, "independent source")])
    write("pdftotext", [(1, "untouchedword")], other_hash)
    assert resolve_document_dates(ResolveDocumentDatesParams(collection, dataset, "probe")) == (
        "0 dates (empty plan)"
    )
    assert stored("pdftotext") == [(1, "oldalpha"), (2, "oldbeta"), (3, "oldgamma")]
    assert stored("extractous") == [(1, "independent source")]
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("pdftotext", [(1, "oldalpha"), (2, "oldbeta"), (3, "oldgamma")])
    assert matches("oldbeta") == [(file_hash, "pdftotext")]

    write("pdftotext", [])
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("pdftotext", [])
    check("extractous", [(1, "independent source")])
    assert matches("oldbeta") == []
    assert matches("untouchedword") == [(other_hash, "pdftotext")]

    write("pdftotext", [(1, "newalpha"), (2, "newbeta"), (3, "newgamma")])
    resolve_document_dates(ResolveDocumentDatesParams(collection, dataset, "probe"))
    assert stored("pdftotext") == [(1, "newalpha"), (2, "newbeta"), (3, "newgamma")]
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    write("pdftotext", [(1, "shortalpha")])
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("pdftotext", [(1, "shortalpha")])
    assert matches("newbeta") == []

    write("pdftotext", [(1, "firstpage"), (2, "middlepage"), (3, "lastpage")])
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    write("pdftotext", [(1, "firstagain"), (2, ""), (3, "lastagain")])
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("pdftotext", [(1, "firstagain"), (3, "lastagain")])
    assert matches("middlepage") == []

    monkeypatch.setattr(parse_pdf, "_maybe_pdftotext", lambda _path: None)
    failed_pages = parse_pdf._pdftotext_pages("unreadable.pdf")
    assert failed_pages == []
    assert parse_pdf._insert_pdf_text_pages(collection, dataset, file_hash, failed_pages) == 0
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("pdftotext", [(1, "firstagain"), (3, "lastagain")])
    check("extractous", [(1, "independent source")])
    assert matches("untouchedword") == [(other_hash, "pdftotext")]

    insert_text_chunks(collection, dataset, file_hash, "extractous", "")
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("extractous", [])
    check("pdftotext", [(1, "firstagain"), (3, "lastagain")])

    write("pdftotext", [(page, f"bulkword{page}") for page in range(1, 1006)])
    resolve_document_dates(ResolveDocumentDatesParams(collection, dataset, "probe"))
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    write("pdftotext", [])
    assert index_text_pages(params) == sorted([file_hash, other_hash])
    check("pdftotext", [])
    assert matches("bulkword1005") == []
