# `UI-SearchPage`: search

`/search/:query/:page/:selected/:viewer_state`

Searching a set of collections and reading a result without leaving the page. The whole
query (words, filters, sort, which page of results, which result is open and how its
viewer is arranged) lives in the URL, so any state a user reaches is a link they can send.

Three regions: a top bar carrying the query and the filter and sort controls, a left panel
carrying the result list and its pagination, and a right pane previewing the selected
result.

## Controls

The date filter shows a range error when its start date follows its end date.
Folder search retains its query during return navigation within the mounted application.
The remembered query is specific to the dataset, container, and folder path.

| id | control | does | constraint |
|---|---|---|---|
| `.query` | query input, submit icon, clear button | sets or clears the words to match | empty is legal and returns the whole collection selection |
| `.folder.query` | folder search input, submit icon, clear button | searches the selected folder and its descendants | it retains its value during mounted return navigation |
| `.folder.open_search` | Open in Search link | opens the folder constraint in Search | it opens a new tab and preserves the folder page |
| `.collections` | collection selector | which collections and datasets are searched | an empty selection searches nothing and says so, rather than searching everything |
| `.facet.<name>` | facet chips, collections, file types, file location, entities, email attachments, language, text source, red flags | narrow by an indexed value; each carries a live count | a chip commits on click; counts are the count *within the rest of the query*, not the corpus |
| `.chips` | filter chips, hidden-chip count, clear all | show the applied filters after Sort, remove one or all of them, and open the filter popup at a category | the chips use at most one row more than the Sort control; a count names the hidden chips and opens the popup at the first of them; a resize changes only that count |
| `.range.dates` | date filter, before, after, between, no confirmed date | narrow by the document's date interval | a document with no confirmed date matches only through "no confirmed date": it can never fall inside a range |
| `.range.file_size_bytes` | file size filter | narrow by size | Unknown size is excluded from every range. Reopening the filter restores its applied bounds, including after reload. |
| `.filters_modal` | "All filters", clear all, cancel, close, show results | edits every filter at once in a draft, and show results applies the draft once | each opening copies the toolbar query into a new draft; cancel, close and the backdrop discard it; the chips, the results and the URL do not change while it is open; the button names how many results the draft would show |
| `.sort` | sort menu (Relevance, Date, File size, Name) plus a direction toggle | the order of the result list | Relevance sorts descending for empty and non-empty queries. Its direction control is disabled. Date, File size, and Name support both directions. |
| `.search_button` | Search button | commits the pending query, filters and sort into the applied query and runs the search | disabled while the pending query matches the applied one; the magnifier icon beside the query input runs the same action |
| `.pager` | previous/next page | walks the result list | 20 results a page, and the pager stops at 1000 documents however large the match is; the page says so beside the count instead of pretending the rest are reachable |
| `.result_step` | previous/next result | moves the selection within the list, crossing a page boundary when it runs out | next selects the first result when none is selected; controls are disabled at the ends |
| `.result_card` | a result | selects it into the preview pane | selection is part of the URL, so the browser's back button steps through selections |
| `.card_actions` | per-result actions, open the document page, open its folder | leave the search for another page | opens in the same tab: an action that silently opens a background tab reads as an action that did nothing |
| `.tree` | folder tree | narrows to a path within a collection | Each endpoint request is uncached. Navigation or remount revalidates browser entries older than five seconds while retaining current rows. A shared keyed visible-row sequence keeps common folder rows mounted when the elision resume parent changes. Each visible row is a keyed element sibling. |
| `.preview` | preview pane, source selector, in-document search, page navigation | reads the selected document without leaving the page | the pane's arrangement is part of the URL. A source change retains the find query and invalidates prior PDF controller work. |

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

Language values show English names and accept a code or name in facet search.
Text source values show the source labels of the document viewer and omit the filename row.
A text source filter matches a document through its text from a selected source.
The Red flags child of Entities shows category titles from the scanner catalog.
Counts retain the other active filters.
In the filters modal, each count applies every other draft filter and excludes its own selection.
A list keeps its previous values while its counts reload.
A selected value with no matching document stays in its list with count 0, so it can be removed.

The backend refuses pages beyond the first 1,000 results.
The page count uses ceiling division.
Grouped snippets prefer parsed body text, other text, raw text, then the filename.
A result card shows at most three complete lines of text, with an ellipsis when text is omitted, and does not scroll.
A filename-only match shares those lines between its notice and the matching path.
Folder disclosure appears only when a node has child folders or containers.
The folder icon remains the same after expansion.
The folder page opens Search in a new tab and retains the folder view.
