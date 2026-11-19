"""Verify the failure classes of remote calls, the outage budget and capability readiness."""

import dataclasses
import json
import time
from datetime import timedelta

import pytest
import requests
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import ActivityEnvironment

from tasks import remote, service_readiness
from tasks.remote_busy_retry import (
    OUTAGE_BUDGET_SECONDS,
    OUTAGE_MAX_DELAY_SECONDS,
    with_remote_busy_retry,
    with_remote_outage_retry,
)

GPU = ("gpu", "http://gpu.test/v1/extract-entities")


@pytest.fixture(autouse=True)
def _clean_breaker():
    remote._BREAKER = remote._Breaker()
    yield
    remote._BREAKER = remote._Breaker()


class _Response:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _post_raising(exc):
    def post(url, **kwargs):
        raise exc
    return post


@pytest.mark.parametrize("exc, expected", [
    (requests.ConnectionError("refused"), remote.RemoteOutage),
    (requests.ConnectTimeout("no route"), remote.RemoteOutage),
    (requests.ReadTimeout("slow"), remote.RemoteReadTimeout),
])
def test_post_json_names_the_failure_class(monkeypatch, exc, expected):
    monkeypatch.setattr(requests, "post", _post_raising(exc))
    with pytest.raises(expected) as excinfo:
        remote.post_json([GPU], {})
    assert isinstance(excinfo.value, remote.RemoteUnavailable)
    assert type(excinfo.value) is expected


def test_a_missing_endpoint_is_not_an_outage():
    with pytest.raises(remote.RemoteNotConfigured):
        remote.post_json([("gpu", "")], {})


def test_a_proxy_502_is_an_outage_and_an_auth_failure_is_not(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Response(status_code=502))
    with pytest.raises(remote.RemoteOutage):
        remote.post_json([GPU], {})
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Response(status_code=401))
    with pytest.raises(requests.HTTPError):
        remote.post_json([GPU], {})


def run_attempt(function, attempt, detail, wrapper=with_remote_outage_retry, seconds=1800):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=attempt,
        heartbeat_details=[detail] if detail else [],
        start_to_close_timeout=timedelta(seconds=seconds))
    beats = []
    env.on_heartbeat = lambda *values: beats.append(json.loads(json.dumps(values[0])))
    try:
        return env.run(wrapper(function)), beats, None
    except Exception as exc:  # noqa: BLE001 - the test inspects every outcome
        return None, beats, exc


def test_outage_retries_exceed_five_attempts_and_then_succeed(monkeypatch):
    now, detail, calls = [1000.0], None, []
    monkeypatch.setattr(time, "time", lambda: now[0])

    def request():
        calls.append(1)
        if len(calls) <= 8:
            raise remote.RemoteOutage("refused")
        return "done"

    delays = []
    for attempt in range(1, 10):
        result, beats, error = run_attempt(request, attempt, detail)
        if attempt <= 8:
            assert isinstance(error, ApplicationError) and error.type == "RemoteOutage"
            assert not error.non_retryable
            delays.append(error.next_retry_delay.total_seconds())
            detail = beats[-1]
            assert detail["failures"] == 0 and detail["first_outage"] == 1000
            now[0] += delays[-1]
        else:
            assert error is None and result == "done"
    assert delays[:3] == [5, 10, 20]
    assert max(delays) == OUTAGE_MAX_DELAY_SECONDS


def test_the_outage_budget_survives_a_restart_and_then_ends_the_activity(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    def refused():
        raise remote.RemoteOutage("refused")

    _, beats, _ = run_attempt(refused, 1, None)
    # A new worker reads the heartbeat details of the earlier attempt.
    now[0] = 1000.0 + OUTAGE_BUDGET_SECONDS
    _, _, error = run_attempt(lambda: pytest.fail("The expired request ran."), 2, beats[-1])
    assert error.type == "ServiceOutage" and error.non_retryable
    assert "refused" in str(error)


def test_a_worker_stop_during_an_outage_wait_keeps_the_failure_count(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    def refused():
        raise remote.RemoteOutage("refused")

    _, beats, _ = run_attempt(refused, 1, None)
    detail = beats[-1]
    assert detail["running"] is False
    result, beats, error = run_attempt(lambda: "done", 2, detail)
    assert error is None and result == "done"
    assert beats[-1]["failures"] == 0


def test_ordinary_failures_keep_their_limit_between_outages(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    outcomes = iter([remote.RemoteOutage("refused"), ValueError("bad input")] * 5)

    def request():
        raise next(outcomes)

    detail, ordinary = None, 0
    for attempt in range(1, 11):
        _, beats, error = run_attempt(request, attempt, detail)
        detail = beats[-1]
        if not (isinstance(error, ApplicationError) and error.type == "RemoteOutage"):
            ordinary += 1
    assert detail["failures"] == 5
    assert isinstance(error, ApplicationError) and error.non_retryable and error.type == "ValueError"


def test_read_timeouts_and_auth_failures_are_ordinary_failures(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    for exc in (remote.RemoteReadTimeout("slow"), requests.HTTPError("HTTP 401")):
        def request(exc=exc):
            raise exc
        _, beats, error = run_attempt(request, 1, None)
        assert error is exc
        assert beats[-1]["failures"] == 1


def test_without_the_outage_option_an_outage_is_an_ordinary_failure(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)

    def refused():
        raise remote.RemoteOutage("refused")

    _, beats, error = run_attempt(refused, 1, None, wrapper=with_remote_busy_retry)
    assert isinstance(error, remote.RemoteOutage)
    assert beats[-1]["failures"] == 1


def test_cancellation_during_an_outage_wait_stays_cancellation(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    detail = {"remote_retry": 1, "failures": 0, "attempt": 1, "running": False,
              "outage_retry": True, "first_outage": 900.0, "outage_retries": 1}

    def cancelled():
        raise CancelledError("Cancelled.")

    _, beats, error = run_attempt(cancelled, 2, detail)
    assert isinstance(error, CancelledError)
    assert beats[-1]["failures"] == 0


def test_the_ner_and_embedding_activities_wait_for_outages():
    from tasks.P4_extract_entities import activities as ner
    from tasks.P5_chunk_embed import activities as embed
    from tasks.P4_extract_entities import scan_regex_entities

    assert "with_remote_outage_retry" in open(ner.__file__).read()
    assert "with_remote_outage_retry" in open(embed.__file__).read()
    assert "with_remote_outage_retry" not in open(scan_regex_entities.__file__).read()


class _Session:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.urls = response, error, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.response


def test_readiness_states(monkeypatch):
    monkeypatch.delenv("NER_URL", raising=False)
    assert service_readiness.capability_readiness("ner") == service_readiness.DISABLED
    monkeypatch.setenv("NER_URL", "http://ai.test/v1/")
    ready = _Session(_Response({"ner_model_loaded": True}))
    assert service_readiness.capability_readiness("ner", ready) == service_readiness.READY
    assert ready.urls == ["http://ai.test/v1/health"]
    unloaded = _Session(_Response({"ner_model_loaded": False}))
    assert service_readiness.capability_readiness("ner", unloaded) == service_readiness.UNAVAILABLE
    refused = _Session(error=requests.ConnectionError("refused"))
    assert service_readiness.capability_readiness("ner", refused) == service_readiness.UNAVAILABLE
    failing = _Session(_Response(status_code=502))
    assert service_readiness.capability_readiness("ner", failing) == service_readiness.UNAVAILABLE


def test_embedding_readiness_needs_the_probed_model(monkeypatch):
    import database.clickhouse as clickhouse

    monkeypatch.setenv("EMBEDDINGS_URL", "http://ai.test/v1")
    settings = {}
    monkeypatch.setattr(clickhouse, "get_server_setting", lambda key: settings.get(key))
    ready = _Session(_Response({"embedding_model_loaded": True}))
    assert service_readiness.capability_readiness("embeddings", ready) == service_readiness.MISCONFIGURED
    settings.update(embeddings_serving_model="model", embeddings_serving_dim="1024")
    assert service_readiness.capability_readiness("embeddings", ready) == service_readiness.READY
