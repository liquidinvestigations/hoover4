"""Unit telemetry retains its payload without starting a datastore writer."""

from tasks import ai_telemetry


def test_unit_telemetry_sink_retains_and_flushes_the_row(_unit_timing_sink):
    ai_telemetry.record("ocr", provider="fixture", latency_ms=12, detail="captured")
    _unit_timing_sink.flush()
    rows = [row for collection, table, columns, rows in _unit_timing_sink.inserts
            if table == "ai_service_telemetry" for row in rows]
    assert rows == [["ocr", "fixture", "pipeline", "", 12, 1, "captured"]]
