# Configuration reference

`hoover4.ini` at the repository root is the single source of configuration. Every key here is
in the two annotated templates, `hoover4.ini.release` and `hoover4.ini.development`, which
carry the defaults and the reasoning per key, and this page is the map of what each group
decides and which code reads it.

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

**A key that is rendered and read by nothing is false.** Several have reached a worker's
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

`enabled = false` turns the GPU services off. Main services then clear each URL that points
to the GPU tier. The CPU spaCy endpoint stays available through `ner_provider = spacy`.
The per-service flags do not turn GPU services on.

**`embeddings_dim` must match the model.** It is a stored column width, not a hint: changing
the model without it produces vectors the store rejects or silently truncates.

## `[main_services]`

Seventy-eight keys plus the six chat and agent cap keys. Read by `deploy.py`, the main compose files, the worker and the website.

### Which provider serves what

`ner_provider`, `embeddings_provider`, `pdf_ocr_provider`, and the twin switches
`ner_spacy_enabled`, `tesseract_cpu_enabled`, `ocr_pdf_enabled`. These pick between the
accelerated tier and the CPU twins on the main side. See
[AI services](../architecture/AI_Services.md) for why the twins live there.

`ner_provider` accepts `gpu`, `spacy`, `both`, and `none`. `none` leaves `NER_URL` empty.

`gpu_fallback`, `gpu_connect_timeout_ms` and `gpu_circuit_break_seconds` are the fallback
behaviour itself, read by `main_services/processing/tasks/remote.py`: whether to retry
against the twin on a connect failure, how long a connect may take, and how long a failing
endpoint stays out of rotation.

### Scanning and OCR

`tesseract_languages` is what the CPU OCR image can serve. It is baked into the image, so a
language added here needs a rebuild. `regex_scanner_threads` and `regex_scanner_queue_depth`
bound the pattern scanner's runtime and its admission control.

`tesseract_cpu_concurrency` (default `2`) is the number of OCR requests
`hoover4-tesseract-cpu` runs at once, and its request queue holds 4 times that number.
`tesseract_threads_per_page` sets `OMP_THREAD_LIMIT`, the threads of one page. Empty leaves
the variable unset. `tesseract_cpu_cpus` is the container's CPU limit, and empty is no
limit. `tesseract_cpu_mem_limit` (default empty) is its memory limit. Empty is 4096M plus
1024M for each unit of `tesseract_cpu_concurrency`, so the default concurrency of 2 gives
6144M. A set value replaces the formula. `deploy.py` refuses a `tesseract_cpu_cpus` above the
CPU count of the host. `deploy.py` prints a
warning when `ocr_concurrency` is lower than `tesseract_cpu_concurrency`, because the
worker then leaves Tesseract slots idle.

### The website

`website_release_mode` picks between the development server and a release build.
`search_max_parallelism` and `search_timeout_seconds` bound the search fan-out; leaving them
empty takes the code's defaults. `max_held_polls_per_user` is how many chat polls one user
may hold at once. `rate_chat_poll_per_minute` is the flat poll ceiling per user.

`development_auth_backdoor_enabled` switches on `hoover4-development-auth-backdoor`, a
header-setting reverse proxy that asserts a fixed identity on every request, with no
sign-in step. Default `false`: a deployment that omits this key, or copies
`hoover4.ini.release`, publishes the website's own port and runs no such container.
`hoover4.ini.development` sets it to `true`. When it is on, the backdoor container
takes the published port instead of the website, because the two cannot both bind it.

`proxy_username` and `proxy_groups` are the identity the backdoor asserts when it runs,
as `X-Forwarded-User` and the other three headers `parse_headers` in
`website/backend/src/auth/session_middleware.rs` reads. A production deployment leaves
`development_auth_backdoor_enabled` at `false` and puts `oauth2-proxy` in front of the
website instead, which asserts a real identity the same way. `proxy_groups` is
comma-separated with no space. A group named `admin` or `superuser` makes the asserted
user an administrator.

### Worker fleet and concurrency

`common_workers`, `worker_mem_limit`, and the per-queue concurrency keys
(`common_concurrency`, `tika_concurrency`, `ocr_concurrency`, `nlp_concurrency`,
`embed_concurrency`, `indexing_concurrency`, `chat_model_concurrency`,
`chat_low_latency_concurrency`, `research_concurrency`). Empty means the default, except
the three chat keys, which are set: a slot is one turn in flight, not one model call.

`common_max_cached_workflows` (default `100`) is the number of workflow runs that each
common-worker process keeps in memory. The SDK default is 1000.

`browser_max_contexts` is live Chromium processes on `hoover4-mcp-browser`, one per chat.
`mcp_browser_mem_limit` is that container's memory ceiling. `agent_subagent_concurrency`
is how many subagent workers one `run_subagent` call may start at once.
`full_research_agent_workers` is uvicorn worker processes on `hoover4-full-research-agent`.

`internet_tools_enabled` starts `hoover4-mcp-browser`, `hoover4-mcp-metasearch` and
`hoover4-mcp-whois`. Default off: an absent or empty key does not start them. Turning it
off on a workstation also removes the developer harness tools those containers publish.
`hoover4-full-research-agent` then binds only collections and todo. Capture wrappers
refuse when the key is off.

`hoover4-internal-search-agent` and `hoover4-full-research-agent` start only when an LLM
provider is enabled (see [`[llm_provider.*]`](#llm_provider)). With no provider, `deploy.py`
selects no research-agent overlay and removes the agent containers of an earlier deploy.

**More workers is rarely the answer to a slow pipeline.** The workflow engine serialises
decisions within one execution, so a fan-out driven from a single parent is a latency ceiling
that no fleet size moves: `.agents/skills/tuning-the-pipeline/` has the measurement that
distinguishes the two cases.

### Bind addresses and ports

`website_bind_ip` and `infra_bind_ip` decide which interface each half publishes on. **Which
address a given deployment uses is not in this tree**. It is in
`INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and gitignored.

**Neither key is ever set to `0.0.0.0`.** Both templates and `deploy.py`'s own defaults use
`127.0.0.1`. `website_bind_ip` carries the whole access boundary in release mode, because the
website accepts `X-Forwarded-User` from whoever connects, so a caller that reaches port
`12345` directly is the user it names. The infrastructure ports carry no authentication at
all. Widen `website_bind_ip` only to the single private address the identity provider dials,
and reach the infrastructure ports through an ssh tunnel.

Everything else in this group is a port key: the datastores, the workflow service and its
stores, the admin consoles, the processing services, the MCP servers, the two agent services,
and the symbol-navigation server. `main_services/ops/Readme.md` lists them with their
defaults and what each answers.

### Data and infrastructure versions

`testdata_dir` and `datasets_mount_path` are where the corpus lives and where it is mounted.
`temporal_history_shards` is the one key that **cannot be changed in place**: the persistence
store refuses to open a keyspace initialised with a different count, so changing it requires
`./deploy --reset-temporal`. The deploy preflights the running cluster against the file and
names both numbers rather than letting the server die with a store error. The default
is `128`.

### Temporal and its Cassandra

| key | default | what it sets |
|---|---|---|
| `cassandra_mem_limit` | `16000M` | the memory limit of `temporal-cassandra` |
| `cassandra_cpus` | `8` | its CPU limit |
| `cassandra_heap` | `8G` | `MAX_HEAP_SIZE` |
| `cassandra_heap_new` | empty | `HEAP_NEWSIZE`. Empty is 100M for each CPU of `cassandra_cpus` |
| `cassandra_direct_memory` | `2G` | `-XX:MaxDirectMemorySize`, through `JVM_EXTRA_OPTS` |
| `cassandra_malloc_arenas` | empty | `MALLOC_ARENA_MAX`. Empty keeps the image default of 4 |
| `cassandra_chunk_cache_mb` | `512` | `file_cache_size_in_mb` in `cassandra.yaml`, written by `cassandra-entrypoint.sh` at each start |
| `temporal_mem_limit` | `8000M` | the memory limit of `temporal` |
| `temporal_cpus` | `8` | its CPU limit |
| `temporal_retention` | `168h` | how long the default namespace keeps a closed workflow |
| `temporal_history_persistence_qps` | empty | `history.persistenceMaxQPS` |
| `temporal_frontend_persistence_qps` | empty | `frontend.persistenceMaxQPS` |
| `temporal_matching_persistence_qps` | empty | `matching.persistenceMaxQPS` |

`deploy.py` refuses a `cassandra_mem_limit` smaller than `cassandra_heap` plus
`cassandra_direct_memory` plus 3G, and names the three values. It refuses a `cassandra_cpus`
or a `temporal_cpus` above the CPU count of the host, because Docker then refuses to start
the container. The message names the key, its value and the CPU count. The container reservation is
5000M, or the limit when the limit is smaller.

The server sets `temporal_retention` only when it creates the namespace. After each
`compose up`, `deploy.py` therefore waits up to 120 s for Temporal and runs
`temporal operator namespace update --retention`. A failure stops the deploy.

Temporal reads one dynamic config file. `deploy.py` renders
`temporal-dynamicconfig/generated.yaml` from the tracked `docker.yaml` and each rate limit
that is set. An empty rate limit keeps Temporal's own default.

### Container logs

`container_log_max_size` (default `100m`) and `container_log_max_files` (default `5`) set
the `json-file` log rotation of every hoover4 container, on the main stack and on the GPU
tier. `deploy.py` writes both values into the `.env` file of each side. Podman records only
the size, and ignores `container_log_max_files`.

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

The drift check joins on key names, so every key in `hoover4.ini.release` appears here
literally. The templates carry each one's default and the reasoning behind it. This index
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
- `tesseract_cpu_concurrency`, `tesseract_threads_per_page`, `tesseract_cpu_cpus`, `tesseract_cpu_mem_limit`
- `regex_scanner_queue_depth`, `website_release_mode`, `search_max_parallelism`, `search_timeout_seconds`
- `common_workers`, `common_concurrency`, `common_max_cached_workflows`, `worker_mem_limit`, `tika_concurrency`
- `ocr_concurrency`, `nlp_concurrency`, `embed_concurrency`, `indexing_concurrency`
- `chat_model_concurrency`, `chat_low_latency_concurrency`, `research_concurrency`
- `max_held_polls_per_user`, `rate_chat_poll_per_minute`, `browser_max_contexts`
- `agent_subagent_concurrency`, `mcp_browser_mem_limit`, `full_research_agent_workers`
- `internet_tools_enabled`
- `gpu_fallback`, `gpu_connect_timeout_ms`, `gpu_circuit_break_seconds`, `serena_enabled`
- `serena_port`, `development_auth_backdoor_enabled`, `proxy_username`, `proxy_groups`
- `testdata_dir`, `datasets_mount_path`
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
- `garage_capacity`, `ops_backup_object_volume_bytes`
- `cassandra_mem_limit`, `cassandra_cpus`, `cassandra_heap`, `cassandra_heap_new`
- `cassandra_direct_memory`, `cassandra_malloc_arenas`, `cassandra_chunk_cache_mb`
- `temporal_mem_limit`, `temporal_cpus`, `temporal_retention`
- `temporal_history_persistence_qps`, `temporal_frontend_persistence_qps`, `temporal_matching_persistence_qps`
- `container_log_max_size`, `container_log_max_files`

### `[llm_provider.selfhosted]`

- `enabled`, `base_url`, `model`, `api_key_file`

### `[llm_provider.nvidia]`

- `enabled`, `base_url`, `model`, `api_key_file`

### `[llm_provider.moonshot]`

- `enabled`, `base_url`, `model`, `api_key_file`
