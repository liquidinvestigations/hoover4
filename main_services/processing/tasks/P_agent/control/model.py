"""The types of the chat control policy: hooks, rules, events, checks and actions.

A workflow definition is plain JSON. `definitions.resolve` validates it into these types.
Every type is frozen, and `freeze` turns nested mappings and lists into read-only views, so
a handler cannot change the parameters or the context that it receives.

`digest` is the identity of a JSON value: SHA-256 over canonical JSON with sorted keys and
no non-finite numbers. `action_id` derives the identity of one action from its event, its
rule revision, its target and its position, so a retry of the same decision gives the same
identities. No timestamp or process id enters an identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence

Hook = Literal["turn_started", "tool_batch_completed", "answer_drafted"]
HOOKS: tuple[str, ...] = ("turn_started", "tool_batch_completed", "answer_drafted")
Status = Literal["pass", "defect", "unknown", "skipped", "error"]
STATUSES: tuple[str, ...] = ("pass", "defect", "unknown", "skipped", "error")
Frequency = Literal["event", "turn", "visible_revision"]
FREQUENCIES: tuple[str, ...] = ("event", "turn", "visible_revision")
ActionKind = Literal["load_skill", "append_note", "call_tools", "repair", "end_turn"]
ACTION_KINDS: tuple[str, ...] = ("load_skill", "append_note", "call_tools", "repair", "end_turn")

#: The interface version that every handler of this worker implements.
API_VERSION = 1


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, no spaces, UTF-8 text, and no NaN or infinity."""
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    """The SHA-256 of the canonical JSON of `value`."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def action_id(event_id: str, rule_revision: str, target: str, position: int) -> str:
    """The stable identity of one action of one decision."""
    return digest([event_id, rule_revision, target, int(position)])


def _plain(value: Any) -> Any:
    """A frozen value as plain JSON types, for hashing and storage."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def plain(value: Any) -> Any:
    """`value` with every read-only view turned back into a dict or a list."""
    return _plain(value)


def freeze(value: Any) -> Any:
    """A read-only copy: mappings become `MappingProxyType`, lists become tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, float) and value != value:  # NaN
        raise ValueError("a control value cannot be NaN")
    return value


@dataclass(frozen=True)
class HandlerRef:
    name: str
    api_version: int
    code_digest: str


@dataclass(frozen=True)
class Rule:
    id: str
    hook: Hook
    handler: HandlerRef
    parameters: Mapping[str, Any]
    priority: int
    frequency: Frequency
    #: The digest of the handler identity and the normalized parameters.
    revision: str = ""
    requires_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ControlEvent:
    id: str
    hook: Hook
    #: The thread index of the row that the event follows: the opening row, the `ai`
    #: message of the batch, or the `ai` message of the draft.
    anchor_idx: int
    origin: Literal["model", "policy", "runtime"]
    draft_kind: Optional[Literal["answer", "question"]] = None


@dataclass(frozen=True)
class CheckResult:
    rule_id: str
    target_id: str
    status: Status
    score: Optional[float]
    input_refs: tuple[str, ...]
    reason: str
    #: Details for the record, such as the scores of a choice. Never shown to the model.
    detail: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target_id: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class PolicyResult:
    checks: tuple[CheckResult, ...] = ()
    actions: tuple[Action, ...] = ()
    #: Values that later hooks of the turn read, such as the source class and the
    #: requirements of the preparation. Stored with the decision.
    facts: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Requirement:
    """One condition of a correct answer.

    `scope` is `whole`, `item` or `relation`. `basis` is `output_form`, `source` or
    `evidence`. `explicit` is true only when `words` occur in the request, so a generated
    condition that the request does not state stays inferred.
    """

    text: str
    scope: str
    basis: str
    explicit: bool
    words: str = ""


@dataclass(frozen=True)
class PolicyContext:
    """A read-only view of one turn for one event.

    `request` contains the original user message. `results` contains the current thread's
    result facts, from `facts.result_facts`. `batch` contains this event's result facts.
    `turn` contains earlier decision facts and bounded prior conversation context.
    Handlers read large texts through `PolicyServices` references.
    """

    run_id: str
    thread_id: str
    profile: str
    definition_revision: str
    request: str
    callable_tools: frozenset
    listed_skills: Mapping[str, Any]
    visible_skills: frozenset
    results: tuple
    batch: tuple
    turn: Mapping[str, Any]
    counters: Mapping[str, int]
    draft: str = ""
    capabilities: frozenset = frozenset()
    collections: tuple[str, ...] = ()
    recent_steps: str = ""


class PolicyServices(Protocol):
    """The operations that handlers may use. Each honors the hook's remaining deadline
    and the activity's cancellation."""

    async def ask(self, state: Mapping[str, Any], questions: Mapping[str, Any],
                  instructions: str = "") -> "ClassifierResult": ...

    async def complete(self, prompt: str, max_tokens: int = 300) -> "ClassifierResult": ...

    async def suggestions(self, names: Sequence[str], kind: str = "pages",
                          collections: Sequence[str] = ()) -> Mapping[str, Any]: ...

    def message_text(self, ref: str) -> str: ...

    def remaining(self) -> float: ...


@dataclass(frozen=True)
class ClassifierResult:
    """The outcome of one classifier request.

    `status` is `ok`, `skipped` (no question was asked), `malformed`, `timeout`,
    `unavailable` or `http_error`. `answers` maps each question id to its validated
    answer. A missing or malformed answer is absent, never a score of zero.
    """

    status: str
    answers: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    text: str = ""
    model: str = ""
    duration_ms: int = 0
    error: str = ""
    asked: int = 0


class PolicyHandler(Protocol):
    api_version: int

    def validate(self, parameters: Mapping[str, Any]) -> None: ...

    async def evaluate(self, event: ControlEvent, context: PolicyContext,
                       parameters: Mapping[str, Any],
                       services: PolicyServices) -> PolicyResult: ...


def check_dict(check: CheckResult) -> dict:
    return {"rule_id": check.rule_id, "target_id": check.target_id, "status": check.status,
            "score": check.score, "input_refs": list(check.input_refs),
            "reason": check.reason, "detail": plain(check.detail)}


def noul(result: ClassifierResult, qid: str) -> Optional[float]:
    """The yes probability of one answered `noul` question, or None."""
    value = result.answers.get(qid)
    if isinstance(value, Mapping) and isinstance(value.get("noul"), (int, float)):
        return float(value["noul"])
    return None


def ranked(items: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    """Items by full-precision score, highest first, and by name for equal scores."""
    return sorted(items, key=lambda kv: (-kv[1], kv[0]))
