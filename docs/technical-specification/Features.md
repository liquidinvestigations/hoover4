# Feature list

Every capability the product offers, one row each, with the code that owns it. **A capability
that is agreed and not yet built has no row here**: this list describes what exists.

Identifiers are `F-<area>-<nn>`, assigned here and never reused after a removal. They are not
referenced back from source — the joins that matter are made on names that already exist in
the code, and a back-reference would buy a grep at the cost of a rename churn in two
languages.

## Contents

- [Ingestion](#ingestion)
- [Search](#search)
- [Reading a document](#reading-a-document)
- [Storage browsing](#storage-browsing)
- [Chat](#chat)
- [Administration](#administration)
- [Identity and access](#identity-and-access)

## Ingestion

| id | capability | owned by |
|---|---|---|
| `F-ingest-01` | Ingest a directory tree on disk as a dataset of a collection | `main_services/processing/tasks/P0_scan_disk/` |
| `F-ingest-02` | Deduplicate by content hash, so the same content at two paths is stored once | `P0_scan_disk/`, the blob tables |
| `F-ingest-03` | Descend into archives and email attachments, indexing members as documents in their own right | `P3_parse_files/` |
| `F-ingest-04` | Extract text from documents, per format, recording which extractor produced each page | `P3_parse_files/` |
| `F-ingest-05` | Read spreadsheets and delimited text into cells, sheets and columns | `P3_parse_files/`, the table tables |
| `F-ingest-06` | Optically recognise text in images and scanned PDFs, in configured languages, and assemble a searchable PDF | `main_services/ocr_tesseract/`, `main_services/ocr_pdf/` |
| `F-ingest-07` | Extract named entities with a model | `P4_extract_entities/` |
| `F-ingest-08` | Scan text for pattern entities — identifiers, amounts, dates and similar — with checksum validation where the format has one | `P4_extract_entities/`, `main_services/regex_entity_scanner/` |
| `F-ingest-09` | Chunk and embed every text variant into a durable vector store | `P5_chunk_embed/` |
| `F-ingest-10` | Index everything into shard tables sized by a planner | `P6_index_data/` |
| `F-ingest-11` | Rescan a dataset incrementally: changed files reprocess, unchanged files are untouched, removed paths are marked and de-indexed by reachability | `P0_scan_disk/`, `vfs_files` |
| `F-ingest-12` | Re-run one stage for the documents it failed on, without re-ingesting | `main.py retry-failed-files` |
| `F-ingest-13` | Re-index a collection from parsed content, without re-parsing | `main.py reindex-collection` |
| `F-ingest-14` | Purge an abandoned dataset's rows from every table and the index | `main.py purge-dataset` |

## Search

| id | capability | owned by |
|---|---|---|
| `F-search-01` | Full-text search across selected collections and datasets, with phrase, exclusion, prefix, alternation and proximity operators | `backend/src/api/search/` |
| `F-search-02` | Repair a query that is not valid engine syntax but is an ordinary thing to type, and refuse with an explanation the two shapes that have no searchable reading | `website/backend/src/db_utils/manticore_match.rs` |
| `F-search-03` | Facet by collection and dataset, file type, file location, entity value and email attachment, with live counts within the rest of the query | `website/backend/src/api/search/search_facets.rs` |
| `F-search-04` | Search the corpus for a facet value rather than filtering the buckets on screen | `website/backend/src/api/search/entity_terms.rs` |
| `F-search-05` | Filter by document date — before, after, between, or no confirmed date — as an interval overlap | `website/backend/src/api/search/search_sql.rs` |
| `F-search-06` | Show a date histogram of the match without its own date filter, over computed bins | `website/backend/src/api/search/date_histogram.rs` |
| `F-search-07` | Filter by file size, with unknown size distinct from zero | `website/backend/src/api/search/search_sql.rs` |
| `F-search-08` | Sort by relevance, date, file size or name, in either direction, consistently across shards | `api/search/`, `website/common/src/search_query.rs` |
| `F-search-09` | Find a document by filename | the synthetic filename row |
| `F-search-10` | Narrow to a folder, including through containers, from the tree or the filter pane | `api/vfs/` |
| `F-search-11` | Report a partial result when some collections could not be searched, and offer a retry | `website/backend/src/api/search/fanout.rs` |
| `F-search-12` | Carry the whole query — words, filters, sort, page, selection, viewer arrangement — in the URL | `website/frontend/src/data_definitions/url_param.rs` |
| `F-search-13` | Cache search responses, invalidated by a collection's shard generation and by a manual epoch | the search cache table |

## Reading a document

| id | capability | owned by |
|---|---|---|
| `F-doc-01` | Preview a result beside the list without leaving the search | `frontend/src/components/document_view_components/` |
| `F-doc-02` | Choose among a document's text sources, each labelled by the extractor that produced it | `website/common/src/document_sources.rs` |
| `F-doc-03` | Render a PDF and highlight in-document search hits at their real positions | `api/search_document_pdf`, the viewer sidecar |
| `F-doc-04` | Show an email's headers, body and attachments, and say so explicitly when no body text was extracted | `api/documents/` |
| `F-doc-05` | Browse a tabular document by sheet, with sorting, per-column filters, hidden columns and paging | `website/backend/src/api/documents/table_browse.rs` |
| `F-doc-06` | Show a document's extracted entities, filterable, with a detail card explaining a scanner value | `api/documents/`, `main_services/regex_entity_scanner/` |
| `F-doc-07` | Show a document's dates with the provenance of each | `document_dates` |
| `F-doc-08` | Show raw metadata, and download the original file or its searchable PDF | `website/backend/src/api/documents/download_document.rs` |
| `F-doc-09` | Step to the previous or next result without returning to the list | `frontend/src/components/search_components/` |

## Storage browsing

| id | capability | owned by |
|---|---|---|
| `F-store-01` | Browse a collection's folder tree, including inside archives and emails | `website/backend/src/api/vfs/tree.rs` |
| `F-store-02` | Page a folder with many children, and window the siblings and ancestors around the current focus | `website/frontend/src/components/search_components/vfs_tree.rs` |
| `F-store-03` | Resize the storage sidebar and remember its width | `website/frontend/src/components/resizable_sidebar.rs` |
| `F-store-04` | Navigate by breadcrumb across container boundaries | `website/backend/src/api/vfs/tree.rs` |
| `F-store-05` | Read the tree uncached, so it is correct while ingestion runs | `website/backend/src/db_utils/manticore_utils.rs` |

## Chat

| id | capability | owned by |
|---|---|---|
| `F-chat-01` | Ask a question about the corpus and get a streamed answer | `backend/src/api/chat/` |
| `F-chat-02` | Choose, at the first turn, whether the answer may use the open web and whether it is a deep research turn — then hold both for the conversation | `db_chat::lock_session_options` |
| `F-chat-03` | Search the corpus, read documents and list entities as agent tools | `main_services/agents/` |
| `F-chat-04` | Search the open web through one tool covering several engines, merged and reranked | `main_services/agents/metasearch_server/` |
| `F-chat-05` | Drive a real browser to read a page in full | `main_services/agents/browser_use_server/` |
| `F-chat-06` | Look up domain registration | `main_services/agents/whois_search_server/` |
| `F-chat-07` | Cite the documents an answer rests on, with a sources strip and inline chips that resolve across turns | `cite_documents`, `frontend` markdown rendering |
| `F-chat-08` | Show each tool call as a card, with its input and output | `frontend/src/components/chat_components/` |
| `F-chat-09` | Keep a conversation history, resume it, and title it automatically | `chat_sessions`, `chat_messages` |
| `F-chat-10` | Stop a turn in flight, and show an interrupted turn as interrupted rather than as a spinner | `live_runs`, the stream table |
| `F-chat-11` | Retry a failed turn automatically, and show the failed attempts behind a disclosure | `website/backend/src/api/chat/agent_client.rs` |
| `F-chat-12` | Run a deep research turn durably, outside the request | `main_services/processing/tasks/P_agent/` |

## Administration

| id | capability | owned by |
|---|---|---|
| `F-admin-01` | Create, edit and delete collections, with display names and visibility | `website/backend/src/api/admin/collections.rs` |
| `F-admin-02` | Add a dataset to a collection and start its ingestion | `website/backend/src/api/admin/datasets.rs` |
| `F-admin-03` | Watch processing progress per stage, with estimates | `website/backend/src/api/admin/processing.rs`, `processing_eta_samples` |
| `F-admin-04` | Rescan or re-index a dataset from the interface | `website/backend/src/api/admin/temporal_trigger.rs` |
| `F-admin-05` | Change a dataset's OCR languages and apply it | `website/backend/src/api/admin/dataset_ocr.rs` |
| `F-admin-06` | Manage users and groups, and grant a group read access to a collection | `website/backend/src/api/admin/users.rs`, `groups.rs` |
| `F-admin-07` | Configure language-model providers, and the model each agent profile uses | `website/backend/src/api/admin/llm.rs` |
| `F-admin-08` | See the accelerated tier's status and what it has loaded | `website/backend/src/api/admin/ai_status.rs` |
| `F-admin-09` | See usage and API metrics, and the agent runs open right now, with a kill control | `website/backend/src/api/admin/metrics.rs`, `live_runs` |
| `F-admin-10` | Change server settings that take effect without a redeploy | `website/backend/src/api/admin/settings.rs` |

## Identity and access

| id | capability | owned by |
|---|---|---|
| `F-auth-01` | Mint a session on exactly one route; every other route requires one | `website/backend/src/auth/route_policy.rs` |
| `F-auth-02` | Accept an identity asserted by a reverse proxy, on every route | `website/backend/src/auth/session_middleware.rs` |
| `F-auth-03` | Provision anonymous guests, and treat them as administrators, when demo mode is on | `website/backend/src/auth/session_middleware.rs` |
| `F-auth-04` | Restrict a collection to the groups granted it, and resolve every per-collection read after the permission check | `db_auth/`, `website/backend/src/db_utils/clickhouse_utils.rs` |
| `F-auth-05` | Rate-limit chat, polling and API calls per user, with a ladder that decays for human-paced traffic and is flat for machine-paced polling | `website/backend/src/api/rate_limit.rs` |
| `F-auth-06` | Resolve an artefact id to its owner and refuse a foreign one with a permission failure, not a missing row | `website/backend/src/db_chat/artifacts.rs` |
