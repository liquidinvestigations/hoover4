---
name: running-consecutive-subagents
description: Runs sub-agents the way this repository requires, one at a time, waited on, self-timeboxed, each with a hand-written work package and a report file of its own. Use before delegating anything to a sub-agent, and whenever asked to "fan out", "delegate", "coordinate", "run agents in parallel", "spawn a swarm", "organize this", or "have an agent do X". Covers what belongs in a work package, how to review a pass (read its diff, never its report), and the two cases where a sub-agent is the wrong tool entirely.
allowed-tools: Task, Read, Write, Edit, Glob, Grep, Bash
---

# Running consecutive sub-agents

The rule is not a style preference. Parallel unsupervised agents on this stack produce work
that has to be read anyway, on a live system that only tolerates one deploy at a time, and
whose failures are indistinguishable from each other in the logs.

## The rule

**One at a time. Waited on. Self-timeboxed. Hand-written work package. Report to a file.**

- **One at a time**, never a swarm, never a parallel fan-out. Two agents editing this tree
  produce a merge you did not plan and a stack you cannot attribute a failure in.
- **Waited on.** The launching agent blocks on the result and reviews it before the next
  pass starts. A pass that is not reviewed before the next one begins compounds its mistakes.
- **Self-timeboxed**. The pass reports what it did not reach rather than running until it is
  stopped. **A self-timebox is a budget of effort and attention, not a clock**: passes
  reporting they had "roughly doubled" a one-hour box had used twenty-four minutes of it, and
  one reporting a "2.5× overrun" had used forty-seven. Ask a pass what it did not reach, never
  how long it took. An agent's sense of its own elapsed time is a feeling, and wall clock has
  to come from outside it.
- **One item per pass**, and two only when they are one item in a dependency chain that a
  single check closes. A brief listing five different items has been measured to deliver one.
  **Items of the same shape are one item.** One rule applied across a tree is one pass however
  many directories it touches, and a pass here has been measured changing 515 files inside one
  context without compacting.

## Resume rather than replace

A pass that runs out of attention with its item half-done is **resumed**, not replaced: it
costs no slot, it keeps the context it has already paid for, and the work is finishing rather
than starting. Three of five briefs in the last sprint needed one, so budget half a pass for
every item that is not a single mechanical change.

A resume still gets **a written work package** rather than a paragraph. It is a new file
beside the first, answering the questions the pass raised and naming what it must not
revisit.
- **A hand-written work package.** This is a file, written before launch, and never a
  paragraph typed into the call. See `planning-work`'s prompt template.
- **A report file** beside the prompt, so the pair is visible in the directory listing.

**A pass with context left is given the next item rather than replaced.** One agent here took
four work packages into one context. The first cost 62 minutes because it read the corpus. The
second, third and fourth cost 25.6, 12.5 and 12.3 minutes, because they did not have to read it
again. A fresh pass pays that reading back every time, and it pays it out of the same budget the
work needs.

## When a sub-agent is the wrong tool

- **To avoid thinking.** If you cannot write the work package, you do not understand the task
  well enough to delegate it, and the sub-agent will not understand it either.
- **For a task whose result you cannot check.** Delegating something you have no way to
  verify converts an unknown into a confident-sounding claim.

Broad read-only search over many files is the case where delegation genuinely pays: the
answer is small, the reading is large, and a wrong answer is cheap to detect.

## The work package

Every pass needs all of this, because it starts with none of your context:

1. **Role and scope**. What it owns, and what it must not touch.
2. **What to read first**, by path, and which decisions are settled and closed.
3. **What is true now**. Anything that has changed since the documents it will read were
   written.
4. **The deliverable**, the exact output path and its required section list.
5. **The checks**, as runnable commands, with what their output must show.
6. **The prohibitions, each with its reason**, especially anything unrecoverable: pushing,
   publishing, deleting, or deploying over live work.

Construct exactly what it needs. It does not inherit your session, and a package that assumes
it does is a package with a hole in it.

**Inside a plan folder the package is the pass document**, which `planning-work` defines. The
executor is launched on that file, and nothing is transcribed into a second one. It adds the
item's provenance and a dated copy of the text the item came from, in front of the six
sections above. Before launch, confirm its commit stamp and re-check every fact it dates.

## Sizing the pass against its context

A pass runs out of context long after it runs out of items. Across 96 recorded passes here the
median peak prompt was 190,402 tokens and the p90 was 293,276, against a window of 1,000,000.
Four of the 96 compacted, all under an earlier and smaller window. The largest recorded pass
reached 689,268 tokens over four work packages and 357 tool calls, and never compacted.

**Two limits apply and the lower binds.** 60% of the window, and an absolute cap of 250,000
tokens for a pass that writes source or 150,000 for one that only reads. On a one-million-token
model the cap binds; on a 262,000-token model the 60% figure does, at 157,000.

The cap is a cost rule. A turn taken at 600,000 tokens of carried context costs about 6.8 times
the same turn taken below 100,000, measured over 20,405 turns, because every turn re-sends the
whole prompt.

**Give the pass the budget in tool calls, because it cannot see its own context.** At the p90
growth rate of 2,603 tokens per call, 250,000 is 96 calls and 150,000 is 58. A typical
implementation pass spends 152, so **the median implementation pass hands over about once**.
Plan for that rather than discovering it.

**When the cap and the merge rule disagree, the plan stays merged and the context splits.** One
pass owns the whole job and restarts with a written handover carrying the rule it derived. Losing
that rule is what the merge rule exists to prevent, and a handover keeps it for about 19,000
tokens, which is the measured median first-turn prompt.

**If two passes fit inside one context and one check settles both, they are one pass.**

These figures are pinned in `.agents/skills/planning-work/reference/estimating.md`. Plan against
them as they stand, and leave re-deriving them to a person who asks for it.

## A worktree does not isolate a pass here

Every check in this repository runs `docker exec` against a named container with the repository
bind-mounted at `/app`. A git worktree lives at a different path on the host, and that path is
not mounted into any container. **A pass working in a worktree therefore has no type check, no
unit tests, no frontend check and no stack verification**, and it would report success against
commands that never saw its code.

This is the difference between this repository and the ones that external skills assume. There,
worktree isolation is free because the toolchain runs on the host.

The isolation that is available instead is the one already in force: **one pass in the main tree
at a time, on its own branch, waited on, and its diff read before the next pass starts.** Accept
a branch by squashing it into the working branch under one lowercase line, so the executor's
intermediate messages do not reach the log. Read the diff with `git diff main...<branch>` rather
than checking out the base, because whatever branch is checked out is what the containers serve,
and switching invalidates every check the pass just ran.

**Run no git write command while a pass is live.** One tree means one index. The archive records
this failing once: a push during a live pass interleaved commits and sent unreviewed work to the
remote.

## Resolving a conflict

The one shape this tree produces is the working branch moving under a live pass. Before
touching a hunk, read the intent of both sides, because intent is the input the model
otherwise lacks.

**Resolve what the intent settles. Stop and ask on what it does not.** The best models
measured on 7,938 real conflict hunks resolve under 60% correctly, and a preserved conflict is
worth more than a confident wrong merge.

Then run the checks the change owes. `writing-tests`'s `scripts/gate-map.sh` names them.

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

- `reference/work-package-template.md`, the skeleton, and the sections that are always got
  wrong.
