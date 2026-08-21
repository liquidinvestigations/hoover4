---
name: tuning-the-pipeline
description: Makes ingestion, indexing and search faster, and diagnoses a pipeline that is slow rather than broken. Use when asked to "speed this up", "why is ingestion so slow", "improve throughput", "add more workers", "tune Temporal", "increase concurrency", "it takes too long", or when a run's wall clock is the complaint. Covers why a single driver workflow is a latency ceiling that no number of workers moves, why a barrier over a batch costs the slowest member, why widening a heartbeat deadline multiplies the timeouts it was meant to prevent, and the synthetic probe that separates a server limit from a shape limit in one measurement.
allowed-tools: Bash, Read, Grep, Glob
---

# Tuning the pipeline

Almost every "the pipeline is slow" question here turns out to be about the **shape of the
work**, not about the size of the fleet. Establish which before changing anything.

## The one fact that decides most of it

**Temporal serialises workflow tasks within an execution.** A workflow decides one thing at a
time no matter how many workers are idle. A single driver workflow therefore saturates near
fifty executions a second on this cluster, and no number of slots, workers, history shards or
task-queue partitions moves that number. Only **more concurrent executions** does, and that
scales close to linearly.

Two consequences to have in hand before touching a knob:

- **A fan-out driven from one parent is a latency ceiling, not a capacity one.** Adding
  workers to it changes nothing.
- **A `gather` barrier over a batch makes every batch cost its slowest member.** On a corpus
  whose per-file p99 is fifteen times its p50, that is most of the wall clock.

## The heartbeat deadline is also a slot lease

Widening it multiplies the failures it was meant to prevent. Under a burst that
oversubscribes the machine, a worker sometimes cannot get a beat out in time; every second of
the heartbeat timeout is then a second that slot stays held by an activity nobody is waiting
on, which starves the remaining slots and makes their beats late too.

Measured on this pipeline with nothing else changed: a 30 s deadline gave a 106 s run with 4
retried activities; a 120 s deadline gave 220 s with 29.

**The tell** is a retried activity whose schedule-to-start time is almost exactly the
deadline, together with a stretch of wall clock in which no activity starts at all.

**Reduce how far the machine is oversubscribed. Never reduce the detector's sensitivity.**

## Server limit or shape limit — one measurement

Do not infer it from the pipeline. Run a throwaway workflow and a no-op activity on a private
task queue, from inside the worker container. It measures the same cluster and the same
worker library with none of the pipeline in the way, so the answer is unambiguous:

- the probe reaches a rate far above what the pipeline gets → the limit is the pipeline's
  shape;
- the probe reaches the same rate → the limit is the cluster or the worker configuration.

`reference/synthetic-probe.md` has the method.

## Order of investigation

1. **Where is the time?** Per-stage and per-activity timings, from the stored timing samples
   — `querying-the-datastores`. Tuning a stage that is not the bottleneck is free of effect.
2. **Is it slow or is it blocked?** Low CPU with no progress is I/O or a lock, not slow work.
   `debugging-the-stack` — a hang and a slow run need completely different answers.
3. **How many executions are in flight?** If the answer is one, that is the finding.
4. **What does the distribution look like?** A p99 far above the p50 with a barrier over the
   batch is a shape problem, and the fix is to remove the barrier, not to add capacity.
5. **Only then**, worker counts and slot counts — and re-measure after each single change.

## What not to do

- **Do not widen a timeout to make a timeout stop.** It converts a detector into a hazard.
- **Do not add workers to a serialised driver.** It costs memory and changes no number.
- **Do not change two knobs at once.** Every measurement here has a wide enough spread that
  two simultaneous changes cannot be attributed.
- **Do not tune against a machine that something else is already saturating.** Read the load
  and the owner column first.

## References

- `reference/synthetic-probe.md` — the throwaway workflow and no-op activity, what to
  measure, and how to read the two outcomes.
