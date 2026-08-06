# Hoover4 AI services

GPU-backed embeddings / NER / reranking, a local LLM, a set of MCP tool servers, and
the LangGraph research agents that use them.

> **Deployment note (plan 3).** These services used to run across several hosts behind a
> VPN and addressed each other by `10.69.x.x`. That network is gone. Everything now runs
> on **one machine with one GPU**, joining the `hoover4` podman network created by
> `main_services/ops/docker/docker-compose.yaml`. Bring the main stack up first, then
> this one.

## What runs here

| Service | Port (loopback) | Purpose |
|---|---|---|
| `hoover4-ai-server` | 8821 | Embeddings, reranking, NER. Also serves the pipeline's P4 stage (`NER_URL`). |
| `hoover4-vllm` | 8011 | Local LLM (**Qwen3.5-2B at its full 262 K context**), OpenAI-compatible. Replaces the old LiteLLM proxy. |
| `hoover4-mcp-collections` | 8085 | **The RAG path.** ACL-bounded search over the user's collections. |
| `hoover4-mcp-metasearch` | 8086 | Web search over four engines, merged with reciprocal rank fusion. |
| `hoover4-mcp-browser` | 8087 | Reads a page with a real headless Chromium, for JS-rendered sites. |
| `hoover4-mcp-ddg` / `-wikipedia` / `-whois` | 8889 / 8093 / 8092 | Older single-purpose open-web tools. |
| `hoover4-internal-search-agent` | 9099 | Collection-only agent. What the website's AI Chat page calls. |
| `hoover4-full-research-agent` | 9090 | Collections + open web. Target of the Temporal `ResearchTask`. |

Per-server detail is in [`hoover4_mcp/README.md`](hoover4_mcp/README.md), which links to a
README per server.

## How access control works

An agent answering for a user must only reach collections that user could read in the
search UI. The chain is:

1. The **website backend** resolves the user's permitted collections (group grants union
   public collections). It is the only component that can — it owns the auth tables.
2. It passes that list to the agent as `allowed_collections`.
3. The agent opens its MCP connections with `X-Hoover4-Collections: <list>` and
   `Authorization: Bearer $MCP_SHARED_SECRET`, and caches one graph **per ACL** so a
   connection is never reused across users.
4. `hoover4-mcp-collections` enforces the header on every tool call. A request for a
   collection outside it is an error, not a silently-narrowed filter.

The model never sees or supplies its own permissions. Set `MCP_SHARED_SECRET` in `.env`;
without it the MCP servers accept any caller and log a warning (the ports are bound to
127.0.0.1, which is the only reason that is survivable locally).

## Why search goes through Manticore, and where Milvus went

The ingestion pipeline writes extracted text to ClickHouse and search documents to
Manticore shards. It **never wrote vectors**, so the whole Milvus tier — three containers
(`milvus-standalone`, `milvus-etcd`, `milvus-minio`) holding ~39 GB of memory limit, an
MCP server that would have searched an empty index, a `pymilvus` dependency in three
packages, and the legacy `hoover4_rag` ingestion CLI — has been removed (Q1/Q3).

The `text_chunks_milvus`, `entity_hits_milvus` and `entity_hits_milvus_unique` ClickHouse
tables are dropped by collection migration `00031`. Migrations `00023`/`00024` still
create them and always will: the runner stores an md5 per applied file, so editing history
breaks every existing deployment. The DROP is what undoes them.

**If vector search is ever wanted again**, this is what would have to be built first — the
missing piece was never the search side:

1. A **chunk-and-embed stage in P5**: split `text_content` into overlapping chunks, embed
   each through `hoover4-ai-server` (`intfloat/multilingual-e5-large-instruct`, 1024-dim),
   and write chunk ↔ vector-id alignment rows. That stage has never existed.
2. A vector store to write them to, and a migration recreating the alignment tables.
3. Hybrid retrieval in the collection MCP server: BM25 from Manticore and vectors from the
   store, merged with RRF — the same merge the metasearch server already implements.

Until step 1 exists, a vector database is three containers searching nothing.

**The stopped Milvus containers and their podman volumes are deliberately left on this
host.** Reclaiming the disk is your call:

```bash
podman rm milvus-standalone milvus-etcd milvus-minio
podman volume rm milvus_etcd milvus_minio milvus_standalone
```

## Quick start

```bash
# 1. the main stack must be up first — it creates the `hoover4` network
../main_services/start-docker.sh

# 2. configure once
cp env.example .env
$EDITOR .env          # at minimum, set MCP_SHARED_SECRET

# 3. start
./start-docker.sh                       # add --build to rebuild images
```

The first start downloads model weights (~2 GB for the embedding model, ~8 GB for the
LLM), so `hoover4-ai-server` and `hoover4-vllm` take several minutes to report healthy.
`start-docker.sh` waits for health and prints what is still coming up.

### Use `start-docker.sh`, not bare `docker compose up`

A plain `docker compose up -d` in this directory fails in two ways that are easy to
misread, and the script checks both before starting anything:

1. **`network hoover4 not found`** — the network is declared `external` here and is
   created by the main stack. That has to be up first.
2. **`crun: cannot stat /usr/lib/libnvidia-*.so.<driver>: OCI runtime attempted to
   invoke a command that was not found`** — `/etc/cdi/nvidia.yaml` lists library mounts
   derived from the running driver version, and a partial driver upgrade (on this host:
   `nvidia-utils` at `610.57.04` while `nvidia-settings` is still at `610.43.03`) leaves
   entries pointing at files that were never installed. A CDI mount is a bind, so `crun`
   refuses to start the container at all. Only the two **GPU** services fail while the
   six others come up, which looks like a GPU problem and is not.

   The script prunes mounts whose host path does not exist, keeping a timestamped backup
   of the spec. The entries this hits in practice (`libnvidia-gtk3`,
   `libnvidia-wayland-client`) belong to `nvidia-settings` and are irrelevant to CUDA.
   **The durable fix is to bring every `nvidia-*` package to the same version**; until
   then `nvidia-ctk cdi generate` will reintroduce the bad entries.

The compose project name is pinned to `ai_services` so the model caches
(`ai_services_ai_models_cache` ~6 GB, `ai_services_vllm_huggingface_cache` ~16 GB) stay
attached. Changing it orphans them and re-downloads every weight.

### Podman specifics

* GPUs are requested with `devices: nvidia.com/gpu=all` (CDI). The
  `deploy.resources.reservations.devices` block docker-compose uses is **silently
  ignored** by podman-compose — services appeared to start and then ran on CPU.
* `HEALTHCHECK` in a Dockerfile is dropped for OCI images, so healthchecks are declared
  in the compose file.
* Both GPU services share one 24 GB card. `VLLM_GPU_FRACTION` (default `0.45`) is the
  knob to turn down first if either OOMs.

### Testing

Python here runs **in containers only** — the host has almost no tooling.

```bash
docker exec hoover4-mcp-collections python -m pytest tests/ -q   # 52 tests
docker exec hoover4-mcp-metasearch  python -m pytest tests/ -q   # 20 tests
docker exec hoover4-mcp-browser     python -m pytest tests/ -q   # 40 tests
```

A `--build` alone can leave the old container running against the new image. Follow it
with an explicit recreate:

```bash
./start-docker.sh --build hoover4-mcp-collections
docker compose up -d --force-recreate hoover4-mcp-collections
```

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
agent makes **zero** tool calls, and answers from nothing — the same symptom as Q12,
from a different cause. The right parser is **`qwen3_xml`** (note the underscore: the
registered name differs from its `qwen3xml_tool_parser.py` filename, and the wrong
spelling is a startup crash-loop rather than a clear error).

No `--reasoning-parser` is set: Qwen3.5-2B is non-thinking by default.

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
  all. See [`hoover4_research_agent/README.md`](hoover4_research_agent/README.md).

### Token streaming is back on

`LLM_STREAMING=true` is now the default. Q12 was a vLLM-0.11/langchain interop bug where
streamed tool-call deltas arrived with `arguments` absent and never accumulated, so the
agent silently made zero tool calls. Re-tested on 0.17.1 with a real agent run: **4 tool
calls and a correctly cited answer with streaming on.** The `disable_streaming` workaround
and its comment are left in `research_agent/agent.py` — set `LLM_STREAMING=false` if it
ever regresses. The symptom to watch for is an agent that answers with no tool calls.

## Manticore `MATCH()` syntax

Verified against the live `testdata_1_pages` shard, not taken from documentation —
several documented spellings are a hard 500 on this deployment.

| Syntax | Result | Notes |
|---|---|---|
| `test document` | works | implicit AND |
| `test \| zzz` | works | OR |
| `test -zzz` | works | NOT, **only with a positive term** |
| `-zzz` alone | 500 | `query is non-computable (single NOT operator)` |
| `"test document"` | works | exact phrase |
| `"test document"~5` | works | proximity |
| `"one two three"/2` | works | quorum |
| `test NEAR/3 document` | works | |
| `test SENTENCE document`, `… PARAGRAPH …` | works | |
| `test MAYBE document` | works | |
| `@page_text test` | works | the only valid field |
| `@title test` | 500 | `no field 'title' found in schema` |
| `who paid @acme` | 500 | a bare `@word` in prose reads as a field operator |
| `test^3` | works | boost |
| `(test \| document) the` | works | grouping |
| `@page_text ^test` | works | field-start |
| `=test` | works | exact form |
| `"test` / `(test` | 500 | `syntax error, unexpected $end` |
| `""` (empty) | works, **matches every row** | dangerous default |
| `docum*`, `*ocument*` | **works now** | see below — was silently wrong |

Two facts worth keeping:

* **`page_text` is the only full-text field.** Everything else in the shard schema
  (`collection_dataset`, `file_hash`, `extracted_by`, `page_id`, `ner_*`) is an attribute
  and belongs in `WHERE`, not `MATCH()`.
* **Wildcards used to fail silently.** Without infix indexing the star was dropped during
  tokenisation and the query became an exact search for a truncated word — `doc*` returned
  **7** where `document` returned 16. Not zero. Wrong.

`sanitize_match_query` no longer strips operators. It passes them through and repairs only
the shapes that 500 (unbalanced quote or paren, NOT-only, bare `@word`, empty), reporting
what it repaired in the response's `note` and returning Manticore's own error text in
`error` so the model can correct itself. The escaping of `\` and `'` is unchanged and is
the injection barrier.

### Infix indexing: what it cost

`min_infix_len='3'` was added to both `pages_table_ddl` and `meta_table_ddl` in
`main_services/processing/database/manticore.py`, and both collections reindexed.
Behaviour on the real `testdata` shard (156 pages, 26 MB of text):

| query | before | after |
|---|---|---|
| `document` | 16 | 16 |
| `docum*` | 0 | 19 |
| `*ocument*` | 0 | 42 |
| `doc*` | **7 (wrong)** | 34 |
| `te*t` | **3 (wrong)** | 28 |
| `wat*` | 0 | 14 |

**The storage cost could not be measured reliably**, and that is worth stating plainly
rather than quoting a number that does not reproduce. `SHOW TABLE ... STATUS` `disk_bytes`
on an RT table depends on chunk-merge state: the same no-infix configuration measured
16.6 MB, 33.6 MB and 65.4 MB at different points in the same session. Under *identical*
treatment — pipeline reindex, then `FLUSH` + `OPTIMIZE` — the numbers were:

| configuration | disk_bytes | ram_bytes |
|---|---|---|
| no infix | 33,588,034 | 35,407,056 |
| `min_infix_len='3'` | 26,013,634 | 17,537,550 |

i.e. the infix build measured **smaller**, which is not a credible causal effect and is
better read as "the metric is noisy at this corpus size". A controlled probe (two tables,
same 156 pages inserted row by row, same flush/optimise) put the difference at **+0.8%**
on disk. Whatever the true figure, it is not a cost worth trading the wrong answers for.
`min_infix_len` 2, 3 and 4 are identical in size and behaviour in this Manticore version —
it is an on/off switch, not a threshold, so do not spend time tuning the number.

**`ALTER TABLE` does not reindex.** It updates metadata only: `SHOW TABLE ... SETTINGS`
will report the new value while queries keep returning the old, wrong answers. Changing
the setting means `main.py reindex-collection <name>`. And the worker is long-running, so
it must be **restarted** after a DDL change or it will keep creating tables from the
module it imported at startup.

## Where the system prompts live

Not in compose. A multi-paragraph prompt inlined as a YAML default was unreadable and
drifted from the tool descriptions it was supposed to agree with. There are two files:

* [`hoover4_mcp/collection_search_server/collection_search_server/prompts.py`](hoover4_mcp/collection_search_server/collection_search_server/prompts.py)
  — the MATCH syntax reference and search strategy. Reaches the model as the MCP server's
  FastMCP `instructions`, i.e. at tool-discovery time, for **whichever** agent connects,
  and is appended to the error text when a query is rejected.
* [`hoover4_research_agent/research_agent/prompts.py`](hoover4_research_agent/research_agent/prompts.py)
  — one system prompt per agent profile, selected by `AGENT_PROFILE`.

`SYSTEM_PROMPT` / `SERVER_INSTRUCTIONS` remain as thin env overrides for experiments;
empty means "use the canonical text".

**Keep the agent prompts short.** Qwen3.5-2B follows a long numbered prompt by doing all
of it forever — an earlier five-step draft made it search, search again, then re-run a
query it had already run until the request died. Detail belongs in tool descriptions,
which the model reads in context at the moment it picks a tool. Re-measure before
lengthening.

## Q9 — the shared `hoover4` network

The network is shared between two compose files: `main_services` creates it, `ai_services`
declares it `external: true` and joins it. Its DNS resolvers were added **by hand** on this
host (containers otherwise have no DNS on a podman network, which bites again after
`reset-docker.sh`).

That is fine for one machine. **Revisit before any multi-host deployment**: it needs real
network configuration — a named overlay or explicit service discovery — rather than one
hand-patched bridge, and the MCP servers' "bind to 127.0.0.1 and trust the caller's ACL
header" model assumes the loopback boundary that a multi-host setup removes.

