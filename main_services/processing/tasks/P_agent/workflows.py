"""Temporal workflow for long-running AI research tasks."""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tasks.P_agent.activities import (
        ResearchTaskParams,
        WriteResultParams,
        run_research_agent,
        write_chat_message,
    )

#: How much of a tool-call payload is kept in the transcript. Matches the website's
#: TOOL_SUMMARY_CHARS so a research transcript and a chat transcript look the same.
TOOL_SUMMARY_CHARS = 400


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
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise

        payload = json.loads(raw)

        for call in payload.get("tool_calls", []):
            if call.get("phase") != "end":
                continue
            content = json.dumps(call.get("content", ""))[:TOOL_SUMMARY_CHARS]
            await workflow.execute_activity(
                write_chat_message,
                WriteResultParams(
                    username=params.username,
                    session_id=params.session_id,
                    seq=seq,
                    role="tool",
                    content=content,
                    tool_name=str(call.get("content", {}).get("name", "tool"))
                    if isinstance(call.get("content"), dict)
                    else "tool",
                ),
                start_to_close_timeout=timedelta(minutes=2),
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
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return answer
