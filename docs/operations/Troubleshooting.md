# Troubleshooting

Every entry here has cost hours at least once. They are written as standing properties of the
system and the failure each prevents, so a person reading cold can route from a symptom to a
mechanism without knowing the history.

The procedural half (the same ground as a checklist an agent loads mid-task) is
`.agents/skills/debugging-the-stack/`.

## Contents

- [Two rules that come before any symptom](#two-rules-that-come-before-any-symptom)
- [Route by symptom](#route-by-symptom)
- [DNS before the application](#dns-before-the-application)
- [Networks, names and ports](#networks-names-and-ports)
- [A hang is a question about who is blocked](#a-hang-is-a-question-about-who-is-blocked)
- [Pipeline errors: a messy corpus or a stall](#pipeline-errors-a-messy-corpus-or-a-stall)
- [Memory that looks like an OOM and is not](#memory-that-looks-like-an-oom-and-is-not)
- [Failures that produce silence rather than errors](#failures-that-produce-silence-rather-than-errors)
- [Timeout units](#timeout-units)
- [Migrations](#migrations)
- [A change that did not take effect](#a-change-that-did-not-take-effect)
- [The host itself is unresponsive](#the-host-itself-is-unresponsive)
- [Cause or workaround. Say which](#cause-or-workaround--say-which)

## Two rules that come before any symptom

**Trust the error's mechanism, not its wording.** In this system an error message routinely
names the wrong half of the problem. A message about an empty container directory named a
volume line and meant that compose could not find its environment file two directories away.
A message demanding a required environment variable came from a **stale image** whose line
numbers no longer matched the source. A symbol server reporting invalid request parameters
was reporting a session it had never been handshaked on.

Before editing the file an error points at, confirm the value it is complaining about is what
the process actually received:

```
docker exec <container> env | sort
docker compose … config          # renders absolute paths and resolved values
docker logs <container> --tail 200
```

The worked example is worth keeping in mind because it generalises: when the harness and the
server disagree about what went wrong, **the server is the one describing the mechanism**.

**Reproduce from inside the container, never from the host.** "The service is up" on the host
proves nothing. Containers on separate networks cannot address each other by name, and a
rootless container cannot reach its host's LAN address at all. It hangs rather than refuses,
which reads as the remote service being slow. The only test that counts is a request made
from inside the container that has the problem. `host.containers.internal` is the routable
name for the host.

## Route by symptom

| symptom | mechanism to check first |
|---|---|
| one container cannot reach the internet, internal names still resolve | [DNS](#dns-before-the-application) |
| connection refused or timing out between services | [networks and ports](#networks-names-and-ports) |
| something hangs and nothing is logged | [who is blocked](#a-hang-is-a-question-about-who-is-blocked) |
| memory sits near the limit | [a JVM committing its heap](#memory-that-looks-like-an-oom-and-is-not) |
| a parser or extractor returns nothing at all | [a missing binary](#failures-that-produce-silence-rather-than-errors) |
| a configuration value has no effect | [rendered and never read](#failures-that-produce-silence-rather-than-errors) |
| a feature quietly does nothing | [wire-format traps](#failures-that-produce-silence-rather-than-errors) |
| a migration fails naming neither file nor line | [the statement splitter](#migrations) |
| a change did not take effect after a restart | [the old image was reused](#a-change-that-did-not-take-effect) |
| a browser will not start, or "cannot connect" | [subprocesses](#failures-that-produce-silence-rather-than-errors) |
| ingestion is slow rather than broken | the pipeline's shape, not the fleet's size, `.agents/skills/tuning-the-pipeline/` |
| the machine itself is unresponsive | [host load](#the-host-itself-is-unresponsive) |

## DNS before the application

"One container cannot reach the internet" is a DNS question before it is an application
question. A container network created without upstream resolvers forwards to the host's local
resolver stub, which stops answering external queries, while **internal container-name
resolution keeps working**. The pipeline therefore looks healthy and only internet-facing
work hangs: fetching dependencies, the web-search tools.

Diagnose by comparing an internal lookup against an external one from inside the container,
and by inspecting the network's own resolver list.

**Never fix this with a per-container DNS pin in a compose file.** That cuts the container off
from the runtime's own resolver and breaks internal resolution instead. The deploy step that
creates and repairs the network pins resolvers at the network level, which is the right layer.

## Networks, names and ports

The accelerated tier is a private network with no dependency on the main stack, which is the
reason the CPU twins live on the main side. A name from one network does not resolve on the
other.

Every port is a configuration key rather than a literal to remember. A connection refused
against a hard-coded port number is usually the port having moved, not the service being
down.

An endpoint variable that is unset is a distinctive failure: the code falls back to a
loopback default meant for running outside a container, and inside a container loopback is
that container itself. The symptom is a healthy service and a caller insisting it is
unreachable.

## A hang is a question about who is blocked

Check the runtime's view and the process's view **separately** and compare. They routinely
disagree. A workflow service reporting an activity as started does not mean the worker is
running anything. Low CPU means blocked on I/O or a lock, not slow work.

To see Python stacks, the profiler needs a capability these containers drop; attach from a
sidecar sharing the target's pod and process namespace with that capability added. **A thread
dump ends the guessing immediately. Reach for it earlier than feels justified.**

A synchronous call on the event-loop thread stalls an activity indefinitely **while
heartbeats keep flowing**, so it is never retried and never fails. The dump is the only thing
that shows it.

## Pipeline errors: a messy corpus or a stall

A reprocess writes error lines steadily, and log volume alone cannot tell you which of two
very different situations you are in. The distinction is whether anything is still growing.

- **Errors accumulating while `text_content` grows is a messy corpus.** The activity
  *succeeds*, records a `processing_errors` row, and the plan moves on. Malformed mail and
  files that merely claim to be archives produce these by the dozen, and they are not a fault.
- **The same error repeating verbatim while nothing grows is a stall**, and it needs a code
  fix rather than patience.

So the test is not how many errors there are but whether the stage tables are advancing:
count rows in `text_content` for the collection, sample the error text to see whether it
varies, and compare both a minute apart. Identical text plus a flat count is the stall.

One reading to avoid while you are there: a stage showing no activity is not evidence of a
hang if an earlier stage is busy. The stages run in order, so a collection in parsing
legitimately shows nothing in embedding at that instant, and a single sample taken then looks
alarming and means nothing. Sample twice.

## Memory that looks like an OOM and is not

A JVM sized with equal minimum and maximum heap commits its whole heap at boot, so the
container's resident memory sits just under the cgroup limit from the first second of uptime
whether it is doing anything or not. A history store configured with a four-gigabyte heap
reports nearly six gigabytes of a six-gigabyte limit while using a third of that heap.
Reading it as "about to run out" is wrong every time, and the same applies to every other JVM
here.

Ask the runtime instead. The node tools report heap used against heap maximum, garbage
collection time against uptime, and dropped messages per stage. **A healthy node is a low
heap fraction, collection well under one per cent of wall time, and zero drops.**

The container-side number worth reading is the anonymous-memory figure in the cgroup's own
memory statistics, never the runtime's headline total. That counts reclaimable page cache as
usage.

## Failures that produce silence rather than errors

**A shelled-out binary that is not in the image fails silently when the wrapper catches the
missing-file error.** A PDF text extractor called a binary that was never installed; the
wrapper returned nothing and the caller read that as "this PDF has no text", so every PDF
ever ingested produced zero rows from that path and it read as a property of the corpus. When
a parser produces suspiciously little, check that the binary exists in the image *before*
reading any of its code.

**Configuration that is rendered but never read is false.** Several knobs have reached a
worker's environment with no consumer. When adding a key, grep for its consumer in the same
change, or write it down as not-yet-implemented.

**Two wire formats fail as silence.** The workflow engine deserialises an activity argument
into its *annotated* type, so an unannotated parameter arrives as a plain dictionary and the
feature quietly does nothing. And an enum column takes the **name** on insert and returns the
**ordinal** on read, so a read-side comparison against the name matches nothing and raises
nothing.

**A result row binds by column name**, an alias shadows the column it derives from, and an
aggregate returns a row even over an empty match, so "there is a row" is not "there is
data".

**A child process on an undrained pipe wedges, and it looks like a hang in your code.** A
browser in a container writes a continuous stream of errors to standard error; on a pipe
nobody reads, that pipe fills and the child blocks on write. Every subprocess launch needs
its output either drained by a task or sent to the null device.

**A library that "cannot connect to the browser" may never have launched one.** Given an
explicit host and port, some drivers treat that as *attach to something already running* and
silently skip the launch, then blame your privileges. Prove the endpoint exists from inside
the container before believing the error. In the same family: a connect loop that allows a
couple of seconds against a browser that needs five or six reports a connection failure for
something that is merely still starting.

## Timeout units

**Treat every timeout unit as suspect.** The common HTTP client's timeout is in **seconds**,
so a value of 3000 is fifty minutes rather than three seconds. Use a separate connect and
read deadline so a dead host is detected in seconds while real work still gets minutes.

**Detection latency must never be tied to how long the slowest legitimate run takes**, which
is what a single total timeout does.

The same principle has a sharper form in the pipeline: **a heartbeat deadline is also a slot
lease.** Widening it multiplies the failures it was meant to prevent, because every second of
the deadline is a second a slot stays held by an activity nobody is waiting on. Reduce how far
the machine is oversubscribed; never reduce the detector's sensitivity.

## Migrations

**The migration runner splits on the statement separator without parsing SQL.** Three ways to
break it, all failing with an error that names neither the file nor the line:

1. a separator inside a comment literal attached to a column or table;
2. a separator inside a line comment;
3. **prose after the final statement terminator**, which contains no stray separator at all,
   becomes a comment-only fragment, and reaches the server as an empty query.

Put explanatory comments **above** the statement they describe. The parity test covers all
three.

## A change that did not take effect

Bringing containers up reuses existing images and containers. A change to a `Dockerfile`, a
build context, an ignore file, or anything the image copies in rather than mounts, needs a
rebuild, and the build output read in full, not tailed.

A generated environment file hand-edited is overwritten by the next deploy, and looks like it
worked until then.

## Traps that have cost real time here

Each of these presented as something other than what it was.

**Every route returns 500 with nothing logged, repeatedly, a few seconds after start.** A
supervisor that kills by the pid in a pid file, having only checked that *something* is alive
at that pid, will eventually kill the wrong process: pid files survive restarts and pids are
recycled. It killed the website's own binary seconds after launch, and each restart repeated
it. A supervisor must confirm the process is the one it means: `/proc/<pid>/cmdline`, not
liveness alone.

**A 502 immediately after a deploy is expected, not a fault.** The deploy command returns
about five minutes before the site serves, because the release build runs inside the
container. Wait for it before diagnosing anything.

**A log line that no log level can filter** is a `println!` rather than a logging call.
Searching for the message text finds it faster than adjusting log configuration that was never
going to apply.

**Deleting an apparently unreferenced page can break something with no build error.** An asset
bundle held alive by a `#[used] static … asset!()` binding is loaded by literal URL, so nothing
in the source refers to it. Removing the page that carries the binding compiles cleanly and
404s the feature at runtime. Before deleting a page, search for what its assets are named, not
just for references to the page.

## The host itself is unresponsive

The load average plus a process list sorted by CPU names the cause in one step. Three things
that are easy to get wrong:

- **Check the owner column.** More than one account may run its own container runtime on a
  shared machine, so the process at the top of the list is not necessarily yours, and killing
  your own work will not help when it is not.
- **Prefer renicing an in-flight build's process tree to killing it.** A build most of the way
  through has already paid for gigabytes of downloads; renicing restores interactive
  responsiveness without discarding that.
- **Load average lags the fix**, because it counts runnable tasks. Judge by the top
  processes' CPU share and by whether the machine responds, not by the number.

## Cause or workaround: say which

A stalled workflow activity can be cleared by failing it explicitly, and that is a
**workaround**: it proves the retry path works and says nothing about why the task was lost.
The same applies to a restart that clears a symptom, a retry that happens to succeed, and a
value nudged until the error stops.

Report the difference plainly. A fix names the mechanism; anything else names what it
unblocked.
