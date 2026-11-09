# Hoover4 ai_services: the optional GPU tier

GPU-backed embeddings / NER / reranking (`hoover4-ai-server`), the language model
(`hoover4-vllm`), and GPU EasyOCR (`hoover4-easyocr-gpu`).

> **Standalone.** This tier is fully optional and has **no
> dependencies on anything else**: no external network, nothing here calls into
> `main_services`. The MCP servers and research agents live in
> [`main_services/agents/`](../main_services/agents/README.md) instead. They read
> ClickHouse and Manticore directly, so they belong to the always-on stack. `main_services`
> reaches this tier over the published ports only, using the `[ai_services] host` and
> `*_port` values from an **identical copy** of `hoover4.ini` (copied by hand to both
> hosts).

> **SECURITY (hard requirement).** The two hosts must share a **private network or
> VPN**. NER, embeddings and EasyOCR are UNAUTHENTICATED, and vLLM's API key is its
> only protection. An exposed `hoover4-vllm` is a free GPU for the internet; an
> exposed EasyOCR endpoint is a free DoS surface. Set `[ai_services] bind_ip` in
> `hoover4.ini` to the private interface.

## What runs here

Every service is an optional overlay under [compose/](compose), selected by `hoover4.ini` flags:

| Overlay | Service | Port (ini key) | Enabled by | Purpose |
|---|---|---|---|---|
| [compose/ai-server.yaml](compose/ai-server.yaml) | `hoover4-ai-server` | 21961 (`ai_server_port`) | `ai_server_enabled` | Embeddings, reranking, NER. Also serves the pipeline's P4 stage (`NER_URL`). |
| [compose/vllm.yaml](compose/vllm.yaml) | `hoover4-vllm` | 21960 (`vllm_port`) | `llm_enabled` | The language model (**Qwen3.8 Flash Next**, FP4) on vLLM, OpenAI-compatible. It serves agent turns and every short call. The switch is off by default, and the stack then has no language model. See [The model server](#the-model-server). |
| [compose/easyocr.yaml](compose/easyocr.yaml) | `hoover4-easyocr-gpu` | 21962 (`easyocr_port`) | `easyocr_enabled` | GPU OCR over HTTP ([`easyocr_server/`](easyocr_server/README.md)). Speaks the same request contract as the CPU twin `main_services/ocr_tesseract`, so [tasks/ocr_client.py](../main_services/processing/tasks/ocr_client.py) posts one request shape to either. |

## Deploy

From the repo root, with `hoover4.ini` in place (`[ai_services] enabled = true`):

```bash
./deploy --ai-services                 # start the enabled overlays
./deploy --ai-services --build         # rebuild images (force-recreates)
./deploy --ai-services --down
./deploy --ai-services --reset         # empty the volume folders; model caches preserved
./deploy --ai-services --print-command # show what would run
```

When `llm_enabled` is true, [deploy.py](../deploy.py) starts the tier in stages, because the model server
cannot start while the other GPU services hold memory, and its load takes more memory than
its steady state.

1. It stops every GPU container of the tier.
2. It starts `hoover4-vllm` alone and waits until `/health` answers, for at most 3,600 s.
   It stops with an error when the container exits first.
3. It asks "What is the capital of France?" with thinking off. It stops with an error when
   no answer names Paris within 60 s of attempts.
4. It starts the other enabled services.

The overlays `ai-server-after-llm.yaml` and `easyocr-after-llm.yaml` make `compose up` start
those services only after `hoover4-vllm` is healthy. The Docker daemon restarts containers
after a host restart by their restart policy, and it does not read `depends_on`. Run
`./deploy --ai-services` after a host restart to get the staged order.

[deploy.py](../deploy.py) preflights the GPU before anything starts: `nvidia-smi` must work, and on
podman a CDI spec must exist (`sudo nvidia-ctk cdi generate
--output=/etc/cdi/nvidia.yaml` if not). It also prunes stale CDI mounts. A partial
driver upgrade leaves `/etc/cdi/nvidia.yaml` entries pointing at files that were never
installed, and crun refuses to start the GPU containers over the missing bind source,
which looks like a GPU problem and is not. **The durable fix is to bring every
`nvidia-*` package to the same version**; until then `nvidia-ctk cdi generate` will
reintroduce the bad entries.

The private `ai_services` network is created by [deploy.py](../deploy.py) with explicit DNS
settings. Fresh podman networks have no DNS until resolvers are attached. It is created
carrying the `com.docker.compose.project` / `com.docker.compose.network` labels compose
would have set itself, because docker compose refuses to adopt a network that lacks them
and fails the whole `up`; podman-compose does not check, so the labels only start
mattering on plain docker.

### Model caches

The cache folders under `[storage] volumes_path` are `ai_models_cache` (~6 GB),
`qwen_flash_hf` (~96 GiB), `qwen_flash_cache` and `easyocr_models_cache` (~100 MB).
`./deploy --ai-services --reset` keeps them. Pass `--reset-caches` to empty them too.
EasyOCR keeps its own folder rather than sharing the ai-server's: the two hold
different model layouts, and overlaying EasyOCR's flat `*.pth` files on a HuggingFace
`hub/` tree works only for as long as the two never pick the same name.

### CUDA and GPU architecture

Both images take their torch wheels from the **CUDA 13 index**
(`download.pytorch.org/whl/cu130`), not from PyPI and not from cu126. That index is the
first one that publishes, for **x86_64 and aarch64 alike**, wheels carrying `sm_120`
kernels, which is what a Blackwell card needs. A GB10 reports compute capability
**12.1** and runs those `sm_120` cubins; the cu126 index has no aarch64 build of the
pinned torch at all, so on ARM the build fails outright at dependency resolution rather
than at first inference.

`torch`, `torchvision` and `torchaudio` move as a set, and the set is chosen as the
newest one published for **both** architectures: torchvision's aarch64 wheels lag torch
by one minor, so it is torchvision that decides which triple is available, not torch.

### Podman specifics

* GPUs are requested with `devices: nvidia.com/gpu=all` (CDI). The
  `deploy.resources.reservations.devices` block docker-compose uses is **silently
  ignored** by podman-compose. Services appeared to start and then ran on CPU.
* `HEALTHCHECK` in a Dockerfile is dropped for OCI images, so healthchecks are declared
  in the compose overlays.
* The GPU services share one device. The KV pool of the model server is a byte cap in
  [compose/vllm.yaml](compose/vllm.yaml). See [Memory](#memory).

### Testing

Python here runs **in containers only**. The host has almost no tooling.

```bash
cd ai_services/hoover4_ai_server
docker run --rm --network ai_services -v "$PWD":/w -w /w \
    -e AI_SERVER_TEST_URL=http://hoover4-ai-server:8000 \
    --entrypoint sh hoover4-ai-server:local \
    -c 'pip -q install pytest requests && python -m pytest tests/ -q'
```

The runtime image carries the server module and nothing else (no `tests/`, no pytest)
so the suite is mounted in rather than run with `docker exec`. `AI_SERVER_TEST_URL`
defaults to `http://localhost:21961`; point it at a container name on the `ai_services`
network as above, or at a remote GPU host.

## The model server

hoover4 supports one language model on the Spark (GB10): Qwen3.8 Flash Next, served by vLLM
in `hoover4-vllm`. `[ai_services] llm_enabled` starts it. It serves agent turns and every
short call. `QWEN_FLASH_ENV` in [deploy.py](../deploy.py) holds the identity of the model, and the engine
arguments are literals of [compose/vllm.yaml](compose/vllm.yaml). A change of either is a code change.

| value | |
|---|---|
| checkpoint | `nvidia/Qwen3.8-Flash-Next-FP4-Local` |
| checkpoint commit | `b9ce18a6887e18c089fdea8509a33e63429a3300` |
| served name | `qwen3.8-flash-next` |
| base image | `eugr/spark-vllm-b12x`, pinned by digest |
| image | `hoover4-qwen-flash:b12x-03a95654` |
| context, sequences | 262,144 tokens, 8 |
| KV pool | 9 GB at fp8 (`--kv-cache-memory-bytes`) |
| container memory limit | 90g |

`QWEN_FLASH_ENV` is part of `HOOVER4_CONFIG_FINGERPRINT`, so two hosts with different
[deploy.py](../deploy.py) revisions report different fingerprints.

### The image

The recipe is github.com/devopsfortunato/Qwen3.8-Flash-Next-FP4-Local-DGX-Spark at `6aab1a5`
(MIT). The compose build of `hoover4-vllm` starts from the base image of the recipe and
applies [qwen_flash/ple_queue_depth.py](qwen_flash/ple_queue_depth.py). The patch lets `PLE_QUEUE_DEPTH` set the
queue depth of the PLE table reads from NVMe, and the compose file sets 256. The build stops
when the patched FlashInfer file has another sha256 than the one that the patch is made
against. To move the build, change `QWEN_FLASH_BASE_IMAGE` and `QWEN_FLASH_IMAGE` in
[deploy.py](../deploy.py), make the patch again against the new base, and run
`./deploy --ai-services --build`.

The PLE table is read from NVMe with `io_uring`, which the default seccomp profile refuses.
The service therefore runs with `seccomp=unconfined` and `apparmor=unconfined`.

### The weights and the caches

The engine downloads the checkpoint at the pinned commit into the folder `qwen_flash_hf`
under `[storage] volumes_path` on its first start, about 96 GiB. It compiles its kernels into
the folder `qwen_flash_cache`, which holds the vLLM, FlashInfer, b12x and Triton caches. A
first start takes about 30 minutes, so the health check allows 3,600 s for the start.

### The KV cache

vLLM keeps one paged KV pool for every request. `--enable-prefix-caching` with
`--mamba-cache-mode align` caches the state of the hybrid layers at block boundaries. A short
call, such as a title or a board label, uses a few blocks and does not remove the cached
prefix of a conversation. The oldest free blocks go first when the pool is full.

A measurement on one GB10 with a 20 GB pool sent the first turn of 4 conversations of about
55,700 tokens, then 20 short calls of about 2,000 tokens, then a second turn of each
conversation. Each second turn read 55,659 to 55,722 cached tokens and gave its first token
in 0.44 s. Each first turn gave its first token in 24 s. The pool holds about 50,570 tokens
for each GB, so 9 GB holds about 455,000 tokens.

### Memory

On GB10 the GPU allocations come from host memory, and they cannot go to swap. A GPU
allocation fails before the kernel stops a process. `mem_limit` bounds only the host pages
of the container, so it does not cap the GPU memory of the engine. The engine holds about
74.5 GiB beside the KV pool, and `--kv-cache-memory-bytes` sets the pool. The pool size
leaves room for `hoover4-ai-server` and GPU EasyOCR at their highest use. A start needs about
90 GiB of available memory, mostly for the page cache of the weight files.

### Speed

With thinking off and outputs of 256 tokens, one request decodes about 35 tokens a second,
and 8 requests decode about 102 tokens a second together.

The templates set the limits of `[main_services]` below. Each is a time that a person
waits, and neither is a bound of the model.
[Known defects](../docs/development/Known_Defects.md#chat-context-handling-depends-on-model-information)
gives the consequences.

| key | what it limits | value, s |
|---|---|---:|
| `llm_request_timeout_seconds` | one model call, its wait in the model server's queue included | 3,600 |
| `agent_queue_wait_seconds` | the wait of one step for a free slot | 5,400 |
| `title_request_timeout_seconds` | the title request | 120 |

### The API key

vLLM asks for `Authorization: Bearer <key>` on `/v1` when the key file in
`vllm_api_key_file` holds a key. The compose wrapper reads the key file and adds `--api-key`
to `vllm serve`. An empty key file turns the key off.

### Requests

The server parses reasoning with the `qwen3` parser and tool calls with the `qwen3_xml`
parser. A request can send `chat_template_kwargs` with `enable_thinking` false to turn
thinking off. `LLM_SEND_TEMPERATURE = false`, which [deploy.py](../deploy.py) always renders, makes the
agents, their compaction summary and the title call leave `temperature` out. The server then
applies the sampling values of the checkpoint's `generation_config.json`: temperature 1.0,
top_k 20 and top_p 0.95. The model reads images.

### Token streaming

`LLM_STREAMING=true` is the default of the research agents. An earlier vLLM sent streamed
tool-call deltas with no `arguments`, and the agent then made no tool call.
[research_agent/agent.py](../main_services/agents/research_agent/research_agent/agent.py) keeps the `disable_streaming` workaround and its comment. The
symptom to look for is an agent that answers with no tool calls.
