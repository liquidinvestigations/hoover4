---
name: operating-remote-hosts
description: Inspect or change an authorized remote hoover4 deployment using the local infrastructure inventory.
allowed-tools: Bash, Read, Grep, Glob
---

# Operating remote hosts

Read `INFRASTRUCTURE_INVENTORY.md` for access details and ownership.
Keep host names, addresses, credentials, and access boundaries out of tracked files.

Inspect the current engine, architecture, mounts, service configuration, and active work.
Do not treat a previous deployment's layout or capacity as current evidence.
Reproduce failures inside the affected container.

Read-only diagnosis does not imply authorization to deploy, reset, or change configuration.
Use existing authorization when it covers the action. Do not ask again because a new turn began.
Keep source changes in the reviewed checkout and deliver them through the deployment process.

Scope cleanup to project-owned resources. Do not prune a shared runtime.
Before an authorized reset, preserve state that ingestion cannot reconstruct.
Verify collection metadata, fixture paths, and build-cache consequences.

For GPU changes, verify the actual device, installed dependencies, and workload.
Measure throughput before choosing batching or concurrency settings.
Read [remote procedures](reference/remote-work.md) for the relevant operation.
