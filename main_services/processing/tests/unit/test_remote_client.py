"""Tests for tasks.remote: the timeout contract, the fallback and the breaker.

These three settings -- GPU_CONNECT_TIMEOUT_MS, GPU_FALLBACK and
GPU_CIRCUIT_BREAK_SECONDS -- were rendered into the worker's environment by
deploy.py from Part 1 and read by nothing, which is how a dead GPU host stalled
the pipeline for tens of minutes instead of degrading it. Each one gets a test
here so it cannot go back to being decorative.
"""

import pytest
import requests

from tasks import remote


@pytest.fixture(autouse=True)
def _clean_breaker():
    """The breaker is process-global by design (one dead host must cost one
    timeout per window for the whole worker, not per activity), so it has to be
    reset between tests."""
    remote._BREAKER = remote._Breaker()
    yield
    remote._BREAKER = remote._Breaker()


class _Response:
    def __init__(self, payload=None, error=None):
        self._payload = payload or {}
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


GPU = ("gpu", "http://gpu.test/v1/extract-entities")
CPU = ("spacy", "http://cpu.test/v1/extract-entities")


def test_connect_timeout_is_a_two_tuple_not_a_scalar(monkeypatch):
    """The bug this module exists for: requests measures timeouts in SECONDS,
    so timeout=3000 was a 50-minute budget for both connect and read."""
    seen = {}

    def post(url, json=None, headers=None, timeout=None):
        seen["timeout"] = timeout
        return _Response({"ok": True})

    monkeypatch.setattr(requests, "post", post)
    remote.post_json([GPU], {"input": []})

    assert isinstance(seen["timeout"], tuple), "must pass (connect, read)"
    connect, read = seen["timeout"]
    assert connect <= 5, "a dead host must be detected in seconds"
    assert read > connect, "a live host chewing through a batch needs minutes"


def test_records_which_endpoint_actually_served(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Response({"data": []}))
    result = remote.post_json([GPU, CPU], {})
    assert result.provider == "gpu" and result.url == GPU[1]


def test_falls_back_to_the_cpu_twin_on_connect_failure(monkeypatch):
    def post(url, **kwargs):
        if url == GPU[1]:
            raise requests.ConnectTimeout("no route to host")
        return _Response({"data": ["cpu"]})

    monkeypatch.setattr(requests, "post", post)
    result = remote.post_json([GPU, CPU], {})
    assert result.provider == "spacy", "must degrade, not fail"
    assert result.data == {"data": ["cpu"]}


def test_no_twin_configured_fails_fast_and_names_the_url(monkeypatch):
    """Until Part 2 builds the CPU twin, GPU_FALLBACK=true with nothing to fall
    back to must fail fast with a clear message, not stall."""
    def post(url, **kwargs):
        raise requests.ConnectTimeout("no route to host")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(remote.RemoteUnavailable) as excinfo:
        remote.post_json([GPU, ("spacy", "")], {})
    assert "gpu.test" in str(excinfo.value)


def test_a_read_timeout_does_not_silently_downgrade(monkeypatch):
    """A ReadTimeout means the host IS alive. Retrying on the CPU twin would
    hide a real server-side problem behind a silently degraded provider."""
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise requests.ReadTimeout("still chewing")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(remote.RemoteUnavailable):
        remote.post_json([GPU, CPU], {})
    assert calls == [GPU[1]], "must not try the twin after a read timeout"


def test_breaker_opens_and_stops_paying_the_connect_timeout(monkeypatch):
    """Without the breaker a dead host costs one connect timeout PER FILE across
    the whole dataset; with it, one per break window."""
    attempts = []

    def post(url, **kwargs):
        attempts.append(url)
        if url == GPU[1]:
            raise requests.ConnectTimeout("down")
        return _Response({"data": []})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(remote, "CIRCUIT_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr(remote, "CIRCUIT_BREAK_SECONDS", 60.0)

    for _ in range(5):
        remote.post_json([GPU, CPU], {})

    gpu_attempts = [u for u in attempts if u == GPU[1]]
    assert len(gpu_attempts) == 2, (
        f"breaker should have stopped probing the dead GPU after 2 failures, "
        f"got {len(gpu_attempts)} attempts"
    )


def test_breaker_is_time_boxed_never_latching(monkeypatch):
    """A recovered GPU host must come back on its own -- a latching breaker
    would silently pin everything to CPU forever."""
    state = {"down": True}

    def post(url, **kwargs):
        if url == GPU[1] and state["down"]:
            raise requests.ConnectTimeout("down")
        return _Response({"data": []})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(remote, "CIRCUIT_FAILURE_THRESHOLD", 1)
    monkeypatch.setattr(remote, "CIRCUIT_BREAK_SECONDS", 0.05)

    assert remote.post_json([GPU, CPU], {}).provider == "spacy"
    assert remote.post_json([GPU, CPU], {}).provider == "spacy"  # circuit open

    state["down"] = False
    import time
    time.sleep(0.08)
    assert remote.post_json([GPU, CPU], {}).provider == "gpu", "breaker latched"


def test_gpu_fallback_false_never_uses_the_twin(monkeypatch):
    def post(url, **kwargs):
        if url == GPU[1]:
            raise requests.ConnectTimeout("down")
        return _Response({"data": []})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(remote, "GPU_FALLBACK", False)
    with pytest.raises(remote.RemoteUnavailable):
        remote.post_json([GPU, CPU], {})


def test_http_errors_propagate_rather_than_falling_back(monkeypatch):
    """A 500 means the host is alive and broken. Failing the activity makes
    Temporal retry it; degrading to CPU would mask the fault."""
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Response(
        error=requests.HTTPError("boom")))
    with pytest.raises(requests.HTTPError):
        remote.post_json([GPU, CPU], {})


def test_no_endpoint_configured_is_a_clear_error(monkeypatch):
    with pytest.raises(remote.RemoteUnavailable) as excinfo:
        remote.post_json([("gpu", ""), ("spacy", "")], {})
    assert "no endpoint is configured" in str(excinfo.value)
