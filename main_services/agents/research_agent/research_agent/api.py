import os
import asyncio
import json
from contextlib import asynccontextmanager
from typing import List, Literal, Optional, Dict, Any, Union
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from enum import Enum
from agent_common import tool_packs
from research_agent.agent import build_agent
from research_agent.prompts import active_profile, system_prompt_override
from research_agent.run_messages import RunMessage, to_langchain


class MessageType(str, Enum):
    human = "human"
    ai = "ai"

class ChatMessage(BaseModel):
    type: MessageType = Field(description="The type of the message, either human or ai")
    content: str = Field(description="The content of the message")

class RunRequest(BaseModel):
    """One agent run's request. The caller stores the thread and sends all of it."""

    run_id: str = Field(description="The agent run id. It keys the graph and the browser.")
    kind: Literal["chat", "subagent", "planner", "organizer"] = Field(
        description="The kind of run, which selects its tool packs"
    )
    depth: int = Field(description="0 for a lead, 1 or 2 for a sub-agent")
    username: str
    session_id: str
    allowed_collections: List[str] = Field(default_factory=list)
    llm_model: Optional[str] = None
    history: List[ChatMessage] = Field(
        default_factory=list, description="Chat history, for depth 0 only"
    )
    messages: List[RunMessage] = Field(
        description="The run's thread. messages[0] is the opening human message"
    )
    tool_turns_used: int = Field(
        default=0, description="Tool turns of the current round before this request"
    )
    extra_tool_turns: int = Field(
        default=0, description="The nag allowance of the current round, else 0"
    )
    can_delegate: bool = Field(default=True, description="False at the deepest level")
    purpose: Optional[Literal["execute", "review", "correct"]] = Field(
        default=None,
        description="The purpose of a plan sub-agent's briefing. `review` adds the verdict block",
    )

    @model_validator(mode="after")
    def _opening(self):
        if not self.messages or self.messages[0].role != "human":
            raise ValueError("messages[0] must be the opening human message")
        if self.depth > 0 and self.history:
            raise ValueError("a sub-agent gets no chat history")
        return self


class MessageFeedBackRequest(BaseModel):
    score_id: str = Field(description="The score id, which is a unique identifier for the score, must be 32 lowercase hex char")
    message_id: str = Field(description="The message id, which is a unique identifier for the message, must be 32 lowercase hex char")
    user_id: str = Field(description="The user id, which is a unique identifier for the user, must be 32 lowercase hex char")
    feedback: str = Field(description="The feedback")
    rating: int = Field(description="The rating")

class FeedBackResponse(BaseModel):
    message: str = Field(description="The message of the feedback")

class SessionFeedBackRequest(BaseModel):
    score_id: str = Field(description="The score id, which is a unique identifier for the score, must be 32 lowercase hex char")
    session_id: str = Field(description="The session id, which is a unique identifier for the session, must be 32 lowercase hex char")
    user_id: str = Field(description="The user id, which is a unique identifier for the user, must be 32 lowercase hex char")
    feedback: str = Field(description="The feedback")
    rating: int = Field(description="The rating")

class HealthResponse(BaseModel):
    status: str = Field(description="The status of the health check")
    message: str = Field(description="The message of the health check")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    print("🚀 Starting Research Agent API...")

    # Initialize agent configuration in app state from environment variables
    app.state.config = {
        "mcp_servers": os.getenv("MCP_SERVERS", "").split(",") if os.getenv("MCP_SERVERS") else [],
        "agent_name": os.getenv("AGENT_NAME", "Research Agent"),
        # `SYSTEM_PROMPT` only, and empty when it is not set. The prompt itself is
        # rendered per graph from the tools that graph binds, which is not known until
        # the MCP connections are open. See research_agent/prompts/ for why a prompt is
        # a function of the deployment rather than a constant.
        "system_prompt": system_prompt_override(),
        # The profile by name, separately from its prompt. It selects the prompt
        # template. The tool packs decide which tools are bound.
        "profile": active_profile(),
        "llm_model": os.getenv("LLM_MODEL")
    }
    app.state.agent = None

    # An unknown pack name stops the service here, before it answers a request.
    packs = tool_packs.check_environment()
    print("🧰 Tool packs: " + "; ".join(f"{k}={','.join(sorted(v))}" for k, v in packs.items()))

    # Validate configuration
    if not app.state.config.get("mcp_servers") or not any(app.state.config.get("mcp_servers")):
        raise RuntimeError("No MCP servers configured. Set MCP_SERVERS environment variable.")

    print(f"📡 Agent Name: {app.state.config.get('agent_name', 'Research Agent')}")
    print(f"🔗 MCP Servers: {', '.join(app.state.config.get('mcp_servers', []))}")
    override = app.state.config.get("system_prompt") or ""
    print(
        f"💭 Profile: {app.state.config.get('profile')}"
        + (f" (SYSTEM_PROMPT override: {override[:50]}...)" if override else "")
    )

    # Initialize the agent
    try:
        app.state.agent = await build_agent(
            mcp_servers=app.state.config["mcp_servers"],
            name=app.state.config["agent_name"],
            system_prompt=app.state.config["system_prompt"],
            llm_model=app.state.config.get("llm_model"),
            profile=app.state.config.get("profile"),
        )
        print(" Agent initialized successfully")
    except Exception as e:
        print(f" Failed to initialize agent: {e}")
        raise

    yield

    # Shutdown
    print("🛑 Shutting down Research Agent API...")
    app.state.agent = None
    app.state.config = None
    print(" Cleanup completed")


# Create FastAPI app with lifespan
app = FastAPI(
    title="Research Agent API",
    description="A research agent with MCP tool integration",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        # Check if agent is available in app state
        if not hasattr(app.state, 'agent') or app.state.agent is None:
            return HealthResponse(
                status="unhealthy",
                message="Agent not initialized"
            )

        return HealthResponse(
            status="healthy",
            message="Agent is ready and operational"
        )
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            message=f"Health check failed: {str(e)}"
        )


#: How long the run stream may send nothing before it sends a keepalive line. It must stay
#: well under the worker's read timeout of the stream (300 s).
KEEPALIVE_SECONDS = 30.0
#: An SSE comment: a line that starts with ":", which a reader of `data: ` frames skips.
KEEPALIVE_LINE = ": keepalive\n\n"


@app.post("/run/stream")
async def run_stream(request: RunRequest):
    """Stream one agent run.

    The request carries the whole thread, so a retry or a continuation starts from the
    stored messages. The stream sends `model_turn`, `tool_start` and `tool_result` events,
    and one `end` event, as `data: {json}` frames. The run's graph is released when the
    stream ends.

    While no event is ready, the stream sends the SSE comment line `: keepalive` every
    `KEEPALIVE_SECONDS`. One model call can wait far longer than the worker's read timeout
    of the stream, and each line restarts that timeout. A reader that takes only `data: `
    lines skips the comment lines.
    """
    if not hasattr(app.state, "agent") or app.state.agent is None:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    agent = app.state.agent
    try:
        thread = to_langchain(request.messages)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def produce(events: asyncio.Queue):
        try:
            async for chunk in agent.stream(
                chat_history=[msg.model_dump() for msg in request.history],
                session_id=request.session_id,
                user_id=request.username,
                username=request.username,
                allowed_collections=request.allowed_collections,
                llm_model=request.llm_model,
                extra_tool_turns=request.extra_tool_turns,
                run_id=request.run_id,
                kind=request.kind,
                can_delegate=request.can_delegate,
                thread=thread,
                tool_turns_used=request.tool_turns_used,
                purpose=request.purpose,
            ):
                await events.put(("data", chunk))
        except Exception as e:  # noqa: BLE001 - the caller reads the error frame
            await events.put(("error", e))
        finally:
            await events.put(("done", None))

    async def generate():
        events: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(produce(events))
        try:
            while True:
                try:
                    # A cancelled get() removes no item, so a timeout loses no event.
                    kind, item = await asyncio.wait_for(events.get(), KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield KEEPALIVE_LINE
                    continue
                if kind == "data":
                    yield f"data: {json.dumps(item, default=str)}\n\n"
                elif kind == "error":
                    error_chunk = {
                        "is_task_complete": True,
                        "type": "error",
                        "content": f"Error during streaming: {str(item)}",
                    }
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    break
                else:
                    break
        finally:
            # A client that disconnects stops the run.
            task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )


def _require_langfuse(agent):
    """Return the Langfuse client, or 503 if tracing/feedback is not configured."""
    handler = getattr(agent, "langfuse_handler", None)
    client = getattr(handler, "client", None) if handler else None
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Feedback requires Langfuse, which is not configured on this deployment",
        )
    return client


@app.post("/feedback/message", response_model=FeedBackResponse)
async def feedback_message(request: MessageFeedBackRequest):
    """Feedback endpoint."""
    try:
        # Get agent from app state
        if not hasattr(app.state, 'agent') or app.state.agent is None:
            raise HTTPException(
                status_code=500,
                detail="Agent not initialized"
            )

        agent = app.state.agent
        client = _require_langfuse(agent)

        # Update the trace with feedback
        client.create_score(
            score_id=request.score_id,
            trace_id=request.message_id,
            user_id=request.user_id,
            name="user-message-feedback",
            value=request.rating,
            data_type="NUMERIC",
            comment=request.feedback
        )
        return FeedBackResponse(message="Feedback received")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/feedback/session", response_model=FeedBackResponse)
async def feedback_session(request: SessionFeedBackRequest):
    """Feedback endpoint."""
    try:
        # Get agent from app state
        if not hasattr(app.state, 'agent') or app.state.agent is None:
            raise HTTPException(
                status_code=500,
                detail="Agent not initialized"
            )

        agent = app.state.agent
        client = _require_langfuse(agent)

        # Update the trace with feedback
        client.create_score(
            score_id=request.score_id,
            session_id=request.session_id,
            user_id=request.user_id,
            name="user-session-feedback",
            value=request.rating,
            data_type="NUMERIC",
            comment=request.feedback
        )
        return FeedBackResponse(message="Feedback received")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/feedback/{score_id}", response_model=FeedBackResponse)
async def delete_feedback(score_id: str):
    """Delete feedback endpoint."""
    try:
        # Get agent from app state
        if not hasattr(app.state, 'agent') or app.state.agent is None:
            raise HTTPException(
                status_code=500,
                detail="Agent not initialized"
            )

        agent = app.state.agent
        client = _require_langfuse(agent)

        # Delete the score
        client.api.score.delete(score_id)
        return FeedBackResponse(message="Feedback deleted")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint with API information."""
    config_info = {}
    if hasattr(app.state, 'config') and app.state.config:
        config_info = {
            "agent_name": app.state.config.get("agent_name"),
            "mcp_servers_count": len(app.state.config.get("mcp_servers", [])),
            "llm_model": app.state.config.get("llm_model")
        }

    return {
        "message": "Research Agent API",
        "version": "1.0.0",
        "status": "running",
        "configuration": config_info,
        "endpoints": {
            "health": "/health",
            "run_stream": "/run/stream",
            "feedback_message": "/feedback/message",
            "feedback_session": "/feedback/session",
            "feedback_delete": "/feedback/{score_id}"
        }
    }
