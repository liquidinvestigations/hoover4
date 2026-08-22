"""Title and one-line summary for a conversation, from the LLM's own words.

Runs at the end of the first turn of a conversation. The title is how a person finds a
conversation in a list a week later, and the first few words of a question are routinely
a bad name for what the conversation turned into.

**Nothing here may raise into a turn.** By the time it runs the answer is already written
and read; a failed summarisation must cost the conversation a good title, never an answer.
Every entry point returns a result object instead of throwing, and the caller writes the
provisional title's fallback by simply doing nothing.

Deliberately not through the agent: that would drag the whole MCP tool surface into a
call that summarises two paragraphs.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Budget for a *reasoning* model, not for two lines of output. At 120 the configured
#: provider spent the entire allowance thinking, came back `finish_reason: "length"` with
#: its scratchpad mirrored into `content`, and the sidebar filled up with titles reading
#: "We need to output exactly two lines: line1 short title max 8 words...". The reply is
#: still two lines; the thinking in front of it is what needs the room.
MAX_TOKENS = 512

#: A summariser that has not answered in this long has cost the conversation nothing but
#: a title, so it is given far less rope than the turn itself.
REQUEST_TIMEOUT = (10, 30)

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
    """The configured summarisation model, or the chat model, or nothing.

    Nothing disables the summariser: the provisional title is a correct answer to "what
    is this conversation called", and inventing a model id here would send the call to
    whatever the endpoint defaults to.
    """
    try:
        from database.clickhouse import get_server_setting

        from tasks.llm_catalog import SETTING_SUMMARIZATION_MODEL

        configured = (get_server_setting(SETTING_SUMMARIZATION_MODEL) or "").strip()
        if configured:
            return configured
    except Exception:  # noqa: BLE001 - a settings read must not cost the turn anything
        log.warning("[P_agent] could not read the summarisation model", exc_info=True)
    return (os.getenv("LLM_MODEL") or "").strip()


def title_and_summary(user_message: str, answer: str) -> TitleSummary:
    """Ask the LLM for a title and a summary of one turn. Never raises."""
    import requests

    model = _model()
    if not model:
        return TitleSummary(error="no summarisation model configured")

    base_url = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return TitleSummary(model=model, error="no LLM_BASE_URL configured")

    prompt = (
        "Given this chat turn, reply with exactly two lines:\n"
        "Line 1: a short title (max 8 words, no quotes).\n"
        "Line 2: a one-or-two sentence summary of what was asked and answered.\n\n"
        f"User: {user_message}\n\nAssistant: {answer}"
    )
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {_api_key()}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": MAX_TOKENS,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - a dead endpoint costs a title, not a turn
        return TitleSummary(model=model, latency_ms=elapsed(), error=str(exc)[:500])

    if response.status_code >= 400:
        return TitleSummary(
            model=model,
            latency_ms=elapsed(),
            error=f"{response.status_code}: {response.text[:200]}",
        )

    # From here on the call has been BILLED. Every unusable answer below is a successful
    # request whose reply we chose not to use, and each one still records a row: a model
    # that hits its token limit every time must not look like one that never ran.
    try:
        choice = response.json()["choices"][0]
    except Exception as exc:  # noqa: BLE001
        return TitleSummary(model=model, latency_ms=elapsed(), error=f"unparseable body: {exc}")

    if choice.get("finish_reason") == "length":
        # A completion cut off at max_tokens is not a title. The user's own words are
        # always better than half a sentence -- or than the model's scratchpad.
        return TitleSummary(model=model, latency_ms=elapsed(), error="hit max_tokens")

    message = choice.get("message") or {}
    raw = (message.get("content") or "").strip()
    if not raw:
        return TitleSummary(model=model, latency_ms=elapsed(), error="empty content")

    # Reasoning is never the answer. A model that mirrors its scratchpad into `content`
    # has told us nothing usable.
    reasoning = (message.get("reasoning_content") or "").strip()
    if reasoning and raw == reasoning:
        return TitleSummary(model=model, latency_ms=elapsed(), error="returned only its reasoning")

    title, summary = parse_reply(raw)
    if not title:
        return TitleSummary(model=model, latency_ms=elapsed(), error="no usable lines")
    return TitleSummary(title=title, summary=summary, model=model, latency_ms=elapsed())
