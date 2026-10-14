"""The fold and the planner: pure functions over the stored rows of a board.

`fold` turns the events of one board into its status, counters and intents. `plan` reads
the folded boards and returns the work the dispatcher starts or cancels. Neither function
reads storage or the clock, so the unit tests in `tests/unit/test_board_fold.py` exercise
every rule without ClickHouse or Temporal.

The rules:

* **Status.** A person's pause, resume, decision or drop applies in event order. A reason
  result of outcome `review`, and a `review_proposed` of the dispatcher, move an active board
  to review. A rejected review and a `goal_added` move a board in review or complete back to
  active.
* **Goal answers.** A reason result of outcome `review` proposes one answer for each goal
  that has no accepted answer, and replaces every earlier proposed answer. The person
  decides each answer separately. `goal_answer_accepted` moves it to the accepted answers,
  which no later event removes. The board is complete when every goal has an accepted
  answer. A board in review with no proposed answer left goes back to active.
  `goal_answer_rejected` drops the answer and moves a board in review to active at once,
  while the other proposed answers wait. A decision counts only for the proposed answer of
  the same reason. `review_accepted` accepts every proposed answer and completes the board,
  also with goals that have no answer. `review_rejected` drops every proposed answer.
* **Late work of a person.** `goal_added` adds a goal that the next reason reads, and sets
  `had_work` in the checkpoint, so the board gets a reason when its work ends without a new
  fact. `question_explored` opens the intent `i0.N` from the fact that asked the question,
  with the question as its objective, and changes no status. `plan` starts such an intent on
  a board in review or complete too, and runs nothing else there.
* **Attempts.** `explore_started` counts an attempt and an explore of the budget. A
  cancellation refunds both. When one attempt has both a concluded event and a cancelled or
  failed event, the concluded event wins, because its fact exists.
* **Reason trigger.** A reason is due when the board is active, no reason is in flight, no
  intent is open, and the situation changed since the checkpoint of the last successful
  reason: more facts, more hints, more rejections, more goals added later, or the open and
  running intents falling to none. A checkpoint written before `goals_added` existed reads it
  as 0. A valid empty result while explores run moves the checkpoint. An invalid result,
  or an empty one with nothing running, does not, so the board stays due, and after
  `INVALID_REASON_LIMIT` such results in a row the board goes to review.
* **Budget.** `Folded.max_explores` and `Folded.explore_steps` start at the base values of
  `model` and grow with each rejected fact, rejected review and hint, up to the caps. Each
  goal added later adds the correction values, and each explored question
  `QUESTION_EXPLORES`, above the explore cap. A repeated event of one subject counts once.
  The explore budget and the step count of the board row are not read.
* **One cap.** Each running explore and each reason in flight takes one board model slot.
  All boards together use at most the global cap, and each board at most its `max_parallel`.
"""

from dataclasses import dataclass, field

from tasks.P_board import model as m
from tasks.P_board.prompts import goal_ids


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
    #: Goal id to the answer that waits for the person: `goal`, `from`, `statement` and
    #: `reason_no`, the number of the reason that proposed it.
    proposed: dict = field(default_factory=dict)
    #: Goal id to the answer that the person accepted, in the same form.
    accepted: dict = field(default_factory=dict)
    review_rejections: int = 0
    last_reason_outcome: str = ""
    #: The checks that changed the last reason reply, which the next reason reads.
    last_reason_problems: list[str] = field(default_factory=list)
    #: The goal ids of `goal_added` events and the intent ids of `question_explored` events.
    goals_added: set = field(default_factory=set)
    questions_explored: set = field(default_factory=set)

    @property
    def max_explores(self) -> int:
        """The explore budget: the base, grown by the person's corrections and hints."""
        corrections = len(self.rejected) + self.review_rejections
        capped = min(m.MAX_EXPLORES, m.BASE_EXPLORES + corrections * m.CORRECTION_EXPLORES
                     + len(self.hints) * m.HINT_EXPLORES)
        return (capped + len(self.goals_added) * m.CORRECTION_EXPLORES
                + len(self.questions_explored) * m.QUESTION_EXPLORES)

    @property
    def explore_steps(self) -> int:
        """The model steps of one explore turn, grown as `max_explores`."""
        corrections = len(self.rejected) + self.review_rejections + len(self.goals_added)
        return min(m.MAX_EXPLORE_STEPS, m.BASE_EXPLORE_STEPS
                   + corrections * m.CORRECTION_EXPLORE_STEPS + len(self.hints) * m.HINT_EXPLORE_STEPS)

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
                      key=lambda i: (i.reason_no, i.intent_id))


def _concluded_attempts(events) -> set[tuple[str, int]]:
    return {(e.subject, int(e.payload.get("attempt", 0)))
            for e in events if e.event_type == m.EXPLORE_CONCLUDED}


def fold(board, events, facts) -> Folded:
    """The state of one board from its definition, its events and its facts."""
    folded = Folded(board_id=board.board_id, goal_ids=goal_ids(facts))
    concluded = _concluded_attempts(events)
    for event in events:
        kind = event.event_type
        data = event.payload or {}
        if kind == m.HINT_ADDED:
            folded.hints.append(str(data.get("text", "")))
            for intent in folded.intents.values():
                if intent.state == m.QUESTION:
                    intent.state = m.OPEN
        elif kind == m.FACT_REJECTED:
            folded.rejected[event.subject] = str(data.get("reason", ""))
        elif kind == m.PAUSE_REQUESTED and folded.status == m.ACTIVE:
            folded.status = m.PAUSED
        elif kind == m.RESUME_REQUESTED and folded.status == m.PAUSED:
            folded.status = m.ACTIVE
        elif kind == m.REVIEW_ACCEPTED and folded.status == m.REVIEW:
            folded.accepted.update(folded.proposed)
            folded.proposed = {}
            folded.status = m.COMPLETED
        elif kind == m.REVIEW_REJECTED and folded.status in (m.REVIEW, m.COMPLETED):
            folded.proposed = {}
            folded.review_rejections += 1
            folded.status = m.ACTIVE
            folded.invalid_reasons = 0
            folded.stall_count = 0
        elif kind == m.GOAL_ANSWER_ACCEPTED:
            if _decides(folded, event.subject, data):
                folded.accepted[event.subject] = folded.proposed.pop(event.subject)
                if folded.status in (m.ACTIVE, m.REVIEW) and folded.all_answered:
                    folded.status = m.COMPLETED
                elif folded.status == m.REVIEW and not folded.proposed:
                    folded.status = m.ACTIVE
                    folded.checkpoint = dict(folded.checkpoint or {}, had_work=True)
        elif kind == m.GOAL_ANSWER_REJECTED:
            goal = str(data.get("goal", ""))
            if _decides(folded, goal, data):
                del folded.proposed[goal]
                folded.review_rejections += 1
                if folded.status == m.REVIEW:
                    folded.status = m.ACTIVE
                    folded.invalid_reasons = 0
                    folded.stall_count = 0
        elif kind == m.DROP_REQUESTED:
            folded.status = m.DROPPED
        elif kind == m.GOAL_ADDED:
            folded.goals_added.add(event.subject)
            _reopen(folded)
        elif kind == m.QUESTION_EXPLORED:
            if m.is_question_intent(event.subject) and event.subject not in folded.intents:
                fact_id = str(data.get("fact_id", ""))
                folded.intents[event.subject] = Intent(
                    intent_id=event.subject, reason_no=0, from_facts=[fact_id] if fact_id else [],
                    objective=str(data.get("question", "")),
                    brief=f"The investigator asked to explore this open question of fact {fact_id}.",
                    created_at=event.created_at)
                folded.questions_explored.add(event.subject)
        elif kind == m.REVIEW_PROPOSED and folded.status == m.ACTIVE:
            folded.status = m.REVIEW
            folded.review_statement = str(data.get("statement", ""))
        elif kind == m.REASON_STARTED:
            folded.reasons_started = max(folded.reasons_started, _int(event.subject))
        elif kind == m.REASON_RESULT:
            _apply_reason(folded, event)
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
                continue
            if intent.state != m.RUNNING or intent.running_attempt != attempt:
                continue
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
    if board.is_deleted:
        folded.status = m.DROPPED
    live = [f for f in facts if f.fact_id not in folded.rejected and f.kind not in (m.ORIGIN, m.GOAL)]
    folded.fact_count = len(live)
    folded.sourced_count = sum(1 for f in live if f.kind == m.SOURCED)
    return folded


def _decides(folded: Folded, goal: str, data: dict) -> bool:
    """Whether a person's decision names the answer that waits for goal `goal`: the decision
    on an answer that a newer reason replaced does nothing."""
    answer = folded.proposed.get(goal)
    return answer is not None and answer.get("reason_no") == _int(str(data.get("reason_no", "")))


def _reopen(folded: Folded) -> None:
    """A person's late work: a board in review or complete goes back to active, and the next
    idle pass runs a reason even when the work ends without a fact."""
    if folded.status in (m.REVIEW, m.COMPLETED):
        folded.status = m.ACTIVE
        folded.invalid_reasons = 0
        folded.stall_count = 0
    folded.checkpoint = dict(folded.checkpoint or {}, had_work=True)


def _int(text: str) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def _apply_reason(folded: Folded, event) -> None:
    data = event.payload or {}
    reason_no = _int(event.subject)
    folded.reasons_done += 1
    outcome = data.get("outcome", "")
    folded.last_reason_outcome = outcome
    folded.last_reason_problems = [str(p) for p in data.get("problems") or []]
    if outcome == "intents":
        for index, item in enumerate(data.get("intents") or [], start=1):
            intent_id = m.intent_id_for(reason_no, index)
            if intent_id not in folded.intents:
                folded.intents[intent_id] = Intent(
                    intent_id=intent_id, reason_no=reason_no,
                    from_facts=[str(f) for f in item.get("from") or []],
                    objective=str(item.get("objective", "")), brief=str(item.get("brief", "")),
                    created_at=event.created_at)
        folded.checkpoint = dict(data.get("situation") or {}, had_work=True)
        folded.invalid_reasons = 0
    elif outcome == "review":
        folded.checkpoint = dict(data.get("situation") or {}, had_work=False)
        folded.invalid_reasons = 0
        review = data.get("review") or {}
        folded.review_statement = str(review.get("statement", ""))
        folded.proposed = {}
        for goal in review.get("goals") or []:
            if isinstance(goal, dict) and str(goal.get("goal", "")) not in folded.accepted:
                folded.proposed[str(goal.get("goal", ""))] = {
                    "goal": str(goal.get("goal", "")), "from": [str(f) for f in goal.get("from") or []],
                    "statement": str(goal.get("statement", "")), "reason_no": reason_no}
        if folded.status == m.ACTIVE:
            folded.status = m.REVIEW
    elif outcome == "noop" and not data.get("idle"):
        # A valid empty result while explores run: the open work covers the situation.
        folded.checkpoint = dict(data.get("situation") or {}, had_work=True)
        folded.invalid_reasons = 0
    else:
        # Invalid, or empty with nothing open: the board stays due, up to the limit.
        folded.invalid_reasons += 1


@dataclass
class ReasonAction:
    board_id: str
    reason_no: int
    stalled: bool


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


def earlier_objectives(folded: Folded) -> list[str]:
    """The objectives that a new intent must not repeat. An intent whose fact a person
    rejected is left out, so a reason can declare its work again."""
    return [i.objective for i in folded.intents.values() if not (i.fact_id and i.fact_id in folded.rejected)]


def may_explore(folded: Folded, intent_id: str) -> bool:
    """Whether an explore of `intent_id` may run now. An active board runs every intent. A
    board in review or complete runs only the intents that a person asked from an open
    question. The planner and the explore activity both read this rule."""
    return folded.status == m.ACTIVE or (folded.status in (m.REVIEW, m.COMPLETED)
                                         and m.is_question_intent(intent_id))


def reason_due(folded: Folded, in_flight: bool) -> bool:
    """Whether a reason should run for this board now. See the module rules."""
    if folded.status != m.ACTIVE or in_flight or folded.by_state(m.OPEN):
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


def plan(boards: list, folded: dict, in_flight: set, cap: int) -> Actions:
    """The work to start and cancel, within the global cap.

    `boards` are the board rows, `folded` maps a board id to its fold, `in_flight` holds the
    board ids with a reason in flight, `cap` is `board_max_parallel_explores`.
    """
    actions = Actions()
    used = len(in_flight) + sum(len(f.by_state(m.RUNNING)) for f in folded.values())

    def oldest_work(board) -> tuple:
        f = folded[board.board_id]
        opened = f.by_state(m.OPEN)
        first = opened[0].created_at if opened else None
        return (first is None, str(first or ""), str(board.created_at or ""))

    for board in sorted(boards, key=oldest_work):
        f = folded[board.board_id]
        running = f.by_state(m.RUNNING)
        if f.status in (m.PAUSED, m.DROPPED):
            actions.cancels.extend((board.board_id, i.intent_id) for i in running)
            continue
        if f.status != m.ACTIVE:
            # A board in review or complete runs only the questions that a person asked.
            board_used = len(running) + (1 if board.board_id in in_flight else 0)
            budget_left = f.max_explores - f.explores_used
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
            actions.reviews.append((board.board_id, "budget"))
            continue
        if (f.invalid_reasons >= m.INVALID_REASON_LIMIT and not running
                and not f.by_state(m.OPEN)):
            actions.reviews.append((board.board_id, "stalled"))
            continue
        board_used = len(running) + (1 if board.board_id in in_flight else 0)
        if used < cap and board_used < max(1, board.max_parallel) and reason_due(
                f, board.board_id in in_flight):
            actions.reasons.append(ReasonAction(
                board.board_id, f.reasons_started + 1, f.stall_count >= m.STALL_THRESHOLD))
            used += 1
            board_used += 1
        budget_left = f.max_explores - f.explores_used
        for intent in f.by_state(m.OPEN):
            if used >= cap or board_used >= max(1, board.max_parallel) or budget_left <= 0:
                break
            actions.explores.append(ExploreAction(board.board_id, intent.intent_id, intent.started + 1))
            used += 1
            board_used += 1
            budget_left -= 1
    return actions
