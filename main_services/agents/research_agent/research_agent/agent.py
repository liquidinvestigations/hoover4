"""The step contexts of the agent service.

The service keeps no state of a run between two requests. Each `/model_step` and
`/tool_call` request names its run, and `MCPGatewayAgent.context_for` returns the
`AgentContext` for it. A context holds the tool catalogue snapshot, the tool objects, the
model client arguments and the system prompt renderer. It holds no open connection: the MCP
adapter opens one session for each server to list the tools when the context is built, and
one session for each tool call, and closes each on exit.
"""

import json
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_mcp_adapters.client import MultiServerMCPClient
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from agent_common import tool_packs
from research_agent import compaction, model_params, prompts, subagents
from research_agent.execution import page_share_client
from research_agent.thinking import describe as describe_thinking
from research_agent.tool_args import decode_string_arguments
from research_agent.tool_catalogue import DELEGATION_TOOL, CatalogueSnapshot, build_snapshot


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

#: How many step contexts to keep in one process. The cache is keyed partly by chat
#: session id and run id, which a service serving many conversations would otherwise grow
#: without limit. Evicts least-recently-used. A context costs one `tools/list` call for
#: each configured server when it is built, and the memory of its tool objects. 0 keeps no
#: context, so each step builds a new one.
MAX_CACHED_GRAPHS = int(os.getenv("AGENT_MAX_CACHED_GRAPHS", "24"))


#: Headers the ACL-aware MCP servers read to scope a call to one user. The agent never
#: decides these: they are handed to it per request by the worker, which reads them from
#: the run row that the website backend wrote.
ACL_COLLECTIONS_HEADER = "X-Hoover4-Collections"
ACL_USER_HEADER = "X-Hoover4-User"

#: Chat session id, forwarded so the browser MCP server can give each conversation its
#: own cookie jar (see main_services/agents/browser_use_server/sessions.py). Unlike the two
#: headers above this carries no authority. It is an isolation key, not an ACL.
CHAT_SESSION_HEADER = "X-Hoover4-Chat-Session"

#: The agent run id, sent on every MCP connection of a step request. The browser server
#: keys a browser by it, so each run gets its own browser. It carries no authority either.
AGENT_RUN_HEADER = "X-Hoover4-Agent-Run"

#: The prompt profile of each run kind that has its own. A chat lead keeps the profile of
#: its container, `internal_search` or `full_research`.
RUN_KIND_PROFILES = {
    "subagent": "research_subagent",
    "planner": "planner",
    "organizer": "organizer",
}


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


@dataclass
class AgentContext:
    """What every step of one run needs, built once and shared by concurrent steps.

    `llm_kwargs` are the arguments of `ThinkingChatOpenAI` with no request body, because
    the thinking value of the body belongs to one step (`steps.thinking_body`).
    `system_text_for` renders the system prompt for the callable names of one model call.
    """

    snapshot: CatalogueSnapshot
    tools: List[Any]
    llm_kwargs: Dict[str, Any]
    model_id: str
    system_text_for: Callable[[Tuple[str, ...]], str]


class MCPGatewayAgent:
    """The agent service's cache of step contexts, and the MCP servers they connect to."""

    def __init__(
        self,
        mcp_servers: List[str],
        name: str,
        system_prompt: str,
        llm_model: str = None,
        profile: Optional[str] = None,
    ):
        self.name = name
        self.mcp_servers = mcp_servers
        # An override, not the prompt itself. The prompt is rendered for each model call,
        # because it is a function of what that call binds. A non-empty value here,
        # `SYSTEM_PROMPT` in compose, or a literal handed in by a test, wins outright.
        self.system_prompt_override = (system_prompt or "").strip()
        self.llm_model = llm_model
        # The profile decides the wording of the system prompt. The tool packs of the
        # run kind decide which tools are bound (`agent_common.tool_packs`). Carried as an
        # attribute so a test can set it without setting a process-wide variable.
        self.profile = (profile or prompts.active_profile()).strip().lower()
        # Contexts are cached per ACL *and chat session*, not shared: the MCP connection
        # carries the caller's permissions in its headers, so one context per distinct
        # ACL is the unit that can safely be reused. Reusing a single context across users
        # would let one user's tool connection serve another user's question.
        #
        # An OrderedDict, used as an LRU bounded by MAX_CACHED_GRAPHS. See there.
        self._contexts: "OrderedDict[str, AgentContext]" = OrderedDict()
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

    async def initialize(self) -> AgentContext:
        """Build one context with no ACL, so the service fails at start on an unreachable
        MCP server or a missing model key. The context is not cached."""
        return await self._create_context(None, None)

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
        # Sorted so that ["a","b"] and ["b","a"] share one cached context.
        #
        # `run_id` is part of the key because the MCP headers carry it, and `kind` and
        # `can_delegate` because they decide which tools the context binds.
        #
        # `session_id` is part of the key because the MCP connection headers carry it,
        # and those headers are fixed when the context is built. Two chats by the same
        # user with the same ACL therefore get two contexts, which gives each
        # conversation its own browser cookie jar.
        #
        # `llm_model` is part of the key because the model client arguments hold a fixed
        # model id, so reusing a context across model choices would answer every later
        # step with the first model that was cached.
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

    async def context_for(
        self,
        username: Optional[str],
        allowed_collections: Optional[List[str]],
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        run_id: Optional[str] = None,
        kind: str = "chat",
        can_delegate: bool = True,
        purpose: Optional[str] = None,
    ) -> AgentContext:
        """Return the cached context of one run, or build it."""
        # `purpose` is not in the key: the key holds the run id, and a run has one purpose.
        model = self._resolve_model(llm_model)
        key = self._acl_key(
            username, allowed_collections, session_id, model, run_id, kind, can_delegate
        )
        if key in self._contexts:
            self._contexts.move_to_end(key)
            return self._contexts[key]

        context = await self._create_context(
            username, allowed_collections, session_id, model, run_id, kind, can_delegate,
            purpose,
        )
        self._contexts[key] = context
        while len(self._contexts) > MAX_CACHED_GRAPHS:
            evicted, _ = self._contexts.popitem(last=False)
            log.info("evicting cached context %s (cap %d)", evicted, MAX_CACHED_GRAPHS)
        return context

    async def _create_context(
        self,
        username: Optional[str] = None,
        allowed_collections: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        run_id: Optional[str] = None,
        kind: str = "chat",
        can_delegate: bool = True,
        purpose: Optional[str] = None,
    ) -> AgentContext:
        """Build the step context of one run, scoped to one caller's ACL.

        `kind` selects the tool packs (`agent_common.tool_packs`). `can_delegate` false
        removes `run_subagent` from the packs.
        """
        # The ACL travels as connection headers so the MCP server enforces it on every
        # tool call. The model cannot widen its own permissions, because it never sees or
        # supplies them.
        headers = acl_headers(username, allowed_collections, session_id, run_id)
        servers = {
            f"mcp_server_{i}": {
                "url": url,
                "transport": "streamable_http",
                "headers": headers,
                # Adds the page share and the idempotency key of the current call.
                "httpx_client_factory": page_share_client,
            }
            for i, url in enumerate(self.mcp_servers)
        }

        client = MultiServerMCPClient(servers)
        # Every MCP tool decodes JSON-string arguments before the call.
        tools = [with_decoded_arguments(tool) for tool in await client.get_tools()]

        llm_api_key = _read_secret("LLM_API_KEY")
        llm_base_url = os.getenv("LLM_BASE_URL")
        model_id = self._resolve_model(llm_model)
        llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))

        if not llm_api_key:
            raise ValueError("LLM_API_KEY (or LLM_API_KEY_FILE) environment variable is required")

        llm_kwargs: Dict[str, Any] = {
            "api_key": llm_api_key,
            "model": model_id,
            "stream_usage": True,
        }
        # `temperature` only when the provider accepts it, and `max_tokens` when an output
        # cap is set. When `LLM_REQUEST_TIMEOUT_SECONDS` is set, the client also gets that
        # read timeout and no retries, so one model call stays inside it.
        llm_kwargs.update(model_params.sampling_params(llm_temperature))
        llm_kwargs.update(model_params.client_kwargs())
        if llm_base_url:
            llm_kwargs["base_url"] = llm_base_url

        log.info("LLM thinking configuration: %s", describe_thinking())
        log.info("%s", compaction.describe())

        # The tool packs of this run kind decide what the context binds, runs and lists in
        # its catalogue. `run_subagent` is a pack tool like the others, so the packs
        # decide whether this run delegates. A run that may not delegate loses it here.
        configured = tool_packs.configured_packs(kind)
        allowed = tool_packs.allowed_tools(kind, configured)
        if not can_delegate:
            allowed = allowed - {DELEGATION_TOOL}

        # `run_subagent` is bound for its schema. Its body never runs, because the worker
        # delegates a readable call and `/tool_call` refuses the others.
        if DELEGATION_TOOL in allowed:
            tools = list(tools) + [subagents.make_delegation_tool()]

        # One snapshot for this context. `/model_step` binds from it and `/tool_call` runs
        # from it, with the names that the thread bound, so the model never receives a
        # tool that `/tool_call` refuses.
        snapshot = build_snapshot(tools, allowed, kind)
        log.info(
            "catalogue %s for kind %s: %d core tools, %d deferred",
            snapshot.version[:12],
            kind,
            len(snapshot.core_names),
            len(snapshot.deferred_names),
        )

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
                    collections_hint=bool(allowed_collections),
                    purpose=purpose,
                )
            return system_texts[names]

        return AgentContext(
            snapshot=snapshot,
            tools=tools,
            llm_kwargs=llm_kwargs,
            model_id=model_id,
            system_text_for=system_text_for,
        )


async def build_agent(
    mcp_servers: List[str],
    name: str,
    system_prompt: str,
    llm_model: str = None,
    profile: Optional[str] = None,
) -> MCPGatewayAgent:
    """Create the agent service's context cache, and build one context to fail fast.

    Args:
        mcp_servers: List of MCP server URLs to connect to
        name: Name of the agent
        system_prompt: Overrides the rendered prompt when non-empty; empty means render
            this profile's templates from the tools that each model call binds
        llm_model: Optional LLM model override
        profile: Agent profile, which selects the prompt of a chat lead. Defaults to
            the container's `AGENT_PROFILE`.
    """
    agent = MCPGatewayAgent(mcp_servers, name, system_prompt, llm_model, profile)
    await agent.initialize()
    return agent
