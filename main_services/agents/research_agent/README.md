# Research Agent API

A FastAPI-based research agent with MCP (Model Context Protocol) tool integration, providing streaming chat capabilities for research assistance.

## The agent profiles

One image serves two chat profiles with different tools.
`internal_search` uses collection and conversation tools.
`full_research` can also use internet tools.
The worker selects the profile from the conversation's stored internet option.

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

**The prompt holds the role, lists the rest, and the skills teach.** The prompt holds the
role line of the profile and the role text of the run kind, which is the rendered role skill
(`skill_store.role_method`). The run's skills by name and description and the run's tools by
name and summary follow. A chat run then gets the `ask_user` rule and the closing lines rule:
an answer to a request that compares documents or collections ends with a `Disagreements:`
line and a `Not covered:` line, and other answers end without them. The role text of the
chat asks for the same two statements. The served model wrote the lines only when both
texts asked for them. The todo text
follows when the run has the four todo tools. It says
that the list is optional and that an open item does not stop an answer. The summary of a
tool is the first sentence of its description, at most 160 characters. `_create_context`
renders the prompt once for each step context. The prompt cache holds the system text for
the run.

The method text is in `research_agent/skills/`.
Each skill has a Jinja body and front matter with its name, group, description, and tools.
The role skills are `method_chat_full` and `method_chat_internal`.
They define the role's sources and evidence requirements.
The other groups provide search, citation, tool use, and failed-call instructions.
A technique or stumble skill has at most 2,600 characters.
A skill renders a tool name only when the run has that tool.
`tests/test_skill_store.py` verifies skill rendering and tool membership.

The model finds a skill with `search_skills` and reads one with `read_skill` when it chooses
to. The result of a read starts with the line ``Skill `name`.``. A role skill and a skill of
another profile are refused with `unknown_skill`. No run reads a skill before its first
model call.

The model receives each tool's schema with each call. It can read a fuller description
with `read_tool`. The Manticore match syntax reaches the model through the skill `search` and
the descriptions of the search tools. The collection MCP server also renders it into its
`instructions`, which this agent does not pass to the model.

## Tool packs and the catalogue

A tool pack is a named set of tools in `agent_common/tool_packs.py`.
`agent_packs_chat` selects chat packs. Its default is `all`.
The available packs are `catalogue`, `skills`, `collections`, `conversation`, `web`, and `browser`.
Every run receives the `skills` pack.
The prompt lists the tools that the selected packs permit.
The catalogue exposes those tools with their descriptions and schemas.

`tool_args.model_schema` shows it (see [Tool arguments](#tool-arguments)). `read_tool` returns one tool's
description and schema. `search_agent_tools` finds tool names from words in a request.
Both tools provide information and do not change which tools the model can call. The
service returns `tool_unavailable` for a name outside the run's callable tools. The
worker runs the todo calls of a reply in call order, the browser calls of a reply
(`read_page` and every `browser_*` tool, `execution.is_browser_tool`) in call order in a
second chain, and the other calls in parallel.

### The batch result budget and the call measure

The result pages of all calls of one model reply share one target of 24,000 UTF-8 bytes
(`execution.batch_budget`). `/model_step` reserves the empty page of each call first, divides
the rest into equal parts, and gives each call entry its `page_share`. The count of calls
and the size of their empty pages set the shares. The length of the conversation does not,
so no call is refused for the context. When the empty pages alone pass the target, each call
keeps its empty page. `/tool_call` sends the share in the `X-Hoover4-Page-Share` header. The
connections' HTTP client factory (`page_share_client`) adds the header, because the MCP
adapter opens one session for each call. The collection server's page broker sizes each page
within that share, a later page of a stored window included, and divides the share of a
`read_documents` call among the documents that it reads.

A page that the broker stored as a window is read on later pages with the share it was
stored with, when not one unit fits the current share.

The broker returns the `build_page` measure of the page beside the page text, as an embedded
resource. The adapter puts that block in the tool message artifact. `/tool_call` takes it out and
returns it as the `measure` of the response. A tool that is not a broker tool has no
measure.

## The step requests

The worker runs the agent loop in the `AgentRun` workflow. For each model call it sends
`POST /model_step`, and for each tool call of a reply it sends `POST /tool_call`. The service
keeps no state of a run between two requests. Every request carries the run fields of
`StepRun` (`steps.py`): `run_id`, `kind`, `depth`, the caller's identity and
collections, and `llm_model`. The worker sends the plan's frozen model for every run of a
plan.

### `POST /model_step`

The request adds `step_no` (1 for the first model call of the run thread), `thinking` (a
required bool, the admin thinking switch), the run's thread as `messages`, and the earlier turns of the chat as `earlier`
(depth 0 only). `messages[0]` is the opening human message. Each message carries its stored
key, `thread_id` and `idx`. `earlier` holds the stored threads of the earlier chat turns in
full, with their tool calls and results. Every model call binds every tool of the run. A call of an earlier turn that has no result, which
a stopped turn leaves, gets a `not_run` result in the request only. `run_messages.py` applies
the stored `compaction` rows and rebuilds the messages into langchain messages, with the tool
calls and the stored usage, so compaction can measure the thread before the model call.

The response is a stream of `data: {json}` frames, in this order:

| `type` | fields | when |
|---|---|---|
| `reasoning` | `content` | each reasoning delta |
| `response` | `content` | each text delta |
| `compaction` | `state` (`running`), `tokens_before`, `target`, `parts` (1, or 0 when a failed summary of the same prefix is not sent again) | once, before the summary request, when this call compacts its input |
| `model_turn` | `model` (the model that answered), `text`, `reasoning`, `tool_calls` (a list of call entries), `usage` (`input_tokens`, `output_tokens`, `total_tokens`, `reasoning_tokens`, `request_size`, `citation_tool`: whether the call bound `cite_documents`), `summarised`, `compaction` (the version 3 record of this call's compaction, or null) | once, after the reply ends |
| `end` | `model`, `latency_ms`, `usage` (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`) | once, last |
| `error` | `error_class`, `retryable`, `content` | in place of `model_turn` and `end` |

`error_class` is `read_timeout`, `connect_error`, `http_<status>`, `context_size`,
`context_preparation` or `other`. `retryable` is false for an HTTP 4xx status other than 408
and 429, and for the two context classes (see
[Context compaction](#context-compaction-agent_compaction_fraction)). `summarised` is true
when a summary replaced older steps of this call's input. The worker then adds the summary
notice to the answer.

A call entry is one call of the reply as the service classifies it:

| field | meaning |
|---|---|
| `id` | the call id. An id that is empty, repeated in the reply, or used by an earlier `ai` message becomes `call-{step_no}-{position}` |
| `name`, `args` | the call, with its arguments after `tool_args.normalize_arguments`. Damaged arguments stay as the model wrote them |
| `argument_repairs` | one line for each change that the normalization made |
| `argument_error` | set when the model client could not read the arguments as JSON (`steps.unreadable_call`). `args` is then empty |
| `kind` | `ordered` for the todo tools, `parallel` for every other call |
| `page_share` | the call's share of the batch result budget, in bytes |
| `retry` | false for each browser tool that can change the page: every `browser_` tool except the reads in `steps.BROWSER_READS`. The worker gives such a call one attempt |

While no frame is ready, the stream sends the SSE comment line `: keepalive` every 30 s
(`KEEPALIVE_SECONDS` in `steps.py`). One model call can wait longer than the worker's 300 s
read timeout of the stream, and each comment line restarts that timeout. A reader of
`data: ` frames skips the comment lines. A client that closes the request stops the model
call.

### `POST /tool_call`

The request adds `call` (the `id`, `name`, `args` and `argument_error` of one stored call entry),
`page_share` and `idempotency_key`. The service sends the key to the MCP server as
`X-Hoover4-Idempotency-Key`, so a retried plan mutation changes the plan tree once. The
response is JSON:

| field | meaning |
|---|---|
| `tool_call_id`, `name` | the call |
| `content` | the result text that the model reads |
| `status` | `ok` or `error` |
| `error_class` | empty for `ok`. For `error`: `tool_error` (the tool raised or marked its result as an error), `tool_unavailable` (a name outside the run's tools) or `invalid_arguments` (damaged or unreadable arguments, or arguments that do not match the schema). A stored result of an older run can hold `budget_exhausted` |
| `measure` | the call measure of a broker tool, or `null`. When `/tool_call` changed the arguments itself, `argument_repairs` lists each change. A call that `/model_step` normalized holds its changes in its call entry |
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
page and a result with no failure get no sentence.

**The arguments are normalized before the call.** `/tool_call` runs the normalization of
[Tool arguments](#tool-arguments) again, which changes nothing for a call that `/model_step`
normalized, and then validates the arguments against the tool's own schema.

### The size of a request

Before each model call, `/model_step` measures the whole request (`request_size.py`): the
system text, the schemas of the bound tools, and every message of the list that the model
receives, with the tool results that the worker stored after the previous reply. The billed
tokens of the previous reply do not include those results, so they are telemetry and not
the size of the next request. With a known context window, the served tokenizer
(`POST .../tokenize`) counts the text, and each message adds 8 tokens. When the window is
unknown or the tokenizer fails, the size is an estimate from the ratio of tokens to
characters that the newest billed call gives. A failed tokenizer is not asked again for
300 s. The safe input is the window less the output reserve. The reserve is
`AGENT_MAX_OUTPUT_TOKENS` when it is set, because the request sends the same cap, and an
estimate of 8,192 tokens otherwise. `model_turn` carries the size as `usage.request_size`:
`tokens`, `method` (`tokenizer` or `estimate`), `model`, `window`, `window_known`,
`output_reserve`, `reserve_source` (`configured` or `estimate`), `safe_input`, `fits`, and
`error` when the tokenizer failed. A compacted call records the size after the compaction
and the size before it (`before_compaction`). A request above the safe input is not sent.
The stream sends an `error` frame (see "The failures" under context compaction).

## Per-chat and per-run browser sessions

`X-Hoover4-Chat-Session` carries the chat session id alongside the ACL headers. It grants
no authority. It is an **isolation key**. `hoover4-mcp-browser` uses it to give each
conversation its own Chromium browser context, so cookies and storage from one chat do not
follow the next one. A step request also sends `X-Hoover4-Agent-Run` with the run
id, and the browser server then keys the browser by the run. The chat session stays the
key for citations and artifacts. The todo server keys each list by conversation session. Sessions are dropped when
the chat ends, or after `BROWSER_SESSION_IDLE_SECONDS` (1 h) idle. See
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

## The end of a run

The model decides when it is finished: a reply with no call is the answer. The worker adds
no todo round. The service skips a repeated successful search or read while its complete result remains in model input. Its limits are the step limit of the run and one retry
after a reply with no text and no call. At a limit, the worker ends the run with a result
that code writes from the stored thread, and it sends no further model request. See
`processing/tasks/Readme.md` for the loop.

## Context compaction: `AGENT_COMPACTION_FRACTION`

A run grows because every result that it collected stays in the list of the next model call.
`research_agent/compaction.py` compacts the list when the measured size of the next request
(see "The size of a request") reaches the trigger, a fraction of the model's stated context
window. The trigger is never above the safe input, the window less the output reserve. It
plans the list to a target of a third of the trigger before the next model call, and
replaces one older prefix of steps with one summary.

| variable | default | meaning |
|---|---|---|
| `AGENT_COMPACTION_FRACTION` | `0.80` | fraction of the stated window at which compaction fires. Out of range, or unparseable, turns compaction off |
| `LLM_MODEL_COMPACTION` | the answering model | model that writes the summary |

For a window of 262,144 tokens at 0.80, the trigger is 209,715 tokens and the target 69,905.

**The parts of the list.** `plan_compaction` plans, in list order, with no model call:

1. **The user's messages.** Every `human` message that is not a record stays in its place:
   the request, the clarifications and the notes that the worker writes. With the system
   text and the tool schemas they are the fixed input.
2. **The summary.** One `human` message takes the place of the first message of the older
   prefix that it replaces. The prefix holds complete step groups (an `ai` message with all
   its results) and the previous summary, so a new summary extends the previous one.
3. **The recent steps.** The largest suffix of complete step groups that fits the target
   with the fixed input, the index and a summary of 2,000 tokens. The newest group always
   stays, with every result of its calls.

A step group leaves the list whole or stays whole, so no call loses its result. A
`read_skill` or `read_tool` result in the prefix never reaches the summary model. The index
names it, and the model can read it again.

**The token estimate.** The plan sizes are estimates. `Estimator.calibrate` divides the
billed prompt of the newest billed call by the characters of the list that it sent, the
system text and the tool schemas included, and clamps the ratio to 1/6 to 1/1.5 tokens a
character. Each size gets a margin of 5 percent. `request_size.measure` uses the same
estimate when the tokenizer does not count.

**The summary.** It starts with `RECORD_HEADER`, which tells the model to read a source again
before it quotes it. Code writes the lists next (`thread_index.py`): the searches that found
nothing, the searches that found documents with their counts, the documents read with their
pages, the citation labels with their file hashes, the pages that `read_page` read with
their source versions and unread continuation offsets, the result pages that continue with their `more`
handle and call, and one line that names the skill and tool texts that left the list. The model never writes those lists, because a summary model copies
file hashes with errors. The summary model writes the rest with thinking off, in one request
with a completion cap of 2,000 tokens, in four sections: findings with their sources,
contradictions, outstanding work, and the identifiers that read a source again. The model
writes each finding with an exact quote and its source. A cut page is read through its shown
text. Its continuation stays unread. The summary request presents page results last, with
their stored step numbers and call inputs. A find with no match is not a content read.
The model
writes the source of each quote in brackets, `[source: ...]`. When a document or page text of
the replaced steps holds the quote and the bracket names another source, code writes the
source of that text in the bracket (`attribute_quotes`), and the record counts the changes in
`sources_corrected`. A quote that no read text holds keeps its bracket. The summary
request must fit the window of the summary model. When the prefix passes it, each larger
result goes to the request as a bounded extract of its start and its end, with a line that
gives its full length. The summary request has the read timeout of a model call. Before the
request, the stream sends one `compaction` frame, and it sends keepalive lines while it runs.

**The failures.** No failure edits the stored thread.

* After compaction, the service reduces the largest newest tool results until the request fits.
  The collection broker stores each complete result under an identity derived from the run and call.
  A reduced view contains the first window and a `read_more` continuation.
  The worker persists each view before it stores the model reply.
  The transcript retains complete evidence and document identities.
* A failed summary changes no older message. The service can still reduce newest results.
  When the request still exceeds the safe input, the stream returns `context_preparation` after a failed summary.
  Other requests that remain too large return `context_size`.
* When the provider refuses a request as too large before any output, `/model_step` reads
  the model's window again, uses the limit that the refusal states when it is lower, and
  prepares the request once more with a compaction under the trigger. It sends the new
  request only when it differs from the refused one.

The worker does not retry these error classes, and the run ends with the text of the error.

**The compacted list is kept.** `model_turn` carries `compaction`, a version 3 record:
`status` (`ok` or `failed`), `source`, the keys `[thread_id, idx]` of the prefix that the
summary replaces, `retained_from`, the key of the first message that stays, the record text
as `summary`, `error`, `tokens_before`, `threshold`, `target`, `est_after`, `target_reached`,
`steps_summarised` and `sizes` (the fixed input, the user messages, the retained steps, the
index, the summary, the summary request, the list after, and the count of extracts). The
worker stores it as a `compaction` row after the `ai` message of that call. Each later call
applies every stored row first (`run_messages.apply_compactions`, which also reads the version
1 and version 2 rows of older threads), and then measures the request.
`finish_compaction` builds its own list with `run_messages.apply_record`, so a replay of the
row gives the list that the call sent.

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

**A compacted turn says so to the user.** The answer was written from a summary and not from
what the agent read, so the worker adds one line to the answer (`summarised` of
`model_turn`). A failed summary sets no such line.

**The notes tool.** `note_tools.py` gives the tool `write_note` (`text`, 1 to 2,000
characters). It returns `{"saved": n, "note": text}`, where `n` counts the notes that the
step context of the run saved. It is in the `skills` pack. A note in the prefix goes to the
summary request, and the summary prompt asks for each note.

Every compaction writes a `chat_compactions` row: the record whole, the citation handles in
the list, the list after, the trigger and its window, and the token counts before and after.
The "after" is the prompt of the call made on the compacted list, so it arrives with the
second insert under the same compaction id.

## Tool arguments

**The schema that the model is shown.** The chat template of the served model renders each
tool parameter from its `type`. It renders a parameter with `anyOf` or `oneOf` with an
empty type, and it drops the item schema of such a list. `cite_documents` takes
`list[Citation] | str`, so the served model saw no field names and sent invented keys such as
`document_id` and `find_phrase`. `tool_args.model_schema` gives each such parameter one
branch: an optional parameter loses its `null` branch, a list or an object loses the string
branch that the server accepts only as a tolerance, and of several scalar branches the
string branch stays. It copies each local `$ref` into place and keeps the description and
the default. `/model_step` binds the tools with these schemas (`steps.shown_tool`), and the
request size counts them. Every argument is still validated against the tool's own schema.

**The normalization.** `/model_step` normalizes the arguments of each call to a tool of the
run before it classifies and returns the call (`classify_calls`), so the stored call, the
worker's readers of it, such as the question of `ask_user`, and `/tool_call` see the same
values. `tool_args.normalize_arguments` runs three steps. A second run on its result changes
nothing.

1. `repair_arguments`. The tool call parser of the model server can leave the model's string
   delimiter `<|"|>` in a key or a value, a quote on a key (`id"`), or one layer of quotes
   around a one-word value. The repair removes a delimiter at the start or the end of a key
   or value, the quotes of a key, and that one layer, and keeps the quotes of `query`,
   `queries`, `quote` and `find`, because a phrase search needs them.
2. `rename_aliases` renames a key that the model wrote under another name, such as
   `collection` for `collectionname`, when the tool's schema has that name.
3. `decode_string_arguments` reads the parameter's JSON schema, following `anyOf`, `oneOf`,
   `$ref` and `type` lists. A string that parses as JSON becomes the parsed value, if that
   value has an allowed type. For a boolean, `true` and `false` in any case become the
   boolean. A single value, or the JSON value of a string, becomes a one-item list when the
   parameter takes a list and the value is a valid item: `3` and `"3"` become `[3]` for a list
   of integers, and `"2024"` becomes `["2024"]` for a list of strings. `null` and an empty
   string are never an item.

The MCP servers validate arguments with pydantic in lax mode, which converts `"True"` and
`"5"` and refuses a string for a list or an object. `_create_context` wraps every MCP tool
with `with_decoded_arguments` (`agent.py`), which runs the same normalization.

Known parser damage repairs missing key quotes, structural key prefixes, merged query values, and delimiters inside query text.
Named arguments inside a collection list move to their schema fields.
Unrepairable JSON reports its damage position.

**Refused arguments.** The normalization preserves values and refuses ambiguous damage.
It never turns a list into a single value or makes several calls from one.
`/tool_call` refuses these calls with `invalid_arguments` and a message that names the
reason, and the stored call keeps the arguments as the model sent them:

- A delimiter inside a key or a value outside query text, or a repaired key that holds a space or
  one of `,:{}[]`. The parser split the call in the wrong place, so no value of it is
  certain.
- Two keys that become one key with different values, and an alias beside its name with a
  different value. The same value twice gives one key.
- A call whose argument text remains invalid JSON after key repair. `/model_step` keeps it as a call with no arguments and an
  `argument_error` that holds the start of the text, so the reply does not count as a reply
  with no call.
- A reply with no parsed call whose text holds the served model's call syntax (`<|"|>` or
  `<|tool_call>`). The model or the parser failed, and the text is not an answer.
  `steps.leaked_call` keeps it as one call with the name from `call:NAME{`, else
  `unnamed_call`, with no arguments and the text in `argument_error`.

The validation message names each problem with its path. For a value that matches no branch
of a choice, it reports the problems of the branch that the value's type matches: for a list
of objects, the missing required keys, the keys that the schema does not name, and the keys
that it names. A list sent for a single value gets "takes one string value, and the call gave
a list of 14 items. Send one value."

**The served parser.** `tests/producer_fixtures/gemma4_tool_calls.json` holds calls of the
served model: the raw text where it was captured, the parse that the model server gave, and
the cause. The parser is the `gemma4` tool parser of vLLM (`vllm/parser/gemma4.py`) in the
serving image, and this repository holds none of its code. Two cases are defects of the
model's output: an empty value written with one delimiter, and objects written with square
brackets. For a malformed call like these, the streamed parse can also give an argument text
that is not JSON, because the parser streams a prefix of its partial parse and does not
correct it when the final parse differs. The agent refuses each of these calls with its
reason.

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
- `LLM_MODEL`: Model name to use when a request has no model. A request fails with a clear
  error when it has no model and this value is empty.
- `LLM_TEMPERATURE`: Temperature setting (default: 0.0)
- `LLM_SEND_TEMPERATURE`: `false` leaves `temperature` out of every model request: the agent
  turns and the compaction summary. `deploy.py` renders it from the active provider's
  `send_temperature` key. Empty or unset is `true`. `research_agent/model_params.py` owns
  the rule, and the worker's title request mirrors it.
- `AGENT_MAX_OUTPUT_TOKENS`: the output cap of every agent model request, which the model
  client sends as `max_completion_tokens`. It is also the output reserve of the request size.
  Empty sends no cap, and the reserve is then an estimate. The compaction summary keeps its
  own ceiling.
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
