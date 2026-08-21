# Website backend

How the server half of the site is put together: who is allowed to ask, which database the
question goes to, how a full-text argument is built, how a failure reaches the screen, and
the two document-reading surfaces with rules of their own.

The search fan-out and everything downstream of it is
[Search architecture](Search_Architecture.md); the chat turn is
[Chat and agents](Chat_And_Agents.md).

## Contents

- [Sessions: one route mints, every other endpoint requires](#sessions-one-route-mints-every-other-endpoint-requires)
- [ClickHouse database routing](#clickhouse-database-routing)
- [Every `MATCH()` argument goes through one builder](#every-match-argument-goes-through-one-builder)
- [Showing a failed server call](#showing-a-failed-server-call)
- [In-document PDF search](#in-document-pdf-search)
- [Browsing a tabular document](#browsing-a-tabular-document)
- [The file-type glyph](#the-file-type-glyph)

## Sessions: one route mints, every other endpoint requires

`/api/whoami` is the only route that creates a session — a `web_sessions` row, a `guest-*`
user, a `user_login` event and the `hoover4_session` cookie. Every other server function
and every custom route (`/_download_document/…`, `/_download_ocr_pdf/…`,
`/_chat_artifact/…`) answers **401** when nothing resolved an identity. The policy is one
file, `website/backend/src/auth/route_policy.rs`, and its tests enumerate the custom routes
literally so a route added to `main.rs` and forgotten there fails a test rather than
shipping open.

The app shell — page routes, `/assets/…`, the wasm bundle — stays open, because the browser
has to load the code that signs in. It carries no collection data; everything it renders
arrives through a checked route.

**The frontend blocks on it.** `website/frontend/src/components/session_gate.rs` wraps the router: no page
renders until `whoami` resolves. Rendering pages first and letting each page's resources
race the sign-in would hand every one of them a 401 to display on first paint.

**And it calls it once.** The gate publishes what it resolved as a context; anything under
it that needs the identity — the admin shell, the admin guard, both chat pages — reads it
with `use_session_user()` instead of running its own `use_resource(whoami)`. A component
that fetches for itself puts another request on the single endpoint that *writes* sessions,
once per page load — the count becomes "how many identity-aware components does this route
mount" rather than one.
`use_session_user()` answers `None` while the gate's call is in flight, which means "not
known yet" and never "guest" — a component that defaults an unknown identity to a concrete
answer draws the wrong control on first paint and then takes it away.

**Why it matters that only one route mints.** A response that attaches a fresh
`set-cookie` on any route lets every client that stores no cookies — a crawler, a `curl`
loop, a link checker — create a `guest-<hex>` user and a `user_login` row *per request*,
so the user list and the metrics page grow without bound and stop being readable. A guest name is derived
from the session id rather than randomised, so a browser holding a cookie whose session row
has expired re-anchors to the identity it already had instead of becoming a second user.

**`HOOVER4_DEMO_MODE` decides whether anonymous visitors exist at all.** With it on, the
mint route provisions a guest and treats them as an administrator — the public demo. With
it off, nothing is provisioned: `whoami` refuses, the session gate renders *Sign-in
required*, and the only way in is a reverse proxy setting `X-Forwarded-User`. A
proxy-authenticated identity is honoured on every route, because the proxy is what
authenticated it; what is confined to the mint route is writing a session for it.

That elevation is applied to the request and never written to the account, so a guest's
`users` row keeps `is_admin = false` while `whoami` reports true for the same session.
The disagreement is the design — the grant belongs to the deployment and lasts exactly as
long as the switch does, where a persisted flag would leave real administrators behind the
day it is turned off — and `/admin/users` states it on the page, because that is the one
screen where the stored flag and the live grant sit side by side.

A non-browser client must therefore hold a cookie jar and call `whoami` first. That is what
`main_services/verify-stack.sh` does, discovering both URLs from the served WASM bundle
because a server function's path carries a build hash.

## ClickHouse database routing

ClickHouse is split into the global database `Hoover4_Processing` (users, groups,
collections, the dataset registry, sessions, settings, search cache) and one database
per collection, `Hoover4_Collection_<collectionname>` (blobs, VFS, parsed content, plans,
errors, term dictionaries). The backend picks the database per query in
`website/backend/src/db_utils/clickhouse_utils.rs`:

- `get_global_client()` for global tables;
- `get_collection_client(collectionname)` for per-collection tables;
- `get_client_for_dataset(collection_dataset)` resolves the owning collection via the
  global `dataset` registry (cached in-process; the mapping is immutable) and returns a
  collection client. Every per-collection read resolves immediately after
  `permissions::assert_can_read`, so an unauthorised dataset never reaches a database
  name.

A dataset's collection is **fixed when the dataset is created** and cannot be changed —
there is no assign/unassign/move in the admin UI; creating a collection provisions its
database, deleting one (only allowed when it has no datasets) drops it.

## Every `MATCH()` argument goes through one builder

That builder is `website/backend/src/db_utils/manticore_match.rs`.

Manticore has no parameter binding over its HTTP SQL endpoint, so a `MATCH()` argument
crosses two language boundaries at once and each has its own rule. `format_sql_query::
QuotedData` gets both wrong for this database and **must never be used to build a
`MATCH()` argument**:

- It escapes `'` by SQL-standard **doubling**. Manticore's parser wants a backslash and
  rejects the doubled form outright — `MATCH('it''s')` is `P01: syntax error`, while
  `MATCH('it\'s')` returns hits. `escape_manticore_string` does the backslash pass first
  and the quote pass second; the other order double-escapes the backslashes the quote
  pass introduces.
- It does nothing about the text *inside* the literal, which is a query expression.
  A dangling `"`, an unbalanced `(`, a bare `/` or `~`, and a query made only of
  negations are each a parser error rather than an empty result — `3/4` and `say"hi` are
  ordinary things to type into a search box. `prepare_match_query` repairs the first
  three, passes the real operators (`"exact phrase"`, `-exclude`, `term*`, `a | b`,
  `NEAR/3`) through untouched, and returns a typed error for the two shapes with no
  searchable reading. That error is `MatchQueryError` and it is carried out by TYPE:
  `auth::guard::is_bad_request` matches on it, so the endpoint answers **400** and the
  page renders the sentence it contains. Restating it anywhere along the way with
  `anyhow!("{e}")` leaves a bare string, and a rejected keystroke goes back to reading
  as the site falling over.

A pure string assertion is how this last reached production: the unit test asserted the
doubled form, so it passed while every search containing an apostrophe failed. Tests for
this helper assert against the character set measured to break a live Manticore, and a
change here is not verified until the query has run against a real one.

Non-`MATCH()` uses of `QuotedData` — attribute comparisons against hashes, dataset ids
and facet values — carry the same wrong quoting rule and are not yet converted.

## Showing a failed server call

`ServerFnError` never reaches the DOM. `api::error_util::user_facing_message` extracts the
`message` the backend wrote for a person — both derived renderings are unusable, `Debug`
prints the struct and `Display` wraps the message in *error running server function: …
(details: …)* — and the `ServerErrorDisplay` component is the one place that renders it.
Formatting the error at the call site instead is how a Rust struct ends up printed across
a search page's pagination.

The status picks the presentation: a **4xx** is something the caller can fix and is shown
as a plain message, anything else is a failure of ours and is shown as the red component
error. Both carry `x-error-display`, which is how `website/tools/capture_screenshots.py` finds a
surfaced error structurally rather than by matching words.

A slot with no value has no error to report either: the hit-count position renders nothing
when the search failed, because the results panel below it already shows the message and
printing it in both put it across the pager and the page numbers.

## In-document PDF search

`/api/search_document_pdf` collects the matching words out of Manticore and asks a
**pdfium sidecar** where they sit on the page, so hits can be highlighted in the rendered
PDF. The sidecar is `backend/pdf-viewer/_server/server-search.js`, a node process this
server starts and supervises (`server_extra::run_pdf_search_server`) rather than a service
of its own, which is why `PDF_SEARCH_ENDPOINT` is loopback.

**The sidecar is handed the PDF's bytes** — `POST` the document as the body, keywords as a
`?keywords=<json array>` parameter — and never a URL. It cannot reach back into anything.
A sidecar told to fetch `http://127.0.0.1:<PORT>/_download_document/…` is this server
asking itself for a document it already knows how to read, over a request that carries no
session cookie; requiring a session on the download route kills it silently. The bytes are
read straight out of the blob store instead
(`api::documents::download_document::read_blob_bytes`), which also bounds the document by
its registered size before a byte is fetched — the whole PDF is buffered here, on the wire
and inside pdfium's wasm heap. Over that ceiling, the document still opens, downloads and
searches by text; only the in-page highlight overlay is unavailable.

That blob read runs on the server's multi-threaded runtime through
`startup::on_multi_thread_runtime`. The S3 SDK blocks internally while collecting the body,
and Dioxus server functions do not run on the runtime the axum routes do — a bare
`tokio::spawn` inherits the same context rather than escaping it.

Its directory is found by walking **up** from the working directory, never joined to it:
the built release binary serves from `target/dx/<pkg>/release/web/`, so a relative path
resolves inside the build output, the spawn fails with `No such file or directory`, and
in-PDF search is dead for the whole deployment while every other route looks healthy.
`PDF_SEARCH_SERVER_DIR` overrides the search outright.

The pid file at `/tmp/pdf-search-server.pid` outlives the process it names — it is on the
container's filesystem and a restart does not clear it — and pids are handed out from a
small range at boot. So "a process exists at this number" is never evidence that it is the
sidecar, and the supervisor reads `/proc/<pid>/cmdline` before signalling anything. Killing
on liveness alone SIGKILLs a stranger: it has killed *this server's own binary* seconds
after start, after which `dx serve` believes the app is running, every route answers 500
with nothing else in the log, and each restart reproduces it because the same pid is
issued again.

This is not `PDF_TO_HTML_ENDPOINT`. That names `hoover4-processing-pdf-to-html`, a
separate container that takes a POST of raw PDF bytes and returns HTML; it answers
`GET requests are not supported` to anything the search path sends.

The viewer's own bundle is vendored under `frontend/assets/embed-pdf/_viewer/` and is
pulled into the build by a `#[used] static … asset!(…folder…)` in
`website/frontend/src/components/pdf_viewer/mod.rs`. Nothing reads that binding, and the `<script>` tag loads
the entry point by literal URL — so the `with_hash_suffix(false)` option and the
`/assets/_viewer/…` path in the tag have to be changed together, and dropping the
declaration silently ships a site with no PDF viewer.


## Browsing a tabular document

A spreadsheet or delimited-text file that the pipeline read into cells has a
`table_documents` row and is `file_type = 'table'` in `file_type_canonical`. The viewer
offers it a **Table** source, declared before `Text` in `DocumentSourceItem` so a workbook
opens on its grid rather than on the tab-separated flattening of it that the text
extractor also produced.

`website/backend/src/api/documents/table_browse.rs` is the whole query surface: `get_table_overview` (the
sheets, the columns and their statistics, the caps that fired), `get_table_page` (one
window of one sheet) and `get_table_column_values` (a filter popover's value list).

**`table_cells` is keyed by content hash alone.** It has no `collection_dataset` column,
because the same spreadsheet ingested into five datasets is one set of cells. So every one
of those three functions calls `permissions::assert_can_read`, then looks
`(collection_dataset, hash)` up in `table_documents` with `status = 'ok'`, and only then
touches `table_cells`. A hash with no manifest row for that dataset is a 404 that never
reaches a cell query; skipping the lookup would let a reader who may see one dataset read
the cells of a document that only exists in another by pasting its hash.

Three more rules those functions share:

* `limit` and the visible-column set are clamped server-side (`MAX_TABLE_PAGE_ROWS` 200,
  `MAX_TABLE_VISIBLE_COLUMNS` 60) and the clamp is **reported back** in `TablePage.clamps`.
  A grid that quietly returns 200 of the 5 000 rows it was asked for looks exactly like a
  grid whose document ends at row 200.
* every column id — visible, sorted, filtered — is validated against the sheet's own
  columns before it reaches SQL.
* every reader-supplied string is a bound parameter. This is ClickHouse, not Manticore:
  `website/backend/src/db_utils/manticore_match.rs`'s escaping exists because Manticore has nothing to bind,
  and copying it here would be a second, worse escaping layer.

Sorting is two phases. Phase 1 orders one contiguous primary-key range — the sort column
of one sheet — and returns `row_id`s; phase 2 fetches those rows' cells by `row_id IN (…)`
and re-orders them into phase 1's order in Rust, so the two phases cannot disagree about
the comparator. Rows with **no cell in the sort column** are not in phase 1's range at all
and are appended after the sorted rows in `row_id` order, in both directions.

**The header row is not a data row.** The reader writes the first row that produces cells
into `table_columns.header`, records its `row_id` as `table_sheets.header_row`, and leaves
it out of every column statistic — but it is also stored as ordinary cells. So every read
here starts *after* `header_row`, and every row count a reader sees subtracts it: otherwise
the grid draws that row twice, once as its column labels and once as row 1, and disagrees
with the statistics the filter popovers and column type marks come from. `header_row = 0`
is a sheet with no header row and nothing is skipped. For a genuinely headerless file the
first data row becomes the column labels — its values are still on screen, and it is what
a spreadsheet application shows too.

The grid draws `source_row`, the row number the file itself gives, in its `#` column —
not the dense `row_id`, which is pagination arithmetic and would be off by every empty row
above. Sheet ordinals are the workbook's own and are not contiguous, so the sheet picker is
built from the stored sheet rows and never from a range.

The selected sheet, sort, filters, hidden columns and page live in
`DocViewerState::table_state` and therefore in the URL, not in the `DocumentSourceItem`
variant: that variant is the key of `ItemHitCounts` and the value the source selector
compares against the selected source, so one carrying view state would deselect the grid
on every click.

## The file-type glyph

`website/common/src/file_type_icons.rs` maps a canonical file type to a glyph name and a label, and
`website/frontend/src/components/file_type_icon.rs` maps that one enum to one icon. Five sites draw it: the
search result card, the storage browser's file rows, the viewer's title bar, an email's
attachment cards and the preview source selector. `SearchResultDocumentItem.file_type` and
`VfsFileEntry.file_type` are filled from `file_type_canonical` — one ClickHouse read per
dataset on the page — rather than decoded from Manticore's `file_types` term ids, because
the viewer draws its glyph from that same table and a symbol must not disagree with itself.
