# Hoover4 Website

The website is a full-stack Dioxus application that provides search and document viewing capabilities over the Hoover4 data plane. It is split into three Rust crates.

## Components

- `frontend/` - Dioxus UI compiled to WASM, with routed pages for search, document view, file browser, and chatbot.
- `backend/` - Server APIs for search queries, document retrieval, and dataset listing.
- `common/` - Shared types and constants used by both frontend and backend.

## Runtime Dependencies

The backend expects:

- ClickHouse (`CLICKHOUSE_URL`) for structured data.
- Manticore (`MANTICORE_URL`) for text search.

## Technical Details

The workspace contains three Rust crates: `backend` exposes HTTP APIs for datasets and search, `frontend` is a Dioxus UI that renders pages and components, and `common` provides shared models and constants used by both.

Code is arranged by feature area: backend API modules under `backend/src/api`, database helpers under `backend/src/db_utils`, and frontend UI components under `frontend/src/components` with pages in `frontend/src/pages`.

Usage:
- Build the frontend crate with `cargo serve ---package frontend`, and follow `frontend/README.md` for Dioxus-specific dev commands.

## Development Notes

For local development, bring up `main_services` and `ai_services` first. Configure the service URLs in `.env.development` using `.env.development.example` as a template.

## Navigation

-  [Go Back](../Readme.md)

  - [frontend/README.md](frontend/README.md)