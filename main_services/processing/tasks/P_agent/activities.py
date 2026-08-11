"""Activities for long-running AI research tasks.

A chat message is answered synchronously by the website (seconds to a couple of
minutes). A *research* task is the other mode: the full research agent searching
exhaustively across collections and the open web, which can run far longer than an HTTP
request should. Those runs live here, in Temporal, so they survive a browser reload, a
website restart, and a worker crash.

The ACL travels with the task. This activity never resolves permissions itself — the
website resolved them when the task was submitted and passed the resulting collection
list in, exactly as it does for a synchronous chat.
"""

import json
import logging
import os
from dataclasses import dataclass, field

import requests
from temporalio import activity
from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

#: Where the full research agent lives on the shared `hoover4` network.
AGENT_URL = os.getenv("RESEARCH_AGENT_URL", "http://hoover4-full-research-agent:8000")

#: One HTTP call to the agent. Generous, because an exhaustive research run is the point
#: of this path, but still bounded so a wedged agent fails the activity and lets
#: Temporal's retry policy take over instead of hanging a worker thread forever.
AGENT_TIMEOUT_SECONDS = int(os.getenv("RESEARCH_AGENT_TIMEOUT_SECONDS", "1800"))


@dataclass
class ResearchTaskParams:
    """Input for one research run.

    `username` and `session_id` identify where the answer is written back to, and
    `allowed_collections` is the ACL the agent is bounded by.
    """

    username: str
    session_id: str
    query: str
    allowed_collections: list[str] = field(default_factory=list)
    #: `seq` of the first row this task may write. The website reserves it when it
    #: submits, so a concurrent synchronous message cannot land on the same position.
    start_seq: int = 0


@activity.defn
@with_heartbeat
def run_research_agent(params: ResearchTaskParams) -> str:
    """Call the full research agent and return its answer.

    Raises on any failure so Temporal retries. Writing the answer into the chat is a
    separate activity: a retried research run must not append a second transcript.

    The agent is consumed through its streaming endpoint, and the events are mirrored
    into `chat_message_stream` as they arrive: a research run shows the same
    pending tool cards and growing answer as an inline chat turn instead of a static
    "Research task started" placeholder for the whole run. The returned payload is the
    same shape `/chat` produced, so the workflow's finalisation is unchanged.
    """
    activity.heartbeat("calling research agent")
    from tasks.P_agent.stream_writer import ResearchStreamWriter

    writer = ResearchStreamWriter(params)
    try:
        payload = writer.run()
    finally:
        writer.close()
    log.info(
        "[P_agent] research run finished for %s: %d chars, %d tool events",
        params.username,
        len(payload.get("answer", "")),
        len(payload.get("tool_calls", [])),
    )
    return json.dumps(payload)


@dataclass
class WriteResultParams:
    """One `chat_messages` row.

    The payload fields mirror the columns the website's synchronous chat path writes
    (`website/backend/src/db_chat`). They were missing here for a while, which is why
    research transcripts rendered as a raw JSON blob with the tool type shown as
    "tool" and an expand panel that opened onto nothing: the columns the UI reads were
    never populated on this path.
    """

    username: str
    session_id: str
    seq: int
    role: str
    content: str
    tool_name: str = ""
    #: JSON arguments the model passed to the tool.
    tool_input: str = ""
    #: JSON tool result, truncated to TOOL_PAYLOAD_CHARS.
    tool_output: str = ""
    #: JSON array of documents this step surfaced, for the result cards.
    doc_refs: str = ""
    #: Wall time the agent took to produce this row, 0 for anything else.
    agent_duration_ms: int = 0
    #: Model that produced the row, empty for user and tool rows. Recorded per message
    #: because model selection is per message -- a transcript that mixes two models is
    #: only readable if each row says which one wrote it.
    model: str = ""
    #: Reasoning kept out of the answer body and rendered behind the disclosure. A
    #: reasoning model narrates its plan on the same channel as its answer, and this is
    #: the column that stops the scratchpad reaching the transcript.
    reasoning: str = ""


@activity.defn
@with_heartbeat
def write_chat_message(params: WriteResultParams) -> int:
    """Append one row to the global `chat_messages` table.

    The chat tables are global (a conversation spans collections), so this writes to
    `Hoover4_Processing`. Idempotent on retry: `chat_messages` is a ReplacingMergeTree
    keyed on `(username, session_id, seq)`, so re-writing the same row replaces it
    rather than duplicating it.
    """
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        client.insert(
            "chat_messages",
            [[
                params.session_id,
                params.username,
                params.seq,
                params.role,
                params.content,
                params.tool_name,
                params.tool_input,
                params.tool_output,
                params.doc_refs,
                params.agent_duration_ms,
                params.model,
                params.reasoning,
            ]],
            column_names=[
                "session_id",
                "username",
                "seq",
                "role",
                "content",
                "tool_name",
                "tool_input",
                "tool_output",
                "doc_refs",
                "agent_duration_ms",
                "model",
                "reasoning",
            ],
        )
    log.info(
        "[P_agent] wrote %s message seq=%d to session %s",
        params.role, params.seq, params.session_id,
    )
    return params.seq
