"""Unit tests for the ETA collector's pure functions.

The SQL side is exercised against the live stack; what must never regress in
silence is the math: event-based rates, the pessimistic combine, and the
self-throttle.
"""

from tasks.P_admin.eta_collector import (
    MIN_INTERVAL_SECONDS,
    THROTTLE_FACTOR,
    combine_eta,
    next_interval_seconds,
    rate_from_events,
    remaining_projection,
)


def test_rate_from_events_needs_two_events():
    assert rate_from_events([]) == (0.0, 0.0)
    assert rate_from_events([(1000.0, 5, 500)]) == (0.0, 0.0)


def test_rate_from_events_zero_span_carries_no_information():
    events = [(1000.0, 5, 500), (1000.0, 5, 500)]
    assert rate_from_events(events) == (0.0, 0.0)


def test_rate_from_events_sums_over_span():
    events = [(1000.0, 10, 1000), (1050.0, 20, 3000), (1100.0, 30, 6000)]
    items, nbytes = rate_from_events(events)
    assert items == 60 / 100
    assert nbytes == 10000 / 100


def test_remaining_projection_is_zero_when_complete_or_stalled():
    assert remaining_projection(100, 100, 2.0) == 0.0
    assert remaining_projection(150, 100, 2.0) == 0.0
    assert remaining_projection(50, 100, 0.0) == 0.0
    assert remaining_projection(50, 100, 2.0) == 25.0


def test_combine_eta_takes_the_pessimistic_projection():
    assert combine_eta(100.0, 40.0) == 100
    assert combine_eta(40.0, 100.0) == 100
    assert combine_eta(0.0, 0.0) == 0
    # One unavailable projection (0) does not kill the other.
    assert combine_eta(0.0, 42.0) == 42


def test_throttle_is_twenty_times_the_mean_cost():
    # A 20 s mean produces a 400 s sampling interval.
    assert next_interval_seconds([20_000, 20_000]) == THROTTLE_FACTOR * 20.0


def test_throttle_has_a_floor_for_idle_clusters():
    assert next_interval_seconds([]) == MIN_INTERVAL_SECONDS
    assert next_interval_seconds([1, 2, 3]) == MIN_INTERVAL_SECONDS


def test_nlp_byte_total_reads_the_stored_column():
    """NLP `total_bytes` must be a sum over `text_bytes`, never `length(text)`."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "tasks" / "P_admin" / "eta_collector.py"
    text = src.read_text()
    assert "sum(length(t))" not in text
    assert "max(text_bytes)" in text


def test_continue_as_new_resets_passes():
    """A carried-over `passes` at the threshold continue-as-news every pass with no sleep."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "tasks" / "P_admin" / "workflows.py"
    text = src.read_text()
    assert "state.passes = 0" in text
    assert "workflow.continue_as_new(state)" in text


def test_disabled_ner_counts_every_segment_as_complete(monkeypatch):
    from tasks.P_admin import eta_collector as eta

    monkeypatch.delenv('NER_URL', raising=False)
    values = iter([[(3,)], [(8,)], [(30,)], [(80,)]])
    monkeypatch.setattr(eta, '_query', lambda *args: next(values))
    sample = eta._sample_nlp(object(), 'dataset')
    assert sample.done == sample.total == 8
    assert sample.eta_seconds == 0


def test_collection_without_active_operation_has_no_collection_reads(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from database import clickhouse
    from tasks.P_admin import eta_collector as eta

    client = SimpleNamespace(query=lambda *args, **kwargs: SimpleNamespace(result_rows=[(0,)]))
    monkeypatch.setattr(clickhouse, 'get_global_client', lambda: nullcontext(client))
    monkeypatch.setattr(clickhouse, 'get_collection_client', lambda *args: (_ for _ in ()).throw(
        AssertionError('Inactive collection was sampled')))
    assert eta.collect_collection_samples('collection') == ([], True)
