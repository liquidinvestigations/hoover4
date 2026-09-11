# Estimating a plan

A plan says how big the work is. This is how that number is arrived at, in units that the
report which follows can contradict.

**Every row here was measured in this repository on 2026-09-11**, over 185 recorded
sub-agent passes and the 85 sessions that ran them, across four harnesses. Each row names
its sample count. Three rows are marked thin and one row is marked as classified by a rule
this file replaced.

**Read no percentile from a row of fewer than ten samples as a measurement.**

Every final report that restates a forecast with actuals beside it moves a row. That column
is the mechanism by which these numbers improve.

## The one rule everything else serves

**Estimate in passes, never in developer days.** A pass is one sub-agent invocation. A
developer day is a unit nothing here has ever been measured in, and a duration that cannot
be falsified by the report that follows it is not an estimate. It is decoration.

**A task is not a pass.** A task is one thing that carries its own verification cycle. A
pass is one sub-agent invocation, and it holds about three tasks. An estimate that gives
every task a pass of its own pays the fixed cost of a pass once for each task instead of
once for each context. Section 1c is the arithmetic and section 1d is how such a pass is
written.

Measured here, **nine tasks cost 1,319 tool calls as nine passes and 639 as three.**

The failure this prevents has already happened. Twenty-one plan headings carried a
parenthetical day-cost, and not one was ever checked against an outcome, because every
report that followed them was written in a different unit. The estimates could not improve,
and each new plan was written by someone reading the last plan's *estimates* rather than the
last plan's *outcomes*.

## Two accounts, kept apart

Every figure below belongs to one of two accounts. Mixing them produces a budget that is
wrong and a pass count that looks fine.

| account | what it holds | what it decides |
|---|---|---|
| **the pass's own** | its fixed cost of 29 calls, then its tasks | its context cap and its tool-call budget |
| **the plan's** | the pass's own, plus 38 coordinator calls and $9.00 a pass | the pass count and the money |

**A pass starts with a fresh context.** The calls its coordinator spends writing the package
and reading the diff are spent somewhere the pass never sees, so they never enter its budget.
They are paid again for every pass, which is what packing removes.

## The method

Take the **outside view** first: put the work in a class of comparable past work and read the
distribution. Do not reason forward from its parts. That is the inside view, and it is where
optimism lives. Reasoning about what the tasks *are* is still judgement. How long each takes
is arithmetic.

Then compute both, and reconcile them. If the two disagree by more than about two-fold, one
of them is wrong and finding out which is worth ten minutes.

### 1. Decompose into tasks

One task is one thing that **carries its own verification cycle**. Write the tasks out. For
each, write the command whose output settles whether it worked. If a task's check is "and
then also check", it is two tasks. If two tasks share one check and neither is verifiable
alone, they are one task.

A task is not a scope item. **A scope item is what a person asked for, and a task is what one
check settles.** Several scope items often sit under one check, and one scope item sometimes
needs two.

### 1b. Merge the tasks that share one instrument

Step 1 counts checks. A corpus sliced by directory has one check per directory, so step 1
will produce as many tasks as there are directories and every one of them will pass its own
test.

Put the tasks through three questions before costing anything.

1. **Do they share one procedure?** The same rule, the same script, the same shape of edit.
2. **Does one command settle all of them at once?**
3. **Does their union fit the context budget in step 2b?**

Three yes answers means one task. Any no means they stay two tasks, and section 1c may still
put them in one pass. Measured, ten directory-sliced items forecast at 361 minutes at p50
were delivered by one pass in 62 minutes, and that pass then absorbed three more items the
plan never had.

**A directory is not a task, and neither is a file type.** Both are orderings inside a pass.

**Homogeneous work gets an instrument rather than a sweep.** A pass that derives the rule
once, writes the script that applies it, and writes the verifier that proves the change
stayed inside its scope will change hundreds of files with tens of tool calls. The pass
measured above changed 515 files using 27 Edit and Write calls out of 357 tool calls. Ten
passes over the same corpus would have derived the rule ten times and discarded the reading
that produced it nine times. Say so in the work package, because a pass that assumes
per-file editing will run out of attention before it runs out of files.

### 1c. Pack the tasks into passes

Section 1b merges tasks that are really one task. This step is different: it puts tasks that
stay separate into one pass, because a pass costs more than the work it carries.

**A pass has a fixed cost and a marginal cost.** The fixed cost is reading the package,
orienting in the tree and writing the report. The marginal cost is one task.

| part | value | n | how it was measured |
|---|---:|---:|---|
| the whole recorded implementation pass | 109 calls | 167 | recorded, and it carried about one task |
| prologue, calls before the first code write | 16 | 167 | recorded |
| epilogue, calls after the last code write | 8 | 167 | recorded |
| **the pass's own fixed cost** | **29** | 167 | the median of prologue plus epilogue |
| **the first task** | **80** | 167 | 109 less 29 |
| a second task in the same context | 45 | | 0.41 of a whole first pass |
| a third and any later task | 22 | | 0.20 of a whole first pass |
| **the coordinator, per pass** | **38 calls, $9.00, 50 min** | 24 | session calls over passes launched |

**The prologue and the epilogue are measured against code writes**, because a pass's own
report is a prose write. Counting every write puts the report inside the work and leaves an
epilogue of one call, which measures the deliverable rather than the reporting.

**The marginal figure of 80 is the cost of the FIRST task**, which pays to read the tree. The
discount a later task gets from a warm context cannot be measured here, because no recorded
pass carried more than about one task. The 0.41 and 0.20 are a ratio from a corpus that did
measure it, where one agent took four work packages into one context and spent 62 minutes on
the first and 25.6, 12.5 and 12.3 on the rest. **A ratio is the only thing a borrowed corpus
lends**, and it is applied to this repository's own call count.

**What one pass holds:**

| tasks | in-pass calls | under the 183 target | plan calls | work fraction | forecast peak context |
|---:|---:|---|---:|---:|---:|
| 1 | 109 | yes | 147 | 55% | 189,450 |
| 2 | 154 | yes | 191 | 65% | 255,980 |
| **3, the default** | **175** | **yes** | **213** | **69%** | **288,435** |
| 4 | 197 | no | 235 | 72% | 320,889 |

**The efficiency floor is 60 percent of a plan's calls spent on work.** A one-task pass
comes out at 55 percent and fails it. A two-task pass reaches 65 and passes. The floor sits
between them deliberately, because a one-task pass is the shape this section exists to
refuse.

**The floor is read on the plan's account.** On the pass's own account a one-task pass
already spends 73 percent of its calls on work, so a floor read there would refuse nothing.
What makes a one-task plan expensive is the 38 coordinator calls it pays again for every
pass.

**Three tasks is the default and the ceiling.** It is the largest count whose in-pass calls
stay under the packing target of 183. Four tasks is 197 calls and a forecast peak of 320,889
tokens, so a four-task pass names the task it hands over on reaching the budget.

**Put the work fraction in the estimate table** so a thin pass is visible before it runs
rather than in the actuals afterwards.

**It is best effort, and a pass short of work says so.** When the work does not exist, a
thinner pass is correct, and it carries one line naming what stopped it filling. What this
refuses is a thin pass nobody noticed. **A pass may open with a review of earlier work and
continue into related development**, which is how two half-empty passes become one: the
reading the review already paid for is what the development would otherwise pay again. Such
a pass never reviews its own work, because a reader who is also the author is not a second
reader, and its package names the review and the development as separate tasks with a check
on each.

**The pass count follows from the arithmetic.** Sum the tasks, pack them three to a pass, and
take the smallest pass count whose passes all sit under the target. The task count decides
nothing on its own.

### 1d. How a packed pass is written

**Five tasks in one package has been measured to deliver one task.** A brief listing five
items delivered one, a brief listing six delivered one, and the only brief delivered whole
had three items in one dependency chain. That is the failure this section has to avoid.
Packing survives it. One agent took four work packages into one context and delivered all
four, because it did not have to read the corpus again.

The difference is in the package.

- **The tasks are an ordered list, and each one names the command that settles it.** A list
  with no check per line is the brief that delivered one item of five.
- **The pass runs them in order and reports after each.** It does not read for all of them
  first.
- **The package says which task is the last one that must be delivered.** A pass that reaches
  the budget stops and hands over, and the plan needs to know which tail is at risk.
- **A pass that stops with tasks unreached has reported the scope, not failed.** Ask what it
  did not reach, never how long it took.

### 2. Bucket each task

The bucket sets the cost, **not the task's apparent difficulty**. That refusal to look at the
work is the whole of the outside view.

**Every row below is a whole pass that carried about one task**, because that is what the
recorded passes did. A row is therefore the fixed cost plus one task, and section 1c splits
it into the two parts. Cost a packed pass from the parts, and cost a single-task pass from
the row.

| bucket | min p50 | min p90 | calls p50 | calls p90 | ctx p50 | ctx p90 | n |
|---|---:|---:|---:|---:|---:|---:|---:|
| **implementation** | 23 | 93 | 109 | 287 | 185,042 | 288,230 | 167 |
| **operational** | 12 | 19 | 83 | 175 | 155,467 | 184,370 | 6, thin |
| **read-only review** | 4 | 671 | 45 | 405 | 71,838 | 127,976 | 10, thin |
| **documentation** | 20 | 20 | 108 | 108 | 170,935 | 170,935 | 2, thin |
| deploy / remote | 72 | 184 | 117 | | | | 8, by description |

Minutes are sub-agent wall clock, being the first to the last timestamp inside the pass's
own transcript. Context is peak prompt tokens, being
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens` on the largest
assistant turn.

**The pooled table spans four harnesses whose tool calls are not one unit.** The median
implementation pass is 109 calls pooled, and 107 in Claude Code, 41 in Codex and 200 in
Cursor, because Cursor issues one read a file where Codex routes a whole shell pipeline
through one `exec` call. A budget read from this table is generous for Cursor and tight for
Codex. Pooling was chosen so that one pack of numbers stands for the repository.

**The 671-minute p90 of the review row is a conversation left open**, not a pass that ran for
eleven hours. Cursor's wall clock is the span of a conversation and includes the time nobody
was at the keyboard. Read that row's call counts and ignore its minutes.

**The deploy row is classified by description**, which is the rule section 2 replaces, and it
is carried because this repository really does deploy to another host and the size matters.
Under the production rule a deploy pass that edits a file is an implementation pass.

#### How a pass is bucketed

By what it produced, and never by what it was called. The rule matters more than the table,
because the classifier decides which row a pass falls in.

1. **A file written by a Bash redirect, a heredoc, `sed -i` or `apply_patch` counts as a
   write.** Counting only the Edit and Write tool calls loses about half the writes recorded
   here.
2. **It wrote a code file**, meaning any file that is not `.md`, `.txt` or `.csv`:
   implementation.
3. **It wrote no code file, and three or more of its shell calls drove Docker, a server, a
   sweep or a generator**, and those are a tenth or more of its shell calls: operational.
4. **It wrote no file at all**: read-only review.
5. **It wrote only prose**: documentation.

**The description is never read.** A documentation pass that made sixty source edits is an
implementation pass, and the rule buckets it that way.

**The rule files a reviewer that wrote its report under documentation**, because the rule
reads what was produced. The agent type is the better classifier for a review, and the
`reviewer` agent's three recorded passes spent 40 calls at the median. That is three samples
and it carries no percentile. Cost a review from the read-only budget of 101 calls instead.

**A demonstration is not a browser pass.** Anything that restarts a container, waits on it
and repeats is operational however its deliverable reads.

### 2b. Check the pass against the context budget

The bucket sets the duration. The context window sets how much one pass can hold, and it is
the number that decides how many tasks one pass carries.

| measure | value | n |
|---|---:|---:|
| prompt growth per tool call, p50 | 1,489 | 150 |
| prompt growth per tool call, p75 | 1,999 | 150 |
| prompt growth per tool call, p90 | 2,490 | 150 |
| prompt growth per tool call, max | 7,006 | 150 |
| first-turn prompt, p50 | 27,179 | 150 |
| peak prompt of the median implementation pass | 185,042 | 167 |
| peak prompt of the p90 implementation pass | 288,230 | 167 |
| largest pass recorded | 732,644 | 185 |
| passes that compacted at all | 8 of 150 | 150 |

**The growth rate is the one measure known to transfer between repositories**, at 1,489 here
against 1,702 and 1,574 measured elsewhere. Duration, tool calls and cost do not.

**Growth per call varies by a factor of five across passes.** The median is 1,489 and one
pass grew at 7,006. That decides what a tool-call budget can and cannot do, in 2c.

**Two caps apply, and the lower one that fits the pass binds.**

| limit | value | what it is |
|---|---:|---|
| a pass that writes source or drives the stack | 300,000 | cost, and a quality aim |
| a pass that only reads | 150,000 | cost, and a quality aim |

**The writing cap was raised from 250,000 on 2026-09-11**, because the p90 pass measured here
already peaks at 288,230 and eight of 150 passes compacted. The old figure was below what the
corpus already did, so it refused nothing and it made every plan forecast a handover.

**The quality aim.** Sixty percent of a window is the conservative reading of the long-context
literature, where multi-hop retrieval accuracy falls off between 50% and 65% of an advertised
window, and the same literature puts degradation onset at an absolute count of 32,000 to
100,000 rather than at a fraction. On a one-million-token model the 60% figure is 600,000, so
the cap of 300,000 binds first.

**Nothing here has observed the effect that aim guards against.** The largest pass recorded
reached 732,644 tokens, produced a 515-file change and survived review.

### 2c. Convert the cap into tool calls, because a token budget cannot be checked

**An agent cannot see its own context.** Where a harness supplies a live token warning it
fires against the window, not against a budget a plan chose. An agent's sense of its own
context is the same kind of feeling as its sense of its own elapsed time, and that one is
wrong by a factor of two in both directions.

An agent **can** count its own tool calls. At the measured rates, a cap converts like this.

| cap | calls at the p50 rate of 1,489 | calls at the p90 rate of 2,490 | the budget in force |
|---:|---:|---:|---:|
| 150,000 | 101 | 60 | **101** |
| 300,000 | 202 | 120 | **202** |

**The budget in force is the cap at the measured p50 rate**, being 202 for a pass that writes
and 101 for a pass that only reads.

**The budget is not the packing target.** The table above ignores the first-turn prompt of
27,179 tokens. Counting it moves the two figures to **183 calls and 83**, which is what a
plan packs to. The difference is the slack a pass spends when one task runs long. Plan to the
target and state the budget.

**A tool-call budget cannot enforce the token cap it comes from.** Growth per call varies by a
factor of five. The budget is a reminder of size, and `.agents/hooks/warn-tool-call-budget.py`
puts it back in front of the pass at 80% and again at 95%. The cap itself is checked by
nothing.

**An agent counts its own tool calls correctly.** Three passes stated their own count and all
three were accurate to within one. That is why a call budget works where a clock does not.

**Say in the work package when a pass will write a long deliverable through the shell**,
because that costs calls the budget does not allow for.

These figures are pinned. Read "The tables are pinned" at the end of this file before changing
any of them.

### 3. There is no general verification adder

**Every bucket figure is measured from passes that ran their own checks inside their own wall
clock.** A verification cost added on top counts those minutes twice.

This was a defect in the previous version of this file, and it was carried into every
estimate in the archive. A bucket percentile already contains the stack verification, the
browser walk and the type check that the sampled passes ran, so adding them again made the
median column behave like a ninetieth percentile. One plan added 10 minutes a pass and its
forecast came out 2.85 times high on the passes it named. A sprint that came in at 64% of its
forecast is the same observation from the other side.

Two costs stay additive, because they are paid outside a pass.

| check | cost | where it is paid |
|---|---:|---|
| the prose and tag checkers, whole tree | < 1 min | inside the bucket, a pass runs them itself |
| a type check, a unit suite, a browser walk | measured in the bucket | inside the bucket, never added |
| a container or image rebuild | about 7 min cold | additive, and paid once per pass, not once per task |
| a full stack reset and reindex | measured separately when a plan needs one | additive |

**A full stack reset in a task is an adder larger than the bucket. That arithmetic says the
task is really two.**

Count rebuilds separately: two tasks needing the same rebuild pay for it once *if they are in
the same pass* and twice if they are not. This is the only place batching genuinely saves
time.

### 4. Sum, raise the pass count, and add the coordinator

**A packed pass is costed from its call count**, because the bucket row is a pass that carried
one task and a packed pass carries three. Four pinned conversions do it.

| from calls to | conversion | how it checks out |
|---|---|---|
| minutes at p50 | 12.4 seconds a call | 109 calls gives 23 minutes against the pinned 23 |
| minutes at p90 | p50 times 4.0 | the ratio the implementation row carries, at 23 and 93 |
| dollars | $0.120 a call pooled, $0.140 at the workhorse tier | the two rows of the cost table below |
| peak tokens | `27,179 + 1,489 x calls` | 109 calls gives 189,450 against the pinned 185,042 |

**Tool calls do not predict wall clock here**, at a correlation of 0.26 against the 0.92 that
another corpus reports. A pass that waits on a container rebuild or a dataset run spends
minutes without spending calls, and this repository runs many of those. **Convert calls to
minutes only for a pass that does not wait on the stack**, and cost a pass that does from the
operational or deploy row instead.

The p50 total is the sum of the pass rows and the p90 total the same. **Report both, never a
single figure.** The distribution is long-tailed and a mean is a commitment nobody can keep.

**Multiply the forecast pass count by 1.2.** Three plans here forecast 7, 16 and 0 passes and
ran 9, 19 and 5. The three causes are the same every time: a pass that answers a review's
findings, a pass found once the work starts, and the passes that produced the plan itself.
**A plan carries a correction-pass row for every review pass it plans.** A packed plan has a
fourth cause, being a pass that reaches its budget with a task unreached and hands over.

**Session wall clock is about 50 minutes of session span a pass**, over the 24 sessions that
launched one. Span is the first to the last timestamp of the session file, so a person can
check it against a clock without deciding what counts as waiting.

**A plan's cost line is the bucket cost plus $9.00 a pass of coordinator cost.** Measured over
the same 24 sessions. Across the whole recorded corpus the sessions cost $4,546.60 and the
passes they launched cost $2,828.82, and **61 of 85 sessions launched no pass at all**, so the
coordinator is where the money is and where nothing looks.

### 5. Name the tier, because the model moves the money by fifty times

Duration and tool calls barely move with the model. Price moves by a factor of fifty. A plan
that states one money figure has stated the model it assumed, whether or not it says so.

| tier | models | against the workhorse tier |
|---|---|---:|
| frontier | `gpt-6-astra`, `claude-fable-5-1` | 2.00x, 1.03x |
| **workhorse** | `claude-opus-5`, `gpt-5.6-sol` | **1.00x**, 0.80x |
| value | `grok-4.6`, `kimi-code/k3`, `gpt-5.6-terra`, `claude-sonnet-5` | 0.76x to 0.40x |
| cheap | `kimi-code/k2.7-code`, `claude-haiku-4-5`, `gpt-5.6-luna` | 0.30x to 0.04x |

The multipliers come from repricing the token counts of all 141 priced implementation passes
at each model's list rate, so the work is identical in every row and the spread is the price
of the model and nothing else.

| model | dollars a tool call | n |
|---|---:|---:|
| `claude-opus-5` | $0.140 | 80 |
| `claude-sonnet-5` | $0.061 | 55 |
| `gpt-5.6-sol` | $0.509 | 7 |
| `gpt-5.6-terra` | $0.232 | 6 |
| pooled, implementation | $0.120 | 141 |

**A plan names its tier. A plan that names none has named the workhorse tier.** The final
report records the tier that actually ran.

**These are list API rates and the work here runs on subscriptions.** They are the only
per-model figure comparable across providers, which is what an estimate needs. **They are also
a floor for a large pass**, because OpenAI charges twice the input rate above 272,000 tokens
and xAI charges more above 200,000, and the p90 pass here peaks at 288,230.

## The block every plan carries

```markdown
## Estimate

**Tier:** workhorse. **Method:** reference class,
`.agents/skills/planning-work/reference/estimating.md`.

**The tasks.** One row a task, costed at its marginal call count: 80 for the first in a
pass, 45 for the second, 22 for each later one.

| # | task | scope items | calls |
|---|---|---|---:|
| `W1.1` | <the task> | <the scope items it lands> | 80 |
| | **total marginal** | | **N** |

**The passes.** One row a pass, at 29 calls of its own fixed cost plus the tasks it carries,
and 38 coordinator calls on top.

| # | pass | tasks | bucket | in-pass | plan | work | min p50 | min p90 | cost |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| `W1` | <the pass> | `W1.1`-`W1.3` | implementation | 175 | 213 | 69% | 36 | 145 | $33.50 |
| | **totals** | | | **N** | **N** | | **min p50** | **min p90** | **$** |

The work column is marginal calls over plan calls. **It is at least 60% on every row**, or
that row carries the line saying what stopped it filling.

**Passes:** N tasks packed into P passes against the target of 183 in-pass calls, plus the
reviews and the corrections. Then that count times 1.2, which is the measured rate at which a
plan here discovers passes it did not have.
**Why P and not fewer:** the packing arithmetic, then one line per pass that came out under
the target saying what stopped it filling.
**Context:** forecast peak prompt of the largest pass at `27,179 + 1,489 x calls`, against the
cap of 300,000, and say whether the pass is expected to grow at the median rate or faster.
**Tool-call budget:** 202 for a pass that writes, 101 for one that only reads.
**Agent wall clock:** the p50 to the p90 minutes, and say which passes wait on the stack, because
calls do not convert to minutes for those.
**Session wall clock:** 50 minutes of session span a pass.
**Cost:** $0.140 a call at the workhorse tier, $0.052 for a pass that only reads, plus $9.00
a pass of coordinator cost.
```

**The final report restates every column with an actual beside it, read from the transcript.**
A pass cannot read its own clock, its own context or its own cost, and every actuals column
written from inside a pass has held tool calls alone for that reason.
`reference/pass-actuals.py` prints all four, and the organizer runs it after a pass reports.

## Three things the numbers will not tell you

**An agent cannot measure its own elapsed time, and always overestimates it.** Passes
reporting they had "roughly doubled" a one-hour box had used twenty-four minutes of it. One
reporting a "2.5x overrun" had used forty-seven. **A self-timebox is a budget of effort and
attention, not a clock.** Ask a pass what it did not reach, never how long it took. Wall clock
comes from outside the agent.

**Duration is not success.** These are durations of passes that ran, not of passes that
worked. A pass that spends forty minutes shipping a defect is indistinguishable here from one
that spends forty minutes shipping a feature. Gates are what separate them and they are
measured nowhere.

**The pass count is where the large errors live.** A duration table can only be wrong by the
width of its bucket. A pass count can be wrong by a factor. Sixteen genuinely different items
were forecast at 1,105 minutes and took about 707, an error of 1.6x that lived in the per-pass
cost. Ten same-shape items were forecast at 361 minutes and took 62, an error of 5.8x that
lived entirely in the count. **The final report records the forecast pass count against the
actual pass count**, in the same table as the durations.

**A pass count is also wrong when every pass in it is half empty.** A plan whose rows all
carry one task has costed the fixed part of a pass once for each task. Section 1c is the
check.

## The tables are pinned

These are recorded measurements from **this repository, four harnesses, and the models listed
in section 5**. That parochialism is deliberate.

**The transfer was measured elsewhere and it does not hold.** Of twelve class-and-measure
comparisons between two repositories on the same machine and the same harness, not one
median fell inside the other's p50 to p90 band. **The two rate measures do transfer**, being
growth per tool call at 1,489 here against 1,702 and 1,439 elsewhere, and seconds a tool call
at 12.4 against 13.6 and 11.5. Converting a context cap into a call budget, and calls into
seconds, is the whole of what a borrowed reference class is good for.

**Do not regenerate them while planning work.** A pass that re-derives its own reference class
reads whatever history sits on the machine it is running on. A developer using a different
editor or a fresh checkout has a thin history or none, and a thin sample prints percentiles
that look exactly like a measurement. Plan against the numbers as they stand.

**Moving a table is a decision a person makes and asks for.** When that is asked, these
scripts print a distribution and change no file.

```
reference/mine-harnesses.py  --out passes.jsonl   # reads all four harnesses
reference/mine-report.py     passes.jsonl         # the distributions
reference/mine-cost.py       passes.jsonl         # the money, at list prices
reference/mine-derive.py     passes.jsonl         # every pinned figure, with its arithmetic
reference/prices.py                               # the price table and what it omits
```

`mine-derive.py` prints the arithmetic beside each figure, so a pinned number can be checked
without being re-derived. Replacing a pinned table means editing this file by hand, keeping
the sample count beside each row, and saying in the plan that the reference class moved.

`reference/pass-actuals.py` is the one that runs after every pass rather than only when a
table moves. It reads one pass's transcript and prints its wall clock, tool calls, peak
context and cost. A pass cannot run it on itself.

**Do not copy these tables into a `Readme.md`, into `docs/`, or into `AGENTS.md`.** They are
a measurement with a half-life, and a tracked file states what is true now.
