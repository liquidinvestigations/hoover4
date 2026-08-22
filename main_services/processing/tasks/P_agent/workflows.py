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
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_agent.activities import (
        ResearchTaskParams,
        WriteResultParams,
        run_research_agent,
        write_chat_message,
    )
    from tasks.P_agent.trajectory import pair_tool_calls


#: The queue chat turns are dispatched to. Named here so the worker that polls it and
#: the caller that addresses it cannot drift: a workflow addressed to a queue nothing is
#: polling waits for ever with no error anywhere, which presents as chat hanging.
CHAT_TASK_QUEUE = "chat-queue"

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


async def _write_payload(params, payload: dict, empty_answer: str) -> str:
    """Write a finished agent payload into the transcript and return the answer.

    Shared by both workflows because a research transcript and a chat transcript are the
    same rows -- keeping one writer is what stops them drifting into rendering
    differently, which they have done before.
    """
    seq = params.start_seq

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

    answer = payload.get("answer") or empty_answer
    await _write_row(
        params, seq, "assistant", answer,
        # The agent separates its narration from its answer; carrying the narration
        # through as `reasoning` is what keeps the disclosure working.
        reasoning=payload.get("reasoning") or "",
        model=payload.get("model") or "",
    )
    return answer


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
    """

    @workflow.run
    async def run(self, params: "ResearchTaskParams") -> str:
        try:
            raw = await workflow.execute_activity(
                run_research_agent,
                params,
                # Shorter than a research run on purpose. A chat turn a user is watching
                # that has produced nothing for a quarter of an hour is wedged, and
                # failing it returns the answer slot to them.
                start_to_close_timeout=timedelta(seconds=900),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                _write_row(
                    params, params.start_seq, "error",
                    "This turn was stopped.",
                )
            )
            raise
        except Exception as e:  # noqa: BLE001 - recorded for the user, then re-raised
            await _write_row(
                params, params.start_seq, "error",
                f"The assistant could not answer: {e}",
            )
            raise

        return await _write_payload(
            params, json.loads(raw), "(the assistant returned an empty answer)"
        )


@workflow.defn
class ResearchTask:
    """Run the full research agent for one question and write the result into the chat.

    Split into two activities on purpose: the agent call is slow and retryable, while
    the write is fast and keyed, so a retried agent call cannot leave a half-written
    transcript behind.

    A failure is written into the transcript as an `error` row rather than left as a
    silently failed workflow — the user is looking at a chat window waiting for an
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

        return await _write_payload(
            params, json.loads(raw), "(the research agent returned an empty answer)"
        )
