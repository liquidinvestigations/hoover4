# Research Agent API

A FastAPI-based research agent with MCP (Model Context Protocol) tool integration, providing streaming chat capabilities for research assistance.

## The agent profiles

One image, two containers, different tool sets, and the difference is deliberate. A third
profile, `research_subagent`, has no container of its own: it is the profile of a sub-agent
run. See "Delegation" below. The `planner` and `organizer` profiles are the profiles of the
two run kinds of a deep research plan.

| | `hoover4-internal-search-agent` (21936) | `hoover4-full-research-agent` (21937) |
|---|---|---|
| `AGENT_PROFILE` | `internal_search` | `full_research` |
| MCP servers | collections **only** | collections + metasearch + browser + ddg + whois + wikipedia |
| Used by | the runs of a thread with internet tools off | the runs of a thread with internet tools on |

`hoover4-full-research-agent` runs four uvicorn worker processes (`UVICORN_WORKERS`).
Each process holds its own cache of step contexts. Citation `[Dn]` handles
are allocated in the collections MCP server, so the worker processes do not split them.

The profile selects the role line of the prompt and the role skill. The tool packs of the
run kind select the tools. See "Tool packs and the catalogue" below.

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

## The system prompt and the skill store

Not in compose, and not as string literals. One template, `research_agent/prompts/agent.md.j2`,
renders the system prompt of every profile (`research_agent/prompts/__init__.py`).
`SYSTEM_PROMPT` overrides the whole rendered text, and empty means "render the template".

**The prompt lists, and the skills teach.** The prompt holds four parts. The role line of the
profile, the run's skills by name and description, and the run's tools by name and summary
come first. The todo rule follows when the run has the four todo tools. The summary of a tool
is the first sentence of its description, at most 160 characters. `_create_context` renders
the prompt once for each step context. The prompt cache holds the system text for the run.

The method text is in the skill store, `research_agent/skills/` (`skill_store.py`). Each
skill is one `.md.j2` file with front matter (`name`, `group`, `description`, `tools`) and a
Jinja body. The groups are `role`, `general`, `technique` and `stumble`. A run lists the role
skill of its profile, and each other skill whose `tools` list is empty or names a tool of the
run. The role skills (`method_chat_full`, `method_chat_internal`, `method_subagent`,
`method_planner`, `method_organizer`) hold the research method of each role and the
delegation text. The general skills (`search`, `thorough`, `citation`, `plan_first`) hold
the search rules, the investigation rule, the citation protocol and the plan-first protocol.
The technique skills (`browser_use`, `web_research`, `spreadsheets`, `emails`,
`folders_and_files`, `passages`, `entities`, `plan_editing`, `deep_research`) teach the use
of one group of tools. The stumble skills (`after_a_result`, `todo_upkeep`, `document_ids`,
`call_arguments`, `collection_names`, `no_results`, `reviewing_a_report`) teach the fix of
one kind of failed call. A technique or stumble skill stays under 2,600 characters. The
A body names a tool only through `tool()`, and a sentence that names a tool renders only when
`has()` finds that tool in the run. `tests/test_skill_store.py` fails when
a skill names a tool that no pack holds.

The model finds a skill with `search_skills` and reads one with `read_skill`. The result of a
read starts with the line ``Skill `name`.``. A skill of another profile is refused with
`unknown_skill`. `always_read` gives the skills that a run reads at its start, in the order
`search`, `thorough`, the role skill, `citation` and `plan_first`, each only when the run
has its tools. The worker writes these reads into the thread before the first model call
(`POST /preload` below).

The model receives each tool's schema with each call. It can read a fuller description
with `read_tool`. The Manticore match syntax reaches the model through the skill `search` and
the descriptions of the search tools. The collection MCP server also renders it into its
`instructions`, which this agent does not pass to the model.

## Delegation

The organizer has `run_subagent` when its packs include `delegation`. Chat, planner and
sub-agent runs do not receive that pack. The organizer sends each briefing to a fresh run.
`/model_step` gives a `run_subagent` call whose briefings can be read the kind
`delegation`, with its briefings (`steps.py`). The worker runs every other call of that
reply, and then writes one sub-agent run for each accepted briefing, and each runs as an `AgentRun` of its own, with the
`research_subagent` profile. When the last one ends, a continuation of the delegating run
sends the thread back with one `tool` result for each call, and the model continues. A
sub-agent cannot delegate. The worker applies the plan budget. See
`processing/tasks/Readme.md` for the runs and the budget.

The agent service excludes `run_subagent` when the run cannot delegate. It returns
`tool_unavailable` if the run calls that name.

**A plan briefing names its section.** An organizer's briefing carries `plan_node_id`, a
section of the approved tree, and `purpose`: `execute` or `correct`. A `correct` briefing
also carries `sections`, every section it corrects, and `plan_node_id` is the first of them.
The worker refuses a section briefing from another run kind, a second run of a section,
a second correction, and a `review` briefing. An organizer can send a briefing without
a section. Its report is stored under the plan root.

**Sub-agents share the conversation's session header, and that is the citation contract.**
Citation handles are allocated per chat session by the collection-search server, keyed by
the session header. Every run of a turn sends the conversation's session id, so a sub-agent's
`[D1]` resolves in the lead's answer.

## Tool packs and the catalogue

A tool pack is a named set of tools (`agent_common/tool_packs.py`): `catalogue`,
`skills`, `collections`, `conversation`, `plan`, `delegation`, `web` and `browser`. The
`chat`, `planner` and `organizer` runs get the packs that `AGENT_PACKS_CHAT`,
`AGENT_PACKS_PLANNER` and `AGENT_PACKS_ORGANIZER` name, as a comma list or `all`. A
`subagent` run reads `AGENT_PACKS_ORGANIZER`, so it gets its parent's packs. Every run kind
also gets the `skills` pack (`search_skills`, `read_skill`, `read_tool`, `ask_user`,
`write_note`), whatever its setting says. `deploy.py` renders them from `hoover4.ini`. The
service refuses to start on an unknown pack name. A tool that an MCP server lists and no pack
names is refused for every run.

Each step builds a `CatalogueSnapshot` (`tool_catalogue.py`) from the run's packs. Every
model call receives all callable tools in that snapshot. `read_tool` returns one tool's
description and schema. `search_agent_tools` finds tool names from words in a request.
Both tools provide information and do not change which tools the model can call. The
service returns `tool_unavailable` for a name outside the run's callable tools. The
worker runs plan mutations in call order and other calls in parallel.

### The batch result budget and the call measure

The result pages of all calls of one model reply share one budget. `/model_step` reserves
the empty page of each call first, divides the rest by read weight, and gives each call entry its
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
`read_documents` gets one weight for each distinct document, up to ten weights.

The broker returns the `build_page` measure of the page beside the page text, as an embedded
resource. The adapter puts that block in the tool message artifact. `/tool_call` takes it out and
returns it as the `measure` of the response. A tool that is not a broker tool has no
measure.

## The step requests

The worker runs the agent loop in the `AgentRun` workflow. For each model call it sends
`POST /model_step`, and for each tool call of a reply it sends `POST /tool_call`. A run that
starts a thread first sends `POST /preload`. The service keeps no state of a run between two
requests. Every request carries the run fields of
`StepRun` (`steps.py`): `run_id`, `kind`, `depth`, `purpose`, the caller's identity and
collections, `llm_model` and `can_delegate`.

### `POST /model_step`

The request adds `step_no` (1 for the first model call of the run thread), `mode` (`tools`
or `final`), `thinking` (a required bool, the admin thinking
switch), the run's thread as `messages`, and the earlier turns of the chat as `earlier`
(depth 0 only). `messages[0]` is the opening human message. Each message carries its stored
key, `thread_id` and `idx`. `earlier` holds the stored threads of the earlier chat turns in
full, with their tool calls and results. A call of an earlier turn that has no result, which
a stopped turn leaves, gets a `not_run` result in the request only. `run_messages.py` applies
the stored `compaction` rows and rebuilds the messages into langchain messages, with the tool
calls and the stored usage, so compaction can measure the thread before the model call.

The response is a stream of `data: {json}` frames, in this order:

| `type` | fields | when |
|---|---|---|
| `reasoning` | `content` | each reasoning delta |
| `response` | `content` | each text delta |
| `compaction` | `state` (`running`), `tokens_before`, `target`, `parts` (1 or 3) | once, before the summary requests, when this call compacts its input |
| `model_turn` | `text`, `reasoning`, `tool_calls` (a list of call entries), `usage` (`input_tokens`, `output_tokens`, `total_tokens`, `reasoning_tokens`), `summarised`, `compaction` (the version 2 record of this call's compaction, or null), `note_warning` | once, after the reply ends |
| `end` | `model`, `latency_ms`, `usage` (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`) | once, last |
| `error` | `error_class`, `retryable`, `content` | in place of `model_turn` and `end` |

`error_class` is `read_timeout`, `connect_error`, `http_<status>` or `other`. `retryable` is
false only for an HTTP 4xx status other than 408 and 429. `summarised` is true when this call
compacted its input. The worker then adds the summary notice to the answer. `note_warning`
is true when the worker writes the warning to save notes (see
[Context compaction](#context-compaction-agent_compaction_fraction)).

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
`page_share`,
`budget_exhausted` and `idempotency_key`. The service sends the key to the MCP server as
`X-Hoover4-Idempotency-Key`, so a retried plan mutation changes the plan tree once. The
response is JSON:

| field | meaning |
|---|---|
| `tool_call_id`, `name` | the call |
| `content` | the result text that the model reads |
| `status` | `ok` or `error` |
| `error_class` | empty for `ok`. For `error`: `tool_error` (the tool raised or marked its result as an error), `tool_unavailable` (a name outside the run's tools), `invalid_arguments` (arguments that do not match the schema) or `budget_exhausted` |
| `measure` | the call measure of a broker tool, or `null`. When the agent repaired the arguments, `argument_repairs` lists each repair |
| `matched_names` | the names that a `search_agent_tools` result matched, or the name that a `read_tool` result described |

A `tool_unavailable` result names the unavailable tool. `search_agent_tools` can list
available names.

**A failed result names the skill of its fix.** `stumbles.with_skill_line` reads each result
before the service returns it. When the result shows a known stumble, and the run lists the
skill that teaches its fix, the text ends with the sentence "Before you call this tool again,
read the skill `name` with `read_skill`." A file name or a path in place of a `file_hash`
names `document_ids`, a collection outside the chat names `collection_names`, a refused query
list names `search`, a refused todo call names `todo_upkeep`, a refused plan tree call names
`plan_editing`, arguments that the schema refuses name `call_arguments`, and a browser error
names `browser_use`. In a JSON object the sentence goes after the text of `message`, else of
`error`, else under the key `next`. In other text it goes after a blank line. A result
page, a result with no failure, and a repeat refusal get no sentence.

**The arguments are repaired before the call.** The tool call parser of the model server
can leave the model's string token `<|"|>` in a key or a value, a quote on a key (`id"`),
or one layer of quotes around a one-word value. `tool_args.repair_arguments` removes the
token, the quotes of a key and that one layer, and keeps the quotes of `query`, `queries`,
`quote` and `find`, because a phrase search needs them. `tool_args.rename_aliases` then
renames a key that the model wrote under another name, such as `collection` for
`collectionname`, when the tool's schema has that name. Each repair is one line of the
`argument_repairs` list in the measure of the call.

### `POST /preload`

The request includes the opening request and the skills read in earlier chat turns. The
response gives synthetic reads of the role and general skills. Each read holds `name`,
`args`, `content`, `status` and `error_class`. The worker assigns its call id. A preload
failure leaves the run active.

## Per-chat and per-run browser sessions

`X-Hoover4-Chat-Session` carries the chat session id alongside the ACL headers. It grants
no authority. It is an **isolation key**. `hoover4-mcp-browser` uses it to give each
conversation its own Chromium browser context, so cookies and storage from one chat do not
follow the next one. A step request also sends `X-Hoover4-Agent-Run` with the run
id, and the browser server then keys the browser by the run. The chat session stays the
key for citations and artifacts. The todo server keys chat and organizer lists by session,
and planner and sub-agent lists by run id. Sessions are dropped when the chat ends, or after
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
loop stops such a run. It sends a `final` model step when the model
repeats a call (the `args_digest` of a call entry makes the repeat visible) or when the run
reaches its step budget. See
`processing/tasks/Readme.md` for the loop.

## Context compaction: `AGENT_COMPACTION_FRACTION`

A run grows because every result that it collected stays in the list of the next model call.
`research_agent/compaction.py` compacts the list when the last call that the provider billed
(prompt plus completion) reaches the trigger, a fraction of the model's stated context
window. It plans the list to a target of a third of the trigger before the next model call,
and replaces the older steps with one record.

| variable | default | meaning |
|---|---|---|
| `AGENT_COMPACTION_FRACTION` | `0.80` | fraction of the stated window at which compaction fires. Out of range, or unparseable, turns compaction off |
| `LLM_MODEL_COMPACTION` | the answering model | model that writes the summary part of the record |

For a window of 262,144 tokens at 0.80, the trigger is 209,715 tokens, the target 69,905, the
recent window 17,476 and the note warning 188,743.

**The parts of the list.** `compact` plans, in this order, with no model call:

1. **The recent window.** The newest step groups (an `ai` message and its results), up to a
   quarter of the target, and at least the newest group.
2. **The keep set**, outside the window. Every user message. The newest successful todo
   result and plan result. Every `cite_documents` result, and every `ai` text with a citation
   handle such as `[D3]`. The newest `read_skill` result of each skill name, cut to 5,000
   tokens, and 25,000 tokens for all skills. Every `run_subagent` report, cut to 4,000
   tokens. The `write_note` results, 4,000 tokens for all notes. The keep set, user messages
   included, has a cap of 35,000 tokens. A kept result keeps its call. Its `ai` message
   keeps its text only when the text holds a citation handle.
3. **The record.** Every other message: old results, old `ai` messages, and an earlier
   record. One `human` message takes the place of the first of them.
4. **Skill and tool texts.** A `read_skill` or `read_tool` result that is not in the window
   or the keep set leaves the list whole, with its call. It never reaches the summariser.
   The record names it, and the model can read it again. A later read of it is not a repeat.

**The shrink order.** When the list with a record budget of 2,000 tokens passes the
target, or the keep set passes its cap, the plan makes it smaller: the oldest window groups
leave the window, then the oldest reports move to the record, then the oldest skills leave
the list, then the record budget falls to 1,000 tokens, then the results of the newest group
are cut to fit, to at least 500 tokens. When the user messages and the fixed part pass the
target, the smallest list goes, and `target_reached` is false. The run goes on. After the
plan, up to 3 of the newest `read_documents` results of the record come back, each cut to
5,000 tokens, while the list stays at or under the target.

**The token estimate.** The sizes are estimates. `Estimator.calibrate` divides the billed
prompt of the newest billed call by the characters of the list that it sent, the system text
and the tool schemas included, and clamps the ratio to 1/6 to 1/1.5 tokens a character.
Each size gets a margin of 5 percent.

**The record.** It starts with `RECORD_HEADER`. Code writes the lists next
(`thread_index.py`): the searches that found nothing, the searches that found documents with
their counts, the documents read with their pages, and one line that names the skill and tool
texts that left the list. The model never writes those lists, because a summariser copies
file hashes with errors. The served model writes the rest with thinking off, in one request,
or in 3 requests at once when the record part passes 30,000 tokens. Each request gets its
share of the record budget as `max_tokens`. A part that fails or times out gets the line
`PART_FAILED`, and no second request is made. The summary request has the read timeout of a
model call. Before the requests, the stream sends one `compaction` frame, and it sends
keepalive lines while they run.

**The compacted list is kept.** `model_turn` carries `compaction`, a version 2 record: the
keys `[thread_id, idx]` of the messages that it `summarised`, `text_removed`, `dropped` and
`cuts` (with the characters kept), the record as `handoff`, `tokens_before`, `threshold`,
`target`, `est_after`, `target_reached`, the `steps` of the shrink order, the state of each summary
part in `parts`, `steps_summarised` and `sizes`. The worker stores it as a `compaction` row
after the `ai` message of that call. Each later call applies every stored row first
(`run_messages.apply_compactions`, which also applies a version 1 row), and then measures the
usage of the last call. `compact` builds its own list with `run_messages.apply_record`, so a
replay of the row gives the list that the call sent. After the row applies, each call keeps
one result and each result keeps its call, because the provider refuses a request without
that.

Three properties hold.

* **Nothing is edited.** The compaction applies to the messages of a model call only, so the
  stored messages, the trajectory that the website renders and the transcript rows keep every
  result in full.
* **An unknown window never fires the trigger.** `llm_models.context_window` is 0 when the
  provider never stated one, and there is no default. The catalog is the source, so the
  number that the trigger divides by is the number that the transcript footer shows.
* **The record is a user message.** It lands in the middle of the list, and this provider
  answers a system message anywhere but the first position with `System message must be at
  the beginning.`. The bracketed header tells the model that the user did not write it.

**A compacted turn says so to the user.** The answer was written from a record and not from
what the agent read, so the worker adds one line to the answer (`summarised` of
`model_turn`).

**The notes tool.** `note_tools.py` gives the tool `write_note` (`text`, 1 to 2,000
characters). It returns `{"saved": n, "note": text}`, where `n` counts the notes that the
step context of the run saved. It is in the `skills` pack. Its results stay in the keep set.
`model_turn` sets `note_warning` when
the reply's input plus output tokens reach 90 percent of the trigger, the reply has calls,
and no warning row (`NOTE_WARNING_TEXT`) follows the newest `compaction` row. The worker
then writes the warning row.

The first model step of a run logs a warning when the system text, the tool schemas and the
user messages pass the target, at 3 characters a token.

Every compaction writes a `chat_compactions` row: the record whole, the citation handles in
the list, the list after, the trigger and its window, and the token counts before and after.
The "after" is the prompt of the call made on the compacted list, so it arrives with the
second insert under the same compaction id.

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
- `LLM_CLASSIFIER_URL`: the `systemone` route of the structured model server, which
  `POST /preload` asks. `deploy.py` renders it for the selfhosted provider with the AI tier
  present, and empty otherwise. Empty sends no classifier request.
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
- `SYSTEM_PROMPT`: overrides the rendered prompt; empty means render the prompt of the run's profile
- `HOST`: Host to bind to (default: 0.0.0.0)
- `PORT`: Port to bind to (default: 8000)
- `RELOAD`: Enable auto-reload for development (default: false)

## API Endpoints

### Health Check
- **GET** `/health` - Check agent status and readiness

### Agent steps
- **POST** `/model_step` - Make one model call and stream it. See "The step requests" above.
- **POST** `/tool_call` - Run one tool call. See "The step requests" above.
- **POST** `/preload` - The reads of a run that starts a thread. See "The step requests" above.

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
