"""Outbound HTTP from activities: bounded timeouts, CPU fallback, circuit breaker.

Why this module exists
----------------------
On 2026-08-06 an ``extract_entities_for_hashes`` activity stalled with no load
on the system at all. Two defects stacked:

1. a routing defect (fixed in Part 1, ``8ab0927``): a rootless podman container
   cannot route to its host's own LAN address, so the GPU endpoint was simply
   unreachable and hung rather than refusing;
2. a timeout defect (this module): ``extract_ner_from_text.py`` passed
   ``timeout=3000`` to ``requests.post``. **requests measures timeouts in
   seconds**, so that is a 50-minute budget applied to *both* connect and read,
   for a single NER batch. The only reason it failed in ~2 minutes rather than
   50 was the kernel giving up on SYN retries first.

And the config contract was not honoured. ``deploy.py`` renders
``GPU_CONNECT_TIMEOUT_MS``, ``GPU_FALLBACK`` and ``GPU_CIRCUIT_BREAK_SECONDS``
into the worker's environment -- the fallback behaviour decided in Part 1 3.1 --
and nothing read any of them. A dead GPU host stalled the pipeline instead of
degrading it, which is precisely what those three settings exist to prevent.

The contract implemented here
-----------------------------
====================== ======================================================
``GPU_CONNECT_TIMEOUT_MS``  connect timeout on every ai-tier call (default 2000)
``GPU_FALLBACK``            on connect failure, retry against the CPU twin
``GPU_CIRCUIT_BREAK_SECONDS`` after N consecutive connect failures, skip the GPU
                            endpoint entirely for this long
====================== ======================================================

The ``(connect, read)`` two-tuple is the whole point: the failure modes are
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

    Raised fast and with the URLs named. Fast and honest beats slow and
    mysterious: a plan that fails in two seconds with "GPU NER unreachable at
    <url> and no CPU twin is enabled" is debuggable, one that stalls for fifty
    minutes is not.
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
) -> RemoteResult:
    """POST ``payload`` to the first endpoint that answers.

    ``endpoints`` is an ordered list of ``(provider_name, url)`` -- the primary
    first, the CPU twin after it. Entries with an empty url are skipped, so a
    caller can pass a twin that Part 2 has not built yet without branching.

    An endpoint is skipped without a request while its breaker is open. A
    connect failure moves to the next endpoint; a *read* failure or an HTTP
    error does not, because the host is alive and retrying elsewhere would hide
    a real server-side problem behind a silently degraded provider.
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
            continue
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
            if isinstance(exc, requests.ReadTimeout):
                break       # host is alive and slow; do not silently downgrade
            continue

        _BREAKER.record_success(url)
        response.raise_for_status()
        if index > 0:
            log.warning("served by fallback provider %s (%s)", provider, url)
        return RemoteResult(data=response.json(), url=url, provider=provider)

    raise RemoteUnavailable(
        "every endpoint for this call failed:\n  " + "\n  ".join(attempts)
    )
