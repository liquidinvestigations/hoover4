"""Context compaction: replace the older steps of a run with a record.

A run grows because every result that the model collected stays in the list of the next
call. When the last billed call reaches the trigger, a fraction of the model's stated
context window, `compact` plans a smaller list before the next model call, and meets a
target of a third of the trigger.

The list after a compaction holds these parts.

- **The recent window.** The newest step groups (an `ai` message and its results), up to a
  quarter of the target, and at least the newest group.
- **The keep set.** Outside the window: every user message, the newest todo and plan
  results, every `cite_documents` result and every `ai` text with a citation handle, the
  newest read of each skill, every sub-agent report, the notes of `write_note`, and up to
  three document reads again after the summary. Each class has a cap. A kept result keeps
  its call.
- **The record.** One `human` message in place of the first message that it replaces. Code
  writes its first part, the index of `thread_index`: the searches, the documents read, and
  the skill and tool texts that left the list. A model writes the rest from the compacted
  part, in 1 or 3 requests.

A `read_skill` or `read_tool` result outside the window and the keep set leaves the list
whole. No summary is made of a skill or a tool text, and the index names it, so the model
can read it again.

Four properties hold.

**Nothing is edited.** The compaction applies to the list on its way to the model. The worker
stores the record as a version 2 `compaction` row (`CompactionReport.row`), and each later
call applies it with `run_messages.apply_record`. The transcript keeps every result in full.
`compact` builds its own output with the same function, so a replay gives the same list.

**Each call has one result.** A kept result keeps its `ai` message. A call whose result
leaves the list leaves its `ai` message, and an `ai` message with no call and no text leaves
the list. The provider refuses a request with a call and no result.

**An unknown context window never fires the trigger.** `llm_models.context_window` is 0 when
the provider never stated one, and 0 means no compaction.

**The plan meets the target before the model call.** The sizes are estimates from a ratio of
tokens to characters that the last billed call gives (`Estimator`). When the list still
passes the target, `shrink` makes it smaller in a fixed order. When the parts that
are never compacted pass the target, the smallest list goes, and `target_reached` is false.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import httpx

from research_agent import model_params, thread_index
from research_agent.run_messages import RunMessage, apply_record

log = logging.getLogger(__name__)

GLOBAL_DB = os.getenv("CLICKHOUSE_DATABASE", "Hoover4_Processing")

#: Fraction of the model's context window at which compaction fires. Configuration
#: (`AGENT_COMPACTION_FRACTION`) can change it.
DEFAULT_COMPACTION_FRACTION = 0.80
#: The target of a compaction is this share of the trigger.
TARGET_SHARE = 1 / 3
#: The recent window holds at most this share of the target, and at least one group.
WINDOW_SHARE = 0.25
#: The keep set outside the recent window, user messages included.
KEEP_CAP_TOKENS = 35_000
#: One sub-agent report in the keep set.
REPORT_CAP_TOKENS = 4_000
#: One skill text in the keep set, and all skill texts together.
SKILL_CAP_TOKENS = 5_000
SKILL_TOTAL_TOKENS = 25_000
#: All notes of `write_note` together. The oldest note leaves first.
NOTES_TOTAL_TOKENS = 4_000
#: After a summary, this many `read_documents` results of the compacted part come back,
#: each cut to this size, while the list stays at or under the target.
REREAD_DOCS = 3
REREAD_CAP_TOKENS = 5_000
#: The completion budget of the record, and its smallest value.
RECORD_BUDGET_TOKENS = 2_000
RECORD_MIN_TOKENS = 1_000
#: The results of the recent window are never cut below this size together.
NEWEST_MIN_TOKENS = 500
#: A compacted part above this size gets `PARTS` summary requests at once.
PARTS_ABOVE_TOKENS = 30_000
PARTS = 3
#: The model step sets `note_warning` at this share of the trigger.
NOTE_WARNING_SHARE = 0.90
#: The warning row that the worker writes when `model_turn` sets `note_warning`, and its
#: start. The worker keeps a copy, because the two images share no module.
NOTE_WARNING_HEAD = "Your context is at"
NOTE_WARNING_TEXT = (
    NOTE_WARNING_HEAD + " {pct} percent of its limit. The older steps of this run will soon "
    "be replaced by a record. Save each fact that you need later with `write_note` now."
)
#: The margin of the token estimate.
MARGIN = 1.05
#: What a cut tool result ends with.
CUT_MARK = " [cut to save context]"
#: The chars of one message that no content holds, such as the role.
FRAME_CHARS = 24

#: What an evicted tool result says in the model's place. A version 1 row applies it.
EVICTION_PLACEHOLDER = (
    "[This tool result was evicted to reclaim context. It is unchanged in the "
    "conversation transcript. The call that produced it is shown above. Re-run the tool "
    "if you need its content again.]"
)

#: The start of each record. A `human` message that starts with it is a record, never a
#: user message, and a later compaction summarises it again.
RECORD_HEADER = (
    "[Record of earlier steps. Code wrote the lists of searches and documents. "
    "A model wrote the rest from the steps it replaces. The full steps are in the "
    "transcript.]\n\n"
)
#: The start of a record of a version 1 row.
_V1_RECORD_HEAD = "[Context handoff."

#: The line of a summary part that failed, timed out or gave no text.
PART_FAILED = ("Part {n} of {k}. The summary failed. The lists above name its searches and "
               "documents.")

#: A citation handle as `cite_documents` allocates it and as the model writes it.
CITATION_HANDLE = re.compile(r"\[D\d+\]")

CITATION_TOOLS = frozenset({"cite_documents"})
TODO_TOOLS = frozenset({"read_todo", "write_todo", "edit_todo", "mark_todo"})
PLAN_TOOLS = frozenset({"read_plan", "append_node", "append_child", "move_node", "edit_node",
                        "remove_node"})
REPORT_TOOL = "run_subagent"
NOTE_TOOL = "write_note"
READ_SKILL = "read_skill"
READ_TOOL = "read_tool"
TEXT_TOOLS = frozenset({READ_SKILL, READ_TOOL})
REREAD_TOOL = "read_documents"

#: The request of one summary part. `{notes}` holds the line of a previous record and the
#: line of a part, when they apply.
SUMMARY_PROMPT = """\
You compress the working history of a research agent that continues its work after you. \
The agent keeps its task, the user's messages, its latest todo and plan, and its newest \
steps. The history below (its own older steps, its tool calls and their results) leaves \
its context now, and your record replaces it. Code adds a list of the searches that found \
nothing and of the documents read, so do not repeat those lists.

Use exactly these sections, in this order:

## Goal
The task and the sub-goals that the history shows, in 1 to 3 sentences.

## Findings
One line for each fact that bears on the task. Give a short exact quote in quotation marks, \
then its source: the collection name, the first 16 characters of the file hash, and the \
path, or the URL, or the sub-agent. Copy every number, date, name, amount, count and \
identifier exactly. A fact that a later step can need is a finding, also when it looks minor.

## Open items
The questions that the history raised and did not answer, and the leads not yet followed, \
each with the document or the query that raised it.

## Next steps
The steps the agent planned and did not yet do. Write "unknown" if the history does not say.

Rules: report only what the history below says. Invent nothing. Do not answer the task. \
Keep the record under {words} words.
{notes}
The agent's task:
{task}

--- history being replaced ---
{transcript}
--- end ---
"""
PREVIOUS_RECORD_LINE = ("A previous record exists. Integrate every fact of it that still "
                        "bears on the task.")
PART_LINE = ("The history below is part {n} of {k} of the history being replaced, in order. "
             "Records of the other parts are written apart.")
#: The task in the summary request is cut to this many characters.
TASK_CHARS = 2_000

#: The (connect, read) timeout of a summary request when `LLM_REQUEST_TIMEOUT_SECONDS` is
#: unset: the read timeout of a model call.
_SUMMARISER_TIMEOUT = (5.0, 3600.0)

#: How long a context window read from the catalog is trusted before it is read again.
_WINDOW_TTL_SECONDS = 300

_window_cache: dict[str, tuple[float, int]] = {}

Key = Tuple[str, int]
#: A summariser takes the prompt and the completion cap, and returns the text.
Summariser = Callable[[str, int], str]


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
    """Token sizes before the model call, from a ratio that the last billed call gives."""

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


# ------------------------------------------------------------------------- layout


def _key(m: RunMessage) -> Optional[Key]:
    if m.thread_id is None or m.idx is None:
        return None
    return (str(m.thread_id), int(m.idx))


def is_record(m: RunMessage) -> bool:
    """Whether a `human` message is a compaction record."""
    text = m.content or ""
    return m.role == "human" and (text.startswith(RECORD_HEADER[:40])
                                  or text.startswith(_V1_RECORD_HEAD))


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


def recent_window(groups: Sequence[List[int]], msgs: Sequence[RunMessage], est: Estimator,
                  target: int) -> int:
    """The index of the first group of the recent window: the newest groups up to
    `WINDOW_SHARE` of the target, and at least the newest group."""
    start, used = len(groups), 0
    for g in range(len(groups) - 1, -1, -1):
        cost = sum(est.tokens(msgs[i]) for i in groups[g])
        if start < len(groups) and used + cost > WINDOW_SHARE * target:
            break
        start, used = g, used + cost
    return start


@dataclass
class Layout:
    """The plan of one compaction, by index into the applied list."""

    msgs: List[RunMessage]
    groups: List[List[int]]
    names: Dict[int, str]
    window_start: int
    #: Kept results outside the window: state, citations and notes.
    fixed_keep: Set[int] = field(default_factory=set)
    #: Kept reports and skills outside the window, oldest first.
    reports: List[int] = field(default_factory=list)
    skills: List[int] = field(default_factory=list)
    rereads: List[int] = field(default_factory=list)
    #: A cap in tokens for a kept `tool` result.
    cuts: Dict[int, int] = field(default_factory=dict)
    budget: int = RECORD_BUDGET_TOKENS
    steps: List[str] = field(default_factory=list)
    target_reached: bool = True

    def window(self) -> Set[int]:
        return {i for g in self.groups[self.window_start:] for i in g}

    def classify(self) -> Tuple[Set[int], Set[int], List[int], List[int]]:
        """(kept, text_removed, summarised, dropped) for the messages outside the window.
        The window messages are kept."""
        window = self.window()
        results = set(self.fixed_keep) | set(self.reports) | set(self.skills) | set(self.rereads)
        kept: Set[int] = set(window)
        blank: Set[int] = set()
        gone: List[int] = []
        drop: List[int] = []
        members = {g[0]: g for g in self.groups}
        for i, m in enumerate(self.msgs):
            if i in window:
                continue
            if m.role == "human":
                (gone.append(i) if is_record(m) else kept.add(i))
            elif m.role == "tool":
                if i in results:
                    kept.add(i)
                elif self.names.get(i) in TEXT_TOOLS:
                    drop.append(i)
                else:
                    gone.append(i)
            elif m.role == "ai":
                own = [j for j in members.get(i, [i]) if j != i]
                handle = bool(CITATION_HANDLE.search(m.content or ""))
                if handle or any(j in results for j in own):
                    kept.add(i)
                    if not handle and (m.content or "").strip():
                        blank.add(i)
                else:
                    gone.append(i)
        return kept, blank, gone, drop

    def row(self, est: Estimator, handoff: str) -> Dict[str, Any]:
        """The keys of a version 2 record for this layout."""
        kept, blank, gone, drop = self.classify()

        def keys(indexes) -> List[List[Any]]:
            return [[k[0], k[1]] for i in sorted(indexes) for k in [_key(self.msgs[i])] if k]

        cuts = []
        for i in sorted(self.cuts):
            k = _key(self.msgs[i])
            chars = est.chars_for(self.cuts[i])
            if k and i in kept and len(self.msgs[i].content or "") > chars:
                cuts.append([k[0], k[1], chars])
        return {"version": 2, "layer": "record", "summarised": keys(gone),
                "text_removed": keys(blank), "dropped": keys(drop), "cuts": cuts,
                "handoff": handoff}


def _names(msgs: Sequence[RunMessage]) -> Dict[int, str]:
    """The tool name of each `tool` message, from its call."""
    calls = {c.id: c.name for m in msgs if m.role == "ai" for c in m.tool_calls}
    return {i: calls.get(m.tool_call_id or "", m.name or "") for i, m in enumerate(msgs)
            if m.role == "tool"}


def _ok(m: RunMessage) -> bool:
    return m.status != "error"


def _skill_name(msgs: Sequence[RunMessage], i: int) -> str:
    call_id = msgs[i].tool_call_id
    for m in msgs:
        if m.role == "ai":
            for c in m.tool_calls:
                if c.id == call_id:
                    return str((c.args or {}).get("name") or "")
    return ""


def initial_layout(msgs: List[RunMessage], est: Estimator, target: int,
                   window_start: Optional[int] = None) -> Layout:
    """The recent window and the keep set with its caps. With `window_start`, the window
    starts at that group, else `recent_window` sets it."""
    groups = step_groups(msgs)
    names = _names(msgs)
    start = recent_window(groups, msgs, est, target) if window_start is None else window_start
    layout = Layout(msgs=msgs, groups=groups, names=names, window_start=start)
    window = layout.window()
    tools = [i for i, m in enumerate(msgs) if m.role == "tool"]
    for family in (TODO_TOOLS, PLAN_TOOLS):
        newest = [i for i in tools if names[i] in family and _ok(msgs[i])]
        if newest and newest[-1] not in window:
            layout.fixed_keep.add(newest[-1])
    outside = [i for i in tools if i not in window]
    layout.fixed_keep |= {i for i in outside if names[i] in CITATION_TOOLS}
    layout.reports = [i for i in outside if names[i] == REPORT_TOOL]
    for i in layout.reports:
        layout.cuts[i] = REPORT_CAP_TOKENS
    newest_skill: Dict[str, int] = {}
    for i in tools:
        if names[i] == READ_SKILL and _ok(msgs[i]):
            newest_skill[_skill_name(msgs, i)] = i
    layout.skills = sorted(i for i in newest_skill.values() if i not in window)
    for i in layout.skills:
        layout.cuts[i] = SKILL_CAP_TOKENS
    while sum(min(est.tokens(msgs[i]), SKILL_CAP_TOKENS) for i in layout.skills) \
            > SKILL_TOTAL_TOKENS:
        layout.cuts.pop(layout.skills.pop(0), None)
    notes = [i for i in outside if names[i] == NOTE_TOOL and _ok(msgs[i])]
    while sum(est.tokens(msgs[i]) for i in notes) > NOTES_TOTAL_TOKENS:
        notes.pop(0)
    layout.fixed_keep |= set(notes)
    return layout


class Sizer:
    """The sizes of a layout, from the list that its record gives."""

    def __init__(self, rows: Sequence[RunMessage], est: Estimator):
        self.rows = list(rows)
        self.est = est

    def index(self, layout: Layout) -> str:
        kept, _blank, _gone, _drop = layout.classify()
        cut_keys = {k for i in layout.cuts for k in [_key(layout.msgs[i])] if k}
        present = {k for i in kept if layout.msgs[i].role == "tool"
                   for k in [_key(layout.msgs[i])] if k}
        return thread_index.render(self.rows, visible_after=present - cut_keys,
                                   present_after=present)

    def visible(self, layout: Layout, handoff: str) -> List[RunMessage]:
        return apply_record(layout.msgs, layout.row(self.est, handoff))

    def rest(self, layout: Layout) -> int:
        """The fixed part, the kept messages, the window and the record without its body."""
        visible = self.visible(layout, RECORD_HEADER + self.index(layout))
        return self.est.fixed + self.est.list_size(visible)

    def keep_outside_window(self, layout: Layout) -> int:
        window = {k for i in layout.window() for k in [_key(layout.msgs[i])] if k}
        visible = self.visible(layout, "")
        return sum(self.est.tokens(m) for m in visible if _key(m) not in window)

    def window_results(self, layout: Layout) -> List[int]:
        return [i for i in sorted(layout.window()) if layout.msgs[i].role == "tool"]


def shrink(layout: Layout, sizer: Sizer, target: int) -> Layout:
    """Reach the target before any model call, in the shrink order.

    1. The oldest groups of the recent window leave it, down to the newest group.
    2. The oldest reports move to the compacted part, then the oldest skills leave the
       list, while the list passes the target or the keep set passes its cap.
    3. The record budget falls, down to `RECORD_MIN_TOKENS`.
    4. The results of the newest group are cut, to at least `NEWEST_MIN_TOKENS`.
    """
    budget = RECORD_BUDGET_TOKENS
    if sizer.rest(layout) + budget <= target \
            and sizer.keep_outside_window(layout) <= KEEP_CAP_TOKENS:
        layout.budget = budget
        return layout
    while len(layout.groups) - layout.window_start > 1 \
            and sizer.rest(layout) + RECORD_MIN_TOKENS > target:
        steps = layout.steps
        layout = initial_layout(layout.msgs, sizer.est, target, layout.window_start + 1)
        layout.steps = steps + ["window"]
    while (layout.reports or layout.skills) and (
            sizer.rest(layout) + RECORD_MIN_TOKENS > target
            or sizer.keep_outside_window(layout) > KEEP_CAP_TOKENS):
        if layout.reports:
            layout.cuts.pop(layout.reports.pop(0), None)
            layout.steps.append("report")
        else:
            layout.cuts.pop(layout.skills.pop(0), None)
            layout.steps.append("skill")
    rest = sizer.rest(layout)
    if rest + RECORD_MIN_TOKENS <= target:
        layout.budget = min(budget, target - rest)
        if layout.budget < budget:
            layout.steps.append("budget")
        return layout
    results = sizer.window_results(layout)
    newest = sum(sizer.est.tokens(layout.msgs[i]) for i in results)
    room = max(NEWEST_MIN_TOKENS, target - (rest - newest) - RECORD_MIN_TOKENS)
    for i in results:
        share = sizer.est.tokens(layout.msgs[i]) / max(newest, 1)
        layout.cuts[i] = min(layout.cuts.get(i, room), max(1, int(room * share)))
    layout.steps.append("newest")
    layout.budget = RECORD_MIN_TOKENS
    layout.steps.append("budget")
    if sizer.rest(layout) + RECORD_MIN_TOKENS > target:
        layout.target_reached = False
    return layout


def add_rereads(layout: Layout, sizer: Sizer, target: int) -> Layout:
    """The newest `REREAD_DOCS` successful `read_documents` results of the
    compacted part come back, newest first, each cut to `REREAD_CAP_TOKENS`. A result comes
    back only when the list then stays at or under the target."""
    _kept, _blank, gone, _drop = layout.classify()
    candidates = [i for i in reversed(gone) if layout.msgs[i].role == "tool"
                  and layout.names.get(i) == REREAD_TOOL and _ok(layout.msgs[i])]
    for i in candidates[:REREAD_DOCS]:
        layout.rereads.append(i)
        layout.cuts[i] = REREAD_CAP_TOKENS
        if sizer.rest(layout) + layout.budget > target:
            layout.rereads.remove(i)
            layout.cuts.pop(i, None)
    return layout


# ------------------------------------------------------------------------ summary


def _call_text(name: str, args: Dict[str, Any]) -> str:
    return f"{name}({json.dumps(args or {}, ensure_ascii=False, sort_keys=True)})"


def compacted_blocks(layout: Layout, est: Estimator) -> List[Tuple[str, int, bool]]:
    """The compacted part as text blocks for the summariser, in list order: (text, tokens,
    starts a group). No block holds a `read_skill` or `read_tool` call or result. An `ai`
    message that keeps its place gives its text and its compacted calls."""
    kept, blank, gone, _drop = layout.classify()
    gone_set = set(gone)
    results = {layout.msgs[i].tool_call_id: i for i in range(len(layout.msgs))
               if layout.msgs[i].role == "tool"}
    blocks: List[Tuple[str, int, bool]] = []
    for i in sorted(gone_set | blank):
        m = layout.msgs[i]
        if m.role == "tool":
            call = next((c for x in layout.msgs if x.role == "ai" for c in x.tool_calls
                         if c.id == m.tool_call_id), None)
            head = _call_text(call.name, call.args) if call else (m.name or "tool")
            text = f"[result of {head}]\n{m.content}"
        elif m.role == "ai":
            calls = [c for c in m.tool_calls if c.name not in TEXT_TOOLS
                     and results.get(c.id) in gone_set]
            label = "assistant"
            if calls:
                label += " calling " + ", ".join(_call_text(c.name, c.args) for c in calls)
            content = (m.content or "").strip()
            if not calls and not content:
                continue
            text = f"[{label}]\n{content}".rstrip()
        else:
            text = f"[earlier record]\n{m.content}"
        blocks.append((text, est.tokens_text(text) + est.tokens_text(" " * FRAME_CHARS),
                       m.role != "tool"))
    return blocks


def split_at_groups(blocks: Sequence[Tuple[str, int, bool]], k: int) -> List[List[str]]:
    """`k` pieces in order, of about equal tokens, each starting at a group."""
    total = sum(b[1] for b in blocks)
    pieces: List[List[str]] = [[]]
    acc = 0
    for text, tokens, starts in blocks:
        if starts and pieces[-1] and len(pieces) < k and acc >= total * len(pieces) / k:
            pieces.append([])
        pieces[-1].append(text)
        acc += tokens
    return pieces


def render_prompt(piece: Sequence[str], task: str, n: int, k: int, max_tokens: int,
                  previous: bool) -> str:
    """The request of one summary part."""
    notes = []
    if previous:
        notes.append(PREVIOUS_RECORD_LINE)
    if k > 1:
        notes.append(PART_LINE.format(n=n, k=k))
    return SUMMARY_PROMPT.format(
        words=max(100, int(0.6 * max_tokens)),
        notes=("\n" + "\n".join(notes) + "\n") if notes else "",
        task=(task or "")[:TASK_CHARS],
        transcript="\n\n".join(piece),
    )


def summarise_parts(blocks: Sequence[Tuple[str, int, bool]], *, task: str, budget: int,
                    summariser: Summariser, previous: bool = False
                    ) -> Tuple[str, List[str]]:
    """One request for a compacted part up to `PARTS_ABOVE_TOKENS`, else
    `PARTS` requests at once, each with a third of the budget as its completion cap. A part
    that fails, raises or gives no text gets the `PART_FAILED` line. Returns the body and
    the state of each part, `ok` or `failed`."""
    total = sum(b[1] for b in blocks)
    k = PARTS if total > PARTS_ABOVE_TOKENS else 1
    pieces = split_at_groups(blocks, k)
    k = len(pieces)
    cap = max(1, budget // k)
    prompts = [render_prompt(piece, task, n + 1, k, cap, previous)
               for n, piece in enumerate(pieces)]

    def one(prompt: str) -> str:
        try:
            return (summariser(prompt, cap) or "").strip()
        except Exception as exc:  # noqa: BLE001 -- a failed part is a line of the record
            log.warning("a summary part failed: %s", exc)
            return ""

    with ThreadPoolExecutor(max_workers=k) as pool:
        texts = list(pool.map(one, prompts))
    states = ["ok" if t else "failed" for t in texts]
    parts = [t or PART_FAILED.format(n=i + 1, k=k) for i, t in enumerate(texts)]
    body = parts[0] if k == 1 else "\n\n".join(
        f"Part {i + 1} of {k}:\n{p}" for i, p in enumerate(parts))
    return body, states


def summarise_with_model(prompt: str, *, model_id: str, max_tokens: int) -> str:
    """Ask the compaction model for one summary part. An empty string on any failure.

    `LLM_MODEL_COMPACTION` names the model, else the answering model. Thinking is off: a
    thinking model given a transcript reasons about its content and starts to answer the
    task (`research_agent/thinking.py`).
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
        with httpx.Client(timeout=summariser_timeout()) as client:
            response = client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={
                    "model": model,
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
            if (m.content or "").endswith(CUT_MARK):
                detail += " CUT"
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
    layer: str = "record"
    tokens_before: int = 0
    tokens_after: int = 0
    context_window: int = 0
    threshold_tokens: int = 0
    target: int = 0
    est_after: int = 0
    target_reached: bool = True
    steps: List[str] = field(default_factory=list)
    parts: List[str] = field(default_factory=list)
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
    #: The content of the version 2 `compaction` row.
    row: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompactionPlan:
    """A compaction planned before any model call. `finish_compaction` summarises it."""

    applied: List[RunMessage]
    rows: List[RunMessage]
    layout: Layout
    est: Estimator
    sizer: Sizer
    index: str
    blocks: List[Tuple[str, int, bool]]
    model_id: str
    window: int
    trigger: int
    target: int
    billed: int

    @property
    def parts(self) -> int:
        return PARTS if sum(b[1] for b in self.blocks) > PARTS_ABOVE_TOKENS else 1


def plan_compaction(applied: Sequence[RunMessage], rows: Sequence[RunMessage], *,
                    system_text: str = "", schemas_json: str = "", model_id: str = "",
                    window: Optional[int] = None, fraction: Optional[float] = None,
                    estimator: Optional[Estimator] = None) -> Optional[CompactionPlan]:
    """The plan of a compaction, with no model call. `None` when the trigger does not fire or
    nothing is outside the keep set and the window.

    `applied` is the list after the stored compactions, `rows` the stored thread.
    """
    applied = list(applied)
    resolved = context_window(model_id) if window is None else int(window)
    trigger = threshold_tokens(resolved, fraction)
    billed = last_billed(applied)
    if trigger <= 0 or billed < trigger:
        return None
    target = target_tokens(trigger)
    est = estimator or Estimator.calibrate(applied, system_text, schemas_json)
    sizer = Sizer(rows, est)
    layout = shrink(initial_layout(applied, est, target), sizer, target)
    _kept, _blank, gone, _drop = layout.classify()
    if not gone:
        log.warning("compaction threshold %d crossed at %d tokens, and nothing is outside "
                    "the keep set and the recent window", trigger, billed)
        return None
    layout = add_rereads(layout, sizer, target)
    return CompactionPlan(applied=applied, rows=list(rows), layout=layout, est=est,
                          sizer=sizer, index=sizer.index(layout),
                          blocks=compacted_blocks(layout, est), model_id=model_id or "",
                          window=resolved, trigger=trigger, target=target, billed=billed)


def finish_compaction(plan: CompactionPlan, summariser: Optional[Summariser] = None
                      ) -> Tuple[List[RunMessage], CompactionReport]:
    """The summary, the record, the list and the report of a planned compaction."""
    layout, est = plan.layout, plan.est
    call = summariser or (lambda prompt, cap: summarise_with_model(
        prompt, model_id=plan.model_id, max_tokens=cap))
    task = next((m.content for m in plan.applied if m.role == "human" and not is_record(m)), "")
    _kept, _blank, gone, _drop = layout.classify()
    previous = any(plan.applied[i].role == "human" for i in gone)
    body, states = summarise_parts(plan.blocks, task=task, budget=layout.budget,
                                   summariser=call, previous=previous)
    record = RECORD_HEADER + plan.index + ("\n\n" + body if body else "")
    row = layout.row(est, record)
    out = apply_record(plan.applied, row)
    est_after = est.fixed + est.list_size(out)
    window_keys = {k for i in layout.window() for k in [_key(plan.applied[i])] if k}
    user = sum(est.tokens(m) for m in out if m.role == "human" and not is_record(m))
    window_size = sum(est.tokens(m) for m in out if _key(m) in window_keys)
    record_size = sum(est.tokens(m) for m in out if is_record(m))
    sizes = {"fixed": est.fixed, "user": user,
             "keep": max(0, est.list_size(out) - user - window_size - record_size),
             "window": window_size, "index": est.tokens_text(plan.index)}
    reached = est_after <= plan.target
    steps_summarised = sum(1 for i in gone if plan.applied[i].role == "ai")
    row.update({
        "tokens_before": plan.billed, "threshold": plan.trigger, "target": plan.target,
        "est_after": est_after, "target_reached": reached, "steps": list(layout.steps),
        "parts": states, "steps_summarised": steps_summarised, "sizes": sizes,
    })
    report = CompactionReport(
        compaction_id=uuid.uuid4().hex, tokens_before=plan.billed,
        context_window=plan.window, threshold_tokens=plan.trigger, target=plan.target,
        est_after=est_after, target_reached=reached, steps=list(layout.steps), parts=states,
        steps_summarised=steps_summarised, sizes=sizes,
        messages_before=len(plan.applied), messages_after=len(out),
        chars_before=sum(len(m.content or "") for m in plan.applied),
        chars_after=sum(len(m.content or "") for m in out), model_id=plan.model_id,
        summary=record, summarised_count=len(row["summarised"]),
        preserved_count=max(0, len(out) - 1), handles=issued_citations(plan.applied),
        list_before=summarise_list(plan.applied), list_after=summarise_list(out), row=row,
    )
    log.info("compacted context %s: %d tokens over trigger %d, target %d, estimate after %d, "
             "steps %s, parts %s\nmodel-visible list AFTER:\n%s", report.compaction_id,
             plan.billed, plan.trigger, plan.target, est_after, layout.steps or "none",
             states, report.list_after)
    if not reached:
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


def fixed_part_passes_target(applied: Sequence[RunMessage], system_text: str,
                             schemas_json: str, window: int) -> bool:
    """Whether the system text, the schemas and the user messages pass the target, at 3
    characters a token. The first model step of a run logs a warning when they do."""
    target = target_tokens(threshold_tokens(window))
    if target <= 0:
        return False
    chars = len(system_text or "") + len(schemas_json or "") + sum(
        len(m.content or "") for m in applied if m.role == "human" and not is_record(m))
    return chars / 3 > target


def note_warning_due(rows: Sequence[RunMessage], usage: Dict[str, Any], has_calls: bool,
                     window: int) -> bool:
    """Whether the worker writes the note warning after this reply.

    The reply's input plus output tokens are at or above `NOTE_WARNING_SHARE` of the
    trigger, the reply has calls, and no warning follows the newest `compaction` row.
    """
    trigger = threshold_tokens(window)
    used = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    if trigger <= 0 or not has_calls or used < NOTE_WARNING_SHARE * trigger:
        return False
    for m in reversed(list(rows)):
        if m.role == "compaction":
            return True
        if m.role == "human" and (m.content or "").startswith(NOTE_WARNING_HEAD):
            return False
    return True


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
        "layer": report.layer or "record",
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
        with httpx.Client(timeout=(2.0, 5.0), auth=_auth()) as client:
            r = client.post(
                f"{base}/",
                params={"database": GLOBAL_DB,
                        "query": "INSERT INTO chat_compactions FORMAT JSONEachRow"},
                content=json.dumps(row, ensure_ascii=False).encode("utf-8"),
            )
            if r.status_code >= 300:
                log.warning("chat_compactions insert failed status=%s body=%s",
                            r.status_code, r.text[:200])
    except Exception as exc:  # noqa: BLE001 -- the trail must not break a chat turn
        log.warning("chat_compactions insert failed: %s", exc)


def describe() -> str:
    """One line for the startup log, so a deployment says what its trigger is."""
    fraction = compaction_fraction()
    if fraction <= 0:
        return "context compaction: off"
    summariser = (os.getenv("LLM_MODEL_COMPACTION") or "").strip() or "the answering model"
    return (
        # `:g`, because a test lowers the fraction, and "0%" would read as off.
        f"context compaction: at {fraction * 100:g}% of the model's stated context window, "
        f"to a third of that, with a record summarised by {summariser}"
    )
