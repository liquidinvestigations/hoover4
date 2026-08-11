# Hoover4 ai_services — the optional GPU tier

GPU-backed embeddings / NER / reranking (`hoover4-ai-server`), a local LLM
(`hoover4-vllm`, **supported but parked**), and GPU EasyOCR (`hoover4-easyocr-gpu`,
**overlay only — no server image in the tree**).

> **Standalone.** This tier is fully optional and has **no
> dependencies on anything else**: no external network, nothing here calls into
> `main_services`. The MCP servers and research agents live in
> [`main_services/agents/`](../main_services/agents/README.md) instead — they read
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
| `compose/vllm.yaml` | `hoover4-vllm` | 21960 (`vllm_port`) | `llm_selfhosted` | Local LLM (**Qwen3.5-2B at its full 262 K context**), OpenAI-compatible. **Parked**: nothing starts it; the NVIDIA NIM cloud provider carries the live tests. |
| `compose/easyocr.yaml` | `hoover4-easyocr-gpu` | 21962 (`easyocr_port`) | `easyocr_enabled` | GPU OCR over HTTP. The server directory (`easyocr_server/`) does not exist, so enabling this overlay fails at build time — deliberately, rather than starting a container that cannot serve. The CPU twin `main_services/ocr_tesseract` carries OCR today. |

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
--output=/etc/cdi/nvidia.yaml` if not). It also prunes stale CDI mounts — a partial
driver upgrade leaves `/etc/cdi/nvidia.yaml` entries pointing at files that were never
installed, and crun refuses to start the GPU containers over the missing bind source,
which looks like a GPU problem and is not. **The durable fix is to bring every
`nvidia-*` package to the same version**; until then `nvidia-ctk cdi generate` will
reintroduce the bad entries.

The private `ai_services` network is created by `deploy.py` with explicit DNS
settings — fresh podman networks have no DNS until resolvers are attached.

### Model caches

The named volumes `ai_services_ai_models_cache` (~6 GB) and
`ai_services_vllm_huggingface_cache` (~16 GB) are preserved across
`./deploy --ai-services --reset`; pass `--reset-caches` to delete them too. The compose
project name is pinned to `ai_services` (`COMPOSE_PROJECT_NAME` in the generated
`.env`) so the caches stay attached. Changing it orphans them and re-downloads every
weight.

### Podman specifics

* GPUs are requested with `devices: nvidia.com/gpu=all` (CDI). The
  `deploy.resources.reservations.devices` block docker-compose uses is **silently
  ignored** by podman-compose — services appeared to start and then ran on CPU.
* `HEALTHCHECK` in a Dockerfile is dropped for OCI images, so healthchecks are declared
  in the compose overlays.
* The GPU services share one 24 GB card. `vllm_gpu_fraction` (default `0.50`) is the
  knob to turn down first if either OOMs.

### Testing

Python here runs **in containers only** — the host has almost no tooling.

```bash
docker exec hoover4-ai-server python -m pytest tests/ -q
```

The ai-server tests target `http://localhost:21961` by default; set
`AI_SERVER_TEST_URL` to point them at a remote GPU host.

## The local LLM: Qwen3.5-2B at its full 262 K context

`vllm/vllm-openai:v0.17.1` serving `Qwen/Qwen3.5-2B` at bf16, `--max-model-len 262144`,
`--gpu-memory-utilization 0.50`. vLLM 0.17 is the first release with native `qwen3_5`
support.

### Why the whole native context fits on a 24 GB card

The card also holds `hoover4-ai-server` (~2.9 GB of embedding/reranker/NER weights) and a
desktop session (~1.7 GB), so the LLM has roughly 10 GB to work with. The number that
decides everything is **KV cache bytes per token**, and Qwen3.5's hybrid architecture
changes it by an order of magnitude.

From `Qwen/Qwen3.5-2B/config.json`: 24 layers with `full_attention_interval: 4`, so
`layer_types` is three Gated-DeltaNet layers then one Gated Attention layer, six times
over. **Only 6 of the 24 layers keep a growing KV cache.** Those 6 have
`num_key_value_heads: 2` and `head_dim: 256`:

```
KV/token = 2 (K,V) x 6 full-attn layers x 2 kv-heads x 256 head_dim x 2 bytes = 12 KiB
```

The other 18 layers hold a *constant* recurrent state per sequence, not one that grows
with context. That is the whole point of the architecture. So:

```
weights (2.27 B params bf16, incl. vision tower)   4.55 GiB   (measured from the safetensors)
KV cache at 262,144 tokens                         3.0  GiB
activations + cudagraph capture                    ~1.3 GiB   (capture measured at 0.46 GiB)
                                                  ----------
                                                   ~9.9 GiB   =>  gpu_memory_utilization ~0.50
```

For comparison, the Qwen3-4B this replaces has 36 layers x 8 KV heads x head_dim 128 =
144 KiB/token — 12x more. Its 16,384-token limit was not a conservative choice; 262 K
would have cost ~36 GiB.

Note the model is **multimodal** (`Qwen3_5ForConditionalGeneration`, with a 24-layer
vision tower). The 4.55 GiB of weights already includes it.

### Read `Maximum concurrency`, not `GPU KV cache size`

```
$ docker logs hoover4-vllm 2>&1 | grep -E "Available KV cache|GPU KV cache size|Maximum concurrency"
Available KV cache memory: 5.95 GiB
GPU KV cache size: 129,472 tokens
Maximum concurrency for 262,144 tokens per request: 1.97x
```

`GPU KV cache size` looks like a failure — half of `max_model_len`, which on a normal
model would mean vLLM cannot hold even one full sequence. **It is not.** That figure is
normalised across all 24 layers, but only 6 keep a cache, so real capacity is 4x it:
517,888 tokens, i.e. the 1.97 full-length sequences vLLM itself reports. And
`5.95 GiB / 517,888 = 12.05 KiB/token`, exactly the arithmetic above.

Verified end to end rather than argued: a **200,021-token prompt** is accepted and
answered correctly. No step of the quantisation ladder (shorter context, FP8 KV cache,
AWQ INT4, the 0.8B model) was needed.

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
agent makes **zero** tool calls, and answers from nothing — the same symptom as the streaming interop bug below,
from a different cause. The right parser is **`qwen3_xml`** (note the underscore: the
registered name differs from its `qwen3xml_tool_parser.py` filename, and the wrong
spelling is a startup crash-loop rather than a clear error).

No `--reasoning-parser` is set, and that is correct **only while thinking stays off**.
Qwen3.5's template prefills `<think>\n\n</think>` unless `enable_thinking` is true, so by
default the model never emits a reasoning block and there is nothing to parse.

If you set `AGENT_THINKING=on` or `budgeted`, add `--reasoning-parser qwen3` at the same
time. Without it vLLM leaves the `<think>…</think>` block inside `content`, and the whole
chain of thought is shown to the user as part of the answer. See
[`../main_services/agents/research_agent/README.md`](../main_services/agents/research_agent/README.md)
for the measured cost of turning it on (~4x completion tokens).

Two consequences of the XML format are handled in code, because both presented as
infinite loops rather than as errors:

* **Array arguments arrive as strings.** `collections` comes across as the literal
  `'["testdata"]'`, pydantic rejects it, and the model retries the identical call until
  the recursion budget is gone — without ever running a search. The collection server
  coerces it (`_as_collection_list`).
* **The model does not reliably stop.** Given good results it will still re-issue a
  search it has already run. The agent now detects a repeated call, and enforces a
  12-turn tool budget, and in either case forces a final answer instead of letting
  langgraph raise `GraphRecursionError` — which surfaced as an HTTP 500 with no answer at
  all. See
  [`../main_services/agents/research_agent/README.md`](../main_services/agents/research_agent/README.md).

### Token streaming is back on

`LLM_STREAMING=true` is the default. The hazard it guards against is a vLLM/langchain interop bug where
streamed tool-call deltas arrived with `arguments` absent and never accumulated, so the
agent silently made zero tool calls. Re-tested on 0.17.1 with a real agent run: **4 tool
calls and a correctly cited answer with streaming on.** The `disable_streaming` workaround
and its comment are left in `research_agent/agent.py` — set `LLM_STREAMING=false` if it
ever regresses. The symptom to watch for is an agent that answers with no tool calls.
