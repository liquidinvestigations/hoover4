"""The query side of the embedding contract: the model-keyed prefix, and the client.

**The prefix convention lives in exactly one function per runtime**.
:func:`embedding_input` here for the search side, and
`main_services/processing/tasks/P5_chunk_embed/embedding_prefix.py` for the indexing
side. The duplication is deliberate (same pattern as `extracted_by` in
`tasks/text_sources.py` vs `website/common/src/document_sources.rs`): the processing
image and the agents images share no package, so neither runtime may depend on the other
being right. Mixing the two directions up (embedding a passage with the query prefix)
degrades retrieval silently and nothing will ever alert you, which is why there is one
function and why it REFUSES an unknown model instead of guessing a convention.

The function keys off the model id recorded in `server_settings`
(`embeddings_serving_model`, written by `main.py probe-embeddings`), which is the probed
truth about what the server serves rather than the configured value.

The client mirrors `rerank.py`'s rules: a 2 s connect timeout so a dead GPU host is
noticed in seconds, a finite read timeout so a slow one cannot wedge a search, and every
call's latency logged.
"""

from __future__ import annotations

import logging
import os
import time

from agent_common import telemetry

log = logging.getLogger(__name__)

#: Dead-host detection, in seconds. Never inherit the read timeout here.
CONNECT_TIMEOUT = float(os.getenv("GPU_CONNECT_TIMEOUT_MS", "2000")) / 1000.0

#: One embed call is a single short text; anything past this is a stuck server.
READ_TIMEOUT = float(os.getenv("EMBED_TIMEOUT_SECONDS", "25"))

#: The task description wrapped around a QUERY when the serving model is an instruct
#: model (see embedding_input). Only instruct models want one; sending it to a plain
#: e5 would change every embedding for no reason.
QUERY_TASK = "Given a search query, retrieve relevant passages from a document collection"


class EmbeddingUnavailable(RuntimeError):
    """The embeddings endpoint is unset or did not answer a query embedding."""


def endpoint() -> str:
    """Base URL of the embeddings service (carries the `/v1` suffix), or empty."""
    return (os.getenv("EMBEDDINGS_URL") or "").rstrip("/")


def embedding_input(model_id: str, kind: str, text: str) -> tuple[str, str | None]:
    """Turn `text` into what the embeddings endpoint should receive.

    `kind` is `"passage"` (a stored chunk, at index time) or `"query"` (a search query,
    at search time). Returns `(text_to_send, task_description)`; `task_description` is
    only set for instruct models, whose query template the SERVER applies
    (`/v1/embeddings`' `task_description` parameter).

    * `intfloat/multilingual-e5-*` and the other non-instruct e5 models:
      `passage: ` / `query: ` prepended by the caller.
    * `*-e5-*-instruct`: passages go bare; queries go bare plus a task description the
      server wraps as `Instruct: {task}\\nQuery: {text}`.
    * Anything else raises, a model whose convention we do not know gets no vectors
      rather than wrong ones.
    """
    name = (model_id or "").lower()
    if kind not in ("passage", "query"):
        raise ValueError(f"kind must be 'passage' or 'query', got {kind!r}")
    if "e5" not in name:
        raise ValueError(
            f"no embedding prefix convention is known for model {model_id!r}; "
            "add it to embedding_input in BOTH runtimes (see module docstring)"
        )
    if "instruct" in name:
        if kind == "query":
            return text, QUERY_TASK
        return text, None
    prefix = "passage: " if kind == "passage" else "query: "
    return prefix + text, None


def embed_query(query: str, model_id: str) -> list[float]:
    """Embed one search query with the serving model's query convention.

    Raises :class:`EmbeddingUnavailable` on anything that stops a real vector being
    produced. The caller falls back to keyword-only search and says so, rather than
    silently returning a keyword result set it presents as fused.
    """
    import requests

    url = endpoint()
    if not url:
        raise EmbeddingUnavailable("EMBEDDINGS_URL is not configured")

    text, task_description = embedding_input(model_id, "query", query)
    payload: dict = {"input": text}
    if task_description:
        payload["task_description"] = task_description

    started = time.monotonic()
    try:
        response = requests.post(
            f"{url}/embeddings",
            json=payload,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.exceptions.RequestException as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        log.warning("embed_query failed after %.0fms: %s", elapsed, exc)
        telemetry.record_async(
            "embeddings", provider=url, latency_ms=elapsed, ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        )
        raise EmbeddingUnavailable(f"embeddings endpoint {url} failed: {exc}") from exc

    elapsed_ms = (time.monotonic() - started) * 1000.0
    # Recorded on every outcome, not only the good one. `/admin/ai_status` reads this
    # table; a capability that writes rows only when it works renders as "no traffic"
    # while it is failing, which is exactly when the panel is being looked at.
    telemetry.record_async(
        "embeddings", provider=url, latency_ms=elapsed_ms,
        ok=response.status_code == 200,
        detail=model_id if response.status_code == 200 else f"HTTP {response.status_code}",
    )
    if response.status_code != 200:
        log.warning("embeddings returned %s in %.0fms", response.status_code, elapsed_ms)
        raise EmbeddingUnavailable(f"embeddings returned {response.status_code}")

    try:
        data = response.json()
        embedding = [float(v) for v in data["data"][0]["embedding"]]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise EmbeddingUnavailable(f"embeddings returned unparseable JSON: {exc}") from exc

    served_model = data.get("model") or ""
    if served_model and model_id and served_model != model_id:
        # The probe is stale: the server serves a different model than server_settings
        # records, so the prefix convention just applied may be the wrong one. Refuse
        # rather than search with a vector from an unknown convention.
        raise EmbeddingUnavailable(
            f"serving model {served_model!r} != probed {model_id!r}; "
            "run `main.py probe-embeddings`"
        )
    log.info("embed_query embedded %d chars in %.0fms", len(query), elapsed_ms)
    return embedding
