import logging
import os
from typing import List, Any, AsyncIterable, Sequence, TypedDict, Annotated, Dict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk, RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from research_agent.chat_model import ThinkingChatOpenAI
from pydantic import TypeAdapter
import json
from json import JSONDecodeError
from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

def recurse_json_decode(d):
    try:
        if isinstance(d, dict):
            return {k: recurse_json_decode(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [recurse_json_decode(item) for item in d]
        elif isinstance(d, str):
            return recurse_json_decode(json.loads(d))
        else:
            return d
    except (JSONDecodeError, TypeError):
        return d

log = logging.getLogger(__name__)

#: How many tool-calling turns the agent may take before it is made to answer. Generous
#: enough for a genuinely multi-step research question, low enough that a stuck model
#: costs seconds rather than the whole recursion budget. `AGENT_RECURSION_LIMIT` is the
#: hard backstop behind this.
MAX_TOOL_TURNS = int(os.getenv("AGENT_MAX_TOOL_TURNS", "12"))


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


#: Headers the ACL-aware MCP servers read to scope a call to one user. The agent never
#: decides these: they are handed to it per request by the website backend, which is the
#: only component that can resolve group and public permissions.
ACL_COLLECTIONS_HEADER = "X-Hoover4-Collections"
ACL_USER_HEADER = "X-Hoover4-User"


def llm_streaming_enabled() -> bool:
    """Whether the LLM is configured to stream tokens. See `_create_graph` for why the
    default is off (vLLM's streamed tool-call deltas do not accumulate)."""
    return os.getenv("LLM_STREAMING", "false").lower() in ("1", "true", "yes")


def acl_headers(username: Optional[str], allowed_collections: Optional[List[str]]) -> Dict[str, str]:
    """Build the per-request MCP headers carrying the caller's identity and ACL.

    An empty collection list is sent as an empty header rather than omitted: "this user
    may read nothing" and "no ACL was supplied" must not look the same to the MCP
    server, which denies the second outright.
    """
    headers = {ACL_COLLECTIONS_HEADER: ",".join(allowed_collections or [])}
    if username:
        headers[ACL_USER_HEADER] = username
    secret = os.getenv("MCP_SHARED_SECRET", "").strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


class MCPGatewayAgent:
    """An agent that gateways to other agents via MCP."""

    def __init__(self, mcp_servers: List[str], name: str, system_prompt: str, llm_model: str = None):
        """Initialize the MCP Gateway Agent with MCP servers."""
        self.name = name
        self.mcp_servers = mcp_servers
        self.system_prompt = system_prompt
        self.llm_model = llm_model
        self.tools_type_adapter = TypeAdapter(Dict[str, Any])
        self.graph = None
        # Graphs are cached per ACL, not shared: the MCP connection carries the caller's
        # permissions in its headers, so one graph per distinct ACL is the unit that can
        # safely be reused. Reusing a single graph across users would let one user's
        # tool connection serve another user's question.
        self._graphs: Dict[str, Any] = {}
        self.langfuse_handler = self._create_langfuse_handler()

    def _create_langfuse_handler(self) -> Optional[CallbackHandler]:
        """Create Langfuse callback handler if credentials are available."""
        langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        
        if langfuse_public_key and langfuse_secret_key:
            try:
                # Initialize Langfuse client with environment variables
                Langfuse(
                    public_key=langfuse_public_key,
                    secret_key=langfuse_secret_key,
                    host=langfuse_host
                )
                return CallbackHandler()
            except Exception as e:
                print(f"Warning: Failed to initialize Langfuse: {e}")
                return None
        return None

    async def initialize(self, username: str = None, allowed_collections: List[str] = None):
        """Build (or reuse) the graph for one caller's ACL.

        Kept async and idempotent so the API can call it at startup with no ACL just to
        fail fast on an unreachable MCP server, and again per request with the real one.
        """
        self.graph = await self._graph_for(username, allowed_collections)
        return self.graph

    @staticmethod
    def _acl_key(username: Optional[str], allowed_collections: Optional[List[str]]) -> str:
        # Sorted so that ["a","b"] and ["b","a"] share one cached graph.
        return f"{username or ''}|{','.join(sorted(allowed_collections or []))}"

    async def _graph_for(self, username: Optional[str], allowed_collections: Optional[List[str]]):
        key = self._acl_key(username, allowed_collections)
        if key not in self._graphs:
            self._graphs[key] = await self._create_graph(username, allowed_collections)
        return self._graphs[key]

    async def _create_graph(
        self,
        username: Optional[str] = None,
        allowed_collections: Optional[List[str]] = None,
    ):
        """Create the agent graph with MCP tools, scoped to one caller's ACL."""
        # Set up MCP servers. The ACL travels as connection headers so the MCP server
        # enforces it on every tool call — the model cannot widen its own permissions,
        # because it never sees or supplies them.
        headers = acl_headers(username, allowed_collections)
        servers = {
            f"mcp_server_{i}": {
                "url": url,
                "transport": "streamable_http",
                "headers": headers,
            }
            for i, url in enumerate(self.mcp_servers)
        }

        # Create MCP client and get tools
        client = MultiServerMCPClient(servers)
        tools = await client.get_tools()

        # Get LLM configuration from environment variables
        llm_api_key = os.getenv("LLM_API_KEY")
        llm_base_url = os.getenv("LLM_BASE_URL")
        llm_model_env = self.llm_model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        
        if not llm_api_key:
            raise ValueError("LLM_API_KEY environment variable is required")
        
        # Token streaming is OFF by default, and that is a correctness decision, not a
        # performance one.
        #
        # vLLM's streaming tool-call deltas send the function name with `arguments`
        # absent, which langchain turns into a `tool_call_chunk` with `args=None`. Those
        # chunks never accumulate into the final AIMessage, so `message.tool_calls` comes
        # back empty, `should_continue` routes straight to END, and the agent answers
        # nothing at all having silently skipped every tool. Non-streaming responses are
        # parsed server-side by vLLM's tool-call parser and arrive intact.
        #
        # Cost: the SSE endpoint emits one response event per turn instead of per token.
        # Set LLM_STREAMING=true to trade tool calling back for token streaming if a
        # future model/vLLM pair fixes the delta shape.
        #
        # `disable_streaming` is the switch that actually matters, not `streaming`: the
        # latter only affects `invoke`, while langgraph drives the model through
        # `astream_events`, which calls `astream` and streams regardless. With
        # `disable_streaming=True`, `astream` degenerates to a single `invoke` and the
        # node emits a whole `AIMessage` with its `tool_calls` intact.
        streaming = llm_streaming_enabled()
        llm_kwargs = {
            "api_key": llm_api_key,
            "model": llm_model_env,
            "temperature": llm_temperature,
            "streaming": streaming,
            "disable_streaming": not streaming,
            "stream_usage": True,
        }
        if llm_base_url:
            llm_kwargs["base_url"] = llm_base_url
            
        llm = ThinkingChatOpenAI(**llm_kwargs).bind_tools(tools)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        agent_runnable = prompt | { "messages": llm }

        # The same model with no tools bound. Used by the `finalize` node below: a model
        # that cannot call a tool has to answer.
        plain_llm = ThinkingChatOpenAI(**llm_kwargs)
        finalize_runnable = prompt | { "messages": plain_llm }

        builder = StateGraph(AgentState)
        builder.add_node("agent", agent_runnable)
        tool_node = ToolNode(tools)
        builder.add_node("tools", tool_node)

        def _tool_turns(state: AgentState) -> int:
            return sum(1 for m in state["messages"] if getattr(m, "tool_calls", None))

        def _repeated_call(state: AgentState) -> bool:
            """Whether the model just re-issued a call it has already made.

            At temperature 0 a repeat is not exploration, it is a stuck loop: the same
            call returns the same result and the next turn is identical again.
            """
            calls = [
                (c.get("name"), json.dumps(c.get("args"), sort_keys=True, default=str))
                for m in state["messages"]
                for c in (getattr(m, "tool_calls", None) or [])
            ]
            return len(calls) > 1 and calls[-1] in calls[:-1]

        def should_continue(state: AgentState):
            last_message = state["messages"][-1]
            if not getattr(last_message, "tool_calls", None):
                return END
            # Two guards, both ending at `finalize` so the caller always gets prose.
            #
            # Without them a model that will not stop calling tools produces a langgraph
            # GraphRecursionError, which surfaces as an HTTP 500 with no answer at all —
            # the least useful possible outcome, and one Qwen3.5-2B hits regularly: it
            # finds the right document, then re-issues the identical search until the
            # budget runs out. Small models are bad at deciding they are finished, so
            # that decision is made here rather than left to the prompt.
            if _repeated_call(state):
                log.warning("agent repeated a tool call; forcing a final answer")
                return "finalize_entry"
            if _tool_turns(state) >= MAX_TOOL_TURNS:
                log.warning("agent hit the %d-turn tool budget; forcing a final answer", MAX_TOOL_TURNS)
                return "finalize_entry"
            return "tools"

        def finalize_entry(state: AgentState):
            """Drop the unanswered tool call and tell the model to answer now.

            The trailing AIMessage holds tool_calls that will never be satisfied, and an
            OpenAI-shaped request carrying tool_calls with no matching tool results is
            rejected — so it is removed rather than left in place. `add_messages` merges
            by id and cannot delete, hence `RemoveMessage`.
            """
            last = state["messages"][-1]
            return {
                "messages": [
                    RemoveMessage(id=last.id),
                    HumanMessage(
                        content=(
                            "Stop searching now and write the final answer using only "
                            "what the tool results above already contain. Cite the file "
                            "path of every document you rely on. If they contain nothing "
                            "relevant, say so plainly."
                        )
                    ),
                ]
            }

        builder.add_node("finalize_entry", finalize_entry)
        builder.add_node("finalize", finalize_runnable)

        builder.set_entry_point("agent")
        builder.add_conditional_edges("agent", should_continue)
        builder.add_edge("tools", "agent")
        builder.add_edge("finalize_entry", "finalize")
        builder.add_edge("finalize", END)

        return builder.compile()

    async def stream(
        self,
        query: str,
        chat_history: List[Dict[str, str]] = None,
        session_id: str = None,
        user_id: str = None,
        username: str = None,
        allowed_collections: List[str] = None,
    ) -> AsyncIterable[dict[str, Any]]:
        # Build (or reuse) the graph whose MCP connections carry this caller's ACL.
        graph = await self._graph_for(username or user_id, allowed_collections)

        # Build messages from chat history and current query
        messages = []
        if chat_history:
            for msg in chat_history:
                if msg["type"] == "human":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["type"] == "ai":
                    messages.append(AIMessage(content=msg["content"]))
        
        # Add current query
        messages.append(HumanMessage(content=query))
        
        inputs = {"messages": messages}

        # Prepare config with Langfuse callback if available
        # langgraph counts every node visit, so one search costs two steps (agent +
        # tools) and the default 25 is only ~12 tool calls. A thorough research run
        # legitimately needs more than that, and hitting the limit is a hard 500 with no
        # partial answer — the least useful possible failure. The prompt is what stops
        # the model looping (see research_agent/prompts.py); this is only the backstop.
        config = {"recursion_limit": int(os.getenv("AGENT_RECURSION_LIMIT", "40"))}
        if self.langfuse_handler and user_id and session_id:
            config["callbacks"] = [self.langfuse_handler]
            config["metadata"] = {
                "langfuse_user_id": user_id,
                "langfuse_session_id": session_id,
                "langfuse_tags": [self.name]
            }

        llm_started = False
        is_reasoning = False
        is_response = False

        all_content = ""

        async for event in graph.astream_events(inputs, version="v2", config=config):
            kind = event["event"]
            node = event["metadata"].get("langgraph_node")

            # `finalize` is an answer-producing node exactly like `agent` — it is the
            # same model with no tools bound (see `_create_graph`). Leaving it out here
            # is why the forced final answer first came back as an empty string with a
            # cheerful HTTP 200.
            if node in ("agent", "finalize"):
                if kind == "on_chain_start" and not llm_started:
                    yield {
                        "is_task_complete": False,
                        "type": "start",
                        "content": "",
                    }
                    llm_started = True
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if isinstance(chunk, AIMessageChunk):
                        # Handle reasoning content
                        reasoning_content = chunk.additional_kwargs.get("reasoning_content", {})
                        if reasoning_content:
                            if not is_reasoning:
                                is_reasoning = True
                                is_response = False
                                yield {
                                    "is_task_complete": False,
                                    "type": "start_reasoning",
                                    "content": "",
                                }
                            yield {
                                "is_task_complete": False,
                                "type": "reasoning",
                                "content": reasoning_content,
                            }
                        
                        # Handle regular content
                        if chunk.content:
                            chunk_content = chunk.content
                            if isinstance(chunk_content, list):
                                chunk_content = "".join([x["text"] for x in chunk_content if x.get("type") == "text"])
                            if not is_response:
                                is_reasoning = False
                                is_response = True
                                yield {
                                    "is_task_complete": False,
                                    "type": "start_response",
                                    "content": "",
                                }
                            yield {
                                "is_task_complete": False,
                                "type": "response",
                                "content": chunk_content,
                            }
                            all_content += chunk_content

                # With streaming off (the default — see `_create_graph`) there are no
                # per-token events, only this one at the end of each turn. Emitting the
                # whole message here is what makes the non-streaming path produce an
                # answer instead of silence.
                if kind == "on_chat_model_end" and not llm_streaming_enabled():
                    message = event["data"].get("output")
                    content = getattr(message, "content", "") or ""
                    if isinstance(content, list):
                        content = "".join(
                            x["text"] for x in content if isinstance(x, dict) and x.get("type") == "text"
                        )
                    if content:
                        yield {
                            "is_task_complete": False,
                            "type": "start_response",
                            "content": "",
                        }
                        yield {
                            "is_task_complete": False,
                            "type": "response",
                            "content": content,
                        }
                        all_content += content

            if node == "tools":
                llm_started = False
                if kind == "on_tool_start":
                    yield {
                        "is_task_complete": False,
                        "type": "start_tool",
                        "content": recurse_json_decode(self.tools_type_adapter.dump_python(event["data"])),
                    }
                elif kind == "on_tool_end":
                    yield {
                        "is_task_complete": False,
                        "type": "end_tool",
                        "content": recurse_json_decode(self.tools_type_adapter.dump_python(event["data"])),
                    }
        
        yield {
            "is_task_complete": True,
            "type": "end",
            "content": all_content,
        }


    async def run(
        self,
        query: str,
        chat_history: List[Dict[str, str]] = None,
        session_id: str = None,
        user_id: str = None,
        username: str = None,
        allowed_collections: List[str] = None,
    ) -> Dict[str, Any]:
        """Run to completion and return the whole trajectory in one object.

        The streaming endpoint is the right shape for a browser; a server-side caller
        (the Hoover4 website backend) wants the finished answer plus the tool calls it
        made, so it does not have to reassemble SSE fragments in Rust.
        """
        answer_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []

        async for chunk in self.stream(
            query=query,
            chat_history=chat_history,
            session_id=session_id,
            user_id=user_id,
            username=username,
            allowed_collections=allowed_collections,
        ):
            kind = chunk.get("type")
            if kind == "response":
                answer_parts.append(chunk.get("content") or "")
            elif kind == "reasoning":
                reasoning_parts.append(str(chunk.get("content") or ""))
            elif kind == "start_tool":
                tool_calls.append({"phase": "start", "content": chunk.get("content")})
            elif kind == "end_tool":
                tool_calls.append({"phase": "end", "content": chunk.get("content")})
            elif kind == "error":
                raise RuntimeError(chunk.get("content"))

        return {
            "answer": "".join(answer_parts),
            "reasoning": "".join(reasoning_parts),
            "tool_calls": tool_calls,
        }


async def build_agent(mcp_servers: List[str], name: str, system_prompt: str, llm_model: str = None) -> MCPGatewayAgent:
    """
    Builder function that creates a langgraph agent with MCP tools.
    
    Args:
        mcp_servers: List of MCP server URLs to connect to
        name: Name of the agent
        system_prompt: System prompt for the agent
        llm_model: Optional LLM model override
        
    Returns:
        MCPGatewayAgent: Configured agent instance
    """
    # Create the agent and initialize it
    agent = MCPGatewayAgent(mcp_servers, name, system_prompt, llm_model)
    await agent.initialize()
    return agent
