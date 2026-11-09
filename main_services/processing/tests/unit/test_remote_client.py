"""Tests for tasks.remote: the timeout contract, the endpoint list and the breaker.

deploy.py renders GPU_CONNECT_TIMEOUT_MS and GPU_CIRCUIT_BREAK_SECONDS into the
worker's environment. Without a reader, a dead GPU host stalls the pipeline for tens
of minutes instead of failing the call in seconds.
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
    def __init__(self, payload=None, error=None, status_code=200, headers=None):
        self._payload = payload or {}
        self._error = error
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


GPU = ("gpu", "http://gpu.test/v1/extract-entities")
SECOND = ("second", "http://second.test/v1/extract-entities")


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
    result = remote.post_json([GPU, SECOND], {})
    assert result.provider == "gpu" and result.url == GPU[1]


def test_falls_back_to_the_cpu_twin_on_connect_failure(monkeypatch):
    def post(url, **kwargs):
        if url == GPU[1]:
            raise requests.ConnectTimeout("no route to host")
        return _Response({"data": ["cpu"]})

    monkeypatch.setattr(requests, "post", post)
    result = remote.post_json([GPU, SECOND], {})
    assert result.provider == "second", "must degrade, not fail"
    assert result.data == {"data": ["cpu"]}


def test_no_twin_configured_fails_fast_and_names_the_url(monkeypatch):
    """With no second endpoint, a connect failure fails fast with a clear message."""
    def post(url, **kwargs):
        raise requests.ConnectTimeout("no route to host")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(remote.RemoteUnavailable) as excinfo:
        remote.post_json([GPU, ("second", "")], {})
    assert "gpu.test" in str(excinfo.value)


def test_a_read_timeout_does_not_silently_downgrade(monkeypatch):
    """A ReadTimeout means the host IS alive. Retrying on the SECOND twin would
    hide a real server-side problem behind a silently degraded provider."""
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise requests.ReadTimeout("still chewing")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(remote.RemoteUnavailable):
        remote.post_json([GPU, SECOND], {})
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
        remote.post_json([GPU, SECOND], {})

    gpu_attempts = [u for u in attempts if u == GPU[1]]
    assert len(gpu_attempts) == 2, (
        f"breaker should have stopped probing the dead GPU after 2 failures, "
        f"got {len(gpu_attempts)} attempts"
    )


def test_breaker_is_time_boxed_never_latching(monkeypatch):
    """A recovered GPU host must come back on its own -- a latching breaker
    would silently pin everything to SECOND forever."""
    state = {"down": True}

    def post(url, **kwargs):
        if url == GPU[1] and state["down"]:
            raise requests.ConnectTimeout("down")
        return _Response({"data": []})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(remote, "CIRCUIT_FAILURE_THRESHOLD", 1)
    monkeypatch.setattr(remote, "CIRCUIT_BREAK_SECONDS", 0.05)

    assert remote.post_json([GPU, SECOND], {}).provider == "second"
    assert remote.post_json([GPU, SECOND], {}).provider == "second"  # circuit open

    state["down"] = False
    import time
    time.sleep(0.08)
    assert remote.post_json([GPU, SECOND], {}).provider == "gpu", "breaker latched"


def test_every_caller_gives_one_endpoint(monkeypatch):
    """No supported call has a second endpoint, so no setting can select one."""
    from tasks import ocr_client, ocr_pdf_client
    from tasks.P4_extract_entities import extract_ner_from_text

    for name in ("OCR_TESSERACT_URL", "OCR_EASYOCR_URL", "OCR_PDF_URL", "NER_URL"):
        monkeypatch.setenv(name, "http://service.test/v1")
    lists = [ocr_client._endpoints_for(ocr_client.ENGINE_TESSERACT),
             ocr_client._endpoints_for(ocr_client.ENGINE_EASYOCR),
             ocr_pdf_client._endpoints(), extract_ner_from_text._endpoints()]
    assert [len(endpoints) for endpoints in lists] == [1, 1, 1, 1]


def test_a_single_endpoint_connect_failure_is_unavailable(monkeypatch):
    def post(url, **kwargs):
        raise requests.ConnectTimeout("down")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(remote.RemoteUnavailable) as excinfo:
        remote.post_json([GPU], {})
    assert "gpu.test" in str(excinfo.value)


def test_http_errors_propagate_rather_than_falling_back(monkeypatch):
    """A 500 means the host is alive and broken. Failing the activity makes
    Temporal retry it; degrading to SECOND would mask the fault."""
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Response(
        error=requests.HTTPError("boom"), status_code=500))
    with pytest.raises(requests.HTTPError):
        remote.post_json([GPU, SECOND], {})


def test_http_503_is_retryable_and_does_not_fall_back(monkeypatch):
    """Queue-full is a live, busy GPU. Temporal retries."""
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _Response(status_code=503, headers={"Retry-After": "5"})

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(remote.RemoteBusy) as excinfo:
        remote.post_json([GPU, SECOND], {})
    assert calls == [GPU[1]], "must not degrade to the SECOND twin on 503"
    assert excinfo.value.retry_after_seconds == 5
    assert not remote._BREAKER.is_open(GPU[1]), "503 must not open the breaker"


def test_no_endpoint_configured_is_a_clear_error(monkeypatch):
    with pytest.raises(remote.RemoteUnavailable) as excinfo:
        remote.post_json([("gpu", ""), ("second", "")], {})
    assert "no endpoint is configured" in str(excinfo.value)
