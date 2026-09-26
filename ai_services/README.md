# Hoover4 ai_services: the optional GPU tier

GPU-backed embeddings / NER / reranking (`hoover4-ai-server`), a local LLM
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

Every service is an optional overlay under `compose/`, selected by `hoover4.ini` flags:

| Overlay | Service | Port (ini key) | Enabled by | Purpose |
|---|---|---|---|---|
| `compose/ai-server.yaml` | `hoover4-ai-server` | 21961 (`ai_server_port`) | `ai_server_enabled` | Embeddings, reranking, NER. Also serves the pipeline's P4 stage (`NER_URL`). |
| `compose/vllm.yaml` | `hoover4-vllm` | 21960 (`vllm_port`), 21963 (`vllm_structured_port`) | `llm_selfhosted` | The agent model (**DiffusionGemma 26B-A4B**, NVFP4), OpenAI-compatible, and its structured server. Off by default; a cloud provider serves the stack until it is turned on. |
| `compose/easyocr.yaml` | `hoover4-easyocr-gpu` | 21962 (`easyocr_port`) | `easyocr_enabled` | GPU OCR over HTTP ([`easyocr_server/`](easyocr_server/README.md)). Speaks the same request contract as the CPU twin `main_services/ocr_tesseract`, so `tasks/ocr_client.py` posts one request shape to either. |

## Deploy

From the repo root, with `hoover4.ini` in place (`[ai_services] enabled = true`):

```bash
./deploy --ai-services                 # start the enabled overlays
./deploy --ai-services --build         # rebuild images (force-recreates)
./deploy --ai-services --down
./deploy --ai-services --reset         # empty the volume folders; model caches preserved
./deploy --ai-services --print-command # show what would run
```

`deploy.py` preflights the GPU before anything starts: `nvidia-smi` must work, and on
podman a CDI spec must exist (`sudo nvidia-ctk cdi generate
--output=/etc/cdi/nvidia.yaml` if not). It also prunes stale CDI mounts. A partial
driver upgrade leaves `/etc/cdi/nvidia.yaml` entries pointing at files that were never
installed, and crun refuses to start the GPU containers over the missing bind source,
which looks like a GPU problem and is not. **The durable fix is to bring every
`nvidia-*` package to the same version**; until then `nvidia-ctk cdi generate` will
reintroduce the bad entries.

The private `ai_services` network is created by `deploy.py` with explicit DNS
settings. Fresh podman networks have no DNS until resolvers are attached. It is created
carrying the `com.docker.compose.project` / `com.docker.compose.network` labels compose
would have set itself, because docker compose refuses to adopt a network that lacks them
and fails the whole `up`; podman-compose does not check, so the labels only start
mattering on plain docker.

### Model caches

The cache folders under `[storage] volumes_path` are `ai_models_cache` (~6 GB),
`dgemma_model` (~19 GB), `dgemma_cache` and `easyocr_models_cache` (~100 MB).
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
* The GPU services share one device. `vllm_gpu_fraction` (default `0.60`) is the setting to
  turn down first if any of them OOMs, and it is a fraction of the **whole** device,
  which on unified-memory hardware means total system memory, not a card's own.

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

## The local LLM: DiffusionGemma 26B-A4B

`hoover4-vllm` serves `nvidia/diffusiongemma-26B-A4B-it-NVFP4` under the model name
`dgemma`. The checkpoint is a mixture of experts with 26B parameters, of which 4B are
active for each token, at NVFP4. The server takes text, image input, thinking and tool
calls. It serves a context of 262,144 tokens.

### The image

Docker BuildKit builds the image from the Git repository in `vllm_build_repo` at the
commit in `vllm_build_ref`. The build context is the Git URL with `#<commit>`, so no file
of that repository is in this one. The image tag is `hoover4-vllm-dgemma:<commit>`. To
move the build, change `vllm_build_ref` and run `./deploy --ai-services --build`.

The entrypoint of the image composes the `vllm serve` arguments from the container
environment. `deploy.py` renders that environment from `[ai_services]`. The entrypoint
starts vLLM on container port 8000, and then the structured server on container port
8011. `vllm_port` publishes the first and `vllm_structured_port` publishes the second.
Both bind to `bind_ip`, which must be a private-network address.

### The weights

The weights are the folder `dgemma_model` under `[storage] volumes_path`. Before the first
start, `./deploy --ai-services` runs the built image once and downloads `vllm_model` into
that folder. The download of about 19 GB runs for minutes, and it continues a partial folder. A
folder is complete when it holds `config.json` and every shard that
`model.safetensors.index.json` names, each above zero bytes. A later deploy does not
download a complete folder again. `deploy.py` stops with an error when the folder is still
incomplete after the download.

The checkpoint is not gated, so `hf_token_file` can stay empty. The server itself runs
with `HF_HUB_OFFLINE=1`. The folder `dgemma_cache` holds the compile and JIT cache at
`/root/.cache`. A first start compiles the FlashInfer kernels before the weights load, so
the health check allows 1,800 s for the start.

### The API key

vLLM asks for `Authorization: Bearer <key>` on `/v1` when the key file in
`vllm_api_key_file` holds a key. The structured server asks for the same key on every
POST. The compose wrapper reads the key file, exports the key for both servers, and then
runs the entrypoint of the image unchanged.

The structured server calls vLLM with no key. `dgemma/sitecustomize.py` adds the key to
each call from inside the container to the local vLLM port, and changes no other call.
The wrapper puts `/opt/hoover4`, where that folder is mounted, first on `PYTHONPATH`, so
Python loads the module in every process of the container. The module then runs a
`sitecustomize` of the image, if the image has one. An empty key file turns the key off
on both servers.

### Memory

The server shares the unified memory of the GPU box with the other model servers.

| key | default | what it sets |
|---|---|---|
| `vllm_gpu_fraction` | `0.60` | the fraction of the whole device that vLLM takes |
| `vllm_kv_cache_gb` | `28` | the KV cache in GiB |
| `vllm_headroom_gb` | `4` | the memory in GiB that the start-up check keeps free |
| `vllm_transient_copies` | `2` | the sampler copies that the start-up check budgets for |
| `vllm_torch_mem_fraction` | `0.85` | the fraction of memory that PyTorch can allocate |
| `vllm_mem_limit` | `97g` | the memory limit of the container |

The entrypoint prints a `memory:` line with the memory available and the memory it needs.
The memory it needs is the sum of the weights, the KV cache, the start-up transient and
the headroom. The entrypoint refuses to start when the memory available is less. The KV cache must hold `vllm_max_num_seqs`
sequences at the full context. Read both from the log:

```
docker logs hoover4-vllm 2>&1 | grep -E "memory:|refusing|GPU KV cache size|Maximum concurrency"
```

The line `Maximum concurrency for 262,144 tokens per request` must read at least
`vllm_max_num_seqs`. When it reads less, increase `vllm_kv_cache_gb` by one.

### Request parameters that the server rejects

vLLM answers a request with a 400 error when it carries `temperature`, `min_p`, `seed`,
`min_tokens`, `logit_bias`, `bad_words` or `allowed_token_ids`. A client of this server
must leave them out. It can send `chat_template_kwargs` with `enable_thinking`, which
wins over `vllm_default_thinking`.

### Differences from the vLLM recipe

The vLLM recipe for this checkpoint, section "Full-Featured Server", with the NVFP4 variant
on DGX Spark GB10, is the reference for the served features. This deployment differs from
it in these arguments.

| argument | recipe | here | why |
|---|---|---|---|
| image | `vllm/vllm-openai:gemma` | the build of `vllm_build_ref` | the build adds the adaptive canvas schedule and the structured server |
| `--served-model-name` | not set | `dgemma` (`vllm_served_name`) | a short name for the clients |
| `--gpu-memory-utilization` | 0.8 | 0.60 (`vllm_gpu_fraction`) | the box runs other model servers |
| `--kv-cache-memory` | not set | 28 GiB (`vllm_kv_cache_gb`) | a fixed KV cache for 8 sequences at the full context |
| `--diffusion-config` | canvas 256 | canvas 256, 32 samples, and a canvas schedule by batch size (`vllm_canvas`, `vllm_max_samples`, `vllm_canvas_schedule`) | the schedule makes a smaller canvas at a larger batch |
| `--exclude-tools-when-tool-choice-none`, `--trust-remote-code`, `--async-scheduling`, `--max-logprobs 128`, `VLLM_USE_V2_MODEL_RUNNER=1` | not set | set by the entrypoint | the entrypoint of the build sets them, and the vLLM patches of the build need `--async-scheduling` |
| `--chat-template` | the recipe names a tool chat template | not set (`vllm_chat_template`) | the model's own template is used until a measurement shows that tool calls need the other |

Every other argument of the recipe is set to the recipe's value. `--mm-processor-kwargs`,
`--limit-mm-per-prompt`, `--default-chat-template-kwargs` and `--load-format` come from
`vllm_image_input`, `vllm_mm_max_soft_tokens`, `vllm_mm_image_limit`,
`vllm_default_thinking` and `vllm_load_format`. `deploy.py` joins them into
`VLLM_EXTRA_ARGS`, which the entrypoint adds to `vllm serve`. The entrypoint splits that
value on spaces, so no JSON value in it holds a space.

### Token streaming

`LLM_STREAMING=true` is the default of the research agents. An earlier vLLM sent streamed
tool-call deltas with no `arguments`, and the agent then made no tool call.
`research_agent/agent.py` keeps the `disable_streaming` workaround and its comment. The
symptom to look for is an agent that answers with no tool calls.
