# `UI-SearchPage`: search

`/search/:query/:page/:selected/:viewer_state`

Searching a set of collections and reading a result without leaving the page. The whole
query (words, filters, sort, which page of results, which result is open and how its
viewer is arranged) lives in the URL, so any state a user reaches is a link they can send.

Three regions: a top bar carrying the query and the filter and sort controls, a left panel
carrying the result list and its pagination, and a right pane previewing the selected
result.

## Controls

| id | control | does | constraint |
|---|---|---|---|
| `.query` | query input | the words to match | empty is legal and returns the whole collection selection |
| `.collections` | collection selector | which collections and datasets are searched | an empty selection searches nothing and says so, rather than searching everything |
| `.facet.<name>` | facet chips, collections, file types, file location, entities, email attachments | narrow by an indexed value; each carries a live count | a chip commits on click; counts are the count *within the rest of the query*, not the corpus |
| `.range.dates` | date filter, before, after, between, no confirmed date | narrow by the document's date interval | a document with no confirmed date matches only through "no confirmed date": it can never fall inside a range |
| `.range.file_size_bytes` | file size filter | narrow by size | unknown size is a distinct value from zero and is excluded from every range |
| `.filters_modal` | "All filters", clear all, cancel, show results | edits every filter at once, pending until `.search_button` commits them | edits are pending until committed; cancel discards them; the button names how many results committing would show |
| `.sort` | sort menu (Relevance, Date, File size, Name) plus a direction toggle | the order of the result list | Relevance is not an order without words to be relevant to: with an empty query it resolves to newest-first, and the control shows the resolved order rather than the one that was asked for |
| `.search_button` | Search button | commits the pending query, filters and sort into the applied query and runs the search | disabled while the pending query matches the applied one; the magnifier icon beside the query input runs the same action |
| `.pager` | previous/next page | walks the result list | 20 results a page, and the pager stops at 1000 documents however large the match is; the page says so beside the count instead of pretending the rest are reachable |
| `.result_step` | previous/next result | moves the selection within the list, crossing a page boundary when it runs out | disabled at the ends rather than hidden |
| `.result_card` | a result | selects it into the preview pane | selection is part of the URL, so the browser's back button steps through selections |
| `.card_actions` | per-result actions, open the document page, open its folder | leave the search for another page | opens in the same tab: an action that silently opens a background tab reads as an action that did nothing |
| `.tree` | folder tree | narrows to a path within a collection | the tree reflects a corpus that changes while ingestion runs, so it is read uncached; a stale tree is worse than a slow one |
| `.preview` | preview pane, source selector, in-document search, page navigation | reads the selected document without leaving the page | the pane's arrangement is part of the URL |

## States

| state | when | what the page shows |
|---|---|---|
| counting | a query is running and no count has arrived | the previous results stay, the count reads as counting |
| results | the query matched | the list, the total, and the cap notice when the total is over 1000 |
| empty, unfiltered | no filters and nothing matched | that nothing matched the words |
| empty, filtered | filters are set and nothing matched | that the *filters* matched nothing, a different sentence, because the fix is different |
| inverted range | a range whose lower bound is above its upper | the control refuses inline; a range that gets past the control must not quietly match everything |
| failed | a server call failed | the failure is surfaced on the page, not swallowed into an empty result list |

## Constraints

- **Every state is a URL.** A query is a bookmarkable encoded blob; fields added to it later
  decode from an older link by taking their default, so an old bookmark keeps working rather
  than shifting every value after the missing one.
- **Sort keys and filter fields are a closed set**, not free text: both end up in a database
  order clause and in a merge across shards that has to implement the same order.
- **The count is the whole match; the pager is not.** These are deliberately different
  numbers, and the page states the difference where a user meets it.

## Owned by

`website/frontend/src/pages/search_page.rs`,
`website/frontend/src/components/search_components/`,
`website/common/src/search_query.rs` (the query, sort and range types, shared with the
backend). The fan-out, the match builder and the caching boundary are
`../../architecture/Search_Architecture.md`.
