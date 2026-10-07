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


def test_generation_makes_one_tool_free_request(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://model.invalid/v1')
    calls = []
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        'choices': [{'message': {'content': '["One?", "Two?", "Three?"]'}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    monkeypatch.setattr(followups.summarize, '_post', lambda base, body: calls.append(body) or response)
    result = followups.generate_prompts('Question', 'Answer', 'selected-model')
    assert result['follow_up_prompts'] == ['One?', 'Two?', 'Three?']
    assert len(calls) == 1 and 'tools' not in calls[0]
    assert calls[0]['model'] == 'selected-model'
    assert result['follow_up_usage']['completion_tokens'] == 20


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
