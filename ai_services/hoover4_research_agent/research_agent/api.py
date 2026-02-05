import os
import asyncio
import json
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any, Union
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from enum import Enum
from research_agent.agent import build_agent


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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    print("🚀 Starting Research Agent API...")

    # Initialize agent configuration in app state from environment variables
    app.state.config = {
        "mcp_servers": os.getenv("MCP_SERVERS", "").split(",") if os.getenv("MCP_SERVERS") else [],
        "agent_name": os.getenv("AGENT_NAME", "Research Agent"),
        "system_prompt": os.getenv("SYSTEM_PROMPT", "You are a helpful research assistant."),
        "llm_model": os.getenv("LLM_MODEL")
    }
    app.state.agent = None

    # Validate configuration
    if not app.state.config.get("mcp_servers") or not any(app.state.config.get("mcp_servers")):
        raise RuntimeError("No MCP servers configured. Set MCP_SERVERS environment variable.")

    print(f"📡 Agent Name: {app.state.config.get('agent_name', 'Research Agent')}")
    print(f"🔗 MCP Servers: {', '.join(app.state.config.get('mcp_servers', []))}")
    print(f"💭 System Prompt: {app.state.config.get('system_prompt', '')[:50]}...")

    # Initialize the agent
    try:
        app.state.agent = await build_agent(
            mcp_servers=app.state.config["mcp_servers"],
            name=app.state.config["agent_name"],
            system_prompt=app.state.config["system_prompt"],
            llm_model=app.state.config.get("llm_model")
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
                with agent.langfuse_handler.client.start_as_current_span(
                    name=agent.name,
                    trace_context={"trace_id": request.message_id}
                ) as span:
                    span.update_trace(
                        input=request.query,
                    )
                    async for chunk in agent.stream(
                        query=request.query,
                        chat_history=chat_history_dicts,
                        session_id=request.session_id,
                        user_id=request.user_id,
                    ):
                        # Format as Server-Sent Events with proper JSON
                        yield f"data: {json.dumps(chunk)}\n\n"
                    span.update_trace(
                        output=chunk["content"],
                    )
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

        # Update the trace with feedback
        agent.langfuse_handler.client.create_score(
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

        # Update the trace with feedback
        agent.langfuse_handler.client.create_score(
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

        # Delete the score
        agent.langfuse_handler.client.api.score.delete(score_id)
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
