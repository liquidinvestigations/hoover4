# Chat components

UI building blocks for the AI Chat pages under `/ai_chat`.

| Module | Role |
|---|---|
| `composer.rs` | Textarea + **Deep Research** / **Internet tools** checkboxes + send arrow. The checkboxes disappear once the conversation has a turn — see below. No paperclip / upload control: documents enter via the processing pipeline. |
| `locked_options.rs` | The two switches, read-only, above the transcript once they are frozen. |
| `session_card.rs` | Homepage / history card showing title + summary. |
| `transcript.rs` | User bubbles, assistant markdown, tool disclosures, inline doc cards, and the retry-attempt disclosure. |
| `tool_disclosure.rs` | Tool card: type chip + prose summary, Expand to labelled fields, then a second toggle for raw JSON. |
| `doc_ref_card.rs` | Wraps the shared [`SearchResultItemCard`](../search_components/search_result_item_card.rs) for a `ChatDocRef`. |
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

## Tool cards have three levels

1. **Collapsed** — a type chip (`search_collections`, `web_search`, …) plus a one-line
   prose summary. Never raw JSON.
2. **Expand** — arguments and result as labelled key/value rows, nested data summarised
   ("8 items").
3. **Show raw JSON** — a second toggle inside the expansion, pretty-printed, for debugging.

The previous version put level 3 where level 2 belongs, so a card was either a wall of
JSON or — when the writer had not populated the payload columns — empty. Rows written
before those columns existed now show the stored summary with a note, instead of a blank
panel.

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

Note there is **no tool name on a start event** — it appears only at `output.name` on the
end event, so the events must be paired before a call can be labelled.
