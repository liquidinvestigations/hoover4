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
| the suites, the screenshot harness, the two diagnostics | [`docs/development/Testing_The_Website.md`](../docs/development/Testing_The_Website.md) |
| what the site does, per route, as agreed | [`docs/technical-specification/`](../docs/technical-specification/Readme.md) |

## Testing

| what | how |
|---|---|
| unit (Rust) | `cargo test --offline` inside `hoover4-website`, Rust is at `/usr/local/cargo/bin` there and is not on `$PATH` |
| type check, test targets included | `cargo check --workspace --tests --offline`, a plain `cargo check` does not build test binaries, so it cannot see a broken one |
| hook order | `dx check --package frontend`; `run-stack-tests.sh` and `development.sh` both run it first |
| live stack | `./run-stack-tests.sh` (fast only), `./run-stack-tests.sh --slow` (everything) |
| whole stack | `main_services/verify-stack.sh` |
| screenshots | `./take-screenshots.sh` |

**Both fixture-driven suites are welded to the corpus `main_services/verify-stack.sh`
ingests**: `screenshots.ini`'s routes and `stack_integration.rs`'s fixtures. On any other
corpus they fail by naming a dataset that does not exist, which reads as a broken page and is
neither. Run the stack verification first, or read their failures as a missing precondition.

## Development notes

Bring up `main_services` (and `ai_services` if the accelerated tier is wanted) first, then
configure the service URLs in `.env.development` from `.env.development.example`.
`website_release_mode` in `hoover4.ini` picks between the dev server and a release build:
`main_services/ops/Readme.md` has the comparison.

## Navigation

- [Go Back](../Readme.md)
- [frontend/README.md](frontend/README.md)
- [frontend/src/components/chat_components/README.md](frontend/src/components/chat_components/README.md)
