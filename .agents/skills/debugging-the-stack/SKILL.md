---
name: debugging-the-stack
description: Diagnose a runtime failure in the hoover4 stack using the process, inputs, and service state that produced it.
allowed-tools: Bash, Read, Grep, Glob
---

# Debugging the stack

Locate the failing process and verify its actual input before changing configuration.
Treat error text and historical causes as hypotheses.
Read the local infrastructure inventory for access details. Keep those details out of tracked output.

Run diagnostics inside the container that experiences the failure.
A host request does not verify container-to-container reachability.
Distinguish an empty result from a failed request.

| Symptom | Relevant procedure |
|---|---|
| A connection fails or reaches the wrong service. | Read [networking](reference/networking.md). |
| A workflow or worker stops progressing. | Read [hangs and stalls](reference/hangs-and-stalls.md). |
| Memory or CPU pressure appears. | Read [host load](reference/host-load.md). |
| A JVM process fails under a memory limit. | Read [JVM memory](reference/jvm-memory.md) after verifying the process. |
| A browser or child process hangs. | Read [browser and subprocesses](reference/browser-and-subprocesses.md). |
| A migration or service response fails unexpectedly. | Read [migrations and wire formats](reference/migrations-and-wire-formats.md). |

Use the smallest diagnostic that distinguishes the remaining explanations.
Do not reset the stack to investigate a symptom.
When a restart is authorized, capture the relevant state first and verify whether the cause remains.
