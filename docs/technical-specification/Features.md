# Feature list

Every capability the product offers, one row each, with the code that owns it. **A capability
that is agreed and not yet built has no row here**: this list describes what exists.

Identifiers are `F-<area>-<nn>`, assigned here and never reused after a removal. They are not
referenced back from source, the joins that matter are made on names that already exist in
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
| `F-ingest-08` | Scan text for pattern entities (identifiers, amounts, dates and similar) with checksum validation where the format has one | `P4_extract_entities/`, `main_services/regex_entity_scanner/` |
| `F-ingest-09` | Chunk and embed every text variant into a durable vector store | `P5_chunk_embed/` |
| `F-ingest-10` | Index everything into shard tables sized by a planner | `P6_index_data/` |
| `F-ingest-11` | Rescan a dataset incrementally: changed files reprocess, unchanged files are untouched, removed paths are marked and de-indexed by reachability | `P0_scan_disk/`, `vfs_files` |
| `F-ingest-12` | Re-run one stage for the documents it failed on, without re-ingesting, keeping each failure at one recorded row however many times it is retried | `main.py retry-failed-files`, the `retry_failed_files` operation |
| `F-ingest-13` | Re-index a collection from parsed content, without re-parsing | `main.py reindex-collection` |
| `F-ingest-14` | Purge an abandoned dataset's rows from every table and the index | `main.py purge-dataset`, the `purge_dataset` operation |
| `F-ingest-15` | Survive a worker restart mid-ingest: in-flight activities are drained rather than killed, batch stages give their work back at an item boundary, and the dataset finishes with every document's chunks, vectors and index rows | `tasks/run_worker.py`, `tasks/heartbeat.py`, `main_services/verify-stack.sh --restart-resilience` |
| `F-ingest-16` | Record a stage's own decision that an input needs no work (an image too small to hold text, a file below the minimum table shape) as a distinct outcome, never as a failure, so it is never retried and never counted in a failure total | `tasks/task_timing.py` (`SkippedOutcome`, `processing_task_runs.outcome`), `P3_parse_files/parse_ocr.py`, `P3_parse_files/parse_table.py` |

## Search

| id | capability | owned by |
|---|---|---|
| `F-search-01` | Full-text search across selected collections and datasets, with phrase, exclusion, prefix, alternation and proximity operators | `backend/src/api/search/` |
| `F-search-02` | Repair a query that is not valid engine syntax but is an ordinary thing to type, and refuse with an explanation the two shapes that have no searchable reading | `website/backend/src/db_utils/manticore_match.rs` |
| `F-search-03` | Facet by collection and dataset, file type, file location, entity value and email attachment, with live counts within the rest of the query | `website/backend/src/api/search/search_facets.rs` |
| `F-search-04` | Search the corpus for a facet value rather than filtering the buckets on screen | `website/backend/src/api/search/entity_terms.rs` |
| `F-search-05` | Filter by document date (before, after, between, or no confirmed date) as an interval overlap | `website/backend/src/api/search/search_sql.rs` |
| `F-search-06` | Show a date histogram of the match without its own date filter, over computed bins | `website/backend/src/api/search/date_histogram.rs` |
| `F-search-07` | Filter by file size, with unknown size distinct from zero | `website/backend/src/api/search/search_sql.rs` |
| `F-search-08` | Sort by relevance, date, file size or name, in either direction, consistently across shards | `api/search/`, `website/common/src/search_query.rs` |
| `F-search-09` | Find a document by filename | the synthetic filename row |
| `F-search-10` | Narrow to a folder, including through containers, from the tree or the filter pane | `api/vfs/` |
| `F-search-11` | Report a partial result when some collections could not be searched, and offer a retry | `website/backend/src/api/search/fanout.rs` |
| `F-search-12` | Carry the whole query (words, filters, sort, page, selection, viewer arrangement) in the URL | `website/frontend/src/data_definitions/url_param.rs` |
| `F-search-13` | Cache search responses, invalidated by a collection's shard generation and by a manual epoch | the search cache table |

## Reading a document

| id | capability | owned by |
|---|---|---|
| `F-doc-01` | Preview a result beside the list without leaving the search | `frontend/src/components/document_view_components/` |
| `F-doc-02` | Choose among a document's text sources, each labelled by the extractor that produced it | `website/common/src/document_sources.rs` |
| `F-doc-03` | Render a PDF and highlight in-document search hits at their real positions | `api/search_document_pdf`, the viewer sidecar |
| `F-doc-04` | Show an email's headers, body and attachments, and say so explicitly when no body text was extracted | `api/documents/` |
| `F-doc-05` | Browse a tabular document by sheet, with sorting, per-column filters, hidden columns and paging | `website/backend/src/api/documents/table_browse.rs` |
| `F-doc-06` | Show a document's extracted entities, filterable, with a detail card explaining a scanner value; a link may name one entity, which opens that card alone and says so when the document no longer carries the value | `api/documents/`, `main_services/regex_entity_scanner/` |
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
| `F-chat-01` | Ask a question about the corpus and get a streamed answer | `backend/src/api/chat/`, `chat_message_stream` |
| `F-chat-02` | Choose, at the first turn, whether the answer may use the open web and whether it is a deep research turn, then hold both for the conversation | `db_chat::lock_session_options` |
| `F-chat-03` | Search the corpus from several query angles in one call, every hit naming the queries that found it | `search_collections`, `matched_queries` |
| `F-chat-03a` | Read several documents in one call, sharing one character budget and naming what did not fit | `read_documents` |
| `F-chat-03b` | List the entities found in several documents in one call, in two tiers, sharing one character budget | `list_document_entities` |
| `F-chat-04` | Search the open web from several query angles in one call, through one tool covering every source, merged into one pool and reranked once, every result naming the queries that found it | `main_services/agents/metasearch_server/` |
| `F-chat-04a` | Search world news, structured entities, DOI metadata and two web archives as sources of that one tool | `gdelt`, `wikidata`, `crossref`, `wayback`, `archive_today` |
| `F-chat-04b` | Search published fact-checks, present only where a key file is mounted and absent from the source list otherwise | `factcheck`, `FACTCHECK_API_KEY_FILE` |
| `F-chat-05` | Read several web pages in one call with a real browser, each returning its text plus an archived copy | `read_page` |
| `F-chat-05a` | Drive a page that has to be operated (navigate, snapshot, click, type, select, press) over a configurable allowlist of the browser sidecar's surface | `BROWSER_EXPOSED_TOOLS` |
| `F-chat-06` | Look up the registration of several domains in one call | `whois_lookup` |
| `F-chat-07` | Cite the documents an answer rests on, with a sources strip and inline chips that resolve across turns | `cite_documents`, `frontend` markdown rendering |
| `F-chat-08` | Show each tool call as a card, with its input and output | `frontend/src/components/chat_components/` |
| `F-chat-08a` | Open a listed entity's explainer card from inside the transcript, in the address so the open card is a link, offered only for a value a rule validated, since a model-found name has no card, and only for a document the conversation named a dataset for | `chat_components/tool_cards/entities_card.rs`, `DocViewerState::selected_entity` |
| `F-chat-09` | Keep a conversation history, resume it, and title it automatically | `chat_sessions`, `chat_messages` |
| `F-chat-10` | Stop a turn in flight, keeping its partial answer out of the conversation rather than saving an unmarked fragment, and saying so on the control; and show an interrupted turn as interrupted rather than as a spinner | `chat::stop_chat_turn`, the stream table |
| `F-chat-11` | Retry a failed turn automatically, on whichever worker picks it up | `ChatTurn`, its activity retry policy |
| `F-chat-12` | Run every turn durably, outside the request, so a website restart or a closed tab does not lose it | `main_services/processing/tasks/P_agent/` |
| `F-chat-13` | List every agent turn running anywhere, and cancel one | `chat::admin_list_live_runs`, Temporal visibility |
| `F-chat-14` | Keep a plan for the conversation (a goal and steps) written whole, read back, its rows edited and its steps marked off in a batch, versioned so every revision survives | `main_services/agents/agent_todo_server/`, `chat_todos` |
| `F-chat-14a` | Refuse a step abandoned with no reason, so giving up on part of a plan is recorded rather than free | `chat_todos.normalise_item` |
| `F-chat-14b` | Open a turn that has no live plan by restating the task and weighing two or three approaches in the answer itself, before writing the chosen one into the plan, and ask it only of a profile that binds the tools to write one | `research_agent/prompts/_blocks/plan_first.md.j2`, `keeps_preamble` |
| `F-chat-15` | Run the agent again, in the same turn, when it stops with steps still unresolved, twice while the plan is not moving, five times in all, each nag buying a fixed extra tool budget | `ChatTurn`, `tasks/P_agent/nagging.py` |
| `F-chat-15a` | Show each nudge in the transcript as its own kind of entry, neither the user's words nor an error | `ChatRole::Nag` |
| `F-chat-16` | Count what a turn cost in tokens (the conversation it carried and the largest single context it was billed for, summed across every nudge round) and keep the conversation's running peak | `tasks/P_agent/`, `chat_messages`, `chat_sessions.peak_context_tokens` |
| `F-chat-16a` | Show both numbers under an answer against the model's context window and the percentage used, and say the window is unknown rather than guessing one the provider never stated | `ChatMessageItem::context_footer` |
| `F-chat-17` | Stop sending the older tool results to the model once a turn's context passes a configured fraction of the model's stated context window. The calls that produced them stay, so the model still sees what it searched for, and the most recent results are kept intact. **The shipped fraction is 60% and no turn this stack produces reaches it**: the widest measured turn uses about a tenth of the window, so this does not fire on current traffic and is present for a smaller window, a larger corpus, or tool results replayed across turns | `research_agent/compaction.py`, `agent_compaction_fraction` |
| `F-chat-17a` | Never compact a model whose context window the provider does not state, rather than compacting against a guessed denominator | `compaction.threshold_tokens` |
| `F-chat-17b` | Leave the transcript exactly as it was, a compaction changes only what is sent to the model, so scrolling back through a conversation shows every tool result in full | `compaction.evict_tool_results`, `chat_messages` |
| `F-chat-17c` | Record every applied compaction (what was evicted, the handoff document whole, the citation handles that were live, the model-visible list either side, the trigger and its denominator, and the token counts before and after) so a compaction error can be debugged | `chat_compactions` |
| `F-chat-17d` | When dropping the older tool results is not enough, replace the older messages with one structured handoff document (what was replaced, the citations that stand, and the work, the verbatim facts and what remains) written by a model that can be a cheaper one than the conversation's | `compaction.summarise_messages`, `agent_compaction_model` |
| `F-chat-17e` | Never summarise the user's own messages, the todo, or any message that issued or used a citation handle. They are selected in code and copied through unchanged, so a summariser cannot lose them whatever it is asked to do | `compaction.protected_indexes` |
| `F-chat-17f` | Tell the reader when an answer was written from a summary rather than from what the agent read, and only then, a turn that merely stopped sending old tool results to the model says nothing, because every one of them is still in the transcript | `research_agent/agent.py` |
| `F-chat-18` | Split a question into several briefings (an objective, what is already known, what to bring back) and research them at once in fresh contexts that cannot see each other, each returning a written report and the citation handles it allocated | `run_subagent`, `research_agent/subagents.py` |
| `F-chat-18a` | Delegate exactly one level deep, because a worker's tool list is built without the delegation tool rather than because its instructions ask it not to recurse | `subagents.worker_tools`, `subagents.WORKER_DENIED_TOOLS` |
| `F-chat-18b` | Enforce every delegation cap as a number rather than a request (tasks per call, workers at once, tool turns each, and a total for the whole user turn that a nudge round continues instead of resetting) refusing the surplus by name so the model can act on it | `subagents.MAX_TASKS_PER_CALL`, `subagents.start_turn` |
| `F-chat-18c` | Give a worker page reading and not the tools that drive a page, and the plan to read and not to write, so a delegating turn costs the browser server what a plain turn costs it and no worker rewrites the conversation's plan | `subagents.WORKER_DENIED_TOOLS` |
| `F-chat-18d` | Make a worker's citations resolve in the conversation that delegated to it, by running it on the lead's own tool connections and therefore its citation session | `subagents.make_delegation_tool`, `citations.HandleTable` |
| `F-chat-18e` | Count what the workers cost into the turn's own token total, and report their share separately, their model calls happen inside a tool call and reach no other counter | `subagents.TurnBudget`, `subagents.worker_usage` |
| `F-chat-19` | Render each profile's system prompt from the tools that profile actually binds, so it can neither describe a tool the model does not have nor omit one it does, and state the tool-turn budget the graph enforces rather than a number typed into the prose. A template that names an unbound tool, or a budget the code does not use, fails a test | `research_agent/prompts/`, `research_agent/tests/test_prompts.py` |
| `F-chat-19a` | Render the collection-search server's discovery instructions (read by whichever agent connects, before it writes a query) from the tools that server registers, so a renamed tool is a test failure and not an instruction to call something that no longer exists | `collection_search_server/prompts/`, `collection_search_server/tests/test_prompts.py` |
| `F-chat-19b` | Tell the model plainly, in its own instructions, when the conversation can read no collection at all, instead of leaving it to infer that from three empty searches | `prompts.render`'s `collections_hint`, `agent._create_graph` |

## Administration

| id | capability | owned by |
|---|---|---|
| `F-admin-01` | Create, edit and delete collections, with display names and visibility, where provisioning and dropping the collection's database are operations with rows of their own | `website/backend/src/api/admin/collections.rs`, the `ensure_collection` and `drop_collection_database` operations |
| `F-admin-02` | Add a dataset to a collection and start its ingestion | `website/backend/src/api/admin/datasets.rs` |
| `F-admin-03` | Watch processing progress per stage, with estimates | `website/backend/src/api/admin/processing.rs`, `processing_eta_samples` |
| `F-admin-04` | Start any per-dataset pipeline run from the interface (ingest, rescan, compute plans, execute plans) each dispatched as an operation, so a run started from a button is one row in the same log as a run started from a terminal | `website/backend/src/api/admin/datasets.rs:admin_trigger_workflow`, `operations.rs:dispatch_operation` |
| `F-admin-05` | Change a dataset's OCR languages and apply it, as an operation whose row carries the stage it is in and the variants it added and removed | `website/backend/src/api/admin/dataset_ocr.rs`, the `change_ocr_languages` operation |
| `F-admin-06` | Manage users and groups, and grant a group read access to a collection | `website/backend/src/api/admin/users.rs`, `groups.rs` |
| `F-admin-07` | Configure language-model providers, and the model each agent profile uses | `website/backend/src/api/admin/llm.rs` |
| `F-admin-07a` | Discover each model's context window from the provider's own listing and keep it against the model, leaving it absent rather than guessed where the provider states none | `website/backend/src/api/admin/llm.rs`, `tasks/llm_catalog.py`, `llm_models.context_window` |
| `F-admin-08` | See the accelerated tier's status and what it has loaded | `website/backend/src/api/admin/ai_status.rs` |
| `F-admin-09` | See usage and API metrics, and the agent turns running right now, with a kill control | `website/backend/src/api/admin/metrics.rs`, `F-chat-13` |
| `F-admin-10` | Change server settings that take effect without a redeploy | `website/backend/src/api/admin/settings.rs` |
| `F-admin-11` | Record every long operation permanently (what was asked for, by whom, its progress, and how it ended) outliving both the process that asked and the workflow history | the `operations` table, `main_services/processing/database/operations.py` |
| `F-admin-12` | Run long operations in a container of their own, with its own memory and CPU budget and the datastore volumes mounted read-only, so they cannot take capacity from ingestion | `hoover4-ops`, `tasks/run_worker.py:run_operations_worker` |
| `F-admin-13` | Refuse a second dispatch of the same kind of operation against the same target while one is still running, naming what is in the way | `database/operations.py:assert_lock_free` |
| `F-admin-14` | Submit a long operation from the command line and follow it, where interrupting the command detaches from the work rather than stopping it | `main.py add-disk-dataset`, `main.py reindex-collection`, `main.py purge-dataset --apply`, `main.py retry-failed-files --apply`, `tasks/P_ops/cli.py` |
| `F-admin-15` | List, inspect, re-run and cancel operations from the command line | `main.py operations list\|show\|rerun\|cancel` |
| `F-admin-16` | Browse the operations log in the interface (newest first, paginated, filtered by state and by collection) with progress, estimate, outcome and the error against each row | `/admin/operations`, `website/backend/src/api/admin/operations.rs` |
| `F-admin-17` | Re-run or cancel an operation from the interface, where a destructive kind is refused until the target is typed out | `admin_rerun_operation`, `admin_cancel_operation` |
| `F-admin-18` | See the same operations log scoped to one collection, on that collection's page | `CollectionOperationsPanel`, `website/frontend/src/pages/admin/collection_detail.rs` |
| `F-admin-19` | Show how many documents an operation failed on, so a run that finished over failed documents does not read as a clean one | `tasks/P_ops/activities.py:sample_dataset_progress`, the row's `detail` |
| `F-admin-20` | Show the failure rate of each task type against a configured threshold, calling out the types above it as candidate tooling limitations | `admin_list_operations`, `error_rate_alert_percent` |
| `F-admin-21` | Delete or purge a dataset, change its OCR languages or retry its failed files from the interface, each as an operation: one lock, one row, and progress that counts rows deleted or plans re-run rather than stages returned | `admin_delete_dataset`, `admin_apply_ocr_languages`, `admin_retry_failed_task`, `tasks/P_ops/workflows.py` |
| `F-admin-22` | Show the newest operation touching a dataset on that dataset's own page, from the same log the operations page reads, so the two cannot describe one run differently | `DatasetOperationStrip`, `dataset_ocr.rs:latest_operation` |
| `F-admin-23` | Back a collection up into one directory under a configured root (its objects, its database and its search tables, in that order) with a manifest naming every artifact, its size, its checksum and the collection's own configuration rows | `main.py export-collection`, the `export_collection` operation, `tasks/P_ops/backup.py` |
| `F-admin-24` | Report a backup's progress from the stores' own byte counts, one named phase per store, and leave a failed or cancelled run in a directory that blocks no later attempt | `tasks/P_ops/backup.py`, the row's `detail` |
| `F-admin-25` | Restore a collection from one of those directories (its objects, its database, its search tables and its configuration rows) into an empty collection of the same name, refusing a target that still holds data by naming what is in the way | `main.py import-collection`, the `import_collection` operation, `tasks/P_ops/restore.py` |

## Identity and access

| id | capability | owned by |
|---|---|---|
| `F-auth-01` | No route mints a session; every route requires an already-resolved identity except `/favicon.ico` | `website/backend/src/auth/route_policy.rs` |
| `F-auth-02` | Accept an identity asserted by a reverse proxy, on every route | `website/backend/src/auth/session_middleware.rs` |
| `F-auth-04` | Restrict a collection to the groups granted it, and resolve every per-collection read after the permission check | `db_auth/`, `website/backend/src/db_utils/clickhouse_utils.rs` |
| `F-auth-05` | Rate-limit chat, polling and API calls per user, with a ladder that decays for human-paced traffic and is flat for machine-paced polling | `website/backend/src/api/rate_limit.rs` |
| `F-auth-06` | Resolve an artefact id to its owner and refuse a foreign one with a permission failure, not a missing row | `website/backend/src/db_chat/artifacts.rs` |
