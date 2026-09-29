---
name: tuning-the-pipeline
description: Measure and improve ingestion or search throughput when performance is the requested outcome.
allowed-tools: Bash, Read, Grep, Glob
---

# Tuning the pipeline

Measure the requested workload before changing concurrency or timeouts.
Record throughput, latency, queue delay, resource use, and failures that affect the comparison.
Keep the workload and relevant configuration comparable.

Locate the limiting stage.
A single workflow can limit scheduling while workers remain idle.
A shard, storage service, model process, or resource limit can produce the same visible symptom.
Use [the synthetic probe](reference/synthetic-probe.md) when it separates scheduling from service capacity.

Choose concurrency from measured capacity.
More workers do not remove a serial dependency.
A barrier can make a batch wait for its slowest item.

Treat timeout changes as tradeoffs.
A longer heartbeat interval can retain a slot after useful work stops.
Verify activity duration, heartbeat delivery, retries, and cancellation before changing it.

Keep ownership and idempotency unchanged while improving batching or scheduling.
Compare the actual result and failure rate after the change.
Do not generalize a measured throughput value to a different host or workload.
