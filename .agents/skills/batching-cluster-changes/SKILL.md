---
name: batching-cluster-changes
description: Plan, apply, and wait on Kubernetes, k3s, Kata, gVisor, or GPU workload changes in batches so that one wait shows many failures. Use before you apply manifests, run `k3s/deploy-k3s`, build images, restart services, or wait for pods, guests, or probes.
allowed-tools: Bash, Read, Grep, Glob, Monitor
---

# Batching cluster changes

A cluster change costs a start, a probe, and often a back-off timer before its result is visible.
Put many changes into one wait, and stop each wait at the first result.
Past sessions in this repository lost most of their wall-clock time to poll loops, waits that ended in a timeout,
and one fix followed by one more wait.

## Before the batch

1. Write all the changes of the stage before you apply any of them. Include images, manifests, Secrets, volumes, and setup steps.
2. Start every long build or pull first, in the background. Write the manifests while they run.
3. Check each input that the change reads: the image entrypoint, the user, paths, ports, volumes, probes, and environment names.
   Read them from the source or the image, not from memory.
4. Validate the complete render in one call with `kubectl apply --dry-run=server`. Use `kubectl diff` for an update.
5. Collect all host and k3s configuration changes, and restart each service once.

## Apply and wait

1. Apply all independent objects in one command. Apply ordered steps in order only where an order exists.
2. Run a wait that takes more than about 2 minutes with `run_in_background`, and wait for its notification.
   Do not block a turn on a poll loop. Do not set a Bash timeout above 600,000 ms.
3. Give every wait a deadline, a failure exit, and a final state line.
4. Use one sweep that prints all pods that are not ready, with their waiting and terminated reasons and the recent Warning events.
   Stop the wait when the sweep shows CrashLoopBackOff, an image error, a configuration error, or OOMKilled.
   Waiting longer does not repair these states.
5. Replace a fixed `sleep` with a condition check every 2 to 5 seconds.
6. Use `Monitor` with a failure filter, for example `Traceback|Error|OOM|^done`, for a long run with many stages.
7. Do work that does not depend on the wait while it runs, for example the next batch, the documentation, or the record.

## After a failure

1. Read conditions and Warning events first, then `kubectl logs --previous`, then the application log.
2. Collect all failures of the sweep before you change anything. Fix all of them, then wait once.
3. After a fix, delete the failed pod. A CrashLoopBackOff or image back-off timer grows to 300 seconds.
4. Reproduce a failure with the smallest check that shows it. Run the full end-to-end check only after the small check passes.

## Limits

A measurement run and a timed benchmark must wait for the real interval. Record that interval.
Run waits in parallel only when the objects are independent. Stop a parallel batch when a shared dependency fails.
Do not restart a workload that owns a running check.
A `pkill -f` pattern also matches the shell that runs it when that command line contains the same text.
Use a bracket pattern such as `'[s]eed.py'`, and do not name the target elsewhere in the same command.
