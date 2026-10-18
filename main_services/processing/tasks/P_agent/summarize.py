"""Title and one-line summary for a conversation, from the LLM's own words.

Runs at the end of the first turn of a conversation. The title is how a person finds a
conversation in a list a week later, and the first few words of a question are routinely
a bad name for what the conversation turned into.

**Nothing here may raise into a turn.** By the time it runs the answer is already written
and read; a failed summarisation must cost the conversation a good title, never an answer.
Every entry point returns a result object instead of throwing, and the caller writes the
provisional title's fallback by doing nothing.

Deliberately not through the agent: that would drag the whole MCP tool surface into a
call that summarises two paragraphs.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from tasks.P_agent.model_timeouts import TIMEOUTS

log = logging.getLogger(__name__)

#: Budget for a *reasoning* model, not for two lines of output. At 120 a configured
#: provider spent the entire allowance thinking, came back `finish_reason: "length"` with
#: its scratchpad mirrored into `content`, and the sidebar filled up with titles reading
#: "We need to output exactly two lines: line1 short title max 8 words...". The reply is
#: still two lines; the thinking in front of it is what needs the room.
MAX_TOKENS = 512

#: Ask the model to leave its thinking mode off. Naming a conversation is not a reasoning problem,
#: and a reasoning model given one spends its whole token budget on the thought and hits
#: `length` with nothing usable in `content`, measured at 512 and again at 1 536 tokens
#: against the model this deployment runs on. With thinking off the same call answers in
#: about a second and its budget is generous.
#:
#: Provider-specific, so it is sent as a hint and dropped on a refusal rather than
#: assumed: a provider that has never heard of it rejects the whole request, and a
#: summariser that fails on every call is invisible in exactly the way the telemetry row
#: exists to prevent.
NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

#: A summariser that has not answered in this long has cost the conversation nothing but
#: a title, so it is given far less time than the turn itself. The read timeout comes from
#: `title_request_timeout_seconds` (30 s when the key is empty). It is a fixed value and does
#: not follow the model's measured speed, because the title activity holds a `chat-queue`
#: slot that every turn needs.
REQUEST_TIMEOUT = (10, TIMEOUTS.title_request_seconds)


def _send_temperature() -> bool:
    """`LLM_SEND_TEMPERATURE`. Empty or unset is true.

    `deploy.py` renders it from the active provider's `send_temperature` key. A provider that
    rejects `temperature` gets a request without it. **Mirrored in
    `main_services/agents/research_agent/research_agent/model_params.py`**, which reads the
    same variable with the same rule for the agent's own requests.
    """
    raw = (os.getenv("LLM_SEND_TEMPERATURE") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")

#: Labels the model prefixes its lines with however firmly the prompt asks for bare ones.
_LABELS = ("title", "summary", "line 1", "line 2")

SYSTEM_PROMPT = (
    "You write short titles and summaries for an investigative-search chat. No markdown."
)


@dataclass
class TitleSummary:
    """A usable title and summary, or the reason there is none.

    `title` empty means the caller keeps the provisional title. `error` is what the
    telemetry row records, and it is set on a discarded answer as well as on a failed
    call: a model that hits its token limit on every request is invisible in exactly the
    same way as one that was never configured.
    """

    title: str = ""
    summary: str = ""
    error: str = ""
    model: str = ""
    latency_ms: int = 0
    #: From the `usage` object of the reply. 0 when the call got no reply body.
    prompt_tokens: int = 0
    completion_tokens: int = 0


def usage_tokens(reply) -> dict[str, int]:
    """The prompt and completion tokens of an OpenAI-style reply. 0 for a missing field."""
    usage = reply.get("usage") if isinstance(reply, dict) else None
    if not isinstance(usage, dict):
        usage = {}

    def count(key: str) -> int:
        try:
            return max(int(usage.get(key) or 0), 0)
        except (TypeError, ValueError):
            return 0

    return {"prompt_tokens": count("prompt_tokens"),
            "completion_tokens": count("completion_tokens")}


def strip_think_blocks(text: str) -> str:
    """Drop `<think>...</think>` blocks some local models emit around their answer."""
    out = []
    rest = text
    while True:
        start = rest.find("<think>")
        if start < 0:
            break
        out.append(rest[:start])
        end = rest.find("</think>", start)
        if end < 0:
            rest = ""
            break
        rest = rest[end + len("</think>"):]
    out.append(rest)
    return "".join(out)


def strip_label(line: str) -> str:
    """Drop a `Title:` / `**Summary:**` style label the model prefixed to a line.

    The prompt asks for two bare lines and the model labels them anyway. Labelling is the
    model being helpful, but it lands verbatim in the sidebar, so it is stripped here
    rather than by escalating the prompt -- prompt wording is not a reliable parser.

    The emphasis can sit outside the colon (`**Title:**`) or inside it (`**Title**:`), so
    the label is identified by stripping decoration from everything before the first colon
    rather than by matching a fixed prefix. A colon in ordinary prose survives.
    """
    trimmed = line.strip()
    head, sep, tail = trimmed.partition(":")
    if sep:
        bare = "".join(c for c in head if c not in "*#_").strip().lower()
        if bare in _LABELS:
            return tail.strip().strip("*").strip()
    return trimmed.lstrip("#").strip().strip("*").strip()


def parse_reply(raw: str) -> tuple[str, str]:
    """Split a model reply into `(title, summary)`; an empty title means unusable."""
    lines = [ln for ln in (l.strip() for l in strip_think_blocks(raw).splitlines()) if ln]
    if not lines:
        return "", ""
    title = strip_label(lines[0])[:80]
    if not title:
        return "", ""
    summary = " ".join(strip_label(ln) for ln in lines[1:])[:400]
    return title, summary or title


def _api_key() -> str:
    key = (os.getenv("LLM_API_KEY") or "").strip()
    if key:
        return key
    # deploy.py bind-mounts the active provider's key file; the env var names the
    # in-container path, never the value.
    path = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if path:
        try:
            return open(path).read().strip()
        except OSError:
            log.warning("could not read LLM_API_KEY_FILE at %s", path)
    return ""


def _model() -> str:
    """The short-call model of `hoover4.ini` (`LLM_MODEL`), or nothing.

    Nothing disables the summariser: the provisional title is a correct answer to "what
    is this conversation called", and inventing a model id here would send the call to
    whatever the endpoint defaults to.
    """
    from tasks.llm_endpoints import short_model

    return short_model()


def _post(endpoint, body: dict, timeout=None):
    """One completion request to `endpoint` (`tasks.llm_endpoints.Endpoint`). Raises only
    what the caller already catches. `timeout` is a `(connect, read)` pair in seconds, and
    `REQUEST_TIMEOUT` when it is None."""
    import requests

    return requests.post(
        f"{endpoint.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {endpoint.api_key}"},
        json=body,
        timeout=timeout or REQUEST_TIMEOUT,
    )


class TransportFailure(RuntimeError):
    """A model request that ended before a usable reply, for a reason that a second request
    can change: a connection error, a timeout, or the HTTP status 408, 429 or 5xx. An
    activity raises it, so Temporal sends the request again (`tasks/Readme.md`, retries)."""


def retryable_status(code: int) -> bool:
    """Whether an HTTP status of a model request can change in a second request."""
    return code in (408, 429) or code >= 500


def post_or_raise(endpoint, body: dict, timeout=None):
    """`_post`, with a transport failure raised as `TransportFailure`. Any other response,
    a 4xx refusal included, is returned."""
    import requests

    try:
        response = _post(endpoint, body, timeout)
    except requests.RequestException as exc:
        raise TransportFailure(f"{type(exc).__name__}: {exc}"[:500]) from exc
    if retryable_status(response.status_code):
        raise TransportFailure(f"HTTP {response.status_code}: {response.text[:200]}")
    return response


def record_call(username: str, session_id: str, kind: str, model: str, usage: dict,
                latency_ms: int, ok: bool, error: str, reply_bytes: int) -> None:
    """One `llm_call_events` row of a short model call. A failed write is logged."""
    from datetime import datetime, timezone

    from database.clickhouse import get_global_client
    from tasks.llm_endpoints import endpoint_for

    try:
        with get_global_client() as client:
            client.insert(
                "llm_call_events",
                [[datetime.now(timezone.utc).replace(tzinfo=None), username, session_id, kind,
                  endpoint_for(model).label, model, int(usage.get("prompt_tokens") or 0),
                  int(usage.get("completion_tokens") or 0), 0, reply_bytes, latency_ms,
                  1 if ok else 0, error[:500]]],
                column_names=["event_time", "username", "session_id", "kind", "provider",
                              "model_id", "prompt_tokens", "completion_tokens",
                              "reasoning_tokens", "reply_bytes", "latency_ms", "ok", "error"],
            )
    except Exception:  # noqa: BLE001 - telemetry never costs the call
        log.warning("could not record the %s call", kind, exc_info=True)


@dataclass
class Completion:
    """The content of one short completion, or the reason there is none.

    `text` is the raw content, with the `<think>` reasoning blocks still in it. `error` is
    set on a failed call and on a discarded answer, so the telemetry row of the caller
    records both.
    """

    text: str = ""
    error: str = ""
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


def complete(system: str, prompt: str, max_tokens: int) -> Completion:
    """One short call of the summarisation model, with the conventions of the title call.

    The call asks the model to leave thinking off (`NO_THINKING`) and sends the request again
    without that hint on a 4xx. It sends a temperature only when `_send_temperature` allows
    it. A reply cut at `max_tokens`, an empty reply and a reply that holds only the
    reasoning are failures. Never raises.
    """
    model = _model()
    if not model:
        return Completion(error="no summarisation model configured")

    from tasks.llm_endpoints import endpoint_for

    endpoint = endpoint_for(model)
    if not endpoint.base_url:
        return Completion(model=model, error="no LLM_BASE_URL configured")
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    if _send_temperature():
        body["temperature"] = 0.2
    try:
        response = _post(endpoint, {**body, **NO_THINKING})
        if 400 <= response.status_code < 500:
            # The hint is the likeliest thing a provider objects to, so it is the first
            # thing dropped. A second refusal is a real one and is reported.
            response = _post(endpoint, body)
    except Exception as exc:  # noqa: BLE001 - a dead endpoint costs a title, not a turn
        return Completion(model=model, latency_ms=elapsed(), error=str(exc)[:500])

    if response.status_code >= 400:
        return Completion(
            model=model,
            latency_ms=elapsed(),
            error=f"{response.status_code}: {response.text[:200]}",
        )

    # From here on the call has been BILLED. Every unusable answer below is a successful
    # request whose reply we chose not to use, and each one still records a row: a model
    # that hits its token limit every time must not look like one that never ran.
    try:
        reply = response.json()
        choice = reply["choices"][0]
    except Exception as exc:  # noqa: BLE001
        return Completion(model=model, latency_ms=elapsed(), error=f"unparseable body: {exc}")
    tokens = usage_tokens(reply)

    if choice.get("finish_reason") == "length":
        # A completion cut off at max_tokens is not an answer. The user's own words are
        # always better than half a sentence -- or than the model's scratchpad.
        return Completion(model=model, latency_ms=elapsed(), **tokens, error="hit max_tokens")

    message = choice.get("message") or {}
    raw = (message.get("content") or "").strip()
    if not raw:
        return Completion(model=model, latency_ms=elapsed(), **tokens, error="empty content")

    # Reasoning is never the answer. A model that mirrors its scratchpad into `content`
    # has told us nothing usable.
    reasoning = (message.get("reasoning_content") or "").strip()
    if reasoning and raw == reasoning:
        return Completion(model=model, latency_ms=elapsed(), **tokens,
                          error="returned only its reasoning")
    return Completion(text=raw, model=model, latency_ms=elapsed(), **tokens)


def title_and_summary(user_message: str, answer: str) -> TitleSummary:
    """Ask the LLM for a title and a summary of one turn. Never raises."""
    prompt = (
        "Given this chat turn, reply with exactly two lines:\n"
        "Line 1: a short title (max 8 words, no quotes).\n"
        "Line 2: a one-or-two sentence summary of what was asked and answered.\n\n"
        f"User: {user_message}\n\nAssistant: {answer}"
    )
    result = complete(SYSTEM_PROMPT, prompt, MAX_TOKENS)
    meta = dict(model=result.model, latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens)
    if result.error:
        return TitleSummary(**meta, error=result.error)
    title, summary = parse_reply(result.text)
    if not title:
        return TitleSummary(**meta, error="no usable lines")
    return TitleSummary(title=title, summary=summary, **meta)
