"""Temporal workflows for AI agent turns.

Two workflows, one shape. `ChatTurn` owns an ordinary chat turn and `ResearchTask` owns a
deep research run: they differ in which agent they reach, how long they may take, and
which queue they are dispatched to, not in what they do with the result.

`ChatTurn` runs on `chat-queue`, deliberately not on the ingestion queue. An ingestion
backlog delaying a chat turn is the one failure a shared queue guarantees and a separate
queue makes impossible, and it costs one worker process.
"""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import CancelledError

with workflow.unsafe.imports_passed_through():
    from database import chat_todos
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_agent import nagging
    from tasks.P_agent.activities import (
        ReadTodoParams,
        ResearchTaskParams,
        SummarizeSessionParams,
        WriteResultParams,
        read_chat_todo,
        run_research_agent,
        summarize_session,
        write_chat_message,
    )
    from tasks.P_agent.trajectory import pair_tool_calls


#: The queue chat turns are dispatched to. Named here so the worker that polls it and
#: the caller that addresses it cannot drift: a workflow addressed to a queue nothing is
#: polling waits for ever with no error anywhere, which presents as chat hanging.
CHAT_TASK_QUEUE = "chat-queue"

#: How long the chat agent activity may go without proving it is alive before Temporal
#: reschedules it on another worker.
#:
#: **This number and the website's `CHAT_STREAM_STALL_SECONDS` are one pair and must be
#: read together.** This one is how long a dead worker goes unnoticed; that one is how
#: long the page waits before telling the user the turn is dead. The page must never give
#: up first, because its advice is "ask again to retry" and a user who follows it while a
#: reschedule is still coming gets the same answer twice, from two workflows. So the
#: stall window is deliberately the larger of the two, by a wide margin: 60 s here
#: against a 180 s default there.
#:
#: 60 s is four missed beats -- `run_research_agent` carries `@with_heartbeat`, whose
#: pump beats every `HEARTBEAT_INTERVAL` (15 s) for as long as the body runs, so the
#: agent's own latency never enters this budget. Lowering it further starts trading
#: against a loaded box missing beats; raising it is worse than it looks, because the
#: deadline is also how long a wedged slot stays occupied (see `tasks.heartbeat`).
CHAT_AGENT_HEARTBEAT_TIMEOUT = timedelta(seconds=60)

async def _write_row(params, seq: int, role: str, content: str, **extra) -> None:
    """Append one finished transcript row.

    Short and retryable: the insert is keyed on `(username, session_id, seq)`, so a retry
    replaces the row rather than appending a second one.

    The three timeout arguments are spelled out rather than unpacked from a shared dict.
    `test_every_execute_activity_declares_a_heartbeat_timeout` reads the call sites as
    source, so a dict would hide the heartbeat from the check that exists to find a
    wedged activity in minutes instead of hours.
    """
    await workflow.execute_activity(
        write_chat_message,
        WriteResultParams(
            username=params.username,
            session_id=params.session_id,
            seq=seq,
            role=role,
            content=content,
            **extra,
        ),
        start_to_close_timeout=timedelta(minutes=2),
        heartbeat_timeout=HEARTBEAT_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
    )


async def _write_payload(
    params, payload: dict, empty_answer: str, start_seq: int, peak_floor: int = 0
) -> tuple[str, int, int]:
    """Write a finished agent payload into the transcript; return the answer, the next
    free `seq`, and the turn's peak context so far.

    Shared by both workflows because a research transcript and a chat transcript are the
    same rows -- keeping one writer is what stops them drifting into rendering
    differently, which they have done before.

    The starting position is passed rather than read off `params` because a nagged chat
    turn writes several payloads into one turn, and each has to land after the last.

    `peak_floor` is there for the same reason: one user turn is several agent runs once
    the nag loop is involved, and "peak this turn" is the maximum over all of them. Each
    round's row carries the running maximum, so the row a reader sees last is the row
    that tells the truth about the turn.
    """
    seq = start_seq

    # Pair start/end events into one row each, with the arguments, the result and any
    # documents surfaced, so every tool call renders as one card.
    for call in pair_tool_calls(payload.get("tool_calls", [])):
        await _write_row(
            params, seq, "tool", call.summary,
            tool_name=call.tool_name,
            tool_input=call.tool_input,
            tool_output=call.tool_output,
            doc_refs=call.doc_refs,
        )
        seq += 1

    # Token counts as the provider billed them. A missing key is 0, which every reader
    # renders as unknown -- an agent that reported no usage must not look free.
    usage = payload.get("usage") or {}
    peak = max(peak_floor, int(usage.get("peak_context_tokens") or 0))
    answer = payload.get("answer") or empty_answer
    await _write_row(
        params, seq, "assistant", answer,
        # The agent separates its narration from its answer; carrying the narration
        # through as `reasoning` is what keeps the disclosure working.
        reasoning=payload.get("reasoning") or "",
        model=payload.get("model") or "",
        context_tokens=int(usage.get("context_tokens") or 0),
        peak_context_tokens=peak,
        context_window=int(usage.get("context_window") or 0),
    )
    return answer, seq + 1, peak


def _was_cancelled(exc: BaseException) -> bool:
    """Whether this failure is a cancellation wearing another exception's clothes.

    Temporal wraps a cancelled activity in an `ActivityError` and hands that to the
    workflow, so the cancellation is only visible down the `__cause__` chain. The chain is
    walked rather than the top type inspected, because how deeply it is wrapped is the
    SDK's business and not a thing to depend on.
    """
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, (asyncio.CancelledError, CancelledError)):
            return True
        seen = seen.__cause__
    return False


async def _write_ending(params, seq: int, message: str) -> None:
    """Write a turn's last row, whatever is happening to the workflow around it.

    Shielded because the common reason a turn needs an ending is that it was cancelled,
    and a cancelled workflow cannot schedule new work in its own scope. Without the shield
    the stop button leaves a user row with nothing after it and the page follows a turn
    that will never speak again.
    """
    await asyncio.shield(_write_row(params, seq, "error", message))


async def _name_the_conversation(params, answer: str) -> None:
    """Give the conversation an LLM-written title, if this is the turn that names it.

    **Fire and forget, and it can never fail the turn.** The answer is already written and
    the user is already reading it by the time this runs, so a summariser that is down, or
    slow, or returns nonsense, is worth a mediocre title and nothing else. Three things
    enforce that together, because any one of them alone leaves a way for it to bite:

      * one attempt, so a broken endpoint is not retried into the user's face;
      * a short timeout, so a hung summariser cannot hold the workflow open;
      * every exception swallowed here, including the Temporal timeout and the activity
        failure that the activity itself cannot catch.

    The activity is careful too. This is the belt to its braces: a caller must not have to
    trust an activity to be harmless.

    A cancellation still propagates -- it is a `BaseException`, and a stop button pressed
    while the title is being written should end the workflow rather than be absorbed. The
    answer is already in the transcript by then, so nothing is lost.

    The fallback is the provisional title the website wrote from the first message, which
    is already in place -- doing nothing is the correct failure.
    """
    if not getattr(params, "summarize_session", False):
        return
    try:
        await workflow.execute_activity(
            summarize_session,
            SummarizeSessionParams(
                username=params.username,
                session_id=params.session_id,
                user_message=params.query,
                answer=answer,
            ),
            start_to_close_timeout=timedelta(seconds=90),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except Exception:  # noqa: BLE001 - a title is never worth an answer
        workflow.logger.warning(
            "could not title session %s; keeping the provisional title",
            params.session_id,
        )


@workflow.defn
class ChatTurn:
    """Own one ordinary chat turn, from dispatch to final answer.

    Every chat turn runs here. Before this, an ordinary turn was an HTTP request the
    website held open against the agent container: a website restart, a closed browser or
    a timed-out request lost the turn and the user saw a conversation that stopped
    mid-sentence. The workflow survives all three, and the turn resumes on whichever
    worker picks it up.

    It runs on `chat-queue` so an ingestion backlog can never delay a chat turn.

    Cancellation is what the interface's stop button does, and it writes an ending rather
    than vanishing: a user row with nothing after it leaves the page following a turn
    that will never speak again. The write is shielded because a cancelled workflow
    cannot schedule new work in its own scope.

    **The nag loop lives here** rather than in the agent, for the same reason the turn
    does: the workflow is what knows a user's turn is still going, and both nag counters
    have to outlive an agent process that may be restarted mid-turn. See
    `tasks.P_agent.nagging` for the rules it applies.
    """

    @workflow.run
    async def run(self, params: "ResearchTaskParams") -> str:
        seq = params.start_seq
        answer = ""
        #: Nags since the plan last actually moved, and nags in this whole user turn.
        #: The first resets on progress; the second never does, which is what keeps a
        #: model from farming resets and nagging itself forever.
        nags_without_progress = 0
        nags_this_turn = 0
        #: The largest context any round of this turn was billed for. One user turn is
        #: several agent runs once the nag loop is involved, so the peak is a maximum
        #: over the rounds and not whatever the last one happened to cost.
        turn_peak = 0
        #: The snapshot taken when the last nag was written, to compare against.
        todo_before_nag: dict | None = None
        round_params = params

        while True:
            try:
                raw = await workflow.execute_activity(
                    run_research_agent,
                    round_params,
                    # Shorter than a research run on purpose. A chat turn a user is
                    # watching that has produced nothing for a quarter of an hour is
                    # wedged, and failing it returns the answer slot to them.
                    start_to_close_timeout=timedelta(seconds=900),
                    heartbeat_timeout=CHAT_AGENT_HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except asyncio.CancelledError:
                await _write_ending(params, seq, "This turn was stopped.")
                raise
            except Exception as e:  # noqa: BLE001 - recorded for the user, then re-raised
                # A stop reaches here too, not only through `CancelledError`: cancelling
                # a workflow cancels the activity it is waiting on, and Temporal reports
                # that as an `ActivityError` wrapping the cancellation. Read as a failure
                # it put "The assistant could not answer: Activity cancelled" in front of
                # a user who had just pressed stop and knew perfectly well why the answer
                # had ended.
                if _was_cancelled(e):
                    await _write_ending(params, seq, "This turn was stopped.")
                else:
                    await _write_ending(params, seq, f"The assistant could not answer: {e}")
                raise

            answer, seq, turn_peak = await _write_payload(
                params, json.loads(raw), "(the assistant returned an empty answer)", seq,
                peak_floor=turn_peak,
            )

            todo = await self._read_todo(params)
            # Progress is the store's question, asked of the two snapshots either side of
            # the last nag. It is deliberately indifferent to status: see `nagging`.
            if todo_before_nag is not None and chat_todos.is_material_change(
                todo_before_nag, todo
            ):
                nags_without_progress = 0

            stop = nagging.stop_reason(todo, nags_without_progress, nags_this_turn)
            if stop:
                if stop != "resolved":
                    await _write_row(params, seq, nagging.NAG_ROLE, stop)
                    seq += 1
                break

            nags_this_turn += 1
            nags_without_progress += 1
            todo_before_nag = todo
            message = nagging.nag_message(todo, nags_without_progress)
            await _write_row(params, seq, nagging.NAG_ROLE, message)
            seq += 1
            round_params = replace(
                params,
                query=message,
                start_seq=seq,
                # Extended, never reset: five nags on a reset budget would be sixty tool
                # turns, and a nag with no budget left cannot do anything at all.
                extra_tool_turns=nags_this_turn * nagging.NAG_TOOL_TURN_INCREMENT,
            )

        await _name_the_conversation(params, answer)
        return answer

    async def _read_todo(self, params: "ResearchTaskParams") -> dict:
        """This session's todo list, as the nag loop's two questions need it."""
        raw = await workflow.execute_activity(
            read_chat_todo,
            ReadTodoParams(username=params.username, session_id=params.session_id),
            start_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        return json.loads(raw)


@workflow.defn
class ResearchTask:
    """Run the full research agent for one question and write the result into the chat.

    Split into two activities on purpose: the agent call is slow and retryable, while
    the write is fast and keyed, so a retried agent call cannot leave a half-written
    transcript behind.

    A failure is written into the transcript as an `error` row rather than left as a
    silently failed workflow. The user is looking at a chat window waiting for an
    answer, and "nothing ever appeared" is the one outcome that gives them nothing to
    act on.
    """

    @workflow.run
    async def run(self, params: "ResearchTaskParams") -> str:
        seq = params.start_seq
        try:
            raw = await workflow.execute_activity(
                run_research_agent,
                params,
                start_to_close_timeout=timedelta(seconds=2400),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as e:  # noqa: BLE001 - recorded for the user, then re-raised
            await _write_row(
                params, seq, "error", f"The research task failed: {e}",
            )
            raise

        answer, _, _ = await _write_payload(
            params, json.loads(raw), "(the research agent returned an empty answer)", seq
        )
        return answer
