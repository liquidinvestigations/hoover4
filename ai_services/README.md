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
| `compose/vllm.yaml` | `hoover4-vllm` | 21960 (`vllm_port`) | `llm_selfhosted` | The agent model (**Qwen3.5-35B-A3B**), OpenAI-compatible. Off by default; a cloud provider serves the stack until it is turned on. |
| `compose/easyocr.yaml` | `hoover4-easyocr-gpu` | 21962 (`easyocr_port`) | `easyocr_enabled` | GPU OCR over HTTP ([`easyocr_server/`](easyocr_server/README.md)). Speaks the same request contract as the CPU twin `main_services/ocr_tesseract`, so `tasks/ocr_client.py` posts one request shape to either. |

## Deploy

From the repo root, with `hoover4.ini` in place (`[ai_services] enabled = true`):

```bash
./deploy --ai-services                 # start the enabled overlays
./deploy --ai-services --build         # rebuild images (force-recreates)
./deploy --ai-services --down
./deploy --ai-services --reset         # data volumes; model caches preserved
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

The named volumes `ai_services_ai_models_cache` (~6 GB),
`ai_services_vllm_huggingface_cache` (~16 GB) and
`ai_services_easyocr_models_cache` (~100 MB) are preserved across
`./deploy --ai-services --reset`; pass `--reset-caches` to delete them too.
EasyOCR keeps its own volume rather than sharing the ai-server's: the two hold
different model layouts, and overlaying EasyOCR's flat `*.pth` files on a HuggingFace
`hub/` tree works only for as long as the two never pick the same name. The compose
project name is pinned to `ai_services` (`COMPOSE_PROJECT_NAME` in the generated
`.env`) so the caches stay attached. Changing it orphans them and re-downloads every
weight.

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
* The GPU services share one device. `vllm_gpu_fraction` (default `0.50`) is the setting to
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

## The local LLM: Qwen3.5-35B-A3B

`vllm/vllm-openai:v0.17.1` serving `Qwen/Qwen3.5-35B-A3B` at bf16, `--max-model-len
262144`, `--max-num-seqs 16`. vLLM 0.17 is the first release with native `qwen3_5`
support.

35B total with 3B active per token, a mixture of experts, which is what makes it usable
on memory-bandwidth-bound hardware where a dense 30B is not. It has the four capabilities
the agents assume: tool calling, parallel tool calls, thinking, and vision.

### `max-num-seqs` is a correctness setting, not a tuning one

A server with one slot serialises every caller head-of-line. A chat turn queued behind a
benchmark then looks like a sixteen-minute model when most of it was a sixteen-minute
queue, a misdiagnosis that costs a full debugging session and reaches the wrong
conclusion about the model. One research agent is already several concurrent streams, and
there is more than one conversation.

The startup log reports what the KV cache can actually hold:

```
$ docker logs hoover4-vllm 2>&1 | grep -E "GPU KV cache size|Maximum concurrency"
GPU KV cache size: 500,544 tokens
Maximum concurrency for 262,144 tokens per request: 7.53x
```

That figure is concurrency at the **full** context. Real turns are far shorter, so the
slot count is the binding limit rather than the cache.

### FP8 does not run on GB10

The FP8 checkpoint loads and then fails during warmup with `RuntimeError: Error Internal`
out of `torch.ops._C.cutlass_scaled_mm`. The cause is above it in the same log: this
build's PyTorch supports compute capability 8.0 through 12.0, and GB10 is **12.1**. The
CUTLASS FP8 kernels are compiled for architectures the device is not, and the error names
the operator rather than the architecture.

bf16 avoids that path entirely. It costs memory (roughly 70 GB of weights against FP8's
35) which on the unified-memory box means nothing else large can be resident beside it.
`vllm_gpu_fraction` is a fraction of **total system memory** there, not of a discrete
card, so a value tuned for a 24 GB card overcommits badly.

Measured on the box, single stream, 256 tokens at temperature 0: **30.4 tok/s** warm.
That matches the published bf16 figure for this model on this hardware.

### Reasoning must be parsed out

Qwen3.5 thinks by default, so `--reasoning-parser qwen3` is not optional here: without it
vLLM leaves the `<think>…</think>` block inside `content` and every answer arrives with
the model's working prepended, visible to the user, counted against the payload budget,
and parsed by nothing. See
[`../main_services/agents/research_agent/README.md`](../main_services/agents/research_agent/README.md)
for the measured cost of thinking (~4x completion tokens).

### Tool calling: `hermes` is wrong for this model

`--tool-call-parser hermes` was correct for Qwen3-4B and **silently breaks Qwen3.5**.
Qwen3.5 emits XML-style blocks:

```
<tool_call>
<function=list_collections>
</function>
</tool_call>
```

`hermes` does not match that, so every tool call arrives as ordinary assistant text, the
agent makes **zero** tool calls, and answers from nothing. That is the same symptom as the streaming interop bug below,
from a different cause. The right parser is **`qwen3_xml`** (note the underscore: the
registered name differs from its `qwen3xml_tool_parser.py` filename, and the wrong
spelling is a startup crash-loop rather than a clear error).

Two consequences of the XML format are handled in code, because both presented as
infinite loops rather than as errors:

* **Array arguments arrive as strings.** `collections` comes across as the literal
  `'["testdata"]'`, pydantic rejects it, and the model retries the identical call until
  the recursion budget is gone, without ever running a search. The collection server
  coerces it (`_as_collection_list`).
* **The model does not reliably stop.** Given good results it will still re-issue a
  search it has already run. The agent now detects a repeated call, and enforces a
  12-turn tool budget, and in either case forces a final answer instead of letting
  langgraph raise `GraphRecursionError`, which surfaced as an HTTP 500 with no answer at
  all. See
  [`../main_services/agents/research_agent/README.md`](../main_services/agents/research_agent/README.md).

### Token streaming is back on

`LLM_STREAMING=true` is the default. The hazard it guards against is a vLLM/langchain interop bug where
streamed tool-call deltas arrived with `arguments` absent and never accumulated, so the
agent silently made zero tool calls. Re-tested on 0.17.1 with a real agent run: **4 tool
calls and a correctly cited answer with streaming on.** The `disable_streaming` workaround
and its comment are left in `research_agent/agent.py`. Set `LLM_STREAMING=false` if it
ever regresses. The symptom to watch for is an agent that answers with no tool calls.
