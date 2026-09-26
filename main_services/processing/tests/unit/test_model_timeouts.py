"""The worker's agent step limits, read from the environment by `model_timeouts`."""

from datetime import timedelta

import pytest

from tasks.P_agent import model_timeouts
from tasks.P_agent.model_timeouts import load


def test_an_empty_environment_keeps_the_code_defaults():
    timeouts = load({})
    assert timeouts.queue_wait is None
    assert timeouts.model_call == timedelta(seconds=3600)
    assert timeouts.title_request_seconds == 30
    assert timeouts.title_activity == timedelta(seconds=90)


def test_empty_strings_are_unset():
    assert load({name: "" for name in (
        model_timeouts.QUEUE_WAIT_ENV, model_timeouts.MODEL_CALL_ENV,
        model_timeouts.TITLE_REQUEST_ENV)}) == load({})


def test_every_variable_set_gives_its_value():
    timeouts = load({
        "HOOVER4_AGENT_QUEUE_WAIT_SECONDS": "5400",
        "LLM_REQUEST_TIMEOUT_SECONDS": "1800",
        "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS": "120",
    })
    assert timeouts.queue_wait == timedelta(seconds=5400)
    assert timeouts.model_call == timedelta(seconds=1800)
    assert timeouts.title_request_seconds == 120


def test_the_run_timeout_variables_are_read_no_more():
    assert load({"HOOVER4_CHAT_RUN_TIMEOUT_SECONDS": "10",
                 "HOOVER4_PLAN_RUN_TIMEOUT_SECONDS": "10"}) == load({})


def test_the_title_activity_allows_two_requests_and_thirty_seconds():
    timeouts = load({"HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS": "120"})
    assert timeouts.title_activity == timedelta(seconds=270)


@pytest.mark.parametrize("name", [
    "HOOVER4_AGENT_QUEUE_WAIT_SECONDS",
    "LLM_REQUEST_TIMEOUT_SECONDS",
    "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS",
])
def test_a_value_that_is_not_a_number_names_its_variable(name):
    with pytest.raises(ValueError, match=name):
        load({name: "an hour"})


def test_the_fixed_step_values():
    assert model_timeouts.TOOL_CALL_TIMEOUT == timedelta(seconds=300)
    assert model_timeouts.STEP_HEARTBEAT_TIMEOUT == timedelta(seconds=30)
    assert model_timeouts.STEP_HEARTBEAT_SECONDS == 10.0
    assert model_timeouts.RUN_MODEL_STEPS == 600
    assert model_timeouts.CONTINUE_AS_NEW_STEPS == 250
    assert model_timeouts.HISTORY_EVENTS_PER_RUN == 30_000
    # Three beats fit in the heartbeat limit.
    assert 3 * model_timeouts.STEP_HEARTBEAT_SECONDS <= (
        model_timeouts.STEP_HEARTBEAT_TIMEOUT.total_seconds())


def test_the_workflow_uses_the_module_values():
    from tasks.P_agent import summarize, workflows

    assert workflows.TIMEOUTS is model_timeouts.TIMEOUTS
    assert workflows.TOOL_CALL_TIMEOUT == model_timeouts.TOOL_CALL_TIMEOUT
    assert workflows.RUN_MODEL_STEPS == model_timeouts.RUN_MODEL_STEPS
    assert summarize.REQUEST_TIMEOUT == (10, model_timeouts.TIMEOUTS.title_request_seconds)
