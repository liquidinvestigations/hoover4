---
name: planning-work
description: Sets up and runs a multi-stage piece of work the way this repository does it. A numbered work folder, the request captured verbatim, a research stage, a plan, then paired prompt and report files per pass, a coordinator log, and a final report. Use when asked to "write a plan", "plan this out", "scope it", "spec this", "start an epic", "investigate before building", "write a work package", "archive this", or when a task is large enough that one pass cannot finish it. Covers how a stage is sized, what a prompt file must contain, why artefacts fan out into a folder beside the document, and the rule that nothing in the tracked tree may ever cite the scratch folder.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Planning work

Work larger than one sitting is run as a folder of documents, not as a conversation. The
folder is the memory: a later pass reads it instead of re-deriving what was already decided.

## Where it lives, and the one hard rule about it

Working documents go in `plans/<n>-<slug>/` at the repo root. **`plans/` is gitignored
scratch and is wiped when the work finishes.** Everything follows from that:

- **No tracked file may ever cite it**, not by path, not by document number, not by a phase
  or part label invented inside it, not by paraphrase (`the design doc`, `the epic`,
  `the part-6 spike`). Every such reference is a dead link the moment it is written.
- Knowledge that must survive the wipe is **lifted** into the `Readme.md` beside the code, or
  into `docs/`, as a present-tense statement about how the system works. Do that as the work
  lands, not afterwards. Afterwards never comes.
- Archive a finished folder by moving it under `plans/old/<DDMMYYYY>/`. **Never delete one**:
  `plans/` is gitignored, so an archived folder exists only on this disk.
- Two standing files sit at the top of `plans/` and outlive every folder: **`TODO.md`** for
  work that was wanted and not built, and **`DEFECTS.md`** for defects and limitations awaiting
  re-verification before they move into `docs/development/`. A pass ends by appending to them.
  Without somewhere for unbuilt intent and open defects to go, a folder can never be archived.

## The file sequence

Numbered so the reading order is the order they were written.

| file | holds |
|---|---|
| `0-prompt.md` | the request **verbatim**, unedited. It is the only record of what was actually asked |
| `1-research-report.md` | what is true today: the code as it is, measured, with file paths |
| `2-questions.md` | the frontier, asked in one round, with a recommended answer each |
| `3-scope-and-cuts.md` | what lands, what does not, and the reason for each cut |
| `N-prompt-NN-<pass>.md` | the work package for one pass |
| `N-report-NN-<pass>.md` | that pass's report, written by whoever ran it |
| `N-coordinator-log.md` | decisions taken mid-flight, in the order they were taken |
| `N-final-report.md` | what landed, what did not, and what the next session needs |

Prompt and report are **paired and adjacent**: a prompt with no report beside it is a pass
that did not finish, and that is visible at a glance from the directory listing.

## Short tags, and the `## Key` table

A scope table and a results table only line up if the items have short names, so
letter-and-number tags (`M3`, `S13`, `X7`, `Q1`) are the right tool **inside one plan
folder** and nowhere else. Measured across this repository's plans, a quarter of tag
citations could not be resolved in the document that made them, and more than half the tags
meant two different things in two different files. That is what the rules below prevent.

- **A tag never leaves the folder that defined it.** Referring to another pass's item means
  **naming it and linking to it**. The same three characters are a scope item in one folder
  and a defect in another, and nothing in a bare citation says which.
- **A document that uses tags opens with a `## Key` table** (every tag it mentions, what it
  is, and a link to where it is defined), and expands each at its **first mention** in the
  body. After that the bare tag is fine, exactly as an acronym works.
- **If the document links into an earlier pass**, the Key table also decodes the tags a
  reader will meet on the other side of that link. A decoder that is not exhaustive for what
  the document links to is worse than none.
- **Worded references are tags.** "Phase 1", "Chapter 3", "Workstream A" index a structure
  the reader cannot see just as much as `X3` does. Same rule.
- **Never in a tracked file**, which includes `docs/`, `.agents/`, a `Readme.md` beside code,
  and **a source comment**. `plans/` is gitignored, so a tag cited from shipped code is
  unresolvable forever for anyone who clones the repository. State the fact instead, in
  practice the sentence beside the tag already says it.

```
.agents/check-doc-ids.py [path ...]     # names every unresolvable tag
```

Run it over the folder before calling a document finished. It is not wired into a hook: the
archived folders under `plans/old/` predate the rule and would fail it forever.

## The question round, between research and scope

**Ask the frontier in one round, before the scope is written.** The frontier is every decision
whose prerequisites are already settled, so it can be answered now. A question that depends on
another question's answer waits for the second round.

Measured across this repository's archive, five of seven plan folders carried a question section
written at the end of the work rather than the start, and two of those questions decided whether
finished work shipped. One of them asked whether to ship a known 3.4x regression, and it was
answerable on day one. A separate plan forecast ten passes for work that one pass did in 62
minutes, and the correction came from the user; **that was a frontier question the plan never
asked**, which is whether the ten items were the same shape.

- **Every question carries a recommended answer**, so the reader can agree in one word. A
  question with no recommendation is asking someone else to do the planning.
- **The round goes into `2-questions.md` and through `AskUserQuestion` as well.** A question
  written in a file nobody has been asked is not a question.
- **Write the questions out where you raise them.** Never name a count and leave the content
  elsewhere.
- **Record what was asked and what came back**, so the next round does not re-ask it.
- **Stop when the frontier is empty**, and say so.

**A scope change re-opens the round.** An item added to the plan, an item dropped, or an item
re-scoped, needs its own question before it reaches a work package. This holds in both
directions, so removing work is asked about in the same way as adding it. The answer goes into
the answers file, and from there into the plan document it changes. An item that the plan
describes as implementing a rule the tree already carries is still a scope change. A mechanism
that enforces a rule is a different thing from the rule, and it is the mechanism that takes the
condition away.

## Provenance, in every decision table

A decision table carries who decided each row and when. Without those two columns a reader
cannot tell an answer a person gave from a recommendation the plan wrote, and the second one
gets implemented as though it were the first.

| decision | answer | who and when | status |
|---|---|---|---|
| the cap binds the coordinator | yes, at 300,000 | person, round two, 2026-08-21 | in force |
| refuse `git push` | none | nobody, proposed by the agent | withdrawn 2026-08-23 |

- **Three status values are enough**, being `in force`, `superseded by <link>`, and
  `withdrawn`. A row is never deleted, because a deleted row lets the same decision be taken
  twice.
- **A row with `nobody` in the who column may not reach a work package.** It is a
  recommendation until a person answers it.
- **A claim of fact cites what produced it**, meaning the file, the command or the
  measurement. A claim about the environment is checked in the same pass that writes it.
- **Text the agent wrote is never a person's request.** A handoff, a report or a plan carries
  the agent's own words, and a person pasting one back is giving context rather than an
  instruction.

## Scope by churn before scanning

**Investigate against primary sources**, meaning official documentation, source code,
specifications and first-party interfaces, and follow every claim back to the source that
owns it.

**Read what has been changing before deciding where to look.** A tree is too large to scan and
the parts that keep moving are where the design questions are.

```
git log --since='6 weeks ago' --name-only --pretty=format: | sort | uniq -c | sort -rn | head -20
```

Applied here it found that the five most-edited files in the repository are configuration,
deployment and specification rather than application code, which is a finding no scan of the
source would have produced.

Churn is a pointer and not a verdict. A file that changes constantly may be the one file that
is supposed to.

## Fanning out artefacts

Complex work produces screenshots, extracted datasets, scratch scripts and test output as
well as prose. Those go in a folder **beside** the document that discusses them, named for it,
and the document links to them. This is the expected pattern, not an exception: a finding
whose evidence is only in a scrollback is a finding nobody can check.

## Sizing a stage

The unit is **the smallest piece of work that carries its own verification cycle and is
worth a fresh reviewer's attention.** Not a checkbox, and not a whole feature.

Two failure shapes to avoid:

- **A stage with no check of its own.** If nothing can be run at the end of it, it is half a
  stage, and its report will be a claim rather than evidence.
- **A stage that spans two verification cycles.** It will be reported as done when only the
  first is green.

**One item per pass.** Measured across this repository's own runs: a brief listing five items
delivered one, a brief listing six delivered one, and the only brief delivered whole had three
items in a strict dependency chain that one check closed. A brief with a list in it estimates one item
and reports the shortfall. It does not estimate the list.

**The rule is about different items and not about volume.** A brief listing five different
things with five different checks delivers one of them. A brief listing one rule applied across
ten directories is one item, and splitting it into ten passes has been measured to cost six
times the wall clock of doing it once. Before writing a plan with more than three passes, put
the items through the merge test in `reference/estimating.md` and write one line per split
saying what forced it. A split with no reason written beside it is a pass that should not exist.

## Deciding a shape

When the plan is choosing how something should be structured rather than what it should do,
**load `reviewing-changes` and apply its four shape tests at planning time**. They are written
for reading a diff and they work as well on a design, and the alternative is discovering at
review that the shape was decided without them.

## Estimating it

**Cost work in passes, never in developer days.** A pass is one sub-agent invocation, and its
cost comes from a measured reference class rather than from judgement about the task. Median
38 minutes for a pass that writes, 9 for one that only reads, 48 for one that touches another
host. A developer day is a unit nothing here has ever been measured in.

**A plan also carries a money figure and a tool-call budget.** The median implementation pass
costs about $22 and spends 152 tool calls, against a budget of 96 under the context cap, so the
median implementation pass hands over about once. Both numbers are in `reference/estimating.md`
and both belong in the estimate block.

**Get the pass count right before refining the per-pass cost.** An estimate that costs ten
passes accurately and needed one is wrong by ten, and every percentile in it is still correct.
The estimate block therefore carries the pass count, the reason for each split, and the forecast
peak context of the largest pass.

Every plan that schedules work carries an `## Estimate` table: one row per item with its
bucket, its verification cost, `T50`/`T90` in minutes and a forecast cost; then passes, the
tool-call budget, agent wall clock, and session wall clock, which is `T × 1.3` at eight passes
or more and `T × 3.3` below that. **The final report restates the same table with an actuals
column.**

That last column is what makes the next estimate better. Twenty-one plan headings in this repository's archive
carried a parenthetical day-cost and not one was ever checked, because every report that
followed was written in a different unit, so the estimates could not improve, and each new
plan was written from the last plan's estimates rather than its outcomes.

`reference/estimating.md` carries the method, the two pinned tables and the adders. Those
numbers are a recorded measurement from one harness, and a plan uses them as they stand.
Re-deriving them is a separate request from a person, and never a step inside a plan.

## What a prompt file must contain

A pass is only as good as its work package. Every one of these, or the pass reconstructs it
badly from context it does not have:

1. **Role and scope**. What this pass owns, and what it must not touch.
2. **What to read first**, by path, including the decisions that are already settled and are
   not to be re-opened.
3. **What is true now**, where the tree has moved since the research was written.
4. **The deliverable**, the exact output path and its required sections.
5. **The checks to run before finishing**, named as commands.
6. **The prohibitions**, including the standing ones that are easy to violate under pressure.

## Closing a stage

Before a stage is called finished:

- Every check named in its prompt has been run in that session and its output read:
  `verifying-before-claiming`.
- A capability that was added, removed or re-scoped has had its row in
  `docs/technical-specification/` edited **in the same patch** as the code.
- Documentation beside the changed code is true again: `writing-project-docs`.
- The report says plainly what was not done and why. A check that failed and was shipped
  anyway is stated as such; an honest gap is worth more than a clean-looking summary.
- **Everything the report needs from a person is written out where it is raised**, with a
  recommended answer, and repeated in full in whatever message hands the report over. Naming
  a count ("three open questions"), and leaving the content in the document means the
  question was never actually asked. The reader has to go looking to find out what they owe,
  and at that point the report is blocking on an answer nobody knows is wanted.

## References

- `reference/prompt-template.md`, the skeleton of a work package, with the sections above.
- `reference/estimating.md`, the reference class, the verification adders, and the estimate
  block every plan carries.
- `reference/mine-wall-clock.py` and `reference/mine-context.py`, which print the duration and
  the context distributions when a person asks for them. Neither runs as part of planning.
- `reference/archiving.md`, closing a folder, and what gets lifted into the tree before the
  scratch is wiped.
