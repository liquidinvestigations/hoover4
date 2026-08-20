# `agent_common` — shared code for the MCP servers

Three things live here because more than one server needs them and a second copy would
drift.

| Module | What it is |
|---|---|
| `artifacts.py` | the chat-artifact writer: bytes to S3, one index row in ClickHouse |
| `s3_store.py` | the S3 client and the `derived/chat-artifacts/` key scheme |
| `rerank.py` | the GPU tier's `/v1/rerank`, with a 2 s connect timeout and a circuit breaker |

Consumers: `metasearch_server` (writes `search_detail`, reranks) and
`browser_use_server` (writes `page_capture`).

## It is vendored, not published

There is no index to install it from. The consuming Dockerfiles build with
**`main_services/agents` as their build context** and do

```dockerfile
COPY ./agent_common/ ./agent_common/
RUN pip install --no-cache-dir ./agent_common
```

before installing their own package. Two consequences worth knowing before you edit
anything:

* **Moving a consumer's Dockerfile means moving its `context:`** in
  `../../ops/docker/compose/agents.yaml`. A Docker build cannot reach outside its context,
  and the failure is a missing-module traceback at container start, not at build time.
* **`agent_common`'s dependencies are declared in each consumer's `pyproject.toml` as
  well.** pip resolves the two installs separately, so `requests` and `minio` appear in
  both places on purpose. Adding a dependency here means adding it there too.

## The artifact contract

Every part of this is load-bearing:

* The model receives **only the `artifact_id`** — a UUID, ~36 characters. It is a lookup
  key, never a capability: the website resolves it back to `session_id`/`username` and
  enforces owner-or-admin before serving a single byte.
* Bytes go under `derived/chat-artifacts/<session>/<id>/`, the one prefix `P0_scan_disk`
  must never walk. An artifact the ingest walker can see is ingested, captured again, and
  produces another artifact, forever. `verify-stack.sh` asserts no `blobs` row references
  `derived/`.
* **Objects are written before the row.** A crash between the two leaves an orphan object
  the retention sweeper's prefix scan collects. The reverse order would leave a row
  pointing at nothing, which the UI would render as a broken artifact forever.
* **A failed artifact never fails the tool.** The search still happened; the page was still
  read. `write()` returns `None` and logs, and the caller omits the id.

Path components are sanitised in `s3_store._safe`: the session id arrives in an HTTP
header, and a header carrying `../../blobs` would otherwise write outside the prefix that
is the whole point of this module.

## The rerank client

Two rules that read identically to their wrong versions:

* **A rerank timeout is an error, not a silent skip.** 25 s hard cap. If reranking is slow,
  the answer is a smaller cross-encoder — not a degradation the transcript cannot show. The
  *caller* decides what to do with the error; what it must not do is pretend the reranked
  order is the RRF order.
* **The breaker counts connect failures only.** A model returning 500 is a different problem
  and must stay visible on every call. A read timeout is likewise not counted: the host
  answered, it was just slow, and skipping it for a minute would hide a model that needs
  replacing.

Latency is logged on every call, successful or not. `breaker_state()` is exposed on the
consuming servers' `/health` so an open circuit is visible without reading logs.

## `telemetry` — one `ai_service_telemetry` row per outbound call

`/admin/ai_status` builds its use% strip and traffic table from that table alone, and until
this sweep only the LLM path wrote to it: embeddings, rerank, NER, OCR and the browser all
rendered as "no traffic", which reads as *idle* and is indistinguishable from *broken*.

`record_async` writes on a daemon thread, because the clients here are synchronous
`requests` inside async servers and `asyncio.to_thread` is not available at the call site.
A dropped row at shutdown is the right trade for never delaying an answer.

**Every outcome is recorded, not only the successes** — a capability that writes rows only
when it works shows as idle exactly while it is failing.

The worker keeps its own copy at `main_services/processing/tasks/ai_telemetry.py`: different
image, and it already holds a ClickHouse client. Same table, same column meanings; the two
are duplicated on purpose and must agree. Their one deliberate difference is the default
`username` — `guest` for a request with no user, `pipeline` for work that is on nobody's
behalf.

## Tests

The behaviour lives in the consumers' suites, where it can be exercised against real call
sites — `metasearch_server/tests/test_pipeline.py` covers the rerank fallback and the
payload/artifact split. There is no separate suite here.
