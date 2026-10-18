"""The board command writer: one serialized writer of the canonical state of each board.

Every board state change is a command. The website writes the commands of a person, and the
board activities write the commands of the dispatcher, the assessments and the explores.
`BoardCommands` (`command_workflows.py`) runs `board_command_step` for one board at a time,
so the commands of a board are handled one after another.

One command goes through three steps:

1. **Prepare.** The writer folds the committed events, checks the command against that state,
   allocates the ids of new nodes, and freezes every row that the command writes (events,
   facts, citations and labels) with fixed times and sequence numbers in a `prepared`
   receipt. A refused command gets a `rejected` receipt with its reason and writes nothing.
2. **Apply.** The writer writes the facts and citations, then the labels, then the events.
3. **Commit.** The receipt becomes `committed`.

A prepared receipt is applied before any other input is read, so a retry after a crash writes
the same rows again and never allocates a second id. The receipt keeps the request identity
after the closed workflow history is gone.

**Node identity.** `board_node_identity_version` 2 gives each new node a permanent slug id:
`intent-<words>`, `fact-<words>`, `correction-<words>`, `goal-01` to `goal-06` and
`background`. A collision with another node id, slug or reservation of the board takes `-2`,
`-3` and so on. The words come from the model's candidate, else from the node text, else
from a word of the node kind. Version 1, the value of an absent setting, keeps the legacy
forms. Existing nodes keep their ids in both versions.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime

from tasks.P_board import model as m
from tasks.P_board.contracts import STOP_WORDS, TYPE_WORDS, slug_words
from tasks.P_board.fold import Folded, canonical_events, explores_left, fold, may_explore, visible_facts
from tasks.P_board.prompts import strip_labels

log = logging.getLogger(__name__)

#: The `server_settings` key of the identity format of new nodes. Absent reads as 1.
IDENTITY_SETTING = "board_node_identity_version"
#: The identity format that gives new nodes slug ids.
SLUG_IDENTITY = 2

# Command kinds of a person. The website writes them.
CREATE_BOARD = "create_board"
ADD_HINT = "add_hint"
REJECT_FACT = "reject_fact"
SET_PAUSED = "set_paused"
SET_INTERNET_TOOLS = "set_internet_tools"
REVIEW_DECISION = "review_decision"
ANSWER_DECISION = "answer_decision"
ADD_GOAL = "add_goal"
EXPLORE_QUESTION = "explore_question"
EXTEND_BUDGET = "extend_budget"
PERSON_KINDS = (CREATE_BOARD, ADD_HINT, REJECT_FACT, SET_PAUSED, SET_INTERNET_TOOLS, REVIEW_DECISION,
                ANSWER_DECISION, ADD_GOAL, EXPLORE_QUESTION, EXTEND_BUDGET)

# Command kinds of the worker.
START_REASON = "start_reason"
REASON_RESULT = "reason_result"
START_EXPLORE = "start_explore"
EXPLORE_END = "explore_end"
REVIEW_PROPOSED = "review_proposed"
FINAL_ENDED = "final_ended"
ASSIGN_LABELS = "assign_labels"
#: The commands that start work. The dispatcher counts their pending inputs as taken slots.
START_KINDS = (START_REASON, START_EXPLORE)

#: The words of a slug when neither the candidate nor the text has one.
KIND_WORDS = {"intent": "direction", "fact": "finding", "correction": "note"}
#: Ids that no new slug takes.
RESERVED = ({m.BACKGROUND_ID, m.ORIGIN, m.FIRST_GOAL_ID}
            | {m.goal_id_for(n) for n in range(2, 100)} | {m.goal_slot_id(n) for n in range(1, 100)})

LIMIT_TEXT = (f"The board used its {m.EXPLORE_LIMIT} explores, the limit of one board. "
              "Create a new board to continue.")


class Rejected(Exception):
    """A command that the committed state refuses. Its text is shown to the person."""


@dataclass
class Prepared:
    """The frozen rows of one command."""

    events: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)
    #: Creation key to the node id that the command allocated.
    assignments: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)


@dataclass
class Context:
    """The committed state that a command is prepared against."""

    board: object
    events: list
    facts: list
    all_facts: list
    folded: Folded
    labels: dict
    #: Creation key to node id, from every earlier receipt of the board.
    assignments: dict
    version: int
    now: datetime
    request_id: str = ""
    actor: str = ""


def identity_version() -> int:
    from database.clickhouse import get_server_setting

    try:
        return int((get_server_setting(IDENTITY_SETTING) or "1").strip())
    except (TypeError, ValueError):
        return 1


def activate_slug_identity() -> tuple[int, int]:
    """Set `IDENTITY_SETTING` to `SLUG_IDENTITY` once the command storage exists. Returns the
    version before and after. A second call changes nothing. The admin settings page does not
    show the setting and refuses it, so this deployment step is the only writer."""
    from database.boards import now
    from database.clickhouse import get_global_client, insert_durable

    before = identity_version()
    if before >= SLUG_IDENTITY:
        return before, before
    with get_global_client() as client:
        tables = {row[0] for row in client.query(
            "SELECT name FROM system.tables WHERE database = currentDatabase() "
            "AND name IN ('board_command_inputs', 'board_command_receipts')").result_rows}
        columns = client.query(
            "SELECT count() FROM system.columns WHERE database = currentDatabase() "
            "AND table = 'board_facts' AND name = 'request_id'").result_rows[0][0]
        if len(tables) != 2 or not columns:
            raise RuntimeError("the board command storage is missing: run the migrations first")
        insert_durable(client, "server_settings", [[IDENTITY_SETTING, str(SLUG_IDENTITY), now()]],
                       column_names=["key", "value", "updated_at"])
    return before, identity_version()


def slug_stem(candidate: str, text: str, kind: str) -> str:
    """The words of a new slug: the candidate's words, else the text's words, else the word
    of the kind. Type words and stop words are left out, at most 4 words and 40 characters."""
    for source in (candidate, strip_labels(text or "")):
        words = [w for w in slug_words(str(source or "").replace("-", " "), 40)
                 if w not in TYPE_WORDS and w not in STOP_WORDS]
        stem = "-".join(slug_words(" ".join(words), 4))
        if stem:
            return stem
    return KIND_WORDS.get(kind, kind)


class Allocator:
    """The node ids of one command, unique in the board namespace."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.assigned: dict = {}
        self.taken = set(RESERVED)
        self.taken |= {f.fact_id for f in ctx.all_facts}
        self.taken |= set(ctx.folded.intents)
        self.taken |= {e.subject for e in ctx.events if e.event_type == m.QUESTION_EXPLORED}
        self.taken |= {row.slug for row in ctx.labels.values() if row.slug}
        self.taken |= set(ctx.assignments.values())

    def claim(self, kind: str, candidate: str, text: str, creation_key: str) -> str:
        """The permanent id of a new node. A creation key that an earlier receipt allocated
        keeps its id."""
        known = self.ctx.assignments.get(creation_key) or self.assigned.get(creation_key)
        if known:
            return known
        base = f"{kind}-{slug_stem(candidate, text, kind)}"
        node_id, number = base, 2
        while node_id in self.taken:
            node_id, number = f"{base}-{number}", number + 1
        return self.take(creation_key, node_id)

    def take(self, creation_key: str, node_id: str) -> str:
        self.taken.add(node_id)
        self.assigned[creation_key] = node_id
        return node_id

    @property
    def slugs(self) -> bool:
        return self.ctx.version >= SLUG_IDENTITY


def _event(ctx: Context, prepared: Prepared, event_type: str, subject: str, payload: dict,
           event_id: str, actor: str = "") -> None:
    prepared.events.append({"event_id": event_id, "event_type": event_type,
                            "actor": actor or ctx.actor, "subject": subject, "payload": dict(payload)})


def _fact(ctx: Context, prepared: Prepared, fact_id: str, kind: str, text: str, created_by: str,
          intent_id: str = "", session_id: str = "", answer_seq: int = 0,
          open_questions: list | None = None, problems: list | None = None) -> None:
    prepared.facts.append({"fact_id": fact_id, "kind": kind, "text": text, "intent_id": intent_id,
                           "session_id": session_id, "answer_seq": int(answer_seq),
                           "open_questions": list(open_questions or []), "problems": list(problems or []),
                           "created_by": created_by})


def _label(alloc: Allocator, prepared: Prepared, node_id: str, kind: str) -> None:
    """A new slug node gets its label row at once: its slug is its id. The label activity
    adds the title and the summary later and keeps the slug."""
    if alloc.slugs:
        prepared.labels.append({"node_id": node_id, "node_kind": kind, "slug": node_id})


def _live(ctx: Context) -> None:
    if ctx.folded.status == m.DROPPED:
        raise Rejected("The board is dropped.")


def _not_at_limit(ctx: Context) -> None:
    if ctx.folded.limit_reached:
        raise Rejected(LIMIT_TEXT)


def _text(body: dict, key: str) -> str:
    return str(body.get(key) or "").strip()[:4000]


def _correction_id(ctx: Context, alloc: Allocator, text: str) -> str:
    key = f"correction:{ctx.request_id}"
    if alloc.slugs:
        return alloc.claim("correction", "", text, key)
    return alloc.take(key, "c" + hashlib.sha256(ctx.request_id.encode()).hexdigest()[:8])


# ------------------------------------------------------------------------ person commands


def _create_board(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    if ctx.events:
        raise Rejected("The board exists already.")
    goals = [str(g).strip()[:4000] for g in body.get("goals") or [] if str(g).strip()]
    if not goals or len(goals) > m.MAX_GOALS:
        raise Rejected(f"A board needs 1 to {m.MAX_GOALS} goals.")
    origin = m.BACKGROUND_ID if alloc.slugs else m.ORIGIN
    alloc.take(f"background:{ctx.request_id}", origin)
    _fact(ctx, prepared, origin, m.ORIGIN, _text(body, "origin"), ctx.actor)
    goal_ids = []
    for slot, text in enumerate(goals, start=1):
        goal_id = m.goal_slot_id(slot) if alloc.slugs else m.goal_id_for(slot)
        goal_ids.append(alloc.take(f"goal:{ctx.request_id}:{slot}", goal_id))
        _fact(ctx, prepared, goal_id, m.GOAL, text, ctx.actor)
    _event(ctx, prepared, m.BOARD_CREATED, "", {"goals": goal_ids}, f"{m.BOARD_CREATED}:{ctx.request_id}")
    for index, hint in enumerate(str(h).strip()[:4000] for h in body.get("hints") or []):
        if hint:
            _event(ctx, prepared, m.HINT_ADDED, "", {"text": hint}, f"{m.HINT_ADDED}:{ctx.request_id}:{index}")


def _add_hint(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    _live(ctx)
    _not_at_limit(ctx)
    text = _text(body, "text")
    if not text:
        raise Rejected("The hint is empty.")
    _event(ctx, prepared, m.HINT_ADDED, "", {"text": text}, f"{m.HINT_ADDED}:{ctx.request_id}")


def _reject_fact(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    _live(ctx)
    fact_id = _text(body, "fact_id")
    fact = next((f for f in ctx.facts if f.fact_id == fact_id), None)
    if fact is None:
        raise Rejected(f"The board has no fact {fact_id}.")
    if fact.kind in (m.ORIGIN, m.GOAL):
        raise Rejected("The background context and the goals cannot be rejected.")
    if fact_id in ctx.folded.rejected:
        raise Rejected("The fact is rejected already.")
    _event(ctx, prepared, m.FACT_REJECTED, fact_id, {"reason": _text(body, "reason")},
           f"{m.FACT_REJECTED}:{ctx.request_id}")


def _set_paused(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    paused = bool(body.get("paused"))
    if paused and ctx.folded.status != m.ACTIVE:
        raise Rejected("Only an active board can pause.")
    if not paused and ctx.folded.status != m.PAUSED:
        raise Rejected("The board is not paused.")
    kind = m.PAUSE_REQUESTED if paused else m.RESUME_REQUESTED
    _event(ctx, prepared, kind, "", {}, f"{kind}:{ctx.request_id}")


def _set_internet_tools(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    _live(ctx)
    _event(ctx, prepared, m.SETTINGS_CHANGED, "", {"internet_tools": bool(body.get("on"))},
           f"{m.SETTINGS_CHANGED}:{ctx.request_id}")


def _review_decision(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    review_id = _text(body, "review_id")
    if f.status != m.REVIEW:
        raise Rejected("The board does not wait for a review.")
    if review_id != f.decision_id:
        raise Rejected("A newer review replaced this one. Read the board again.")
    if body.get("accept"):
        _event(ctx, prepared, m.REVIEW_ACCEPTED, "", {"review_id": review_id},
               f"{m.REVIEW_ACCEPTED}:{ctx.request_id}")
        return
    correction = _text(body, "correction")
    if not correction:
        raise Rejected("A rejected review needs a correction.")
    corrected = list(dict.fromkeys(fid for a in f.proposed.values() for fid in a["from"]))
    fact_id = _correction_id(ctx, alloc, correction)
    _fact(ctx, prepared, fact_id, m.CORRECTION, correction, ctx.actor)
    _label(alloc, prepared, fact_id, "correction")
    _event(ctx, prepared, m.REVIEW_REJECTED, fact_id,
           {"correction": correction, "from": corrected, "review_id": review_id},
           f"{m.REVIEW_REJECTED}:{ctx.request_id}")


def _answer_decision(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    _live(ctx)
    goal = _text(body, "goal")
    answer = f.proposed.get(goal)
    if answer is None:
        raise Rejected("The goal has no proposed answer.")
    proposal_id = _text(body, "proposal_id")
    if proposal_id != answer.get("proposal_id"):
        raise Rejected("A newer assessment replaced this answer. Read it again.")
    decided = {"proposal_id": proposal_id, "reason_no": answer["reason_no"], "from": answer["from"],
               "statement": answer["statement"], "answer_kind": answer.get("answer_kind", "")}
    if body.get("accept"):
        _event(ctx, prepared, m.GOAL_ANSWER_ACCEPTED, goal, decided,
               f"{m.GOAL_ANSWER_ACCEPTED}:{ctx.request_id}")
        return
    correction = _text(body, "correction")
    if not correction:
        raise Rejected("A rejected answer needs a correction.")
    fact_id = _correction_id(ctx, alloc, correction)
    _fact(ctx, prepared, fact_id, m.CORRECTION, correction, ctx.actor)
    _label(alloc, prepared, fact_id, "correction")
    _event(ctx, prepared, m.GOAL_ANSWER_REJECTED, fact_id,
           {"goal": goal, "proposal_id": proposal_id, "reason_no": answer["reason_no"],
            "from": answer["from"], "correction": correction},
           f"{m.GOAL_ANSWER_REJECTED}:{ctx.request_id}")


def _add_goal(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    _live(ctx)
    _not_at_limit(ctx)
    text = _text(body, "text")
    if not text:
        raise Rejected("The goal is empty.")
    goals = [f for f in ctx.all_facts if f.kind == m.GOAL]
    if len(goals) >= m.MAX_GOALS:
        raise Rejected(f"A board has at most {m.MAX_GOALS} goals. Create a new board for another goal.")
    used = {m.goal_slot(g.fact_id) for g in goals}
    slot = next(n for n in range(1, m.MAX_GOALS + 1) if n not in used)
    goal_id = alloc.take(f"goal:{ctx.request_id}", m.goal_slot_id(slot) if alloc.slugs else m.goal_id_for(slot))
    _fact(ctx, prepared, goal_id, m.GOAL, text, ctx.actor)
    _event(ctx, prepared, m.GOAL_ADDED, goal_id, {"text": text}, f"{m.GOAL_ADDED}:{ctx.request_id}")


def _explore_question(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    _live(ctx)
    _not_at_limit(ctx)
    fact_id = _text(body, "fact_id")
    fact = next((x for x in ctx.facts if x.fact_id == fact_id), None)
    if fact is None:
        raise Rejected(f"The board has no fact {fact_id}.")
    if fact_id in f.rejected:
        raise Rejected("The fact of this question is rejected.")
    has_index = body.get("index") is not None
    own_text = _text(body, "question")
    if has_index == bool(own_text):
        raise Rejected("Name an open question or write a question, not both.")
    payload = {"fact_id": fact_id, "origin": m.ORIGIN_PERSON_QUESTION}
    if has_index:
        if fact.kind not in m.EXPLORE_KINDS:
            raise Rejected("Only an explore fact has open questions.")
        index = int(body["index"])
        if not 0 <= index < len(fact.open_questions or []):
            raise Rejected(f"The fact has no open question {index}.")
        key = m.question_key(fact_id, index)
        holder = f.holder(key)
        if holder is not None:
            raise Rejected(f"This question is already explored in {holder.intent_id}.")
        question = str(fact.open_questions[index])
        payload.update(own=False, index=index, question=question, question_key=key)
    else:
        if fact.kind not in m.EXPLORE_KINDS + (m.ORIGIN,):
            raise Rejected("A question can follow an explore fact or the background context.")
        question = own_text
        payload.update(own=True, question=question)
    key = f"question:{ctx.request_id}"
    if alloc.slugs:
        intent_id = alloc.claim("intent", "", question, key)
    else:
        numbers = [int(i[len(m.QUESTION_INTENT_PREFIX):]) for i in f.intents if m.is_question_intent(i)]
        intent_id = alloc.take(key, f"{m.QUESTION_INTENT_PREFIX}{max(numbers, default=0) + 1}")
    payload["intent_id"] = intent_id
    _label(alloc, prepared, intent_id, "intent")
    _event(ctx, prepared, m.QUESTION_EXPLORED, intent_id, payload, f"{m.QUESTION_EXPLORED}:{ctx.request_id}")
    prepared.result["intent_id"] = intent_id


def _extend_budget(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    expected = _text(body, "expected_id")
    if f.status not in (m.REVIEW, m.COMPLETED):
        raise Rejected("Only a board in review or complete can reopen.")
    if expected != f.decision_id:
        raise Rejected("The board changed since it was read. Read it again.")
    if f.decision_id in f.extended:
        raise Rejected("This review was reopened already.")
    if not f.open_goals:
        raise Rejected("Every goal has an accepted answer.")
    _not_at_limit(ctx)
    grant = min(m.EXTENSION_EXPLORES, m.EXPLORE_LIMIT - f.max_explores)
    _event(ctx, prepared, m.BUDGET_EXTENDED, "", {"expected_id": expected, "prior_status": f.status,
                                                   "grant": grant},
           f"{m.BUDGET_EXTENDED}:{ctx.request_id}")
    prepared.result["grant"] = grant


# ------------------------------------------------------------------------ worker commands


def _start_reason(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    reason_no = int(body.get("reason_no") or 0)
    if f.status != m.ACTIVE:
        raise Rejected(f"the board is {f.status}")
    if reason_no <= f.reasons_started:
        raise Rejected(f"assessment {reason_no} started already")
    payload = {"stalled": bool(body.get("stalled"))}
    if body.get("final"):
        budget = int(body.get("assessed_budget") or 0)
        if f.explores_used < f.max_explores or budget != f.max_explores:
            raise Rejected("the budget is not used")
        if str(budget) in f.final_ops:
            raise Rejected(f"the budget {budget} had its final assessment")
        payload.update(final=True, assessed_budget=budget, assessment_id=str(body.get("assessment_id", "")))
    _event(ctx, prepared, m.REASON_STARTED, str(reason_no), payload, f"{m.REASON_STARTED}:{reason_no}")


def _reason_result(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    reason_no = int(body.get("reason_no") or 0)
    if not any(e.event_type == m.REASON_STARTED and e.subject == str(reason_no) for e in ctx.events):
        raise Rejected(f"assessment {reason_no} has no start")
    if any(e.event_type == m.REASON_RESULT and e.subject == str(reason_no) for e in ctx.events):
        raise Rejected(f"assessment {reason_no} has a result")
    payload = dict(body.get("payload") or {})
    problems = list(payload.get("problems") or [])
    claimed: set = set()
    intents = []
    for kept, item in enumerate(payload.get("intents") or [], start=1):
        item = dict(item)
        key = f"assessment:{reason_no}:{int(item.get('position') or kept)}"
        if alloc.slugs:
            intent_id = alloc.claim("intent", str(item.get("slug") or ""), str(item.get("objective") or ""), key)
        else:
            intent_id = alloc.take(key, m.intent_id_for(reason_no, kept))
        questions = []
        for question in item.get("questions") or []:
            holder = f.holder(question)
            if holder is not None or question in claimed:
                problems.append(f"discarded the binding of {question} to {intent_id}: "
                                f"{holder.intent_id if holder else 'an earlier intent of this reply'} explores it")
                continue
            claimed.add(question)
            questions.append(question)
        item.update(intent_id=intent_id, origin=m.ORIGIN_ASSESSMENT, creation_key=key, questions=questions)
        intents.append(item)
        _label(alloc, prepared, intent_id, "intent")
    if intents:
        payload["intents"] = intents
    payload["problems"] = problems
    _event(ctx, prepared, m.REASON_RESULT, str(reason_no), payload, f"{m.REASON_RESULT}:{reason_no}",
           actor="reason")


def _start_explore(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    intent_id = _text(body, "intent_id")
    attempt = int(body.get("attempt") or 0)
    intent = f.intents.get(intent_id)
    if intent is None:
        raise Rejected(f"the board has no intent {intent_id}")
    if not may_explore(f, intent_id):
        raise Rejected(f"the board is {f.status}")
    if intent.state != m.OPEN or attempt != intent.started + 1:
        raise Rejected(f"the intent is {intent.state} at attempt {intent.started}")
    if explores_left(f) <= 0:
        raise Rejected("the explore budget is used")
    _event(ctx, prepared, m.EXPLORE_STARTED, intent_id, {"attempt": attempt},
           f"{m.EXPLORE_STARTED}:{intent_id}:{attempt}", actor="dispatcher")


def _explore_end(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    intent_id = _text(body, "intent_id")
    attempt = int(body.get("attempt") or 0)
    end = _text(body, "end")
    base = {"attempt": attempt, **({"phase": body["phase"]} if body.get("phase") else {})}
    actor = str(body.get("actor") or "explore")
    if end != m.EXPLORE_CONCLUDED:
        if end not in (m.EXPLORE_FAILED, m.EXPLORE_CANCELLED, m.EXPLORE_QUESTION):
            raise Rejected(f"unknown end {end!r}")
        extra = {"question": str(body.get("question") or "")[:2000]} if end == m.EXPLORE_QUESTION else {
            "error": str(body.get("error") or "")[:2000]}
        _event(ctx, prepared, end, intent_id, {**base, **extra}, f"{end}:{intent_id}:{attempt}", actor=actor)
        return
    intent = f.intents.get(intent_id)
    if intent is None:
        raise Rejected(f"the board has no intent {intent_id}")
    if intent.fact_id:
        raise Rejected(f"the intent {intent_id} has a fact")
    existing = next((x for x in ctx.facts if x.intent_id == intent_id
                     and x.fact_id == str(body.get("existing_fact") or "")), None)
    if existing is not None:
        # A legacy fact that its writer wrote without the event: the event names it.
        _event(ctx, prepared, m.EXPLORE_CONCLUDED, intent_id,
               {**base, "fact_id": existing.fact_id, "kind": existing.kind},
               f"{m.EXPLORE_CONCLUDED}:{intent_id}:{attempt}", actor=actor)
        return
    if any(x.intent_id == intent_id for x in ctx.facts):
        raise Rejected(f"the intent {intent_id} has a fact")
    fact = dict(body.get("fact") or {})
    key = f"fact:{intent_id}"
    known = [x for x in ctx.all_facts if x.intent_id == intent_id]
    if known:
        # A fact row whose event was never written: the writer publishes it again under its id.
        fact_id = alloc.take(key, known[0].fact_id)
    elif not alloc.slugs and m.is_legacy_intent(intent_id):
        fact_id = alloc.take(key, m.fact_id_for(intent_id))
    else:
        fact_id = alloc.claim("fact", str(fact.get("slug") or ""), str(fact.get("text") or ""), key)
    _fact(ctx, prepared, fact_id, str(fact.get("kind") or ""), str(fact.get("text") or ""), "explore",
          intent_id=intent_id, session_id=str(fact.get("session_id") or ""),
          answer_seq=int(fact.get("answer_seq") or 0), open_questions=fact.get("open_questions"),
          problems=fact.get("problems"))
    for citation in body.get("citations") or []:
        prepared.citations.append({**citation, "fact_id": fact_id})
    _label(alloc, prepared, fact_id, "fact")
    _event(ctx, prepared, m.EXPLORE_CONCLUDED, intent_id,
           {**base, "fact_id": fact_id, "kind": str(fact.get("kind") or ""),
            "claimed_kind": str(fact.get("claimed_kind") or ""), "problems": list(fact.get("problems") or []),
            "citations": len(body.get("citations") or [])},
           f"{m.EXPLORE_CONCLUDED}:{intent_id}:{attempt}", actor=actor)
    prepared.result["fact_id"] = fact_id


def _review_proposed(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    f = ctx.folded
    if f.status != m.ACTIVE:
        raise Rejected(f"the board is {f.status}")
    why = _text(body, "why")
    statement = "The explore budget is used." if why == "budget" else stall_statement(f.stall_causes)
    _event(ctx, prepared, m.REVIEW_PROPOSED, why,
           {"reason": why, "statement": statement, "explores_used": f.explores_used,
            "max_explores": f.max_explores, "causes": dict(f.stall_causes)},
           ctx.request_id, actor="dispatcher")


#: The words of each stall cause in a review statement.
_CAUSE_WORDS = {
    m.CAUSE_NO_DIRECTION: "gave no new direction",
    m.CAUSE_INVALID: "held no valid JSON",
    m.CAUSE_MODEL_FAILURE: "got no answer from the model",
}


def stall_statement(causes: dict) -> str:
    """The review statement of a board that stopped without progress. It names each cause
    and its count, for example: "The last 3 assessments made no progress: 2 got no answer
    from the model, and 1 held no valid JSON."."""
    parts = [f"{count} {_CAUSE_WORDS[cause]}"
             for cause, count in sorted(causes.items(), key=lambda kv: -kv[1])
             if cause in _CAUSE_WORDS and count]
    total = sum(int(c) for c in causes.values())
    if not parts:
        return "The assessments made no progress."
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ", and " + parts[-1]
    noun = "assessment" if total == 1 else f"{total} assessments"
    return f"The last {noun} made no progress: {listed}."


def _final_ended(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    budget = int(body.get("assessed_budget") or 0)
    op = ctx.folded.final_ops.get(str(budget))
    if op is None or op["state"] != "running":
        raise Rejected(f"the final assessment of budget {budget} is not running")
    _event(ctx, prepared, m.FINAL_ASSESSMENT_ENDED, op["assessment_id"],
           {"assessed_budget": budget, "assessment_id": op["assessment_id"],
            "outcome": _text(body, "outcome") or "failed", "error": _text(body, "error")[:2000]},
           f"{m.FINAL_ASSESSMENT_ENDED}:{op['assessment_id']}", actor="dispatcher")


def _assign_labels(ctx: Context, body: dict, alloc: Allocator, prepared: Prepared) -> None:
    """The first slug of a node without one. A node that has a slug keeps it."""
    for entry in body.get("labels") or []:
        node_id = str(entry.get("node_id") or "")
        old = ctx.labels.get(node_id)
        if old is not None and old.slug:
            slug = old.slug
        else:
            kind = str(entry.get("node_kind") or "fact")
            slug = alloc.claim(kind, str(entry.get("slug") or ""), str(entry.get("text") or ""), f"label:{node_id}")
        prepared.labels.append({"node_id": node_id, "node_kind": str(entry.get("node_kind") or ""),
                                "slug": slug, "title": str(entry.get("title") or ""),
                                "summary": str(entry.get("summary") or ""),
                                "source_hash": str(entry.get("source_hash") or ""),
                                "model": str(entry.get("model") or ""), "created_at": entry.get("created_at")})


HANDLERS = {
    CREATE_BOARD: _create_board, ADD_HINT: _add_hint, REJECT_FACT: _reject_fact,
    SET_PAUSED: _set_paused, SET_INTERNET_TOOLS: _set_internet_tools,
    REVIEW_DECISION: _review_decision, ANSWER_DECISION: _answer_decision, ADD_GOAL: _add_goal,
    EXPLORE_QUESTION: _explore_question, EXTEND_BUDGET: _extend_budget,
    START_REASON: _start_reason, REASON_RESULT: _reason_result, START_EXPLORE: _start_explore,
    EXPLORE_END: _explore_end, REVIEW_PROPOSED: _review_proposed, FINAL_ENDED: _final_ended,
    ASSIGN_LABELS: _assign_labels,
}


def prepare(ctx: Context, kind: str, body: dict, seq_start: int) -> Prepared:
    """The frozen rows of one command against the committed state. Raises `Rejected`."""
    handler = HANDLERS.get(kind)
    if handler is None:
        raise Rejected(f"unknown command {kind!r}")
    alloc = Allocator(ctx)
    prepared = Prepared()
    handler(ctx, body, alloc, prepared)
    stamp = ctx.now.isoformat()
    for offset, event in enumerate(prepared.events):
        event["payload"].update(seq=seq_start + offset, request_id=ctx.request_id)
        event["created_at"] = stamp
    for fact in prepared.facts:
        fact.update(created_at=stamp, request_id=ctx.request_id)
    for label in prepared.labels:
        label["created_at"] = label.get("created_at") or stamp
        label["updated_at"] = stamp
    prepared.assignments = dict(alloc.assigned)
    prepared.result.setdefault("events", [e["event_id"] for e in prepared.events])
    prepared.result.setdefault("nodes", sorted(alloc.assigned.values()))
    return prepared


# ------------------------------------------------------------------------- the step


def context(board, receipts: dict, now: datetime, version: int) -> Context:
    from database import boards

    events = canonical_events(boards.read_events(board.board_id))
    all_facts = boards.read_facts(board.board_id)
    facts = visible_facts(all_facts, events)
    labels = {row.node_id: row for row in boards.read_labels([board.board_id])}
    assignments = {}
    for receipt in receipts.values():
        assignments.update(receipt.prepared.get("assignments") or {})
    return Context(board, events, facts, all_facts, fold(board, events, facts), labels, assignments,
                   version, now)


def _parse_time(value):
    if isinstance(value, datetime) or value is None:
        return value
    return datetime.fromisoformat(str(value))


def apply(board_id: str, prepared: dict) -> None:
    """Write the rows of a prepared receipt: facts and citations, labels, then events. Every
    row has its fixed time, so a retry writes the same rows again."""
    from database import boards

    facts = [boards.FactRow(board_id, f["fact_id"], f["kind"], f["text"], f["intent_id"], f["session_id"],
                            int(f["answer_seq"]), list(f["open_questions"]), list(f["problems"]),
                            f["created_by"], _parse_time(f["created_at"]), f["request_id"])
             for f in prepared.get("facts") or []]
    citations = [boards.CitationRow(board_id, c["fact_id"], c["label"], c.get("collection_dataset", ""),
                                    c.get("collectionname", ""), c.get("file_hash", ""), c.get("path", ""),
                                    int(c.get("page_id") or 0), c.get("quote", ""), int(c.get("quote_verified") or 0))
                 for c in prepared.get("citations") or []]
    if facts:
        boards.publish_facts(facts, citations)
    labels = [boards.LabelRow(board_id, lb["node_id"], lb["node_kind"], lb.get("slug", ""),
                              lb.get("title", ""), lb.get("summary", ""), lb.get("source_hash", ""),
                              lb.get("model", ""), 0, _parse_time(lb.get("created_at")),
                              _parse_time(lb.get("updated_at")))
              for lb in prepared.get("labels") or []]
    if labels:
        boards.write_labels(labels)
    events = [boards.EventRow(board_id, e["event_id"], e["event_type"], e["actor"], e["subject"],
                              e["payload"], _parse_time(e["created_at"]))
              for e in prepared.get("events") or []]
    if events:
        boards.write_events(events)


def step(board_id: str) -> bool:
    """Handle one command of a board: apply a prepared receipt, else prepare and apply the
    oldest pending input. Returns False when the board has no command left."""
    from database import board_commands as bc
    from database import boards

    receipts = bc.read_receipts(board_id)
    waiting = sorted((r for r in receipts.values() if r.state == bc.PREPARED),
                     key=lambda r: (r.seq_start, str(r.created_at or ""), r.request_id))
    if waiting:
        receipt = waiting[0]
        apply(board_id, receipt.prepared)
        receipt.state = bc.COMMITTED
        bc.write_receipt(receipt)
        return True
    pending = [i for i in bc.read_inputs(board_id) if i.request_id not in receipts]
    if not pending:
        return False
    command = pending[0]
    receipt = bc.Receipt(board_id, command.request_id, command.payload_digest, command.kind, bc.REJECTED,
                         created_at=boards.now())
    board = boards.read_board(board_id)
    if board is None or board.is_deleted:
        receipt.error = "The board is dropped."
        bc.write_receipt(receipt)
        return True
    if command.kind in PERSON_KINDS and command.actor != board.owner:
        receipt.error = "Only the owner of the board can act on it."
        bc.write_receipt(receipt)
        return True
    seq_start = max((r.seq_end for r in receipts.values()), default=0) + 1
    ctx = context(board, receipts, receipt.created_at, identity_version())
    ctx.request_id, ctx.actor = command.request_id, command.actor
    seq_start = max(seq_start, ctx.folded.last_seq + 1)
    try:
        prepared = prepare(ctx, command.kind, command.body, seq_start)
    except Rejected as exc:
        receipt.error = str(exc)
        bc.write_receipt(receipt)
        log.info("[P_board] %s %s of %s refused: %s", command.kind, command.request_id, board_id, exc)
        return True
    receipt.state = bc.PREPARED
    receipt.prepared = {"events": prepared.events, "facts": prepared.facts, "citations": prepared.citations,
                        "labels": prepared.labels, "assignments": prepared.assignments}
    if not any(r.seq_end for r in receipts.values()):
        legacy = [e for e in ctx.events if "seq" not in (e.payload or {})]
        receipt.prepared["legacy_frontier"] = {"events": len(legacy),
                                               "last_event_id": legacy[-1].event_id if legacy else ""}
    receipt.result = prepared.result
    if prepared.events:
        receipt.seq_start, receipt.seq_end = seq_start, seq_start + len(prepared.events) - 1
    bc.write_receipt(receipt)
    apply(board_id, receipt.prepared)
    receipt.state = bc.COMMITTED
    bc.write_receipt(receipt)
    return True


__all__ = [
    "ADD_GOAL", "ADD_HINT", "ANSWER_DECISION", "ASSIGN_LABELS", "Allocator", "CREATE_BOARD", "Context",
    "EXPLORE_END", "EXPLORE_QUESTION", "EXTEND_BUDGET", "FINAL_ENDED", "IDENTITY_SETTING", "LIMIT_TEXT",
    "PERSON_KINDS", "Prepared", "REASON_RESULT", "REJECT_FACT", "REVIEW_DECISION", "REVIEW_PROPOSED",
    "Rejected", "SET_INTERNET_TOOLS", "SET_PAUSED", "SLUG_IDENTITY", "START_EXPLORE", "START_KINDS",
    "START_REASON", "apply", "context", "identity_version", "prepare", "slug_stem", "step",
]
