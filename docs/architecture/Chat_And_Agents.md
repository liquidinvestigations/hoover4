# Chat and agents

The chat turn end to end: what is fixed when a conversation starts, which agent answers,
how an answer streams back, how citations work, and what the admin views over it show.

The agents themselves and their tools are `main_services/agents/README.md`; the pipeline's
durable research path is `main_services/processing/tasks/P_agent/`.

## Contents

- [The internet option stays fixed](#the-internet-option-stays-fixed)
- [Reaching the agents](#reaching-the-agents)
- [Citations, and why they are not the search cards](#citations-and-why-they-are-not-the-search-cards)
- [Chat checks](#chat-checks)
- [Streaming a turn](#streaming-a-turn)
- [Timeouts and retries](#timeouts-and-retries)
- [Naming a conversation](#naming-a-conversation)
- [Admin: live chats](#admin-live-chats)
- [Admin: the inline SVG charts](#admin-the-inline-svg-charts)
- [Language-model access](#language-model-access)
- [Allocating a message sequence](#allocating-a-message-sequence)
- [Tool-event payload shapes](#tool-event-payload-shapes)

Routes (see `website/frontend/src/routes.rs`):

- `/ai_chat`, homepage ("What are you researching?") with recent-session cards and composer
- `/ai_chat/history`, full conversation list
- `/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state`, transcript + document preview (60/40)

Storage lives in the global ClickHouse database: `chat_sessions` (migration `00011`) and
`chat_messages` (`00012`), plus `chat_message_stream` (`00018`) for in-flight output. The
tool payload columns (`tool_input` / `tool_output` / `doc_refs` / `created_ms` /
`agent_duration_ms`), `retry_errors`, the per-message `model`, the session `summary` and
the frozen option flags are all declared in those two `CREATE TABLE`s. The migration set
is collapsed, so do not look for them in `ALTER` files of their own.

`retry_errors` is written by nothing today: retries are Temporal's and it does not report
a per-attempt error to the row's writer. The column and the disclosure that renders it are
kept because a future writer would want exactly that shape, and an empty column renders
nothing.

## The internet option stays fixed

The first message stores `use_internet_tools` and locks the session options.
The composer then shows the stored option above the transcript.
The internet option defaults to on.

## Reaching the agents

The worker selects the agent from the stored internet option.
It sends turns with internet tools to the full research agent.
It sends other turns to the internal search agent.
The agent service names remain unchanged.

The same switch also picks the **model**. Each agent profile has a `server_settings` key
of its own (`llm_model_internal_search`, `llm_model_full_research`,
`llm_summarization_model`) resolved by `admin::llm::model_for_profile`. **Unset means
"use `llm_default_chat_model`"**, and an empty string is the same as unset, so a deployment
that never touches these keys runs one model everywhere. They exist because the profiles make
different demands: one binds four tools and reads a handful of
passages, the other binds thirty and reads the open web, and the summariser writes a chat
title. Without it the only way to make one faster is to change the model for everything.

A model the user picked in the composer still wins over the profile's: the key configures
the deployment, not the conversation.
The worker uses `llm_default_chat_model` for a request without a model. If that setting is
empty, it uses the configured `LLM_MODEL` value, as the website does. It gives an error
when both values are empty. The agent service also requires a selected or configured
model, and it does not insert a model id of its own.

**`llm_models.supports_tools` is `0` for every row**, and nothing populates it, so nothing
checks that a model chosen here can call tools at all. Choosing one that cannot produces a
turn that answers without ever searching, which reads as a bad answer rather than as a
misconfiguration.

## Citations

`cite_documents` identifies the documents that support the answer.
Search cards show the search results inside tool groups.
Citation cards appear at their references in the answer.
Tables show each source card after its cited row.
Document cards contain the matching source excerpt.
The search-term line links to the originating query with the cited document selected.
The line is absent when stored traces cannot identify that query.

Each citation carries a handle (`[D1]`, `[D2]`) allocated per chat **session** by the
collection-search MCP server, so a handle from the first turn still resolves in the ninth.
The server stores each new handle as an artifact before it returns it, so a restart of the
server keeps the numbering. When an answer or a question uses a label that no successful
citation result of the session gives, or a label that results give for two documents, the
worker asks the model for the citations and the answer again. A quote that is not in
the text stays unverified, and the result gives an exact passage of the text near it.
An unlabeled answer also gets that round after a successful document read, even if the
answer does not name the file. A question without a citation label gets no citation repair.
A verified absence answer needs no source handle. The worker checks the revised answer before it replaces
the earlier answer. It retains the earlier answer with a notice when the reply contains
raw call text or a label that does not resolve.
Each answer stores citation status in its usage metadata.
The interface omits redundant status prose.
A turn gets at most two repair rounds after its first draft.
The answer of the last round is published without a notice when findings remain.

The citation check uses tool evidence from the current and earlier turns.
It excludes earlier repair notes.
The web repair requires search discovery, successful page reads, and `cite_pages` references.
It identifies bare source URLs, unread pages, and undiscovered pages.
It requires verified item identities and each requested constraint.
It requires merged duplicates and fewer items when sources are insufficient.
It verifies each list item separately, so a sibling citation cannot cover an uncited claim.

`read_page` stores successful Markdown under the owner and chat session.
`cite_pages` verifies exact supporting terms against that captured text.
Its `[Wn]` handles identify source versions and survive browser service replacement.
Unread pages and absent terms return individual errors.
Case differences return literal source terms for an explicit retry.
The failed call allocates no handle and keeps exact matching unchanged.
Web cards show linked titles, domains, and source quotes.
They open the captured Markdown in a side pane with exact find and match navigation.
The preview and find state survive URL reload.
The existing artifact access check protects captured text.
Bounded web read and citation results remain complete in the stored transcript.

The worker stores the typed evidence of each tool result beside it: the reads with their
spans, failed items, citations, notes, and artifacts.
Table row windows and cell text count as document reads. Table metadata and search results
count as discovery. A page find with no match does not count as a content read. The read
record keeps its source version and unread continuation when the page gives them.
`markdown_text.rs` renders bare document and web handles as controls that scroll to their cards.
Repeated references resolve beside their claim within the answer.
A Markdown link remains a link.
Superseded answers remain inside collapsed tool groups.

**A quote that does not verify is shown, marked, never dropped.** A model that stops citing
is a worse outcome than a citation the reader can see is unverified.

De-duplication of document cards is **within a group and never across one**. A search card
and a citation card for the same document are two different statements about it, and
collapsing them would hide that the agent chose one of the things it found.

## Chat checks

The worker runs chat checks at three events of a turn: the turn start, each completed tool
batch, and each answer draft. The `control_event` activity runs them. `AgentRun` keeps the
order of model steps, tool calls and checks.

A definition lists the rules of a profile. Each rule names a handler, an event, a frequency
and its parameters. Handlers are trusted Python modules. The folder
`tasks/P_agent/control/handlers/` holds the built-in handlers. The `chat_control_dir` key of
`[main_services]` can add a read-only folder with more handlers and definitions. When a turn
starts, the worker stores a copy of its assets on the opening row of the run. The copy holds
the definition, the digest of each handler file, the rendered system prompt and the skill
texts. The turn uses that copy until it ends, so a later change affects new turns only.

For each event the worker stores one decision before it writes any row of it. A retry reads
the stored decision and writes the same rows at the same keys. An action is a note, a skill
load or a tool call. Skill loads and tool calls run as a policy batch before the next model
step. The batch uses the normal tool path and the permissions of the run. The transcript
labels each row of a policy batch.

The checks ask the structured server of the selfhosted model (`CHAT_CLASSIFIER_URL`).
No other route receives chat content. A failed or absent route makes the answers unknown,
and the turn continues as it would without the check. Scores are recorded at full
precision. They are not calibrated probabilities.
Cancellation preserves completed request samples without applying policy actions.

The built-in definition has these rules:

- At the turn start, the preparation check classes the request sources. It scores the
  listed skills and the request constraints, and loads at most three skills in 15 seconds.
  It uses bounded context from the last two ended turns to resolve references in a follow-up request.
- After a tool batch, a result that needs the table, email or citation method loads that
  skill. A skill text that is still visible to the model is not loaded again.
- After a web search batch of the model, the worker reads the unread result addresses in
  search-rank order. It uses one `read_page` call of at most six addresses.
- A short page capture with no article text gets a note that names the page.
- A reply that reads one page while two or more search results stay unread gets one note.
- An answer drafted before any source read, in a turn that needs documents or web sources,
  gets one note that asks for reads first.
  A verified citation from an earlier turn also meets this read condition.
- Each answer draft gets the citation check and a check for bracketed source names that
  no citation returned. It also gets semantic checks of support, names and explicit
  requirements, which are recorded. All findings that start a round go into one correction note. The semantic
  checks do not start a round.

An absent-name note requires the person's choice before the agent searches a suggested spelling.
Without web tools, preparation records whether the request asks for public sources, including past events.
A public-source request gets the unavailable-access note without document-search guidance.
The chat system prompt requires the name choice before candidate searches and the capability explanation before the answer.

## Streaming a turn

**Every turn is a Temporal workflow, and the website holds nothing open.** `send_message`
takes the session's **turn lock**, writes the user row, reserves the answer's `seq` as an
empty stream row, dispatches `AgentRun` to `chat-queue` and returns the transcript
*including* the message just sent. The start sends the ids of the turn and no text, and it
rejects a duplicate workflow id. Temporal answers a duplicate with HTTP 409, which the
website counts as started. The model call runs on `chat-model-queue`.
Each tool call runs on `agent-tool-queue`.
The worker stores the model thread and transcript rows in ClickHouse.
The page reads persisted rows through `chat_poll`.
When a turn ends, the page refreshes all its rows once.
This receives earlier tool results and citation metadata that incremental polling can miss.
The agent run sweep closes running rows whose workflows have ended.


## Timeouts and retries

A turn is bounded twice, and the two bounds do different jobs.

**The activity** gets `start_to_close` 900 s and a 60-second heartbeat, much shorter than a
research run's 2 400 s and 10 minutes. A chat turn somebody is watching that has produced
nothing for a quarter of an hour is wedged, and failing it hands the answer slot back to
them.

**The heartbeat timeout and the stall window above are one pair.** The heartbeat timeout is
how long a dead worker goes unnoticed; the stall window is how long the page waits before
telling the user so. The page must never give up first: the interrupted marker's advice is
to ask again, and Temporal reschedules the activity on its own, so a page that gave up
early would earn the user the same answer twice from two workflows. 180 s against 60 s
leaves the reschedule 120 s to be noticed, picked up and write its first row. Both numbers
carry that reasoning where they are declared.

**The agent connection** is bounded by *silence*, not by duration: the worker's read
timeout is the longest gap between two bytes, and there is a separate absolute ceiling for
an agent that loops forever while still emitting events.

**A total-request timeout is the wrong bound for a streamed run**, and getting this wrong
is expensive to diagnose. A healthy internet-tools turn is a dozen provider calls at
50–120 s each; cutting it at a total makes the client report a body error whose message is
indistinguishable from a corrupt stream, while the agent, which never learns the reader
left, keeps working for another quarter of an hour and writes a full set of `ok = 1` rows
into `llm_call_events`. Log the error's whole cause chain and its timeout flag, never the
message alone.

Retries are Temporal's: the agent activity gets two attempts, and a worker that dies
mid-turn does not consume one. The activity is rescheduled on whichever worker picks it
up, which is the durability the whole shape exists for. A turn that ends in an error
writes an `error` row into the transcript *and* logs at ERROR with the session and the
turn uuid. A failure whose only record is a row in `chat_messages` is a failure nobody
finds while the user is asking why the assistant stopped answering.

## Naming a conversation

The first turn writes a provisional title from the user's own words, and the workflow then
asks the LLM for a better one. **It cannot fail the turn**: the answer is already written
and read by the time it runs, so it gets one attempt, a short timeout, and every exception
swallowed on both sides of the call. The provisional title is the fallback and doing
nothing is the correct failure.

Naming a conversation is not a reasoning problem, and a reasoning model given one spends
its whole token budget on the thought and returns nothing usable. The request therefore
carries a hint asking the model to leave its thinking mode off. Sent as a hint and dropped
on a refusal, because a provider that has never heard of it rejects the whole request and a summariser
that fails on every call is exactly what the telemetry row exists to make visible. Every
outcome, including a discarded answer, writes a row into `llm_call_events` with `ok = 0`:
a model that hits its token limit every time must not look like one that never ran.

## Admin: live chats

`/admin/metrics` lists the agent runs running right now (user, conversation, the internet option, elapsed time) with a **Kill** button. It is a **Temporal visibility query** on
`WorkflowType = 'AgentRun'`, so it is true in both directions across a
website restart: it does not lose the runs that were already running, and it does not keep
listing one whose process died. Each open workflow is one entry. `AgentRun` reads session and turn identifiers from its stored row.

Kill is the same cancellation the user's own stop button sends, so an admin-stopped turn
ends the way a user-stopped one does: with an ending in the transcript rather than a
workflow that vanishes.

## Admin: the inline SVG charts

The events-per-hour bars on `/admin/metrics` and the ETA lines on a collection's
processing page are hand-written SVG, and two traps come with that.

**A `<title>` inside `<svg>` has to be built in the SVG namespace, and `dioxus-html` has
no such element.** It declares `title` in the HTML namespace only (the SVG twin collides
on the Rust identifier and is commented out in that crate), so `title { … }` written
inside a chart is created with `createElement` and lands in the document as an
`HTMLTitleElement`. Inside `<svg>` that is a foreign element: not rendered, not a tooltip,
and no warning on any build. `components::svg_title` declares the missing element by
shadowing the `dioxus_elements` module rsx resolves against, and the charts use
`svgtitle { … }`. The tooltip is the only place a bar's exact bucket timestamp and count
are readable, because the axis deliberately drops the date.

**Keys among SVG siblings are positions, never labels.** Two axis ticks can legitimately
carry the same text (three ticks all read `0s` on a finished pipeline, and the 24 h window
spans 25 hourly buckets so its two ends print the same `HH:MM`), and duplicate keys among
keyed siblings are a `debug_assert` in dioxus-core that kills the renderer on the next
re-diff, then puts *App panicked!* on the next page the operator opens. A release build
does not assert; it re-associates the wrong nodes instead. Both charts key by tick index.

The tick VALUES are chosen so they cannot collide in the first place: the count axis rounds
its top up to an even number, so the half-height rule is labelled with the value it is
actually drawn at rather than a rounded one, and a remaining-time axis whose whole range is
zero draws one baseline tick instead of three that all read `0s`.

## Language-model access

Nothing is provisioned anonymously. Every user is authenticated, no page is reachable
without an identity, and chat access follows from that identity like every other
capability.

A user driving a local accelerator hard is a **resource** question rather than a
permission one, and the chat rate limiter (`backend::api::rate_limit::check_and_record`) is
the control for it: its budget decays the longer a burst lasts, which is what distinguishes
a person working from a loop running.

A new turn is also refused when chat cannot work. `api::chat::gate` closes when no
provider is configured, when a non-self-hosted provider has an empty API key, or when
`chat_enabled` in `server_settings` is false. The composer overlay names which of those
three holds. An in-flight turn is left to finish. The frontend control is a hint. The
backend refuses `chat_send_message` and `chat_start_research` under the same three
conditions.

## Allocating a message sequence

A message's `seq` is `max(seq)+1` with no database-side sequence behind it, so two senders in
one session can pick the same number. Three mechanisms stand behind it, and all three are
required:

* **the session's `db_chat::turn_lock`**, which serialises allocation within this process.
  It is an in-process lock and it is released when the request handler returns. Long
  before the worker writes the answer;
* **`next_seq` counts `chat_message_stream` too**, not only `chat_messages`. Every turn
  allocates its answer seq up front and reserves it as a *stream* row; the transcript row
  appears when the workflow finishes. The lock cannot cover that gap (it went with the
  handler), so a `next_seq` reading only `chat_messages` handed the reserved seq to the
  next send and ReplacingMergeTree silently kept one of the two messages. Both entry
  points also refuse outright while `stream_state(...).active`, which is the same question
  the poller asks;
* **`next_seq` starts a fresh session at 1, not 0.** ClickHouse's `max()` over an empty
  `UInt32` column is 0 rather than NULL, so "no rows yet" and "one row at seq 0" produce
  the same number. Whether a session is on its first turn is read from the transcript,
  never inferred from the seq;
* **`message_uuid`** (migration `00012`), shared by every row of a turn and **read** rather
  than merely written: `db_chat::detect_seq_collision` looks for a second uuid at the seq just claimed
  and refuses the turn if it finds one, so the user resends instead of losing a message. It
  reads without `FINAL` on purpose: `FINAL` collapses away the evidence. **A write-only
  collision detector is worse than none, because it reads as covered.**

## Tool rows

A tool row of the transcript is written twice. `model_step` writes a live row into
`chat_message_stream` for each call of a reply, at the seq it gave the call, with the name
and the arguments as `{"name": "…", "input": {…}}`. `tool_call` writes the finished row into
`chat_messages` at the same seq, with `tool_name`, `tool_input`, `tool_output` and the
document references, and marks the live row final. The name is in the stored call entry,
so a card is labelled while its call still runs.

A row of a policy batch has `origin` `policy` in its `usage_json`. A call that repeats an
identical search or read call of the same reply waits for that call and shows its result.
Its row has `shared_from` with the id of the first call. The transcript shows one label
line above each such row (`ChatMessageItem::call_origin_label`).

`search_collections` hits carry `collection_dataset` + `file_hash` (the
`DocumentIdentifier` key used by the document-preview stack).

Note there is **no tool name on a start event**. It appears only at `output.name` on the
end event, which is why the events have to be paired before a call can be labelled at all.

This format is parsed in two places in the worker, and they must agree:
`P_agent/stream_writer.py` while the turn streams, and `P_agent/trajectory.py` when it is
written into the transcript. A parser that writes the raw event as the message body,
hardcodes the tool name and populates none of the payload columns produces a transcript
that renders as a wall of JSON in a card whose expand panel opens onto nothing. If you
change the shape, change both.

### Search progress and classifier traffic

The turn pins capabilities from callable tools and permitted collections. Rules skip when their required tools are unavailable.
Preparation classifies effort and names. It verifies absent names with indexed counts and suggests a clarification through `ask_user`.
Code also retains names after "folder called", "folder named", "collection called" and "collection named" when the classifier omits them.
A progress decision records distinct keyword sources, empty results, repeated calls, refusals, todo churn and word counts.
Three units raise the note level. A new keyword source resets the current units. The level does not decrease.
The third level requires an answer. Six further model steps end the turn through `write_incomplete` with the search summary.
Classifier signals require measured score thresholds. A failed request supplies no signal.
Each classifier request writes metadata to `systemone_call_events` and traffic to `ai_service_telemetry`.
The admin report reads these rows only when an administrator selects Run report.
