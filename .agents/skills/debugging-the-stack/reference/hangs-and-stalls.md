# Hangs and stalls

Compare workflow state, activity heartbeats, and the actual worker process.
A started activity can be waiting without useful work.
Low CPU alone does not identify the cause.

Inspect thread stacks when they can distinguish I/O, lock contention, and event-loop blocking.
The supplied sidecar can collect Python stacks when the target lacks ptrace capability.

```sh
scripts/pyspy-sidecar.sh <container> [pid]
```

Verify the required namespace access before attaching.
A synchronous call on the event-loop thread can block progress.
Heartbeats from another thread may continue during that block.
Compare the stack with heartbeat and timeout configuration before selecting a correction.
