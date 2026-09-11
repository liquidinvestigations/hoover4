---
name: planning-work
description: Sets up and runs a multi-stage piece of work the way this repository does it. A numbered work folder, the request captured verbatim, a research stage, a plan, then paired prompt and report files per pass, a coordinator log, and a final report. Use when asked to "write a plan", "plan this out", "scope it", "spec this", "start an epic", "investigate before building", "write a work package", "archive this", or when a task is large enough that one pass cannot finish it. Covers how a task is sized and packed into a pass, the tag scheme, what a prompt file must contain, why artefacts fan out into a folder beside the document, and the rule that nothing in the tracked tree may ever cite the scratch folder.
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
| `0-prompt.md` | the request **verbatim**, every image that came with it, and the reading the plan works from. `## What 0-prompt.md holds` below gives the three sections |
| `1-research-report.md` | what is true today: the code as it is, measured, with file paths |
| `2-questions.md` | the frontier, asked in one round, with a recommended answer each |
| `3-scope-and-cuts.md` | what lands, what does not, and the reason for each cut |
| `N-execution-and-checks.md` | the container commands, the commands the plan must create, the documentation rows each pass owns, and the report contract. Every pass document links it instead of restating it |
| `N-prompt-NN-<pass>.md` | the work package for one pass |
| `N-report-NN-<pass>.md` | that pass's report, written by whoever ran it |
| `N-coordinator-log.md` | decisions taken mid-flight, in the order they were taken |
| `N-final-report.md` | what landed, what did not, and what the next session needs |

**A plan of more than two passes carries the execution-and-checks document.** Every check in
this repository runs `docker exec` against a named container, and a package that restates
those invocations gets one of them wrong. Write them once, link them from every package, and
name there which commands exist today and which the plan has to create. A planned command
presented as an existing one is how a pass reports a check it never ran.

Prompt and report are **paired and adjacent**: a prompt with no report beside it is a pass
that did not finish, and that is visible at a glance from the directory listing.

**Two numbering conventions are legal.** The table above numbers by stage. A folder may
instead number by the order its documents were written, which gives `1-plan.md`,
`2-research.md`, `3-answers.md`, `4-organizer-log.md`, `5-scorecards/` and `6-final-report.md`,
with the passes in `1-plan/` beside the plan they belong to. Pick one per folder and keep it.
Two rules hold under either convention: the reading order is the number order, and a prompt
has its report beside it.

## What `0-prompt.md` holds

Three sections, in this order. The first two are a record and the third is a reading.

### 1. The request, unmodified

Every line of the request, quoted with `>`. No correction of spelling, no reordering, and no
summary. It is the only record of what was actually asked. An answer a person gave in a
question round is quoted the same way, under its own heading, because it is part of the
request.

### 2. The images the request attached

**An image that arrives with a request is written into the folder.** Put it under `images/`
beside the document, name it by the number the request gives it, and link every one from a
table that says what it shows. A request that draws on a screenshot is unreadable without the
screenshot, and a plan folder that cannot be read is a plan nobody checks.

**An image that cannot be recovered is named as missing.** An agent reads an attached image
and cannot write its bytes back out. Look for the file on disk first, by the screenshot
harness's own output directory and by modification time. Copy what is found. For each one
that is not found, write the row with the file name it will take and say plainly that a
person drops it in. **Do not paraphrase the picture in place of it**, because a description of
a drawing is a new drawing nobody checked.

### 3. What this plan understands the request to be

The reading the plan works from, so an operator can find a wrong reading before any work rests
on it. It goes at the bottom, after the quote, and it holds:

- **Every item the request names, unpacked**, in the vocabulary the code uses. One heading an
  item.
- **Every relative reference resolved to a path**, linked, so no reader has to guess which
  file a sentence is about.
- **An explainer note wherever the request names a skill, a page under `docs/`, an invariant
  or a named feature of the code.** Say which one, and say what it requires. A reading that
  silently breaks the one-configuration-file rule, or cites the scratch folder from a tracked
  file, is caught here or not at all.

Nothing in this section is a decision. It is what the words are taken to mean.

**When the request is genuinely ambiguous, write the follow-up questions before this section.**
Put them in their own `## Follow-up questions` section at the end of the file, one per real
choice, each saying what the two readings are and what turns on the difference. The research
stage answers what it can from the code. **Whatever research does not answer goes to a person
in the question round** and its answer becomes a numbered decision in `2-questions.md`. A
question written here and never asked is an assumption written into a deliverable, which the
invariants refuse.

## The pass document

**One document per pass, in a folder named for the plan**, such as `1-plan/pass-4-<slug>.md`.
That document is the work package: the executor is launched on it, and nothing is transcribed
into a second file. A plan whose passes live only as rows in an estimate table sends a
sub-agent out with a slug and a cost.

Each one carries, in this order:

1. **The address block.** Which agent this is, that this file is its prompt, the exact
   deliverable path, and the commit stamp the package was written against.
2. **The `## Key` table**, because the document uses short tags and has to
   decode them where it stands.
3. **The estimate table's header and this pass's row**, copied from the plan. One row is
   cheap and it means the reader never opens the plan to learn what the pass costs.
4. **The pass's tasks, as an ordered list**, each with the command that settles it and the
   order it runs in. A pass carries about three. A list with no check on a line is the brief
   shape that has been measured to deliver one task of five.
5. **Where each task came from**, as a table: every source, what it holds, and a link.
6. **Each task's item, copied, with the date of the copy.** Verbatim, including whatever
   register the source was written in. A quoted line keeps its exact wording.
7. **The technical design**, for a pass that changes code, a data format, an algorithm or
   runtime behaviour. `reference/technical-pass-design.md` says what it must carry: the files
   and symbols this pass owns, the interfaces with their types and units, the ordered steps of
   any algorithm, the state transitions, the migration behaviour, and the acceptance cases
   with an expected result that does not come from the implementation. A package that leaves
   the architecture to the executor gets a second architecture.
8. **The six package sections** from `running-consecutive-subagents`: read before you start,
   what lands, what is true now, what must not happen, before you finish, and the report.

**The report is written beside it** as `pass-N-report.md`, which keeps the pairing rule.

**Copy across the folder boundary, link inside it.** `TODO.md`, `DEFECTS.md` and anything under
`plans/old/` are rewritten on their own schedule and can be wiped, so a pass document copies
their text and dates the copy. Everything inside the plan folder is linked instead. The same
sentence in two files inside one folder is a defect waiting to happen, and the same sentence
copied out of a file that may not exist next week is the only way to keep it.

**An item with no entry in the standing files is the one that most needs copying.** Measured
in this repository: of eight items in one sprint, two came from a code reading and a churn
reading, and their only record was an archived folder. Those two are the items a plan loses.

## The tag scheme

A scope table and a results table only line up if the items have short names, so
letter-and-number tags are the right tool **inside one plan folder** and nowhere else.
**The letters are fixed**, because two plans that pick their own letters cannot be read
side by side, and because a plan that picks a letter the tree already owns discovers the
collision halfway through writing itself.

| tag | what it is | where it is defined |
|---|---|---|
| `W1`, `W2` | a **w**ork pass, numbered in execution order | the plan document |
| `W1.1`, `W1.2` | a **task** inside pass `W1`, numbered in the order it runs | the pass document |
| `G1` | a scope item, being a **g**oal the request asked for | `3-scope-and-cuts.md` |
| `C1` | a **c**ut, being scope deliberately not delivered | `3-scope-and-cuts.md` |
| `Q1` | a **q**uestion put to a person | `2-questions.md` |
| `D1` | a **d**ecision a person took | the answers file |

**Four letters are forbidden, because this tree already owns them.**

| forbidden | what the tree means by it |
|---|---|
| `P0` to `P7` | the **pipeline stages** in `main_services/processing/tasks/` |
| `S3` | the object store protocol, so the whole of `S` is unsafe for a scope item |
| `H1` to `H6` | heading levels |
| `E5` | the embedding model |

`.agents/check-doc-ids.py` carries the full list of tokens that look like a tag and are
domain vocabulary here, in its `NOT_TAGS` set. **Read that set before inventing a letter this
table does not give you.** A tag that appears there is silently excused by the checker, so a
scope item called `S3` is never checked for resolvability and is read by a person as the
object store.

A plan that needs a tag class this table does not have adds a row to the table in the same
patch, rather than inventing one for itself.

Measured across this repository's plans, a quarter of tag citations could not be resolved in
the document that made them, and more than half the tags meant two different things in two
different files. That is what the rules below prevent.

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
  the reader cannot see just as much as `W3` does. Same rule.
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
  written in a file nobody has been asked is not a question. Unless otherwise stated, for
  example an unattended pass, where nobody is available to answer and the question goes into
  `OPEN_QUESTIONS.md` beside the plan's `TODO.md`, with the choice taken and how to undo it.
  `running-unattended` carries that mode.
- **Write the questions out where you raise them.** Never name a count and leave the content
  elsewhere.
- **Record what was asked and what came back**, so the next round does not re-ask it.
- **An answer that creates a new decision goes into the round that is still open.** A choice
  the answer did not name, such as a rename's target word, is the next question rather than a
  judgement call.
- **The round is empty when the next document holds no value a person could have chosen.**
  Read the draft before you say so.
- **Stop when the frontier is empty**, and say so.

**A scope change re-opens the round**, unless otherwise stated, for example an unattended pass,
where the change is recorded in `OPEN_QUESTIONS.md` and stays provisional until a person reads
it. An item added to the plan, an item dropped, or an item
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

## Sizing a task, and filling a pass

A task is **the smallest piece of work that carries its own verification cycle and is worth a
fresh reviewer's attention.** A checkbox is smaller than that and a whole feature is larger. A
pass is one sub-agent invocation, and it carries several tasks.

Two failure shapes to avoid:

- **A task with no check of its own.** If nothing can be run at the end of it, it is half a
  task, and its report will be a claim rather than evidence.
- **A task that spans two verification cycles.** It will be reported as done when only the
  first is green.

**One check per task, and three tasks per pass.** Measured in this repository: a pass spends
29 tool calls on being a pass before it does any work, its first task costs 80, and a later
task in the same context costs 45 and then 22. Three tasks is 175 calls, inside the packing
target of 183. `reference/estimating.md`, section 1c, carries the arithmetic and the sample
count behind every figure.

**Every pass also costs its coordinator 38 tool calls and $9.00 before it runs**, spent
writing the package and reading the diff. That cost is paid again for every pass and it never
enters the pass's own budget, because a pass starts with a fresh context. It is what packing
removes. **Nine tasks cost 1,319 tool calls as nine passes and 639 as three.**

**The efficiency floor is 60 percent of a plan's calls spent on work**, being the marginal
calls over the pass's calls plus its coordinator's. A one-task pass comes out at 55 percent
and fails it. A two-task pass reaches 65 and passes. **Put the fraction in the estimate
table** so a thin pass is visible before it runs rather than in the actuals afterwards.

**Three tasks is the ceiling too, unless the package names a tail.** Four tasks is 197 calls,
past the packing target of 183, so a four-task pass says which task it hands over on reaching
the budget.

**It is best effort, and a pass short of work says so.** When the work does not exist, a
thinner pass is correct, and it carries one line naming what stopped it filling. What this
refuses is a thin pass nobody noticed. **A pass may open with a review of earlier work and
continue into related development**, which is how two half-empty passes become one: the
reading the review already paid for is what the development would otherwise pay again. Such a
pass never reviews its own work, because a reader who is also the author is not a second
reader, and its package names the review and the development as separate tasks with a check on
each.

**A packed pass needs the tasks written as an ordered list with a check on each line.**
Measured: a brief listing five items delivered one, a brief listing six delivered one, and the
only brief delivered whole had three items in a strict dependency chain that one check closed.
Those briefs carried a list and no check per line.

**Volume inside one task is free.** A brief listing one rule applied across ten directories is
one task, and splitting it into ten passes has been measured to cost six times the wall clock
of doing it once. Put the tasks through the merge test in `reference/estimating.md` first, then
pack what survives.

## Deciding which service owns a computation

**Before a plan places any computation, name the service that owns its input.** A plan that
puts work in the wrong tier is found at deployment rather than at review, because each tier
has its own image, its own configuration and its own restart.

| question | if the answer is yes |
|---|---|
| does it read or write a document's bytes or its derived rows? | it belongs in the pipeline under `main_services/processing/` |
| does it need a GPU? | it belongs in `ai_services/`, and the CPU twin in `main_services/` mirrors its interface |
| does a person wait on it inside a request? | it belongs in the website, and anything slower than a request becomes a Temporal workflow |
| would two callers each compute a different answer? | they will drift, so compute it once upstream and store it |
| does it need a value that only `hoover4.ini` has? | it is generated into an env file, and never hand-edited there |

A computation placed in two tiers needs the mirrored-constant rule in `reviewing-changes`,
because nothing checks that the two copies agree.

## Deciding a shape

When the plan is choosing how something should be structured rather than what it should do,
**load `reviewing-changes` and apply its four shape tests at planning time**. They are written
for reading a diff and they work as well on a design, and the alternative is discovering at
review that the shape was decided without them.

## Estimating it

**Cost work in passes, never in developer days.** A pass is one sub-agent invocation, and its
cost comes from a measured reference class rather than from judgement about the task. The
reference class in `reference/estimating.md` was measured in this repository over 185 passes
across four harnesses. A developer day is a unit nothing here has ever been measured in.

**Cost the tasks, then pack them into passes.** The first task in a pass costs about 80 tool
calls, a second costs 45 and each later one 22, and a pass costs 29 before it does any work.
Three tasks is 175 calls against a packing target of 183. A plan whose passes all carry one
task has bought the fixed part of a pass once for every task.

**Check every pass against the efficiency floor before the plan is finished**, being 60
percent of a plan's calls spent on work. A plan that fails the floor on several passes is a
plan with too many passes in it, and merging them is what the floor is for.

**A plan also carries a money figure, a tier and a tool-call budget.** A call costs about
$0.120 at the workhorse tier, the coordinator adds $9.00 a pass, and the budget is 202 calls
for a pass that writes and 101 for one that only reads. **The tier is named**, because the
same work costs fifty times more on the dearest model than the cheapest while its duration and
its call count barely move.

**There is no verification adder.** Every bucket figure already contains the checks the
sampled passes ran, so adding a stack verification or a browser walk on top counts those
minutes twice. Only a container rebuild and a full stack reset stay additive, and a rebuild is
paid once per pass rather than once per task.

**Get the pass count right before refining the per-pass cost.** An estimate that costs ten
passes accurately and needed one is wrong by ten, and every percentile in it is still correct.
The estimate block therefore carries the pass count, the packing arithmetic behind it, and the
forecast peak context of the largest pass.

Every plan that schedules work carries an `## Estimate` block of two tables: one row per task
with its call count, then one row per pass with its bucket, its in-pass and plan call counts,
its work fraction, its p50 and p90 minutes and a forecast cost. Then passes, the tool-call
budget, agent wall clock, and session wall clock, which is 50 minutes of session span a pass.
**The final report restates both tables with an actuals column**, and
`reference/pass-actuals.py` reads the four quantities a pass cannot report about itself.

That last column is what makes the next estimate better. Twenty-one plan headings in this
repository's archive carried a parenthetical day-cost and not one was ever checked, because
every report that followed was written in a different unit, so the estimates could not
improve, and each new plan was written from the last plan's estimates rather than its
outcomes.

`reference/estimating.md` carries the method, the pinned tables and the two additive costs.
A plan uses those numbers as they stand. Re-deriving them is a separate request from a person,
and never a step inside a plan.

## What a prompt file must contain

**A technical pass carries an implementation design.** Read
[`reference/technical-pass-design.md`](reference/technical-pass-design.md) when a pass changes
code, a data format, an algorithm or runtime behaviour. Put the design in the pass document,
or in a document beside it inside the same plan folder, and link the exact section. A weaker
executor must have enough detail to implement the agreed design without repeating the
architecture research.

Ask architecture questions before writing the design they affect. Continue independent
research while the answers are pending. Record each answer and what it changes before writing
the packages that depend on it.

A pass is only as good as its work package. In a plan folder the prompt file is the pass
document above, so this list is what that document's six sections hold. Every one of these, or
the pass reconstructs it badly from context it does not have:

1. **Role and scope**. What this pass owns, and what it must not touch.
2. **What to read first**, by path, including the decisions that are already settled and are
   not to be re-opened.
3. **What is true now**, where the tree has moved since the research was written.
4. **The deliverable**, the exact output path and its required sections.
5. **The checks to run before finishing**, named as commands.
6. **The prohibitions**, including the standing ones that are commonly violated under pressure.

## Closing a pass

Before a pass is called finished:

- Every check named in its prompt has been run in that session and its output read:
  `verifying-before-claiming`.
- A capability that was added, removed or re-scoped has had its row in
  `docs/technical-specification/` edited **in the same patch** as the code.
- Documentation beside the changed code is true again: `writing-project-docs`.
- The report says plainly what was not done and why. A check that failed and was shipped
  anyway is stated as such; a named gap is worth more than a clean-looking summary.
- **Everything the report needs from a person is written out where it is raised**, with a
  recommended answer, and repeated in full in whatever message hands the report over. On an
  unattended run there is no such message, so the same content goes into `OPEN_QUESTIONS.md`
  as the work lands rather than at the end. Naming
  a count ("three open questions"), and leaving the content in the document means the
  question was never actually asked. The reader has to go looking to find out what they owe,
  and at that point the report is blocking on an answer nobody knows is wanted.

## References

- `reference/prompt-template.md`, the skeleton of a work package, with the sections above.
- `reference/estimating.md`, the reference class, the two additive costs, and the estimate
  block every plan carries.
- `reference/technical-pass-design.md`, what a package must carry when its pass changes code,
  a data format, an algorithm or runtime behaviour.
- `reference/mine-harnesses.py`, `reference/mine-report.py`, `reference/mine-cost.py` and
  `reference/mine-derive.py`, which read all four harnesses and print the distributions, the
  money and every pinned figure with its arithmetic. None of them runs as part of planning.
  `reference/prices.py` holds the list price of every model and the page each row came from.
- `reference/pass-actuals.py`, which prints one pass's wall clock, tool calls, peak context
  and cost from its transcript. The organizer runs it after a pass reports, to fill the
  actuals column. A pass cannot run it on itself.
- `reference/archiving.md`, closing a folder, and what gets lifted into the tree before the
  scratch is wiped.
