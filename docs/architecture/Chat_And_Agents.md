# Chat and agents

The chat turn end to end: what is fixed when a conversation starts, which agent answers,
how an answer streams back, how citations work, and what the admin views over it show.

The agents themselves and their tools are `main_services/agents/README.md`; the pipeline's
durable research path is `main_services/processing/tasks/P_agent/`.

## Contents

- [The two switches are frozen at the first turn](#the-two-switches-are-frozen-at-the-first-turn)
- [Reaching the agents](#reaching-the-agents)
- [Citations, and why they are not the search cards](#citations-and-why-they-are-not-the-search-cards)
- [Streaming a turn](#streaming-a-turn)
- [Timeouts](#timeouts)
- [Retries](#retries)
- [Admin: live chats](#admin-live-chats)
- [Admin: the inline SVG charts](#admin-the-inline-svg-charts)
- [Guests and language-model access](#guests-and-language-model-access)
- [Allocating a message sequence](#allocating-a-message-sequence)
- [Tool-event payload shapes](#tool-event-payload-shapes)

Routes (see `website/frontend/src/routes.rs`):

- `/ai_chat` — homepage ("What are you researching?") with recent-session cards and composer
- `/ai_chat/history` — full conversation list
- `/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state` — transcript + document preview (60/40)

Storage lives in the global ClickHouse database: `chat_sessions` (migration `00011`) and
`chat_messages` (`00012`), plus `chat_message_stream` (`00018`) for in-flight output. The
tool payload columns (`tool_input` / `tool_output` / `doc_refs` / `created_ms` /
`agent_duration_ms`), `retry_errors`, the per-message `model`, the session `summary` and
the frozen option flags are all declared in those two `CREATE TABLE`s — the migration set
is collapsed, so do not look for them in `ALTER` files of their own.

## The two switches are frozen at the first turn

`Deep Research` and `Internet tools` decide **which agent answers**, and therefore which
tools exist. Changing them mid-thread would produce a transcript where some answers had
web access and some did not, with nothing on screen saying which was which. So the first
message writes them to `chat_sessions` (`use_internet_tools`, `deep_research`,
`options_locked`) and the UI moves them out of the composer to a read-only bar above the
transcript.

The freeze is enforced **server-side** in `db_chat::lock_session_options`, not just by
hiding the checkboxes: later turns reuse the stored values whatever the client sends.

`Internet tools` defaults to **on** (`ChatOptions::default`). The chat is more useful with
them than without, and a user who wants a documents-only answer can untick before sending.

## Reaching the agents

Two services, and **both URLs must be set explicitly in compose**:

| Env | Service | Used when |
|---|---|---|
| `HOOVER4_AGENT_URL` | `hoover4-internal-search-agent` | Internet tools **off** |
| `HOOVER4_FULL_AGENT_URL` | `hoover4-full-research-agent` | Internet tools **on** |

The code defaults (`localhost:21936` / `localhost:21937`) are the loopback ports published
on the *host*, for running the website outside Docker. Inside the container `localhost` is
the container itself. `HOOVER4_FULL_AGENT_URL` being unset is what made every
internet-tools turn fail with `AI agent unreachable at http://localhost:21937` while the
agent itself was perfectly healthy — the same trap as `TEMPORAL_HTTP_URL`.

The same switch also picks the **model**. Each agent profile has a `server_settings` key
of its own — `llm_model_internal_search`, `llm_model_full_research`,
`llm_summarization_model` — resolved by `admin::llm::model_for_profile`. **Unset means
"use `llm_default_chat_model`"**, and an empty string is the same as unset — so a deployment
that never touches these keys runs one model everywhere. They exist because the profiles make
different demands: one binds four tools and reads a handful of
passages, the other binds thirty and reads the open web, and the summariser writes a chat
title. Without it the only way to make one faster is to change the model for everything.

A model the user picked in the composer still wins over the profile's: the key configures
the deployment, not the conversation.

**`llm_models.supports_tools` is `0` for every row**, and nothing populates it, so nothing
checks that a model chosen here can call tools at all. Choosing one that cannot produces a
turn that answers without ever searching, which reads as a bad answer rather than as a
misconfiguration.

## Citations, and why they are not the search cards

`cite_documents` is the agent's own claim about which documents its answer rests on. The
search cards under a tool disclosure are everything a search returned; the **Sources
strip** beneath an answer is what the agent chose, and rendering the first in place of the
second is what turns an answer into a pile of links.

Each citation carries a handle — `[D1]`, `[D2]` — allocated per chat **session** by the
collection-search MCP server, so a handle from the first turn still resolves in the ninth.
`markdown_text.rs` renders a bare `[Dn]` in the prose as a chip that scrolls the strip's
entry into view and flashes it; `[D3](https://…)` is still a link, because the handle arm
only fires when no `(` follows the `]`. The anchor id is minted by `source_anchor_id` and
read by the strip — one function, because two spellings would scroll to nothing silently.

**A quote that does not verify is shown, marked, never dropped.** A model that stops citing
is a worse outcome than a citation the reader can see is unverified.

De-duplication of document cards is **within a group and never across one**. A search card
and a citation card for the same document are two different statements about it, and
collapsing them would hide that the agent chose one of the things it found.

## Streaming a turn

`send_message` does not hold the request open for the agent run. It takes the
session's **turn lock**, writes the user row, registers the run and spawns the turn, then
returns the transcript *including* the message just sent. The turn consumes the agent's
`/chat/stream` SSE feed and mirrors it into `chat_message_stream`; the page follows it
with `chat_poll`.

The lock is `try_lock`: one turn at a time per session, and a second send is refused with
a message rather than blocking a request for the length of an agent run.

| Piece | Where |
|---|---|
| stream consumer | `api::chat::agent_client::ask_agent_stream_once` |
| fold into rows | `api::chat::handle_stream_event` + `TurnState` |
| stream table I/O | `db_chat::{append_stream_row, read_stream_rows, mark_stream_final}` |
| long-poll | `api::chat::poll_chat`, `RateLimitKind::ChatPoll` |
| Temporal twin | `main_services/processing/tasks/P_agent/stream_writer.py` |

Three rules that are easy to break and hard to notice:

- **`read_stream_rows` aggregates in a subquery.** `max(updated_at) AS updated_at`
  shadows the column, so sibling `argMax(…, updated_at)` calls become aggregates inside
  aggregates (`Code: 184`); but `clickhouse::Row` also matches columns **by name**, so
  the aliases cannot simply be renamed. Aggregate as `last_*` inside, rename outside.
- **Liveness comes from the transcript, not from an open stream row.** `ChatPollResult`
  carries `active`, computed from `db_chat::turn_boundaries` — a turn is open while the
  last user row has no assistant/error row after it. The writer finalises one row and
  opens the next as two separate inserts, so a poll landing in that gap sees no open stream
  row for a turn that is still running. An inline turn's `live_runs` entry masks that;
  a durable research turn has none here, and a poller trusting the stream row drops out of
  its loop seconds in.
- **A turn always keeps exactly one non-final stream row open**, from before the agent
  call until finalisation. That is what the interrupted detector points at: a process
  killed with nothing open leaves a transcript that just stops, with no marker.

Poll cadence: holds up to 15 s when nothing changes, and every poll after the first takes
at least 500 ms — with content flowing each poll returns immediately, so without that
floor the client spins as fast as the network allows. Concurrently-held polls are capped
per user (`MAX_HELD_POLLS_PER_USER`).

**Rate limiting a poll loop is not rate limiting a person.** `RateLimitKind::ChatPoll` has
a *flat* window ladder — factor 1.0 everywhere, unlike chat messages and API calls, whose
budget decays the longer a burst lasts. That decay distinguishes a burst of human activity
from an hour of it; a streaming turn polls at the 500 ms floor for as long as the model
generates, so for this limiter "sustained" is simply "working". Under a decaying ladder
one tab sits exactly on the one-hour window's ceiling and two or three trip it, at which
point the page declares the chat lost mid-turn. The refusal is
also typed — `rate_limited:<secs>`, parsed with `chat_types::rate_limited_seconds` — so the
poll loop waits and retries instead of counting it toward `failures >= 3` and declaring
"lost contact with the chat" while the turn is still running. The parser searches for the
marker rather than stripping a prefix: `ServerFnError` may wrap the message.

Stop and interruption: the composer's stop button calls `live_runs::request_cancel_for`;
the turn notices within 200 ms and finalises whatever partial exists with an explicit
marker. A turn whose rows stop advancing for `CHAT_STREAM_STALL_SECONDS` (default 60)
with no live run behind it renders as **interrupted** with a Dismiss button — never a
spinner, and never promoted into `chat_messages`.

Deep research streams through the same table. `start_research_task` writes an empty
stream row when it accepts the task (the only thing that tells the poller a turn exists
before the worker picks the activity up) and the activity rewrites that seq, keepalive
included.

## Timeouts

The agent connection is bounded by **silence**, not by duration:
`HOOVER4_AGENT_TIMEOUT_SECONDS` (default 300) is a `read_timeout` — the longest gap
between two bytes — and `HOOVER4_AGENT_TOTAL_TIMEOUT_SECONDS` (default 1800) is the
absolute ceiling for an agent that loops forever while still emitting events.

**A total-request timeout is the wrong bound for a streamed run**, and getting this wrong
is expensive to diagnose. A healthy internet-tools turn is a dozen provider calls at
50–120 s each; cutting it at a total makes `reqwest` report a body error whose `Display`
is `error decoding response body` — indistinguishable from a corrupt stream — while the
agent, which never learns the reader left, keeps working for another quarter of an hour
and writes a full set of `ok = 1` rows into `llm_call_events`. Every log line about a
broken stream therefore prints the error's whole `source` chain and its `is_timeout()`
flag, never `{e}` alone.

## Retries

Each turn gets `HOOVER4_AGENT_ATTEMPTS` attempts (default 4) with exponential backoff from
`HOOVER4_AGENT_RETRY_BASE_MS` (default 2 s, so 2/4/8 s). Retries cover *every* failure
class rather than a curated list — unreachable, 5xx, timeout, malformed body are one thing
from the user's seat, and this stack fails transiently in all four ways.

**Once the agent has streamed anything, an attempt is worth much more.** A replay repeats
every tool call and every provider call the turn has already made, so at most
`HOOVER4_AGENT_STREAM_RESUMES` (default 1, max 2) of the attempts may be spent after the
first event, and only for a transport break the connection caused — a deadline lands in
the same place on the replay and is never retried
(`agent_client::is_resumable_break`). Before a replay the prose already collected is
folded into the reasoning trace, so the second attempt's answer is not appended to half of
the first one's; tool rows keep their seqs and the replay's rows follow them, so the
transcript records both runs.

Failed attempts are kept in `chat_messages.retry_errors` even when the turn eventually
succeeds, and the transcript shows them behind a disclosure. A turn that only worked on
the third try is a healthy answer over an unhealthy agent tier, and that is worth seeing.
The list holds **one entry per attempt including the one that ended the turn**, so it is
labelled by its length and not as "earlier" attempts.

A turn that ends in an error also logs at ERROR with the session, the turn uuid and the
attempt count. A failure whose only record is a row in `chat_messages` is a failure nobody
finds while the user is asking why the assistant stopped answering.

## Admin: live chats

`/admin/metrics` lists the agent runs this website process is holding open right now —
user, conversation, both switches, elapsed time, attempt number — with a **Kill** button.
The registry is in-process (`backend::api::chat::live_runs`), not in ClickHouse: a row
means "this process is doing this work now", and a persisted row would outlive the process
and show an admin ghosts to kill. Cancellation is cooperative — it lands between retry
attempts, and cannot abort a generation already in flight.

Deep-research turns run in a Temporal worker and are **not** listed there; the Temporal UI
owns that view.

## Admin: the inline SVG charts

The events-per-hour bars on `/admin/metrics` and the ETA lines on a collection's
processing page are hand-written SVG, and two traps come with that.

**A `<title>` inside `<svg>` has to be built in the SVG namespace, and `dioxus-html` has
no such element.** It declares `title` in the HTML namespace only — the SVG twin collides
on the Rust identifier and is commented out in that crate — so `title { … }` written
inside a chart is created with `createElement` and lands in the document as an
`HTMLTitleElement`. Inside `<svg>` that is a foreign element: not rendered, not a tooltip,
and no warning on any build. `components::svg_title` declares the missing element by
shadowing the `dioxus_elements` module rsx resolves against, and the charts use
`svgtitle { … }`. The tooltip is the only place a bar's exact bucket timestamp and count
are readable, because the axis deliberately drops the date.

**Keys among SVG siblings are positions, never labels.** Two axis ticks can legitimately
carry the same text — three ticks all read `0s` on a finished pipeline, and the 24 h window
spans 25 hourly buckets so its two ends print the same `HH:MM` — and duplicate keys among
keyed siblings are a `debug_assert` in dioxus-core that kills the renderer on the next
re-diff, then puts *App panicked!* on the next page the operator opens. A release build
does not assert; it re-associates the wrong nodes instead. Both charts key by tick index.

The tick VALUES are chosen so they cannot collide in the first place: the count axis rounds
its top up to an even number, so the half-height rule is labelled with the value it is
actually drawn at rather than a rounded one, and a remaining-time axis whose whole range is
zero draws one baseline tick instead of three that all read `0s`.

## Guests and language-model access

Which users can chat is decided by the deployment's mode, and the same mechanism decides
whether anonymous users exist at all.

**In demo mode** an anonymous visitor is provisioned as a `guest-*` user and may chat, keyed
by that username, with the same persistence as any other user. A visitor driving a local
accelerator is a **resource** question rather than a permission one, and the chat rate
limiter (`backend::api::rate_limit::check_and_record`) is the control for it: the chat
limiter's budget decays the longer a burst lasts, which is what distinguishes a person
working from a loop running.

**Outside demo mode** nothing is provisioned anonymously. Every user is authenticated, no
page is reachable without an identity, and chat access follows from that identity like every
other capability.

## Allocating a message sequence

A message's `seq` is `max(seq)+1` with no database-side sequence behind it, so two senders in
one session can pick the same number. Three mechanisms stand behind it, and all three are
required:

* **the session's `db_chat::turn_lock`**, held for the whole turn, which serialises
  allocation and stops a second turn reading a history the first has not finished writing.
  It is an in-process lock and it is released when the request handler returns;
* **`next_seq` counts `chat_message_stream` too**, not only `chat_messages`. Deep research
  allocates its answer seq up front and reserves it as a *stream* row — the transcript row
  appears minutes later, when the Temporal workflow finishes. The lock cannot cover that
  gap (it went with the handler), so a `next_seq` reading only `chat_messages` handed the
  reserved seq to the next inline send and ReplacingMergeTree silently kept one of the two
  messages. Both entry points also refuse outright while `stream_state(...).active` — the
  same question the poller asks;
* **`message_uuid`** (migration `00021`), shared by every row of a turn and **read** rather
  than merely written: `db_chat::detect_seq_collision` looks for a second uuid at the seq just claimed
  and refuses the turn if it finds one, so the user resends instead of losing a message. It
  reads without `FINAL` on purpose — `FINAL` collapses away the evidence. **A write-only
  collision detector is worse than none, because it reads as covered.**

## Tool-event payload shapes

```
start  {"input": {}, "name": "list_collections"}
start  {"input": {"query": "…", "collections": ["…"]}, "name": "search_collections"}
end    {"output": {"content": …, "type": "tool", "name": "…", "tool_call_id": "…"}, …}
```

`name` on the **start** event is added by the agent (`main_services/agents/research_agent/research_agent/agent.py`);
LangGraph's raw `on_tool_start` data carries only `input`, and the tool's name first
appears under `output.name` on the end event. Without it every card rendered while a call
was still running was labelled "tool".

`search_collections` hits carry `collection_dataset` + `file_hash` (the
`DocumentIdentifier` key used by the document-preview stack).

Note there is **no tool name on a start event** — it appears only at `output.name` on the
end event, which is why the events have to be paired before a call can be labelled at all.

This format is parsed in two places, and they must agree: `api::chat::agent_client` for
inline chat, and `main_services/processing/tasks/P_agent/trajectory.py` for the Temporal research path. A parser that
writes the raw event as the message body, hardcodes the tool name and populates none of the
payload columns produces a transcript that renders as a wall of JSON in a card whose expand
panel opens onto nothing. If you change the shape, change both.
