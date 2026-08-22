import asyncio
import logging
import os
from collections import OrderedDict
from typing import List, Any, AsyncIterable, Sequence, TypedDict, Annotated, Dict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk, RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent import llm_events
from research_agent.thinking import describe as describe_thinking, thinking_kwargs, tool_turn_kwargs
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

#: The tool calls a plan-first opening is made of. Prose in front of any of them, before
#: any other tool has run, is the plan being proposed and belongs in the answer.
#:
#: `read_todo` is in the list and it is not decoration: the protocol tells the model to
#: check whether a plan is needed before writing one, so the very first call of a
#: plan-first turn is a read. Watching a real turn is how that was found -- the
#: understanding-and-approaches prose went behind the reasoning disclosure because the
#: exception was written for `write_todo` alone.
PLAN_FIRST_TOOLS = ("read_todo", "write_todo", "edit_todo", "mark_todo")


def tool_name_of(content: Any) -> str:
    """The tool's name out of a LangGraph tool event, whichever shape it arrives in."""
    if not isinstance(content, dict):
        return ""
    name = content.get("name") or content.get("tool")
    if not name:
        output = content.get("output")
        if isinstance(output, dict):
            name = output.get("name")
    return str(name or "")


def keeps_preamble(in_plan_first_opening: bool, content: Any) -> bool:
    """Whether the prose before this tool call belongs in the answer, not the reasoning.

    Everything a model says before calling a tool is normally narration about the call
    -- "let me search the collections first" -- and it is folded into `reasoning`,
    behind the disclosure, so the scratchpad does not reach the transcript.

    **The plan-first block is the one exception, and it is deliberate.** Both profiles
    are told to open a fresh plan by restating the task and weighing two or three
    approaches before writing the chosen one into the todo. That prose is the part the
    user most needs to see -- it is what they would correct -- so hiding it behind a
    disclosure would defeat the instruction that produced it.

    The exception is bounded by the opening itself: it holds while every tool called so
    far has been a todo tool, and ends for good at the first call that is real work.
    """
    return in_plan_first_opening and tool_name_of(content) in PLAN_FIRST_TOOLS


#: How many compiled graphs to keep. Each holds one MCP client with a live connection
#: per configured server (six, for the full research agent), so this cache is not free
#: and cannot be unbounded — it is keyed partly by chat session id, which an agent
#: serving many conversations would otherwise grow without limit. Evicts
#: least-recently-used.
MAX_CACHED_GRAPHS = int(os.getenv("AGENT_MAX_CACHED_GRAPHS", "24"))


class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    #: This run's tool-turn budget, when the caller sets one. In the state rather than
    #: baked into the graph because graphs are cached and reused across requests, while
    #: the budget is per run: the chat workflow raises it by a fixed increment each time
    #: it nags, so a nagged turn has room to act. Absent means MAX_TOOL_TURNS.
    max_tool_turns: int


#: Headers the ACL-aware MCP servers read to scope a call to one user. The agent never
#: decides these: they are handed to it per request by the website backend, which is the
#: only component that can resolve group and public permissions.
ACL_COLLECTIONS_HEADER = "X-Hoover4-Collections"
ACL_USER_HEADER = "X-Hoover4-User"

#: Chat session id, forwarded so the browser MCP server can give each conversation its
#: own cookie jar (see main_services/agents/browser_use_server/sessions.py). Unlike the two
#: headers above this carries no authority — it is an isolation key, not an ACL.
CHAT_SESSION_HEADER = "X-Hoover4-Chat-Session"


def llm_streaming_enabled() -> bool:
    """Whether the LLM is configured to stream tokens. See `_create_graph` for why the
    default is off (vLLM's streamed tool-call deltas do not accumulate)."""
    return os.getenv("LLM_STREAMING", "false").lower() in ("1", "true", "yes")


def acl_headers(
    username: Optional[str],
    allowed_collections: Optional[List[str]],
    session_id: Optional[str] = None,
) -> Dict[str, str]:
    """Build the per-request MCP headers carrying the caller's identity and ACL.

    An empty collection list is sent as an empty header rather than omitted: "this user
    may read nothing" and "no ACL was supplied" must not look the same to the MCP
    server, which denies the second outright.
    """
    headers = {ACL_COLLECTIONS_HEADER: ",".join(allowed_collections or [])}
    if username:
        headers[ACL_USER_HEADER] = username
    if session_id:
        headers[CHAT_SESSION_HEADER] = session_id
    secret = _read_secret("MCP_SHARED_SECRET")
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def _read_secret(env_var: str) -> str:
    """Read a secret from an env var, falling back to the <name>_FILE bind mount that
    deploy.py creates (hoover4.ini stores host paths, never values)."""
    value = os.getenv(env_var, "").strip()
    if value:
        return value
    key_file = os.getenv(env_var + "_FILE", "").strip()
    if key_file and os.path.exists(key_file):
        with open(key_file) as fh:
            return fh.read().strip()
    return ""


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
        # Graphs are cached per ACL *and chat session*, not shared: the MCP connection
        # carries the caller's permissions in its headers, so one graph per distinct ACL
        # is the unit that can safely be reused. Reusing a single graph across users
        # would let one user's tool connection serve another user's question.
        #
        # An OrderedDict, used as an LRU bounded by MAX_CACHED_GRAPHS — see there.
        self._graphs: "OrderedDict[str, Any]" = OrderedDict()
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
    def _acl_key(
        username: Optional[str],
        allowed_collections: Optional[List[str]],
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> str:
        # Sorted so that ["a","b"] and ["b","a"] share one cached graph.
        #
        # `session_id` is part of the key because the MCP connection headers carry it,
        # and those headers are baked into the graph at construction time. Two chats by
        # the same user with the same ACL therefore get two graphs — which is the point:
        # it is what gives each conversation its own browser cookie jar.
        #
        # `llm_model` is part of the key for the same reason the model is: the ChatOpenAI
        # instance is constructed with a fixed model id, so reusing a graph across model
        # choices would silently answer every later turn with the first model that was
        # cached.
        acl = f"{username or ''}|{','.join(sorted(allowed_collections or []))}"
        return f"{acl}|{session_id or ''}|{llm_model or ''}"

    def _resolve_model(self, llm_model: Optional[str] = None) -> str:
        return (
            (llm_model or "").strip()
            or (self.llm_model or "").strip()
            or os.getenv("LLM_MODEL", "gpt-4o-mini")
        )

    async def _graph_for(
        self,
        username: Optional[str],
        allowed_collections: Optional[List[str]],
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
    ):
        model = self._resolve_model(llm_model)
        key = self._acl_key(username, allowed_collections, session_id, model)
        if key in self._graphs:
            self._graphs.move_to_end(key)
            return self._graphs[key]

        self._graphs[key] = await self._create_graph(
            username, allowed_collections, session_id, model
        )
        while len(self._graphs) > MAX_CACHED_GRAPHS:
            evicted, _ = self._graphs.popitem(last=False)
            log.info("evicting cached graph %s (cap %d)", evicted, MAX_CACHED_GRAPHS)
        return self._graphs[key]

    async def _create_graph(
        self,
        username: Optional[str] = None,
        allowed_collections: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
    ):
        """Create the agent graph with MCP tools, scoped to one caller's ACL."""
        # Set up MCP servers. The ACL travels as connection headers so the MCP server
        # enforces it on every tool call — the model cannot widen its own permissions,
        # because it never sees or supplies them.
        headers = acl_headers(username, allowed_collections, session_id)
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
        llm_api_key = _read_secret("LLM_API_KEY")
        llm_base_url = os.getenv("LLM_BASE_URL")
        llm_model_env = self._resolve_model(llm_model)
        llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        
        if not llm_api_key:
            raise ValueError("LLM_API_KEY (or LLM_API_KEY_FILE) environment variable is required")
        
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
            
        # Thinking is configured per node, not globally, because the two nodes want
        # opposite things. See research_agent/thinking.py for the measurements.
        #
        #  * `agent` may call a tool. Choosing a tool is routing, not reasoning, and
        #    Qwen3.5-2B reasons its way into repeated identical calls when allowed to,
        #    so thinking is always off here.
        #  * `finalize` writes prose and cannot call a tool. This is where thinking
        #    buys anything, so it gets AGENT_THINKING.
        log.info("LLM thinking configuration: %s", describe_thinking())
        llm = ThinkingChatOpenAI(
            **llm_kwargs, extra_body=tool_turn_kwargs()
        ).bind_tools(tools)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        agent_runnable = prompt | { "messages": llm }

        # The same model with no tools bound. Used by the `finalize` node below: a model
        # that cannot call a tool has to answer.
        plain_llm = ThinkingChatOpenAI(**llm_kwargs, extra_body=thinking_kwargs())
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
            budget = int(state.get("max_tool_turns") or MAX_TOOL_TURNS)
            if _tool_turns(state) >= budget:
                log.warning("agent hit the %d-turn tool budget; forcing a final answer", budget)
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
        llm_model: str = None,
        extra_tool_turns: int = 0,
    ) -> AsyncIterable[dict[str, Any]]:
        # Build (or reuse) the graph whose MCP connections carry this caller's ACL and
        # chat session, keyed also by the model that will answer.
        model_id = self._resolve_model(llm_model)
        provider = llm_events.provider_from_base_url()
        graph = await self._graph_for(
            username or user_id, allowed_collections, session_id, model_id
        )

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
        
        # The budget travels with the run, not with the cached graph. `extra_tool_turns`
        # is what the chat workflow adds per nag: the base budget stays, so the total a
        # nagged turn may spend is bounded rather than multiplied.
        inputs = {
            "messages": messages,
            "max_tool_turns": MAX_TOOL_TURNS + max(0, int(extra_tool_turns or 0)),
        }

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
        call_timer: Optional[llm_events.CallTimer] = None

        # Token accounting for the whole run, summed over its model calls.
        #
        # Two numbers rather than one, because they answer different questions and differ
        # by an order of magnitude. `context_tokens` is what the provider counted for the
        # FIRST call: the system prompt, the tool schemas, the history and the question —
        # the standing cost of the conversation, and what the next turn starts from.
        # `peak_context_tokens` is the largest single call in the run, which is the last
        # one in a tool-using turn because every result stays in the model-visible list.
        # A compaction trigger fires on the peak; a user's intuition is about the other.
        #
        # Both stay 0 when the provider reports no usage at all. 0 means unknown here and
        # everywhere downstream — never "free".
        context_tokens = 0
        peak_context_tokens = 0
        prompt_tokens_total = 0
        completion_tokens_total = 0
        model_calls = 0

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
                    call_timer = llm_events.CallTimer()
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
                if kind == "on_chat_model_end":
                    message = event["data"].get("output")
                    latency_ms = call_timer.elapsed_ms() if call_timer else 0
                    call_timer = None
                    # Hoisted out of the telemetry block below because the accounting
                    # reads it too, and guarded for the same reason the block is: a
                    # message shape this cannot read is a number lost, never an answer
                    # lost.
                    try:
                        stats = llm_events.stats_from_message(
                            message,
                            model_id=model_id,
                            provider=provider,
                            latency_ms=latency_ms,
                            kind="chat",
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("could not read usage off a model turn: %s", exc)
                        stats = llm_events.LlmCallStats(
                            provider=provider, model_id=model_id, latency_ms=latency_ms
                        )
                    if stats.prompt_tokens:
                        model_calls += 1
                        if not context_tokens:
                            context_tokens = stats.prompt_tokens
                        peak_context_tokens = max(
                            peak_context_tokens,
                            stats.prompt_tokens + stats.completion_tokens,
                        )
                    prompt_tokens_total += stats.prompt_tokens
                    completion_tokens_total += stats.completion_tokens
                    try:
                        # `to_thread`, because this is two synchronous POSTs to ClickHouse
                        # inside the stream loop. On the event loop they stall every other
                        # chat's tokens for as long as ClickHouse takes to answer — and
                        # this fires once per model turn, so a busy stack pays it
                        # constantly. Telemetry must never be in the way of the answer it
                        # is describing.
                        await asyncio.to_thread(
                            llm_events.record_llm_call,
                            stats,
                            username=username or user_id,
                            session_id=session_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("failed to record llm_call_events: %s", exc)
                    if not llm_streaming_enabled():
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
                    # `event["data"]` on a start is only `{"input": {...}}` — the tool's
                    # name lives on the event, not in its data, and until the matching
                    # end event arrives there is nowhere else to get it. A consumer
                    # rendering the call *while it runs* (the website's streaming chat)
                    # would otherwise have to label every in-flight card "tool".
                    start_data = recurse_json_decode(
                        self.tools_type_adapter.dump_python(event["data"])
                    )
                    if isinstance(start_data, dict) and not start_data.get("name"):
                        start_data["name"] = event.get("name") or ""
                    # The run id is what makes a start and its own end pairable. Without
                    # it a consumer has nothing but the tool's name and arrival order:
                    # a model that issues two calls to the SAME tool at once — which
                    # these models do, observed milliseconds apart — then has the second
                    # result matched to the first call, and a card shows a result that
                    # belongs to a different question. A start event carries no
                    # tool_call_id at all, so this is the only identity available.
                    if isinstance(start_data, dict):
                        start_data["run_id"] = str(event.get("run_id") or "")
                    yield {
                        "is_task_complete": False,
                        "type": "start_tool",
                        "content": start_data,
                    }
                elif kind == "on_tool_end":
                    end_data = recurse_json_decode(
                        self.tools_type_adapter.dump_python(event["data"])
                    )
                    if isinstance(end_data, dict):
                        end_data["run_id"] = str(event.get("run_id") or "")
                    yield {
                        "is_task_complete": False,
                        "type": "end_tool",
                        "content": end_data,
                    }
        
        yield {
            "is_task_complete": True,
            "type": "end",
            "content": all_content,
            "model": model_id,
            # The only place these counts exist. Every consumer's alternative is to
            # re-tokenise the transcript with a tokeniser that is not the model's, which
            # is a guess wearing a number's clothes.
            "usage": {
                "context_tokens": context_tokens,
                "peak_context_tokens": peak_context_tokens,
                "prompt_tokens": prompt_tokens_total,
                "completion_tokens": completion_tokens_total,
                "model_calls": model_calls,
            },
        }


    async def run(
        self,
        query: str,
        chat_history: List[Dict[str, str]] = None,
        session_id: str = None,
        user_id: str = None,
        username: str = None,
        allowed_collections: List[str] = None,
        llm_model: str = None,
        extra_tool_turns: int = 0,
    ) -> Dict[str, Any]:
        """Run to completion and return the whole trajectory in one object.

        The streaming endpoint is the right shape for a browser; a server-side caller
        (the Hoover4 website backend) wants the finished answer plus the tool calls it
        made, so it does not have to reassemble SSE fragments in Rust.
        """
        # The answer body is the content produced AFTER the last tool call.
        #
        # A reasoning model narrates its plan as ordinary content alongside the tool
        # calls it is about to make ("I need to search the collections. Let me start by
        # listing them..."), and those chunks arrive on the same `response` channel as
        # the real answer. Concatenating everything shipped the model's scratchpad into
        # the transcript ahead of the answer, and it does not happen in every chat
        # configuration, so it is easy to miss.
        #
        # So every `start_tool` moves what has accumulated so far into the preamble,
        # which is returned as `reasoning` and rendered behind the existing tool
        # disclosure rather than discarded. Content genuinely produced after the last
        # tool is the answer.
        answer_parts: List[str] = []
        # The plan-first opening, held apart from the answer so the next fold into the
        # preamble cannot sweep it up with the narration around it.
        plan_parts: List[str] = []
        preamble_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        resolved_model = self._resolve_model(llm_model)
        # Filled from the `end` event. Empty when the run produced no model call at all,
        # which a caller must read as unknown rather than as zero tokens spent.
        usage: Dict[str, int] = {}
        # True until the first tool call that is not part of the plan-first opening.
        in_plan_first_opening = True

        async for chunk in self.stream(
            query=query,
            chat_history=chat_history,
            session_id=session_id,
            user_id=user_id,
            username=username,
            allowed_collections=allowed_collections,
            llm_model=llm_model,
            extra_tool_turns=extra_tool_turns,
        ):
            kind = chunk.get("type")
            if kind == "response":
                answer_parts.append(chunk.get("content") or "")
            elif kind == "reasoning":
                reasoning_parts.append(str(chunk.get("content") or ""))
            elif kind == "start_tool":
                # Whatever the model said before deciding to call a tool is narration
                # about the call, not the answer -- except for the block that opens a
                # plan-first turn, which is kept. See `keeps_preamble`.
                keep = keeps_preamble(in_plan_first_opening, chunk.get("content"))
                if answer_parts:
                    (plan_parts if keep else preamble_parts).extend(answer_parts)
                    answer_parts = []
                in_plan_first_opening = keep
                tool_calls.append({"phase": "start", "content": chunk.get("content")})
            elif kind == "end_tool":
                tool_calls.append({"phase": "end", "content": chunk.get("content")})
            elif kind == "error":
                raise RuntimeError(chunk.get("content"))
            elif kind == "end":
                if chunk.get("model"):
                    resolved_model = chunk["model"]
                if isinstance(chunk.get("usage"), dict):
                    usage = dict(chunk["usage"])

        answer = "\n\n".join(
            part for part in ("".join(plan_parts).strip(), "".join(answer_parts).strip())
            if part
        )
        preamble = "".join(preamble_parts).strip()
        if not answer:
            # A turn that called tools and then said nothing new. Returning an empty
            # answer would render as a blank assistant bubble, which reads as a failure;
            # the narration is the only thing the model produced, so it becomes the
            # answer rather than being dropped on the floor.
            answer = preamble
            preamble = ""

        # Model narration goes in with the reasoning, behind the disclosure.
        reasoning = "\n\n".join(part for part in ("".join(reasoning_parts).strip(), preamble)
                                if part)

        return {
            "answer": answer,
            "reasoning": reasoning,
            "tool_calls": tool_calls,
            # The model that actually answered, so the transcript row can record it.
            # Reported by the agent rather than assumed by the caller: the website and
            # the Temporal research path reach different agents, and a per-message model
            # is only meaningful if it names what really ran.
            "model": resolved_model,
            # Token counts as the provider billed them, for the transcript row and the
            # session's running peak. Empty when no model call reported any.
            "usage": usage,
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
