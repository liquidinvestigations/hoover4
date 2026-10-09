"""Context compaction: replace the older steps of a run with one summary.

A run grows because every result that the model collected stays in the list of the next
call. When the size of the next request reaches the trigger, a fraction of the model's stated
context window, `plan_compaction` selects the older steps to replace, and `finish_compaction`
replaces them with one summary before the model call. The list is planned to a target of a
third of the trigger.

The list after a compaction holds these parts, in list order.

- **The user's messages.** Every `human` message that is not a record stays: the request,
  the clarifications, and the notes that the worker writes. They are the fixed input of the
  run, with the system text and the tool schemas.
- **The summary.** One `human` message in place of the first message that it replaces. Code
  writes its first part, the index of `thread_index`: the searches, the documents and pages
  read, the continuation handles, the citation labels, and the skill and tool texts that
  left the list. The summary model writes
  the rest in one request: findings, contradictions, outstanding work, and the identifiers
  that let the model read a source again.
- **The recent steps.** The largest suffix of complete step groups (an `ai` message with all
  its results) that fits the target with the fixed input and the summary. The newest group
  always stays.

A compaction replaces one older prefix of complete groups. The prefix includes the previous
summary, so the new summary extends it. A `read_skill` or `read_tool` result in the prefix
does not go to the summary model, and the index names it, so the model can read it again.

Five properties hold.

**Nothing is edited.** The compaction applies to the list on its way to the model. The worker
stores the record as a version 3 `compaction` row (`CompactionReport.row`), and each later
call applies it with `run_messages.apply_record`. The transcript keeps every result in full.
`finish_compaction` builds its own output with the same function, so a replay gives the same
list. The readers of version 1 and 2 rows stay in `run_messages`.

**Each call has one result.** A step group leaves the list whole or stays whole.

**An unknown context window never fires the trigger.** `llm_models.context_window` is 0 when
the provider never stated one, and 0 means no compaction.

**A request that cannot fit ends the run.** When the fixed input and the newest group pass
the safe input of the model, no summary can help, and `plan_compaction` raises
`ContextError` with the size of each part. The stored thread stays whole.

**A quote keeps the source that the results give.** The summary model writes the source of
each quote in brackets. When the quote is in the text of a document or a page that the
replaced steps read, and the bracket names another source, code writes the source of that
text in the bracket (`attribute_quotes`).

**A failed summary is not retention.** When the summary request fails or gives no text, the
record has the status `failed` and changes no message. The caller sends the previous list
only when it fits. A later plan over the same prefix does not ask the summary model again.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import httpx

from research_agent import model_params, thread_index
from research_agent.run_messages import RunMessage, apply_record

log = logging.getLogger(__name__)

GLOBAL_DB = os.getenv("CLICKHOUSE_DATABASE", "Hoover4_Processing")

#: Fraction of the model's context window at which compaction fires. Configuration
#: (`AGENT_COMPACTION_FRACTION`) can change it.
DEFAULT_COMPACTION_FRACTION = 0.80
#: The version of the record that this module writes.
RECORD_VERSION = 3
#: The completion cap of the summary request. The plan keeps this many tokens free for it.
SUMMARY_TOKENS = 2_000
#: The margin of the token estimate.
MARGIN = 1.05
#: What a cut tool result ends with. Version 2 rows apply it.
CUT_MARK = " [cut to save context]"
#: The chars of one message that no content holds, such as the role.
FRAME_CHARS = 24

#: What an evicted tool result says in the model's place. Version 1 rows apply it.
EVICTION_PLACEHOLDER = (
    "[This tool result was evicted to reclaim context. It is unchanged in the "
    "conversation transcript. The call that produced it is shown above. Re-run the tool "
    "if you need its content again.]"
)

#: The start of each record. A `human` message that starts with it is a record, never a
#: user message, and a later compaction replaces it.
RECORD_HEADER = (
    "[Summary of earlier steps. Code wrote the lists of searches, documents, pages, "
    "continuations and citation labels. A model wrote the rest from the steps it replaces. "
    "The full steps are in the transcript. Read a source again before you quote it.]\n\n"
)
#: The starts of the records of version 2 and version 1 rows.
_V2_RECORD_HEAD = "[Record of earlier steps. Code wrote the lists"
_V1_RECORD_HEAD = "[Context handoff."
_RECORD_HEADS = (RECORD_HEADER[:40], _V2_RECORD_HEAD, _V1_RECORD_HEAD)

#: A document or web citation handle returned by a citation tool.
CITATION_HANDLE = re.compile(r"\[[DW]\d+\]")

#: The results that never go to the summary model. The index names them.
TEXT_TOOLS = frozenset({thread_index.READ_SKILL, thread_index.READ_TOOL})

#: The request of the summary. `{previous}` holds `PREVIOUS_SUMMARY_LINE` when the history
#: starts with a previous summary.
SUMMARY_PROMPT = """\
You summarise the older steps of a research agent. The agent continues its work after you, \
and your summary replaces these steps in its context. The agent keeps its task, the user's \
messages and its newest steps. Code adds lists of the searches, the documents and pages \
read, the continuation handles and the citation labels, so do not copy those lists.

Use exactly these sections, in this order:

## Findings
One line for each fact that bears on the task. Quote each sentence of a source that states \
such a fact, whole and word for word, in quotation marks. After the quote, give the source \
of the result that holds it, in this form: [source: collection name, first 16 characters of \
the file hash, path] or [source: URL] or [source: report]. Do not shorten a quote and do \
not merge two sources. Copy every number, date, name, \
amount, count and identifier exactly. Include each note that the agent saved with \
`write_note`. Read every `read_page` result at the end of the history below. Keep every \
finding that answers its call's goal, including each numbered clause, with its URL.

## Contradictions
Each pair of sources that disagree, with both quoted claims, each followed by its source in \
the same form. Write "none" when \
the history shows no disagreement.

## Outstanding work
The parts of the task and of the user's requests that the history did not finish, the \
questions it did not answer, and the leads not yet followed, each with the document or the \
query that raised it. Check completed tool results before you list work here. A cut page \
has been read through its shown text; its continuation remains unread. List only the \
needed unread part as work. Add no work that the user or the agent did not state.

## Sources to read again
The identifiers that let the agent read a source again exactly: file hashes with pages, \
URLs, cached file handles, continuation handles with their offsets, and report identifiers.

Rules: report only what the history below says. Invent nothing. Do not answer the task. \
Keep the summary under {words} words.
{previous}
The agent's task:
{task}

--- history being replaced ---
{transcript}
--- end ---
"""
PREVIOUS_SUMMARY_LINE = ("The history starts with the previous summary. Keep every fact of it "
                         "that still bears on the task.")
#: The task in the summary request is cut to this many characters.
TASK_CHARS = 2_000
#: The end of a result that the summary request holds in part.
EXTRACT_MARK = ("\n[The summary request holds part of this result. It has {chars} characters "
                "in the transcript. The call above and its continuation read it again.]\n")

#: The (connect, read) timeout of a summary request when `LLM_REQUEST_TIMEOUT_SECONDS` is
#: unset: the read timeout of a model call.
_SUMMARISER_TIMEOUT = (5.0, 3600.0)

#: How long a context window read from the catalog is trusted before it is read again.
_WINDOW_TTL_SECONDS = 300

_window_cache: dict[str, tuple[float, int]] = {}

Key = Tuple[str, int]
#: A summariser takes the prompt and the completion cap, and returns the text.
Summariser = Callable[[str, int], str]

#: The error classes of `ContextError`.
CONTEXT_SIZE = "context_size"
CONTEXT_PREPARATION = "context_preparation"


class ContextError(Exception):
    """A model request that cannot be prepared within the model's input. The worker ends the
    run with the text, and the stored thread stays whole. A repeat cannot help, so the
    request is not retried."""

    def __init__(self, error_class: str, message: str):
        super().__init__(message)
        self.error_class = error_class


def summariser_timeout() -> tuple[float, float]:
    """The (connect, read) timeout of a summary request."""
    return model_params.request_timeout() or _SUMMARISER_TIMEOUT


def _without_cap(params: dict) -> dict:
    """`params` without `max_tokens`."""
    return {key: value for key, value in params.items() if key != "max_tokens"}


def compaction_fraction() -> float:
    """The configured trigger, as a fraction of the context window.

    A value out of range, or not a number, turns compaction off. A fraction above 1 cannot
    fire, and a fraction at or below 0 would compact every call.
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


def _clickhouse_url() -> str:
    return (os.getenv("CLICKHOUSE_URL") or "").rstrip("/")


def _auth() -> tuple[str, str]:
    return (os.getenv("CLICKHOUSE_USER") or "hoover4", os.getenv("CLICKHOUSE_PASSWORD") or "")


def forget_window(model_id: str) -> None:
    """Remove the cached context window of a model, so the next read asks the catalog."""
    _window_cache.pop((model_id or "").strip(), None)


def context_window(model_id: str, *, now: Optional[float] = None) -> int:
    """The model's context window from the catalog, or 0 when nothing states one.

    Read from `llm_models`, so the trigger divides by the number that the transcript footer
    shows. Every failure returns 0, and 0 means no compaction. Never substitute a default.
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
                    "database": GLOBAL_DB, "async_insert": 1, "wait_for_async_insert": 1,
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


def target_tokens(trigger: int) -> int:
    """The size that a compaction plans the list to, a third of the trigger."""
    return trigger // 3


def last_billed(messages: Sequence[RunMessage]) -> int:
    """Prompt plus completion of the newest `ai` message with a billed prompt, else 0."""
    for m in reversed(list(messages)):
        if m.role == "ai" and m.usage and int(m.usage.get("input_tokens") or 0) > 0:
            return int(m.usage.get("input_tokens") or 0) + int(m.usage.get("output_tokens") or 0)
    return 0


# ------------------------------------------------------------------------ estimate


def msg_chars(m: RunMessage) -> int:
    """The characters of one message: content, call names and arguments, and the frame."""
    return (len(m.content or "")
            + sum(len(c.name) + len(json.dumps(c.args, ensure_ascii=False))
                  for c in m.tool_calls)
            + FRAME_CHARS)


@dataclass
class Estimator:
    """Token sizes before the model call, from a ratio that the last billed call gives.
    `request_size.measure` uses it when the tokenizer does not count."""

    ratio: float
    fixed: int

    @classmethod
    def calibrate(cls, applied: Sequence[RunMessage], system_text: str = "",
                  schemas_json: str = "") -> "Estimator":
        """The ratio of the newest `ai` message with a billed prompt P: P over the
        characters of the list that its call sent, between 1/6 and 1/1.5 tokens a
        character. With no billed call the ratio is 1/3."""
        base = len(system_text or "") + len(schemas_json or "")
        ratio = 1 / 3
        for k in range(len(applied) - 1, -1, -1):
            m = applied[k]
            prompt = int((m.usage or {}).get("input_tokens") or 0) if m.role == "ai" else 0
            if prompt > 0:
                chars = base + sum(msg_chars(x) for x in applied[:k])
                ratio = min(1 / 1.5, max(1 / 6, prompt / max(chars, 1)))
                break
        return cls(ratio, math.ceil(base * ratio * MARGIN))

    def tokens(self, m: RunMessage) -> int:
        return math.ceil(msg_chars(m) * self.ratio * MARGIN)

    def tokens_text(self, text: str) -> int:
        return math.ceil(len(text or "") * self.ratio * MARGIN)

    def list_size(self, messages: Sequence[RunMessage]) -> int:
        return sum(self.tokens(m) for m in messages)

    def chars_for(self, tokens: int) -> int:
        """The characters of content that `tokens` holds."""
        return max(0, int(tokens / (self.ratio * MARGIN)))


# ------------------------------------------------------------------------- groups


def _key(m: RunMessage) -> Optional[Key]:
    if m.thread_id is None or m.idx is None:
        return None
    return (str(m.thread_id), int(m.idx))


def is_record(m: RunMessage) -> bool:
    """Whether a `human` message is a compaction record of any version."""
    return m.role == "human" and (m.content or "").startswith(_RECORD_HEADS)


def step_groups(msgs: Sequence[RunMessage]) -> List[List[int]]:
    """Index groups in list order: an `ai` message with its results, else one message."""
    owner: Dict[str, int] = {}
    groups: Dict[int, List[int]] = {}
    for i, m in enumerate(msgs):
        if m.role == "ai":
            groups[i] = [i]
            for c in m.tool_calls:
                owner[c.id] = i
        elif m.role == "tool" and m.tool_call_id in owner:
            groups[owner[m.tool_call_id]].append(i)
        else:
            groups[i] = [i]
    return [sorted(v) for _, v in sorted(groups.items())]


def _is_user(m: RunMessage) -> bool:
    return m.role == "human" and not is_record(m)


def _names(msgs: Sequence[RunMessage]) -> Dict[int, str]:
    """The tool name of each `tool` message, from its call."""
    calls = {c.id: c.name for m in msgs if m.role == "ai" for c in m.tool_calls}
    return {i: calls.get(m.tool_call_id or "", m.name or "") for i, m in enumerate(msgs)
            if m.role == "tool"}


def _too_large_text(est_fixed: int, user: int, newest: int, limit: int) -> str:
    """The text of a request whose fixed input and newest group pass the safe input."""
    total = est_fixed + user + newest + SUMMARY_TOKENS
    if est_fixed + user > limit:
        part = (f"The fixed input alone is about {est_fixed + user:,} tokens: the system text "
                f"and the tool schemas {est_fixed:,}, and the user's messages {user:,}.")
    else:
        part = (f"The newest tool results are about {newest:,} tokens, and the fixed input "
                f"is about {est_fixed + user:,} tokens.")
    return (f"The next model request needs about {total:,} tokens, and the model accepts "
            f"{limit:,} tokens of input. {part} A summary of older steps cannot make it "
            "fit, so the run stops. The transcript keeps every step.")


# ------------------------------------------------------------------------ summary


def _call_text(name: str, args: Dict[str, Any]) -> str:
    return f"{name}({json.dumps(args or {}, ensure_ascii=False, sort_keys=True)})"


@dataclass
class Block:
    """One message of the prefix as text for the summary request."""

    text: str
    #: The characters of a tool result, 0 for another message. Only a result is cut.
    result_chars: int = 0
    head: str = ""


def summary_blocks(msgs: Sequence[RunMessage], prefix: Sequence[int]) -> List[Block]:
    """The prefix as blocks for the summary request. Page results follow other blocks so
    the summary sees them last. Each result names its original step and call. A previous
    record gives its text. No block holds a `read_skill` or `read_tool` result."""
    names = _names(msgs)
    calls = {c.id: c for m in msgs if m.role == "ai" for c in m.tool_calls}
    blocks: List[Block] = []
    page_results: List[Block] = []
    for i in prefix:
        m = msgs[i]
        if m.role == "tool":
            if names.get(i) in TEXT_TOOLS:
                continue
            call = calls.get(m.tool_call_id or "")
            head = (f"[result of {_call_text(call.name, call.args) if call else (m.name or 'tool')}"
                    f" at stored step {m.idx}]\n")
            block = Block(text=m.content or "", result_chars=len(m.content or ""), head=head)
            (page_results if names.get(i) == thread_index.READ_PAGE else blocks).append(block)
        elif m.role == "ai":
            shown = [c for c in m.tool_calls if c.name not in TEXT_TOOLS]
            content = (m.content or "").strip()
            if not shown and not content:
                continue
            label = "assistant"
            if shown:
                label += " calling " + ", ".join(_call_text(c.name, c.args) for c in shown)
            blocks.append(Block(text=f"[{label}]\n{content}".rstrip()))
        elif is_record(m):
            blocks.append(Block(text=f"[previous summary]\n{m.content}"))
    return blocks + page_results


#: A quote of the summary with its bracketed source: the quote, and the source text.
QUOTE_SOURCE = re.compile(r'["\u201c]([^"\u201c\u201d\n]{12,})["\u201d]\s*\[source: ([^\]\n]*)\]')
#: The most sources that one corrected bracket names.
QUOTE_SOURCES_MAX = 3


@dataclass(frozen=True)
class ReadSource:
    """The text of one document or page that a replaced step read, with its source."""

    #: The source as a bracket gives it: "collection, hash start, path", or the URL.
    label: str
    #: The identifiers of which one must be in a correct bracket, in lower case.
    ids: Tuple[str, ...]
    #: The text with each run of white space as one space.
    text: str


def _flat(text: str) -> str:
    return " ".join((text or "").split())


def read_sources(msgs: Sequence[RunMessage], prefix: Sequence[int]) -> List[ReadSource]:
    """The document and page texts of the `read_documents` and `read_page` results in the
    prefix, each with its source."""
    names = _names(msgs)
    out: List[ReadSource] = []
    for i in prefix:
        m = msgs[i]
        if m.role != "tool" or m.status == "error":
            continue
        name = names.get(i) or m.name or ""
        if name == thread_index.READ_DOCUMENTS:
            body = thread_index._json_object(m.content) or {}
            for item in body.get("items") or []:
                if not isinstance(item, dict) or not item.get("file_hash") or not item.get("text"):
                    continue
                start = str(item["file_hash"])[:16]
                label = ", ".join(x for x in (str(item.get("collection") or ""), start,
                                              str(item.get("path") or "")) if x)
                out.append(ReadSource(label, (start.lower(),), _flat(str(item["text"]))))
        elif name == thread_index.READ_PAGE and isinstance(m.content, str):
            for block in thread_index.page_blocks(m.content):
                lines = block.split("\n", 2)
                if len(lines) < 3:
                    continue
                url = lines[1].strip()
                out.append(ReadSource(url, (url.lower(),), _flat(lines[2])))
    return out


def attribute_quotes(summary: str, sources: Sequence[ReadSource]) -> Tuple[str, int]:
    """The summary with the source of each quote that a read text holds, and the count of
    brackets changed.

    A bracket that names an identifier of a text that holds the quote stays. A quote that no
    read text holds keeps its bracket, because code cannot find its source.
    """
    changed = 0

    def fix(match: "re.Match[str]") -> str:
        nonlocal changed
        quote = _flat(match.group(1))
        holders = [s for s in sources if quote and quote in s.text]
        named = match.group(2).lower()
        if not holders or any(i in named for s in holders for i in s.ids):
            return match.group(0)
        labels = list(dict.fromkeys(s.label for s in holders))[:QUOTE_SOURCES_MAX]
        changed += 1
        start = match.start(2) - match.start(0)
        end = match.end(2) - match.start(0)
        whole = match.group(0)
        return whole[:start] + "; ".join(labels) + whole[end:]

    return QUOTE_SOURCE.sub(fix, summary), changed


def extract(text: str, chars: int) -> str:
    """A bounded extract of a result: its start and its end, which often holds the
    continuation handle, with `EXTRACT_MARK` between them."""
    if len(text) <= chars:
        return text
    mark = EXTRACT_MARK.format(chars=len(text))
    room = max(0, chars - len(mark))
    tail = room // 5
    return text[:room - tail] + mark + (text[-tail:] if tail else "")


def fit_blocks(blocks: Sequence[Block], budget_chars: int) -> Tuple[List[str], int]:
    """The texts of the blocks within `budget_chars`, and the count of results cut.

    The results share the room that the other blocks leave. A result under the share stays
    whole, and each larger result is cut to one equal cap (`extract`).
    """
    # Each block is joined to the next with a blank line.
    fixed = sum(len(b.head) + len(b.text) for b in blocks if not b.result_chars)
    fixed += sum(len(b.head) for b in blocks if b.result_chars) + 2 * len(blocks)
    sizes = sorted(b.result_chars for b in blocks if b.result_chars)
    room = max(0, budget_chars - fixed)
    if sum(sizes) <= room:
        return [b.head + b.text for b in blocks], 0
    cap, left = 0, room
    for n, size in enumerate(sizes):
        share = left // (len(sizes) - n)
        if size > share:
            cap = share
            break
        left -= size
    texts, cut = [], 0
    for b in blocks:
        if b.result_chars > cap and b.result_chars:
            texts.append(b.head + extract(b.text, cap))
            cut += 1
        else:
            texts.append(b.head + b.text)
    return texts, cut


def render_prompt(texts: Sequence[str], task: str, max_tokens: int, previous: bool) -> str:
    """The summary request."""
    return SUMMARY_PROMPT.format(
        words=max(100, int(0.6 * max_tokens)),
        previous=("\n" + PREVIOUS_SUMMARY_LINE + "\n") if previous else "",
        task=(task or "")[:TASK_CHARS],
        transcript="\n\n".join(texts),
    )


def summary_model(model_id: str) -> str:
    """The model of the summary request: `LLM_MODEL_COMPACTION`, else the answering model."""
    return (os.getenv("LLM_MODEL_COMPACTION") or "").strip() or model_id


def summarise_with_model(prompt: str, *, model_id: str, max_tokens: int) -> str:
    """Ask the compaction model for the summary. An empty string on any failure.

    Thinking is off: a thinking model given a transcript reasons about its content and
    starts to answer the task (`research_agent/thinking.py`).
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
    try:
        with httpx.Client(timeout=summariser_timeout()) as client:
            response = client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={
                    "model": summary_model(model_id),
                    # `temperature` only when the provider accepts it. The output cap of
                    # `sampling_params` is left out, because this body sets its own.
                    **_without_cap(model_params.sampling_params(0)),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": int(max_tokens),
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            if response.status_code >= 300:
                log.warning("the summariser refused: status=%s body=%s",
                            response.status_code, response.text[:200])
                return ""
            choices = response.json().get("choices") or []
            return str((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001 -- no summary is a valid answer
        log.warning("the summariser could not be reached: %s", exc)
        return ""


# ------------------------------------------------------------------------ report


def summarise_list(messages: Sequence[RunMessage]) -> str:
    """One line for each message: its role, its calls or its tool, and its length. Logged
    with a compaction, because a reader first asks what the model could still see."""
    lines = []
    for i, m in enumerate(messages):
        detail = ""
        if m.role == "tool":
            detail = f" result of {m.name or '?'}"
        if m.tool_calls:
            detail = " calls " + ", ".join(c.name for c in m.tool_calls)
        lines.append(f"  {i:3d} {m.role}{detail} [{len(m.content or '')} chars]")
    return "\n".join(lines)


def issued_citations(messages: Sequence[RunMessage]) -> List[str]:
    """Every citation handle in the list, in the order it first occurs."""
    handles: List[str] = []
    for m in messages:
        for handle in CITATION_HANDLE.findall(m.content or ""):
            if handle not in handles:
                handles.append(handle)
    return handles


@dataclass
class CompactionReport:
    """What one compaction did: the row that the worker stores, and the trail row."""

    compaction_id: str = ""
    layer: str = "prefix"
    #: `ok`, or `failed` when the summary gave no text. A failed record changes no message.
    status: str = "ok"
    tokens_before: int = 0
    tokens_after: int = 0
    context_window: int = 0
    threshold_tokens: int = 0
    target: int = 0
    est_after: int = 0
    target_reached: bool = True
    steps_summarised: int = 0
    sizes: Dict[str, int] = field(default_factory=dict)
    messages_before: int = 0
    messages_after: int = 0
    chars_before: int = 0
    chars_after: int = 0
    model_id: str = ""
    #: The record, stored whole.
    summary: str = ""
    summarised_count: int = 0
    preserved_count: int = 0
    handles: List[str] = field(default_factory=list)
    list_before: str = ""
    list_after: str = ""
    #: The content of the version 3 `compaction` row.
    row: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompactionPlan:
    """A compaction planned before any model call. `finish_compaction` summarises it."""

    applied: List[RunMessage]
    est: Estimator
    model_id: str
    window: int
    trigger: int
    target: int
    billed: int
    #: The keys of the prefix that the summary replaces, in list order.
    source: List[Key]
    #: The key of the first message of the recent steps.
    retained_from: Optional[Key]
    index: str
    prompt: str
    steps_summarised: int
    #: The estimated sizes of the parts of the planned list, and of the summary request.
    sizes: Dict[str, int]
    #: The count of prefix results that the summary request holds as extracts.
    extracts: int = 0
    #: True when the newest stored record failed over the same prefix. No summary request
    #: is sent again.
    unchanged_failure: bool = False
    #: The texts that the prefix read, with their sources, for `attribute_quotes`.
    read_sources: List[ReadSource] = field(default_factory=list)

    @property
    def parts(self) -> int:
        """The count of summary requests, for the `compaction` frame."""
        return 0 if self.unchanged_failure else 1


def _record_rows(rows: Sequence[RunMessage]) -> List[Dict[str, Any]]:
    out = []
    for m in rows:
        if m.role != "compaction":
            continue
        try:
            record = json.loads(m.content or "{}")
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def _source_keys(record: Dict[str, Any]) -> List[Key]:
    out = []
    for item in record.get("source") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((str(item[0]), int(item[1])))
    return out


def plan_compaction(applied: Sequence[RunMessage], rows: Sequence[RunMessage], *,
                    system_text: str = "", schemas_json: str = "", model_id: str = "",
                    window: Optional[int] = None, fraction: Optional[float] = None,
                    estimator: Optional[Estimator] = None, measured: Optional[int] = None,
                    safe_input: int = 0, force: bool = False,
                    summary_window: Optional[int] = None,
                    allow_oversized_newest: bool = False) -> Optional[CompactionPlan]:
    """The plan of a compaction, with no model call. `None` when the trigger does not fire or
    no complete group is older than the newest one that must stay.

    `applied` is the list after the stored compactions, `rows` the stored thread.
    `measured` is the size of the next request (`request_size.measure`), with the results
    that the previous reply's calls stored. Without it, the size is the billed tokens of the
    newest billed call. `safe_input` is the window less the output reserve. The trigger is
    never above it. `force` plans a compaction under the trigger, after the provider refused
    the request as too large. `summary_window` is the window of the summary model, read from
    the catalog when it is not given.

    Raises `ContextError` when the fixed input and the newest group pass the safe input.
    """
    applied = list(applied)
    resolved = context_window(model_id) if window is None else int(window)
    trigger = threshold_tokens(resolved, fraction)
    if trigger > 0 and safe_input > 0:
        trigger = min(trigger, safe_input)
    billed = last_billed(applied) if measured is None else int(measured)
    if trigger <= 0 or (billed < trigger and not force):
        return None
    target = target_tokens(trigger)
    limit = safe_input or resolved
    est = estimator or Estimator.calibrate(applied, system_text, schemas_json)

    groups = step_groups(applied)
    steps = [g for g in groups if not (len(g) == 1 and _is_user(applied[g[0]]))]
    user = sum(est.tokens(m) for m in applied if _is_user(m))
    fixed = est.fixed + user
    sizes = [sum(est.tokens(applied[i]) for i in g) for g in steps]
    newest = sizes[-1] if sizes else 0
    header = est.tokens_text(RECORD_HEADER) + SUMMARY_TOKENS
    if not allow_oversized_newest and fixed + newest + (header if len(steps) > 1 else 0) > limit:
        raise ContextError(CONTEXT_SIZE, _too_large_text(est.fixed, user, newest, limit))
    if len(steps) < 2:
        return None

    def index_for(start: int) -> str:
        hidden = {k for g in steps[:start] for i in g if applied[i].role == "tool"
                  for k in [_key(applied[i])] if k}
        visible = {k for m in applied if m.role == "tool"
                   for k in [_key(m)] if k and k not in hidden}
        return thread_index.render(rows, visible_after=visible)

    # The largest suffix of complete groups that fits the target with the fixed input and
    # the summary, and at least the newest group.
    start, used = len(steps) - 1, newest
    while start > 0 and fixed + header + used + sizes[start - 1] <= target:
        start -= 1
        used += sizes[start]
    if start == 0:
        log.warning("compaction threshold %d crossed at %d tokens, and every step fits the "
                    "target of %d", trigger, billed, target)
        return None
    index = index_for(start)
    while start < len(steps) - 1 and fixed + header + est.tokens_text(index) + used > target:
        used -= sizes[start]
        start += 1
        index = index_for(start)

    prefix = [i for g in steps[:start] for i in g]
    source = [k for i in prefix for k in [_key(applied[i])] if k]
    retained_from = _key(applied[steps[start][0]])
    previous = any(is_record(applied[i]) for i in prefix)
    task = next((m.content for m in applied if _is_user(m)), "")

    s_window = summary_window
    if s_window is None:
        name = summary_model(model_id)
        s_window = resolved if name == model_id else (context_window(name) or resolved)
    skeleton = render_prompt([], task, SUMMARY_TOKENS, previous)
    budget = max(0, int(s_window) - SUMMARY_TOKENS - est.tokens_text(skeleton))
    texts, extracts = fit_blocks(summary_blocks(applied, prefix), est.chars_for(budget))
    prompt = render_prompt(texts, task, SUMMARY_TOKENS, previous)

    failed_before = next((r for r in reversed(_record_rows(rows))
                          if r.get("version") == RECORD_VERSION), None)
    unchanged = bool(failed_before and failed_before.get("status") == "failed"
                     and _source_keys(failed_before) == source)
    return CompactionPlan(
        applied=applied, est=est, model_id=model_id or "", window=resolved, trigger=trigger,
        target=target, billed=billed, source=source, retained_from=retained_from,
        index=index, prompt=prompt,
        steps_summarised=sum(1 for i in prefix if applied[i].role == "ai"),
        sizes={"fixed": est.fixed, "user": user, "retained": used,
               "index": est.tokens_text(index), "summary_input": est.tokens_text(prompt),
               "summary_window": int(s_window)},
        extracts=extracts, unchanged_failure=unchanged,
        read_sources=read_sources(applied, prefix))


def finish_compaction(plan: CompactionPlan, summariser: Optional[Summariser] = None
                      ) -> Tuple[List[RunMessage], CompactionReport]:
    """The summary, the record, the list and the report of a planned compaction.

    A summary that fails or gives no text gives a record with the status `failed`, which
    changes no message. The caller decides whether the previous list fits.
    """
    est = plan.est
    call = summariser or (lambda prompt, cap: summarise_with_model(
        prompt, model_id=plan.model_id, max_tokens=cap))
    text, error = "", ""
    if plan.unchanged_failure:
        error = "the summary of this prefix failed before, and the prefix did not change"
    else:
        try:
            text = (call(plan.prompt, SUMMARY_TOKENS) or "").strip()
        except Exception as exc:  # noqa: BLE001 -- a failed summary is a record state
            log.warning("the summary request failed: %s", exc)
            error = f"{type(exc).__name__}: {exc}"[:300]
        if not text and not error:
            error = "the summary request gave no text"
    text, corrected = attribute_quotes(text, plan.read_sources)
    status = "ok" if text else "failed"
    record = RECORD_HEADER + plan.index + ("\n\n" if plan.index else "") + text if text else ""
    row: Dict[str, Any] = {
        "version": RECORD_VERSION, "layer": "prefix", "status": status,
        "source": [[k[0], k[1]] for k in plan.source],
        "retained_from": list(plan.retained_from) if plan.retained_from else None,
        "summary": record, "error": error,
    }
    out = apply_record(plan.applied, row)
    est_after = est.fixed + est.list_size(out)
    reached = est_after <= plan.target
    sizes = {**plan.sizes, "summary": est.tokens_text(record), "after": est_after,
             "extracts": plan.extracts}
    row.update({
        "tokens_before": plan.billed, "threshold": plan.trigger, "target": plan.target,
        "est_after": est_after, "target_reached": reached,
        "steps_summarised": plan.steps_summarised if text else 0, "sizes": sizes,
        "sources_corrected": corrected,
    })
    report = CompactionReport(
        compaction_id=uuid.uuid4().hex, status=status, tokens_before=plan.billed,
        context_window=plan.window, threshold_tokens=plan.trigger, target=plan.target,
        est_after=est_after, target_reached=reached,
        steps_summarised=row["steps_summarised"], sizes=sizes,
        messages_before=len(plan.applied), messages_after=len(out),
        chars_before=sum(len(m.content or "") for m in plan.applied),
        chars_after=sum(len(m.content or "") for m in out), model_id=plan.model_id,
        summary=record, summarised_count=len(plan.source) if text else 0,
        preserved_count=max(0, len(out) - 1), handles=issued_citations(plan.applied),
        list_before=summarise_list(plan.applied), list_after=summarise_list(out), row=row,
    )
    log.info("compacted context %s: status %s, %d tokens over trigger %d, target %d, "
             "estimate after %d, %d results as extracts, %d quote sources corrected\n"
             "model-visible list AFTER:\n%s",
             report.compaction_id, status, plan.billed, plan.trigger, plan.target, est_after,
             plan.extracts, corrected, report.list_after)
    if text and not reached:
        log.warning("compaction %s did not reach the target %d: sizes %s",
                    report.compaction_id, plan.target, sizes)
    return out, report


def compact(applied: Sequence[RunMessage], rows: Sequence[RunMessage], *,
            system_text: str = "", schemas_json: str = "", model_id: str = "",
            window: Optional[int] = None, fraction: Optional[float] = None,
            summariser: Optional[Summariser] = None, estimator: Optional[Estimator] = None,
            ) -> Tuple[List[RunMessage], Optional[CompactionReport]]:
    """Plan and finish one compaction. `(applied, None)` when none fires."""
    plan = plan_compaction(applied, rows, system_text=system_text, schemas_json=schemas_json,
                           model_id=model_id, window=window, fraction=fraction,
                           estimator=estimator)
    if plan is None:
        return list(applied), None
    return finish_compaction(plan, summariser)


def record_compaction(report: CompactionReport, *, username: Optional[str],
                      session_id: Optional[str]) -> None:
    """Best-effort insert of the compaction trail. Never raises.

    Written twice: once when the compaction is applied, and again with `tokens_after`
    once the next model call reports what the list cost. The table is a
    `ReplacingMergeTree` keyed on the compaction id, so the second insert replaces the first.
    """
    base = _clickhouse_url()
    if not base or not report.compaction_id:
        return
    row = {
        "compaction_id": report.compaction_id,
        "username": (username or "").strip() or "guest",
        "session_id": session_id or "",
        "model_id": report.model_id,
        "layer": report.layer or "prefix",
        "context_window": int(report.context_window),
        "threshold_tokens": int(report.threshold_tokens),
        "tokens_before": int(report.tokens_before),
        "tokens_after": int(report.tokens_after),
        "messages_before": int(report.messages_before),
        "messages_after": int(report.messages_after),
        "evicted_count": 0,
        "kept_count": int(report.preserved_count),
        "chars_before": int(report.chars_before),
        "chars_after": int(report.chars_after),
        "evicted": [],
        "summary": report.summary,
        "summarised_count": int(report.summarised_count),
        "preserved_count": int(report.preserved_count),
        "handles": list(report.handles),
        "list_before": report.list_before,
        "list_after": report.list_after,
    }
    try:
        from agent_common.clickhouse_buffer import record as buffer_record

        buffer_record(base, GLOBAL_DB, _auth(), 'chat_compactions', row)
    except Exception as exc:
        log.warning("chat_compactions insert failed: %s", exc)


#: The words of a provider refusal that says the request passes the model's input.
_SIZE_REFUSAL = re.compile(
    r"context length|context window|maximum context|too many tokens|prompt is too long|"
    r"input is too long|exceeds the model|longer than the model", re.IGNORECASE)
_STATED_LIMIT = re.compile(r"maximum context length is (\d+)", re.IGNORECASE)


def size_refusal(status: Optional[int], text: str) -> Optional[int]:
    """For a provider refusal of a request that is too large, the context length that the
    refusal states, else 0. None when the refusal is of another kind."""
    if status not in (400, 413) or not _SIZE_REFUSAL.search(text or ""):
        return None
    match = _STATED_LIMIT.search(text or "")
    return int(match.group(1)) if match else 0


def describe() -> str:
    """One line for the startup log, so a deployment says what its trigger is."""
    fraction = compaction_fraction()
    if fraction <= 0:
        return "context compaction: off"
    summariser = (os.getenv("LLM_MODEL_COMPACTION") or "").strip() or "the answering model"
    return (
        # `:g`, because a test lowers the fraction, and "0%" would read as off.
        f"context compaction: at {fraction * 100:g}% of the model's stated context window, "
        f"to a third of that, with one summary of the older steps by {summariser}"
    )
