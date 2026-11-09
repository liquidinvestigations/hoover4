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

Every service is an optional overlay under [compose/](compose), selected by `hoover4.ini` flags:

| Overlay | Service | Port (ini key) | Enabled by | Purpose |
|---|---|---|---|---|
| [compose/ai-server.yaml](compose/ai-server.yaml) | `hoover4-ai-server` | 21961 (`ai_server_port`) | `ai_server_enabled` | Embeddings, reranking, NER. Also serves the pipeline's P4 stage (`NER_URL`). |
| [compose/vllm.yaml](compose/vllm.yaml) | `hoover4-vllm` | 21960 (`vllm_port`), 21963 (`vllm_structured_port`) | `llm_enabled` | The model of short calls (**DiffusionGemma 26B-A4B**, NVFP4), OpenAI-compatible, and its structured server. The switch is off by default, and the stack then has no language model. |
| [compose/vllm-chat.yaml](compose/vllm-chat.yaml) | `hoover4-vllm-chat` | 21964 (`chat_vllm_port`) | `llm_enabled` | The model of agent turns (**Ornith-1.5-35B-A3B**, NVFP4). It runs plain `vllm serve` in the image of `hoover4-vllm`, with the same API key, and starts after `hoover4-vllm` is healthy. See [The chat model server](#the-chat-model-server). |
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
* The GPU services share one device. The GPU fractions of the two model servers are
  constants of [deploy.py](../deploy.py) (`DGEMMA_ENV`, `ORNITH_ENV`). Each is a fraction of the
  **whole** device, which on unified-memory hardware means total system memory, not a
  card's own.

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

## The supported model set

hoover4 supports one model set on the Spark (GB10): dgemma with its structured server, and
ornith. `[ai_services] llm_enabled` starts both servers. [deploy.py](../deploy.py) holds every other
value as a constant, so a change of a model, a commit or a capacity value is a code change.

| value | dgemma (`hoover4-vllm`) | ornith (`hoover4-vllm-chat`) |
|---|---|---|
| checkpoint | `nvidia/diffusiongemma-26B-A4B-it-NVFP4` | `ornith-ai/Ornith-1.5-35B-A3B-NVFP4` |
| checkpoint commit | `ec4ff3df205028f4e81c954c2227f9312b3ec2ea` | `94e431d9cc47fa1986a7a1a4e9a80f7f118b03aa` |
| served name | `dgemma` | `ornith` |
| image | `hoover4-vllm-dgemma:<VLLM_BASE_RELEASE>-<DJEV_SPARK_COMMIT>` | the same image |
| GPU fraction | 0.24 | 0.30 |
| container memory limit | 40g | 48g |
| context, sequences | 262,144 tokens, 4 | 262,144 tokens, 4 |

`MODEL_SERVERS`, `DGEMMA_ENV` and `ORNITH_ENV` in [deploy.py](../deploy.py) hold the complete values.
They are also part of `HOOVER4_CONFIG_FINGERPRINT`, so two hosts with different
[deploy.py](../deploy.py) revisions report different fingerprints.

## The local LLM: DiffusionGemma 26B-A4B

`hoover4-vllm` serves `nvidia/diffusiongemma-26B-A4B-it-NVFP4` under the model name
`dgemma`. The checkpoint is a mixture of experts with 26B parameters, of which 4B are
active for each token, at NVFP4. The server takes text, image input, thinking and tool
calls. It serves a context of 262,144 tokens.

### The image

The compose build of `hoover4-vllm` starts from the vLLM release image
`vllm/vllm-openai:<release>`. [deploy.py](../deploy.py) pins the release in `VLLM_BASE_RELEASE`. A
release tag stays on Docker Hub. A nightly tag is deleted after about a week, so the build
does not start from a nightly.

The build takes its support files from the djev-spark repository at the commit
`DJEV_SPARK_COMMIT` of [deploy.py](../deploy.py): the CUDA header links, the worker memory cap, the entrypoint,
the test pages and the image check. It takes the structured server from the djev
repository at the commit that this djev-spark commit pins. The Dockerfile of djev-spark
is not used, because it starts from a nightly.

The build then applies the patches in [dgemma/vllm-image/](dgemma/vllm-image) to the vLLM package. It stops
when the base reports a vLLM version other than the pinned release, or when a patch does
not apply. The image tag is `hoover4-vllm-dgemma:<release>-<commit>`. To move the build,
change `VLLM_BASE_RELEASE` and make each patch again against the new release. Then run
`./deploy --ai-services --build`.

`diffusion-gemma-stack.patch` adds three DiffusionGemma changes that the release does not
have: the skip of the last self-conditioning step (vllm-project/vllm#58221), engine
samples (vllm-project/vllm#58438), which the structured server uses with
`--engine-samples`, and the load-adaptive canvas width, which `VLLM_CANVAS_SCHEDULE`
sets. The image does not carry the FlashInfer per-request causal change of djev-spark,
because the attention backend is `TRITON_ATTN`.

`parser-arguments.patch` changes the tool call parser of vLLM. A parser that converts the
model's own argument syntax to JSON, such as `gemma4`, streams no argument deltas. It sends
the arguments of a call once, when the call ends. The final parse of malformed model output
can differ from a streamed prefix, and the client cannot take back a prefix that it has
received. Without the patch, the client then holds arguments that are not JSON. The streamed
arguments now equal the arguments of a request without streaming.

[dgemma/vllm-image/check_parser.py](dgemma/vllm-image/check_parser.py) tests the parser of an image against the producer
fixture [main_services/agents/research_agent/tests/producer_fixtures/gemma4_tool_calls.json](../main_services/agents/research_agent/tests/producer_fixtures/gemma4_tool_calls.json).
It feeds each captured raw call to the parser one token at a time, and compares the joined
argument deltas with the parse without streaming. It needs the weights folder for the
tokenizer and no GPU:

```
docker run --rm --entrypoint python3 -e HF_HUB_OFFLINE=1 \
  -v <checkout>/ai_services/dgemma/vllm-image:/check:ro \
  -v <checkout>/main_services/agents/research_agent/tests/producer_fixtures:/fixtures:ro \
  -v <volumes_path>/dgemma_model:/models/dgemma:ro \
  hoover4-vllm-dgemma:<release>-<commit> /check/check_parser.py /fixtures/gemma4_tool_calls.json
```

An image without `parser-arguments.patch` fails the case `streamed_prefix_not_json`, and the patched image passes
every case.

The entrypoint of the image composes the `vllm serve` arguments from the container
environment. [deploy.py](../deploy.py) renders that environment from `DGEMMA_ENV`. The entrypoint
starts vLLM on container port 8000, and then the structured server on container port
8011. `vllm_port` publishes the first and `vllm_structured_port` publishes the second.
Both bind to `bind_ip`, which must be a private-network address.

### The weights

The weights are the folder `dgemma_model` under `[storage] volumes_path`. Before each
start, `./deploy --ai-services` checks the folder. A complete folder holds `config.json`,
`model.safetensors.index.json` and every shard that the index names, each above zero bytes.
The deploy keeps a complete folder when the download metadata of each of these files names
the pinned checkpoint commit. huggingface_hub writes that metadata in
`.cache/huggingface/download/<file>.metadata` of the folder. A checkpoint of one shard has
no index, so a folder with no index needs `config.json` and its `*.safetensors` files.

Otherwise the deploy runs the built image once with `snapshot_download` at the pinned
commit. The download keeps each file that equals the file of that commit, downloads the
other files again, and continues a partial file. The first download of about 19 GB runs for
minutes. [deploy.py](../deploy.py) stops with an error when the folder does not match the pinned commit
after the download. Run `./deploy --ai-services` again to continue an interrupted download.
The deploy changes no other folder.

The checkpoints are not gated, so the download sends no token. The server itself runs
with `HF_HUB_OFFLINE=1`. The folder `dgemma_cache` holds the compile and JIT cache at
`/root/.cache`. A first start compiles the FlashInfer kernels before the weights load, so
the health check allows 1,800 s for the start.

### The API key

vLLM asks for `Authorization: Bearer <key>` on `/v1` when the key file in
`vllm_api_key_file` holds a key. The structured server asks for the same key on every
POST. The compose wrapper reads the key file, exports the key for both servers, and then
runs the entrypoint of the image unchanged.

The structured server calls vLLM with no key. [dgemma/sitecustomize.py](dgemma/sitecustomize.py) adds the key to
each call from inside the container to the local vLLM port, and changes no other call.
The wrapper puts `/opt/hoover4`, where that folder is mounted, first on `PYTHONPATH`, so
Python loads the module in every process of the container. The module then runs a
`sitecustomize` of the image, if the image has one. An empty key file turns the key off
on both servers.

### Memory

The server shares the unified memory of the GPU box with ornith, `hoover4-ai-server` and GPU
EasyOCR. These values of `DGEMMA_ENV` set its memory.

| variable | value | what it sets |
|---|---|---|
| `VLLM_GPU_FRACTION` | `0.24` | the fraction of the whole device that vLLM takes |
| `VLLM_KV_CACHE_GB` | `6` | the KV cache in GiB |
| `VLLM_HEADROOM_GB` | `4` | the memory in GiB that the start-up check keeps free |
| `VLLM_TRANSIENT_COPIES` | `2` | the sampler copies that the start-up check budgets for |
| `VLLM_TORCH_MEM_FRACTION` | `0.85` | the fraction of memory that PyTorch can allocate |
| `VLLM_MEM_LIMIT` | `40g` | the memory limit of the container |

The entrypoint prints a `memory:` line with the memory available and the memory it needs.
The memory it needs is the sum of the weights, the KV cache, the start-up transient and
the headroom. The entrypoint refuses to start when the memory available is less. Read the
line and the KV cache size from the log:

```
docker logs hoover4-vllm 2>&1 | grep -E "memory:|refusing|GPU KV cache size|Maximum concurrency"
```

With these values the `memory:` line reads 117 GB available and 32 GB needed (weights 19,
KV cache 6, start-up transient 3, headroom 4). The log reads `GPU KV cache size: 511,437
tokens` and `Maximum concurrency for 262,144 tokens per request: 1.95x`. The KV cache
therefore holds fewer than `VLLM_MAX_NUM_SEQS` (4) sequences at the full context. Four
shorter sequences fit.

### Speed, and the agent timeouts that follow from it

A sweep sent streamed requests with thinking off, a unique first line in each prompt, and
`ignore_eos`, so each request decoded its full output. Each cell sent its requests at once.
The first chunk is the time to the first content, and the stream rate is the decode rate of
one stream after it.

| sequences | context tokens | output tokens | slowest first chunk, s | slowest stream, tokens/s | slowest request, s |
|---:|---:|---:|---:|---:|---:|
| 1 | 2,048 | 512 | 3.0 | 178.0 | 5.8 |
| 1 | 2,048 | 4,096 | 2.8 | 351.8 | 14.4 |
| 1 | 16,384 | 512 | 15.6 | 81.3 | 21.9 |
| 1 | 16,384 | 4,096 | 17.5 | 133.6 | 48.1 |
| 1 | 32,768 | 512 | 31.2 | 92.3 | 36.8 |
| 1 | 32,768 | 4,096 | 19.7 | 164.2 | 44.7 |
| 2 | 2,048 | 512 | 3.5 | 176.7 | 6.4 |
| 2 | 2,048 | 4,096 | 3.7 | 124.0 | 36.1 |
| 2 | 16,384 | 512 | 15.6 | 86.8 | 19.2 |
| 2 | 16,384 | 4,096 | 14.7 | 37.4 | 124.0 |
| 2 | 32,768 | 512 | 42.8 | 32.9 | 58.3 |
| 2 | 32,768 | 4,096 | 48.5 | 16.2 | 300.8 |
| 4 | 2,048 | 512 | 3.3 | 53.2 | 12.7 |
| 4 | 2,048 | 4,096 | 3.4 | 46.2 | 92.1 |
| 4 | 16,384 | 512 | 24.9 | 19.4 | 51.2 |
| 4 | 16,384 | 4,096 | 51.7 | 12.8 | 366.0 |
| 4 | 32,768 | 512 | 104.8 | 13.3 | 123.9 |
| 4 | 32,768 | 4,096 | 101.6 | 6.6 | 666.7 |
| 8 | 2,048 | 512 | 4.4 | 34.2 | 18.6 |
| 8 | 2,048 | 4,096 | 7.0 | 15.9 | 264.2 |
| 8 | 16,384 | 512 | 71.9 | 7.5 | 95.7 |
| 8 | 16,384 | 4,096 | 42.8 | 8.8 | 492.4 |
| 8 | 32,768 | 512 | 167.7 | 4.0 | 192.7 |
| 8 | 32,768 | 4,096 | 140.4 | 6.7 | 669.0 |

`VLLM_MAX_NUM_SEQS` is 4 when the slowest stream at 8 sequences decodes below 30 tokens a
second, and 8 otherwise. The slowest stream at 8 decoded 4.0 tokens a second, so the value is 4.

The six cells at 4 sequences give an estimate of one worst-case request. The first chunk
time is fitted as `a + b*c` over the context `c`, and the inverse stream rate as `e + f*c`.
Both fits are extrapolated to the full context of 262,144 tokens, which the sweep did not
send. At that context the fit gives 861 s to the first chunk and 1.24 tokens a second. One
worst-case request, `W`, is that first chunk plus 33,792 output tokens, 28,150 s.

The templates set the two limits of `[main_services]` below. Each is a time that a person
waits, and neither is a bound of the model. A request as long as `W` fails at the model call
limit while the model server still works on it.
[Known defects](../docs/development/Known_Defects.md#chat-context-handling-depends-on-model-information)
gives the consequences.

| key | what it limits | value, s |
|---|---|---:|
| `llm_request_timeout_seconds` | one model call, its wait in the model server's queue included | 3,600 |
| `agent_queue_wait_seconds` | the wait of one step for a free slot | 5,400 |
| `title_request_timeout_seconds` | the title request | 120 |

### Request parameters that the server rejects

vLLM answers a request with a 400 error when it carries `temperature`, `min_p`, `seed`,
`min_tokens`, `logit_bias`, `bad_words` or `allowed_token_ids`. A client of this server
must leave them out. It can send `chat_template_kwargs` with `enable_thinking`, which
wins over the default thinking of `VLLM_EXTRA_ARGS`. `LLM_SEND_TEMPERATURE = false`, which
[deploy.py](../deploy.py) always renders, makes the agents, their compaction summary and the title call
leave `temperature` out.

### Differences from the vLLM recipe

The vLLM recipe for this checkpoint, section "Full-Featured Server", with the NVFP4 variant
on DGX Spark GB10, is the reference for the served features. This deployment differs from
it in these arguments.

| argument | recipe | here | why |
|---|---|---|---|
| image | `vllm/vllm-openai:gemma` | the release `VLLM_BASE_RELEASE` with the patches of [dgemma/vllm-image/](dgemma/vllm-image) | the build adds the adaptive canvas schedule and the structured server |
| `--served-model-name` | not set | `dgemma` | a short name for the clients |
| `--gpu-memory-utilization` | 0.8 | 0.24 (`VLLM_GPU_FRACTION`) | the box runs ornith and other model servers |
| `--kv-cache-memory` | not set | 6 GiB (`VLLM_KV_CACHE_GB`) | a fixed KV cache beside ornith |
| `--max-num-seqs` | 8 | 4 (`VLLM_MAX_NUM_SEQS`) | at 8, one stream decodes below 30 tokens a second |
| `--diffusion-config` | canvas 256 | canvas 256, 32 samples, and a canvas schedule by batch size (`VLLM_CANVAS`, `VLLM_MAX_SAMPLES`, `VLLM_CANVAS_SCHEDULE`) | the schedule makes a smaller canvas at a larger batch |
| `--exclude-tools-when-tool-choice-none`, `--trust-remote-code`, `--async-scheduling`, `--max-logprobs 128`, `VLLM_USE_V2_MODEL_RUNNER=1` | not set | set by the entrypoint | the entrypoint of the build sets them, and the vLLM patches of the build need `--async-scheduling` |
| `--chat-template` | the recipe names a tool chat template | not set | the model's own template is used until a measurement shows that tool calls need the other |

Every other argument of the recipe is set to the recipe's value. `--mm-processor-kwargs`
(1,120 soft tokens), `--limit-mm-per-prompt` (7 images), `--default-chat-template-kwargs`
(thinking on) and `--load-format` (`fastsafetensors`) are in `VLLM_EXTRA_ARGS` of
`DGEMMA_ENV`, which the entrypoint adds to `vllm serve`. The entrypoint splits that value on
spaces, so no JSON value in it holds a space.

### Token streaming

`LLM_STREAMING=true` is the default of the research agents. An earlier vLLM sent streamed
tool-call deltas with no `arguments`, and the agent then made no tool call.
[research_agent/agent.py](../main_services/agents/research_agent/research_agent/agent.py) keeps the `disable_streaming` workaround and its comment. The
symptom to look for is an agent that answers with no tool calls.

## The chat model server

`hoover4-vllm-chat` serves ornith, the model of agent turns, beside `hoover4-vllm`, which
keeps dgemma and the structured server. It uses the image of `hoover4-vllm`, because that
vLLM build serves the Qwen3.5 mixture architecture and its MTP draft head on GB10. The
entrypoint is plain `vllm serve`, with `CHAT_VLLM_ARGS` of `ORNITH_ENV` added after the size
values.

[deploy.py](../deploy.py) downloads the pinned ornith commit into the folder `chat_model` with the
rule of [The weights](#the-weights), and the folder `chat_cache` holds the compile cache. The
service reads the key file of `vllm_api_key_file`, so one key opens both servers.

The memory of the two model servers, `hoover4-ai-server` and GPU EasyOCR must fit the device
together. The two model servers take 0.24 and 0.30 of it.

`hoover4-vllm-chat` starts after `hoover4-vllm` is healthy. vLLM measures the free memory of
the device when it starts, and memory that `hoover4-vllm` takes during that measurement
counts against `hoover4-vllm-chat`. Two servers that start together can give
`hoover4-vllm-chat` a negative KV cache, and its first start then fails. A restart of the host
starts both containers together, and the restart policy then starts `hoover4-vllm-chat`
again.

[deploy.py](../deploy.py) renders this server as `LLM_QUALITY_BASE_URL` and `LLM_QUALITY_MODEL` for the main
services. A request that names `ornith` goes to it.
