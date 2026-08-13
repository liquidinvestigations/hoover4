"""Which re-run recovers which failure, and the chunking that keeps a hash list
inside ClickHouse's parameter limit."""

from tasks.P_admin.failed_file_retry import (
    HASH_CHUNK,
    RETRY_EMBED,
    RETRY_INDEX,
    RETRY_NLP,
    RETRY_PLAN,
    FailureGroup,
    chunked,
    partition_retry_result,
    retry_kind_for_task,
)


def test_ner_failures_retry_the_nlp_stage():
    assert retry_kind_for_task("P4_ExtractEntities") == RETRY_NLP


def test_index_writers_retry_the_index_stage():
    for task in ("P6_IndexTextPages", "P6_IndexMetadata",
                 "P6_IndexVectors", "P6_IndexFilenamesRow"):
        assert retry_kind_for_task(task) == RETRY_INDEX, task


def test_embedding_failures_retry_the_embed_stage():
    assert retry_kind_for_task("P5_ChunkEmbed") == RETRY_EMBED


def test_parse_stage_failures_need_the_whole_plan():
    # The parse stages are per-file child workflows of plan execution and have no entry
    # point that does not start by downloading the plan. An unknown task must land here
    # too: reopening a plan is always correct, just expensive.
    for task in ("P3_ParseSingleFile", "detector_error_tika", "run_ocr_and_store",
                 "run_ocr_pdf_and_store[tesseract]", "parse_office_xml_and_store",
                 "archive_scan", "pdf_process", "", "something_new"):
        assert retry_kind_for_task(task) == RETRY_PLAN, task


def test_failure_group_reports_its_retry_kind():
    group = FailureGroup(
        collection_dataset="epstein_docs", task_name="P4_ExtractEntities",
        errors=200, documents=200, first_seen="", last_seen="",
    )
    assert group.retry_kind == RETRY_NLP


def test_chunked_bounds_every_batch():
    values = [f"h{i}" for i in range(HASH_CHUNK * 2 + 3)]
    batches = list(chunked(values))
    assert sum(len(b) for b in batches) == len(values)
    assert [v for b in batches for v in b] == values
    assert all(len(b) <= HASH_CHUNK for b in batches)


def test_chunked_of_nothing_yields_nothing():
    assert list(chunked([])) == []


def test_a_repeated_failure_replaces_its_row_instead_of_adding_one():
    """The row count is what a visitor reads on `/file_browser/c/<name>` and what the
    admin processing page prints beside the bar. An append-only retry shows N failed
    documents as 2N failures, and 3N after the next attempt."""
    hashes = ["a", "b", "c"]
    outcome = partition_retry_result(hashes, refreshed=["a", "b"], still_broken=[])
    assert outcome.recovered == ["c"]
    assert outcome.superseded == ["a", "b"]
    assert outcome.unchanged == []


def test_a_document_that_recorded_nothing_new_keeps_its_evidence():
    """An NER retry verifies by watermark, so a document can be judged still broken
    without the re-run having written anything. Its original row is the only record of
    the failure and must survive untouched."""
    outcome = partition_retry_result(["a", "b"], refreshed=[], still_broken=["b"])
    assert outcome.recovered == ["a"]
    assert outcome.superseded == []
    assert outcome.unchanged == ["b"]


def test_a_fresh_error_row_outranks_the_watermark_check():
    # A document whose text got a watermark but whose re-run still recorded an error is
    # not recovered: clearing its rows would delete the failure that just happened.
    outcome = partition_retry_result(["a"], refreshed=["a"], still_broken=[])
    assert outcome.recovered == []
    assert outcome.superseded == ["a"]


def test_every_retried_hash_is_accounted_for_exactly_once():
    hashes = [f"h{i}" for i in range(20)]
    outcome = partition_retry_result(hashes, refreshed=hashes[:5], still_broken=hashes[3:8])
    seen = outcome.recovered + outcome.superseded + outcome.unchanged
    assert sorted(seen) == sorted(hashes)
    assert len(seen) == len(set(seen))
