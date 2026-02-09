# Hoover4

Hoover4 is an end-to-end document search platform. It ingests file collections, extracts and normalizes content, indexes structured and unstructured data, and exposes search and retrieval experiences through a web application.

## Repository Layout

- `main_services` - Data ingestion, processing workflows, and core databases (ClickHouse, Manticore, MinIO, Temporal). This layer performs extraction, parsing, and indexing at scale.
- `ai_services` - GPU-backed AI services for embeddings, reranking, named entity recognition, RAG pipelines, and supporting clients.
- `website` - Full-stack Dioxus application (Rust backend, shared types, and WASM frontend) that queries the search stack.

## High-Level Flow

1. Data sources are scanned and cataloged into a virtual file system.
2. Files are parsed and normalized into ClickHouse tables and search indexes.
3. AI services enrich and rank content for retrieval and RAG use cases.
4. The web application serves search, document viewing, and related workflows.

## Navigation


- [main_services/Readme.md](main_services/Readme.md)
- [ai_services/README.md](ai_services/README.md)
- [website/Readme.md](website/Readme.md)