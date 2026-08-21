# Repository map

Where things are, and which `Readme.md` answers which question. Read this before searching:
most questions here are answered by opening one known file rather than by grepping.

## Contents

- [Top level](#top-level)
- [main_services](#main_services)
- [website](#website)
- [ai_services](#ai_services)
- [Supporting directories](#supporting-directories)
- [Which file answers which question](#which-file-answers-which-question)

## Top level

| path | holds |
|---|---|
| `main_services/` | the ingestion pipeline, the datastores' operational config, the MCP servers and research agents |
| `website/` | the full-stack Dioxus application: Rust backend, WASM frontend, shared types |
| `ai_services/` | the standalone GPU tier — embeddings, reranking, NER, GPU OCR, local model serving |
| `components/` | build wrappers around the vendored PDF viewer that the website embeds |
| `docs/` | the documentation tree this page belongs to, including the technical specification |
| `.agents/` | the shared agent configuration: skills, path-scoped rules, hooks and per-harness adapters |
| `testdata/` | corpora and generated fixtures used by the pipeline tests and the stack verification |
| `deploy` | the single entry point that renders configuration and brings stacks up |
| `hoover4.ini` | the one configuration file; every generated `.env` derives from it |

## main_services

| path | holds |
|---|---|
| `processing/` | the Temporal workflows and activities; `tasks/P0_scan_disk` … `P6_index_data` are the pipeline stages, each with its own `Readme.md` |
| `processing/database/` | schema, per-collection and global migrations, and the migration runner |
| `processing/tests/` | unit tests that run without a stack, and integration tests that need one |
| `agents/` | the MCP servers and research agents, plus `agent_common`, which is vendored into the server images |
| `ops/` | operational procedures, the compose files and per-service Docker build contexts |
| `ocr_tesseract/`, `ner_spacy/` | the CPU twins of GPU services, speaking the same HTTP contracts so callers need no branching |
| `ocr_pdf/` | searchable-PDF assembly, writing under the blob store's derived prefix |
| `regex_entity_scanner/` | the pattern-scanning service the entity stage calls; self-contained, with its own `README.md` and sub-documents |
| `verify-stack.sh` | the end-to-end stack verification |

## website

| path | holds |
|---|---|
| `backend/src/` | the server: `api/` by feature, `auth/`, `db_auth/`, `db_chat/`, `db_utils/` |
| `frontend/src/` | the WASM client: `pages/`, `components/`, `data_definitions/` |
| `common/src/` | types shared by both halves — anything mirrored across the language boundary belongs here |
| `tools/` | single-question diagnostics driven through a browser container |
| `tests/` | stack integration tests, split by name rather than by attribute |

## ai_services

The GPU tier is standalone: its own private network, no dependency on the main stack. Each
service directory holds its server and its Dockerfile; `compose/` holds the overlay per
service.

## Supporting directories

`components/pdf-viewer/` wraps an upstream viewer: the scripts build it and copy the
artefacts into the website's assets. `testdata/` mixes a fetched corpus with generated
fixtures.

## Which file answers which question

| question | file |
|---|---|
| what the product is, and how to install it | root `Readme.md` |
| how a pipeline stage works | `main_services/processing/tasks/P<n>_*/Readme.md` |
| the schema and how migrations run | `main_services/processing/database/Readme.md` |
| which containers exist and what they expose | `main_services/ops/Readme.md` |
| what an MCP server does and how it is built | `main_services/agents/README.md` and the per-server README |
| how the website is structured | `website/Readme.md` and the pages under `docs/architecture/` |
| how the agent configuration works | [Working with agents](Working_With_Agents.md) |
| every configuration key and its consumer | [Configuration reference](../operations/Configuration_Reference.md) |
| what the product does, as agreed | [`docs/technical-specification/`](../technical-specification/Readme.md) |
| how to reach the demo box or the GPU box | `INFRASTRUCTURE_INVENTORY.md` at the repository root — local and gitignored |

## Searching, when searching is right

Searches here run on a `grep` replacement that does **not** skip build output, and
`website/target` alone is tens of gigabytes. Scope every search: name the extensions, or
exclude the build roots, or point it at one directory. A search that has not returned within
seconds is wrong rather than slow — kill it and re-scope. The harness reports the runaway as
"no output", which is indistinguishable from a search that legitimately found nothing.
