---
name: debugging-the-stack
description: Diagnoses failures in the running hoover4 stack. A hang, a container that cannot reach another, a connection refused or timing out, an OOM that is not one, a parser returning nothing, a query that silently does nothing, a feature that quietly does not happen. Use when something is broken at runtime and the cause is not yet known, when an error message is being taken at face value, when asked "why is it failing", "why is it slow to respond", "it can't connect", "it's hanging", "nothing happens", or when a container, worker, browser or migration misbehaves. Routes by symptom to the mechanism that has actually caused it here before, and names the command that distinguishes the candidates in one step.
allowed-tools: Bash, Read, Grep, Glob
---

# Debugging the stack

Every entry below has cost hours at least once. They are habits, not trivia.

## Two rules that come before any symptom

**Trust the error's mechanism, not its wording.** `Error: container directory cannot be
empty` named a volume line and meant compose could not find `.env` two directories away.
`LLM_API_KEY environment variable is required` came from a stale image whose line numbers no
longer matched the source. Before editing the file an error points at, confirm the value it
complains about is what the process actually received:

```
.agents/skills/debugging-the-stack/scripts/inspect-env.sh <container> <VAR>
docker compose … config          # renders absolute paths and resolved values
docker logs <container> --tail 200
```

**Reproduce from inside the container, never from the host.** "The service is up" on the
host proves nothing: containers on separate networks cannot use container names, and a
rootless podman container cannot reach its host's LAN IP at all. It hangs rather than
refuses. `docker exec <worker> curl -sS --max-time 5 <url>` is the only test that counts.
`host.containers.internal` is the routable name for the host.

## Route by symptom

| symptom | look here first |
|---|---|
| a container cannot reach the internet, internal names still work | DNS on the podman network, `reference/networking.md` |
| connection refused / timeout between services | wrong network, or the port is an ini key you assumed, `reference/networking.md` |
| something hangs and nothing is logged | who is blocked, `reference/hangs-and-stalls.md` |
| memory near the cgroup limit | almost certainly a JVM committing its heap, `reference/jvm-memory.md` |
| a parser or extractor returns nothing at all | a shelled-out binary missing from the image, below |
| a config value has no effect | it is rendered and never read, below |
| a migration fails with `Code: 62, Empty query` | the `;` splitter, `reference/migrations-and-wire-formats.md` |
| a feature silently does nothing | a wire-format trap, `reference/migrations-and-wire-formats.md` |
| the browser will not start or "cannot connect" | `reference/browser-and-subprocesses.md` |
| a change did not take effect after a restart | `up -d` reused the old image, `deploying-the-stack` |
| ingestion is slow rather than broken | `tuning-the-pipeline` |
| the host itself is unresponsive | `reference/host-load.md` |

## Four traps that produce silence rather than errors

**A shelled-out binary that is not in the image fails silently when the wrapper catches
`FileNotFoundError`.** `parse_pdf.py` has always called `pdftotext`; `poppler-utils` was
never installed; the wrapper returned `None` and the caller read that as "this PDF has no
text", so every PDF ever ingested produced zero rows from that path and it looked like a
property of the corpus. When a parser produces suspiciously little, run
`docker exec <c> which <binary>` before reading any of its code.

**Config that is rendered but never read is a lie.** Several knobs reached a worker's
environment with no consumer. When adding a setting to `hoover4.ini`, grep for its consumer in
the same change, or write it down as not-yet-implemented.

**Treat every timeout unit as suspect.** `requests`' `timeout=` is seconds; `timeout=3000`
is fifty minutes, not three seconds. Use a `(connect, read)` two-tuple so a dead host is
detected in seconds while real work still gets minutes. Detection latency must never be
tied to how long the slowest legitimate run takes.

**A child process on an undrained pipe wedges, and it looks like a hang in your code.**
Chromium in a container writes a continuous stream of D-Bus and GCM errors to stderr; on a
`PIPE` nobody reads, the pipe fills and the browser blocks on write. Every
`create_subprocess_exec` needs its output drained by a task or sent to `DEVNULL`.

## How to work while it is live

Prefer the one command that answers the question over several that describe the situation,
and run independent checks in parallel. Background anything long and keep working. A
monitor that only emits on failure signatures beats polling, but make sure its filter
would fire on a crash, because silence must not be indistinguishable from success.

Do not disturb a long-running verification: `main_services/verify-stack.sh` runs inside
`hoover4-worker` and any `./deploy` kills it with `EXIT=137`. Check what is in flight,
batch fixes, restart once.

**Fix causes, not symptoms, and say which you did.** Clearing a stalled activity with
`temporal activity fail -w <id> --activity-id <n>` proves the retry path works and says
nothing about why the task was lost. Report that difference plainly.

## References

- `reference/networking.md`, DNS on the podman network, container-name resolution, the
  `dns:` pin that must never be used, port-versus-ini-key mistakes.
- `reference/hangs-and-stalls.md`, the runtime's view versus the process's view, reading
  `docker stats` correctly, attaching py-spy from a sidecar sharing the pod and PID
  namespace.
- `reference/jvm-memory.md`, why Cassandra and Elasticsearch always look near their limit,
  and the `nodetool` numbers that answer the question instead.
- `reference/migrations-and-wire-formats.md`, the three ways to break the `;` splitter, and
  the two silent wire-format traps (Temporal annotated arguments, ClickHouse `Enum8`).
- `reference/browser-and-subprocesses.md`, nodriver skipping the launch, the connect-loop
  budget, proving the endpoint exists.
- `reference/host-load.md`, reading load average, the owner column, renicing an in-flight
  build, and `BUILD_JOBS`.
