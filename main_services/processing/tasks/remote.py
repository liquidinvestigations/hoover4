"""Outbound HTTP from activities: bounded timeouts, CPU fallback, circuit breaker.

Why this module exists
----------------------
An activity that calls out over HTTP can stall with no load on the system at
all. Two defects stack to produce it:

1. a routing defect: a rootless podman container cannot route to its host's own
   LAN address, so the GPU endpoint is unreachable and hangs rather than
   refusing;
2. a timeout defect (this module): ``extract_ner_from_text.py`` passed
   a bare ``timeout=3000`` to ``requests.post``. **requests measures timeouts
   in seconds**, so that is a 50-minute budget applied to *both* connect and
   read, for a single NER batch. The only reason it fails in ~2 minutes rather
   than 50 is the kernel giving up on SYN retries first.

The config contract must also be honoured. ``deploy.py`` renders
``GPU_CONNECT_TIMEOUT_MS``, ``GPU_FALLBACK`` and ``GPU_CIRCUIT_BREAK_SECONDS``
into the worker's environment, and this module is what reads them. A setting that
is rendered and never read means a dead GPU host stalls the pipeline instead of
degrading it, which is precisely what those three settings exist to prevent.

The contract implemented here
-----------------------------
====================== ======================================================
``GPU_CONNECT_TIMEOUT_MS``  connect timeout on every ai-tier call (default 2000)
``GPU_FALLBACK``            on connect failure, retry against the CPU twin
``GPU_CIRCUIT_BREAK_SECONDS`` after N consecutive connect failures, skip the GPU
                            endpoint entirely for this long
====================== ======================================================

The ``(connect, read)`` two-tuple is what this module exists for. The failure modes are
completely different. A dead host must be detected in ~2 seconds, while a live
host chewing through a batch legitimately needs minutes. A single scalar forces
one number to serve both and guarantees one of them is wrong.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# Connect: a dead host must be detected in ~2 s, not in minutes.
CONNECT_TIMEOUT = _env_float("GPU_CONNECT_TIMEOUT_MS", 2000.0) / 1000.0

# Read: generous for a real NER/embeddings batch, but finite. Never inherit the
# connect number and never leave it unset.
READ_TIMEOUT = _env_float("REMOTE_READ_TIMEOUT_SECONDS", 120.0)

# After this many consecutive connect failures the endpoint is considered down.
CIRCUIT_FAILURE_THRESHOLD = int(_env_float("REMOTE_CIRCUIT_FAILURES", 3))

# How long an endpoint stays skipped once the breaker opens. Time-boxed, never
# latching: a recovered GPU host must come back on its own.
CIRCUIT_BREAK_SECONDS = _env_float("GPU_CIRCUIT_BREAK_SECONDS", 60.0)

GPU_FALLBACK = _env_bool("GPU_FALLBACK", True)


class RemoteUnavailable(RuntimeError):
    """Every configured endpoint for a capability refused or was unreachable.

    Raised fast and with the URLs named: a plan that fails in two seconds with "GPU NER
    unreachable at <url> and no CPU twin is enabled" names what broke, and one that stalls
    for fifty minutes does not.
    """


@dataclass
class _Circuit:
    consecutive_failures: int = 0
    open_until: float = 0.0


class _Breaker:
    """Per-endpoint circuit state, shared across the threads of one worker.

    Without this, a dead GPU host costs one connect timeout *per file* across
    the whole dataset. With it, the cost is one timeout per break window.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._circuits: dict[str, _Circuit] = {}

    def is_open(self, url: str) -> bool:
        with self._lock:
            c = self._circuits.get(url)
            return bool(c and c.open_until > time.monotonic())

    def record_failure(self, url: str) -> bool:
        """Count a connect failure. Returns whether that tripped the breaker."""
        with self._lock:
            c = self._circuits.setdefault(url, _Circuit())
            c.consecutive_failures += 1
            if c.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
                c.open_until = time.monotonic() + CIRCUIT_BREAK_SECONDS
                c.consecutive_failures = 0
                return True
            return False

    def record_success(self, url: str) -> None:
        with self._lock:
            self._circuits.pop(url, None)


_BREAKER = _Breaker()


def _record(service: str, provider: str, latency_ms: float, *, ok: bool,
            detail: str) -> None:
    """Telemetry for one attempt, if the caller opted in. Never raises."""
    if not service:
        return
    from tasks.ai_telemetry import record

    record(service, provider=provider, latency_ms=latency_ms, ok=ok, detail=detail)


@dataclass
class RemoteResult:
    """A response plus **which endpoint actually served it**.

    Callers record ``served_by`` -- in ``extracted_by`` for OCR, ``nlp_model``
    for NER, ``embedding_model`` for vectors. Never record the *configured*
    provider: under fallback the two differ, and that difference is the only
    evidence an outage happened at all.
    """

    data: object
    url: str
    provider: str


def post_json(
    endpoints: list[tuple[str, str]],
    payload: dict,
    *,
    read_timeout: float = READ_TIMEOUT,
    session: requests.Session | None = None,
    service: str = "",
) -> RemoteResult:
    """POST ``payload`` to the first endpoint that answers.

    ``endpoints`` is an ordered list of ``(provider_name, url)`` -- the primary
    first, the CPU twin after it. Entries with an empty url are skipped, so a
    caller can pass a twin that is not deployed without branching.

    An endpoint is skipped without a request while its breaker is open. A
    connect failure moves to the next endpoint; a *read* failure or an HTTP
    error does not, because the host is alive and retrying elsewhere would hide
    a real server-side problem behind a silently degraded provider.

    HTTP 503 is the admission-control signal (queue full). It is retryable
    (Temporal reschedules the activity), and it is **not** a connect failure:
    the host is alive and busy. It does not open the circuit breaker and it
    does not fall through to a CPU twin. spaCy is not the answer to a full GPU.

    ``service`` names the capability for ``ai_service_telemetry`` (``ocr``, ``ner``,
    ``embeddings``). It is separate from ``provider`` because provider is *which endpoint
    answered* -- under fallback those differ, and that difference is the evidence an
    outage happened. Empty means do not record: the callers that opt in are the ones
    ``/admin/ai_status`` has a panel for.
    """
    live = [(name, url) for name, url in endpoints if url]
    if not live:
        raise RemoteUnavailable(
            "no endpoint is configured for this call; check NER_URL / the "
            "*_provider settings in hoover4.ini"
        )
    if not GPU_FALLBACK:
        live = live[:1]

    post = (session or requests).post
    attempts: list[str] = []

    for index, (provider, url) in enumerate(live):
        is_last = index == len(live) - 1
        if _BREAKER.is_open(url) and not is_last:
            attempts.append(f"{provider} ({url}): circuit open, skipped")
            _record(service, provider, 0.0, ok=False, detail="circuit open, skipped")
            continue
        started = time.monotonic()
        try:
            response = post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=(CONNECT_TIMEOUT, read_timeout),
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            # ConnectTimeout is a subclass of both ConnectionError and Timeout;
            # a ReadTimeout means the host IS alive, so it must not count
            # towards the breaker or the endpoint would be marked down for
            # being slow.
            connect_failure = not isinstance(exc, requests.ReadTimeout)
            if connect_failure and _BREAKER.record_failure(url):
                log.warning(
                    "circuit opened for %s (%s) for %.0fs after repeated "
                    "connect failures", provider, url, CIRCUIT_BREAK_SECONDS,
                )
            attempts.append(f"{provider} ({url}): {type(exc).__name__}: {exc}")
            _record(service, provider, (time.monotonic() - started) * 1000.0,
                    ok=False, detail=type(exc).__name__)
            if isinstance(exc, requests.ReadTimeout):
                break       # host is alive and slow; do not silently downgrade
            continue

        _BREAKER.record_success(url)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if response.status_code == 503:
            retry_after = response.headers.get("Retry-After", "5")
            _record(service, provider, elapsed_ms, ok=False, detail="HTTP 503")
            raise requests.HTTPError(
                f"{provider} ({url}): queue is full (Retry-After: {retry_after})",
                response=response,
            )
        try:
            response.raise_for_status()
        except Exception:
            # HTTP errors are recorded too. A capability that writes a telemetry row only
            # when it succeeds reads as idle on `/admin/ai_status` exactly while it is
            # failing, which is when someone is looking at the panel.
            _record(service, provider, elapsed_ms, ok=False,
                    detail=f"HTTP {getattr(response, 'status_code', '?')}")
            raise
        _record(service, provider, elapsed_ms, ok=True, detail=provider)
        if index > 0:
            log.warning("served by fallback provider %s (%s)", provider, url)
        return RemoteResult(data=response.json(), url=url, provider=provider)

    raise RemoteUnavailable(
        "every endpoint for this call failed:\n  " + "\n  ".join(attempts)
    )


def scanner_health(session: requests.Session | None = None) -> dict:
    """The regex entity scanner's `/health`, as a dict.

    Read once per activity, for `rule_set_version`. The scan stage compares it against
    what each batch response reports: an image swapped mid-activity would otherwise file
    the new rules' values under the old version's watermark, and nothing downstream would
    ever reconsider them.

    `/health` stays answerable at full load because the service scans off its event loop,
    so this is a cheap call even when every scan thread is busy.
    """
    base = (os.getenv("REGEX_SCANNER_URL") or "http://hoover4-regex-entity-scanner:19705").rstrip("/")
    get = (session or requests).get
    response = get(f"{base}/health", timeout=(CONNECT_TIMEOUT, 10.0))
    response.raise_for_status()
    return response.json()


def probe_embeddings(base_url: str) -> tuple[str, int]:
    """One trivial ``POST {base_url}/embeddings``; returns ``(serving_model, dims)``.

    The ini's ``embeddings_model`` / ``embeddings_dim`` are the *request*; this probe is
    the *truth*. The index builder builds Manticore ``_vectors`` tables from the probed value and
    refuses to index when it stops matching a shard's ``knn_dims``. A table's knn_dims
    is fixed at creation, so writing 384-dim vectors into a 1024-dim table is the
    failure this exists to catch early.
    """
    result = post_json(
        [("embeddings", f"{base_url.rstrip('/')}/embeddings")],
        {"input": "dimension probe"},
        read_timeout=30.0,
        service="embeddings",
    )
    data = result.data
    embedding = data["data"][0]["embedding"]
    return data.get("model", ""), len(embedding)


def record_embeddings_probe() -> tuple[str, int] | None:
    """Probe the endpoint and write the result to ``server_settings``.

    Returns ``(model, dims)``, or ``None`` when there is nothing to probe
    (``embeddings_provider = none``) or the endpoint could not be reached.

    **This must never raise.** Its callers are a worker's startup path and a CLI, and a
    worker that refuses to boot because the GPU tier is down is worse than one that boots
    and refuses the embed activity with a clear message. The same stack still has five
    other stages to run. A failed probe leaves ``server_settings`` as it was.
    """
    import os

    base_url = (os.getenv("EMBEDDINGS_URL") or "").strip()
    if not base_url:
        return None

    try:
        model, dims = probe_embeddings(base_url)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.warning(
            "embeddings probe failed (%s); server_settings left unchanged, so "
            "consumers will refuse until `main.py probe-embeddings` succeeds", exc,
        )
        return None

    if not model or not dims:
        log.warning("embeddings probe returned model=%r dims=%r; not recording", model, dims)
        return None

    from tasks.llm_catalog import set_server_setting

    set_server_setting("embeddings_serving_model", model)
    set_server_setting("embeddings_serving_dim", str(dims))
    log.info("embeddings probe: serving %s at %d dims", model, dims)
    return model, dims
