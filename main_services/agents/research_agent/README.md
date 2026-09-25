# Research Agent API

A FastAPI-based research agent with MCP (Model Context Protocol) tool integration, providing streaming chat capabilities for research assistance.

## The agent profiles

One image, two containers, different tool sets, and the difference is deliberate. A third
profile, `research_subagent`, has no container of its own: it is the profile of a sub-agent
run. See "Delegation" below. The `planner` and `organizer` profiles are the prompts of the
two run kinds of a deep research plan.

| | `hoover4-internal-search-agent` (21936) | `hoover4-full-research-agent` (21937) |
|---|---|---|
| `AGENT_PROFILE` | `internal_search` | `full_research` |
| MCP servers | collections **only** | collections + metasearch + browser + ddg + whois + wikipedia |
| Used by | the runs of a thread with internet tools off | the runs of a thread with internet tools on |

`hoover4-full-research-agent` runs four uvicorn worker processes (`UVICORN_WORKERS`).
Each process holds its own graph cache and MCP connections. Citation `[Dn]` handles
are allocated in the collections MCP server, so the worker processes do not split them.

The profile selects the prompt template. The tool packs of the run kind select the tools.
See "Tool packs and deferred binding" below.

**The internal-search agent has no web tools on purpose.** A chat about the user's own
documents must not quietly become a web search. The user cannot tell from the answer
which sentence came from their archive and which came from a search engine.

## The ACL header chain

An agent answering for a user must only reach collections that user could read in the
search UI:

1. The **website backend** resolves the user's permitted collections (group grants union
   public collections). It is the only component that can. It owns the auth tables.
2. It passes that list with the turn to the Temporal worker, and the worker's `run_agent`
   sends it to the agent as `allowed_collections` on the `/run/stream` request.
3. `acl_headers()` turns it into `X-Hoover4-Collections: <list>` plus
   `Authorization: Bearer $MCP_SHARED_SECRET`, set as **MCP connection headers**.
4. The agent caches **one graph per ACL and chat session** (`_acl_key`), so a connection
   opened for one user is never reused for another. The chat session is part of the key
   because `X-Hoover4-Chat-Session` travels in the same connection headers. See the
   browser sessions note below. The cache is LRU-bounded by `AGENT_MAX_CACHED_GRAPHS`
   (default 24); each entry holds one live MCP connection per configured server, so it
   cannot be allowed to grow per conversation without limit.
5. `hoover4-mcp-collections` enforces the header on every tool call.

The model never sees or supplies its own permissions. They are not tool arguments, so it
cannot widen them. An empty list is sent as an empty header rather than omitted: "this user
may read nothing" and "no ACL was supplied" must not look the same to the MCP server, which
denies the second outright.

## System prompts live in `research_agent/prompts/`

Not in compose, and not as string literals. Each profile is a `.md.j2` template beside the
loader in `research_agent/prompts/__init__.py`, which is the only thing that renders one.
`SYSTEM_PROMPT` overrides the whole rendered text; empty means "render the templates".

**The prompt is a function of the deployment.** It is rendered in `_create_graph`, at the
first point where the tool list is real, and it takes named parameters: the bound tool
names, the tool-turn budget the graph will enforce, whether delegation is bound, whether
the caller can read any collection at all, and whether the open web is reachable. The tool
section is generated from the bound names, so a prompt can neither describe a tool the
model does not have nor leave out one it does. `tests/test_prompts.py` fails when a
template names an unbound tool or states a budget the code does not use. Renaming a tool
used to mean correcting the same sentence by hand in several prose files, and the one that
was missed told the model to call a name that no longer existed.

Blocks in `prompts/_blocks/` are shared, and each guards itself: the plan-first block
renders only where the todo writers are bound, so a worker profile cannot be handed an
instruction to call a tool it does not have.

**Keep them short.** Qwen3.5-2B follows a long, numbered, multi-clause prompt by doing all
of it forever: an earlier five-step draft made the model search, search again, then re-run
a query it had already run until the request died with no answer. Detail belongs in tool
descriptions, which the model reads in context at the moment it picks a tool. The Manticore
MATCH syntax deliberately lives in the collection MCP server's `instructions` instead, where
every agent reads it at tool-discovery time and there is only one copy to maintain.

## Delegation

A lead binds `run_subagent` when the `delegation` pack is in its run kind's packs, which
is the default for both agents. The tool splits a question into one to five briefings.
`/run/stream` stops the run at `run_subagent` (`execution.py`). The execution node runs
every other call of that model turn, then sends `tool_start` and `delegate` for each
`run_subagent` call and ends the graph with no answer. The worker writes one sub-agent run
for each accepted briefing, and each runs as an `AgentRun` of its own, with the
`research_subagent` profile. When the last one ends, a continuation of the delegating run
sends the thread back with one `tool` result for each call, and the model continues. A
sub-agent at depth 1 can delegate again, and a run at depth 2 cannot. The worker applies the
budgets. See `processing/tasks/Readme.md` for the runs, the fan-in and the budgets.

**Depth is enforced by what is bound.** A `/run/stream` request with `can_delegate` false
does not bind `run_subagent`, so a call to it gets the execution node's `tool_unavailable`
result. A prompt asking a model not to recurse eventually meets a model that does.

**A plan briefing names its section.** An organizer's briefing carries `plan_node_id`, a
section of the approved tree, and `purpose`: `execute`, `review` or `correct`. The request
sends a sub-agent's `purpose`, and `review` adds the verdict block to its prompt. The worker
refuses a section briefing from any other run kind, and a third correction of one section.

**Sub-agents share the conversation's session header, and that is the citation contract.**
Citation handles are allocated per chat session by the collection-search server, keyed by
the session header. Every run of a turn sends the conversation's session id, so a sub-agent's
`[D1]` resolves in the lead's answer.

## Tool packs and deferred binding

A tool pack is a named set of tools (`agent_common/tool_packs.py`): `catalogue`,
`collections`, `conversation`, `plan`, `delegation`, `web` and `browser`. Each kind of run
(`chat`, `subagent`, `planner`, `organizer`) gets the packs that `AGENT_PACKS_CHAT`,
`AGENT_PACKS_SUBAGENT`, `AGENT_PACKS_PLANNER` and `AGENT_PACKS_ORGANIZER` name, as a comma
list or `all`. `deploy.py` renders them from `hoover4.ini`. The service refuses to start on an
unknown pack name. A tool that an MCP server lists and no pack names is refused for every
run.

Each graph builds one `CatalogueSnapshot` (`tool_catalogue.py`) from the tools of its packs.
The snapshot splits them into core tools, which every model call binds, and deferred tools.
The core tools are `list_collections`, `search_collections`, `search_passages`,
`read_documents`, `list_document_entities`, `cite_documents`, `read_more`,
`search_agent_tools`, `run_subagent`, and every tool of a server other than the collection
server and the plan tools. The plan tools are core for the `planner` and `organizer` kinds.

The model finds a deferred tool with `search_agent_tools`. It ranks an exact name, then the
request as words of a tool's summary, then a name prefix, then the count of shared words. It
returns at most `AGENT_CATALOGUE_MATCH_COUNT` matches (6 to 12, default 6), and
`No available tool matches this request.` when nothing matches.

The model node and the execution node (`execution.py`) read the run's `bound_names` from one
state value. The model node binds the core tools and `bound_names` for that call only. The
execution node refuses any other name with a `tool_unavailable` error, decodes and validates
the arguments, and runs the calls. Plan mutations run one after the other in call order, and
the other calls run in parallel. After the batch, the bind step puts the newest matches of
`search_agent_tools` first, then the earlier names, and keeps `AGENT_CATALOGUE_MATCH_COUNT`.
Each request starts with no bound names.

### The batch result budget and the call measure

The result pages of all calls of one model turn share one budget. The execution node
reserves the empty page of each call first, divides the rest equally, and sends each call its
share in the `X-Hoover4-Page-Share` header. The connections' HTTP client factory
(`page_share_client`) adds the header, because the MCP adapter opens one session for each
call. The collection server's page broker sizes each page within that share, a later page
of a stored window included.

- **Safe mode** is the default. One turn's results share 24,000 UTF-8 bytes, or less when
  the request bytes plus the completion reserve leave less of the context window.
- **Token mode** needs `AGENT_MAX_PAGE_TOKENS` and `AGENT_COMPLETION_RESERVE_TOKENS`, and a
  known context window. The node counts the request and the empty pages with the served
  tokenizer and applies `result_pages.allocate`. It sends the token share as a byte share,
  because a token covers at least one byte. A failed count keeps safe mode. When the empty
  pages and the reserve do not fit, no call runs, and each call gets its empty
  `budget_exhausted` page.

A page that the broker stored as a window is read on later pages with the share it was
stored with, when not one unit fits the current share.

The broker returns the `build_page` measure of the page beside the page text, as an embedded
resource. The adapter puts that block in the tool message artifact. The node takes it out,
adds `page_share`, `budget_mode` and `batch_total`, and gives it as the `measure` of the
`tool_result` event and as `response_metadata["call_measure"]` of the tool message. A tool
that is not a broker tool has no measure. `scripts/test-agent-batch-budget.sh` runs three
parallel `search_collections` calls through the node and checks the total and each digest.

## The run request: `POST /run/stream`

A `/run/stream` request carries one agent run: `run_id`, `kind`, `depth`, the caller's
identity and collections, the chat `history` (depth 0 only), and the run's thread as
`messages`. `messages[0]` is the opening human message. `run_messages.py` rebuilds the
stored messages into langchain messages, with the tool calls and the stored usage, so
compaction can measure the thread before the first new model call. The run has
`max(0, AGENT_MAX_TOOL_TURNS + extra_tool_turns - tool_turns_used)` tool turns left.

The stream sends `data: {json}` frames with these events:

| type | content |
|---|---|
| `model_turn` | `index`, `text`, `reasoning`, `tool_calls` with `id`, `name` and `args`, `usage` |
| `tool_start` | `index`, `tool_call_id`, `name`, `args` |
| `tool_result` | `index`, `tool_call_id`, `name`, `content`, `measure` (the call measure, or `null`), `status` (`ok` or `error`) |
| `delegate` | `index`, `tool_call_id`, `briefings` (each `objective`, `known`, `bring_back`) |

`index` is the message position in the run's thread. A call that raised sends a
`tool_result` with `status` `error`, and `content` is the error text the model receives. The
graph cache key holds the run id, and the run's graph is released when its stream ends.

A `run_subagent` call stops the run: one `delegate` event for each such call of the model
turn, in call order, after the results of the other calls, then `end` with an empty answer.
A model turn with two `run_subagent` calls is one delegation. A call whose briefings cannot
be read gets an `invalid_arguments` result and does not stop the run.

When the thread ends with an `ai` message whose calls do not all have a `tool` message, the
graph starts at the execution node and runs the missing calls before the next model call.
That is a retry of an attempt that ended during a call.

## Per-chat and per-run browser sessions

`X-Hoover4-Chat-Session` carries the chat session id alongside the ACL headers. It grants
no authority. It is an **isolation key**. `hoover4-mcp-browser` uses it to give each
conversation its own Chromium browser context, so cookies and storage from one chat do not
follow the next one. A `/run/stream` request also sends `X-Hoover4-Agent-Run` with the run
id, and the browser server then keys the browser by the run. The chat session stays the
key for citations, artifacts and the todo list. Sessions are dropped when the chat ends, or after
`BROWSER_SESSION_IDLE_SECONDS` (1 h) idle. See
[`../browser_use_server/README.md`](../browser_use_server/README.md).

## Thinking budget: `AGENT_THINKING`

Qwen3.5's chat template decides thinking in the **prompt**, not the sampler. With
`enable_thinking` unset or false it emits `<think>\n\n</think>` *before* generation, so
the default is not a small thinking budget. It is **no thinking at all**.

Measured on this host, Qwen3.5-2B, simple question ("what is 17x23, reason it out"):

| setting | completion tokens | notes |
|---|---|---|
| thinking off (**default**) | 441 | `<think></think>` prefilled by the template |
| thinking on | 1,735 | closes `</think>` after ~1,300 tokens, then answers |

Roughly **4x** on a simple question. On a *hard* one (a two-trains-and-a-bird puzzle) the
picture is much worse. Unbounded thinking does not converge at all:

| mode | wall time | completion tokens | finish reason |
|---|---|---|---|
| off (**default**) | 19.0 s | 594 | `stop` |
| on (unbounded) | **563.5 s** | 16,000 | `length`, never terminated |
| budgeted 750 (half) | 56.9 s | 1,774 | `length` |
| budgeted 375 (quarter) | 49.8 s | 1,399 | `length` |

**Unbounded thinking is not a safe setting on this model.** It ran to a 16 K-token cap
and nine and a half minutes without closing `</think>`. Use `budgeted` if you want
thinking at all. The budget is what turns a non-terminating run into a ~1-minute one.

There is no half-way setting inside the model, and vLLM 0.17.1 has no thinking-budget
flag: `max_thinking_tokens`, `thinking_budget` and `reasoning_max_tokens` are all
accepted and silently ignored in the request body (verified against the running server).
That is why the budget here is enforced as a `max_tokens` ceiling on the whole
completion.

`research_agent/thinking.py` adds the control:

| `AGENT_THINKING` | behaviour |
|---|---|
| `off` (default) | template prefills `<think></think>`. Fastest. |
| `on` | unbounded reasoning. Slowest, best on multi-step questions. |
| `budgeted` | reasoning on, completion capped at `AGENT_THINKING_BUDGET_TOKENS` + answer allowance |

`AGENT_THINKING_BUDGET_TOKENS` defaults to **750**, half a measured unbudgeted thought,
which is the "half the thinking" setting.

**Tool-calling turns keep thinking off, whatever the mode.** Choosing a tool is routing, not
reasoning, and letting this model reason about it is what produces the repeated-call loop
the `agent` node has a guard for. The budget applies to the `finalize` node, which writes
prose and cannot call a tool, which is the turn where thinking changes the answer.

**Two things to fix before shipping `on` or `budgeted` to real users:**

1. vLLM is not started with `--reasoning-parser qwen3`, so `reasoning_content` is never
   separated out and the `<think>` block lands in the answer the user reads. In the runs
   above the budgeted modes returned *only* reasoning (the budget was spent before the
   model closed the block), so without the parser the chat would show a chain of thought
   and no answer.
2. A budget that truncates mid-thought yields no answer at all. If thinking is wanted,
   pair it with a larger `ANSWER_TOKEN_ALLOWANCE`, or accept `off` for the chat path and
   reserve thinking for the Temporal research task where minutes are affordable.

## Stopping the model looping

Small models are bad at deciding they are finished. Given results that fully answer the
question, Qwen3.5-2B will still re-issue a search it has already run. Left alone that ends
in langgraph's `GraphRecursionError`, which surfaces as an **HTTP 500 with no answer at
all**. The least useful possible failure, since the tool results needed to answer were
already in hand.

`_create_graph` therefore routes to a `finalize` node when either guard trips:

* **a repeated tool call**, at temperature 0 the same call returns the same result, so a
  repeat is a stuck loop, not exploration;
* **`AGENT_MAX_TOOL_TURNS`** (default 12) tool-calling turns.

`finalize` removes the unsatisfied tool call (an OpenAI-shaped request carrying `tool_calls`
with no matching results is rejected), appends "answer now from what you already have", and
runs the same model **with no tools bound**, a model that cannot call a tool has to answer.
`AGENT_RECURSION_LIMIT` (default 40) is the hard backstop behind both.

`finalize` is an answer-producing node exactly like `agent`, so the SSE event loop must
watch both. Omitting it is why the forced answer first came back as an empty string with a
cheerful HTTP 200.

## Context compaction: `AGENT_COMPACTION_FRACTION`

A tool-using turn grows because every result it collected stays in the list sent back to
the model on the next call. `research_agent/compaction.py` replaces the content of the
older tool results with a placeholder once the last call the provider billed crosses a
fraction of the model's stated context window. The assistant messages that requested them
keep their `tool_calls`, so the model still sees that it searched and what for, and the
`AGENT_COMPACTION_KEEP_RECENT` (default 3) most recent results stay intact because the
model is usually still working with what it just read.

| variable | default | meaning |
|---|---|---|
| `AGENT_COMPACTION_FRACTION` | `0.6` | fraction of the stated window at which compaction fires. Out of range, or unparseable, turns compaction off rather than clamping |
| `AGENT_COMPACTION_KEEP_RECENT` | `3` | most recent tool results left intact by eviction |
| `AGENT_COMPACTION_KEEP_RECENT_MESSAGES` | `6` | trailing messages summarisation leaves alone, on top of what it may never touch |
| `LLM_MODEL_COMPACTION` | the answering model | model that writes the handoff document |

**It does not fire on the traffic this stack produces.** The widest turn measured here
(the full research profile, sixteen tool calls, three web pages read and cited) peaked at
about a tenth of the window, and an ordinary corpus question at half that. The trigger is
sized against the window rather than against those measurements because the window is a
property of the model in use: a smaller-window model, a larger corpus, sub-agents, or tool
results replayed across turns all bring it into range.

Three properties decide whether a citation still resolves:

* **Nothing is edited.** The transformation sits in front of the prompt template, not in a
  node that writes state, so the graph state, the trajectory the website renders and the
  transcript rows all keep every result in full. Only the model sees less.
* **A result is shortened, never removed.** An assistant message whose `tool_calls` have no
  matching tool result is rejected by an OpenAI-shaped API outright (the same constraint
  `finalize` works around above), so the placeholder is what "dropped" has to mean here.
* **An unknown window never fires the trigger.** `llm_models.context_window` is 0 when the
  provider never stated one, and there is no default to fall back on. The catalog is the
  source rather than the provider directly, so the number the trigger divides by is the
  number the transcript footer shows the user.

### Layer two: summarisation

Eviction runs first, always, because it makes no model call and cannot lose a fact: every
result it takes away is still in the transcript and can be re-read. Summarisation runs
only on what eviction leaves, and only when the list is still projected to be over the
threshold. That projection is an estimate and is labelled one. The only measured token
count available is what the provider billed for the *previous* call, so the saving is
scaled by the fraction of the list's characters eviction removed.

Layer two drops whole call-and-result groups and puts one structured handoff document in
their place: what was replaced, the citations that stand, and three model-written sections
quoting verbatim rather than paraphrasing. If the summariser answers with nothing, if there
is too little unprotected material to be worth a model call, or if the handoff would be no
smaller than what it replaces, the list is sent as layer one left it.

**The handoff is a user message, not a system message.** It lands in the middle of the
list, and this provider answers a system message anywhere but the first position with
`System message must be at the beginning.`. A 400 the client retries, so the symptom is a
turn that hangs rather than one that fails. The bracketed header is what tells the model
the message is not the user speaking.

The summariser runs with thinking off and a hard completion ceiling. Summarising is not a
reasoning task, and a thinking model handed a transcript starts answering the research
question instead of compressing it. Measured here as a call that did not return inside two
minutes.

**Some messages are never summarised, and that is enforced by selecting them in code, not
by asking the summariser to spare them.** `protected_indexes` picks out the user's own
messages, every todo call and result, the `cite_documents` result that says which document
`[D3]` means, any message whose text carries a handle, and the most recent exchanges;
those are copied into the outgoing list unchanged and the summariser never sees them. A
model asked politely to preserve a citation will eventually not, and **a compaction that
loses a citation the answer already made is a correctness bug, not a compression
trade-off.** Protection is closed over call-and-result groups, so a preserved result never
arrives without the call that asked for it. Eviction honours the same set.

**A summarised turn says so to the user; an evicted one does not.** The difference is what
a reader can still check. Eviction leaves every result in the transcript, so the evidence
is there. Summarisation replaces the model's own working prose, and the answer was written
from that summary rather than from what the agent read, which is a fact about how much to
trust it, so the answer carries one line saying so.

Every applied compaction writes a `chat_compactions` row. What was evicted, the handoff
document whole, the citation handles that were live, the model-visible list either side,
the trigger and its denominator, and the token counts before and after. The "after" is the
prompt of the first call made on the shortened list, so it arrives one call later and
supersedes the first insert under the same compaction id.

## Tool arguments sent as JSON strings

The served model often writes a non-string tool argument as a string. It sends
`"collectionname": "testdata"` or `"collectionname": "[\"testdata\"]"` for a list of
strings, and `"filename_only": "True"` for a boolean. The MCP servers validate arguments
with pydantic in lax mode. That mode converts `"True"` and `"5"`, and refuses a string for a
list or an object, so such a call fails and the model gets no result.

`_create_graph` wraps every MCP tool with `with_decoded_arguments` (`agent.py`), and the
execution node (`execution.py`) decodes the arguments of every call it runs. The workers
use the same wrapped tools and the same execution node. Before each call, `decode_string_arguments` (`tool_args.py`)
reads the parameter's JSON schema, following `anyOf`, `oneOf`, `$ref` and `type` lists. It
changes a string argument only when the schema does not allow a string:

- A string that parses as JSON becomes the parsed value, if that value has an allowed type.
  `null` is never a target.
- For a boolean, `true` and `false` in any case become the boolean.
- For a list of strings, a string becomes a one-item list when it does not parse, or when it
  parses to a value of a type the schema does not allow. `"2024"` becomes `["2024"]`.

Every other value stays as the model wrote it, so the server's own validation error reaches
the model. The decoding runs in the agent because the MCP schemas are correct. `recurse_json_decode`
decodes strings only for the event stream, and does not change what a tool receives.

## `LLM_STREAMING` and `disable_streaming`

**Streaming is back on** (`LLM_STREAMING=true`), and the workaround is retained.

Under **vLLM 0.11**, streamed tool-call deltas arrived with the function name but
`arguments` absent. langchain turned those into `tool_call_chunk`s with `args=None`, which
never accumulated into the final `AIMessage`. `message.tool_calls` came back empty,
`should_continue` routed straight to `END`, and the agent produced a confident answer having
silently made **zero** tool calls. It presents as "the model is bad".

`disable_streaming` is the switch that actually matters, not `streaming`: the latter only
affects `invoke`, while langgraph drives the model through `astream_events`, which calls
`astream` and streams regardless. With `disable_streaming=True`, `astream` degenerates to a
single `invoke` and the node emits a whole `AIMessage` with its `tool_calls` intact.

**Re-tested on vLLM 0.17.1 + Qwen3.5-2B: fixed.** With `LLM_STREAMING=true` a real agent run
made 4 tool calls and returned a correctly cited answer, so the default is now on and token
streaming is back. The code path and its comment are deliberately left in place. Set
`LLM_STREAMING=false` if it ever regresses. **The symptom to watch for is an agent that
answers with no tool calls**, not an error.

Note this is a separate failure from the tool-*parser* problem: `--tool-call-parser hermes`
does not match Qwen3.5's XML blocks and produces the same zero-tool-call symptom for an
unrelated reason. See [`../README.md`](../README.md).

## Features

- 🤖 **AI Research Agent**: Powered by configurable LLM models
- 🔗 **MCP Integration**: Connect to multiple MCP servers for tool access
- 🌊 **Streaming Responses**: Real-time streaming of agent responses with reasoning
- 🚀 **FastAPI Backend**: Modern, fast web API with automatic documentation
- ⚙️ **Environment Configuration**: Fully configurable via environment variables
- 🏥 **Health Checks**: Built-in health monitoring and status endpoints

## Quick Start

### Running

In deployment both agent containers are built from this directory by
[`../../ops/docker/compose/agents.yaml`](../../ops/docker/compose/agents.yaml) and come
up with the main stack (`./deploy` from the repo root). Environment is rendered from
`hoover4.ini` by `deploy.py`, there is no `.env` to copy. For local development
outside docker, `poetry install` and `python main.py` still work.

## Configuration

The application is configured entirely via environment variables (rendered from
`hoover4.ini` by `deploy.py` in deployment):

### Required Variables

- `LLM_API_KEY` (or `LLM_API_KEY_FILE`, a bind-mounted file takes precedence when the plain var is unset): Your LLM API key
- `MCP_SERVERS`: Comma-separated list of MCP server URLs. On `hoover4-full-research-agent`, `deploy.py` renders this from `internet_tools_enabled`: five servers when on, collections and todo when off.

### Optional Variables

- `LLM_BASE_URL`: Base URL for your LLM service
- `LLM_MODEL`: Model name to use
- `LLM_TEMPERATURE`: Temperature setting (default: 0.0)
- `AGENT_NAME`: Name of the agent
- `SYSTEM_PROMPT`: overrides the rendered prompt; empty means render this profile's templates
- `HOST`: Host to bind to (default: 0.0.0.0)
- `PORT`: Port to bind to (default: 8000)
- `RELOAD`: Enable auto-reload for development (default: false)

## API Endpoints

### Health Check
- **GET** `/health` - Check agent status and readiness

### Run Streaming
- **POST** `/run/stream` - Stream one agent run. See "The run request" above.

### API Information
- **GET** `/` - API information and configuration details

## Usage Examples

### Health Check

```bash
curl http://localhost:8000/health
```

## Response Format

The streaming endpoint returns Server-Sent Events with JSON data:

```json
{
  "is_task_complete": false,
  "type": "start",
  "content": ""
}
```

### Response Types

- `start`: Initial response start
- `start_reasoning`: Beginning of reasoning phase
- `reasoning`: Reasoning content (if supported by model)
- `start_response`: Beginning of final response
- `response`: Final response content
- `model_turn`, `tool_start`, `tool_result`, `delegate`: the run events, see "The run request"
- `error`: Error occurred
- `end`: Final completion signal

## Development

### Running in Development Mode

```bash
# Enable auto-reload
export RELOAD=true
python main.py
```

### Testing

```bash
# Run tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=research_agent
```

### Code Quality

```bash
# Format code
poetry run black .

# Lint code
poetry run ruff check .

# Type checking
poetry run mypy research_agent/
```

## Docker Support

The included Dockerfile is what `compose/research-agents.yaml` builds (context:
`main_services/agents`, because the image copies `agent_common` for the tool pack table). Secrets arrive as read-only bind mounts under `/run/secrets/`; the code
falls back to `LLM_API_KEY_FILE` / `MCP_SHARED_SECRET_FILE` when the plain env vars
are unset.

## Architecture

### Components

- **FastAPI Application**: Web API with lifespan management
- **MCP Gateway Agent**: Core agent with MCP tool integration
- **Streaming Handler**: Real-time response streaming
- **Environment Configuration**: Flexible configuration system

### MCP Integration

The agent connects to MCP servers to access various tools and capabilities:

- Database connections
- File system access
- External API integrations
- Custom research tools

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Run the test suite
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For questions, issues, or contributions, please open an issue on the GitHub repository.
