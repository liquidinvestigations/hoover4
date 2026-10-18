"""Verify suggestion validation, one completion call, and answer metadata preservation."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace

import pytest

from tasks.P_agent import followups
from tasks.P_agent.activities import RunRef, WriteResultParams


def test_three_questions_are_required_and_duplicates_are_rejected():
    assert followups.parse_prompts('["What next?", "Which source?", "Who replied?"]') == [
        "What next?", "Which source?", "Who replied?"]
    assert followups.parse_prompts('1. What next?\n2. Which source?\n3. Who replied?')
    for text in ['[]', '["One?"]', '["Same?", "same?", "Other?"]', '{"questions":[]}']:
        assert followups.parse_prompts(text) == []


#: The reply of the demo `ornith` that the old parser refused: a fenced JSON array.
FENCED_REPLY = ('```json\n[\n  "How would the answer change if you searched only for Chapter 11 '
                'documents in the Enron collection rather than the broader term \\"bankruptcy\\"?",\n'
                '  "Can you explain the difference between the search-index word counts and actual '
                'document-text claims so I understand why some items lack citation handles?",\n'
                '  "What other Enron collection documents corroborate the December 2, 2001 filing date '
                'beyond the three Dow Jones, NYT, and Houston Chronicle pieces cited?"\n]\n```')


def test_a_fenced_array_gives_three_questions():
    prompts = followups.parse_prompts(FENCED_REPLY)
    assert len(prompts) == 3
    assert prompts[0].startswith("How would the answer change")
    assert followups.parse_prompts("Here they are:\n```\n[\"A?\", \"B?\", \"C?\"]\n```") == ["A?", "B?", "C?"]
    assert followups.parse_prompts("<think>x</think>[\"A?\", \"B?\", \"C?\",]") == ["A?", "B?", "C?"]


def _response(status=200, content='["One?", "Two?", "Three?"]', finish='stop'):
    return SimpleNamespace(status_code=status, text='refused', json=lambda: {
        'choices': [{'message': {'content': content}, 'finish_reason': finish}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})


def test_generation_makes_one_tool_free_request_and_records_it(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://model.invalid/v1')
    calls, events = [], []
    monkeypatch.setattr(followups.summarize, '_post', lambda base, body, timeout=None: calls.append(body) or _response())
    monkeypatch.setattr(followups.summarize, 'record_call', lambda *args: events.append(args))
    result = followups.generate_prompts('Question', 'Answer', 'selected-model', 'owner', 'session')
    assert result['follow_up_prompts'] == ['One?', 'Two?', 'Three?']
    assert len(calls) == 1 and 'tools' not in calls[0]
    assert calls[0]['model'] == 'selected-model'
    assert result['follow_up_usage']['completion_tokens'] == 20
    owner, session, kind, model, usage, _latency, ok, error, _bytes = events[0]
    assert (owner, session, kind, model, ok, error) == ('owner', 'session', 'follow_up', 'selected-model', True, '')
    assert usage['prompt_tokens'] == 100


def test_an_unusable_reply_is_recorded_as_a_failed_call(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://model.invalid/v1')
    events = []
    monkeypatch.setattr(followups.summarize, '_post', lambda *a, **k: _response(content='no questions'))
    monkeypatch.setattr(followups.summarize, 'record_call', lambda *args: events.append(args))
    result = followups.generate_prompts('Question', 'Answer', 'm')
    assert result['follow_up_prompts'] == [] and result['follow_up_error']
    assert events[0][6] is False and events[0][7]


@pytest.mark.parametrize("failure", ["status", "connection"])
def test_a_transport_failure_raises_for_the_temporal_retry(monkeypatch, failure):
    import requests

    monkeypatch.setenv('LLM_BASE_URL', 'http://model.invalid/v1')
    events = []

    def post(*args, **kwargs):
        if failure == "connection":
            raise requests.ConnectionError("refused")
        return _response(status=503)

    monkeypatch.setattr(followups.summarize, '_post', post)
    monkeypatch.setattr(followups.summarize, 'record_call', lambda *args: events.append(args))
    with pytest.raises(followups.summarize.TransportFailure):
        followups.generate_prompts('Question', 'Answer', 'm')
    assert len(events) == 1 and events[0][6] is False


def test_a_refused_request_returns_its_error(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://model.invalid/v1')
    monkeypatch.setattr(followups.summarize, '_post', lambda *a, **k: _response(status=400))
    monkeypatch.setattr(followups.summarize, 'record_call', lambda *args: None)
    result = followups.generate_prompts('Question', 'Answer', 'm')
    assert result['follow_up_prompts'] == [] and result['follow_up_error']


@pytest.mark.parametrize("stopped", [False, True])
def test_suggestions_preserve_answer_metadata_and_retry_identity(monkeypatch, stopped):
    from database import agent_runs, clickhouse
    from tasks.P_agent import activities
    run = agent_runs.RunRow(run_id='run', username='owner', session_id='session',
                            start_seq=2, next_seq=6, turn_seq=1, result='Answer')
    monkeypatch.setattr(agent_runs, 'read_run', lambda *args: run)
    monkeypatch.setattr(agent_runs, 'turn_is_stopped', lambda *args: False)
    original = WriteResultParams(username='owner', session_id='session', seq=5,
        role='assistant', content='Answer', context_tokens=42, model='selected',
        usage_json=json.dumps({'citation_status': 'cited'}))
    stored = {**asdict(original), "updated_at": datetime(2020, 1, 1), "message_uuid": "identity", "retry_errors": "[]", "created_ms": datetime(2020, 1, 1)}

    @contextmanager
    def client():
        class Client:
            def query(self, sql, parameters):
                assert parameters['owner'] == 'owner' and parameters['end'] == 6
                return SimpleNamespace(column_names=list(stored), result_rows=[list(stored.values())])
        yield Client()

    monkeypatch.setattr(clickhouse, 'get_global_client', client)
    monkeypatch.setattr(activities, '_user_row_text', lambda *args: 'Question')
    calls = []
    def generate(*args):
        calls.append(args)
        if stopped:
            run.state = 'cancelled'
        return {'follow_up_prompts': ['One?', 'Two?', 'Three?']}
    monkeypatch.setattr(followups, 'generate_prompts', generate)
    written = []
    def write(client, table, data, column_names):
        row = dict(zip(column_names, data[0]))
        written.append(row)
        stored.update(row)
    monkeypatch.setattr(clickhouse, 'insert_durable', write)
    ref = RunRef(run_id='run', username='owner', session_id='session')
    followups.write_followups.__wrapped__(ref)
    followups.write_followups.__wrapped__(ref)
    assert len(calls) == 1
    if stopped:
        assert not written
        return
    assert len(written) == 1
    assert written[0]["seq"] == 5 and written[0]["context_tokens"] == 42
    assert json.loads(written[0]["usage_json"])['citation_status'] == 'cited'
    assert written[0]['message_uuid'] == 'identity' and written[0]['retry_errors'] == '[]'
