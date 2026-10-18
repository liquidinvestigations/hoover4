"""Constants and names shared by the board fold, activities and workflows.

A board is a long-running investigation: a goal, board facts, intents that agents explore,
and the events of every action. `docs/architecture/Boards.md` describes the whole system.
"""

#: The queue of `BoardDispatcher`, `BoardExplore` and their short activities.
#: **Mirrored in `website/backend/src/api/boards.rs`.** The names move together.
BOARD_TASK_QUEUE = "board-queue"

#: The fixed id of the singleton dispatcher workflow.
DISPATCHER_WORKFLOW_ID = "board-dispatcher"

#: The id prefix of every explore chat session. The chat history leaves these sessions out,
#: and the website refuses a person's message into one.
#: **Mirrored in `website/backend/src/db_chat/mod.rs`.**
SESSION_PREFIX = "board-"

# Board statuses.
ACTIVE = "active"
PAUSED = "paused"
REVIEW = "review"
COMPLETED = "completed"
DROPPED = "dropped"

# Intent states.
OPEN = "open"
RUNNING = "running"
CONCLUDED = "concluded"
FAILED = "failed"
QUESTION = "question"
CANCELLED = "cancelled"

# Fact kinds.
ORIGIN = "origin"
GOAL = "goal"
#: The legacy fact id of the first goal. Further legacy goals are `goal-2`, `goal-3` and so on.
FIRST_GOAL_ID = "goal"
#: The fact id of the background of a board with slug identifiers. The legacy id is `origin`.
BACKGROUND_ID = "background"
#: The most goals of one board. **Mirrored in `website/common/src/board_types.rs`** (`MAX_GOALS`).
MAX_GOALS = 6
SOURCED = "sourced"
INFERRED = "inferred"
NOT_FOUND = "not_found"
CORRECTION = "correction"
EXPLORE_KINDS = (SOURCED, INFERRED, NOT_FOUND)

# Event types written by the website.
BOARD_CREATED = "board_created"
HINT_ADDED = "hint_added"
FACT_REJECTED = "fact_rejected"
PAUSE_REQUESTED = "pause_requested"
RESUME_REQUESTED = "resume_requested"
REVIEW_ACCEPTED = "review_accepted"
REVIEW_REJECTED = "review_rejected"
DROP_REQUESTED = "drop_requested"
SETTINGS_CHANGED = "settings_changed"
#: A person added a goal to a board that exists. The subject is the goal id.
GOAL_ADDED = "goal_added"
#: A person asked to explore a question. The subject is the new intent id. The payload names
#: the fact, the question, and either the 0-based position of an open question of the fact
#: (`index`) or `own: true` for a question that the person wrote. A legacy event has the
#: subject `i0.N` and no `intent_id` in its payload.
QUESTION_EXPLORED = "question_explored"
#: A person reopened a board in review or complete, with up to `EXTENSION_EXPLORES` more
#: explores. The payload names the review or completion it decides (`expected_id`), the
#: status before, and the actual grant, which is 0 at the cap.
BUDGET_EXTENDED = "budget_extended"
#: A person accepted the proposed answer of one goal. The subject is the goal id, and the
#: payload is the answer: `reason_no`, `from` and `statement`.
GOAL_ANSWER_ACCEPTED = "goal_answer_accepted"
#: A person rejected the proposed answer of one goal. The subject is the correction fact, and
#: the payload holds `goal`, `reason_no`, `from` and `correction`.
GOAL_ANSWER_REJECTED = "goal_answer_rejected"

# Event types written by the board activities.
REASON_STARTED = "reason_started"
REASON_RESULT = "reason_result"
EXPLORE_STARTED = "explore_started"
EXPLORE_CONCLUDED = "explore_concluded"
EXPLORE_FAILED = "explore_failed"
EXPLORE_CANCELLED = "explore_cancelled"
EXPLORE_QUESTION = "explore_question"
REVIEW_PROPOSED = "review_proposed"
#: The terminal record of a final assessment that wrote no result: its call failed in every
#: attempt, or it closed without a result.
FINAL_ASSESSMENT_ENDED = "final_assessment_ended"

#: A derived row of the event log: one status transition of the board, written by
#: `board_plan` after its causal event. The fold ignores it. Its id is
#: `status_changed:<causal event id>:<ordinal>`.
STATUS_CHANGED = "status_changed"

# The origin of an intent.
ORIGIN_ASSESSMENT = "assessment"
ORIGIN_PERSON_QUESTION = "person_question"

# The kind of a proposed goal answer. A supported answer names its own sourced fact. A
# not-established answer names only not-found facts and says that the cited records do not
# establish an answer.
SUPPORTED = "supported"
NOT_ESTABLISHED = "not_established"
#: The statement of a not-established answer. Model text never replaces it.
#: **Mirrored in `website/common/src/board_types.rs`** (`NOT_ESTABLISHED_STATEMENT`).
NOT_ESTABLISHED_STATEMENT = "The cited records do not establish an answer to this goal."

#: Attempts of one intent that count. A cancellation by a pause does not count.
MAX_ATTEMPTS = 2
#: Intents one reason may declare.
MAX_INTENTS = 3
#: Explores in a row without a new sourced fact, after which reason is told the board stalled.
STALL_THRESHOLD = 4
#: Assessments in a row without progress and with no open intent, after which the board goes
#: to review.
INVALID_REASON_LIMIT = 3

#: The `reason_result` outcome of an assessment whose model request failed in every attempt,
#: or was refused. Older results of a failed request have the outcome `invalid`.
MODEL_FAILURE = "model_failure"

# The causes of an assessment without progress, which the fold counts in `stall_causes`.
# A valid reply without new work, a reply without a valid JSON object, and a failed request.
CAUSE_NO_DIRECTION = "no_direction"
CAUSE_INVALID = "invalid"
CAUSE_MODEL_FAILURE = "model_failure"

# The `review_proposed` reasons of a board that stopped without progress, by cause. An older
# event has the reason `stalled` for every cause. **Mirrored in
# `website/common/src/board_types.rs`** (`BoardSnapshot.review_reason`).
STALLED_NO_DIRECTION = "stalled_no_direction"
STALLED_INVALID = "stalled_invalid"
MODEL_UNAVAILABLE = "model_unavailable"
STALL_REVIEW_REASONS = {CAUSE_NO_DIRECTION: STALLED_NO_DIRECTION, CAUSE_INVALID: STALLED_INVALID,
                        CAUSE_MODEL_FAILURE: MODEL_UNAVAILABLE}
#: Output tokens of one reason call. The reasoning of the model counts against it, and
#: replies of 3,000 to 4,000 tokens with a short JSON object are common, so a lower cap cuts
#: the object off and the reply is invalid.
REASON_MAX_TOKENS = 16000
#: Model steps of the conclude turn that asks for the fact only.
CONCLUDE_STEP_BUDGET = 4

# The explore budget of a board. The base covers the first goal. Each further goal, at
# creation or later, adds `GOAL_EXPLORES`. Each hint, explored question, own question,
# rejected fact and rejected answer or review adds `ACTION_EXPLORES`, and each reopening
# adds `EXTENSION_EXPLORES`. The budget never exceeds `EXPLORE_LIMIT`, and no explore starts
# once a board has used `EXPLORE_LIMIT` explores. The person sets no budget.
# **Mirrored in `website/common/src/board_types.rs`.**
BASE_EXPLORES = 30
GOAL_EXPLORES = 25
ACTION_EXPLORES = 4
EXTENSION_EXPLORES = 50
EXPLORE_LIMIT = 300
# The model steps of one explore. A rejected fact, a rejected answer or review and a later
# goal add the correction steps, and a hint adds the hint steps, up to the cap.
BASE_EXPLORE_STEPS = 60
CORRECTION_EXPLORE_STEPS = 20
HINT_EXPLORE_STEPS = 5
MAX_EXPLORE_STEPS = 120

#: The tool that ends an explore turn with its fact. Only board turns have it.
#: **Mirrored in `research_agent/board_tools.py` and in the website's tool card.**
SUBMIT_FACT_TOOL = "submit_board_fact"


def goal_id_for(index: int) -> str:
    """The legacy fact id of the `index`-th goal (1-based) of a board."""
    return FIRST_GOAL_ID if index == 1 else f"goal-{index}"


def goal_slot_id(slot: int) -> str:
    """The fact id of the goal in slot `slot` of a board with slug identifiers: `goal-01`."""
    return f"goal-{slot:02d}"


def goal_slot(fact_id: str) -> int:
    """The 1-based slot of a goal id in either form: `goal` is 1, `goal-2` and `goal-02` are 2.
    0 for another id. **Mirrored in `website/common/src/board_types.rs`** (`goal_slot`)."""
    if fact_id == FIRST_GOAL_ID:
        return 1
    rest = fact_id[len("goal-"):] if fact_id.startswith("goal-") else ""
    return int(rest) if rest.isdigit() and rest.isascii() and int(rest) > 0 else 0


def question_key(fact_id: str, index: int) -> str:
    """The key of open question `index` (0-based) of a fact: `<fact_id>#<1-based index>`.
    The fact id is opaque. **Mirrored in `website/common/src/board_types.rs`**."""
    return f"{fact_id}#{index + 1}"


def parse_question_key(key: str) -> tuple[str, int] | None:
    """The fact id and the 0-based index of a question key, or None."""
    fact_id, _, number = str(key).rpartition("#")
    if not fact_id or not number.isdigit() or not number.isascii() or int(number) < 1:
        return None
    return fact_id, int(number) - 1


def session_id_for(board_id: str, intent_id: str) -> str:
    """The chat session of an intent. Every attempt and conclude turn of it run there."""
    return f"{SESSION_PREFIX}{board_id}-{intent_id}"


def explore_workflow_id(board_id: str, intent_id: str) -> str:
    """The id of the `BoardExplore` of an intent. Temporal refuses a second open workflow
    with one id, so one intent never has two explores at once."""
    return f"board-explore-{board_id}-{intent_id}"


# Legacy identifiers. An event without explicit node metadata names its nodes this way, and
# the command writer allocates these forms while `board_node_identity_version` is 1. No
# reader applies them to an explicit identifier.


def intent_id_for(reason_no: int, index: int) -> str:
    """The legacy id of the `index`-th intent (1-based) of reason `reason_no`."""
    return f"i{reason_no}.{index}"


#: The prefix of the legacy intents that a person starts from an open question. Reasons
#: start at 1, so reason number 0 is free.
QUESTION_INTENT_PREFIX = "i0."


def is_question_intent(intent_id: str) -> bool:
    """Whether `intent_id` has the legacy form `i0.<digits>` of an intent from a question."""
    rest = intent_id[len(QUESTION_INTENT_PREFIX):] if intent_id.startswith(QUESTION_INTENT_PREFIX) else ""
    return rest.isdigit() and rest.isascii()


def is_legacy_intent(intent_id: str) -> bool:
    """Whether `intent_id` has the legacy form `i<digits>.<digits>`."""
    head, _, tail = intent_id[1:].partition(".")
    return intent_id.startswith("i") and all(p.isdigit() and p.isascii() for p in (head, tail))


def fact_id_for(intent_id: str) -> str:
    """The legacy id of the fact a legacy intent concludes in: `i3.2` gives `f3.2`."""
    return "f" + intent_id[1:]
