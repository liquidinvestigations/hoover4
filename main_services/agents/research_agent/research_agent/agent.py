import asyncio
import logging
import os
from collections import OrderedDict
from contextvars import ContextVar
from typing import List, Any, AsyncIterable, Sequence, TypedDict, Annotated, Dict, Optional, Tuple
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk, RemoveMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent_common import tool_packs
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent import compaction, llm_events, prompts, subagents
from research_agent.execution import (
    DELEGATE, MODEL_TURN, TOOL_RESULT, TOOL_START, make_execution_node, model_turn_event,
    page_share_client, pending_calls,
)
from research_agent.run_messages import history_to_langchain
from research_agent.tool_catalogue import DELEGATION_TOOL, build_snapshot
from research_agent.thinking import describe as describe_thinking, thinking_kwargs, tool_turn_kwargs
from research_agent.tool_args import decode_string_arguments
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
            parsed = json.loads(d)
            if isinstance(parsed, dict) and parsed.get("kind") == "result_page":
                # A broker result page. The byte rule requires this string to reach
                # `trajectory.py` unchanged: decoding it into a dict here and
                # re-serializing it later would produce bytes the broker never wrote,
                # which breaks the fixed-point test that recognises a page on the way
                # in. See `agent_common.result_pages`, "The byte rule".
                return d
            return recurse_json_decode(parsed)
        else:
            return d
    except (JSONDecodeError, TypeError):
        return d


def with_decoded_arguments(tool: Any) -> Any:
    """Return a copy of an MCP tool that decodes JSON-string arguments before the call.

    The adapter builds each MCP tool with its JSON schema as `args_schema`, and langchain
    does not validate a dict schema, so the arguments reach the MCP server as the model
    wrote them. The copy runs `decode_string_arguments` on them first. A tool with no
    coroutine or no dict schema is returned unchanged.
    """
    original = getattr(tool, "coroutine", None)
    schema = getattr(tool, "args_schema", None)
    if original is None or not isinstance(schema, dict):
        return tool

    async def call_with_decoded_arguments(**arguments: Any) -> Any:
        return await original(**decode_string_arguments(arguments, schema))

    return tool.model_copy(update={"coroutine": call_with_decoded_arguments})


log = logging.getLogger(__name__)

#: How many tool-calling turns the agent may take before it is made to answer. Generous
#: enough for a genuinely multi-step research question, low enough that a stuck model
#: costs seconds rather than the whole recursion budget. `AGENT_RECURSION_LIMIT` is the
#: hard backstop behind this.
MAX_TOOL_TURNS = int(os.getenv("AGENT_MAX_TOOL_TURNS", "12"))

#: Compactions applied during the run currently executing, waiting for the token count
#: that says what they bought.
#:
#: A `ContextVar` and not an attribute, because the compiled graph is cached and shared
#: across concurrent requests while a compaction belongs to exactly one of them. Each
#: `stream()` call installs its own list, and the graph nodes it drives inherit that
#: context; another chat running at the same time appends to its own.
_PENDING_COMPACTIONS: ContextVar[Optional[List[compaction.CompactionReport]]] = ContextVar(
    "hoover4_pending_compactions", default=None
)


#: How many compiled graphs to keep. A cached graph holds no open MCP connection: the
#: adapter opens one session for each server to list the tools when the graph is created,
#: and one session for each tool call, and closes each on exit. A graph costs one
#: `tools/list` call for each configured server when it is created, and the memory of its
#: tool objects. The cache is keyed partly by chat session id and run id, which an agent
#: serving many conversations would otherwise grow without limit. Evicts
#: least-recently-used. A `/run/stream` request releases its graph when it ends.
MAX_CACHED_GRAPHS = int(os.getenv("AGENT_MAX_CACHED_GRAPHS", "24"))


class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    #: This run's tool-turn budget. In the state rather than baked into the graph because
    #: graphs are cached and reused across requests, while the budget is per run. Absent
    #: means MAX_TOOL_TURNS. Zero means the next tool call goes to the forced answer.
    max_tool_turns: int
    #: The deferred tool names bound for the next model call. The model node and the
    #: execution node read this one value, and only the bind step of the execution node
    #: changes it. Each request starts with none.
    bound_names: Tuple[str, ...]
    #: How many chat history messages come before the run's thread. An event `index` is
    #: a position in the thread, so it is the message position less this offset.
    thread_offset: int
    #: How many messages the request started with. The tool-turn count reads only the
    #: messages after it, which are the turns this request made.
    request_start: int
    #: Set by the execution node of a `/run/stream` graph when the run stops at
    #: `run_subagent`. The graph then ends with no answer.
    delegated: bool


#: Headers the ACL-aware MCP servers read to scope a call to one user. The agent never
#: decides these: they are handed to it per request by the website backend, which is the
#: only component that can resolve group and public permissions.
ACL_COLLECTIONS_HEADER = "X-Hoover4-Collections"
ACL_USER_HEADER = "X-Hoover4-User"

#: Chat session id, forwarded so the browser MCP server can give each conversation its
#: own cookie jar (see main_services/agents/browser_use_server/sessions.py). Unlike the two
#: headers above this carries no authority. It is an isolation key, not an ACL.
CHAT_SESSION_HEADER = "X-Hoover4-Chat-Session"

#: The agent run id, sent on every MCP connection that a `/run/stream` request opens. The
#: browser server keys a browser by it, so each run gets its own browser. It carries no
#: authority either.
AGENT_RUN_HEADER = "X-Hoover4-Agent-Run"

#: The prompt profile of each run kind that has its own. A chat lead keeps the profile of
#: its container, `internal_search` or `full_research`.
RUN_KIND_PROFILES = {
    "subagent": "research_subagent",
    "planner": "planner",
    "organizer": "organizer",
}


def llm_streaming_enabled() -> bool:
    """Whether the LLM is configured to stream tokens. See `_create_graph` for why the
    default is off (vLLM's streamed tool-call deltas do not accumulate)."""
    return os.getenv("LLM_STREAMING", "false").lower() in ("1", "true", "yes")


def acl_headers(
    username: Optional[str],
    allowed_collections: Optional[List[str]],
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
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
    if run_id:
        headers[AGENT_RUN_HEADER] = run_id
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

    def __init__(
        self,
        mcp_servers: List[str],
        name: str,
        system_prompt: str,
        llm_model: str = None,
        profile: Optional[str] = None,
    ):
        """Initialize the MCP Gateway Agent with MCP servers."""
        self.name = name
        self.mcp_servers = mcp_servers
        # An override, not the prompt itself. The prompt is rendered for each model call
        # in `_create_graph`, because it is a function of what that call binds: the tool
        # section comes from the bound tool names and the budget from `MAX_TOOL_TURNS`,
        # neither of which is known here. A non-empty value here, `SYSTEM_PROMPT` in
        # compose, or a literal handed in by a test, wins outright.
        self.system_prompt_override = (system_prompt or "").strip()
        self.llm_model = llm_model
        # The profile decides the wording of the system prompt. The tool packs of the
        # run kind decide which tools are bound (`agent_common.tool_packs`). Carried as an
        # attribute so a test can set it without setting a process-wide variable.
        self.profile = (profile or prompts.active_profile()).strip().lower()
        self.tools_type_adapter = TypeAdapter(Dict[str, Any])
        self.graph = None
        # Graphs are cached per ACL *and chat session*, not shared: the MCP connection
        # carries the caller's permissions in its headers, so one graph per distinct ACL
        # is the unit that can safely be reused. Reusing a single graph across users
        # would let one user's tool connection serve another user's question.
        #
        # An OrderedDict, used as an LRU bounded by MAX_CACHED_GRAPHS. See there.
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
        run_id: Optional[str] = None,
        kind: str = "chat",
        can_delegate: bool = True,
    ) -> str:
        # Sorted so that ["a","b"] and ["b","a"] share one cached graph.
        #
        # `run_id` is part of the key because the MCP headers carry it, and `kind` and
        # `can_delegate` because they decide which tools the graph binds.
        #
        # `session_id` is part of the key because the MCP connection headers carry it,
        # and those headers are baked into the graph at construction time. Two chats by
        # the same user with the same ACL therefore get two graphs, which is the point:
        # it is what gives each conversation its own browser cookie jar.
        #
        # `llm_model` is part of the key for the same reason the model is: the ChatOpenAI
        # instance is constructed with a fixed model id, so reusing a graph across model
        # choices would silently answer every later turn with the first model that was
        # cached.
        acl = f"{username or ''}|{','.join(sorted(allowed_collections or []))}"
        return (
            f"{acl}|{session_id or ''}|{llm_model or ''}|{run_id or ''}|{kind}"
            f"|{'d' if can_delegate else 'n'}"
        )

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
        run_id: Optional[str] = None,
        kind: str = "chat",
        can_delegate: bool = True,
        purpose: Optional[str] = None,
    ):
        # `purpose` is not in the key: the key holds the run id, and a run has one purpose.
        model = self._resolve_model(llm_model)
        key = self._acl_key(
            username, allowed_collections, session_id, model, run_id, kind, can_delegate
        )
        if key in self._graphs:
            self._graphs.move_to_end(key)
            return self._graphs[key]

        self._graphs[key] = await self._create_graph(
            username, allowed_collections, session_id, model, run_id, kind, can_delegate,
            purpose,
        )
        while len(self._graphs) > MAX_CACHED_GRAPHS:
            evicted, _ = self._graphs.popitem(last=False)
            log.info("evicting cached graph %s (cap %d)", evicted, MAX_CACHED_GRAPHS)
        return self._graphs[key]

    def release_graph(self, run_id: str) -> int:
        """Remove every cached graph of one run, and return how many were removed.

        A graph holds no open connection, so dropping the reference is the whole release.
        A request that still runs on the graph keeps its own reference.
        """
        if not run_id:
            return 0
        keys = [k for k in self._graphs if k.split("|")[4] == run_id]
        for key in keys:
            del self._graphs[key]
        return len(keys)

    async def _create_graph(
        self,
        username: Optional[str] = None,
        allowed_collections: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        run_id: Optional[str] = None,
        kind: str = "chat",
        can_delegate: bool = True,
        purpose: Optional[str] = None,
    ):
        """Create the agent graph with MCP tools, scoped to one caller's ACL.

        `kind` selects the tool packs (`agent_common.tool_packs`). `can_delegate` false
        removes `run_subagent` from the packs. The graph serves `/run/stream`: it stops at
        a `run_subagent` call (`execution.py`), and the worker starts the sub-agent runs.
        """
        stop_at_delegation = True
        # Set up MCP servers. The ACL travels as connection headers so the MCP server
        # enforces it on every tool call. The model cannot widen its own permissions,
        # because it never sees or supplies them.
        headers = acl_headers(username, allowed_collections, session_id, run_id)
        servers = {
            f"mcp_server_{i}": {
                "url": url,
                "transport": "streamable_http",
                "headers": headers,
                # Adds the page share that the execution node gives each call.
                "httpx_client_factory": page_share_client,
            }
            for i, url in enumerate(self.mcp_servers)
        }

        # Create MCP client and get tools
        client = MultiServerMCPClient(servers)
        # Every MCP tool decodes JSON-string arguments before the call. The worker pool
        # below is built from this list, so the in-process workers get the same wrapper.
        tools = [with_decoded_arguments(tool) for tool in await client.get_tools()]

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
        recursion_limit = int(os.getenv("AGENT_RECURSION_LIMIT", "40"))
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
        log.info("%s", compaction.describe())

        # The tool packs of this run kind decide what the graph binds, runs and lists in
        # its catalogue. `run_subagent` is a pack tool like the others, so the packs
        # decide whether this graph delegates. A run that may not delegate loses it here.
        configured = tool_packs.configured_packs(kind)
        allowed = tool_packs.allowed_tools(kind, configured)
        if not can_delegate:
            allowed = allowed - {DELEGATION_TOOL}

        # A `/run/stream` graph binds `run_subagent` for its schema, and the execution
        # node stops at it, so its body never runs (`subagents.make_delegation_tool`).
        if DELEGATION_TOOL in allowed:
            tools = list(tools) + [subagents.make_delegation_tool()]

        # One snapshot for this graph. The model node and the execution node both read
        # it, with the run's `bound_names`, so the model never receives a tool that the
        # execution node refuses.
        snapshot = build_snapshot(tools, allowed, kind)
        log.info(
            "catalogue %s for kind %s: %d core tools, %d deferred",
            snapshot.version[:12],
            kind,
            len(snapshot.core_names),
            len(snapshot.deferred_names),
        )
        tool_llm = ThinkingChatOpenAI(**llm_kwargs, extra_body=tool_turn_kwargs())

        # The prompt is rendered from the tools one model call binds, so a prompt cannot
        # claim a tool the model does not have, and a bound tool cannot go unmentioned.
        # It is rendered once for each distinct tool list. `collections_hint` is the
        # caller's ACL: an empty one means every collection search will come back empty,
        # which the model should be told rather than left to discover.
        # The run kind selects the prompt. A chat lead keeps the container's profile.
        profile = RUN_KIND_PROFILES.get(kind, self.profile)
        system_texts: Dict[Tuple[str, ...], str] = {}

        def system_text_for(names: Tuple[str, ...]) -> str:
            if names not in system_texts:
                system_texts[names] = self.system_prompt_override or prompts.system_prompt(
                    profile,
                    tools=list(names),
                    max_tool_turns=MAX_TOOL_TURNS,
                    collections_hint=bool(allowed_collections),
                    purpose=purpose,
                )
            return system_texts[names]

        def compact_state(state: AgentState) -> Dict[str, Any]:
            """Shorten old tool results on the way to the model, when the trigger fires.

            This sits in front of the prompt rather than inside a node that writes state,
            and that placement is the whole design: what it returns is handed to the
            template and thrown away, so the graph state, the trajectory the website
            renders and the transcript rows all keep every tool result in full. Only the
            model sees less.

            See research_agent/compaction.py for the trigger, which is a configured
            fraction of the model's stated context window and does not fire on this
            stack's ordinary traffic.
            """
            messages = state.get("messages") or []
            compacted, report = compaction.compact_messages(
                messages, model_id=llm_model_env
            )
            if report is not None:
                compaction.record_compaction(
                    report, username=username, session_id=session_id
                )
                pending = _PENDING_COMPACTIONS.get()
                if pending is not None:
                    pending.append(report)
            return {**state, "messages": compacted}

        async def model_call(state: AgentState, config: RunnableConfig, llm: Any) -> Dict[str, Any]:
            """Call the model on the compacted messages, and send a `model_turn` event."""
            names = snapshot.callable_names(state.get("bound_names") or ())
            compacted = compact_state(state)["messages"]
            reply = await llm.ainvoke(
                [SystemMessage(content=system_text_for(names))] + list(compacted), config
            )
            index = len(state["messages"]) - int(state.get("thread_offset") or 0)
            try:
                await adispatch_custom_event(
                    MODEL_TURN, model_turn_event(index, reply), config=config
                )
            except RuntimeError:
                pass
            return {"messages": [reply]}

        async def agent_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
            """The model node. It binds the core tools and the run's bound names for this
            call only, from the same `bound_names` the execution node reads."""
            bound = snapshot.tools_for(state.get("bound_names") or ())
            return await model_call(state, config, tool_llm.bind_tools(bound))

        # The same model with no tools bound. Used by the `finalize` node below: a model
        # that cannot call a tool has to answer.
        #
        # It compacts too. `finalize` is the call that carries the most context in the
        # whole run -- every tool result the turn collected, plus the instruction to stop
        # and answer -- so exempting it would exempt the one call most likely to be over.
        plain_llm = ThinkingChatOpenAI(**llm_kwargs, extra_body=thinking_kwargs())

        async def finalize_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
            return await model_call(state, config, plain_llm)

        builder = StateGraph(AgentState)
        builder.add_node("agent", agent_node)
        # The execution node in place of langgraph's `ToolNode`. See
        # research_agent/execution.py. The node keeps the name `tools`, which the stream
        # loop reads.
        builder.add_node(
            "tools", make_execution_node(snapshot, stop_at_delegation=stop_at_delegation)
        )

        def _tool_turns(state: AgentState) -> int:
            """The tool turns this request made. A continued thread's earlier turns are
            counted by the caller in `tool_turns_used`."""
            start = int(state.get("request_start") or 0)
            return sum(
                1 for m in state["messages"][start:] if getattr(m, "tool_calls", None)
            )

        def _repeated_call(state: AgentState) -> bool:
            """Whether the model just re-issued a call it has already made.

            At temperature 0 a repeat is a stuck loop rather than exploration: the same
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
            # GraphRecursionError, which surfaces as an HTTP 500 with no answer at all.
            # The least useful possible outcome, and one Qwen3.5-2B hits regularly: it
            # finds the right document, then re-issues the identical search until the
            # budget runs out. Small models are bad at deciding they are finished, so
            # that decision is made here rather than left to the prompt.
            if _repeated_call(state):
                log.warning("agent repeated a tool call; forcing a final answer")
                return "finalize_entry"
            budget = state.get("max_tool_turns")
            budget = MAX_TOOL_TURNS if budget is None else int(budget)
            if _tool_turns(state) >= budget:
                log.warning("agent hit the %d-turn tool budget; forcing a final answer", budget)
                return "finalize_entry"
            return "tools"

        def finalize_entry(state: AgentState):
            """Drop the unanswered tool call and tell the model to answer now.

            The trailing AIMessage holds tool_calls that will never be satisfied, and an
            OpenAI-shaped request carrying tool_calls with no matching tool results is
            rejected, so it is removed rather than left in place. `add_messages` merges
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
        builder.add_node("finalize", finalize_node)

        def entry(state: AgentState):
            """Start at the execution node when the thread ends with unanswered calls.

            That is a retry of an attempt that ended during a tool call. The stored model
            message keeps its calls, and the missing ones run before the next model call.
            """
            calls, _ = pending_calls(state["messages"])
            return "tools" if calls else "agent"

        def after_tools(state: AgentState):
            return END if state.get("delegated") else "agent"

        builder.set_conditional_entry_point(entry, ["tools", "agent"])
        builder.add_conditional_edges("agent", should_continue)
        builder.add_conditional_edges("tools", after_tools, ["agent", END])
        builder.add_edge("finalize_entry", "finalize")
        builder.add_edge("finalize", END)

        return builder.compile()

    async def stream(
        self,
        chat_history: List[Dict[str, str]] = None,
        session_id: str = None,
        user_id: str = None,
        username: str = None,
        allowed_collections: List[str] = None,
        llm_model: str = None,
        extra_tool_turns: int = 0,
        run_id: Optional[str] = None,
        kind: str = "chat",
        can_delegate: bool = True,
        thread: Optional[Sequence[BaseMessage]] = None,
        tool_turns_used: int = 0,
        purpose: Optional[str] = None,
    ) -> AsyncIterable[dict[str, Any]]:
        """Run the graph and yield its events.

        `/run/stream` passes `run_id` and `thread`, the rebuilt run messages. The stream
        yields the `model_turn`, `tool_start`, `tool_result` and `delegate` events, and
        releases the run's graph at the end. A run that stops at `run_subagent` sends
        `delegate` and then `end`.
        """
        # Build (or reuse) the graph whose MCP connections carry this caller's ACL and
        # chat session, keyed also by the model that will answer.
        model_id = self._resolve_model(llm_model)
        provider = llm_events.provider_from_base_url()
        graph = await self._graph_for(
            username or user_id, allowed_collections, session_id, model_id,
            run_id, kind, can_delegate, purpose,
        )
        try:
            async for event in self._stream_graph(
                graph, chat_history, session_id, user_id, username, model_id,
                provider, extra_tool_turns, thread, tool_turns_used,
            ):
                yield event
        finally:
            if run_id:
                self.release_graph(run_id)

    async def _stream_graph(
        self,
        graph: Any,
        chat_history: Optional[List[Dict[str, str]]],
        session_id: Optional[str],
        user_id: Optional[str],
        username: Optional[str],
        model_id: str,
        provider: str,
        extra_tool_turns: int,
        thread: Optional[Sequence[BaseMessage]],
        tool_turns_used: int,
    ) -> AsyncIterable[dict[str, Any]]:
        messages: List[BaseMessage] = list(history_to_langchain(chat_history or []))
        thread_offset = len(messages)
        messages.extend(thread or [])

        # The budget travels with the run, not with the cached graph. `extra_tool_turns`
        # is what the chat workflow adds per nag: the base budget stays, so the total a
        # nagged turn may spend is bounded rather than multiplied. `tool_turns_used` is
        # what a continued run already spent in the current round.
        inputs = {
            "messages": messages,
            "max_tool_turns": max(
                0,
                MAX_TOOL_TURNS
                + max(0, int(extra_tool_turns or 0))
                - max(0, int(tool_turns_used or 0)),
            ),
            "bound_names": (),
            "thread_offset": thread_offset,
            "request_start": len(messages),
            "delegated": False,
        }

        # Prepare config with Langfuse callback if available
        # langgraph counts every node visit, so one search costs two steps (agent +
        # tools) and the default 25 is only ~12 tool calls. A thorough research run
        # legitimately needs more than that, and hitting the limit is a hard 500 with no
        # partial answer, which is the least useful possible failure. The prompt is what stops
        # the model looping (see research_agent/prompts/); this is only the backstop.
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

        # This run's compaction trail. Installed here so the graph nodes, which are shared
        # with every other request, append to a list belonging to this request only.
        pending_compactions: List[compaction.CompactionReport] = []
        _PENDING_COMPACTIONS.set(pending_compactions)
        # Whether layer two ran at all in this turn. A separate flag because
        # `pending_compactions` is drained as each compaction's token count arrives, and
        # by the end of the run it says nothing about what happened.
        summarised_this_run = False

        # Token accounting for the whole run, summed over its model calls.
        #
        # Two numbers rather than one, because they answer different questions and differ
        # by an order of magnitude. `context_tokens` is what the provider counted for the
        # FIRST call: the system prompt, the tool schemas, the history and the question.
        # The standing cost of the conversation, and what the next turn starts from.
        # `peak_context_tokens` is the largest single call in the run, which is the last
        # one in a tool-using turn because every result stays in the model-visible list.
        # A compaction trigger fires on the peak; a user's intuition is about the other.
        #
        # Both stay 0 when the provider reports no usage at all. 0 means unknown here and
        # everywhere downstream, never "free".
        context_tokens = 0
        peak_context_tokens = 0
        prompt_tokens_total = 0
        completion_tokens_total = 0
        model_calls = 0

        all_content = ""

        async for event in graph.astream_events(inputs, version="v2", config=config):
            kind = event["event"]
            node = event["metadata"].get("langgraph_node")

            # The run events of research_agent/execution.py and the model node.
            if kind == "on_custom_event":
                if event.get("name") in (MODEL_TURN, TOOL_START, TOOL_RESULT, DELEGATE):
                    yield {
                        "is_task_complete": False,
                        "type": event["name"],
                        "content": event.get("data"),
                    }
                continue

            # `finalize` is an answer-producing node exactly like `agent`. It is the
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

                # With streaming off (the default, see `_create_graph`) there are no
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
                    # A compaction's "after" is the prompt of the first call made on the
                    # shortened list, so it only exists here, one call later. Re-inserting
                    # the row under the same compaction id supersedes the placeholder 0 --
                    # the table is a ReplacingMergeTree keyed on that id.
                    if pending_compactions and stats.prompt_tokens:
                        while pending_compactions:
                            report = pending_compactions.pop(0)
                            report.tokens_after = stats.prompt_tokens
                            summarised_this_run = (
                                summarised_this_run or report.layer == "summarisation"
                            )
                            try:
                                await asyncio.to_thread(
                                    compaction.record_compaction,
                                    report,
                                    username=username or user_id,
                                    session_id=session_id,
                                )
                            except Exception as exc:  # noqa: BLE001
                                log.warning("failed to close a compaction record: %s", exc)
                    try:
                        # `to_thread`, because this is two synchronous POSTs to ClickHouse
                        # inside the stream loop. On the event loop they stall every other
                        # chat's tokens for as long as ClickHouse takes to answer, and
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

        # A summarised turn says so; an evicted one does not.
        #
        # The difference is what the user can still check. Eviction takes tool results
        # away from the model and leaves every one of them in the transcript, so a reader
        # who wants the evidence has it. Summarisation replaces the model's own working
        # prose with a machine summary, and the answer above was written from that
        # summary rather than from what the agent actually read. That is a fact about how
        # much to trust the answer, so it is told plainly, once, attached to the turn it
        # is about -- not left in an administrator's table.
        if summarised_this_run or any(
            r.layer == "summarisation" for r in pending_compactions
        ):
            notice = (
                "\n\n---\n\n*This turn grew past the model's context window, so its "
                "earlier steps were summarised before the answer was written. Every "
                "step is unchanged above, and every citation still points at the "
                "document it was made from.*"
            )
            yield {
                "is_task_complete": False,
                "type": "response",
                "content": notice,
            }
            all_content += notice

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


async def build_agent(
    mcp_servers: List[str],
    name: str,
    system_prompt: str,
    llm_model: str = None,
    profile: Optional[str] = None,
) -> MCPGatewayAgent:
    """
    Builder function that creates a langgraph agent with MCP tools.

    Args:
        mcp_servers: List of MCP server URLs to connect to
        name: Name of the agent
        system_prompt: Overrides the rendered prompt when non-empty; empty means render
            this profile's templates from the tools the graph actually binds
        llm_model: Optional LLM model override
        profile: Agent profile, which decides whether delegation is bound. Defaults to
            the container's `AGENT_PROFILE`.

    Returns:
        MCPGatewayAgent: Configured agent instance
    """
    # Create the agent and initialize it
    agent = MCPGatewayAgent(mcp_servers, name, system_prompt, llm_model, profile)
    await agent.initialize()
    return agent
