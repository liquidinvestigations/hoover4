"""Cross-encoder reranking against the GPU tier's `POST /v1/rerank`.

Same shape as `main_services/processing/tasks/remote.py`: a **2 s connect timeout** so a
dead host is noticed in seconds, and a **circuit breaker** so it is noticed once rather
than once per search. Without the breaker every query pays a connect timeout while the
GPU box is down, and the whole point of reranking — better ordering, cheaply — inverts.

Two rules the plan states explicitly and that read identically to their wrong versions:

* **A rerank timeout is an error, not a silent skip.** 25 s hard cap. If reranking is
  slow the answer is a smaller cross-encoder, not a degradation the transcript cannot
  show. The *caller* decides what to do with the error; what it must not do is pretend
  the reranked order is the RRF order.
* Latency is logged on **every** call, successful or not.

The breaker only counts *connect* failures. A model that returns a 500 is a different
problem and must stay visible on every call rather than being hidden behind a breaker.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Dead-host detection, in seconds. Never inherit the read timeout here — see AGENTS.md
#: on timeout units.
CONNECT_TIMEOUT = float(os.getenv("GPU_CONNECT_TIMEOUT_MS", "2000")) / 1000.0

#: Hard cap on one rerank call. A timeout is an error (module docstring).
READ_TIMEOUT = float(os.getenv("RERANK_TIMEOUT_SECONDS", "25"))

CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("REMOTE_CIRCUIT_FAILURES", "3"))
CIRCUIT_BREAK_SECONDS = float(os.getenv("GPU_CIRCUIT_BREAK_SECONDS", "60"))

#: The cross-encoder truncates anyway; sending 20 kB of page text per candidate just
#: costs transfer time. A title plus a snippet is what the model scores on.
DOC_CHARS = int(os.getenv("RERANK_DOC_CHARS", "1200"))


class RerankUnavailable(RuntimeError):
    """The rerank endpoint is unset, breaker-open, or did not answer in time."""


@dataclass
class _Circuit:
    consecutive_failures: int = 0
    open_until: float = 0.0


class _Breaker:
    """Per-endpoint circuit state, shared across this process's threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._circuits: dict[str, _Circuit] = {}

    def is_open(self, url: str) -> bool:
        with self._lock:
            c = self._circuits.get(url)
            return bool(c and c.open_until > time.monotonic())

    def record_failure(self, url: str) -> bool:
        """Count a connect failure; returns True if that tripped the breaker."""
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

    def state(self) -> dict[str, dict]:
        """Snapshot for a `/health` endpoint."""
        now = time.monotonic()
        with self._lock:
            return {
                url: {
                    "consecutive_failures": c.consecutive_failures,
                    "open_for_seconds": round(max(0.0, c.open_until - now), 1),
                }
                for url, c in self._circuits.items()
            }


_BREAKER = _Breaker()


def endpoint() -> str:
    """Base URL of the rerank service, or empty when none is configured.

    `RERANK_URL` is rendered by deploy.py and already carries the `/v1` suffix (it is the
    same base URL as `EMBEDDINGS_URL`, because one server serves both).
    """
    return (os.getenv("RERANK_URL") or "").rstrip("/")


def available() -> bool:
    url = endpoint()
    return bool(url) and not _BREAKER.is_open(url)


def breaker_state() -> dict[str, dict]:
    return _BREAKER.state()


@dataclass
class RerankScore:
    """One document's place in the reranked order."""

    index: int
    score: float


def rerank(query: str, documents: list[str], model: str | None = None) -> tuple[list[RerankScore], float]:
    """Score `documents` against `query`, best first.

    Returns `(scores, elapsed_ms)`. `scores[i].index` points back into `documents`.
    Raises :class:`RerankUnavailable` on anything that stops a real ranking being
    produced — an empty list would be indistinguishable from "everything scored zero".
    """
    import requests

    url = endpoint()
    if not url:
        raise RerankUnavailable("RERANK_URL is not configured")
    if _BREAKER.is_open(url):
        raise RerankUnavailable(f"rerank endpoint {url} circuit is open")
    if not documents:
        return [], 0.0

    payload = {
        "query": query,
        "documents": [(d or "")[:DOC_CHARS] for d in documents],
    }
    if model:
        payload["model"] = model

    started = time.monotonic()
    try:
        response = requests.post(
            f"{url}/rerank",
            json=payload,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.exceptions.ConnectTimeout as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        if _BREAKER.record_failure(url):
            log.warning("rerank circuit opened for %s for %.0fs", url, CIRCUIT_BREAK_SECONDS)
        log.warning("rerank connect failed after %.0fms: %s", elapsed, exc)
        raise RerankUnavailable(f"rerank endpoint {url} unreachable: {exc}") from exc
    except requests.exceptions.ConnectionError as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        if _BREAKER.record_failure(url):
            log.warning("rerank circuit opened for %s for %.0fs", url, CIRCUIT_BREAK_SECONDS)
        log.warning("rerank connection error after %.0fms: %s", elapsed, exc)
        raise RerankUnavailable(f"rerank endpoint {url} unreachable: {exc}") from exc
    except requests.exceptions.ReadTimeout as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        # Deliberately NOT a breaker failure: the host answered, it was just slow, and
        # skipping it for a minute would hide a model that needs replacing.
        log.warning("rerank timed out after %.0fms (cap %.0fs)", elapsed, READ_TIMEOUT)
        raise RerankUnavailable(f"rerank timed out after {READ_TIMEOUT:g}s") from exc

    elapsed_ms = (time.monotonic() - started) * 1000.0
    if response.status_code != 200:
        log.warning(
            "rerank returned %s in %.0fms: %s",
            response.status_code, elapsed_ms, response.text[:300],
        )
        raise RerankUnavailable(f"rerank returned {response.status_code}")

    _BREAKER.record_success(url)
    try:
        data = response.json().get("data") or []
    except ValueError as exc:
        raise RerankUnavailable(f"rerank returned unparseable JSON: {exc}") from exc

    scores = [
        RerankScore(index=int(item["index"]), score=float(item.get("relevance_score", 0.0)))
        for item in data
        if isinstance(item, dict) and "index" in item
    ]
    # The server already sorts, but relying on that couples this client to its
    # implementation; sorting here costs nothing and makes the contract local.
    scores.sort(key=lambda s: s.score, reverse=True)
    log.info("rerank scored %d documents in %.0fms", len(scores), elapsed_ms)
    return scores, elapsed_ms
