# Processing Tasks

This directory contains Temporal workflows and activities that implement the multi-stage Hoover4 ingestion pipeline. Each stage is organized as a separate submodule and executed via worker queues defined in `run_worker.py`.

## Pipeline Stages

### P0 - Scan Disk

Discovers datasets on disk, enumerates files, and writes the virtual filesystem (VFS) tables:

- Top-level workflow: `IngestDiskDataset`
- Outputs: `vfs_files` and `vfs_directories` in ClickHouse

### P1 - Compute Plans

Builds processing plans from VFS statistics to chunk work into manageable batches.

### P2 - Execute Plan

Schedules plan chunks for distributed execution and manages temporary download and cleanup steps.
`download_plan_files` copies each blob of a plan to `/tmp/hoover4/<collection_dataset>/<plan_hash>/`
in the worker, and the P3 parse, email and archive activities read that copy. `/tmp/hoover4` is
the volume `worker_temp_files`, so a recreated worker container keeps the copies of the plans in
progress. When a copy is missing all the same, each reader raises the non-retryable
`TempCopyMissing` error that names the path. It does not detect a type for the path.

### P3 - Parse Files

Parses files by type (archives, email, PDF, audio, video, images, OCR, and Tika-based extraction) and writes structured content.

### P4 - Extract Entities (NLP/NER)

Runs named-entity recognition over parsed text content via the remote NER service, before indexing. Writes `entity_hit` rows and `nlp_processed` watermarks (including `text_bytes`). Texts are sent to the NER service in batches of `NLP_BATCH_TEXTS = 32`. NER failures are retried and then recorded in `processing_errors`, never silently swallowed.

A variant that is a worse copy of another variant of the same document is not sent to the
model at all (`text_sources.ner_reads_variant`: a mail file's MIME envelope beside its
parsed body), and `entity_stoplist` drops the values that are extraction debris rather
than entities: header names, encoding fragments, letter-spaced PDF headings.

### P5 - Chunk and Embed

Splits `text_content` pages into `text_chunks` and embeds them into `text_chunk_vectors`,
on `processing-embed-queue`. Chunking is deterministic and byte-addressed, which is what
makes the left-anti join against `text_chunk_vectors` a correct idempotency key.

**Chunks that are not language are not embedded.** Text extraction is greedy on purpose
(a parser that skips what it does not understand loses real documents), so it also yields
an email attachment's base64, an XPM colour table and an XBM byte dump as "page text".
`text_quality.non_linguistic_reason` holds those back before the embeddings call: it cost
GPU time to produce a vector that then won searches it had no business winning (live,
`search_collections("Eiffel Tower height")` returned an image's pixel rows as its top hit,
because noise is close to everything in embedding space). `text_content` still holds every
byte. This filters what is *embedded*, never what is stored, and the count comes back as
`chunks_skipped_non_linguistic` so a heuristic that starts eating real documents is visible
rather than silent.

The number was freed by renaming indexing to P6. Indexing genuinely runs last, and
inserting a stage before it would otherwise have meant either an out-of-order number or
a second rename later.

### P6 - Index Data

Aggregates metadata and text content into search indexes, reading the entity rows and watermarks written by P4. Pure I/O, no remote model calls.

Search indexes are sharded: a single planner activity (`plan_shards`, on
`processing-index-planner-queue`, exactly one worker process) assigns every document
to a shard, persisting the `manticore_shards` ledger and `manticore_shard_assignments`
in the collection database, and creates the Manticore table `<collectionname>_<n>_pages`.
A shard stays open until the next document would push it over
`MAX_SHARD_TEXT_BYTES = 4_000_000_000` (4 GB of extracted text) or
`MAX_SHARD_ROWS = 2_500_000` (two budgets because bytes per row vary by two orders of
magnitude across the corpus while facet cost tracks rows), then it is sealed and a new
shard opens. Re-indexing overwrites documents in place. A document never
moves between shards and never appears in two shards.

## Administrative Workflows

### P_admin - Collection database lifecycle, purges, ETA sampling

Not a pipeline stage. Creates and drops the per-collection ClickHouse databases
(`Hoover4_Collection_<collectionname>`) on demand, purges soft-deleted datasets, and
runs `CollectEtaSamples`. The self-scheduling singleton that writes
`processing_eta_samples` for the admin processing page (100-event rates, items/s and
bytes/s combined pessimistically, 20x-cost throttle, finished collections skipped).
Runs on `processing-common-queue`. Each pass also calls the operation sweep and, behind the
`agent-run-sweep` patch, the agent run sweep on `operations-queue`. See [P_admin/Readme.md](P_admin/Readme.md).

### P_ops - Long operations a person can start

Not a pipeline stage. One `Operation` workflow per dispatched long operation, whose
workflow id **is** the `op_id` of its row in the global `operations` table, so a caller
that was killed, or that deliberately detached, can always find its work again, and the
row outlives Temporal's history, which is retained for a day. The workflow owns the row's
lifecycle and its terminal write is what releases the operations lock. Runs on
`operations-queue`, the three store queues and `operations-admission-queue`, in the
`hoover4-ops` container rather than in this fleet. The admission queue has one slot. It keeps
the running operations of each kind at the cap of the `[operations]` section, and a
`queued` row waits there for a slot. See [P_ops/Readme.md](P_ops/Readme.md). A failed operation also writes a
tree of worker stack traces into the global `operation_failures` table
(`tasks/operation_failure_capture.py`). A pipeline workflow that fails an operation writes
the same way. The group workflow `ProcessItemsBatched` records an unreadable PDF, like
every failed file, in `processing_errors`, and does not write `operation_failures` for it.

### P_agent - every AI agent turn

**Every agent run runs here.** `AgentRun` owns an ordinary chat message on `chat-queue`, and
each planner and organizer run of a deep research plan. The workflow runs the agent loop.
Each model call is one `model_step` activity on the queue in its run row, `chat-model-queue`
for a chat turn and `research-queue` for a plan run. Each tool call is one `tool_call`
activity on `agent-tool-queue`. The step activities are in `P_agent/steps.py`.
`plan_runs.py` writes the plan run state in `open_run` and `write_ending`, the section
documents, and `sections_json`. A decision of the person starts the next run from the
website, so no workflow waits for review.

`AgentRun` keeps its state in `agent_runs` and `agent_run_messages`
(`database/agent_runs.py`). Its input holds ids and settings only. `open_run` writes the
row and the opening message from the user row, and returns the unanswered calls of the
stored thread. `model_step` sends the stored thread to the agent's `POST /model_step`, and
writes the reply: the `ai` message with its call entries, one live tool row for each call,
or the answer row. `tool_call` sends one stored call to `POST /tool_call` with an
idempotency key from the thread, the reply and the place of the call, and writes its `tool`
message and tool row. `write_ending` writes the terminal state and the ending row. No
answer or tool result crosses a Temporal payload. Each write has a fixed key, so a retry, a
worker restart and a continue-as-new resume from the stored thread. A step that finds its
own `ai` message makes no second model call, and a call that has a result runs nothing.
A turn with a stop row in `agent_turn_stops` closes in `open_run`.

**The limits of the loop** are in `P_agent/model_timeouts.py`. A model step has 3,600 s
(`llm_request_timeout_seconds`) and a tool call 300 s. Each waits at most
`agent_queue_wait_seconds` for a slot. A model step that waits longer fails the run with
"The model queue wait passed ... s.", and a tool call that fails after its last attempt gets
a stored `tool_unavailable` result, which the model reads. After 600 model steps one
`final` step binds no tool, and the run ends `completed` with `end_reason` `step_budget`.
A reply that repeats an earlier call also gets one `final` step (`repeated_call`). The
workflow continues as new every 250 model steps, or past 30,000 history events. A planner
that answers with no plan section gets one more round with a note, and then fails.

**Each attempt of a model step, a tool step and a title call writes one row of
`agent_step_events`** (`database/agent_step_events.py`). The row holds the queue wait, the
duration, the status, the error class and the tokens. The step activities write it from a `finally`
block through the buffer of `task_timing.py`. A step that returns a stored result writes no
row. Each attempt that starts writes one row. An attempt that passes its start-to-close
limit on a live worker is cancelled with the reason `timed_out`, and its row has the class
`start_to_close_timeout`. `record_step_failure` writes the row of a step that never started
or lost its heartbeat, with `attempt` 0. The table keeps 90 days.

**A change to `AgentRun` needs the drain.** A running `AgentRun` replays its history on the
new code, and a history that does not match fails as nondeterministic, so the turn never
ends. No workflow versioning exists. Before a worker with a changed `AgentRun` starts,
write the stop row of each open agent turn and cancel every running `AgentRun`, with the
old worker still up, until the count of running `AgentRun` workflows is 0. The Temporal CLI
in the `temporal` container needs `--address` with the address that the worker connects to,
because the default address of the CLI has no server.

**Delegation runs through run rows.** A reply with `run_subagent` calls runs its other
calls first. `delegate_step` then writes one `tool` row for each delegation call, applies
the budgets of `run_budgets.py`, writes a child row and an opening message for each accepted
briefing, and puts its own row in `waiting_for_children`. The workflow starts one abandoned
child `AgentRun` for each child, with the parent's collections, model and internet switch in
its input, and returns. When a run ends, `fan_in` reads its sibling set. When every sibling
is terminal, `continue_run` writes a continuation row of the parent, and the workflow starts
it. The continuation's `prepare_continuation` adds one `tool` result for each `run_subagent`
call, the
JSON `{"reports": [...], "refused": [...]}`, and rewrites the call's transcript row with it.
`write_ending` of a continuation writes its state into every run it continues. Child and
continuation ids are `uuid5` values, so a retry and a second writer write the same rows, and
a refused duplicate workflow start counts as started. A child at depth 2 cannot delegate.

The budgets: at most 5 briefings a call, `AGENT_SUBAGENT_MAX_PER_TURN` sub-agent runs a chat
turn (default 6), `AGENT_PLAN_RUN_BUDGET` a plan run (default 300), and a depth 1 run spends
only the share its parent gave it. The surplus is refused by name in the continuation's
result. The counts leave out the caller's own batch, so a retry counts what it counted first.

**The agent run sweep** (`supervise.py`) runs on `operations-queue` after the operation sweep
of each `CollectEtaSamples` pass. It ends a running row whose workflow closed or does not
exist, as `failed` or, for a stopped turn, `cancelled`, and runs `fan_in` for it. It
continues a waiting row whose workflow closed and whose batch is terminal. It leaves a row
younger than 120 s, and a child whose parent's workflow still runs. A child whose parent
is terminal is ended when its own workflow is closed or absent, because no attempt of a
terminal parent starts it.

The website holds nothing open for either: it writes the user row, reserves the answer's
seq and dispatches. That is what makes a turn survive a browser reload, a website restart
and a worker crash.

None of the three queues is the ingestion queue. An ingestion backlog delaying
somebody waiting at a screen is the one failure a shared queue guarantees. **The worker
deploys before the website**: a workflow addressed to a queue nothing polls waits for ever
with no error anywhere. A `chat-model-queue` slot is one agent run in flight, not one model
call, and a delegated turn takes one slot for each running sub-agent.

`nagging.py` is why a chat turn is a loop rather than one call. An agent stops when the
model stops calling tools, which is not the same as the work being done, so `AgentRun` reads
the session's todo afterwards and runs the agent again (under its own `nag` role in the
transcript) while items are still open. `append_nag` writes the nag row, the nag text into
the thread and the counters into the run row. **The counters live in the run row, not in the
agent**, because they have to outlive an agent process that restarts mid-turn. Two nags
while the plan is not moving, five in the whole turn, and each buys a fixed extra tool
budget rather than resetting it. What counts as the plan moving is
`database/chat_todos.py`'s question and not a second copy of it: a status flip is not
progress, or a model could keep a turn alive for ever by toggling one row.

`trajectory.py` turns the agent's raw event list into transcript rows, and
`stream_writer.py` mirrors the same events live while they arrive. The two must agree, and
for a while they did not: this path wrote `json.dumps(event)[:400]` as the message body
with the tool name hardcoded to `"tool"` and none of `tool_input` / `tool_output` /
`doc_refs` populated, so a transcript rendered as a wall of JSON in a card whose expand
panel opened onto nothing. **If you change the event format, change both.**

`summarize.py` names a conversation from its first exchange. It runs as an activity after
the answer is written, and it **cannot fail the turn**: one attempt, a short timeout, every
exception swallowed in the activity and again in the workflow. The provisional title the
website wrote from the user's first message is the fallback.

The one shape fact that catches everyone: there is **no tool name on a start event**. It
appears only at `output.name` on the end event, so events have to be paired before a call
can be labelled at all.

## Temporal visibility

Every workflow the pipeline starts (top-level submissions and child workflows alike)
carries the `CollectionDataset` keyword search attribute (`visibility.py`), registered
idempotently at every worker startup. The admin workflow browser filters on it, so
child workflows (`HandleFolders-<hash>`, per-plan runs) show up in a collection-scoped
query.

Registration alone is **not** sufficient: the Temporal frontend caches the attribute
list, so after a fresh `./deploy --reset` there is a window where the attribute is
provably registered yet workflow starts using it are still rejected with
`search attribute CollectionDataset is not defined`. Submitting processes
(`main.py add-disk-dataset`, the P0/P1/P2 `submit_job.py` paths) therefore call
`ensure_search_attributes_ready` and wrap the start in `start_with_attribute_retry`.
Polling cannot close the frontend-cache window, only retrying the start can.

## Activity liveness and outbound HTTP

Every activity declares `heartbeat_timeout = HEARTBEAT_TIMEOUT` (30 s) at all 55 call
sites, and every activity body is wrapped in `@with_heartbeat` (`heartbeat.py`), which
beats every 15 s from a pump thread. The blanket wrap is deliberate: any activity whose
real work legitimately exceeds the deadline (ffprobe on a large video, a Manticore batch
write) would otherwise be killed and retried forever.

`model_step` and `tool_call` are the exception. Their heartbeat limit is 30 s, their pump
beats every 10 s, and the chat-model, research and tool workers set
`max_heartbeat_throttle_interval` to 5 s. A stop cancels the activity, and the worker learns
of a cancel only from a heartbeat reply, so it learns of a stop within about two beats. The
request to the agent service runs in a thread of its own, so the step stops within a
second after that, also during a long tool call or a model call that waits in the model
server queue.

The 2x margin is deliberate too, and widening it is a trap. The deadline is also how
long a wedged slot is held before the fleet can reuse it, so a wider one starves the
remaining slots and produces *more* timeouts. Measured, only this number changing: 30 s
gave a 106 s smoke run with 4 retried activities; 120 s gave 220 s with 29. When
timeouts appear under load, reduce how far the box is oversubscribed
(`common_workers` x `common_concurrency`), never the detector's sensitivity.

`ACTIVITY_MAX_ATTEMPTS` (5) is sized for the same phenomenon from the other side. Roughly
one activity in a hundred is dispatched during a parse burst and completed by the worker
after the server has already expired it, and those losses are correlated. The process
that missed one beat misses the next. Three attempts has been observed running out on a
20-millisecond activity and failing that file's whole parse. An attempt that is never
needed costs nothing, and every activity is idempotent on retry. Activities with a
real loop additionally beat a `HeartbeatClock` inside it, which is evidence of forward
progress rather than only a live thread.

Every heartbeat goes through `send_heartbeat` (`heartbeat.py`): the pump, the
`HeartbeatClock`, `stop_if_worker_is_stopping`, and the cursor heartbeat of a scan range.
A stage activity of the group workflow registers its batch progress with
`batch_progress`, and `send_heartbeat` then puts the batch detail first on every
heartbeat of that attempt. When a file passes its try time limit, `send_heartbeat` drops
every heartbeat of the attempt, so the server ends the attempt at the heartbeat timeout.
A new direct call of `activity.heartbeat` inside a stage keeps a stalled attempt alive,
so a stage must not make one. A stage activity has no attempt limit
(`RetryPolicy(maximum_attempts=0)`). Its runner fails it after 5 consecutive attempts
that finish no new file, and it gives each file its own 5 tries inside an attempt.
`threading`/`contextvars`/`time` are imported lazily inside the
helpers, never at module scope, because workflow modules import `HEARTBEAT_TIMEOUT` from
here and the workflow sandbox restricts those modules.

## Stopping a worker, and what a deploy of this directory may break

A worker being shut down gets a graceful period (`worker_graceful_shutdown_seconds` in
the configuration) before its in-flight activities are cancelled, and the worker
container's stop grace period is derived from that same key with a margin on top, so the
runtime cannot SIGKILL through it. Both halves are needed: without the SDK setting the
activities die where they stand, and without the container setting the SDK's period is
unreachable. The supervisor process forwards `SIGTERM` to every worker child, because a
container runtime signals only PID 1 and the workers are its grandchildren.

Batch activities check `stop_if_worker_is_stopping()` between items. It raises a
retryable error rather than returning early: a batch that returned a partial result would
report success over work it had not done, and its workflow would mark the stage finished.
Raising hands the batch back to Temporal, which redelivers it to a live worker, which
skips the already-written work through the same left-anti joins and watermarks that make
every stage re-runnable. Failing at once also costs an attempt instead of a heartbeat
deadline, which is what makes a restart under load survivable: an activity killed in
place is not noticed until its deadline expires, and that time comes out of the same
budget the retries need.

**The asymmetric deploy rule.** A running execution replays its history against the code
deployed *now*. Changing an `activities.py` is free. Activity results are already in the
history, and the new code only runs for the next call. Changing a `workflows.py` (the
order of its commands, the ids it gives its children, a loop, a timer) makes a live
execution's replay disagree with its history, and it wedges with a non-determinism error
until someone terminates it. So a workflow change requires no live executions of the
workflows it touches: drain the queue, or terminate and re-drive, and only then restart
the worker. `.agents/check-workflow-diff.py` says which of the two a diff is and names
the files.

**The pipeline drain.** No workflow versioning exists. A change to the command sequence of
`Operation`, `IngestAndProcessDataset`, `ExecutePlans`, `ExecuteSinglePlan` or
`IndexDatasetPlan` therefore needs the drain before the deploy. With the old workers still
up, count the open workflows of these five types with `temporal workflow count --address
temporal:7233` and an `ExecutionStatus='Running'` query. Cancel each live operation with
`main.py operations cancel <op_id>`, and cancel a workflow with no operation row by its id.
Deploy only when the count is 0. A `queued` operation is cancelled like the others, and a
person dispatches it again after the deploy with `main.py operations rerun <op_id>`.

Outbound HTTP from activities (NER, OCR, embeddings) goes through
`remote.py`: `(connect, read)` two-tuple timeouts (`GPU_CONNECT_TIMEOUT_MS`, default
2 s connect), an ordered endpoint list with an optional CPU twin, and a per-endpoint,
time-boxed circuit breaker (`GPU_CIRCUIT_BREAK_SECONDS`). A connect failure falls back;
a read timeout does not. `RemoteResult.provider` records which endpoint actually served.

## Where processing time goes (`task_timing.py`)

Every worker installs `TaskTimingInterceptor` (a Temporal **activity inbound
interceptor**), so one row lands in the collection's `processing_task_runs` per activity
execution, and one row for each file of a stage activity of the group workflow: task name, dataset, artifact hash, wall duration, outcome, attempt, queue,
worker process, plus queue-wait (`scheduled_at`, `schedule_to_start_ms`,
`retry_backoff_ms`) and the parent workflow identity (`workflow_id`, `workflow_run_id`,
`workflow_type`). The interceptor is the hook rather than the 79 call sites or
`@with_heartbeat` for one reason: it cannot be forgotten by the next activity someone
adds. `tests/unit/test_task_timing.py` asserts every `Worker(...)` installs it.

Operation-owned successful and skipped rows are durable before an activity returns.
The interceptor writes document outcomes first for each file of a P3 stage activity, P4
and P5 chunk members, and hashes returned by P6 writers. Each outcome and task run share
the Temporal execution identity.

A stage activity returns a `BatchResult`. The interceptor writes one run row for each
file, with the per-file function name, the file hash, and the file's own outcome, run
time and start. The attempt, the activity id and the queue-wait columns are those of the
stage activity, the same on every file row. A stage name, such as `run_tika_batch`, gets a
run row only when the stage activity raises, so it always has the outcome `error`, and a
failure rate grouped by task name shows each stage name at 100 percent.

Three properties decide what the table can answer:

- **Failures are in the same table.** An activity that raises is recorded with
  `outcome = 'error'` and its real duration, so "where did the time go" includes the time
  spent failing and retrying. `processing_errors` still holds the stack traces. The two
  are joined on `(collection_dataset, hash)`, not merged.
- **Batched.** Rows buffer in-process and a daemon thread drains them every 5 s or every
  500 rows. A ~200k-file ingest is millions of executions, and one insert each would
  distort the measurement it is taking.
- **Never silent.** Instrumentation may not fail an ingest, so every write is wrapped,
  but every drop is logged with a count: a failed insert, an overflowing buffer, and the
  handful of activities whose parameters carry no `collectionname`
  (`ensure_temp_dir_exists`, `cleanup_temp_dir`, `collect_eta_samples`, the P_agent chat
  activities), which are recorded in the global `Hoover4_Processing` copy of
  `processing_task_runs` with an empty `collection_dataset`.

The same thread samples what is *running* into `processing_task_inflight`, because a
finished-rows table cannot show the twenty-minute activity that has not finished yet.
Samples are levels, not counters: a reader takes the newest per worker and sums those.
Inflight is busy slots inside a worker process. Queue *waiters* are
`Hoover4_Processing.processing_queue_backlog`, sampled from Temporal `DescribeTaskQueue`
every 10 s by the common worker: one row per known queue, TTL 2 days like inflight. A
sample is kept whenever any queue has a poller attached, not merely when one reports a
backlog -- a server that leaves the enhanced `stats` block empty falls back to
`backlog_count_hint`, which reads 0 for a task that is sync-matched or about to be, so a
fleet stalled on dispatch reports zeros everywhere while activities wait seconds to
start. Only a stack with no workers at all costs zero rows.

Read it back with `main_services/task-time-report.sh` (per-task totals, shares, p95, wall
clock, achieved parallelism) or on `/admin/collections/<name>/processing`, which has both
the after-the-fact breakdown and a live view.

## The AI tier is optional

The website and pipeline degrade rather than hard-fail when the AI services are down:
P4 records `processing_errors` and continues with empty entities, and chat writes the
failure into the transcript. This is confirmed as wanted behaviour. Do not add a
startup-time hard dependency on the AI tier.

## Worker Queues

Workers are split into dedicated queues to control throughput and resource usage:

- `processing-common-queue`, all workflows plus the common activities.
- `processing-tika-queue`, Tika parsing.
- `processing-ocr-queue`, OCR.
- `processing-nlp-queue`, P4 entity extraction against the remote NER service
  (`main.py worker nlp`, concurrency 4).
- `processing-embed-queue`, P5 chunk+embed against the remote embeddings service
  (`main.py worker embed`, concurrency 6).
- `processing-indexing-queue`, P6 Manticore writes and the dataset-wide tree steps
  (`main.py worker indexing`, `indexing_workers` processes, 4 by default, of one slot
  each).
- `processing-index-planner-queue`, P6 shard planning (`plan_shards`). MUST run at
  exactly one worker process: the planner does a read-modify-write on the shard ledger
  and assignments, which is only race-free when serialized.
- `processing-email-graph-queue`, `build_email_graph` (`main.py worker email-graph`).
  MUST run at exactly one worker process of one slot. A run deletes its collection's
  rows that are older than its own start. Two runs at once can delete each other's rows.
- `chat-queue`, `AgentRun` plus `open_run`, `append_nag`, `write_ending`, `fan_in`,
  `continue_run`, `delegate_step`, `prepare_continuation`, `record_step_failure`,
  `plan_has_sections`, todo reads and session titles (`main.py worker chat`, concurrency
  from `chat_low_latency_concurrency`).
- `chat-model-queue`, `model_step` for those chat turns and their sub-agents
  (`chat_model_concurrency`, 3 slots). A slot is one model call in flight.
- `research-queue`, `model_step` of a plan run (`research_concurrency`, 3 slots), outside
  the chat-model slots.
- `agent-tool-queue`, `tool_call` of every agent run (`agent_tool_concurrency`, 16 slots).
  A slot is one tool call in flight. A delegation takes no tool slot.

### How the numbers are chosen

Every tier's slot count comes from what that tier waits on, and `worker_concurrency()`
lets `hoover4.ini` override any of them. The pipeline keys are empty by default, because
a default that is a measurement is better than one a deployment guessed. The four agent
keys are set: a slot is one model call or one tool call in flight.

The two remote tiers pipeline HTTP against a GPU that has its own admission control, so
their number is the *server's* window (`ai_server_ner_concurrency`,
`ai_server_embed_concurrency`), not anything about this host. Below it the GPU idles
between batches; above it the server sheds with 503 + `Retry-After`, which
`tasks/remote.py` retries, an asymmetry that argues for sitting at the window rather
than under it. A plan's chunk+embed work arrives as a handful of long activities, so
slots below the window turned one stage into several serial waves at the end of every
plan.

The common tier is where the parse fan-out lands, and its *process* count follows the
host: `common_worker_processes()` gives `cores/4`, bounded to 2..8. A constant there
suited the four-core machine it was written on and left a sixteen-core host idle.

## Database Routing

Every params dataclass that carries `collection_dataset` also carries `collectionname`.
It is resolved once at the workflow entry point (or CLI submission, e.g.
`main.py add-disk-dataset <collectionname> <dataset_name> <path>`) and threaded through
every child workflow and activity, never re-derived inside an activity. Activities open
per-collection ClickHouse clients with `get_collection_client(params.collectionname)`;
global tables (dataset registry, collections) use `get_global_client()`.

## Navigation

-  [Go Back](../Readme.md)
