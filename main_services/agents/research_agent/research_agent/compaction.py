"""Context compaction, layer one: eviction of old tool results.

A tool-using turn grows because every result the model collected stays in the list handed
back to it on the next call. The answer needs the reasoning those results produced, not
the fifty kilobytes of snippets they arrived in. Eviction replaces the content of the
older tool results with a placeholder while the assistant messages that requested them
keep their tool calls untouched, so the model still sees that it searched and what it
searched for.

Three properties hold and each one is load-bearing.

**Nothing is edited.** This transformation is applied to the list on its way to the model
and never written back into the graph state or into `chat_messages`. The transcript a user
scrolls back through holds every result in full, which is the only reason a compaction
error can be debugged afterwards.

**A tool result is shortened, not removed.** An OpenAI-shaped request carrying an
assistant message whose `tool_calls` have no matching tool result is rejected outright, so
dropping the message would end the turn in a provider error rather than a shorter context.
The placeholder is what "dropped" has to mean on this wire format.

**An unknown context window never fires the trigger.** `llm_models.context_window` is 0
when the provider never stated one, and a threshold is a fraction of that number. Guessing
a denominator is how a conversation silently loses its evidence, so 0 means no compaction
is evaluated at all.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import httpx
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

log = logging.getLogger(__name__)

GLOBAL_DB = os.getenv("CLICKHOUSE_DATABASE", "Hoover4_Processing")

#: Fraction of the model's context window at which compaction fires.
#:
#: 0.6 is the specified figure. It is configuration rather than a constant so the gap
#: between it and the published 70-75% practice is a setting to tune with evidence, and so
#: a demonstration can lower it without shipping the lower number.
#:
#: **It does not fire on this stack's ordinary traffic.** The widest turn measured here --
#: the full research profile, sixteen tool calls, three web pages read and cited -- peaked
#: at a tenth of the window. That is a property of the model's window and of how much a
#: turn currently collects, both of which move: a larger corpus, a model with a smaller
#: window, or replaying tool results across turns all bring this into range. Lowering the
#: fraction to make it fire today would discard results the model still needs in exchange
#: for nothing.
DEFAULT_COMPACTION_FRACTION = 0.6

#: How many of the most recent tool results survive a compaction intact. The model is
#: usually still working with what it just read, and evicting the result of the call it
#: made moments ago forces an immediate re-read that costs more than it saved.
DEFAULT_KEEP_RECENT = 3

#: What an evicted tool result says in the model's place. It names the transcript as the
#: place the content still exists, because the alternative reading -- that the tool
#: returned nothing -- would make the model report a gap that is not there.
EVICTION_PLACEHOLDER = (
    "[This tool result was evicted to reclaim context. It is unchanged in the "
    "conversation transcript. The call that produced it is shown above. Re-run the tool "
    "if you need its content again.]"
)

#: A tool result shorter than the placeholder is left alone, because replacing it makes
#: the context bigger. Measured on the first driven run: a `list_collections` result is 91
#: characters and evicting it added 36. Most tool results here are kilobytes and this
#: guard never sees them -- it exists for the handful that are one line.
MIN_EVICTABLE_CHARS = len(EVICTION_PLACEHOLDER)

#: How long a context window read from the catalog is trusted before it is read again.
#: The catalog is refreshed on a schedule and a model's window does not change between
#: refreshes, so this only bounds how long a stale denominator can survive a re-list.
_WINDOW_TTL_SECONDS = 300

_window_cache: dict[str, tuple[float, int]] = {}


def compaction_fraction() -> float:
    """The configured trigger, as a fraction of the context window.

    Out-of-range values disable compaction rather than clamping into it: a fraction above
    1 cannot fire anyway, and a fraction at or below 0 would compact every call, which is
    a misconfiguration that must not silently look like a feature.
    """
    raw = (os.getenv("AGENT_COMPACTION_FRACTION") or "").strip()
    if not raw:
        return DEFAULT_COMPACTION_FRACTION
    try:
        value = float(raw)
    except ValueError:
        log.warning("AGENT_COMPACTION_FRACTION=%r is not a number, compaction is off", raw)
        return 0.0
    if not 0.0 < value <= 1.0:
        log.warning("AGENT_COMPACTION_FRACTION=%r is out of range, compaction is off", raw)
        return 0.0
    return value


def keep_recent() -> int:
    try:
        return max(0, int(os.getenv("AGENT_COMPACTION_KEEP_RECENT") or DEFAULT_KEEP_RECENT))
    except ValueError:
        return DEFAULT_KEEP_RECENT


def _clickhouse_url() -> str:
    return (os.getenv("CLICKHOUSE_URL") or "").rstrip("/")


def _auth() -> tuple[str, str]:
    return (os.getenv("CLICKHOUSE_USER") or "hoover4", os.getenv("CLICKHOUSE_PASSWORD") or "")


def context_window(model_id: str, *, now: Optional[float] = None) -> int:
    """The model's context window from the catalog, or 0 when nothing states one.

    Read from `llm_models` rather than from the provider directly so that the number the
    trigger divides by is the same number the transcript footer shows the user. Two
    denominators that disagree would make a compaction the user cannot account for.

    Every failure -- no ClickHouse, no row, an unparseable answer -- returns 0, and 0
    means the trigger cannot be evaluated. Never substitute a default here.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return 0
    clock = time.monotonic() if now is None else now
    cached = _window_cache.get(model_id)
    if cached and cached[0] > clock:
        return cached[1]
    base = _clickhouse_url()
    if not base:
        return 0
    window = 0
    try:
        with httpx.Client(timeout=(2.0, 5.0), auth=_auth()) as client:
            r = client.get(
                f"{base}/",
                params={
                    "database": GLOBAL_DB,
                    "query": (
                        "SELECT max(context_window) FROM llm_models FINAL "
                        "WHERE model_id = {m:String} AND is_deleted = 0 FORMAT TSV"
                    ),
                    "param_m": model_id,
                },
            )
            if r.status_code < 300:
                window = int((r.text or "0").strip() or 0)
    except Exception as exc:  # noqa: BLE001 -- an unknown window is a valid answer
        log.warning("could not read the context window for %s: %s", model_id, exc)
        return 0
    _window_cache[model_id] = (clock + _WINDOW_TTL_SECONDS, window)
    return window


def threshold_tokens(window: int, fraction: Optional[float] = None) -> int:
    """The token count at or above which compaction fires. 0 means it never does."""
    if window <= 0:
        return 0
    frac = compaction_fraction() if fraction is None else fraction
    if not 0.0 < frac <= 1.0:
        return 0
    return int(window * frac)


def last_billed_tokens(messages: Sequence[BaseMessage]) -> int:
    """What the provider billed for the most recent model call in this list.

    The last assistant message carries the provider's own `usage_metadata`, which is the
    only token count in the system that was not estimated by a tokeniser that is not the
    model's. Prompt plus completion, because that is what the peak the trigger is sized
    against means everywhere else.

    0 when no assistant message reports usage -- before the first call of a run, or from a
    provider that reports none. The trigger reads that as "not known to be over".
    """
    for message in reversed(list(messages)):
        if not isinstance(message, AIMessage):
            continue
        meta = getattr(message, "usage_metadata", None)
        if isinstance(meta, dict) and meta:
            prompt = int(meta.get("input_tokens") or 0)
            completion = int(meta.get("output_tokens") or 0)
            if prompt:
                return prompt + completion
        resp = getattr(message, "response_metadata", None) or {}
        usage = resp.get("token_usage") or resp.get("usage") or {} if isinstance(resp, dict) else {}
        if isinstance(usage, dict) and usage:
            prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            if prompt:
                return prompt + completion
    return 0


def _content_length(message: BaseMessage) -> int:
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str):
        content = str(content)
    return len(content)


def summarise_list(messages: Sequence[BaseMessage]) -> str:
    """One line per message: what it is, what it called, how long its content is.

    Logged either side of an applied compaction, because the question anyone debugging a
    compaction asks first is what the model could still see. A compaction is rare by
    construction, so this costs nothing until the one moment it is the only record of what
    happened.
    """
    lines = []
    for i, message in enumerate(messages):
        kind = type(message).__name__
        detail = ""
        if isinstance(message, ToolMessage):
            detail = f" result of {getattr(message, 'name', '') or '?'}"
            if message.content == EVICTION_PLACEHOLDER:
                detail += " EVICTED"
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            detail = " calls " + ", ".join(str(c.get("name") or "?") for c in calls)
        lines.append(f"  {i:3d} {kind}{detail} [{_content_length(message)} chars]")
    return "\n".join(lines)


@dataclass
class EvictionReport:
    """What one eviction did, for the trail and for the tests."""

    compaction_id: str = ""
    tokens_before: int = 0
    tokens_after: int = 0
    context_window: int = 0
    threshold_tokens: int = 0
    messages_before: int = 0
    messages_after: int = 0
    evicted_count: int = 0
    kept_count: int = 0
    chars_before: int = 0
    chars_after: int = 0
    evicted: list[str] = field(default_factory=list)
    model_id: str = ""

    @property
    def chars_freed(self) -> int:
        return max(0, self.chars_before - self.chars_after)


def evict_tool_results(
    messages: Sequence[BaseMessage],
    *,
    keep: int,
) -> tuple[list[BaseMessage], EvictionReport]:
    """Shorten every tool result but the `keep` most recent ones.

    Returns a new list. The input messages are never mutated: each evicted result is a
    copy with different content, so the objects still held by the graph state -- and
    therefore everything the transcript is written from -- are untouched.

    Only `ToolMessage` is ever touched. The user's own messages, the assistant's prose,
    and every `tool_calls` block stay exactly as they were, which is what leaves the model
    able to see that it searched and what for.

    A result no longer than the placeholder is left alone -- see `MIN_EVICTABLE_CHARS`.
    """
    out = list(messages)
    tool_indexes = [i for i, m in enumerate(out) if isinstance(m, ToolMessage)]
    report = EvictionReport(
        messages_before=len(out),
        messages_after=len(out),
        chars_before=sum(_content_length(out[i]) for i in tool_indexes),
        kept_count=min(keep, len(tool_indexes)),
    )
    evictable = tool_indexes[: max(0, len(tool_indexes) - keep)]
    for i in evictable:
        message = out[i]
        if message.content == EVICTION_PLACEHOLDER:
            # Already evicted on an earlier call of the same turn. Counting it again would
            # report the same kilobytes freed twice.
            continue
        if _content_length(message) <= MIN_EVICTABLE_CHARS:
            report.kept_count += 1
            continue
        report.evicted.append(str(getattr(message, "name", "") or "tool"))
        report.evicted_count += 1
        out[i] = message.model_copy(update={"content": EVICTION_PLACEHOLDER})
    report.chars_after = sum(_content_length(out[i]) for i in tool_indexes)
    return out, report


def compact_messages(
    messages: Sequence[BaseMessage],
    *,
    model_id: str,
    window: Optional[int] = None,
) -> tuple[list[BaseMessage], Optional[EvictionReport]]:
    """Apply layer one if the last billed call crossed the configured threshold.

    Returns the list to send and the report of what was done, or `(messages, None)` when
    nothing fired -- which is the ordinary case on current traffic and is not an error.
    """
    resolved_window = context_window(model_id) if window is None else int(window)
    threshold = threshold_tokens(resolved_window)
    if threshold <= 0:
        return list(messages), None
    billed = last_billed_tokens(messages)
    if billed < threshold:
        return list(messages), None
    evicted, report = evict_tool_results(messages, keep=keep_recent())
    if not report.evicted_count:
        # Over the threshold with nothing left to evict. Layer two is what answers this
        # case and it is not built, so the turn proceeds unchanged rather than pretending.
        log.warning(
            "compaction threshold %d crossed at %d tokens with no evictable tool results",
            threshold,
            billed,
        )
        return list(messages), None
    report.compaction_id = uuid.uuid4().hex
    report.tokens_before = billed
    report.context_window = resolved_window
    report.threshold_tokens = threshold
    report.model_id = model_id or ""
    log.info(
        "compacted context %s: %d tokens over threshold %d of window %d, "
        "evicted %d tool results (%d chars), kept %d\n"
        "model-visible list BEFORE:\n%s\nmodel-visible list AFTER:\n%s",
        report.compaction_id,
        billed,
        threshold,
        resolved_window,
        report.evicted_count,
        report.chars_freed,
        report.kept_count,
        summarise_list(messages),
        summarise_list(evicted),
    )
    return evicted, report


def record_compaction(
    report: EvictionReport,
    *,
    username: Optional[str],
    session_id: Optional[str],
) -> None:
    """Best-effort insert of the compaction trail. Never raises.

    Written twice: once when the eviction is applied, and again with `tokens_after` filled
    in once the next model call reports what the shortened list actually cost. The table
    is a `ReplacingMergeTree` keyed on the compaction id, so the second insert supersedes
    the first rather than doubling it.
    """
    base = _clickhouse_url()
    if not base or not report.compaction_id:
        return
    row = {
        "compaction_id": report.compaction_id,
        "username": (username or "").strip() or "guest",
        "session_id": session_id or "",
        "model_id": report.model_id,
        "layer": "eviction",
        "context_window": int(report.context_window),
        "threshold_tokens": int(report.threshold_tokens),
        "tokens_before": int(report.tokens_before),
        "tokens_after": int(report.tokens_after),
        "messages_before": int(report.messages_before),
        "messages_after": int(report.messages_after),
        "evicted_count": int(report.evicted_count),
        "kept_count": int(report.kept_count),
        "chars_before": int(report.chars_before),
        "chars_after": int(report.chars_after),
        "evicted": list(report.evicted),
    }
    try:
        with httpx.Client(timeout=(2.0, 5.0), auth=_auth()) as client:
            r = client.post(
                f"{base}/",
                params={
                    "database": GLOBAL_DB,
                    "query": "INSERT INTO chat_compactions FORMAT JSONEachRow",
                },
                content=json.dumps(row, ensure_ascii=False).encode("utf-8"),
            )
            if r.status_code >= 300:
                log.warning(
                    "chat_compactions insert failed status=%s body=%s",
                    r.status_code,
                    r.text[:200],
                )
    except Exception as exc:  # noqa: BLE001 -- the trail must not break a chat turn
        log.warning("chat_compactions insert failed: %s", exc)


def describe() -> str:
    """One line for the startup log, so a deployment says what its trigger is."""
    fraction = compaction_fraction()
    if fraction <= 0:
        return "context compaction: off"
    return (
        f"context compaction: eviction at {fraction:.0%} of the model's stated context "
        f"window, keeping the {keep_recent()} most recent tool results"
    )
