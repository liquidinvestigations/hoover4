"""When a chat turn nags the agent to keep going, and what it says when it does.

The agent stops when the model stops calling tools, which is not the same as the work
being finished: the commonest way a turn ends badly is with a plan on the table and
half of it undone. A nag runs the agent again, in the same turn, pointed at the item it
left open.

**The rules here are pure and the loop that applies them lives in `ChatTurn`.** Not in
the agent: a nag counter kept inside the agent process is lost the moment that process
restarts, and the workflow is the only thing that knows the user's turn is still going.

Three numbers bound it, and each answers a different failure:

* **[`MAX_NAGS_WITHOUT_PROGRESS`]** -- an agent that is not moving will not start moving
  on the third ask. This resets when the plan itself changes.
* **[`MAX_NAGS_PER_TURN`]** -- the backstop that a resetting counter cannot lift. Past
  it the turn has failed and saying so is worth more than asking again.
* **[`NAG_TOOL_TURN_INCREMENT`]** -- each nag buys the agent a few more tool turns.
  Neither resetting the budget (which would make five nags a sixtyfold budget) nor
  leaving it alone (which would leave the second nag no room to do anything).

**What counts as progress is [`database.chat_todos.is_material_change`], and it ignores
status on purpose.** A model that earned a reset by flipping one row from `pending` to
`in_progress` would never reach either cap and the caps would be decorative. Adding,
removing or rewriting an item is progress; marking one done is not, however welcome it
is. That question is asked of the store rather than re-derived here, so the tool the
model calls and the loop that judges it cannot disagree.
"""

from __future__ import annotations

import os

from database import chat_todos

#: How many nags in a row are allowed while the plan itself is not moving.
MAX_NAGS_WITHOUT_PROGRESS = int(os.getenv("CHAT_MAX_NAGS_WITHOUT_PROGRESS", "2"))

#: How many nags one user-originated turn may ever contain, progress or not.
MAX_NAGS_PER_TURN = int(os.getenv("CHAT_MAX_NAGS_PER_TURN", "5"))

#: Extra tool turns granted to the agent per nag, cumulative across the turn.
NAG_TOOL_TURN_INCREMENT = int(os.getenv("CHAT_NAG_TOOL_TURNS", "6"))

#: Transcript role a nag is written under. It is not the user speaking, and a transcript
#: that implies it was makes the user responsible for words they never wrote.
NAG_ROLE = "nag"


def open_items(todo: dict) -> list[dict]:
    """The items still pending or in progress, in plan order."""
    return [
        item
        for item in todo.get("items", [])
        if item.get("status") not in chat_todos.RESOLVED_STATUSES
    ]


def stop_reason(todo: dict, nags_without_progress: int, nags_this_turn: int) -> str:
    """Why this turn should stop rather than nag again -- empty means nag.

    Order matters only for what the transcript says: the caps are checked after the
    plan, so a turn that finished its work is never told it ran out of nags.
    """
    if not chat_todos.is_open(todo):
        return "resolved"
    if nags_this_turn >= MAX_NAGS_PER_TURN:
        return (
            f"Stopping after {nags_this_turn} nudges in one turn with the plan still "
            f"unfinished ({chat_todos.summarise(todo)}). Ask again to continue it."
        )
    if nags_without_progress >= MAX_NAGS_WITHOUT_PROGRESS:
        return (
            f"Stopping: the plan has not changed across {nags_without_progress} nudges "
            f"({chat_todos.summarise(todo)}). Ask again, or say what to drop."
        )
    return ""


def nag_message(todo: dict, nag_number: int) -> str:
    """What the nag says, given how many it is into the current no-progress streak.

    **The first nag asks for the plan to be revised, not merely continued.** The usual
    reason an agent stops with an open todo is that it wrote a plan it could not finish,
    and telling it to try harder at an impossible step wastes both nags. So the first
    one offers the exit as well: finish the item, or cancel it with a reason -- which
    the store accepts as resolved, so an over-ambitious plan does not earn two nags for
    nothing. The second asks only for the work.

    The streak, not the turn, is what `nag_number` counts: an agent that made real
    progress and then stopped again is in the same position as one being nagged for the
    first time, and deserves the same offer.
    """
    still_open = open_items(todo)
    summary = chat_todos.summarise(todo)
    nxt = still_open[0]["text"] if still_open else ""
    head = (
        f"You have stopped, but your todo list is not finished: {summary}. "
        f"The next unresolved item is: {nxt}"
    )
    if nag_number <= 1:
        return (
            f"{head}\n\n"
            "Call `read_todo` to see the whole plan, then decide which of these is "
            "true, and act on it in this same reply:\n"
            "- the plan is still right: keep working through it, and call `mark_todo` "
            "as each item lands;\n"
            "- the plan was too ambitious or is now wrong: call `write_todo` with a "
            "revised plan, or `mark_todo` to cancel the items you are dropping, each "
            "with a note saying why.\n\n"
            "Do not answer with a summary of what you have already done. Either move "
            "the work forward or change the plan."
        )
    return (
        f"{head}\n\n"
        "Finish the remaining items now. Work through them with your tools and call "
        "`mark_todo` as each one lands. If an item truly cannot be done, cancel it "
        "with a note saying why. Do not restate the plan -- act on it."
    )


__all__ = [
    "MAX_NAGS_WITHOUT_PROGRESS",
    "MAX_NAGS_PER_TURN",
    "NAG_TOOL_TURN_INCREMENT",
    "NAG_ROLE",
    "nag_message",
    "open_items",
    "stop_reason",
]
