import os
import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from typing import List, Optional, Dict, Any, Union
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from enum import Enum
from research_agent.agent import build_agent
from research_agent.prompts import active_profile, system_prompt_override


class MessageType(str, Enum):
    human = "human"
    ai = "ai"

class ChatMessage(BaseModel):
    type: MessageType = Field(description="The type of the message, either human or ai")
    content: str = Field(description="The content of the message")

class ChatRequest(BaseModel):
    session_id: str = Field(description="The session id, which is a unique identifier for the session, must be 32 lowercase hex char")
    user_id: str = Field(description="The user id, which is a unique identifier for the user, must be 32 lowercase hex char")
    message_id: str = Field(description="The message id, which is a unique identifier for the message, must be 32 lowercase hex char")
    query: str = Field(description="The query to the agent")
    chat_history: List[ChatMessage] = Field(description="The chat history, which is a list of messages of type dict with type and content")
    username: Optional[str] = Field(
        default=None,
        description="Hoover4 username on whose behalf the agent acts. Forwarded to the MCP servers for audit.",
    )
    allowed_collections: List[str] = Field(
        default_factory=list,
        description=(
            "Collections this user may read, resolved by the caller (the Hoover4 "
            "website backend). The agent forwards it to the MCP servers, which refuse "
            "anything outside it. An empty list means the agent can search nothing."
        ),
    )
    llm_model: Optional[str] = Field(
        default=None,
        description=(
            "Optional per-message model id. When set, the agent builds (or reuses) a "
            "graph keyed by this model. The website enforces the allowlist before "
            "sending; an empty/None value uses the agent's configured default."
        ),
    )
    extra_tool_turns: int = Field(
        default=0,
        description=(
            "Tool turns granted on top of the agent's own budget for this run only. "
            "The chat workflow raises it by a fixed increment each time it nags, so a "
            "nagged turn has room to act without the budget being reset."
        ),
    )


class ChatResult(BaseModel):
    """Whole-trajectory result of a non-streaming run."""

    answer: str = Field(description="The assistant's final answer")
    reasoning: str = Field(default="", description="Reasoning trace, when the model emits one")
    tool_calls: List[Dict[str, Any]] = Field(
        default_factory=list, description="Tool calls made, in order, start and end events"
    )
    model: str = Field(
        default="",
        description="Model that actually answered, for the transcript row to record",
    )

class ChatResponse(BaseModel):
    type: MessageType = Field(description="The type of the message, either human or ai")
    content: Union[str, Dict[str, Any]] = Field(description="The content of the message")
    is_task_complete: bool = Field(description="Whether the task is complete")

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

@contextmanager
def _trace_span(agent, message_id: str, query: str):
    """Yield a Langfuse span, or `None` when tracing is not configured.

    Langfuse is optional infrastructure. Making the chat endpoint depend on it (as it
    did) turns "no observability credentials" into "no chat", which is the wrong
    trade-off for a self-hosted deployment.
    """
    handler = getattr(agent, "langfuse_handler", None)
    if handler is None or getattr(handler, "client", None) is None:
        yield None
        return
    try:
        with handler.client.start_as_current_span(
            name=agent.name, trace_context={"trace_id": message_id}
        ) as span:
            span.update_trace(input=query)
            yield span
    except Exception as exc:  # noqa: BLE001 - tracing must never break the request
        print(f"Warning: Langfuse tracing disabled for this request: {exc}")
        yield None


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
        # The profile by name, separately from its prompt: it also decides whether this
        # container binds the delegation tool. A `SYSTEM_PROMPT` override changes the
        # words and deliberately not that.
        "profile": active_profile(),
        "llm_model": os.getenv("LLM_MODEL")
    }
    app.state.agent = None

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


@app.post("/chat/stream", response_model=ChatResponse)
async def chat_stream(request: ChatRequest):
    """Stream chat responses from the agent."""
    try:
        # Get agent from app state
        if not hasattr(app.state, 'agent') or app.state.agent is None:
            raise HTTPException(
                status_code=500,
                detail="Agent not initialized"
            )

        agent = app.state.agent

        async def generate():
            """Generator function for streaming responses."""
            try:
                # Convert Pydantic objects to Python dicts using model_dump()
                chat_history_dicts = [msg.model_dump() for msg in request.chat_history]
                # Tracing is optional: this deployment runs without Langfuse, and an
                # unconfigured handler makes every chat request fail with
                # AttributeError on `None.client`.
                with _trace_span(agent, request.message_id, request.query) as span:
                    last_chunk = None
                    async for chunk in agent.stream(
                        query=request.query,
                        chat_history=chat_history_dicts,
                        session_id=request.session_id,
                        user_id=request.user_id,
                        username=request.username,
                        allowed_collections=request.allowed_collections,
                        llm_model=request.llm_model,
                        extra_tool_turns=request.extra_tool_turns,
                    ):
                        last_chunk = chunk
                        # Format as Server-Sent Events with proper JSON
                        yield f"data: {json.dumps(chunk)}\n\n"
                    if span is not None and last_chunk is not None:
                        span.update_trace(output=last_chunk["content"])
            except Exception as e:
                error_chunk = {
                    "is_task_complete": True,
                    "type": "error",
                    "content": f"Error during streaming: {str(e)}"
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/plain; charset=utf-8"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResult)
async def chat(request: ChatRequest):
    """Run the agent to completion and return the full trajectory as one JSON object.

    This is what the Hoover4 website backend calls. It exists alongside `/chat/stream`
    because a server-side consumer wants a finished result, not an SSE stream it would
    have to reassemble.
    """
    if not hasattr(app.state, "agent") or app.state.agent is None:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    try:
        result = await app.state.agent.run(
            query=request.query,
            chat_history=[msg.model_dump() for msg in request.chat_history],
            session_id=request.session_id,
            user_id=request.user_id,
            username=request.username,
            allowed_collections=request.allowed_collections,
            llm_model=request.llm_model,
            extra_tool_turns=request.extra_tool_turns,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return ChatResult(**result)


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
            "chat_stream": "/chat/stream",
            "feedback_message": "/feedback/message",
            "feedback_session": "/feedback/session",
            "feedback_delete": "/feedback/{score_id}"
        }
    }
