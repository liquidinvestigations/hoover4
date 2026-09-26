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
Each process holds its own cache of step contexts. Citation `[Dn]` handles
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
2. It passes that list with the turn to the Temporal worker, and the worker sends it to
   the agent as `allowed_collections` on each `/model_step` and `/tool_call` request.
3. `acl_headers()` turns it into `X-Hoover4-Collections: <list>` plus
   `Authorization: Bearer $MCP_SHARED_SECRET`, set as **MCP connection headers**.
4. The agent caches **one step context per ACL, chat session and run** (`_acl_key`), so
   the connection headers built for one user are never used for another. The chat session
   is part of the key because `X-Hoover4-Chat-Session` travels in the same connection
   headers. See the browser sessions note below. The cache is LRU-bounded by
   `AGENT_MAX_CACHED_GRAPHS` (default 24). A context holds no open connection, but it holds
   the tool objects of every configured server, so it cannot be allowed to grow per
   conversation without limit.
5. `hoover4-mcp-collections` enforces the header on every tool call.

The model never sees or supplies its own permissions. They are not tool arguments, so it
cannot widen them. An empty list is sent as an empty header rather than omitted: "this user
may read nothing" and "no ACL was supplied" must not look the same to the MCP server, which
denies the second outright.

## System prompts live in `research_agent/prompts/`

Not in compose, and not as string literals. Each profile is a `.md.j2` template beside the
loader in `research_agent/prompts/__init__.py`, which is the only thing that renders one.
`SYSTEM_PROMPT` overrides the whole rendered text; empty means "render the templates".

**The prompt is a function of the deployment.** It is rendered for each model call from
the step context that `_create_context` builds, at the first point where the tool list is
real, and it takes named parameters: the bound tool names, whether delegation is bound,
whether the caller can read any collection at all, and whether the open web is reachable.
The tool section is generated from the bound names, so a prompt can neither describe a tool
the model does not have nor leave out one it does. `tests/test_prompts.py` fails when a
template names an unbound tool. Renaming a tool
used to mean correcting the same sentence by hand in several prose files, and the one that
was missed told the model to call a name that no longer existed.

Blocks in `prompts/_blocks/` are shared, and each guards itself: the plan-first block
renders only where the todo writers are bound, so a worker profile cannot be handed an
instruction to call a tool it does not have. `search.md.j2` tells the model to search the
documents before the web, and to put every form of a name in one `search_collections` call.
It also gives the query syntax that the model gets wrong most often. Each `method_*.md.j2` block is
the research method of one role: the two chat profiles, the planner, the organizer and the
researcher. A sentence in these blocks that names a tool renders only when that tool is
bound.

**Keep the tool notes short.** Qwen3.5-2B follows a long, numbered, multi-clause prompt by
doing all of it forever: an earlier five-step draft made the model search, search again,
then re-run a query it had already run until the request died with no answer. The method
blocks are long, about 3,000 tokens each, and they are written for the served model. Detail on one tool belongs in its description, which the model reads in
context at the moment it picks a tool. The Manticore match syntax reaches the model through
the search block and the descriptions of the search tools. The collection MCP server also
renders it into its `instructions`, which this agent does not pass to the model.

## Delegation

A lead binds `run_subagent` when the `delegation` pack is in its run kind's packs, which
is the default for both agents. The tool splits a question into one to five briefings.
`/model_step` gives a `run_subagent` call whose briefings can be read the kind
`delegation`, with its briefings (`steps.py`). The worker runs every other call of that
reply, and then writes one sub-agent run for each accepted briefing, and each runs as an `AgentRun` of its own, with the
`research_subagent` profile. When the last one ends, a continuation of the delegating run
sends the thread back with one `tool` result for each call, and the model continues. A
sub-agent at depth 1 can delegate again, and a run at depth 2 cannot. The worker applies the
budgets. See `processing/tasks/Readme.md` for the runs, the fan-in and the budgets.

**Depth is enforced by what is bound.** A step request with `can_delegate` false does not
bind `run_subagent`, so a call to it is a `parallel` call, and `/tool_call` answers it with
`tool_unavailable`. A prompt asking a model not to recurse eventually meets a model that does.

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

Each step context builds one `CatalogueSnapshot` (`tool_catalogue.py`) from the tools of its packs.
The snapshot splits them into core tools, which every model call binds, and deferred tools.
The core tools are `list_collections`, `search_collections`, `search_passages`,
`read_documents`, `list_document_entities`, `cite_documents`, `read_more`,
`search_agent_tools`, `run_subagent`, and every tool of a server other than the collection
server and the plan tools. The plan tools are core for the `planner` and `organizer` kinds.

The model finds a deferred tool with `search_agent_tools`. It ranks an exact name, then the
request as words of a tool's summary, then a name prefix, then the count of shared words. It
returns at most `AGENT_CATALOGUE_MATCH_COUNT` matches (6 to 12, default 6), and
`No available tool matches this request.` when nothing matches.

The bound names are not stored. `/model_step` derives them from the thread with
`bound_names_from_thread` (`tool_catalogue.py`): for each reply of the thread, the bind step
puts the matches of its successful `search_agent_tools` results first, then the earlier
names, and keeps `AGENT_CATALOGUE_MATCH_COUNT`. The model call binds the core tools and the
bound names, and the `model_turn` frame returns the bound names. `/tool_call` receives them
back, refuses any other name with a `tool_unavailable` error, decodes and validates the
arguments, and runs the call. The worker runs plan mutations one after the other in call
order, and the other calls in parallel.

### The batch result budget and the call measure

The result pages of all calls of one model reply share one budget. `/model_step` reserves
the empty page of each call first, divides the rest equally, and gives each call entry its
`page_share`. `/tool_call` sends the share in the `X-Hoover4-Page-Share` header. The connections' HTTP client factory
(`page_share_client`) adds the header, because the MCP adapter opens one session for each
call. The collection server's page broker sizes each page within that share, a later page
of a stored window included.

- **Safe mode** is the default. One turn's results share 24,000 UTF-8 bytes, or less when
  the request bytes plus the completion reserve leave less of the context window.
- **Token mode** needs `AGENT_MAX_PAGE_TOKENS` and `AGENT_COMPLETION_RESERVE_TOKENS`, and a
  known context window. The service counts the request and the empty pages with the served
  tokenizer and applies `result_pages.allocate`. It sends the token share as a byte share,
  because a token covers at least one byte. A failed count keeps safe mode. When the empty
  pages and the reserve do not fit, every call entry has `budget_exhausted`, and
  `/tool_call` returns the empty `budget_exhausted` page with no call.

A page that the broker stored as a window is read on later pages with the share it was
stored with, when not one unit fits the current share.

The broker returns the `build_page` measure of the page beside the page text, as an embedded
resource. The adapter puts that block in the tool message artifact. `/tool_call` takes it out and
returns it as the `measure` of the response. A tool that is not a broker tool has no
measure.

## The step requests

The worker runs the agent loop in the `AgentRun` workflow. For each model call it sends
`POST /model_step`, and for each tool call of a reply it sends `POST /tool_call`. The service
keeps no state of a run between two requests. Both requests carry the run fields of
`StepRun` (`steps.py`): `run_id`, `kind`, `depth`, `purpose`, the caller's identity and
collections, `llm_model` and `can_delegate`.

### `POST /model_step`

The request adds `step_no` (1 for the first model call of the run thread), `mode` (`tools`,
`final` with no tool bound, or `plan`), `thinking` (a required bool, the admin thinking
switch), the run's thread as `messages`, and the earlier turns of the chat as `earlier`
(depth 0 only). `messages[0]` is the opening human message. Each message carries its stored
key, `thread_id` and `idx`. `earlier` holds the stored threads of the earlier chat turns in
full, with their tool calls and results. A call of an earlier turn that has no result, which
a stopped turn leaves, gets a `not_run` result in the request only. `run_messages.py` applies
the stored `compaction` rows and rebuilds the messages into langchain messages, with the tool
calls and the stored usage, so compaction can measure the thread before the model call.

Mode `plan` is the first-turn planning call of a chat. Its system text is
`prompts/planning_call.md.j2`, with the collections the run can read and one line on the
web tools. It binds `write_todo` only with `tool_choice` `auto`, it sends thinking off
whatever the request says, a call to any other name is dropped from the reply, and its
`llm_call_events` row has `kind` `plan`. The worker runs the `write_todo` call through
`/tool_call`, so the todo server writes the plan.

The response is a stream of `data: {json}` frames, in this order:

| `type` | fields | when |
|---|---|---|
| `reasoning` | `content` | each reasoning delta |
| `response` | `content` | each text delta |
| `model_turn` | `text`, `reasoning`, `tool_calls` (a list of call entries), `bound_names`, `usage` (`input_tokens`, `output_tokens`, `total_tokens`, `reasoning_tokens`), `summarised`, `compaction` (the record of this call's compaction, or null) | once, after the reply ends |
| `end` | `model`, `latency_ms`, `usage` (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`) | once, last |
| `error` | `error_class`, `retryable`, `content` | in place of `model_turn` and `end` |

`error_class` is `read_timeout`, `connect_error`, `http_<status>` or `other`. `retryable` is
false only for an HTTP 4xx status other than 408 and 429. `summarised` is true when the
compaction of this call summarised the thread. The worker then adds the summary notice to
the answer.

A call entry is one call of the reply as the service classifies it:

| field | meaning |
|---|---|
| `id` | the call id. An id that is empty, repeated in the reply, or used by an earlier `ai` message becomes `call-{step_no}-{position}` |
| `name`, `args` | the call as the model wrote it |
| `kind` | `delegation` for a `run_subagent` call whose briefings can be read, `ordered` for a plan mutation, `parallel` for every other call |
| `briefings` | the briefings of a delegation |
| `page_share`, `budget_exhausted` | the call's share of the batch result budget, in bytes, for a `parallel` or `ordered` call |
| `retry` | false for the browser actions (`browser_navigate`, `browser_click`, `browser_type`, `browser_select_option`, `browser_press_key`). The worker gives such a call one attempt |
| `args_digest` | the sha1 hex of the name, a newline and the canonical JSON of the arguments |

While no frame is ready, the stream sends the SSE comment line `: keepalive` every 30 s
(`KEEPALIVE_SECONDS` in `steps.py`). One model call can wait longer than the worker's 300 s
read timeout of the stream, and each comment line restarts that timeout. A reader of
`data: ` frames skips the comment lines. A client that closes the request stops the model
call.

### `POST /tool_call`

The request adds `call` (the `id`, `name` and `args` of one stored call entry),
`bound_names` (from the `model_turn` that made the call), `page_share`,
`budget_exhausted` and `idempotency_key`. The service sends the key to the MCP server as
`X-Hoover4-Idempotency-Key`, so a retried plan mutation changes the plan tree once. The
response is JSON:

| field | meaning |
|---|---|
| `tool_call_id`, `name` | the call |
| `content` | the result text that the model reads |
| `status` | `ok` or `error` |
| `error_class` | empty for `ok`. For `error`: `tool_error` (the tool raised or marked its result as an error), `tool_unavailable` (a name that this step did not bind), `invalid_arguments` (arguments that do not match the schema, or a `run_subagent` call) or `budget_exhausted` |
| `measure` | the call measure of a broker tool, or `null` |
| `matched_names` | the names that a `search_agent_tools` result matched |

## Per-chat and per-run browser sessions

`X-Hoover4-Chat-Session` carries the chat session id alongside the ACL headers. It grants
no authority. It is an **isolation key**. `hoover4-mcp-browser` uses it to give each
conversation its own Chromium browser context, so cookies and storage from one chat do not
follow the next one. A step request also sends `X-Hoover4-Agent-Run` with the run
id, and the browser server then keys the browser by the run. The chat session stays the
key for citations, artifacts and the todo list. Sessions are dropped when the chat ends, or after
`BROWSER_SESSION_IDLE_SECONDS` (1 h) idle. See
[`../browser_use_server/README.md`](../browser_use_server/README.md).

## Thinking: the `thinking` value of a model step

A Qwen-family chat template decides thinking in the **prompt**. The sampler has no part in it. With
`enable_thinking` unset or false it emits `<think>\n\n</think>` *before* generation, so
the model does not reason at all. With it true the model reasons, then answers.

Measured on this host, Qwen3.5-2B, simple question ("what is 17x23, reason it out"):

| setting | completion tokens | notes |
|---|---|---|
| thinking off | 441 | `<think></think>` prefilled by the template |
| thinking on | 1,735 | closes `</think>` after ~1,300 tokens, then answers |

The admin switch "Thinking" on `/admin/llm` decides the value. It is the `server_settings`
row `llm_thinking`, and an absent row is on. The worker reads the row before each model
call and sends `thinking`, a required boolean of `POST /model_step`. The service sends it as
`chat_template_kwargs.enable_thinking` in the request body, in both modes (`thinking.py`).
The title call and the compaction summary send `enable_thinking: false` of their own. The output cap `AGENT_MAX_OUTPUT_TOKENS` bounds a request with thinking on.

The thinking text arrives in the delta field `reasoning` from vLLM, and in
`reasoning_content` from older servers and other providers. `chat_model.py` reads either
field and gives the agent `reasoning_content`.

## Stopping the model looping

Small models are bad at deciding they are finished. Given results that fully answer the
question, Qwen3.5-2B will still re-issue a search it has already run. The worker's agent
loop stops such a run. It sends a `final` model step, with no tool bound, when the model
repeats a call (the `args_digest` of a call entry makes the repeat visible) or when the run
reaches its step budget. A model that cannot call a tool has to answer. See
`processing/tasks/Readme.md` for the loop.

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
| `AGENT_COMPACTION_FRACTION` | `0.65` | fraction of the stated window at which compaction fires. Out of range, or unparseable, turns compaction off rather than clamping |
| `AGENT_COMPACTION_KEEP_RECENT` | `3` | most recent tool results left intact by eviction |
| `AGENT_COMPACTION_KEEP_RECENT_MESSAGES` | `6` | trailing messages summarisation leaves alone, on top of what it may never touch |
| `LLM_MODEL_COMPACTION` | the answering model | model that writes the handoff document |

The earlier turns of a chat reach the model as their stored threads, with every tool call
and result (`POST /model_step` above), so a long conversation reaches the threshold.

**The compacted list is kept.** When a call compacts its input, the `model_turn` frame
carries `compaction`, a record that names each evicted and each summarised message by its
stored key `[thread_id, idx]`, and the handoff document of a summarisation. The worker
stores it as a `compaction` row after the `ai` message of that call. Each later call applies
every stored row first (`run_messages.apply_compactions`), and then measures the usage of the
last call, which was billed on the compacted list. The calls above the threshold therefore do
not alternate between a short list and the full list. A stored row is applied in the request
only: the thread keeps every message in full.

Three properties decide whether a citation still resolves:

* **Nothing is edited.** The transformation applies to the messages of a model call only,
  so the stored messages, the trajectory the website renders and the transcript rows all
  keep every result in full. Only the model sees less.
* **A result is shortened, never removed.** An assistant message whose `tool_calls` have no
  matching tool result is rejected by an OpenAI-shaped API outright (the same constraint
  a `final` step works around), so the placeholder is what "dropped" has to mean here.
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
`[D3]` means, any message whose text carries a handle, every failed tool result, and the
most recent exchanges;
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

`_create_context` wraps every MCP tool with `with_decoded_arguments` (`agent.py`), and
`/tool_call` (`steps.py`) decodes the arguments of every call it runs. Before each call, `decode_string_arguments` (`tool_args.py`)
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
`deploy.py` renders `LLM_STREAMING` from `[main_services] llm_streaming`, and an empty key
renders `true`.

Under **vLLM 0.11**, streamed tool-call deltas arrived with the function name but
`arguments` absent. langchain turned those into `tool_call_chunk`s with `args=None`, which
never accumulated into the final `AIMessage`. `message.tool_calls` came back empty, the
reply looked like an answer, and the agent produced a confident answer having silently made
**zero** tool calls. It presents as "the model is bad".

With `LLM_STREAMING=false`, `/model_step` makes one `ainvoke` call and the reply arrives as
one `AIMessage` with its `tool_calls` intact. The client also gets
`disable_streaming=True`. `ThinkingChatOpenAI._create_chat_result` keeps the reasoning of
such a whole reply.

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
- `LLM_SEND_TEMPERATURE`: `false` leaves `temperature` out of every model request: the agent
  turns and the compaction summary. `deploy.py` renders it from the active provider's
  `send_temperature` key. Empty or unset is `true`. `research_agent/model_params.py` owns
  the rule, and the worker's title request mirrors it.
- `AGENT_MAX_OUTPUT_TOKENS`: the output cap of every agent model request, which the model
  client sends as `max_completion_tokens`. Empty sends no cap. The compaction summary keeps
  its own ceiling.
- `LLM_REQUEST_TIMEOUT_SECONDS`: the read timeout of one agent model call, with a 10 s
  connect timeout. When set, the model client does not retry, so a call that receives no
  data for this long fails once and is not sent again. It is also the read timeout of the compaction summary. Empty keeps the client
  default (600 s and 2 retries) and 180 s for the summary.
- `LLM_STREAMING`: see the sections above.
- `AGENT_NAME`: Name of the agent
- `SYSTEM_PROMPT`: overrides the rendered prompt; empty means render this profile's templates
- `HOST`: Host to bind to (default: 0.0.0.0)
- `PORT`: Port to bind to (default: 8000)
- `RELOAD`: Enable auto-reload for development (default: false)

## API Endpoints

### Health Check
- **GET** `/health` - Check agent status and readiness

### Agent steps
- **POST** `/model_step` - Make one model call and stream it. See "The step requests" above.
- **POST** `/tool_call` - Run one tool call. See "The step requests" above.

### API Information
- **GET** `/` - API information and configuration details

## Usage Examples

### Health Check

```bash
curl http://localhost:8000/health
```

## Response Format

`/model_step` returns `data: {json}` frames. See "The step requests" above for the frame
types and their fields.

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
- **MCP Gateway Agent**: the cache of step contexts, with MCP tool integration
- **Step handlers**: `steps.py`, one model call or one tool call for each request
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
