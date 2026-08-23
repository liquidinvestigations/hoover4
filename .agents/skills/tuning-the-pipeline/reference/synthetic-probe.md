# The synthetic probe

A throwaway workflow and a no-op activity, on a private task queue, run from inside the
worker container. It answers one question that nothing else answers cheaply: **is the limit
the cluster, or the shape of the work?**

## Why it has to be synthetic

Measuring the pipeline measures the pipeline. Every stage carries its own I/O, its own
retries and its own batch shape, so a slow run is consistent with a dozen causes. The probe
removes all of them and leaves the cluster and the worker library, the two things a
configuration change could actually move.

## Why it runs inside the worker container

It must use the **same** cluster, the **same** client library version and the **same**
network path as the real work. Run from the host it measures a different set of those, and
the number it produces cannot be compared with anything.

## Shape

- A workflow that starts N activities and waits for them.
- An activity that returns immediately and does nothing else.
- A task queue name nobody else uses, so the probe never competes with real work and real
  work never competes with the probe.
- The whole thing deleted afterwards. A probe left in the tree becomes a fixture nobody
  can explain.

## What to measure

- **Activities completed per second**, at a few different concurrency levels.
- **The same, with more than one workflow execution driving them.** This is the measurement
  that matters: if throughput rises close to linearly with the number of concurrent
  executions while it is flat against slot count, the ceiling is per-execution
  serialisation and no worker-side knob will move it.
- **Schedule-to-start latency**, which is where slot starvation shows up before throughput
  does.

## Reading the result

| probe rate | pipeline rate | conclusion |
|---|---|---|
| high | low | the limit is the pipeline's shape, barriers, one driver, batch skew |
| ≈ pipeline rate | low | the limit is the cluster or the worker configuration |
| rises with executions, flat with slots | - | per-execution serialisation, as expected; the fix is more executions |
| schedule-to-start climbing toward the heartbeat deadline | - | the machine is oversubscribed; reduce the load, do not widen the deadline |

## After the probe

Change **one** thing, re-run the probe if the change was worker-side, and re-run the real
workload if it was shape-side. Two changes at once cannot be attributed, because the spread
on these measurements is wide enough to swallow either of them.
