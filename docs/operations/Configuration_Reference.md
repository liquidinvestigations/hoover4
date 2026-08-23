# Configuration reference

`hoover4.ini` at the repository root is the single source of configuration. Every key here is
in the annotated template `hoover4.ini.example`, which carries the defaults and the reasoning
per key, and this page is the map of what each group decides and which code reads it.

## Contents

- [How configuration flows](#how-configuration-flows)
- [The standing rule about keys](#the-standing-rule-about-keys)
- [`[ai_services]`](#ai_services)
- [`[main_services]`](#main_services)
- [`[llm_provider.*]`](#llm_provider)
- [Secrets](#secrets)
- [Every key, by section](#every-key-by-section)

## How configuration flows

```
hoover4.ini  ->  deploy.py  ->  generated .env beside each compose file  ->  container environment
```

One direction only. **Never hand-edit a generated `.env`**: the next deploy overwrites it,
and the change looks like it worked until then. `./deploy --print-env` renders the files and
shows them without starting anything, and `docker exec <c> env` reports what the container
has at runtime. The two disagreeing is a finding rather than a curiosity.

The two sides render separately. `[ai_services]` feeds the accelerated tier's compose
project; `[main_services]` feeds everything else. The two hosts hold **identical copies** of
this file, copied by hand, which is why the stack verification compares a configuration
fingerprint between them: it will drift.

## The standing rule about keys

**A key that is rendered and read by nothing is a lie.** Several have reached a worker's
environment with no consumer, and the feature they named silently did not exist.

When adding a key, grep for its consumer **in the same change**, or record it here as
not-yet-implemented. `website/tools/check-spec-drift.sh` reports keys in the template that
this page does not name, and keys that nothing in the tree reads.

**Ports are keys, not literals.** A connection refused against a hard-coded number is usually
the port having moved. The website's port is the single exception, because a person types it.

## `[ai_services]`

Thirty-one keys. Read by `deploy.py`, by the tier's compose overlays, and by the model
server itself.

| group | keys | decides |
|---|---|---|
| tier | `enabled`, `host`, `bind_ip` | whether the tier exists, where the main stack reaches it, and which interface it binds |
| local model server | `llm_selfhosted`, `vllm_*` | whether a self-hosted chat model runs, and its image, model, served name, context length, concurrent sequences, memory fraction, and the parsers for its tool and reasoning output |
| model server | `ai_server_enabled`, `ai_server_port`, `*_concurrency` | the embeddings, reranking and entity service, and how many of each it will do at once |
| models | `ner_enabled`, `embeddings_enabled`, `embeddings_model`, `embeddings_dim`, `reranker_enabled`, `reranker_model`, `half_precision`, `torch_compile` | which capabilities load, and at what precision |
| OCR | `easyocr_enabled`, `easyocr_port`, `easyocr_languages` | the accelerated OCR service |
| credentials | `vllm_api_key_file`, `hf_token_file` | paths to files outside the repository, never values |

**`embeddings_dim` must match the model.** It is a stored column width, not a hint: changing
the model without it produces vectors the store rejects or silently truncates.

## `[main_services]`

Seventy-seven keys. Read by `deploy.py`, the main compose files, the worker and the website.

### Which provider serves what

`ner_provider`, `embeddings_provider`, `pdf_ocr_provider`, and the twin switches
`ner_spacy_enabled`, `tesseract_cpu_enabled`, `ocr_pdf_enabled`. These pick between the
accelerated tier and the CPU twins on the main side. See
[AI services](../architecture/AI_Services.md) for why the twins live there.

`gpu_fallback`, `gpu_connect_timeout_ms` and `gpu_circuit_break_seconds` are the fallback
behaviour itself, read by `main_services/processing/tasks/remote.py`: whether to retry
against the twin on a connect failure, how long a connect may take, and how long a failing
endpoint stays out of rotation.

### Scanning and OCR

`tesseract_languages` is what the CPU OCR image can serve. It is baked into the image, so a
language added here needs a rebuild. `regex_scanner_threads` and `regex_scanner_queue_depth`
bound the pattern scanner's runtime and its admission control.

### The website

`website_release_mode` picks between the development server and a release build.
`demo_mode` decides whether anonymous visitors exist at all. See
[Chat and agents](../architecture/Chat_And_Agents.md) for what it grants.
`search_max_parallelism` and `search_timeout_seconds` bound the search fan-out; leaving them
empty takes the code's defaults.

### Worker fleet and concurrency

`common_workers`, `worker_mem_limit`, and the per-queue concurrency keys
(`common_concurrency`, `tika_concurrency`, `ocr_concurrency`, `nlp_concurrency`,
`embed_concurrency`, `indexing_concurrency`). Empty means the default.

**More workers is rarely the answer to a slow pipeline.** The workflow engine serialises
decisions within one execution, so a fan-out driven from a single parent is a latency ceiling
that no fleet size moves: `.agents/skills/tuning-the-pipeline/` has the measurement that
distinguishes the two cases.

### Bind addresses and ports

`website_bind_ip` and `infra_bind_ip` decide which interface each half publishes on. **Which
address a given deployment uses is not in this tree**. It is in
`INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and gitignored.

Everything else in this group is a port key: the datastores, the workflow service and its
stores, the admin consoles, the processing services, the MCP servers, the two agent services,
and the symbol-navigation server. `main_services/ops/Readme.md` lists them with their
defaults and what each answers.

### Data and infrastructure versions

`testdata_dir` and `datasets_mount_path` are where the corpus lives and where it is mounted.
`temporal_history_shards` is the one key that **cannot be changed in place**: the persistence
store refuses to open a keyspace initialised with a different count, so changing it requires
`./deploy --reset-temporal`. The deploy preflights the running cluster against the file and
names both numbers rather than letting the server die with a store error.

The pinned versions (of the workflow service and its UI, the history and visibility stores,
and the object store, which is pinned by digest as well as tag) are here so that a rebuild
is reproducible. `garage_capacity` sizes the object store's advertised capacity.

`serena_enabled` and `serena_port` control the symbol-navigation server, which is development
tooling and is published on loopback only.

## `[llm_provider.*]`

One section per provider, each with the same four keys: `enabled`, `base_url`, `model`, and
`api_key_file`. Exactly the shape of a provider entry, repeated, so adding one is a section
rather than a code change.

`api_key_file` is a **path**, and the file lives outside the repository, chmod-600,
bind-mounted read-only. A key value never appears in this file.

Which model a given chat profile uses is *not* here: that is a runtime setting under
`/admin/llm`, per profile, with an unset value meaning "use the default chat model". The
provider section says which providers exist; the admin surface says which model each profile
asks for.

## Secrets

Three keys name files rather than values: the local model server's API key, the token for the
model hub, and the shared secret for the MCP servers. All three are files outside the
repository, bind-mounted read-only.

**No key value belongs in any tracked file or in any log line.** Where a deployment keeps
them is recorded in `INFRASTRUCTURE_INVENTORY.md`, by location, never by value.

## Every key, by section

The drift check joins on key names, so every key in `hoover4.ini.example` appears here
literally. The template carries each one's default and the reasoning behind it; this index
is the map back to the group above that explains it.

### `[ai_services]`: the accelerated tier

- `enabled`, `host`, `bind_ip`, `llm_selfhosted`
- `vllm_port`, `vllm_image`, `vllm_model`, `vllm_served_name`
- `vllm_gpu_fraction`, `vllm_max_model_len`, `vllm_max_num_seqs`, `vllm_tool_parser`
- `vllm_reasoning_parser`, `vllm_api_key_file`, `ai_server_enabled`, `ai_server_port`
- `ner_enabled`, `embeddings_enabled`, `embeddings_model`, `embeddings_dim`
- `reranker_enabled`, `reranker_model`, `half_precision`, `torch_compile`
- `ai_server_ner_concurrency`, `ai_server_embed_concurrency`, `ai_server_rerank_concurrency`, `hf_token_file`
- `easyocr_enabled`, `easyocr_port`, `easyocr_languages`

### `[main_services]`: everything else

- `ner_provider`, `ner_spacy_enabled`, `embeddings_provider`, `pdf_ocr_provider`
- `tesseract_cpu_enabled`, `tesseract_languages`, `ocr_pdf_enabled`, `regex_scanner_threads`
- `regex_scanner_queue_depth`, `website_release_mode`, `search_max_parallelism`, `search_timeout_seconds`
- `common_workers`, `common_concurrency`, `worker_mem_limit`, `tika_concurrency`
- `ocr_concurrency`, `nlp_concurrency`, `embed_concurrency`, `indexing_concurrency`
- `gpu_fallback`, `gpu_connect_timeout_ms`, `gpu_circuit_break_seconds`, `serena_enabled`
- `serena_port`, `demo_mode`, `testdata_dir`, `datasets_mount_path`
- `mcp_shared_secret_file`, `website_bind_ip`, `infra_bind_ip`, `clickhouse_http_port`
- `clickhouse_native_port`, `manticore_sql_port`, `manticore_http_port`, `garage_s3_port`
- `garage_admin_port`, `redis_port`, `temporal_grpc_port`, `temporal_http_port`
- `temporal_ui_port`, `clickhouse_monitoring_port`, `ch_ui_port`, `cassandra_port`
- `elasticsearch_port`, `pdf_to_html_port`, `tesseract_cpu_port`, `ocr_pdf_port`
- `ner_spacy_port`, `embeddings_cpu_port`, `regex_entity_scanner_port`, `mcp_collections_port`
- `mcp_metasearch_port`, `mcp_browser_port`, `mcp_whois_port`, `mcp_todo_port`
- `internal_search_agent_port`
- `full_research_agent_port`, `cassandra_version`, `elasticsearch_version`, `temporal_version`
- `temporal_ui_version`, `temporal_history_shards`, `garage_version`, `garage_image_digest`
- `garage_capacity`

### `[llm_provider.selfhosted]`

- `enabled`, `base_url`, `model`, `api_key_file`

### `[llm_provider.nvidia]`

- `enabled`, `base_url`, `model`, `api_key_file`

### `[llm_provider.moonshot]`

- `enabled`, `base_url`, `model`, `api_key_file`
