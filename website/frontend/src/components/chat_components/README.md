# Chat components

UI building blocks for the AI Chat pages under `/ai_chat`.

| Module | Role |
|---|---|
| [composer.rs](composer.rs) | Textarea + **Internet tools** checkbox + send arrow. The checkbox disappears once the conversation has a turn, see below. No paperclip / upload control: documents enter via the processing pipeline. |
| [gate_overlay.rs](gate_overlay.rs) | Non-dismissible overlay over the composer when a new turn cannot start. Names which reason applies: no provider, missing API key, or chat switched off. History stays readable. |
| [locked_options.rs](locked_options.rs) | The internet tools switch shows beside the title after locking, only when the deployment enables it. Its tooltip is "Start a new chat to change this setting." |
| [session_card.rs](session_card.rs) | Homepage / history card showing title + summary. |
| [transcript.rs](transcript.rs) | User bubbles, assistant markdown, tool disclosures, inline doc cards, the retry-attempt disclosure, and the token footer under an answer. |
| [tool_cards/mod.rs](tool_cards/mod.rs) | The card registry dispatches on tool name and provides card chrome, elapsed counters, and JSON helpers. |
| [activity.rs](activity.rs) | The activity line of a turn in progress. |
| [tool_cards/result_cards.rs](tool_cards/result_cards.rs) | Result-page, read, citation, todo call, task summary, plan, question and board fact cards. |
| [tool_cards/web_search_card.rs](tool_cards/web_search_card.rs) | `web_search`: pending → collapsed → expanded result list → the before/after reranking popup. |
| [tool_cards/browser_card.rs](tool_cards/browser_card.rs) | Every `browser_*` tool: action label, capture thumbnails, page text, and the archived page in a sandboxed iframe. |
| [tool_cards/entities_card.rs](tool_cards/entities_card.rs) | `list_document_entities`: the two tiers apart, each rule-validated value a link to its explainer card in the document viewer. |
| [tool_run_summary.rs](tool_run_summary.rs) | The summary line of a run of consecutive tool rows, see below. |
| [tool_disclosure.rs](tool_disclosure.rs) | The **generic** card, and the deliberate fallback: type chip + prose summary, Expand to labelled fields, then a second toggle for raw JSON. |
| [doc_ref_card.rs](doc_ref_card.rs) | Wraps the shared [`SearchResultItemCard`](../search_components/search_result_item_card.rs) for a `ChatDocRef`. Renders `display_snippet()`, not the raw snippet, see below. Loads the file size and the dates of the document with `get_document_card_facts`, because a stored citation holds neither. |
| [conversation_find.rs](conversation_find.rs) | "Search in conversation" bar (an input of at most 350 px, then 0/N and up/down), mirroring the document find box chrome. In a board explore chat it ends with an "Investigation Board" link to the board. |
| [markdown_text.rs](markdown_text.rs) | Markdown → Dioxus nodes for assistant turns. |

The transcript and persisted answer nodes expose stable attributes for browser history verification.
Each finished answer retains citation status and tool scope in metadata.
The interface omits this status prose.
Each source has one card across the conversation, placed at its first visible marker.
Successful citations without markers follow the final answer, before the centered token footer.
Later markers select the source and scroll to its card.
Distinct verified document passages share one card and keep their own find actions.
A web source without a title uses its URL as the linked title.
Opening any captured version selects the shared page card. Each quote opens a search term present in that quote.
Preview find accounts for the display scale when scrolling a match into view.
Three generated follow-up buttons fill the composer without submitting.
The buttons share one row inside a card headed "Suggested next...", beside a small question icon.
Send uses the shared navigation arrow button, including its disabled state and tooltip.
A user message (`UserMessage` in [transcript.rs](transcript.rs)) shows three lines and a "Show" toggle in its top-right corner when its text is longer. The toggle says "Hide" while the message is whole. The answer card at the end of a board explore chat (`BoardFactSummary`) is a link to the board with the turn's fact selected, from the `ChatBoard` context of the session page.
It measures the text on mount and on resize, and opens when it holds the active conversation find match.
A doc card scrolls to the middle of the transcript once per session when it is the selected card at page load.
The shared result card has a pointer cursor and a hover background, except when `data-selected` is `true`.
Every todo call is a tool card inside its group, with its stored arguments, result,
failure, origin label and the list after the call. A task summary shows after the group
of a successful todo call that changed what a reader sees: the goal, the item order and
text, which items are done, their reasons, and replacements. `common::chat_todos` decides
which calls show one. A failed call, a read, a call whose stored list has not arrived and
an identical call show none. A summary ends its group, and later calls start another.
The summary is as wide as its text, at most 80% of the transcript, on the neutral surface
colour, with the task icon in its upper-right corner. A done item is struck through and
followed by the first three words of its reason in bold. The whole reason is the title of
those words and is in the call card.
The reasoning of an answer renders once, inside the group of tool rows directly before
the answer, because stored reasoning of an earlier turn can cover a repair round and names no tool. An answer
with no group before it keeps its reasoning beside it. A superseded answer keeps its
reasoning inside its round's group. The live reasoning follows the group of the live
tool rows, or the stored group that the live answer follows.
The session page shows one activity line, a rotating icon and `The bot is working...`,
while its turn is active and not interrupted. A queued turn adds the slot it waits for
under that line. [activity.rs](activity.rs) holds it.
The transcript root carries `data-chat-turn`, the state of the newest turn: `active`, `queued-model`, `queued-tool`, `interrupted` or `idle`.
A browser test reads the end of a turn from it and from the user message seq (`data-chat-user`).
An answer whose turn wrote a workspace file names it in `report`. The page reads the pinned
versions with the transcript (`reports`), and `with_reports` in [transcript.rs](transcript.rs) puts the report
text in place of the answer text before the citation cards are placed. A line above the
report names the file and version and opens it in the workspace pane
([workspace_pane.rs](workspace_pane.rs)), and the chat text of the answer follows the report in a muted colour.
The pane is read-only, and the address holds its file and version
(`DocViewerState::workspace_file`).
A board explore turn writes a report. The board then writes a `submit_board_fact` row after
the answer, and its card says "Submitted by the board". Under the answer, the board fact
summary (`x-board-fact-summary`) states the kind of the fact and its open questions. An
older explore turn has the call as a card inside the group before its answer.

## Internet access stays fixed for a conversation.

The first message stores the internet option in the session.
The composer then hides its checkbox.
`LockedInternetFlag` shows the stored option in the title row.
The backend enforces the stored option through `db_chat::lock_session_options`.
Internet tools default to on.

## Markdown rendering

[markdown_text.rs](markdown_text.rs) maps markdown to real Dioxus elements: headings, bold/italic, inline
and fenced code, links, tables, block quotes, rules, bullets and numbered lists.

**No `dangerous_inner_html` anywhere.** The input is model output built partly from pages
scraped off the open web, so raw HTML would be an injection sink fed by exactly the wrong
source. Any HTML in the source shows as the text it is, and `[x](javascript:…)` stays
literal text rather than becoming an anchor. The cost is nested lists and quotes-inside-
lists, which a full CommonMark renderer would handle; the trade is deliberate.

A successful `cite_documents` result assigns a handle to a document in the conversation.
The transcript renders each issued handle as a source control.
An unknown handle shows a citation warning.
A handle assigned to two documents shows the conflict and links to neither document.
Live output can show a handle before its citation result arrives.

The heading scale tops out at **body + 3px** (18px against 15px). Chat headings are labels
inside a message, not page titles. A browser-default `h1` at 2em towers over the
conversation. Weight and colour carry the hierarchy instead. A test pins this.

## Group consecutive tool rows.

[transcript.rs](transcript.rs) puts each run of consecutive tool and instruction rows behind one button, and the
button opens the cards of the run. `tool_run_summary` writes the line from rules, for
example `Searched 20 terms, read 8 documents, 2 failed, took 8m12s`. The kinds of call
always appear in one order: corpus search, document reads, web search, web page reads,
browser actions, entities, citations, todo calls, other calls. The
unit of each kind comes from the arguments, such as the queries of a search or the hashes of
a read. The time runs from the row before the run to the last row of the run, so it holds
the model time between the calls. The line always shows the time, and says
`time not recorded` when a row has no time. The live calls of a turn in flight stay as
cards, because a running card shows its own counter. The conversation search opens a run
that holds its current match.

## A registry selects each tool card renderer.

Do not collapse this back into one `match` in [tool_disclosure.rs](tool_disclosure.rs) with a branch per
tool. That shape has a specific failure: the generic branch collects the *newest* tools,
which are the ones whose output is least readable as flat key/value rows. Dispatch lives
in [tool_cards/mod.rs](tool_cards/mod.rs) and the generic card is the deliberate fallback. An MCP server
that adds a tool tomorrow uses the default renderer.

`browser_*` is matched on the **prefix**, not by listing thirty names, so a
playwright-mcp upgrade that adds a tool does not silently drop it into the generic card.

### Validate external links.

The entities card links a value to its explainer card in the document viewer, and the
explainer is fetched with the rule that accepted the value, so a name a model found has
nothing to explain and is rendered as text with a line saying why. The link also needs a
dataset, which that tool does not return: [transcript.rs](transcript.rs) collects `file_hash` to
`collection_dataset` from every tool result in the conversation and hands the map down. A
document nothing named a dataset for keeps its values as text under the reason. Both cases
are visible rather than silent, because a link that works for some values and does nothing
for others is worse than no link.

### Display generic card detail levels.

1. **Collapsed**: a type chip plus a one-line prose summary, never raw JSON.
2. **Expand**: arguments and result as labelled key/value rows, with nested data summarised
   ("8 items").
3. **Show raw JSON**: a second toggle inside the expansion, pretty-printed, for debugging.

An earlier version put level 3 where level 2 belongs, so a card was either a wall of JSON
or (when the writer had not populated the payload columns), empty. Rows written before
those columns existed show the stored summary with a note, instead of a blank panel.

### `web_search`

* **Pending** (streaming, `tool_start` seen, no `tool_result`): the query in quotes, the
  sources it is waiting on, and a seconds counter. A pending search with no counter is
  indistinguishable from a wedged one.
* **Collapsed:** the numbered search forms and the result count.
* **Expanded:** each result's title link, host, matching forms, and snippet.
  The card shows sources that returned no results and the tool's note.
* **Popup:** both orderings side by side, fetched lazily from the web search JSON artifact
  through the `chat_artifact_detail` server function. It shows ranking and timing details
  that the model did not read.

### Document cards

A citation card shows its search term and the matching search passage.
When the citation omits the term, the transcript uses the newest earlier search that returned that document.
The card highlights query words in the passage.
The citation quote and document find phrase remain separate from this search context.
The chat document pane opens when a card opens a document.
Without a selected document, the conversation uses the available width.

The `Search this` link resolves named collections through the permitted storage tree. Its search filter contains dataset IDs. A name with no permitted dataset has no scoped link.
The `read_more` card shows scalar continuation text in page order and keeps the source and part in its title.

A `search_collections` hit carries up to `SEARCH_SNIPPET_CHARS` (1200) characters of page
text and one turn can return a dozen, so `ChatDocRefCard` renders
`ChatDocRef::display_snippet()`, clamped to 400 characters. This is a *display* clamp: the
full text stays in the payload and the card links to the document, which is where reading
it belongs.

**One card per document, not per hit.** The search tool answers with one hit per PAGE:
`page_id` is part of its dedup key on purpose, since two pages are two pieces of evidence,
and the same bytes can be ingested into several collections, so one document arrives as
several rows. `extract_doc_refs` collapses them on `file_hash`, keeps the best-scoring
row's snippet, and gathers the other datasets into `ChatDocRef::also_in`, which the card
renders after the primary one under a CSS width clamp. Without that collapse the same title
rendered three times over and the disclosure's count described page-hits while calling them
documents.

Document cards use `DocRefsDisclosure`, collapsed by default for each tool row.
The summary identifies the tool and document count.
Expand the disclosure to read the result cards.

Text truncation counts Unicode characters and preserves character boundaries.
Extracted content can contain encoded attachments or pixel data.
The card renderer must handle that content even when the pipeline excludes it from vector indexing.

### `browser_*`

`browser_navigate` gets the full treatment; every other action gets a compact row. What
was done, to which element, and the resulting thumbnail. Read as a sequence those rows are
a filmstrip of the navigation, which is what makes a multi-step browse legible.

`status = 'too_large'` or `'failed'` renders as an **explicit line**, never as an absent
element: a capture that silently is not there looks identical to a tool that was never
called.

The popup frames the archived page as `<iframe sandbox="">`. The **empty** value, which is
the strict one; an omitted attribute means no sandbox at all. The response additionally
carries `default-src 'none'`. Both are required: the CSP alone still allows scripts, and
the sandbox alone still lets a stylesheet fetch leak that the capture was viewed.

### Show tool status in collapsed cards.

A card built from the tool's **arguments** describes what was attempted, and most readers
never expand it. Live, a `browser_navigate` that urlcheck refused rendered as "opened
http://clickhouse:8123" and a dead `web_search` as "0 results · 0 sources". The demo
stating as fact something it knew to be false. So every card asks `tool_failure()` before
it writes its header, and a failure turns the whole card red with a `⚠ refused` / `⚠ failed`
pip and the message as its tooltip.

Three signals, because no one of them covers everything:

| signal | where it comes from |
|---|---|
| `{"success": false}` / non-empty `error` | urlcheck refusals, `web_search` errors |
| `"failed": true` in the trailing artifact marker | Playwright's `is_error`, written down by the browser router |
| a first line starting `Error:` | Playwright prose, when there is no marker |

Only the **first** line is examined for that last one. The rest of a browser result is the
fetched page, and a page whose body contains "Error: 404" has not failed the tool call.

Browser labels carry two tenses for this (`opened {url}` and `could not open {url}`), so
the header is a statement about the outcome rather than about the argument.

### Apply shared card behavior.

**Tool payloads are never rendered as HTML.** Titles, snippets and page text come from the
open web and are attacker-controlled; every one is a Dioxus text node, and a URL becomes an
`href` only after `http_link` has confirmed it is plainly `http`/`https`.

### Manage popup keyboard focus.

Both popups go through `ModalShell`, which supplies `role="dialog"`, `aria-modal`, an
announced label, Escape, and a focus trap made of two guard elements. Tab off either end
lands on a guard, which bounces focus back into the pane. There is no DOM to query for
focusable descendants from here, which is why guards rather than a focus list.

Capture thumbnails are buttons in the tab order.
Closing a modal returns focus to its opening control.

### Mark truncated JSON values.

`truncate_tool_payload` removes complete elements from the largest array and sets the owning object's `truncated` flag.
The card reports that flag beside the retained data.
If parsing fails, the card displays the stored bytes.

### Read pending arguments from stream summaries.

A `chat_message_stream` row has no payload columns. The arguments and result are written
only when the call finalises into `chat_messages`. Its `summary` **is** the arguments JSON
while the call runs (`AgentToolCall::summary` takes `input` first), which is what lets the
pending `web_search` card show the query. It is truncated at 400 chars, so the cards parse
it best-effort and fall back to a bare label.

The stream row carries `elapsed_ms`, measured by the server from the tool start.
The component uses that elapsed value after reload because the component also renders without a browser clock.
A running tool's `updated_at` records its start until the call finishes.

## Reuse search and document previews.

- Document cards use `SearchResultItemCard` unchanged. The session page provides a
  `SearchResultsState` context with the selection fields the card reads. It has no search
  result, so the card shows the earliest date. `ChatDocRefCard` loads the size and the dates.
- The right pane is `DocumentPreviewForSearchRoot` unchanged, including
  `NoDocumentSelected` when nothing is selected. Selection lives in the URL
  (`/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state`).

## Read tool event structures.

Observed from the live internal search agent:

```
start  {"input": {}}
start  {"input": {"query": "…", "collections": ["testdata"]}}
end    {"output": {"content": …, "type": "tool", "name": "list_collections"|"search_collections"|…,
                   "tool_call_id": "…"}, "input": {}}
```

`search_collections` results carry `collection_dataset` + `file_hash` (the
`DocumentIdentifier` key). `get_document_text` currently returns `collectionname` +
`file_hash` without `collection_dataset`. Those cards render as a non-clickable stub.

There is **no tool name on a raw start event**. It appears only at `output.name` on the
end event. [research_agent/agent.py](../../../../../main_services/agents/research_agent/research_agent/agent.py) therefore copies it onto the start chunk, because a
card rendered *while the call runs* has no end event yet and would otherwise be labelled
"tool".

Web and browser tool results additionally carry a reserved `_hoover4_artifacts` key: a list
of `{artifact_id, kind, status, url, title, detail}`. The model is told nothing about it;
it is how the cards find the screenshot and the archived page. Assets are fetched from
`/_chat_artifact/{id}/{thumb.webp|page.html|detail.json}`, which resolves the id to its
owner and enforces owner-or-admin. The id comes from an LLM-driven tool payload and is a
lookup key, not a capability. `artifact_id` is validated as a UUID before it is put in a
URL: nothing else has any business in that path segment.

The structured key does not survive LangGraph, so the browser router repeats it as a
`[hoover4:artifacts] [...]` line in the tool's **text**, and for a browser tool that text
*is the fetched page*. A hostile page can therefore write the marker into its own body. Two
things stop it: the router appends its marker as the final block of **every** result,
`[hoover4:artifacts] []` included, and `artifact_refs_from_text` honours a marker only on
the last line. A planted one is always followed by the genuine one, and a result that does
not end in a marker carries no artifacts at all. `strip_artifact_marker` matches the same
rule, so a page cannot hide its own content behind a marker either.
