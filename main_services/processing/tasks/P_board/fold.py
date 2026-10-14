"""The fold and the planner: pure functions over the stored rows of a board.

`fold` turns the events of one board into its status, counters and intents. `plan` reads
the folded boards and returns the work the dispatcher starts or cancels. Neither function
reads storage or the clock, so the unit tests in `tests/unit/test_board_fold.py` exercise
every rule without ClickHouse or Temporal.

The rules:

* **Status.** A person's pause, resume, review decision or drop applies in event order. A
  reason result of outcome `review`, and a `review_proposed` of the dispatcher, move an
  active board to review. Only `review_accepted` completes a board.
* **Attempts.** `explore_started` counts an attempt and an explore of the budget. A
  cancellation refunds both. When one attempt has both a concluded event and a cancelled or
  failed event, the concluded event wins, because its fact exists.
* **Reason trigger.** A reason is due when the board is active, no reason is in flight, no
  intent is open, and the situation changed since the checkpoint of the last successful
  reason: more facts, more hints, more rejections, or the open and running intents falling
  to none. A valid empty result while explores run moves the checkpoint. An invalid result,
  or an empty one with nothing running, does not, so the board stays due, and after
  `INVALID_REASON_LIMIT` such results in a row the board goes to review.
* **One cap.** Each running explore and each reason in flight takes one board model slot.
  All boards together use at most the global cap, and each board at most its `max_parallel`.
"""

from dataclasses import dataclass, field

from tasks.P_board import model as m


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
    review_from: list[str] = field(default_factory=list)
    last_reason_outcome: str = ""

    def situation(self) -> dict:
        """The counts a reason checkpoint compares."""
        return {"facts": self.fact_count, "hints": len(self.hints), "rejected": len(self.rejected)}

    def by_state(self, state: str) -> list[Intent]:
        return sorted((i for i in self.intents.values() if i.state == state),
                      key=lambda i: (i.reason_no, i.intent_id))


def _concluded_attempts(events) -> set[tuple[str, int]]:
    return {(e.subject, int(e.payload.get("attempt", 0)))
            for e in events if e.event_type == m.EXPLORE_CONCLUDED}


def fold(board, events, facts) -> Folded:
    """The state of one board from its definition, its events and its facts."""
    folded = Folded(board_id=board.board_id)
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
            folded.status = m.COMPLETED
        elif kind == m.REVIEW_REJECTED and folded.status in (m.REVIEW, m.COMPLETED):
            folded.status = m.ACTIVE
            folded.invalid_reasons = 0
            folded.stall_count = 0
        elif kind == m.DROP_REQUESTED:
            folded.status = m.DROPPED
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
        folded.review_from = [str(f) for f in review.get("from") or []]
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
    seen = {k: checkpoint.get(k, 0) for k in ("facts", "hints", "rejected")}
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
            continue
        if f.explores_used >= board.max_explores and not running:
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
        budget_left = board.max_explores - f.explores_used
        for intent in f.by_state(m.OPEN):
            if used >= cap or board_used >= max(1, board.max_parallel) or budget_left <= 0:
                break
            actions.explores.append(ExploreAction(board.board_id, intent.intent_id, intent.started + 1))
            used += 1
            board_used += 1
            budget_left -= 1
    return actions
