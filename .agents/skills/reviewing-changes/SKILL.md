---
name: reviewing-changes
description: Review a repository diff for correctness, scope, and cross-component contracts. Use for a requested review or before committing changes.
allowed-tools: Bash, Read, Grep, Glob
---

# Reviewing changes

Read the actual diff against the agreed baseline and requirements.
Follow affected callers and storage contracts where needed. An executor's report does not replace the diff.

Report concrete defects with their location, observable consequence, and necessary verification.
A blocking finding identifies a correctness fault, requirement violation, unsafe behavior, or missing evidence needed for acceptance.
Keep preferences and unrelated improvements non-blocking.

Use [the repository checklist](reference/checklist.md) for affected boundaries.
Pay particular attention to mirrored Python and Rust behavior, writer identities, migrations, Temporal payloads, and access checks.
Review frontend hook ordering and real interaction evidence when visible behavior changes.

Recommend a refactor only when it resolves a demonstrated defect or simplifies the requested change.
An abstraction with one implementation, a private test helper, or repeated conditions alone do not establish a defect.
Do not turn a review into a new architecture investigation without evidence that the requested outcome requires it.

Read captured checks and verify that they cover the changed code and relevant environment.
Rerun when edits, failures, or uncertainty invalidate the evidence. A new review turn alone does not invalidate it.

Give the smallest sufficient correction. The organizer chooses its execution structure and role.
Do not count defect classes to prescribe batches, new passes, or stopping conditions.
When a defect repeats, diagnose its cause.

State unresolved findings and limits of the review. A self-review is not an independent review.
Executors and reviewers run no Git write commands.
