"""Context compaction: eviction of old tool results, then summarisation.

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

Layer two, summarisation, runs only when layer one has run and the list is still projected
to be over. It drops whole call-and-result groups and puts a structured handoff document
in their place. One rule governs its design and overrides compression everywhere the two
disagree: **a compaction that loses a citation the answer already made is a correctness
bug.** The messages that may never be summarised -- the user's own turns, the todo, and
every message carrying or issuing a citation handle -- are therefore selected by
`protected_indexes` and copied into the output list unchanged. The summariser model is
never asked to preserve them, because a model asked politely will eventually not.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

import httpx
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

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

#: A citation handle as `cite_documents` allocates it and as the model writes it into an
#: answer. Handles are allocated per chat session and are stable for its whole life, so
#: `[D7]` from the first turn still has to resolve in the ninth.
CITATION_HANDLE = re.compile(r"\[D\d+\]")

#: Tool results that carry the citation handle table. Summarising one of these takes the
#: handle-to-document mapping away from the model while its own prose still cites it.
CITATION_TOOLS = frozenset({"cite_documents"})

#: The todo tools. The todo is the turn's plan and the thing the nag loop checks against,
#: so a summary of it is not a cheaper todo, it is a different one.
TODO_TOOLS = frozenset({"read_todo", "write_todo", "edit_todo", "mark_todo"})

#: How many messages at the end of the list layer two always leaves alone, on top of
#: whatever `protected_indexes` selects. The model is mid-turn and the last few exchanges
#: are what it is reasoning about right now.
DEFAULT_KEEP_RECENT_MESSAGES = 6

#: What the handoff document is introduced with in the model-visible list. It says the
#: transcript is intact for the same reason the eviction placeholder does: the alternative
#: reading, that those steps never happened, would make the model report a gap.
HANDOFF_HEADER = (
    "[Context handoff. The earlier steps of this turn were summarised to fit the "
    "context window. They are unchanged in the conversation transcript. Every citation "
    "handle already issued, the user's own messages and the todo are still present in "
    "full below.]"
)

#: How long the summariser model is given. A compaction that hangs costs the turn it was
#: meant to save, so this is short and a timeout means no summarisation rather than no
#: answer.
_SUMMARISER_TIMEOUT = (5.0, 120.0)

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


def _content_text(message: BaseMessage) -> str:
    """A message's content as one string, whatever shape it arrived in."""
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str):
        content = str(content)
    return content


def _content_length(message: BaseMessage) -> int:
    return len(_content_text(message))


def _tool_name(message: BaseMessage) -> str:
    return str(getattr(message, "name", "") or "")


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
class CompactionReport:
    """What one compaction did, for the trail and for the tests.

    One shape for both layers. `layer` says which one produced it: `eviction` fills the
    `evicted`/`kept` and character counts, `summarisation` fills the summary, the counts
    of what it dropped and preserved, and the handles it carried through. A row where
    `layer` is `summarisation` also carries the eviction that ran in front of it, because
    layer two only ever runs on a list layer one has already been over.
    """

    compaction_id: str = ""
    layer: str = "eviction"
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
    #: The handoff document layer two produced, stored whole. It is the only place the
    #: prose the model was given in place of its own can be read back.
    summary: str = ""
    #: Messages layer two dropped, and messages it copied through unchanged.
    summarised_count: int = 0
    preserved_count: int = 0
    #: Every citation handle that had been issued when the compaction ran. All of them
    #: are preserved -- this is the record that says so, and what a later reader checks
    #: an answer's citations against.
    handles: list[str] = field(default_factory=list)
    #: The model-visible list either side of the compaction, one line per message. §3.5.3
    #: asks the record to hold the pre-compaction list, and the question anyone debugging
    #: a compaction asks first is what the model could still see.
    list_before: str = ""
    list_after: str = ""

    @property
    def chars_freed(self) -> int:
        return max(0, self.chars_before - self.chars_after)


def evict_tool_results(
    messages: Sequence[BaseMessage],
    *,
    keep: int,
) -> tuple[list[BaseMessage], CompactionReport]:
    """Shorten every tool result but the `keep` most recent ones.

    Returns a new list. The input messages are never mutated: each evicted result is a
    copy with different content, so the objects still held by the graph state -- and
    therefore everything the transcript is written from -- are untouched.

    Only `ToolMessage` is ever touched. The user's own messages, the assistant's prose,
    and every `tool_calls` block stay exactly as they were, which is what leaves the model
    able to see that it searched and what for.

    A result no longer than the placeholder is left alone -- see `MIN_EVICTABLE_CHARS`.

    A `cite_documents` or todo result is left alone too, for the reason `protected_indexes`
    gives: the `cite_documents` result is the model's only copy of which document `[D3]`
    means, and evicting it while the model's own prose still says `[D3]` is how a cited
    answer becomes an unsourced one. Both layers honour the same never-compacted set.
    """
    out = list(messages)
    tool_indexes = [i for i, m in enumerate(out) if isinstance(m, ToolMessage)]
    report = CompactionReport(
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
        if _tool_name(message) in CITATION_TOOLS or _tool_name(message) in TODO_TOOLS:
            report.kept_count += 1
            continue
        report.evicted.append(str(getattr(message, "name", "") or "tool"))
        report.evicted_count += 1
        out[i] = message.model_copy(update={"content": EVICTION_PLACEHOLDER})
    report.chars_after = sum(_content_length(out[i]) for i in tool_indexes)
    return out, report


def _call_groups(messages: Sequence[BaseMessage]) -> list[list[int]]:
    """Index groups that have to move together to keep the request well formed.

    An assistant message whose `tool_calls` have no matching tool result is rejected by
    an OpenAI-shaped API outright, and so is a tool result with no call that asked for
    it. A group is one assistant message plus every result answering its calls, so
    dropping a group can never leave half a pair behind.
    """
    owner_of: dict[str, int] = {}
    groups: dict[int, list[int]] = {}
    for i, message in enumerate(messages):
        if isinstance(message, AIMessage) and (getattr(message, "tool_calls", None) or []):
            groups[i] = [i]
            for call in message.tool_calls:
                call_id = str(call.get("id") or "")
                if call_id:
                    owner_of[call_id] = i
    for i, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        owner = owner_of.get(str(getattr(message, "tool_call_id", "") or ""))
        if owner is None:
            # No call in this list asked for it. It cannot be grouped, and it is left
            # alone rather than guessed at.
            groups[i] = [i]
        else:
            groups[owner].append(i)
    grouped = {i for members in groups.values() for i in members}
    for i in range(len(messages)):
        if i not in grouped:
            groups[i] = [i]
    return [sorted(members) for _, members in sorted(groups.items())]


def protected_indexes(
    messages: Sequence[BaseMessage],
    *,
    keep_recent_messages: int = 0,
) -> set[int]:
    """Indexes layer two may never summarise.

    This is where the never-summarised set is enforced. It is a selection made in code
    over the list itself, not an instruction in the summariser's prompt: the summariser
    never sees these messages and cannot rewrite, shorten or drop them, whatever it is
    asked to do. Four things are protected.

    * **The user's own messages**, and any system message that reached the list.
    * **The todo**, every call and result of it. The todo is the turn's plan and what the
      nag loop checks against, so a summary of it is a different todo, not a cheaper one.
    * **Every citation handle already issued.** That means both halves of the mapping: the
      `cite_documents` result that allocated `[D3]` and named the document, and any
      message whose text carries `[D3]` -- which is the assistant's own prose. Losing
      either turns a cited answer into an unsourced one, and that is a correctness bug
      rather than a compression trade-off.
    * **The most recent `keep_recent_messages`**, because the model is mid-turn and those
      are what it is reasoning about right now.

    Protection is then closed over `_call_groups`, so protecting a tool result also
    protects the assistant message that asked for it. Without the closure a preserved
    result would arrive with no matching call and the provider would reject the request.
    """
    messages = list(messages)
    protected: set[int] = set()
    tail_start = len(messages) - max(0, keep_recent_messages)
    for i, message in enumerate(messages):
        if i >= tail_start:
            protected.add(i)
            continue
        if isinstance(message, (HumanMessage, SystemMessage)):
            protected.add(i)
            continue
        if isinstance(message, ToolMessage):
            if _tool_name(message) in CITATION_TOOLS or _tool_name(message) in TODO_TOOLS:
                protected.add(i)
        if CITATION_HANDLE.search(_content_text(message)):
            protected.add(i)
    for members in _call_groups(messages):
        if protected.intersection(members):
            protected.update(members)
    return protected


def issued_citations(messages: Sequence[BaseMessage]) -> list[str]:
    """Every citation handle visible in the list, in the order it was first issued.

    Read from the list rather than from the citation server, because the question this
    answers is what the *model* has already told the user, and the model can only have
    used what is in front of it.
    """
    handles: list[str] = []
    for message in messages:
        for handle in CITATION_HANDLE.findall(_content_text(message)):
            if handle not in handles:
                handles.append(handle)
    return handles


def citation_index(messages: Sequence[BaseMessage]) -> list[str]:
    """One verbatim line per cited document: handle, collection, hash, path.

    Built from the `cite_documents` results by reading their fields, never by asking a
    model to restate them. A paraphrase of a citation is a new citation nobody checked.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, ToolMessage) or _tool_name(message) not in CITATION_TOOLS:
            continue
        try:
            payload = json.loads(_content_text(message))
        except (TypeError, ValueError):
            continue
        citations = payload.get("citations") if isinstance(payload, dict) else None
        for citation in citations or []:
            if not isinstance(citation, dict):
                continue
            handle = str(citation.get("handle") or "")
            if not handle or handle in seen:
                continue
            seen.add(handle)
            lines.append(
                f"{handle} {citation.get('collectionname') or '?'}"
                f"/{citation.get('file_hash') or '?'}"
                f"  {citation.get('path') or ''}".rstrip()
            )
    return lines


#: What the summariser is asked for. The sections are fixed and named here rather than
#: left to the model, because a handoff whose shape changes per compaction cannot be read
#: back or compared. Verbatim quoting is asked for explicitly: a paraphrase of a fact is a
#: new fact nobody checked.
#:
#: Nothing in this prompt protects a citation, a user message or the todo. Those never
#: reach the summariser at all -- see `protected_indexes`.
SUMMARISER_PROMPT = """\
You are compacting the working context of a research assistant that is part-way \
through answering a question. Below is the portion of its transcript that is being \
replaced. The user's own messages, the todo and every citation already made are kept \
separately and are NOT your responsibility.

Write a handoff document with exactly these three sections, in this order, using these \
headings and no others:

## Work completed so far
What was searched, read and established. Name the tools and the documents by the \
identifiers used below.

## Facts established, quoted verbatim
The findings that must survive. Quote the source text exactly, in quotation marks, with \
the document identifier beside each quote. Do not paraphrase. Write "none" if there are \
no such facts.

## What remains
What the assistant had not yet done. Write "unknown" rather than guessing.

Rules: report only what appears below. Invent nothing. Do not write a preamble, a \
conclusion, or any heading other than the three above.

--- transcript being replaced ---
{transcript}
--- end ---
"""


def keep_recent_messages() -> int:
    """How many trailing messages layer two leaves alone, from configuration."""
    try:
        raw = os.getenv("AGENT_COMPACTION_KEEP_RECENT_MESSAGES")
        return max(0, int(raw or DEFAULT_KEEP_RECENT_MESSAGES))
    except ValueError:
        return DEFAULT_KEEP_RECENT_MESSAGES


def _transcript_for_summariser(messages: Sequence[BaseMessage]) -> str:
    """The messages being replaced, rendered for the summariser as plain text."""
    parts: list[str] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            label = f"tool result: {_tool_name(message) or 'tool'}"
        elif isinstance(message, AIMessage):
            calls = ", ".join(
                f"{c.get('name') or '?'}({json.dumps(c.get('args') or {}, ensure_ascii=False)})"
                for c in (getattr(message, "tool_calls", None) or [])
            )
            label = "assistant" + (f" calling {calls}" if calls else "")
        else:
            label = type(message).__name__
        parts.append(f"[{label}]\n{_content_text(message)}")
    return "\n\n".join(parts)


def summarise_with_model(prompt: str, *, model_id: str) -> str:
    """Ask the compaction model for the handoff document. Empty string on any failure.

    A separate model from the one answering, when `LLM_MODEL_COMPACTION` names one --
    summarising a transcript is not the task the conversation model was chosen for, and
    it can be a cheaper or faster one. Falls back to the answering model so that an
    unconfigured deployment still has a working layer two.

    Every failure returns an empty string, and an empty summary means no summarisation.
    Compaction exists to save a turn, so it must never be the thing that ends one.
    """
    base = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
    if not base:
        return ""
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    if not api_key:
        key_file = (os.getenv("LLM_API_KEY_FILE") or "").strip()
        if key_file and os.path.exists(key_file):
            with open(key_file) as handle:
                api_key = handle.read().strip()
    model = (os.getenv("LLM_MODEL_COMPACTION") or "").strip() or model_id
    try:
        with httpx.Client(timeout=_SUMMARISER_TIMEOUT) as client:
            response = client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={
                    "model": model,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if response.status_code >= 300:
                log.warning(
                    "the summariser refused: status=%s body=%s",
                    response.status_code,
                    response.text[:200],
                )
                return ""
            choices = response.json().get("choices") or []
            return str((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001 -- no summary is a valid answer
        log.warning("the summariser could not be reached: %s", exc)
        return ""


def build_handoff(
    *,
    summary_body: str,
    dropped: Sequence[BaseMessage],
    citations: Sequence[str],
) -> str:
    """The handoff document, fixed sections, machine-written parts first.

    The two sections the correctness rule depends on -- what was replaced, and which
    citation handles stand -- are assembled here from the list itself. Only the narrative
    sections come from a model, so a summariser that answers badly costs detail and never
    a handle.
    """
    tools: list[str] = []
    for message in dropped:
        for call in getattr(message, "tool_calls", None) or []:
            tools.append(str(call.get("name") or "?"))
    sections = [
        HANDOFF_HEADER,
        "",
        "## What was replaced",
        f"{len(dropped)} messages covering {len(tools)} tool calls"
        + (f": {', '.join(tools)}" if tools else "")
        + ".",
        "",
        "## Citations already issued, and still valid",
        "\n".join(citations) if citations else "none",
        "",
    ]
    return "\n".join(sections) + summary_body.strip() + "\n"


def summarise_messages(
    messages: Sequence[BaseMessage],
    *,
    model_id: str,
    keep_messages: Optional[int] = None,
    summariser: Optional[Callable[[str], str]] = None,
) -> tuple[list[BaseMessage], CompactionReport]:
    """Replace the unprotected older messages with one handoff document.

    Returns a new list. Nothing is mutated and nothing is written back: like layer one,
    this transformation happens on the way to the model and the transcript keeps every
    message in full.

    Whole `_call_groups` are dropped together, so the request stays well formed. The
    protected messages are copied through unchanged and the handoff takes the position of
    the first message it replaces, which keeps the surviving messages in the order they
    happened.

    The list is returned unchanged, with `summarised_count` at 0, when there is nothing
    unprotected to replace, when the summariser gives nothing back, or when the result
    would be longer than the input. The last of those is the same guard
    `MIN_EVICTABLE_CHARS` is for layer one: a compaction that grows the context has
    failed, however well it summarised.
    """
    messages = list(messages)
    report = CompactionReport(
        layer="summarisation",
        model_id=model_id or "",
        messages_before=len(messages),
        messages_after=len(messages),
        chars_before=sum(_content_length(m) for m in messages),
        handles=issued_citations(messages),
        list_before=summarise_list(messages),
    )
    report.chars_after = report.chars_before
    keep = keep_recent_messages() if keep_messages is None else max(0, keep_messages)
    protected = protected_indexes(messages, keep_recent_messages=keep)
    droppable = [i for i in range(len(messages)) if i not in protected]
    report.preserved_count = len(protected)
    if not droppable:
        return messages, report
    dropped = [messages[i] for i in droppable]
    prompt = SUMMARISER_PROMPT.format(transcript=_transcript_for_summariser(dropped))
    call = summariser or (lambda text: summarise_with_model(text, model_id=model_id))
    body = (call(prompt) or "").strip()
    if not body:
        log.warning("summarisation produced nothing, the list is sent unchanged")
        return messages, report
    handoff = build_handoff(
        summary_body=body, dropped=dropped, citations=citation_index(messages)
    )
    out: list[BaseMessage] = []
    for i, message in enumerate(messages):
        if i == droppable[0]:
            out.append(SystemMessage(content=handoff))
        if i in protected:
            out.append(message)
    chars_after = sum(_content_length(m) for m in out)
    if chars_after >= report.chars_before:
        log.warning(
            "the handoff document is not smaller than what it replaces "
            "(%d chars vs %d), the list is sent unchanged",
            chars_after,
            report.chars_before,
        )
        return messages, report
    report.summary = handoff
    report.summarised_count = len(dropped)
    report.messages_after = len(out)
    report.chars_after = chars_after
    report.list_after = summarise_list(out)
    return out, report


def compact_messages(
    messages: Sequence[BaseMessage],
    *,
    model_id: str,
    window: Optional[int] = None,
    summariser: Optional[Callable[[str], str]] = None,
) -> tuple[list[BaseMessage], Optional[CompactionReport]]:
    """Apply the layers, in order, if the last billed call crossed the threshold.

    Returns the list to send and the report of what was done, or `(messages, None)` when
    nothing fired -- which is the ordinary case on current traffic and is not an error.

    Layer one runs first and layer two only runs on what it leaves, because eviction is
    most of the benefit for none of the cost: it makes no model call and it cannot lose a
    fact, since every evicted result is still in the transcript and can be re-read. Layer
    two is what answers the two cases eviction cannot: nothing left to evict, and
    everything evictable evicted while the list is still projected to be over.

    "Still projected to be over" is an estimate and is labelled one. The only honest token
    count available here is what the provider billed for the *previous* call, so the
    saving is projected by the fraction of the list's characters eviction removed. The
    alternative is a second model call made only to measure, or a tokeniser that is not
    the model's -- a guess wearing a number's clothes.
    """
    resolved_window = context_window(model_id) if window is None else int(window)
    threshold = threshold_tokens(resolved_window)
    if threshold <= 0:
        return list(messages), None
    billed = last_billed_tokens(messages)
    if billed < threshold:
        return list(messages), None

    evicted, report = evict_tool_results(messages, keep=keep_recent())
    chars_before_all = sum(_content_length(m) for m in messages)
    chars_after_all = sum(_content_length(m) for m in evicted)
    projected = billed
    if chars_before_all > 0:
        projected = int(billed * chars_after_all / chars_before_all)

    if report.evicted_count and projected < threshold:
        report.compaction_id = uuid.uuid4().hex
        report.tokens_before = billed
        report.context_window = resolved_window
        report.threshold_tokens = threshold
        report.model_id = model_id or ""
        report.list_before = summarise_list(messages)
        report.list_after = summarise_list(evicted)
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
            report.list_before,
            report.list_after,
        )
        return evicted, report

    # Eviction was not enough -- either there was nothing to evict, or what it freed
    # still leaves the list projected over the threshold. Layer two.
    summarised, second = summarise_messages(
        evicted, model_id=model_id, summariser=summariser
    )
    if not second.summarised_count:
        # Layer two could not help -- nothing unprotected to replace, no summary came
        # back, or the handoff was not smaller. Whatever layer one already freed still
        # stands: throwing the eviction away because the second layer failed would send
        # the model MORE than it would have been sent with layer two switched off.
        if report.evicted_count:
            report.compaction_id = uuid.uuid4().hex
            report.tokens_before = billed
            report.context_window = resolved_window
            report.threshold_tokens = threshold
            report.model_id = model_id or ""
            report.list_before = summarise_list(messages)
            report.list_after = summarise_list(evicted)
            log.info(
                "compacted context %s: %d tokens over threshold %d of window %d, "
                "evicted %d tool results (%d chars), kept %d -- still projected over at "
                "%d and summarisation reclaimed nothing\n"
                "model-visible list BEFORE:\n%s\nmodel-visible list AFTER:\n%s",
                report.compaction_id,
                billed,
                threshold,
                resolved_window,
                report.evicted_count,
                report.chars_freed,
                report.kept_count,
                projected,
                report.list_before,
                report.list_after,
            )
            return evicted, report
        log.warning(
            "compaction threshold %d crossed at %d tokens and neither layer could "
            "reclaim anything, the list is sent unchanged",
            threshold,
            billed,
        )
        return list(messages), None
    # One row for the turn's compaction, carrying both layers: the eviction that ran in
    # front of it is what layer two was handed, and reading the summary without it would
    # not explain the counts.
    second.compaction_id = uuid.uuid4().hex
    second.tokens_before = billed
    second.context_window = resolved_window
    second.threshold_tokens = threshold
    second.evicted = list(report.evicted)
    second.evicted_count = report.evicted_count
    second.kept_count = report.kept_count
    second.messages_before = len(messages)
    second.chars_before = chars_before_all
    second.list_before = summarise_list(messages)
    log.info(
        "compacted context %s: %d tokens over threshold %d of window %d, "
        "evicted %d tool results then summarised %d messages into a handoff, "
        "preserved %d, citation handles carried through: %s\n"
        "model-visible list BEFORE:\n%s\nmodel-visible list AFTER:\n%s\n"
        "handoff document:\n%s",
        second.compaction_id,
        billed,
        threshold,
        resolved_window,
        second.evicted_count,
        second.summarised_count,
        second.preserved_count,
        ", ".join(second.handles) or "none",
        second.list_before,
        second.list_after,
        second.summary,
    )
    return summarised, second


def record_compaction(
    report: CompactionReport,
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
        "layer": report.layer or "eviction",
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
        "summary": report.summary,
        "summarised_count": int(report.summarised_count),
        "preserved_count": int(report.preserved_count),
        "handles": list(report.handles),
        "list_before": report.list_before,
        "list_after": report.list_after,
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
    summariser = (os.getenv("LLM_MODEL_COMPACTION") or "").strip() or "the answering model"
    return (
        f"context compaction: eviction at {fraction:.0%} of the model's stated context "
        f"window, keeping the {keep_recent()} most recent tool results, then "
        f"summarisation by {summariser} keeping the {keep_recent_messages()} most "
        "recent messages"
    )
