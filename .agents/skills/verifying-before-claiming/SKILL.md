---
name: verifying-before-claiming
description: Select and run checks for changed behavior, and assess whether captured evidence supports a result. Use before reporting implementation or runtime success.
allowed-tools: Bash, Read, Grep, Glob
---

# Verifying before claiming

Match each claim to evidence from the relevant code and environment.
Run a new check when changes or uncertainty invalidate existing evidence.
Reuse captured output when its revision, inputs, environment, and coverage still support the claim.

Read the exit status and complete result. A skipped check does not pass.
State whether a change corrects the cause or only removes the current symptom.
A type check supports a compilation claim. Runtime and interface claims need their own evidence.

Select tests by changed behavior and dependencies.
Use the full relevant fast suite when selection costs more than running it.
Add a regression test for a meaningful failure mechanism. Avoid tests that only repeat the implementation.
The [test guidance](../writing-tests/reference/test-shapes.md) and [suite inventory](../writing-tests/reference/suites.md) provide further detail.
The retained `../writing-tests/scripts/gate-map.sh` routes paths to candidate checks. Review relevance before running them.

| Changed behavior | Available check |
|---|---|
| Rust types and test targets change. | Run `scripts/cargo-check.sh`. |
| Dioxus components change. | Run `scripts/dx-check.sh` and exercise the affected controls. |
| Worker Python changes. | Run `scripts/pytest-unit.sh [path]`. |
| Research-agent behavior changes. | Run `scripts/pytest-research-agent.sh [path]`. |
| MCP or shared agent code changes. | Run `scripts/pytest-agents.sh [path]` against the affected images. |
| OCR-PDF behavior changes. | Run `scripts/pytest-ocr-pdf.sh [path]`. |
| Test reachability changes. | Run `scripts/test-reachability.sh`. |
| Website backend contracts change. | Run the relevant cases in `website/run-stack-tests.sh`. |
| Ingestion and storage contracts change. | Use `main_services/verify-stack.sh` for the affected end-to-end claim. |

Scripts above are relative to this skill unless they name a repository path.
Verify the source loaded by the test process. An image can contain older code than the checkout.
Use the supported rebuild or a controlled source mount or copy when appropriate.
Do not restart a container that owns a running check.

Verify fixture availability before interpreting integration or screenshot failures.
For visible changes, use the browser skill and preserve its report.
For model-driven behavior, exercise the actual prompt and tools before claiming the model completes the task.

Keep complete output for long checks and record the command, tested revision, result, and limitations.
See [stack verification](reference/verification-runs.md) and [browser verification](reference/browser-pass.md) when those checks apply.
