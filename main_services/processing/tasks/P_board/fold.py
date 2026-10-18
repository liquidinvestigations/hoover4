"""The fold and the planner: pure functions over the stored rows of a board.

`fold` turns the events of one board into its status, counters and intents. `plan` reads
the folded boards and returns the work the dispatcher starts or cancels. Neither function
reads storage or the clock, so the unit tests in `tests/unit/test_board_fold.py` exercise
every rule without ClickHouse or Temporal.

The rules:

* **Order.** Events without a `seq` in their payload were written before the command
  writer. They come first, in their stored order (`created_at`, then the event id). The
  events of the command writer follow in `seq` order. A derived `status_changed` row is not
  folded.
* **Visible facts.** A fact that a command wrote carries its request id. It counts only
  when an event carries the same request id (`visible_facts`), so a fact whose publication
  stopped before its event is not read.
* **Node identity.** An intent of a `reason_result` or `question_explored` event with an
  explicit `intent_id` keeps that id and its explicit origin. An event without one is a
  legacy event: its intent is `iR.N` by position, or the subject `i0.N` for a question. The
  fact of an intent is the `fact_id` of its `explore_concluded` event.
* **Status.** A person's pause, resume, decision or drop applies in event order. An
  assessment that leaves every open goal with a proposed answer, and a `review_proposed` of
  the dispatcher, move an active board to review. A rejected review, a rejected answer, a
  later goal and a reopening move a board back to active. A question explored by a person
  keeps the status. Each change is a `Transition` named by its causal event, and
  `board_plan` writes it as a `status_changed` row.
* **Review identity.** Entering review or completion sets `decision_id` to the id of the
  causal event. A review decision or a reopening that names another identity does nothing,
  so a late retry cannot decide a newer review. A legacy decision without an identity
  applies as before.
* **Goal answers.** An assessment proposes answers for some goals or for all. New proposals
  replace the proposal of their goal and keep the others. A proposal has the identity
  `<reason_result event id>:<goal>`, and a decision names it. A legacy assessment of outcome
  `review` replaces every proposal, and a legacy decision names its reason number.
  `goal_answer_accepted` moves an answer to the accepted answers, which no later event
  removes. The board is complete when every goal has an accepted answer.
* **Progress.** An assessment makes progress when it adds an intent, proposes an answer for
  a goal without one, or changes the facts or the kind of a proposal. An assessment without
  progress follows the no-progress rules of an empty result, so repeated partial answers
  end in review after `INVALID_REASON_LIMIT` results. The fold counts each such result by
  its cause: no new direction, no valid JSON, or a failed model request (`model_failure`).
  The review reason names the cause with the most results.
* **Attempts.** `explore_started` counts an attempt and an explore of the budget. A
  cancellation refunds both. When one attempt has both a concluded event and a cancelled or
  failed event, the concluded event wins, because its fact exists.
* **Reason trigger.** A reason is due when the board is active, no reason is in flight, no
  intent is open, and the situation changed since the checkpoint of the last successful
  reason, or the open and running intents fell to none.
* **Budget.** `max_explores` is `min(EXPLORE_LIMIT, BASE + GOAL * (goals - 1) + ACTION *
  (hints + person questions + corrections) + EXTENSION * reopenings)`. The goals of the
  creation count from the start, and a later goal counts at its own event. Each
  budget-bearing event keeps its actual grant in `grants`: the capped budget after it less
  the capped budget before it. A repeated event of one subject counts once.
* **Final assessment.** A board whose budget is used and whose explores ended gets one final
  assessment for that budget. It proposes answers from the facts and starts no explore. Its
  result or its recorded failure ends it, and the next pass proposes the budget review when
  that budget is still used.
* **Question bindings.** An assessment intent can name open questions by key
  (`<fact id>#<1-based index>`). A key is bound while an intent that is not failed holds it.
  The fold keeps the first holder in event order. A failed intent releases its keys.
* **One cap.** Each running explore, each reason in flight and each pending start takes one
  board model slot. All boards together use at most the global cap, and each board at most
  its `max_parallel`. A free slot goes first to the board with the least work in flight, then
  to the board that has received the fewest explores and reasons.
"""

from dataclasses import dataclass, field

from tasks.P_board import model as m
from tasks.P_board.prompts import goal_ids

#: The assessment results that the next reason prompt reports.
RECENT_REASONS = 3

#: The event types that can change the budget. Each keeps its actual grant.
BUDGET_EVENTS = (m.HINT_ADDED, m.QUESTION_EXPLORED, m.FACT_REJECTED, m.REVIEW_REJECTED,
                 m.GOAL_ANSWER_REJECTED, m.GOAL_ADDED, m.BUDGET_EXTENDED)


@dataclass
class Intent:
    intent_id: str
    reason_no: int
    from_facts: list[str]
    objective: str
    brief: str
    state: str = m.OPEN
    attempts: int = 0
    started: int = 0
    running_attempt: int = 0
    fact_id: str = ""
    question: str = ""
    last_error: str = ""
    created_at: object = None
    running_since: object = None
    #: `assessment`, or `person_question` for a question that a person asked to explore.
    origin: str = m.ORIGIN_ASSESSMENT
    #: The question keys that the intent explores.
    questions: list[str] = field(default_factory=list)
    #: A person wrote the question of this intent, so it has no open-question key.
    own: bool = False
    #: The fact that the question of a person question intent belongs to.
    source_fact: str = ""


@dataclass
class Transition:
    """One status change: its causal event, its position in that event, and the statuses."""

    event_id: str
    ordinal: int
    prior: str
    status: str
    created_at: object = None
    seq: int = 0


@dataclass
class Folded:
    """One board after the fold."""

    board_id: str
    status: str = m.ACTIVE
    explores_used: int = 0
    reasons_started: int = 0
    reasons_done: int = 0
    stall_count: int = 0
    invalid_reasons: int = 0
    checkpoint: dict = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)
    #: Rejected fact id to the reason that the person gave.
    rejected: dict = field(default_factory=dict)
    intents: dict = field(default_factory=dict)
    fact_count: int = 0
    sourced_count: int = 0
    review_statement: str = ""
    #: The goal ids of the board, first goal first.
    goal_ids: list[str] = field(default_factory=list)
    #: Goal id to the answer that waits for the person: `goal`, `from`, `statement`,
    #: `reason_no`, `proposal_id`, `answer_kind` and `commentary`.
    proposed: dict = field(default_factory=dict)
    #: Goal id to the answer that the person accepted, in the same form.
    accepted: dict = field(default_factory=dict)
    review_rejections: int = 0
    last_reason_outcome: str = ""
    #: The checks that changed the last reason reply.
    last_reason_problems: list[str] = field(default_factory=list)
    #: The last `RECENT_REASONS` assessment results, oldest first, which the next reason
    #: reads: `reason_no`, `outcome`, `problems` and `error`.
    recent_reasons: list[dict] = field(default_factory=list)
    #: The assessments without progress since the last progress, by cause
    #: (`m.CAUSE_NO_DIRECTION`, `m.CAUSE_INVALID`, `m.CAUSE_MODEL_FAILURE`). Their sum is
    #: `invalid_reasons`.
    stall_causes: dict = field(default_factory=dict)
    #: The cause of the last assessment without progress.
    last_stall_cause: str = ""
    #: The goals of the creation, and the goal ids of later `goal_added` events.
    initial_goals: list[str] = field(default_factory=list)
    goals_added: set = field(default_factory=set)
    #: The intent ids of the questions that a person asked to explore.
    questions_explored: set = field(default_factory=set)
    #: Reopenings that the board accepted.
    extensions: int = 0
    #: Event id to the actual budget grant of each budget-bearing event.
    grants: dict = field(default_factory=dict)
    #: Status changes in event order.
    transitions: list[Transition] = field(default_factory=list)
    #: The id of the event that moved the board into its current review or completion.
    decision_id: str = ""
    #: Why the board is in review: `answers`, `budget`, a value of `m.STALL_REVIEW_REASONS`,
    #: or `stalled` from an older event. Empty otherwise.
    review_reason: str = ""
    #: The decision ids that a reopening has used.
    extended: set = field(default_factory=set)
    #: Assessed budget to its final assessment: `assessment_id`, `reason_no`, `state`
    #: (`running` or `terminal`) and `outcome`.
    final_ops: dict = field(default_factory=dict)
    #: Question key to the intents that bound it, in event order.
    bindings: dict = field(default_factory=dict)
    #: The highest canonical sequence number.
    last_seq: int = 0

    def clear_stalls(self) -> None:
        """Progress or a person's action: no assessment without progress is counted."""
        self.invalid_reasons = 0
        self.stall_causes = {}
        self.last_stall_cause = ""

    def stall_review_reason(self) -> str:
        """The review reason of a board that stopped without progress: the cause with the
        most assessments, and on a tie the cause of the last one."""
        if not self.stall_causes:
            return m.STALLED_NO_DIRECTION
        cause = max(self.stall_causes,
                    key=lambda c: (self.stall_causes[c], c == self.last_stall_cause))
        return m.STALL_REVIEW_REASONS.get(cause, m.STALLED_NO_DIRECTION)

    def counts(self) -> dict:
        """The counts that the budget formula reads."""
        return {"goals": len(self.initial_goals) + len(self.goals_added), "hints": len(self.hints),
                "questions": len(self.questions_explored),
                "corrections": len(self.rejected) + self.review_rejections,
                "extensions": self.extensions}

    @property
    def max_explores(self) -> int:
        """The explore budget. See the module rules."""
        return budget_of(self.counts())

    @property
    def explore_steps(self) -> int:
        """The model steps of one explore turn."""
        corrections = len(self.rejected) + self.review_rejections + len(self.goals_added)
        return min(m.MAX_EXPLORE_STEPS, m.BASE_EXPLORE_STEPS
                   + corrections * m.CORRECTION_EXPLORE_STEPS + len(self.hints) * m.HINT_EXPLORE_STEPS)

    @property
    def limit_reached(self) -> bool:
        """Whether the board used every explore that any board may use."""
        return self.explores_used >= m.EXPLORE_LIMIT

    @property
    def final_at_budget(self) -> int:
        """The largest budget whose final assessment ended, 0 for none."""
        ended = [int(b) for b, op in self.final_ops.items() if op.get("state") == "terminal"]
        return max(ended, default=0)

    def situation(self) -> dict:
        """The counts a reason checkpoint compares."""
        return {"facts": self.fact_count, "hints": len(self.hints), "rejected": len(self.rejected),
                "goals_added": len(self.goals_added)}

    @property
    def open_goals(self) -> list[str]:
        """The goals without an accepted answer, which a review must answer."""
        return [g for g in self.goal_ids if g not in self.accepted]

    @property
    def all_answered(self) -> bool:
        """Whether every goal has an accepted answer."""
        return bool(self.goal_ids) and not self.open_goals

    def by_state(self, state: str) -> list[Intent]:
        return sorted((i for i in self.intents.values() if i.state == state),
                      key=lambda i: (i.reason_no, str(i.created_at or ""), i.intent_id))

    def holder(self, key: str) -> Intent | None:
        """The intent that holds a question key: the newest bound intent that is not failed."""
        for intent_id in reversed(self.bindings.get(key, [])):
            intent = self.intents.get(intent_id)
            if intent is not None and intent.state != m.FAILED:
                return intent
        return None


def budget_of(counts: dict) -> int:
    """The capped explore budget of a set of counts."""
    raw = (m.BASE_EXPLORES + m.GOAL_EXPLORES * max(0, counts["goals"] - 1)
           + m.ACTION_EXPLORES * (counts["hints"] + counts["questions"] + counts["corrections"])
           + m.EXTENSION_EXPLORES * counts["extensions"])
    return min(m.EXPLORE_LIMIT, raw)


def _int(text) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def canonical_events(events) -> list:
    """The events that the fold reads, in fold order. See the module rules."""
    legacy, sequenced = [], []
    for event in events:
        if event.event_type == m.STATUS_CHANGED:
            continue
        payload = event.payload or {}
        (sequenced if "seq" in payload else legacy).append(event)
    sequenced.sort(key=lambda e: _int((e.payload or {}).get("seq")))
    return legacy + sequenced


def visible_facts(facts, events) -> list:
    """The facts without a request id, and the facts whose command wrote its event."""
    published = {str((e.payload or {}).get("request_id") or "") for e in events}
    return [f for f in facts if not getattr(f, "request_id", "") or f.request_id in published]


def _concluded_attempts(events) -> set[tuple[str, int]]:
    return {(e.subject, int(e.payload.get("attempt", 0)))
            for e in events if e.event_type == m.EXPLORE_CONCLUDED}


def _initial_goals(events, goals: list[str]) -> list[str]:
    """The goals of the creation. A board created by the command writer names them in its
    `board_created` event. For a legacy board they are the goals without a `goal_added`."""
    for event in events:
        if event.event_type == m.BOARD_CREATED and "goals" in (event.payload or {}):
            named = [str(g) for g in event.payload.get("goals") or []]
            return [g for g in goals if g in named]
    added = {e.subject for e in events if e.event_type == m.GOAL_ADDED}
    return [g for g in goals if g not in added]


class _Fold:
    """The state of one pass of `fold`: the folded board and the event in hand."""

    def __init__(self, folded: Folded):
        self.f = folded
        self.event = None

    def status(self, new: str) -> None:
        f = self.f
        if f.status == new:
            return
        ordinal = sum(1 for t in f.transitions if t.event_id == self.event.event_id)
        f.transitions.append(Transition(self.event.event_id, ordinal, f.status, new,
                                        self.event.created_at,
                                        _int((self.event.payload or {}).get("seq"))))
        f.status = new
        if new in (m.REVIEW, m.COMPLETED):
            f.decision_id = self.event.event_id
        else:
            f.decision_id = ""
            f.review_reason = ""

    def reopen(self) -> None:
        """A person's late work: a board in review or complete goes back to active, and the
        next idle pass runs a reason even when the work ends without a fact."""
        f = self.f
        if f.status in (m.REVIEW, m.COMPLETED):
            self.status(m.ACTIVE)
            f.clear_stalls()
            f.stall_count = 0
        f.checkpoint = dict(f.checkpoint or {}, had_work=True)

    def names_decision(self, data: dict) -> bool:
        """Whether a decision names the current review or completion. A legacy decision
        without an identity names it."""
        named = data.get("review_id", data.get("expected_id"))
        return named is None or str(named) == self.f.decision_id


def fold(board, events, facts) -> Folded:
    """The state of one board from its definition, its events and its facts."""
    events = canonical_events(events)
    facts = visible_facts(facts, events)
    goals = goal_ids(facts)
    folded = Folded(board_id=board.board_id, goal_ids=goals,
                    initial_goals=_initial_goals(events, goals))
    run = _Fold(folded)
    concluded = _concluded_attempts(events)
    for event in events:
        run.event = event
        data = event.payload or {}
        folded.last_seq = max(folded.last_seq, _int(data.get("seq")))
        before = folded.max_explores
        _apply(run, event, data, concluded)
        if event.event_type in BUDGET_EVENTS:
            folded.grants[event.event_id] = folded.max_explores - before
    if board.is_deleted:
        folded.status = m.DROPPED
    live = [f for f in facts if f.fact_id not in folded.rejected and f.kind not in (m.ORIGIN, m.GOAL)]
    folded.fact_count = len(live)
    folded.sourced_count = sum(1 for f in live if f.kind == m.SOURCED)
    return folded


def _apply(run: _Fold, event, data: dict, concluded: set) -> None:
    folded = run.f
    kind = event.event_type
    if kind == m.HINT_ADDED:
        folded.hints.append(str(data.get("text", "")))
        for intent in folded.intents.values():
            if intent.state == m.QUESTION:
                intent.state = m.OPEN
    elif kind == m.FACT_REJECTED:
        folded.rejected[event.subject] = str(data.get("reason", ""))
    elif kind == m.PAUSE_REQUESTED and folded.status == m.ACTIVE:
        run.status(m.PAUSED)
    elif kind == m.RESUME_REQUESTED and folded.status == m.PAUSED:
        run.status(m.ACTIVE)
    elif kind == m.REVIEW_ACCEPTED and folded.status == m.REVIEW and run.names_decision(data):
        folded.accepted.update(folded.proposed)
        folded.proposed = {}
        run.status(m.COMPLETED)
    elif (kind == m.REVIEW_REJECTED and folded.status in (m.REVIEW, m.COMPLETED)
          and run.names_decision(data)):
        folded.proposed = {}
        folded.review_rejections += 1
        run.status(m.ACTIVE)
        folded.clear_stalls()
        folded.stall_count = 0
    elif kind == m.GOAL_ANSWER_ACCEPTED:
        if _decides(folded, event.subject, data):
            folded.accepted[event.subject] = folded.proposed.pop(event.subject)
            if folded.status in (m.ACTIVE, m.REVIEW) and folded.all_answered:
                run.status(m.COMPLETED)
            elif folded.status == m.REVIEW and not folded.proposed:
                run.status(m.ACTIVE)
                folded.checkpoint = dict(folded.checkpoint or {}, had_work=True)
    elif kind == m.GOAL_ANSWER_REJECTED:
        goal = str(data.get("goal", ""))
        if _decides(folded, goal, data):
            del folded.proposed[goal]
            folded.review_rejections += 1
            if folded.status == m.REVIEW:
                run.status(m.ACTIVE)
                folded.clear_stalls()
                folded.stall_count = 0
    elif kind == m.DROP_REQUESTED:
        run.status(m.DROPPED)
    elif kind == m.GOAL_ADDED:
        if event.subject not in folded.initial_goals:
            folded.goals_added.add(event.subject)
        run.reopen()
    elif kind == m.QUESTION_EXPLORED:
        _explore_question(folded, event, data)
    elif kind == m.BUDGET_EXTENDED:
        if (folded.status in (m.REVIEW, m.COMPLETED) and run.names_decision(data)
                and folded.decision_id not in folded.extended and folded.open_goals
                and not folded.limit_reached):
            folded.extended.add(folded.decision_id)
            folded.extensions += 1
            folded.review_statement = ""
            run.reopen()
    elif kind == m.REVIEW_PROPOSED and folded.status == m.ACTIVE:
        run.status(m.REVIEW)
        folded.review_statement = str(data.get("statement", ""))
        folded.review_reason = str(data.get("reason", ""))
    elif kind == m.REASON_STARTED:
        folded.reasons_started = max(folded.reasons_started, _int(event.subject))
        if data.get("final"):
            budget = str(_int(data.get("assessed_budget")))
            folded.final_ops.setdefault(budget, {
                "assessment_id": str(data.get("assessment_id", "")), "reason_no": _int(event.subject),
                "state": "running", "outcome": ""})
    elif kind == m.REASON_RESULT:
        _apply_reason(run, event)
    elif kind == m.FINAL_ASSESSMENT_ENDED:
        op = folded.final_ops.get(str(_int(data.get("assessed_budget"))))
        if op is not None and op["state"] == "running":
            op.update(state="terminal", outcome=str(data.get("outcome", "failed")))
    elif kind == m.EXPLORE_STARTED:
        intent = folded.intents.get(event.subject)
        if intent is not None and intent.state not in (m.CONCLUDED, m.CANCELLED):
            intent.state = m.RUNNING
            intent.started += 1
            intent.attempts += 1
            intent.running_attempt = int(data.get("attempt", intent.started))
            intent.running_since = event.created_at
            folded.explores_used += 1
    elif kind == m.EXPLORE_CONCLUDED:
        intent = folded.intents.get(event.subject)
        if intent is not None:
            intent.state = m.CONCLUDED
            intent.fact_id = str(data.get("fact_id", ""))
            if data.get("kind") == m.SOURCED:
                folded.stall_count = 0
            else:
                folded.stall_count += 1
    elif kind in (m.EXPLORE_FAILED, m.EXPLORE_CANCELLED, m.EXPLORE_QUESTION):
        intent = folded.intents.get(event.subject)
        attempt = int(data.get("attempt", 0))
        if intent is None or (event.subject, attempt) in concluded:
            return
        if intent.state != m.RUNNING or intent.running_attempt != attempt:
            return
        if kind == m.EXPLORE_CANCELLED:
            intent.attempts -= 1
            folded.explores_used -= 1
            intent.state = m.OPEN
        elif kind == m.EXPLORE_QUESTION:
            intent.state = m.QUESTION
            intent.question = str(data.get("question", ""))
        else:
            intent.last_error = str(data.get("error", ""))
            intent.state = m.FAILED if intent.attempts >= m.MAX_ATTEMPTS else m.OPEN
            folded.stall_count += 1


def _bind(folded: Folded, intent: Intent, keys) -> list[str]:
    """Bind the keys that no other live intent holds, in order. Returns the bound keys."""
    bound = []
    for key in keys:
        if key in bound or folded.holder(key) is not None:
            continue
        folded.bindings.setdefault(key, []).append(intent.intent_id)
        bound.append(key)
    return bound


def _explore_question(folded: Folded, event, data: dict) -> None:
    """A person's question: a new person-question intent that keeps the status."""
    explicit = str(data.get("intent_id") or "")
    intent_id = explicit or event.subject
    if not explicit and not m.is_question_intent(intent_id):
        return
    if intent_id in folded.intents:
        return
    fact_id = str(data.get("fact_id", ""))
    own = bool(data.get("own"))
    brief = (f"The investigator asked this question about {fact_id}." if own
             else f"The investigator asked to explore this open question of fact {fact_id}.")
    intent = Intent(intent_id=intent_id, reason_no=0, from_facts=[fact_id] if fact_id else [],
                    objective=str(data.get("question", "")), brief=brief, created_at=event.created_at,
                    origin=m.ORIGIN_PERSON_QUESTION, own=own, source_fact=fact_id)
    folded.intents[intent_id] = intent
    folded.questions_explored.add(intent_id)
    if not own and fact_id:
        intent.questions = _bind(folded, intent, [m.question_key(fact_id, _int(data.get("index")))])


def _decides(folded: Folded, goal: str, data: dict) -> bool:
    """Whether a person's decision names the answer that waits for goal `goal`: the decision
    on an answer that a newer reason replaced does nothing. A decision names the proposal
    identity, or for a legacy decision the reason number."""
    answer = folded.proposed.get(goal)
    if answer is None:
        return False
    if data.get("proposal_id") is not None:
        return str(data.get("proposal_id")) == answer.get("proposal_id")
    return answer.get("reason_no") == _int(str(data.get("reason_no", "")))


def _proposal(event, goal: dict, reason_no: int) -> dict:
    name = str(goal.get("goal", ""))
    return {"goal": name, "from": [str(f) for f in goal.get("from") or []],
            "statement": str(goal.get("statement", "")), "reason_no": reason_no,
            "proposal_id": f"{event.event_id}:{name}",
            "answer_kind": str(goal.get("answer_kind", "")),
            "commentary": str(goal.get("commentary", ""))}


def _material(old: dict | None, new: dict) -> bool:
    """Whether a proposal is new or changes its facts or its kind."""
    return old is None or (sorted(old["from"]), old.get("answer_kind", "")) != (
        sorted(new["from"]), new.get("answer_kind", ""))


def _add_intents(folded: Folded, event, data: dict, reason_no: int) -> int:
    added = 0
    for index, item in enumerate(data.get("intents") or [], start=1):
        intent_id = str(item.get("intent_id") or "") or m.intent_id_for(reason_no, index)
        if intent_id in folded.intents:
            continue
        intent = Intent(
            intent_id=intent_id, reason_no=reason_no,
            from_facts=[str(f) for f in item.get("from") or []],
            objective=str(item.get("objective", "")), brief=str(item.get("brief", "")),
            created_at=event.created_at, origin=str(item.get("origin") or m.ORIGIN_ASSESSMENT))
        folded.intents[intent_id] = intent
        intent.questions = _bind(folded, intent, [str(k) for k in item.get("questions") or []])
        added += 1
    return added


def _apply_reason(run: _Fold, event) -> None:
    folded = run.f
    data = event.payload or {}
    reason_no = _int(event.subject)
    folded.reasons_done += 1
    outcome = data.get("outcome", "")
    folded.last_reason_outcome = outcome
    folded.last_reason_problems = [str(p) for p in data.get("problems") or []]
    folded.recent_reasons = (folded.recent_reasons + [{
        "reason_no": reason_no, "outcome": outcome, "problems": folded.last_reason_problems,
        "error": str(data.get("error") or "")}])[-RECENT_REASONS:]
    if data.get("final"):
        # A final assessment proposes answers and ends its operation. It changes no status,
        # so the budget review of the next pass follows it.
        for goal in data.get("proposals") or []:
            proposal = _proposal(event, goal, reason_no)
            if proposal["goal"] in folded.goal_ids and proposal["goal"] not in folded.accepted:
                folded.proposed[proposal["goal"]] = proposal
        op = folded.final_ops.get(str(_int(data.get("assessed_budget"))))
        if op is not None:
            op.update(state="terminal", outcome=outcome)
        return
    added = _add_intents(folded, event, data, reason_no)
    changed = 0
    if "proposals" in data:
        for goal in data.get("proposals") or []:
            proposal = _proposal(event, goal, reason_no)
            name = proposal["goal"]
            if name not in folded.goal_ids or name in folded.accepted:
                continue
            changed += _material(folded.proposed.get(name), proposal)
            folded.proposed[name] = proposal
    elif outcome == "review":
        # A legacy review replaces every earlier proposal and moves an active board to
        # review even when it leaves a goal out, as it did when it was written.
        review = data.get("review") or {}
        folded.review_statement = str(review.get("statement", ""))
        folded.proposed = {}
        for goal in review.get("goals") or []:
            if isinstance(goal, dict) and str(goal.get("goal", "")) not in folded.accepted:
                folded.proposed[str(goal.get("goal", ""))] = _proposal(event, goal, reason_no)
        changed = 1
    legacy_review = "proposals" not in data and outcome == "review"
    covered = bool(folded.open_goals) and all(g in folded.proposed for g in folded.open_goals)
    if legacy_review or (covered and (changed or outcome == "review")):
        folded.checkpoint = dict(data.get("situation") or {}, had_work=False)
        folded.clear_stalls()
        if folded.status == m.ACTIVE:
            run.status(m.REVIEW)
            folded.review_reason = "answers"
    elif added or changed:
        folded.checkpoint = dict(data.get("situation") or {}, had_work=True)
        folded.clear_stalls()
    elif outcome == "noop" and not data.get("idle"):
        # A valid empty result while explores run: the open work covers the situation.
        folded.checkpoint = dict(data.get("situation") or {}, had_work=True)
        folded.clear_stalls()
    else:
        # Invalid, empty with nothing open, no progress, or a failed request: the board stays
        # due, up to the limit.
        folded.invalid_reasons += 1
        cause = {"invalid": m.CAUSE_INVALID, m.MODEL_FAILURE: m.CAUSE_MODEL_FAILURE}.get(
            outcome, m.CAUSE_NO_DIRECTION)
        folded.stall_causes[cause] = folded.stall_causes.get(cause, 0) + 1
        folded.last_stall_cause = cause


@dataclass
class ReasonAction:
    board_id: str
    reason_no: int
    stalled: bool
    final: bool = False
    assessed_budget: int = 0
    assessment_id: str = ""


@dataclass
class ExploreAction:
    board_id: str
    intent_id: str
    attempt: int


@dataclass
class Actions:
    reasons: list[ReasonAction] = field(default_factory=list)
    explores: list[ExploreAction] = field(default_factory=list)
    cancels: list[tuple[str, str]] = field(default_factory=list)
    reviews: list[tuple[str, str]] = field(default_factory=list)
    #: Final assessments that closed without a terminal record: `(board_id, assessed_budget)`.
    final_failures: list[tuple[str, int]] = field(default_factory=list)


def earlier_objectives(folded: Folded) -> list[str]:
    """The objectives that a new intent must not repeat. An intent whose fact a person
    rejected is left out, so a reason can declare its work again."""
    return [i.objective for i in folded.intents.values() if not (i.fact_id and i.fact_id in folded.rejected)]


def may_explore(folded: Folded, intent_id: str) -> bool:
    """Whether an explore of `intent_id` may run now. An active board runs every intent. A
    board in review or complete runs only the intents of a person's question. The planner
    and the explore activity both read this rule."""
    intent = folded.intents.get(intent_id)
    if folded.status == m.ACTIVE:
        return True
    return (folded.status in (m.REVIEW, m.COMPLETED) and intent is not None
            and intent.origin == m.ORIGIN_PERSON_QUESTION)


def explores_left(folded: Folded) -> int:
    """The explores that may still start."""
    return min(folded.max_explores, m.EXPLORE_LIMIT) - folded.explores_used


def reason_due(folded: Folded, in_flight: bool) -> bool:
    """Whether a reason should run for this board now. See the module rules."""
    if folded.status != m.ACTIVE or in_flight or folded.by_state(m.OPEN):
        return False
    if any(op["state"] == "running" for op in folded.final_ops.values()):
        return False
    if folded.reasons_done == 0:
        return True
    idle = not folded.by_state(m.RUNNING)
    if idle and folded.invalid_reasons:
        return True
    checkpoint = folded.checkpoint or {}
    seen = {k: checkpoint.get(k, 0) for k in ("facts", "hints", "rejected", "goals_added")}
    if seen != folded.situation():
        return True
    return idle and bool(checkpoint.get("had_work"))


def plan(boards: list, folded: dict, in_flight: set, cap: int,
         busy: set | None = None, reserved: dict | None = None) -> Actions:
    """The work to start and cancel, within the global cap.

    `boards` are the board rows, `folded` maps a board id to its fold, `in_flight` holds the
    board ids with a reason in flight or waiting to start, `cap` is
    `board_max_parallel_explores`. `busy` holds the boards with an uncommitted command, which
    get no new decision in this pass. `reserved` maps a board id to its pending explore
    starts, which take slots and explores.
    """
    busy = busy or set()
    reserved = reserved or {}
    actions = Actions()
    used = (len(in_flight) + sum(len(f.by_state(m.RUNNING)) for f in folded.values())
            + sum(reserved.values()))

    def turn(board) -> tuple:
        """A board with less work in flight goes first, then the board that has received
        less work so far, so one board cannot take every free slot while another waits for
        its first reason. The older board breaks a tie."""
        f = folded[board.board_id]
        busy_slots = (len(f.by_state(m.RUNNING)) + (1 if board.board_id in in_flight else 0)
                      + reserved.get(board.board_id, 0))
        return (busy_slots, f.explores_used + f.reasons_started, str(board.created_at or ""))

    for board in sorted(boards, key=turn):
        f = folded[board.board_id]
        running = f.by_state(m.RUNNING)
        if f.status in (m.PAUSED, m.DROPPED):
            actions.cancels.extend((board.board_id, i.intent_id) for i in running)
            continue
        if board.board_id in busy:
            continue
        board_used = len(running) + (1 if board.board_id in in_flight else 0) + reserved.get(board.board_id, 0)
        budget_left = explores_left(f) - reserved.get(board.board_id, 0)
        if f.status != m.ACTIVE:
            # A board in review or complete runs only the questions that a person asked.
            for intent in f.by_state(m.OPEN):
                if not may_explore(f, intent.intent_id):
                    continue
                if used >= cap or board_used >= max(1, board.max_parallel) or budget_left <= 0:
                    break
                actions.explores.append(ExploreAction(board.board_id, intent.intent_id, intent.started + 1))
                used += 1
                board_used += 1
                budget_left -= 1
            continue
        if f.explores_used >= f.max_explores and not running:
            if board.board_id in in_flight:
                continue
            op = f.final_ops.get(str(f.max_explores))
            if op is None:
                if used < cap:
                    actions.reasons.append(ReasonAction(
                        board.board_id, f.reasons_started + 1, False, True, f.max_explores,
                        f"final-{f.max_explores}"))
                    used += 1
            elif op["state"] == "running":
                actions.final_failures.append((board.board_id, f.max_explores))
            else:
                actions.reviews.append((board.board_id, "budget"))
            continue
        if (f.invalid_reasons >= m.INVALID_REASON_LIMIT and not running
                and not f.by_state(m.OPEN)):
            actions.reviews.append((board.board_id, f.stall_review_reason()))
            continue
        if used < cap and board_used < max(1, board.max_parallel) and reason_due(
                f, board.board_id in in_flight):
            actions.reasons.append(ReasonAction(
                board.board_id, f.reasons_started + 1, f.stall_count >= m.STALL_THRESHOLD))
            used += 1
            board_used += 1
        for intent in f.by_state(m.OPEN):
            if used >= cap or board_used >= max(1, board.max_parallel) or budget_left <= 0:
                break
            actions.explores.append(ExploreAction(board.board_id, intent.intent_id, intent.started + 1))
            used += 1
            board_used += 1
            budget_left -= 1
    return actions
