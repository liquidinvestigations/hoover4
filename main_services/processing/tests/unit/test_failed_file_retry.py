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
