"""Temporal workflow for long-running AI research tasks."""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import HEARTBEAT_TIMEOUT
    from tasks.P_agent.activities import (
        ResearchTaskParams,
        WriteResultParams,
        run_research_agent,
        write_chat_message,
    )
    from tasks.P_agent.trajectory import pair_tool_calls


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
            await workflow.execute_activity(
                write_chat_message,
                WriteResultParams(
                    username=params.username,
                    session_id=params.session_id,
                    seq=seq,
                    role="error",
                    content=f"The research task failed: {e}",
                ),
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise

        payload = json.loads(raw)

        # Pair start/end events into one row each, with the arguments, the result and
        # any documents surfaced -- the same columns the synchronous chat path writes,
        # so a research transcript renders identically to a chat one.
        for call in pair_tool_calls(payload.get("tool_calls", [])):
            await workflow.execute_activity(
                write_chat_message,
                WriteResultParams(
                    username=params.username,
                    session_id=params.session_id,
                    seq=seq,
                    role="tool",
                    content=call.summary,
                    tool_name=call.tool_name,
                    tool_input=call.tool_input,
                    tool_output=call.tool_output,
                    doc_refs=call.doc_refs,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            seq += 1

        answer = payload.get("answer") or "(the research agent returned an empty answer)"
        await workflow.execute_activity(
            write_chat_message,
            WriteResultParams(
                username=params.username,
                session_id=params.session_id,
                seq=seq,
                role="assistant",
                content=answer,
                # The agent separates its narration from its answer; carrying the
                # narration through as `reasoning` is what keeps a research transcript
                # rendering identically to a synchronous chat one, disclosure included.
                reasoning=payload.get("reasoning") or "",
                model=payload.get("model") or "",
            ),
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return answer
