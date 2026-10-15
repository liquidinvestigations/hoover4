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
#: The fact id of the first goal. Further goals are `goal-2`, `goal-3` and so on.
FIRST_GOAL_ID = "goal"
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
#: A person asked to explore an open question. The subject is the intent id `i0.N`, where
#: N counts the explored questions of the board from 1. The payload names the fact, the
#: position of the question in it, and the question.
QUESTION_EXPLORED = "question_explored"
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

#: Attempts of one intent that count. A cancellation by a pause does not count.
MAX_ATTEMPTS = 2
#: Intents one reason may declare.
MAX_INTENTS = 3
#: Explores in a row without a new sourced fact, after which reason is told the board stalled.
STALL_THRESHOLD = 4
#: Invalid or empty reasons in a row with no open intent, after which the board goes to review.
INVALID_REASON_LIMIT = 3
#: Output tokens of one reason call. The reasoning of the model counts against it, and
#: replies of 3,000 to 4,000 tokens with a short JSON object are common, so a lower cap cuts
#: the object off and the reply is invalid.
REASON_MAX_TOKENS = 16000
#: Model steps of the conclude turn that asks for the fact only.
CONCLUDE_STEP_BUDGET = 4

# The explore budget of a board and the model steps of one explore. A board starts at the
# base values. A rejected fact or a rejected review adds the correction values, and a hint
# adds the hint values, up to the caps. The person sets no budget.
BASE_EXPLORES = 12
BASE_EXPLORE_STEPS = 60
CORRECTION_EXPLORES = 4
CORRECTION_EXPLORE_STEPS = 20
HINT_EXPLORES = 1
HINT_EXPLORE_STEPS = 5
MAX_EXPLORES = 24
MAX_EXPLORE_STEPS = 120
#: The explores that one explored open question adds. A late goal adds the correction
#: values. Both are added above `MAX_EXPLORES`, so a person's request after the budget is
#: used still gets its explore.
QUESTION_EXPLORES = 1

#: The tool that ends an explore turn with its fact. Only board turns have it.
#: **Mirrored in `research_agent/board_tools.py` and in the website's tool card.**
SUBMIT_FACT_TOOL = "submit_board_fact"


def goal_id_for(index: int) -> str:
    """The fact id of the `index`-th goal (1-based) of a board.

    **Mirrored in `website/backend/src/api/boards.rs`**, which writes the goal facts."""
    return FIRST_GOAL_ID if index == 1 else f"goal-{index}"


def session_id_for(board_id: str, intent_id: str) -> str:
    """The chat session of an intent. Every attempt and conclude turn of it run there."""
    return f"{SESSION_PREFIX}{board_id}-{intent_id}"


def explore_workflow_id(board_id: str, intent_id: str) -> str:
    """The id of the `BoardExplore` of an intent. Temporal refuses a second open workflow
    with one id, so one intent never has two explores at once."""
    return f"board-explore-{board_id}-{intent_id}"


def intent_id_for(reason_no: int, index: int) -> str:
    """The id of the `index`-th intent (1-based) of reason `reason_no`."""
    return f"i{reason_no}.{index}"


#: The prefix of the intents that a person starts from an open question. Reasons start at 1,
#: so reason number 0 is free. **Mirrored in `website/common/src/board_types.rs`**
#: (`QUESTION_INTENT_PREFIX`).
QUESTION_INTENT_PREFIX = "i0."


def is_question_intent(intent_id: str) -> bool:
    """Whether `intent_id` has the form `i0.<digits>` of an intent from an open question."""
    rest = intent_id[len(QUESTION_INTENT_PREFIX):] if intent_id.startswith(QUESTION_INTENT_PREFIX) else ""
    return rest.isdigit() and rest.isascii()


def fact_id_for(intent_id: str) -> str:
    """The id of the fact an intent concludes in: `i3.2` gives `f3.2`."""
    return "f" + intent_id[1:]
