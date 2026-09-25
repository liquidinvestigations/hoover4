# Hoover4 Website

A full-stack Dioxus application serving search and document viewing over the Hoover4 data
plane. Three Rust crates in one workspace.

## Components

- `frontend/`, the Dioxus UI compiled to WASM: routed pages for search, the document view,
  the file browser and chat, with components under `frontend/src/components/`.
- `backend/`, the server: API modules by feature under `backend/src/api/`, authentication
  under `backend/src/auth/`, database helpers under `backend/src/db_utils/`,
  `backend/src/db_chat/` and `backend/src/db_auth/`.
- `common/`, types and constants shared by both halves. **Anything mirrored across the
  language boundary belongs here**, including the stage identifiers the pipeline stores and
  the extractor-key formatter.

## Runtime dependencies

The backend expects ClickHouse (`CLICKHOUSE_URL`) for structured data and Manticore
(`MANTICORE_URL`) for text search, plus the blob store for document bytes and the two agent
services for chat. Every URL is a key in `hoover4.ini`, rendered into the generated `.env`;
`docs/operations/Configuration_Reference.md` lists them with their consumers.

## How it is structured, and why

The explanations live in `docs/`, because they outlive any one change here:

| subject | page |
|---|---|
| sessions, database routing, the full-text argument builder, failure surfacing, in-document PDF search, tabular browsing | [`docs/architecture/Website_Backend.md`](../docs/architecture/Website_Backend.md) |
| the search fan-out, what is exact and what is approximate, filters, the date histogram, sorting, the folder tree, cache invalidation | [`docs/architecture/Search_Architecture.md`](../docs/architecture/Search_Architecture.md) |
| the chat turn, which agent answers, streaming, retries, citations, the admin views | [`docs/architecture/Chat_And_Agents.md`](../docs/architecture/Chat_And_Agents.md) |
| the suites, the screenshot harness, the two diagnostics | [`docs/quality-assurance/Testing_The_Website.md`](../docs/quality-assurance/Testing_The_Website.md) |
| what the site does, per route, as agreed | [`docs/technical-specification/`](../docs/technical-specification/Readme.md) |

## Agent routes

Every path under `/api/agent/v1/` is a stable read route for a tool-calling agent, mounted
beside the ordinary Dioxus server functions and covered by the same session middleware. Each
route is `POST` with a JSON body and a JSON response, defined in `common::agent_api` and
implemented in `backend::api::agent`, one module for each route group (search, documents,
tables, folders).

An agent route refuses `X-Forwarded-User` and session cookies with `403`.
A request identifies itself with `X-Hoover4-User`,
resolved against the existing user table. An absent header, or a username with no matching
row, is refused with `401`. No user or group row is written on this path: the header-identity
sync a browser request triggers would overwrite a resolved user's stored groups with an empty
list, so the agent branch reads the row and never writes it.

A request also carries `X-Hoover4-Collections`, a comma-separated list narrowing the caller's
own permitted collections; an empty header means the whole permitted set. A named collection
outside that set is refused with `403`, not `404`: the caller asked for something that exists
and was refused, which is a different fact from asking for something absent.

A statement that Manticore or ClickHouse refuses is answered with `400` `invalid_argument` and
the datastore's message, because it fails the same way on a retry. A datastore time limit is
`504` `timed_out`, and an unreachable datastore is `503` `backend_unavailable`. A body that does
not parse into the route's request type is `400`.

Every search, folder, document and table route runs under one 30 s deadline for the whole request, and
answer `504` `timed_out` when it fires. Their paged responses carry `AgentPageInfo` beside their
own fields: `source`, `next_position`, `total` and `partial`. A request continues with that
`position`, whose `kind` names its type, and with `expected_source`. A changed source is
refused with `409` `source_changed`, and a position of a kind the route does not issue with
`400`. Search pages stop at the website's 1,000-result limit, so page 50 is refused with `400`.
A folder route accepts the short dataset name that `collections/list` returns or the full
`<collection>_<dataset>` name, and answers with the short name. A folder node id reads the six
characters `\u001f` as the U+001F separator, because a model cannot write that character. A
node id that names no node of the dataset is `404` `not_found`. A search facet filter takes
the term ids that `facet_counts` and `search/facet_values` return, except
`collection_dataset`, which takes dataset names.

A document route reads one window of a document: one stored text page, one page of hits,
or one page of a kept PDF search result. The agent names a document by its file hash, and one
blob can be in more than one dataset. The route reads a dataset that the caller can read and
that holds the row the route reads: the `email_headers` row for `documents/email`, and the
table manifest row for a table route. Name order decides between equal datasets. Two reads grow with the document and run under the
30 s deadline. `documents/pdf_search` searches the whole PDF when no kept result matches, and
`documents/sources` with a `query` counts the hits of every source over the whole document.
`documents/read` reads one stored text page of each of at most 20 documents. With a
`query` and no page, it opens the page with the most hits, as the viewer does, and lists the
first 50 page ids with hits. Page ids can have gaps, and a page id with no stored page is `404`.
It continues with `TextPage` positions. `documents/search_text` lists the hits of one source in
page order, 50 a page, with `HitKey` positions, and reads only the pages that hold them. A hit
count stops at the viewer's 1,000-page limit and then sets `partial`. `documents/sources` lists
every source kind with the viewer's hit counts. A PDF count that does not finish before the
deadline answers `count_state` `timed_out` for that source only. A count that fails answers
`failed`, and a text or Email count whose read stopped at the 1,000-row limit answers
`partial`. Each of these sets `partial` on the response. A query that the index refuses is
`400`, as in `documents/search_text`. `documents/metadata` cuts a
value over 2,000 characters and marks it with `cut`. `documents/email` takes `node`, the graph
centre, and pages the attachments 50 at a time with `Offset` positions.
`documents/diff_sources` compares one page of each source. `documents/pdf_search` keeps the
sidecar result of the last 16 searches for 10 minutes, filters it by `page_from` and
`page_to`, and pages it 100 hits at a time with `HitKey` positions. The website's own PDF
search keeps its 120 s sidecar timeout, and the agent route gives the sidecar the time that
remains of its deadline.

A table route reads a window of a sheet, and its `source` comes from the table manifest,
the reader version and the latest manifest write time, so no read scans the cells for it.
Three reads grow with the sheet and run under the 30 s deadline. `tables/search_cells` scans
every cell of the sheet, `tables/column_values` groups the whole column, and a sorted,
filtered or searched `tables/page` reads every matching row of the sheet.
`tables/overview` lists 20 sheets a page with `Offset` positions, each with its column ids.
`tables/page` reads 50 rows of at most 60 columns: `columns` names the column ids, and the
website's clamp keeps the first 60 and returns what it kept as `clamps`. A column id in
`columns`, `sort` or `filters` that the sheet does not have is `400` `invalid_argument`, and
the message gives the lowest and highest column id of the sheet. With no sort, filter
or search it starts at `row_start` and continues with `Rows` positions, computed from the row
id with no query. A sorted, filtered or searched page continues with `Offset` positions, as the
table viewer reads it. A cell over 2,000 characters is cut and marked with `cut`, and
`tables/cell` reads one cell by its `row_id` and column id, 2,000 characters a page, with
`Offset` positions. `tables/column_values` takes the filter popover's `search` and continues
past 200 values with `ValueKey` positions. `tables/search_cells` pages 200 hits with `Offset`
positions.

`scripts/test-agent-api-contract.sh` calls every route against the running site, plus the four
identity refusals, one forbidden-collection case, and the search, folder, document and table
paging cases, and exits nonzero on the first failure. The table cases read the `testdata_tables`
dataset: one workbook with one sheet of more than 1,000,000 rows and more than 60 columns, and
one cell longer than 2,000 characters. The testdata checkout has no such spreadsheet, so the
fixture is generated and ingested with `add-disk-dataset testdata tables <root>`.

## Testing

| what | how |
|---|---|
| unit (Rust) | `cargo test --offline` inside `hoover4-website`, Rust is at `/usr/local/cargo/bin` there and is not on `$PATH` |
| type check, test targets included | `cargo check --workspace --tests --offline`, a plain `cargo check` does not build test binaries, so it cannot see a broken one |
| hook order | `dx check --package frontend`; `run-stack-tests.sh` and `development.sh` both run it first |
| live stack | `./run-stack-tests.sh` (fast only), `./run-stack-tests.sh --slow` (everything) |
| whole stack | `main_services/verify-stack.sh` |
| agent routes | `scripts/test-agent-api-contract.sh`, against the running site |
| screenshots | `./take-screenshots.sh` |
| chat observation | `./observe-chat.sh` |

**Both fixture-driven suites separate their corpus-dependent cases from their
corpus-independent ones.** A screenshot page that names a missing dataset is
`incomplete_execution` and does not pass. Other pages still run.
`stack_integration.rs` checks with `skip_unless_dataset!` and its two corpus-wide forms.
Run the stack verification first to exercise the corpus-dependent half too.

## Development notes

Bring up `main_services` (and `ai_services` if the accelerated tier is wanted) first, then
configure the service URLs in `.env.development` from `.env.development.example`.
`website_release_mode` in `hoover4.ini` picks between the dev server and a release build:
`main_services/ops/Readme.md` has the comparison.

Browser work packages can use the ignored `TEST_LOGIN.env` beside `take-screenshots.sh`.
[`TEST_LOGIN.env.example`](TEST_LOGIN.env.example) defines the account input keys for agents.
`take-screenshots.sh` and `observe-chat.sh` both load this file automatically when no
`HOOVER4_TEST_USERNAME`/`HOOVER4_TEST_PASSWORD` pair is supplied. Pass `--login-env FILE`
to name another file. Credential values are not accepted as `--username` or `--password`
arguments.
See [`docs/quality-assurance/Testing_The_Website.md`](../docs/quality-assurance/Testing_The_Website.md)
for the full runner and observer contract.

## Navigation

- [Go Back](../Readme.md)
- [frontend/README.md](frontend/README.md)
- [frontend/src/components/chat_components/README.md](frontend/src/components/chat_components/README.md)
