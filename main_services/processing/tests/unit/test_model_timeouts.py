"""The worker's agent-run timeouts, read from the environment by `model_timeouts`."""

from datetime import timedelta

import pytest

from tasks.P_agent import model_timeouts
from tasks.P_agent.model_timeouts import load


def test_an_empty_environment_keeps_the_values_of_before_the_keys():
    timeouts = load({})
    assert timeouts.queue_wait is None
    assert timeouts.chat_run == timedelta(seconds=900)
    assert timeouts.plan_run == timedelta(seconds=2400)
    assert timeouts.title_request_seconds == 30
    assert timeouts.title_activity == timedelta(seconds=90)


def test_empty_strings_are_unset():
    assert load({name: "" for name in (
        model_timeouts.QUEUE_WAIT_ENV, model_timeouts.CHAT_RUN_ENV,
        model_timeouts.PLAN_RUN_ENV, model_timeouts.TITLE_REQUEST_ENV)}) == load({})


def test_every_variable_set_gives_its_value():
    timeouts = load({
        "HOOVER4_AGENT_QUEUE_WAIT_SECONDS": "36120",
        "HOOVER4_CHAT_RUN_TIMEOUT_SECONDS": "18060",
        "HOOVER4_PLAN_RUN_TIMEOUT_SECONDS": "18060",
        "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS": "120",
    })
    assert timeouts.queue_wait == timedelta(seconds=36120)
    assert timeouts.chat_run == timedelta(seconds=18060)
    assert timeouts.plan_run == timedelta(seconds=18060)
    assert timeouts.title_request_seconds == 120


def test_the_title_activity_allows_two_requests_and_thirty_seconds():
    timeouts = load({"HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS": "120"})
    assert timeouts.title_activity == timedelta(seconds=270)


@pytest.mark.parametrize("name", [
    "HOOVER4_AGENT_QUEUE_WAIT_SECONDS",
    "HOOVER4_CHAT_RUN_TIMEOUT_SECONDS",
    "HOOVER4_PLAN_RUN_TIMEOUT_SECONDS",
    "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS",
])
def test_a_value_that_is_not_a_number_names_its_variable(name):
    with pytest.raises(ValueError, match=name):
        load({name: "an hour"})


def test_the_workflow_uses_the_module_values():
    from tasks.P_agent import summarize, workflows

    assert workflows.RUN_AGENT_TIMEOUT == model_timeouts.TIMEOUTS.chat_run
    assert workflows.PLAN_RUN_AGENT_TIMEOUT == model_timeouts.TIMEOUTS.plan_run
    assert summarize.REQUEST_TIMEOUT == (10, model_timeouts.TIMEOUTS.title_request_seconds)
