"""Verify waited telemetry batches without request-path writes."""

import json
import pytest
from agent_common import clickhouse_buffer as buffer


@pytest.fixture
def sent(monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(buffer, '_thread', object())
    monkeypatch.setattr(buffer, '_rows', {})

    class Client:
        def __init__(self, **kwargs):
            self.auth = kwargs['auth']

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, params, content):
            calls.append((url, self.auth, params, [json.loads(line) for line in content.splitlines()]))
            return httpx.Response(200, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'Client', Client)
    return calls


def test_hundred_events_write_one_waited_statement_for_each_table(sent):
    for index in range(100):
        for table in ('llm_call_events', 'ai_service_telemetry'):
            buffer.record('http://unused', 'database', ('user', 'password'), table, {'value': index})
    assert sent == []
    buffer.flush()
    assert len(sent) == 2
    for _, auth, params, rows in sent:
        assert auth == ('user', 'password')
        assert params['async_insert'] == params['wait_for_async_insert'] == 1
        assert len(rows) == 100
    buffer.flush()
    assert len(sent) == 2


def test_full_buffer_keeps_recent_events_and_reports_dropped_rows(sent, monkeypatch, caplog):
    monkeypatch.setattr(buffer, 'MAX_ROWS', 2)
    for value in range(3):
        buffer.record('http://unused', 'database', ('user', 'password'), 'telemetry', {'value': value})
    buffer.flush()
    assert sent[0][3] == [{'value': 1}, {'value': 2}]
    assert 'dropped one telemetry row' in caplog.text
