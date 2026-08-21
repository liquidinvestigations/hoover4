---
name: running-consecutive-subagents
description: Runs sub-agents the way this repository requires — one at a time, waited on, self-timeboxed, each with a hand-written work package and a report file of its own. Use before delegating anything to a sub-agent, and whenever asked to "fan out", "delegate", "coordinate", "run agents in parallel", "spawn a swarm", "organize this", or "have an agent do X". Covers what belongs in a work package, how to review a pass (read its diff, never its report), and the two cases where a sub-agent is the wrong tool entirely.
allowed-tools: Task, Read, Write, Edit, Glob, Grep, Bash
---

# Running consecutive sub-agents

The rule is not a style preference. Parallel unsupervised agents on this stack produce work
that has to be read anyway, on a live system that only tolerates one deploy at a time, and
whose failures are indistinguishable from each other in the logs.

## The rule

**One at a time. Waited on. Self-timeboxed. Hand-written work package. Report to a file.**

- **One at a time** — never a swarm, never a parallel fan-out. Two agents editing this tree
  produce a merge you did not plan and a stack you cannot attribute a failure in.
- **Waited on** — the launching agent blocks on the result and reviews it before the next
  pass starts. A pass that is not reviewed before the next one begins compounds its mistakes.
- **Self-timeboxed** — around thirty minutes of work, and the pass reports what it did not
  reach rather than running until it is stopped.
- **A hand-written work package** — a file, written before launch, not a paragraph typed into
  the call. See `planning-work`'s prompt template.
- **A report file** beside the prompt, so the pair is visible in the directory listing.

## When a sub-agent is the wrong tool

- **To avoid thinking.** If you cannot write the work package, you do not understand the task
  well enough to delegate it, and the sub-agent will not understand it either.
- **For a task whose result you cannot check.** Delegating something you have no way to
  verify converts an unknown into a confident-sounding claim.

Broad read-only search over many files is the case where delegation genuinely pays: the
answer is small, the reading is large, and a wrong answer is cheap to detect.

## The work package

Every pass needs all of this, because it starts with none of your context:

1. **Role and scope** — what it owns, and what it must not touch.
2. **What to read first**, by path, and which decisions are settled and closed.
3. **What is true now** — anything that has changed since the documents it will read were
   written.
4. **The deliverable** — the exact output path and its required section list.
5. **The checks**, as runnable commands, with what their output must show.
6. **The prohibitions, each with its reason** — especially anything unrecoverable: pushing,
   publishing, deleting, deploying over live work.

Construct exactly what it needs. It does not inherit your session, and a package that assumes
it does is a package with a hole in it.

## Reviewing a pass

**Read the diff. The report is a claim, not evidence.** A pass reporting success on a check
it did not run reads exactly like a pass reporting success on a check it did run.

- `git diff` the whole range the pass touched, and read it.
- Re-run at least one check the report names, yourself.
- Look for the two things no check catches: private infrastructure detail, and prose that
  records the work instead of describing the system.
- Confirm the prohibitions held. A pass that pushed, deployed or deleted against instruction
  is a finding regardless of how good its output is.

Assume a real error rate. Passes have been confidently wrong about a code path that did not
exist and about a violation count off by two orders of magnitude.

## Reporting on a pass you ran

Say which checks you re-ran yourself, and which you took on the pass's word. Those are
different levels of evidence and collapsing them is how an unverified claim reaches the
tree.

## References

- `reference/work-package-template.md` — the skeleton, and the sections that are always got
  wrong.
