---
name: deploying-the-stack
description: Deploy or restart the authorized part of the hoover4 stack, with configuration generation and worker drain handling.
allowed-tools: Bash, Read, Grep, Glob
---

# Deploying the stack

Inspect the target containers and active jobs before starting.
Use the local infrastructure inventory for the target environment.
Confirm the authorized deployment scope and preserve unrelated services.

`hoover4.ini` owns configuration. The deployment generates environment files.
Read [deploy flags](reference/deploy-flags.md) before selecting a build or reset operation.
A normal bring-up does not prove that an image was rebuilt.

Use `scripts/deploy-logged.sh` to preserve output and the deployment exit status.
Verify the source or image that the changed service actually loads.
Keep build parallelism within the configured resource limit.

Restart a worker through `main_services/restart-worker.sh` so it receives the intended drain period.
The script restarts `hoover4-worker` and `hoover4-ops` together, because both load the worker source.
A bare container restart can interrupt active work.
For a single Compose service, use `--no-deps` when dependency recreation is outside the requested change.
On Podman, an exited init dependency can prevent restart. Verify whether the old container remained running.

Use rendered Compose configuration to verify relative paths.
Verify service reachability from the consuming container after the change.
Read [long jobs](reference/long-jobs.md) when the operation continues beyond one tool call.
Keep communicating while it runs and do not disturb another active verification.
