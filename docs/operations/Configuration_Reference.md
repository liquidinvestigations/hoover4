# Configuration reference

`hoover4.ini` at the repository root is the single source of configuration. This page explains
what each group of keys decides and which code reads it.

## Contents

- [How configuration flows](#how-configuration-flows)
- [Start from a sample.](#start-from-a-sample)
- [Check the file before a deployment.](#check-the-file-before-a-deployment)
- [Replace a removed key.](#replace-a-removed-key)
- [Store credential file paths in configuration.](#store-credential-file-paths-in-configuration)
- [`[storage]`](#storage)
- [`[ai_services]`](#ai_services)
- [`[main_services]`](#main_services)
- [`[dataset_mount.*]`](#dataset_mount)
- [`[operations]`](#operations)
- [`[processing_updates]`](#processing_updates)
- [`[uploads]`](#uploads)
- [Model endpoints](#model-endpoints)
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

## Start from a sample.

Two tracked samples are at the repository root. Copy one of them to `hoover4.ini` and edit the copy.

- `hoover4.ini.release` is for a deployment that other people use.
- `hoover4.ini.development` is for a host that only its developer can reach.

Each sample sets every key that an operator can set. A value is the default of
[deploy.py](../../deploy.py), or a value that both samples choose, for example the agent timeouts.
A key has at most one full-line `#` comment above it. This page holds the longer explanations.
The samples differ only in these keys of `[main_services]`.

| Key | Release sample | Development sample |
|---|---|---|
| `website_release_mode` | `true` | `false` |
| `development_auth_backdoor_enabled` | `false` | `true` |

Both samples set `internet_tools_enabled = false` and `web_tor_enabled = true`. Tor therefore
starts only after you turn on the internet tools. Both samples have the dataset mount
`[dataset_mount.testdata]` with the host folder `/opt/hoover4-testdata`. Create that folder, or
change the section, before the first deployment. `[storage] volumes_path` is empty in both
samples, and a deployment refuses it until you set an absolute host folder.

[The render tests](../../scripts/deploy.py_tests/Readme.md) check the keys, the values and the
comment layout of both samples.

## Check the file before a deployment.

[deploy.py](../../deploy.py) reads the file before every command, including `--print-env` and
`--print-command`. It refuses the file when it finds one of these problems:

- A section that this page does not describe. A `[DEFAULT]` section is such a section, and
  its keys do not go into the other sections.
- A key that its section does not have.
- A removed key or section. The message names the setting that replaces it, or states that no
  setting replaces it.
- A value that starts with `;` or `#`, or that has a space or a tab and then `;` or `#`. The
  parser removes no comment after a value, so write each comment on its own line above its key.
- A `[dataset_mount.<name>]` section with a name that is not 1 to 32 characters of `a-z`,
  `0-9` and `_`, or with a key other than `host_path`, `container_path` and `writable`.
- A repeated section, or a repeated key in one section.

The message names the section and the key of each problem, and it does not show the value.
A `;` or `#` inside a value with no space before it stays part of the value. A key that the file does not
set keeps its default. The file must set `[storage] volumes_path`. The file of the main side
must also set `manticore_mem_limit` and `manticore_vectors_mem_limit`, and it must have at
least one `[dataset_mount.<name>]` section.

`./deploy --check` validates the file and stops. It needs `hoover4.ini` and does not read a
sample in its place. It renders the environment of both sides in memory. It validates the
boolean, number, port and size values that the two renders read. It also runs the refusals
that depend only on the file. A file with `[ai_services] enabled = false` can be valid.

`./deploy --check --ai-services` checks the file of a host that runs only the GPU side. It
refuses the structural problems of the list above in every section. Then it renders only the
GPU side and runs the refusals of that side that depend only on the file. The file needs no
Manticore limit and no dataset mount. It must set `[ai_services] enabled = true`.

The command prints `configuration valid` and exits with status 0. Otherwise it prints the
problems and exits with status 1. It writes no file, creates no folder, runs no command and
contacts no service. It cannot be used with another action flag.

A file with a structural problem gets no value check. Each later check reports only its
first problem.

Some refusals need the host or a running service, so only a deployment runs them. They check
the secret files, the CPU count of the host and the dataset mount folders. They also check the
GPU, its CDI specification, free ports and the compose files. Two more read the Temporal
shard count and probe each writable dataset mount.

## Replace a removed key.

A file that sets a removed key or section is refused. The message names the replacement, or
states that no setting replaces it. `REMOVED_SETTINGS` in [deploy.py](../../deploy.py) is the
complete list.

| Removed setting | Action |
|---|---|
| `[llm_provider.*]` sections, `[ai_services] llm_selfhosted` and `chat_llm_selfhosted` | Delete them and set `[ai_services] llm_enabled`. |
| `[ai_services]` model and capacity keys `vllm_*` and `chat_vllm_*`, other than `vllm_port` and `vllm_api_key_file` | Delete them. [deploy.py](../../deploy.py) sets these values for the supported model server. |
| `[ai_services] vllm_structured_port`, `chat_vllm_port` | Delete them. One model server serves every call on `vllm_port`. |
| `[ai_services] hf_token_file`, `embeddings_model`, `embeddings_dim`, `reranker_model`, `half_precision` and `torch_compile` | Delete them. The model servers and the AI server use fixed models. |
| `[main_services] ner_provider` and `embeddings_provider` | Use `[ai_services] ner_enabled` and `embeddings_enabled`. |
| `[main_services] testdata_dir` and `datasets_mount_path` | Add a `[dataset_mount.<name>]` section. |
| `[main_services] garage_capacity` | Move the key to `[storage]`. |
| `[main_services] tesseract_languages`, `[ai_services] easyocr_languages` and `[operations] change_ocr_languages_cap` | Delete them. Automatic OCR selects the languages of each page. |
| `[main_services] cassandra_version`, `elasticsearch_version`, `temporal_version`, `temporal_ui_version`, `garage_version` and `garage_image_digest` | Delete them. The compose files hold the versions. |
| `[main_services] embeddings_cpu_port`, `gpu_fallback` and `agent_compaction_model` | Delete them. |
| `[main_services] serena_enabled` and `serena_port` | Delete them. The Serena development server is removed. |
| `[main_services] agent_packs_planner`, `agent_packs_organizer`, `agent_packs_subagent`, `agent_plan_run_budget`, `research_concurrency`, `agent_max_page_tokens` and `agent_completion_reserve_tokens` | Delete them. |
| `[cluster]` | Delete the section. Give the registry address to [publish-images.sh](../../main_services/ops/publish-images.sh) as its first argument. |

## Store credential file paths in configuration.

**A key that is rendered and read by nothing is false.** Several have reached a worker's
environment with no consumer, and the feature they named silently did not exist.

When adding a key, grep for its consumer **in the same change**, or record it here as
not-yet-implemented. [website/tools/check-spec-drift.sh](../../website/tools/check-spec-drift.sh) reports keys in the release sample that
this page does not name, and keys that nothing in the tree reads.

**Ports are keys, not literals.** A connection refused against a hard-coded number is usually
the port having moved. The website's port is the single exception, because a person types it.

## `[storage]`

Two keys. `volumes_path` is read by [deploy.py](../../deploy.py) on both sides. It is mandatory, and it must be an
absolute host path, for example `/srv/hoover4-volumes`. Each host sets its own value.
`garage_capacity` (default `300G`) is the capacity that the object store declares for its node.
The store sizes its partitions from it and reports itself full above it. [deploy.py](../../deploy.py) does not measure the disk.

Every container keeps its data in a folder `<volumes_path>/<volume name>`, which the compose
files bind-mount. [deploy.py](../../deploy.py) creates `volumes_path`, its parents and the folders of the
selected side, and it halts with the path when it cannot. Before `compose up`, it gives each
folder the owner that its service writes as, from the `VOLUMES` table in [deploy.py](../../deploy.py). A
command that starts containers and the reset flags refuse an empty or relative value.
`--down` runs with any value, and `--print-env` prints the refusal as a warning. The reset
flags empty folders. They never remove a folder.

The website mounts the volume folder `hoover4-upload-tmp` at `/upload-tmp` as its upload space.
It holds the transfer journals and the bytes of files that are still arriving. It also holds
complete files that wait for placement. Its reset class is `data`, so `--reset` empties it. A batch that has
not placed its files then loses them, and its owner must upload them again. Placed files are
in the dataset folder and stay. Compose uses separate mounts for upload space and dataset folders.
Placement copies files across these mounts, including mounts on the same host file system.
[deploy.py](../../deploy.py) prints this copy requirement for each writable dataset mount.

Manticore uses version 29.9.0. Its data folders retain the `_v14` names for existing installations.
Deployment creates each daemon's authentication file when it is absent and preserves an existing file.

## `[ai_services]`

Eighteen keys. Read by [deploy.py](../../deploy.py), by the tier's compose overlays, and by the model
server itself.

| group | keys | decides |
|---|---|---|
| tier | `enabled`, `host`, `bind_ip` | whether the tier exists, where the main stack reaches it, and which interface it binds |
| language model | `llm_enabled`, `vllm_port` | whether the self-hosted model server runs, and its port. The model, its checkpoint commit and its capacity are constants of [deploy.py](../../deploy.py) ([the model server](../../ai_services/README.md)) |
| model server | `ai_server_enabled`, `ai_server_port`, `*_concurrency` | the embeddings, reranking and entity service, and how many of each it will do at once |
| capabilities | `ner_enabled`, `embeddings_enabled`, `reranker_enabled` | which capabilities load, and which endpoints the main side receives. The models, the embedding dimension and the precision are constants of [the model server](../../ai_services/hoover4_ai_server/README.md) |
| OCR | `easyocr_enabled`, `easyocr_port` | the accelerated OCR service. Its language groups are constants of [the EasyOCR server](../../ai_services/easyocr_server/README.md) |
| credentials | `vllm_api_key_file` | the path of the API key file of the model server, never the value |

NER, embeddings, reranking and EasyOCR have no authentication. The model servers accept only
the key of `vllm_api_key_file`. Connect the two hosts through a private network, and set
`bind_ip` to the private address of the GPU host.

`enabled = false` turns the GPU services off. Main services then clear each URL that points
to the GPU tier. NER then has no endpoint, because NER runs on the GPU only.
The per-service flags do not turn GPU services on.

The main side reads `ai_server_enabled`, `ner_enabled` and `embeddings_enabled` of its own file.
`NER_URL` is set only when `enabled`, `ai_server_enabled` and `ner_enabled` are true.
`EMBEDDINGS_URL` follows the same rule with `embeddings_enabled`, and `RERANK_URL` also needs `reranker_enabled`.
An empty URL makes the stage skip its work. Set `ner_enabled = false` or `embeddings_enabled = false` to turn a capability off.

## `[main_services]`

[deploy.py](../../deploy.py), the main compose files, the worker, and the website read these keys.

### Which provider serves what

`pdf_ocr_provider`, and the twin switches `tesseract_cpu_enabled`, `ocr_pdf_enabled`. These
select the OCR services on the main side. See
[AI services](../architecture/AI_Services.md) for why the twins live there.
NER and embeddings have no provider key. The `[ai_services]` capability switches decide their endpoints.

`gpu_connect_timeout_ms` and `gpu_circuit_break_seconds` are read by
[main_services/processing/tasks/remote.py](../../main_services/processing/tasks/remote.py): how long a connect may take, and how long a failing
endpoint stays out of rotation. Each capability has one endpoint, so a call has no second endpoint to try.

### Scanning and OCR

OCR selects the installed model of each page from its detected script and language. No key
selects OCR languages. `./deploy` refuses the removed keys `[main_services]
tesseract_languages`, `[ai_services] easyocr_languages` and `[operations]
change_ocr_languages_cap`. The Tesseract image installs Debian language models. The EasyOCR
image installs a fixed set of language groups and reports them.

The `ocr` step of a processing update keeps earlier OCR text of a page when the stored
recognition languages include the detected language of the page. It publishes that text under
the detected language without a new OCR request. It builds the image PDF or the searchable PDF
part again from the stored pages. Entity extraction, embedding and indexing then run again for
the file. Only pages without a compatible earlier result get new OCR. A page with an unknown
detected language keeps its earlier output under its original identity.
When detection succeeds and finds no text on a page, the step replaces earlier OCR text of
that page with the empty result. It retires the earlier text only after it publishes the empty
result. When detection is missing or fails, the file stays incomplete and keeps its earlier
output. [The parse stage guide](../../main_services/processing/tasks/P3_parse_files/Readme.md#earlier-ocr-output-is-reconciled-before-new-ocr)
describes the rules.

`regex_scanner_threads` and `regex_scanner_queue_depth`
bound the pattern scanner's runtime and its admission control. The scanner takes a slot
before it reads or parses a scan request body. `regex_scanner_mem_limit` (default `4G`)
sets its container memory limit.

`clamav_enabled` (default `true`) starts `hoover4-clamav` and turns on the antivirus scan
of each file before parsing. When it is off, the worker tier `clamav` still runs and
records each file as `skipped_disabled`. `clamav_concurrency` (default `4`) is the number
of scans that clamd runs at once, and the worker tier sends at most that many. The
scanner front holds 4 times that number of waiting requests and answers 503 to more.
`clamav_update_signatures` (default `true`) runs freshclam in the container. When it is
off, the scanner uses the signatures of its image build. `clamav_mem_limit` (default
`4G`) is the container memory limit.

`clickhouse_ui_mem_limit` and `clickhouse_monitoring_mem_limit` set the memory
limits of the two ClickHouse interface containers. Each defaults to `6000M`.

`tesseract_cpu_concurrency` (default `2`) is the number of OCR requests
`hoover4-tesseract-cpu` runs at once, and its request queue holds 4 times that number.
`tesseract_threads_per_page` sets `OMP_THREAD_LIMIT`, the threads of one page. Empty leaves
the variable unset. `tesseract_cpu_cpus` is the container's CPU limit, and empty is no
limit. `tesseract_cpu_mem_limit` (default empty) is its memory limit. Empty is 4096M plus
1024M for each unit of `tesseract_cpu_concurrency`, so the default concurrency of 2 gives
6144M. A set value replaces the formula. [deploy.py](../../deploy.py) refuses a `tesseract_cpu_cpus` above the
CPU count of the host. [deploy.py](../../deploy.py) prints a
warning when `ocr_concurrency` is lower than `tesseract_cpu_concurrency`, because the
worker then leaves Tesseract slots idle.

`ocr_pdf_files_per_batch` defaults to `4`.
It limits separate part activity lists for each engine and file group.
Each list sends its requests sequentially.
The builder slot limit still controls simultaneous requests.
`pdf_preview_concurrency` defaults to `2` and limits Office PDF conversions on the preview queue.

`ocr_pdf_concurrency` is the number of searchable PDFs that `hoover4-ocr-pdf` builds at
once, one render process each. Empty follows `tesseract_cpu_concurrency`, or gives 2 when
`tesseract_cpu_enabled` is false. The same value sizes the worker queue of searchable-PDF
batches, so the worker never sends the builder more requests than it runs. The pages of
one PDF go to the OCR service one after the other. `ocr_pdf_queue_depth` is the number of
requests that wait for a builder slot, and empty follows `ocr_pdf_concurrency`.
The builder preserves source PDF pages and adds invisible OCR overlays to selected pages.
It streams source and output objects through temporary files.
The source split target adds no builder byte cutoff.
Its input, page, and raster pixel budgets remain independent.
`ocr_pdf_mem_limit` is the builder's memory limit. Empty is the larger of 8000M and 2048M
plus 512M for each builder slot. A set value replaces the formula.

[deploy.py](../../deploy.py) prints two more warnings. One names an `ocr_pdf_mem_limit` below that formula.
The other names an `ocr_concurrency` plus `ocr_pdf_concurrency` above 5 times
`tesseract_cpu_concurrency`. Tesseract admits that many requests, its slots and its
queue. Above it, Tesseract answers 503, and the builder fails the whole PDF with 503.
An empty `ocr_concurrency` counts as its default of 4 in that sum.

Both OCR services raise the thread limit of their request handlers to their admission
plus 4, so every admitted request has a thread. Their `/health` answers report
`concurrency`, `queue_depth` and `http_threads`.

### Scanner and ClickHouse settings

`regex_scanner_mem_limit` defaults to `4G`. Deployment refuses values below 4 GiB.
ClickHouse query, part, and async insert logs retain three days of events.
The default user profile enables query logging and uses blocks of at most 8192 rows.
It disables parallel input parsing and output formatting and uses one download thread.
These profile settings load from the mounted `users.d` override.

### The website

`manticore_expansion_limit` limits wildcard term expansion in page searches. It defaults to 5000.
Zero disables the limit. Structure searches do not use it.
The website and collection tools use the same expansion limit and search time budget.
A limit can exclude documents that contain only less frequent matching terms.

`website_release_mode` picks between the development server and a release build. The code
default is `false`. The release sample sets `true`, and the development sample sets `false`.
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
[website/backend/src/auth/session_middleware.rs](../../website/backend/src/auth/session_middleware.rs) reads. A production deployment leaves
`development_auth_backdoor_enabled` at `false` and puts `oauth2-proxy` in front of the
website instead, which asserts a real identity the same way. `proxy_groups` is
comma-separated with no space. A group named `admin` or `superuser` makes the asserted
user an administrator.

### Tika parser limits

`tika_parse_processes` defaults to `4`.
`tika_parse_heap` defaults to `1g` for each parser process.
`tika_mem_limit` defaults to `6G` for the server container.
An empty `tika_concurrency` uses the parser process count.
A configured concurrency must equal that count.
Deployment requires memory for all parser heaps plus one GiB.

[deploy.py](../../deploy.py) generates the server configuration from these keys.
The configuration disables request overrides and embedded document parsing.
It limits output to 20,000,000 characters and keeps a truncation flag.
The XML general and total entity size limits use the same finite value.
The entity expansion count and external entity restrictions remain active.

### Worker fleet and concurrency

`common_workers`, `worker_mem_limit`, and the per-queue concurrency keys
(`common_concurrency`, `tika_concurrency`, `ocr_concurrency`, `ocr_pdf_concurrency`,
`nlp_concurrency`, `embed_concurrency`, `indexing_concurrency`, `chat_model_concurrency`,
`chat_low_latency_concurrency`, `agent_tool_concurrency`). Empty
means the default, except the three agent keys, which are set. `ocr_concurrency` sizes
image OCR on `processing-ocr-queue`. `ocr_pdf_concurrency` sizes the builder and the
worker slots of `processing-ocr-pdf-queue` together. A slot of
`chat_model_concurrency` is one model call in flight, and a slot
of `agent_tool_concurrency` is one tool call in flight. The samples set 3, 4 and 16.
An empty key gives 3 for `chat_model_concurrency` and 8 for
`chat_low_latency_concurrency` and 16 for `agent_tool_concurrency`.

`common_max_cached_workflows` (default `100`) is the number of workflow runs that each
common-worker process keeps in memory. The SDK default is 1000.

`indexing_workers` is the number of index-worker processes on `processing-indexing-queue`.
Empty gives 4, and both samples set 8. Each process has `indexing_concurrency`
slots, 1 by default. The email graph runs in one more process of its own, on
`processing-email-graph-queue` with one slot, and no key changes that count.

`browser_max_contexts` limits interactive Chromium processes, one per agent run.
`mcp_browser_mem_limit` is the browser container's memory ceiling.
Page reads and metasearch source fetches use separate shared browsers and bounded tab queues.

| Main service key | Default | Behavior |
|---|---|---|
| `browser_reader_tabs` | `4` | This setting limits concurrent reader tabs. |
| `browser_search_tabs` | `2` | This setting limits concurrent metasearch browser tabs. |
| `browser_queue_limit` | `32` | This setting limits waiting requests in each shared browser queue. |
| `browser_read_timeout_seconds` | `180` | This setting bounds a complete page-read call. |
| `browser_fetch_token_file` | Empty. | This setting names the private token file shared by browser and metasearch containers. |
| `web_search_concurrency` | `4` | This setting limits concurrent web-search calls. |
| `web_search_queue_limit` | `16` | This setting limits waiting web-search calls. |
| `web_search_queue_wait_seconds` | `60` | This setting bounds the web-search queue wait. |
| `web_search_fetch_budget_seconds` | `60` | This setting bounds source fetching across all queries in one call. |
| `web_tor_enabled` | `true` | This setting enables private Tor clients when internet tools are enabled. |
| `web_tor_mem_limit` | `512M` | This setting limits Tor container memory. |

Create a private, nonempty token file before enabling browser-backed search sources.
Set its path through `browser_fetch_token_file` and restrict host file access to the deployment user.
An empty file disables the internal source-fetch route and reports degraded browser source access.
Tor fallback uses two clients with isolated request identities and no published ports or control interface.
A Tor container health response verifies listeners.
Live source requests must verify circuit availability separately.

`agent_packs_chat` selects chat tool packs as a comma-separated list or `all`.
The available packs are `catalogue`, `skills`, `collections`, `conversation`, `web`, and `browser`.
Every chat receives the `skills` pack.
[deploy.py](../../deploy.py) refuses the removed research configuration keys.
The agent service sends all
available tools with each model call and refuses an unknown pack name.
The results of one model step share 24,000 bytes, and each call gets an equal part. No key
changes that. `./deploy` refuses the removed keys `agent_max_page_tokens` and
`agent_completion_reserve_tokens`. `agent_catalogue_match_count` is how
many names one `search_agent_tools` call returns, from 6 to 12. Empty means 6. `./deploy`
refuses a value that is not a whole number in range. The tool limit probe selects this
value.
`full_research_agent_workers` is uvicorn worker processes on `hoover4-full-research-agent`.

The timeout keys set the step limits of an agent run, in whole seconds. An empty key keeps the
code default. An agent run has no time limit of its own: 600 model steps bound it.
`agent_queue_wait_seconds` is how long one model step or one tool call may wait for a free
slot. A model step that waits longer fails the run, and empty sets no limit. The samples
set 5400. `title_request_timeout_seconds` (empty: 30) is the read timeout of the
conversation title request, and the title activity allows two requests and 30 s more.
`board_reason_request_seconds` (empty: 600) is the read timeout of one board assessment
request. Temporal sends the request once more after a transport failure. The samples set
600.
`llm_request_timeout_seconds` is the read timeout of one agent model call and of the
compaction summary, and the worker's limit of one model step. When it is set, the model
client does not retry. Empty keeps the client default of 600 s and 2 retries, 180 s for the
summary and 3,600 s for the model step. The samples set 3600. `./deploy` refuses a value
that is not a whole number of at least 1. The worker's limits that have no key are in
[tasks/P_agent/model_timeouts.py](../../main_services/processing/tasks/P_agent/model_timeouts.py): 300 s for a tool call, a 30 s heartbeat limit for each
step, 600 model steps, and a continue-as-new every 250 model steps. The other liveness
bounds do not have keys either: the agent's keepalive line every 30 s, the worker's 300 s
read of the agent stream and the website's 180 s stall window.

`agent_compaction_fraction` is the fraction of the model's stated context window at which
the agent compacts the context of a model call, to a third of that size. It replaces one
older prefix of steps with one summary. The samples and the code default set 0.80. An
empty key keeps the code default. The compacted list is kept for the later calls of the
conversation. The answering model writes the summary.

`agent_max_output_tokens` is the output cap of every agent model request, sent as
`max_completion_tokens`. Empty sends no cap, and the samples set 32768. The agent also
reserves this many tokens of the context window for the reply when it sizes a request. With
no cap, it reserves an estimate of 8,192 tokens and records that the reserve is an estimate.
`llm_streaming` is token streaming of the agent's model calls, and empty is `true`.
Thinking has no key. The "Thinking" checkbox on `/admin/llm` sets it in the
`server_settings` row `llm_thinking`, and an absent row is on. The worker reads the row
before each agent model call. The title call and the compaction summary always send thinking off.

`internet_tools_enabled` starts `hoover4-mcp-browser`, `hoover4-mcp-metasearch` and
`hoover4-mcp-whois`. Default off: an absent or empty key does not start them. Turning it
off on a workstation also removes the developer harness tools those containers publish.
`hoover4-full-research-agent` then receives the tools of its available packs. Capture wrappers
refuse when the key is off.
`factcheck_api_key_file` names the key file of the metasearch fact-check source. Empty
registers no such source.

`hoover4-internal-search-agent` and `hoover4-full-research-agent` start only when
`[ai_services] llm_enabled` and `[ai_services] enabled` are true (see [Model endpoints](#model-endpoints)).
Otherwise [deploy.py](../../deploy.py) selects no research-agent overlay and removes the agent
containers of an earlier deploy.

The chat policy checks of the worker make no model request.
`chat_control_dir` names an absolute host folder with custom policy handlers and
definitions. The worker mounts it read-only. Empty means the built-in handlers and
definitions only.

**More workers is rarely the answer to a slow pipeline.** The workflow engine serialises
decisions within one execution, so a fan-out driven from a single parent is a latency ceiling
that no fleet size moves: [.agents/skills/tuning-the-pipeline/](../../.agents/skills/tuning-the-pipeline) has the measurement that
distinguishes the two cases.

`worker_graceful_shutdown_seconds` (default `60`) is the time that a worker keeps its
in-progress activities at shutdown before it cancels them. [deploy.py](../../deploy.py)
sets the stop grace period of the container to this value plus 30 s, so the cancelled
activities can finish. `hoover4-ops` uses the same value.

### The operations container

`hoover4-ops` runs backups, restores, re-indexes and the other operations that a person
starts. It has its own memory and CPU limits, so an operation cannot take capacity from
ingestion.

| Key | Default | Meaning |
|---|---|---|
| `ops_mem_limit` | `4000M` | The memory limit of `hoover4-ops`. |
| `ops_cpus` | `4` | The CPU limit of `hoover4-ops`. |
| `ops_backup_dir` | Empty. | The host folder for backups, mounted read-write. The folder must exist. Empty uses `<volumes_path>/ops_backups`, which [deploy.py](../../deploy.py) creates. |
| `ops_backup_bandwidth_bytes` | `0` | The read bytes per second of a ClickHouse backup. `0` sets no limit. |
| `ops_backup_object_volume_bytes` | Empty. | The bytes of one backup object volume before the next volume opens. Empty is 8 GiB. [deploy.py](../../deploy.py) refuses a value below 1048576, including `0`. |
| `admin_base_url` | Empty. | The admin address that a detached CLI prints. Empty prints the operation id and the command that shows it. |
| `error_rate_alert_percent` | `5` | The operations page marks a task type when its failure rate is above this percent. |

### Bind addresses and ports

`website_bind_ip` and `infra_bind_ip` decide which interface each half publishes on. **Which
address a given deployment uses is not in this tree**. It is in
`INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and gitignored.

**Neither key is ever set to `0.0.0.0`.** Both samples and [deploy.py](../../deploy.py)'s own defaults use
`127.0.0.1`. `website_bind_ip` carries the whole access boundary in release mode, because the
website accepts `X-Forwarded-User` from whoever connects, so a caller that reaches port
`12345` directly is the user it names. The infrastructure ports carry no authentication at
all. Widen `website_bind_ip` only to the single private address the identity provider dials,
and reach the infrastructure ports through an ssh tunnel.

Everything else in this group is a port key: the datastores, the workflow service and its
stores, the admin consoles, the processing services, the MCP servers and the two agent services.
[main_services/ops/Readme.md](../../main_services/ops/Readme.md) lists them with their
defaults and what each answers.

### Temporal history shards

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
| `temporal_ui_mem_limit` | `6000M` | the memory limit of `temporal-ui` |
| `temporal_cpus` | `8` | its CPU limit |
| `temporal_retention` | `168h` | how long the default namespace keeps a closed workflow |
| `temporal_history_persistence_qps` | empty | `history.persistenceMaxQPS` |
| `temporal_frontend_persistence_qps` | empty | `frontend.persistenceMaxQPS` |
| `temporal_matching_persistence_qps` | empty | `matching.persistenceMaxQPS` |

[deploy.py](../../deploy.py) refuses a `cassandra_mem_limit` smaller than `cassandra_heap` plus
`cassandra_direct_memory` plus 3G, and names the three values. It refuses a `cassandra_cpus`
or a `temporal_cpus` above the CPU count of the host, because Docker then refuses to start
the container. The message names the key, its value and the CPU count. The container reservation is
5000M, or the limit when the limit is smaller.

The server sets `temporal_retention` only when it creates the namespace. After each
`compose up`, [deploy.py](../../deploy.py) therefore waits up to 120 s for Temporal and runs
`temporal operator namespace update --retention`. A failure stops the deploy.

Temporal reads one dynamic config file. [deploy.py](../../deploy.py) renders
`temporal-dynamicconfig/generated.yaml` from the tracked `docker.yaml` and each rate limit
that is set. An empty rate limit keeps Temporal's own default.

### Container logs

`container_log_max_size` (default `100m`) and `container_log_max_files` (default `5`) set
the `json-file` log rotation of every hoover4 container, on the main stack and on the GPU
tier. [deploy.py](../../deploy.py) writes both values into the `.env` file of each side. Podman records only
the size, and ignores `container_log_max_files`.

The versions of the workflow service and its UI, the history and visibility stores, and the
object store are literals of [the main compose file](../../main_services/ops/docker/docker-compose.yaml). The object store is
pinned by digest as well as tag. No `hoover4.ini` key selects a version.

## `[dataset_mount.*]`

Each `[dataset_mount.<name>]` section names one host folder. `hoover4-worker` and
`hoover4-website` mount it at the same container path. The admin dataset form lists the
folders directly beneath each mount and shows the mount name. The name matches
`[a-z0-9_]{1,32}`.

| key | what it sets |
|---|---|
| `host_path` | The absolute host folder. It must exist. |
| `container_path` | The absolute, normalized path in both containers. |
| `writable` | `false` mounts the folder read-only in both services. `true` mounts it read-write in both, and lets the dataset form create a new folder in it. |

`deploy.py` writes the mounts to the generated, gitignored overlay
`main_services/ops/docker/compose/generated-dataset-mounts.yaml`. Every compose command of the
main side includes it. The same overlay sets `HOOVER4_DATASET_MOUNTS`, a JSON list of the name,
container path and `writable` flag of each mount, in both services.
`DATASETS_MOUNT_PATH` keeps the container path of the first mount, by name order.

The file must have at least one `[dataset_mount.<name>]` section. [deploy.py](../../deploy.py) refuses a file without one.
When a `[dataset_mount.testdata]` section exists, `deploy.py` renders its `host_path` as
`HOOVER4_TESTDATA_DIR`, which `verify-stack.sh` uses to check the corpus fixtures.

`deploy.py` refuses these configurations, with a message that names the section and the key.

| Rule | Reason |
|---|---|
| `host_path` is absolute and exists. | Podman refuses a missing bind source, and Docker creates an empty folder owned by root. |
| `container_path` neither contains nor falls beneath a path the services use for code, scratch, secrets, mirrors or system folders, such as `/app`, `/tmp`, `/run` or `/mirror`. | A dataset mount must not cover another mount or the image. |
| No two container paths are equal or contain each other. No two host folders are equal or contain each other after symbolic links are resolved. | An alias or a nested writable mount would make a read-only mount writable. |
| The file has at least one section. | The dataset form needs a folder to list. |
| A writable mount accepts an exclusive create, a write, a sync and a delete in each running service, under the user of that container. | A permission error would otherwise show only at the first new folder or upload. A rootless runtime maps container users to other host users, so a host check is not sufficient. |

The last rule runs after the services start. The others run before any compose command.

## `[operations]`

One key for each operation kind, named `<kind>_cap`, with the default `2`. A cap is the most
operations of that kind that run at once across the deployment. No key covers a group of
kinds. [deploy.py](../../deploy.py) refuses a value below 1 and an unknown key in the
section. It renders the 19 values into one variable, `HOOVER4_OPERATION_CAPS`, in
`hoover4-ops`, as `kind=value` pairs joined by commas. `ingest_upload_cap` limits the
`ingest_upload` operations that the upload queues start, one queue for each upload dataset.
`update_dataset_cap` and `update_collection_cap` limit the processing update operations.
The coordinator starts one automatic update at a time, so these caps limit the manual
updates beside it.

An operation over its cap is stored as `queued`. It waits with no time limit, and the oldest
queued operation of its kind starts when a slot is free. An operation also waits as `queued`
while another running operation of its dataset or collection runs, whatever its kind. A queued
operation holds its dataset or collection. A second operation on that target is refused until the first one ends or is
cancelled. A change to a cap takes effect when `hoover4-ops` is created again,
which `./deploy` does.

## `[processing_updates]`

`automatic` (default `true`) lets the processing update coordinator start update
operations without a person. It starts one at a time after a deployment that changes a
stage version, after a settings change and after new input. `false` starts no automatic
operation. The admin pages still show the waiting steps, and Update processing still
starts them. [deploy.py](../../deploy.py) renders the value into `HOOVER4_PROCESSING_UPDATES_AUTOMATIC` in the
worker, and a change takes effect when the worker is created again.

## `[uploads]`

The limits of one upload batch. The upload page and the `begin` route check the first three
before any byte is sent. [deploy.py](../../deploy.py) renders each key as `HOOVER4_UPLOAD_<KEY>` into
`hoover4-website` and `hoover4-worker`. A change takes effect when the containers are created
again.

| Key | Default | Meaning |
|---|---|---|
| `max_batch_files` | `10000` | The most files in one batch. |
| `max_batch_bytes` | `10737418240` | The most bytes in one batch. |
| `max_file_bytes` | `10737418240` | The most bytes in one file. |
| `chunk_bytes` | `786432` | The most bytes of one tus `PATCH`. Keep it below the body limit of every proxy in front of the website. The default stays below the 1 MiB body limit of an nginx proxy with its default settings. |
| `abandon_hours` | `24` | A batch with no acknowledged chunk for this many hours is committed with the files that arrived. `0` commits every idle batch at the next hourly sweep. |

Each value is a whole number. [deploy.py](../../deploy.py) refuses a value below 1, except `abandon_hours`,
which may be 0. It refuses an unknown key. The path limits are fixed: 64 names, 255
bytes for one name, and 1,024 bytes for a destination path. The `begin` body is at most 16 MiB.

The upload scenarios ran at the defaults with these sizes:

- 1,000 files of 1 KB in one batch
- one file of 256 MiB
- a zip of 1,000 members, and a zip that holds 2 zips of 100 members
- a `begin` body of 16 MiB with 1,000 files

No batch above 1,000 files or 512 MiB was measured.

## Model endpoints

hoover4 uses only its self-hosted model server on the GPU tier. `[ai_services] llm_enabled`
starts `hoover4-vllm`, which serves Qwen3.8 Flash Next with vLLM. [deploy.py](../../deploy.py) refuses
`llm_enabled = true` with `[ai_services] enabled = false`. The model, its Hugging Face
checkpoint commit, its image and its served name are constants of [deploy.py](../../deploy.py)
(`QWEN_FLASH_ENV`). The engine arguments are literals of
[ai_services/compose/vllm.yaml](../../ai_services/compose/vllm.yaml), so a change of the model is a code change.
[The model server](../../ai_services/README.md) describes it. The engine downloads the checkpoint at
its pinned commit into the `qwen_flash_hf` folder on its first start.

[deploy.py](../../deploy.py) renders these variables for the main services from `[ai_services] host`
and `vllm_port`.

| variable | value |
|---|---|
| `LLM_BASE_URL`, `LLM_MODEL` | the model server at `vllm_port`. It serves agent turns of chats and board explores, and every short call: conversation titles and summaries, follow-up suggestions, board labels, board assessments and the classification of board findings. |
| `LLM_VISION_MODELS` | the served model. Both catalog refreshes mark it `supports_vision`, and an agent turn sends it the images of tool results. |
| `LLM_PROVIDER_NAME` | `selfhosted`, the catalog name of the endpoint |
| `LLM_SEND_TEMPERATURE` | `false`, so the server applies the sampling values of the checkpoint |
| `LLM_API_KEY_FILE_HOST` | `vllm_api_key_file`, when it is set |

With `llm_enabled = false` or the GPU tier off, every endpoint variable is empty, so no service
calls a model.

The worker and both agent services send every request to `LLM_BASE_URL`, with the key of
`vllm_api_key_file` or a placeholder when there is none
([tasks/llm_endpoints.py](../../main_services/processing/tasks/llm_endpoints.py), [research_agent/endpoints.py](../../main_services/agents/research_agent/research_agent/endpoints.py)).
The worker runs `main.py refresh-llm-catalog` once at start, and the admin LLM page runs the
website refresh. Compaction of agent turns divides by the context window of that catalog row,
so a model without a row is never compacted.

No page and no `server_settings` key overrides the model: the keys
`llm_default_chat_model`, `llm_summarization_model`, `llm_model_internal_search` and
`llm_model_full_research` are retired, and a stored row of one of them has no effect.
`/admin/llm` shows the model read only.

The `[llm_provider.*]` sections, `llm_selfhosted`, `chat_llm_selfhosted`, `hf_token_file`,
`vllm_structured_port`, `chat_vllm_port` and the earlier `vllm_*` and `chat_vllm_*` model keys
are removed. A file that sets one of them is refused, and the message names the replacement.

## Secrets

Keys that end in `_file` name files rather than values, for example the API key of the model
server and the shared secret of the MCP servers. Each one is a file outside the repository,
bind-mounted read-only.

**No key value belongs in any tracked file or in any log line.** Where a deployment keeps
them is recorded in `INFRASTRUCTURE_INVENTORY.md`, by location, never by value.

## Every key, by section

The drift check joins on key names, so every key in `hoover4.ini.release` appears here
literally. This index maps each key to the group above that explains it.

### `[storage]`: the volume folders

- `volumes_path`, `garage_capacity`

### `[dataset_mount.<name>]`: the dataset folders

- `host_path`, `container_path`, `writable`

### `[ai_services]`: the accelerated tier

- `enabled`, `host`, `bind_ip`, `llm_enabled`
- `vllm_port`, `vllm_api_key_file`
- `ai_server_enabled`, `ai_server_port`
- `ner_enabled`, `embeddings_enabled`, `reranker_enabled`
- `ai_server_ner_concurrency`, `ai_server_embed_concurrency`, `ai_server_rerank_concurrency`
- `easyocr_enabled`, `easyocr_port`

### `[main_services]`: everything else

- `pdf_ocr_provider`
- `tesseract_cpu_enabled`, `ocr_pdf_enabled`, `regex_scanner_threads`
- `manticore_mem_limit`, `manticore_vectors_mem_limit` (required), `clickhouse_mem_limit`, `ocr_pdf_mem_limit`
- `ocr_pdf_concurrency`, `ocr_pdf_queue_depth`
- `tesseract_cpu_concurrency`, `tesseract_threads_per_page`, `tesseract_cpu_cpus`, `tesseract_cpu_mem_limit`
- `clamav_enabled`, `clamav_update_signatures`, `clamav_concurrency`, `clamav_mem_limit`
- `regex_scanner_queue_depth`, `website_release_mode`, `search_max_parallelism`, `search_timeout_seconds`, `manticore_expansion_limit`
- `common_workers`, `common_concurrency`, `common_max_cached_workflows`, `worker_mem_limit`, `tika_concurrency`
- `ocr_concurrency`, `nlp_concurrency`, `embed_concurrency`, `indexing_concurrency`, `indexing_workers`
- `chat_model_concurrency`, `chat_low_latency_concurrency`, `agent_tool_concurrency`
- `max_held_polls_per_user`, `rate_chat_poll_per_minute`, `browser_max_contexts`
- `mcp_browser_mem_limit`, `full_research_agent_workers`
- `agent_packs_chat`
- `agent_catalogue_match_count`
- `agent_queue_wait_seconds`, `title_request_timeout_seconds`
- `board_reason_request_seconds`
- `llm_request_timeout_seconds`
- `agent_max_output_tokens`
- `llm_streaming`
- `internet_tools_enabled`
- `gpu_connect_timeout_ms`, `gpu_circuit_break_seconds`
- `development_auth_backdoor_enabled`, `proxy_username`, `proxy_groups`
- `mcp_shared_secret_file`, `chat_control_dir`, `website_bind_ip`, `infra_bind_ip`, `clickhouse_http_port`
- `clickhouse_native_port`, `manticore_sql_port`, `manticore_http_port`, `manticore_vectors_sql_port`, `manticore_vectors_http_port`, `garage_s3_port`
- `garage_admin_port`, `redis_port`, `temporal_grpc_port`, `temporal_http_port`
- `temporal_ui_port`, `clickhouse_monitoring_port`, `ch_ui_port`, `cassandra_port`
- `elasticsearch_port`, `pdf_to_html_port`, `tesseract_cpu_port`, `ocr_pdf_port`
- `regex_entity_scanner_port`, `mcp_collections_port`
- `mcp_metasearch_port`, `mcp_browser_port`, `mcp_whois_port`, `mcp_todo_port`
- `internal_search_agent_port`
- `full_research_agent_port`, `temporal_history_shards`, `ops_backup_object_volume_bytes`
- `cassandra_mem_limit`, `cassandra_cpus`, `cassandra_heap`, `cassandra_heap_new`
- `cassandra_direct_memory`, `cassandra_malloc_arenas`, `cassandra_chunk_cache_mb`
- `temporal_mem_limit`, `temporal_cpus`, `temporal_retention`
- `temporal_history_persistence_qps`, `temporal_frontend_persistence_qps`, `temporal_matching_persistence_qps`
- `container_log_max_size`, `container_log_max_files`
- `regex_scanner_mem_limit`, `clickhouse_ui_mem_limit`, `clickhouse_monitoring_mem_limit`, `temporal_ui_mem_limit`
- `ocr_pdf_files_per_batch`, `pdf_preview_concurrency`
- `tika_mem_limit`, `tika_parse_processes`, `tika_parse_heap`
- `browser_reader_tabs`, `browser_search_tabs`, `browser_queue_limit`, `browser_read_timeout_seconds`, `browser_fetch_token_file`
- `web_search_concurrency`, `web_search_queue_limit`, `web_search_queue_wait_seconds`, `web_search_fetch_budget_seconds`
- `web_tor_enabled`, `web_tor_mem_limit`, `factcheck_api_key_file`
- `agent_compaction_fraction`, `worker_graceful_shutdown_seconds`
- `ops_mem_limit`, `ops_cpus`, `ops_backup_dir`, `ops_backup_bandwidth_bytes`, `admin_base_url`, `error_rate_alert_percent`

The `clickhouse_server_memory_ratio` key sets the server memory fraction of its container limit.
It defaults to `0.7` and must be above zero and at most one.
Deployment renders this value into the server override XML.

### `[operations]`: the operation caps

- `add_dataset_cap`, `rescan_dataset_cap`, `compute_plans_cap`, `execute_plans_cap`
- `purge_dataset_cap`, `delete_dataset_cap`, `rerun_ocr_cap`, `reindex_collection_cap`
- `refresh_document_locations_cap`, `retry_failed_files_cap`, `ensure_collection_cap`
- `drop_collection_database_cap`, `export_collection_cap`, `import_collection_cap`
- `purge_unattributed_entities_cap`, `backfill_vectors_cap`, `ingest_upload_cap`
- `update_dataset_cap`, `update_collection_cap`

### `[processing_updates]`: the automatic updates

- `automatic`

### `[uploads]`: the upload limits

- `max_batch_files`, `max_batch_bytes`, `max_file_bytes`, `chunk_bytes`, `abandon_hours`
