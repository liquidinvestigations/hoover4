# Chat components

UI building blocks for the AI Chat pages under `/ai_chat`.

| Module | Role |
|---|---|
| `composer.rs` | Textarea + **Deep Research** / **Internet tools** checkboxes + send arrow. The checkboxes disappear once the conversation has a turn — see below. No paperclip / upload control: documents enter via the processing pipeline. |
| `locked_options.rs` | The two switches, read-only, above the transcript once they are frozen. |
| `session_card.rs` | Homepage / history card showing title + summary. |
| `transcript.rs` | User bubbles, assistant markdown, tool disclosures, inline doc cards, the retry-attempt disclosure, and the token footer under an answer. |
| `tool_cards/mod.rs` | The card **registry**: dispatches on tool name, plus the shared card chrome, the elapsed-seconds counter, and the JSON/link helpers every card uses. |
| `tool_cards/web_search_card.rs` | `web_search`: pending → collapsed → expanded result list → the before/after reranking popup. |
| `tool_cards/browser_card.rs` | Every `browser_*` tool: action label, capture thumbnails, page text, and the archived page in a sandboxed iframe. |
| `tool_cards/entities_card.rs` | `list_document_entities`: the two tiers apart, each rule-validated value a link to its explainer card in the document viewer. |
| `tool_disclosure.rs` | The **generic** card, and the deliberate fallback: type chip + prose summary, Expand to labelled fields, then a second toggle for raw JSON. |
| `doc_ref_card.rs` | Wraps the shared [`SearchResultItemCard`](../search_components/search_result_item_card.rs) for a `ChatDocRef`. Renders `display_snippet()`, not the raw snippet — see below. |
| `conversation_find.rs` | "Search in conversation" bar (0/N + up/down), mirroring the document find box chrome. |
| `markdown_text.rs` | Markdown → Dioxus nodes for assistant turns. |

## The two switches are frozen after the first message

They decide **which agent answers**, so changing them mid-thread would give a transcript
where some answers had web access and some did not, with nothing on screen saying which.
The first message writes them to the session; the composer then drops the checkboxes and
`LockedOptionsBar` shows them disabled, in the position the user left them, above the
transcript. Enforced server-side too (`db_chat::lock_session_options`) — hiding the
control is the UI half, not the mechanism.

`Internet tools` defaults to **on**.

## Markdown rendering

`markdown_text.rs` maps markdown to real Dioxus elements — headings, bold/italic, inline
and fenced code, links, tables, block quotes, rules, bullets and numbered lists.

**No `dangerous_inner_html` anywhere.** The input is model output built partly from pages
scraped off the open web, so raw HTML would be an injection sink fed by exactly the wrong
source. Any HTML in the source shows as the text it is, and `[x](javascript:…)` stays
literal text rather than becoming an anchor. The cost is nested lists and quotes-inside-
lists, which a full CommonMark renderer would handle; the trade is deliberate.

The heading scale tops out at **body + 3px** (18px against 15px). Chat headings are labels
inside a message, not page titles — a browser-default `h1` at 2em towers over the
conversation. Weight and colour carry the hierarchy instead. A test pins this.

## Tool cards: a registry, not a growing `match`

Do not collapse this back into one `match` in `tool_disclosure.rs` with a branch per
tool. That shape has a specific failure: the generic branch collects the *newest* tools,
which are the ones whose output is least readable as flat key/value rows. Dispatch lives
in `tool_cards/mod.rs` and the generic card is the deliberate fallback — an MCP server
that adds a tool tomorrow still renders, just plainly.

`browser_*` is matched on the **prefix**, not by listing thirty names, so a
playwright-mcp upgrade that adds a tool does not silently drop it into the generic card.

### Only a validated value gets a link out of the transcript

The entities card links a value to its explainer card in the document viewer, and the
explainer is fetched with the rule that accepted the value — so a name a model found has
nothing to explain and is rendered as text with a line saying why. The link also needs a
dataset, which that tool does not return: `transcript.rs` collects `file_hash` to
`collection_dataset` from every tool result in the conversation and hands the map down. A
document nothing named a dataset for keeps its values as text under the reason. Both cases
are visible rather than silent, because a link that works for some values and does nothing
for others is worse than no link.

### The generic card still has three levels

1. **Collapsed** — a type chip plus a one-line prose summary. Never raw JSON.
2. **Expand** — arguments and result as labelled key/value rows, nested data summarised
   ("8 items").
3. **Show raw JSON** — a second toggle inside the expansion, pretty-printed, for debugging.

An earlier version put level 3 where level 2 belongs, so a card was either a wall of JSON
or — when the writer had not populated the payload columns — empty. Rows written before
those columns existed show the stored summary with a note, instead of a blank panel.

### `web_search`

* **Pending** (streaming, `start_tool` seen, no `end_tool`): the query in quotes, the
  sources it is waiting on, and a seconds counter. A pending search with no counter is
  indistinguishable from a wedged one.
* **Collapsed:** `web_search · "danube water level" · 30 results · 7 sources`, plus a
  warning pip when a source came back empty and a "not reranked" pip when the
  cross-encoder did not run.
* **Expanded:** the summary strip (sources, degraded list, dedupe counts, timings) and the
  result list — rank badge, title as a real link, the **full** snippet, the source chips,
  and an `RRF #7 → #2` badge where reranking moved it.
* **Popup:** both orderings side by side, fetched lazily from the `search_detail` artifact
  through the `chat_artifact_detail` server function. The tool payload cannot carry two
  orderings of forty candidates, which is why that artifact exists.

### Document cards

A `search_collections` hit carries up to `SEARCH_SNIPPET_CHARS` (1200) characters of page
text and one turn can surface a dozen, so `ChatDocRefCard` renders
`ChatDocRef::display_snippet()`, clamped to 400 characters. This is a *display* clamp: the
full text stays in the payload and the card links to the document, which is where reading
it belongs.

**One card per document, not per hit.** The search tool answers with one hit per PAGE —
`page_id` is part of its dedup key on purpose, since two pages are two pieces of evidence —
and the same bytes can be ingested into several collections, so one document arrives as
several rows. `extract_doc_refs` collapses them on `file_hash`, keeps the best-scoring
row's snippet, and gathers the other datasets into `ChatDocRef::also_in`, which the card
renders after the primary one under a CSS width clamp. Without that collapse the same title
rendered three times over and the disclosure's count described page-hits while calling them
documents.

**The cards are collapsed behind `DocRefsDisclosure` by default**, one disclosure per tool
row, labelled `<n> documents from <tool> — show`. A result set is evidence for the answer,
not the answer: rendered open, a single search put 46 cards between the question and a
one-line reply and made the page 22 168 characters of which 31 were the answer. The
summary line carries the tool name and the count because a bare chevron makes the reader
open the list to find out whether it is worth opening.

The clamp counts **characters, never bytes** — the text is arbitrary extracted content
(Romanian diacritics, CJK, an attachment's base64) and slicing a `&str` mid-codepoint
panics. The worst offenders were exactly the hits least worth reading: extraction indexes
an email attachment's base64 and an image's pixel rows as page text. `tasks/text_quality.py`
now keeps those out of the vector index, but a keyword hit can still surface one, and a card
must not depend on the pipeline having been perfect.

### `browser_*`

`browser_navigate` gets the full treatment; every other action gets a compact row — what
was done, to which element, and the resulting thumbnail. Read as a sequence those rows are
a filmstrip of the navigation, which is what makes a multi-step browse legible.

`status = 'too_large'` or `'failed'` renders as an **explicit line**, never as an absent
element: a capture that silently is not there looks identical to a tool that was never
called.

The popup frames the archived page as `<iframe sandbox="">` — the **empty** value, which is
the strict one; an omitted attribute means no sandbox at all. The response additionally
carries `default-src 'none'`. Both are required: the CSP alone still allows scripts, and
the sandbox alone still lets a stylesheet fetch leak that the capture was viewed.

### Every card says whether the call worked, collapsed

A card built from the tool's **arguments** describes what was attempted, and most readers
never expand it. Live, a `browser_navigate` that urlcheck refused rendered as "opened
http://clickhouse:8123" and a dead `web_search` as "0 results · 0 sources" — the demo
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

Browser labels carry two tenses for this — `opened {url}` and `could not open {url}` — so
the header is a statement about the outcome rather than about the argument.

### The rule every card follows

**Tool payloads are never rendered as HTML.** Titles, snippets and page text come from the
open web and are attacker-controlled; every one is a Dioxus text node, and a URL becomes an
`href` only after `http_link` has confirmed it is plainly `http`/`https`.

### Popups: Escape, a focus trap, and focus back where it came from

Both popups go through `ModalShell`, which supplies `role="dialog"`, `aria-modal`, an
announced label, Escape, and a focus trap made of two guard elements — Tab off either end
lands on a guard, which bounces focus back into the pane. There is no DOM to query for
focusable descendants from here, which is why guards rather than a focus list.

Before this, neither popup could be closed or navigated without a mouse: nothing was
announced, Tab walked straight past the overlay into the transcript behind it, and the
search-detail popup had no Escape at all. The capture thumbnails became real `<button>`s
in the same change — they open a modal, so they have to be in the tab order and they have
to be the element focus returns to on close.

### A truncated payload is truncated inside its JSON

Storage cut the serialised document at `TOOL_PAYLOAD_CHARS`, which leaves a `{` with no
`}` — so `tool_content` parsed nothing and the card printed "the result payload was not
recorded" about data sitting in the row it had just read. `truncate_tool_payload` now drops
whole elements off the biggest array and marks the owning object `"truncated": true`, which
the card reports as a line rather than letting the list stop silently. When a payload
genuinely cannot be parsed the card shows the **bytes**; a card must never deny data the
transcript is holding.

### Pending cards read their arguments from the stream row's summary

A `chat_message_stream` row has no payload columns — the arguments and result are written
only when the call finalises into `chat_messages`. Its `summary` **is** the arguments JSON
while the call runs (`AgentToolCall::summary` takes `input` first), which is what lets the
pending `web_search` card show the query. It is truncated at 400 chars, so the cards parse
it best-effort and fall back to a bare label.

The row also carries `elapsed_ms`, measured **server-side**. A running tool's stream row is
written once, at `start_tool`, and not rewritten until the call finalises — the keepalive
touches the assistant row — so its `updated_at` is when the call started. Refreshing the
page mid-call used to restart the counter at 0, which made a two-minute browse read as
having just begun: the reassuring number showing up exactly when the worrying one is true.
It is a duration rather than a start timestamp because this component is compiled into the
server-side render build too, where there is no browser clock.

## Reuse of search / document preview

- Document cards use `SearchResultItemCard` unchanged. The session page provides a
  `SearchResultsState` context with the selection fields the card reads.
- The right pane is `DocumentPreviewForSearchRoot` unchanged, including
  `NoDocumentSelected` when nothing is selected. Selection lives in the URL
  (`/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state`).

## Tool-event shapes (for the next person)

Observed from the live internal search agent:

```
start  {"input": {}}
start  {"input": {"query": "…", "collections": ["testdata"]}}
end    {"output": {"content": …, "type": "tool", "name": "list_collections"|"search_collections"|…,
                   "tool_call_id": "…"}, "input": {}}
```

`search_collections` results carry `collection_dataset` + `file_hash` (the
`DocumentIdentifier` key). `get_document_text` currently returns `collectionname` +
`file_hash` without `collection_dataset` — those cards render as a non-clickable stub.

There is **no tool name on a raw start event** — it appears only at `output.name` on the
end event. `research_agent/agent.py` therefore copies it onto the start chunk, because a
card rendered *while the call runs* has no end event yet and would otherwise be labelled
"tool".

Web and browser tool results additionally carry a reserved `_hoover4_artifacts` key: a list
of `{artifact_id, kind, status, url, title, detail}`. The model is told nothing about it;
it is how the cards find the screenshot and the archived page. Assets are fetched from
`/_chat_artifact/{id}/{thumb.webp|page.html|detail.json}`, which resolves the id to its
owner and enforces owner-or-admin — the id comes from an LLM-driven tool payload and is a
lookup key, not a capability. `artifact_id` is validated as a UUID before it is put in a
URL: nothing else has any business in that path segment.

The structured key does not survive LangGraph, so the browser router repeats it as a
`[hoover4:artifacts] [...]` line in the tool's **text** — and for a browser tool that text
*is the fetched page*. A hostile page can therefore write the marker into its own body. Two
things stop it: the router appends its marker as the final block of **every** result,
`[hoover4:artifacts] []` included, and `artifact_refs_from_text` honours a marker only on
the last line. A planted one is always followed by the genuine one, and a result that does
not end in a marker carries no artifacts at all. `strip_artifact_marker` matches the same
rule, so a page cannot hide its own content behind a marker either.
