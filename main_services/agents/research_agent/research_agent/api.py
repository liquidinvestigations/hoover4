import os
from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from agent_common import tool_packs
from research_agent import steps
from research_agent.agent import build_agent
from research_agent.prompts import active_profile, system_prompt_override
from research_agent.run_messages import to_langchain
from research_agent.steps import ModelStepRequest, ToolCallRequest


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
        # rendered for each model call from the tools that call binds, which is not known
        # until the MCP connections are open. See research_agent/prompts/ for why a prompt is
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


def _agent():
    if not hasattr(app.state, "agent") or app.state.agent is None:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    return app.state.agent


@app.post("/model_step")
async def model_step(request: ModelStepRequest):
    """Make one model call and stream it.

    The request carries the run thread and, for a lead, the earlier turns of the chat. The
    stream sends `reasoning` and `response` frames, one `model_turn` frame with the
    classified calls of the reply, and one `end` frame, as `data: {json}` lines. A failed
    call sends one `error` frame instead. While no frame is ready, the stream sends the SSE
    comment line `: keepalive` every `steps.KEEPALIVE_SECONDS`. A client that closes the
    request stops the model call.
    """
    agent = _agent()
    try:
        to_langchain(list(request.earlier) + list(request.messages))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamingResponse(
        steps.stream_frames(steps.run_model_step(agent, request)),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )


@app.post("/tool_call")
async def tool_call(request: ToolCallRequest) -> Dict[str, Any]:
    """Run one tool call of a stored reply, and return its result as JSON."""
    return await steps.run_tool_call(_agent(), request)


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
            "model_step": "/model_step",
            "tool_call": "/tool_call",
            "feedback_message": "/feedback/message",
            "feedback_session": "/feedback/session",
            "feedback_delete": "/feedback/{score_id}"
        }
    }
