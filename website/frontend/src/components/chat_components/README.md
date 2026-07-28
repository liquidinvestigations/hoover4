# Chat components

UI building blocks for the AI Chat pages under `/ai_chat`.

| Module | Role |
|---|---|
| `composer.rs` | Textarea + **Deep Research** / **Internet tools** checkboxes + send arrow. No paperclip / upload control — documents enter via the processing pipeline. |
| `session_card.rs` | Homepage / history card showing title + summary. |
| `transcript.rs` | Renders user bubbles, assistant markdown-ish text, tool disclosures, and inline doc cards. |
| `tool_disclosure.rs` | Compact "🔎 searched collections · query" line with Expand and a "Search this" link that opens `/search/...` from the recorded `tool_input`. |
| `doc_ref_card.rs` | Wraps the shared [`SearchResultItemCard`](../search_components/search_result_item_card.rs) for a `ChatDocRef`. |
| `conversation_find.rs` | "Search in conversation" bar (0/N + up/down), mirroring the document find box chrome. |
| `markdown_text.rs` | Light paragraphs / bullets / numbered lists for assistant turns. |

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
