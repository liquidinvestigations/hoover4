"""Verify estimates for completion batches against ClickHouse."""

from datetime import datetime, timedelta

import pytest

from database.clickhouse import get_collection_client
from tasks.P_admin import eta_collector as eta


pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stage", ["nlp", "index"])
@pytest.mark.parametrize("span_seconds", [0, 10])
def test_completion_batches_retain_rate_span(temp_collection, monkeypatch, stage, span_seconds):
    monkeypatch.setenv("NER_URL", "configured")
    dataset = "batch_estimate"
    start = datetime(2026, 1, 1)
    with get_collection_client(temp_collection) as client:
        client.insert("text_content", [
            [dataset, str(index), "raw_text", 1, "source text", 10, 1]
            for index in range(300)
        ], column_names=["collection_dataset", "file_hash", "extracted_by", "page_id",
                         "text", "text_bytes", "version"])
        times = [start + timedelta(seconds=span_seconds * (index // 100)) for index in range(200)]
        if stage == "nlp":
            table = "nlp_processed"
            columns = ["collection_dataset", "file_hash", "extracted_by", "page_id",
                       "nlp_model", "text_bytes", "processed_at"]
            rows = [[dataset, str(index), "raw_text", 1, "test", 10, times[index]]
                    for index in range(200)]
            sample = eta._sample_nlp
        else:
            table = "index_state"
            columns = ["collection_dataset", "file_hash", "shard_name", "indexed_at"]
            rows = [[dataset, str(index), "test_1", times[index]] for index in range(200)]
            sample = eta._sample_index
        client.insert(table, rows, column_names=columns)
        client.insert(table, rows, column_names=columns)
        result = sample(client, dataset)
    assert (result.done, result.total) == (200, 300)
    assert result.rate_items_per_sec == (20.0 if span_seconds else 0.0)
    assert result.eta_seconds == (5 if span_seconds else 0)
    assert result.rate_bytes_per_sec == (200.0 if stage == "nlp" and span_seconds else 0.0)


def test_completion_sample_bounds_timestamp_groups(temp_collection):
    with get_collection_client(temp_collection) as client:
        events = eta._completion_events(client, "unused",
            "SELECT toDateTime(1700000000 + number) AS ts, 1 AS items, 10 AS nbytes "
            "FROM numbers(101)")
    assert len(events) == eta.RATE_WINDOW_TIMESTAMPS
    assert events[0] == (1700000100.0, 1, 10)
    assert events[-1] == (1700000001.0, 1, 10)
