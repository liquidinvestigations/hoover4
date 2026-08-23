# Estimating a plan

A plan says how big the work is. This is how that number is arrived at, in units that the
report which follows can contradict.

## The one rule everything else serves

**Estimate in passes, never in developer days.** A pass is one sub-agent invocation. A
developer day is a unit nothing here has ever been measured in, and a duration that cannot be
falsified by the report that follows it is not an estimate. It is decoration.

The failure this prevents is specific and it has already happened: twenty-one plan headings
carried a parenthetical day-cost, and not one was ever checked against an outcome, because
every report that followed them was written in a different unit. The estimates could not
improve, and each new plan was written by someone reading the last plan's *estimates* rather
than the last plan's *outcomes*.

## The method

Take the **outside view** first: put the item in a class of comparable past work and read the
distribution. Do not reason forward from the item's parts. That is the inside view, and it is
where optimism lives. Reasoning about what the items *are* is still judgement; how long each
takes is arithmetic.

Then compute both, and reconcile them. If the two disagree by more than about two-fold, one of
them is wrong and finding out which is worth ten minutes.

### 1. Decompose into right-sized items

One item is one thing that **carries its own verification cycle**. Write the items out; for
each, write the command whose output settles whether it worked. If an item's check is "and
then also check", it is two items. If two items share one check and neither is verifiable
alone, they are one item.

**A pass delivers one item.** Two only when they form a strict dependency chain that a single
verification closes. Measured: a brief with five items delivered one; a brief with six
delivered one; the only brief fully delivered had three items in one chain.

### 1b. Merge the items that share one instrument

Step 1 counts checks. A corpus sliced by directory has one check per directory, so step 1 will
produce as many items as there are directories and every one of them will pass its own test.
That is how a ten-pass plan gets written for work that one pass does.

Put the items through three questions before costing anything.

1. **Do they share one procedure?** The same rule, the same script, the same shape of edit.
2. **Does one command settle all of them at once?**
3. **Does their union fit the context budget in step 2b?**

Three yes answers means one pass. Any no means the items split at that boundary. Measured, ten
directory-sliced items forecast at 361 minutes at p50 were delivered by one pass in 62 minutes,
and that pass then absorbed three more items the plan never had.

**A directory is not an item, and neither is a file type.** Both are orderings inside a pass.

**Homogeneous work gets an instrument rather than a sweep.** A pass that derives the rule once,
writes the script that applies it, and writes the verifier that proves the change stayed inside
its scope will change hundreds of files with tens of tool calls. The pass measured above changed
515 files using 27 Edit and Write calls out of 357 tool calls. Ten passes over the same corpus
would have derived the rule ten times and discarded the reading that produced it nine times. Say
so in the work package, because a pass that assumes per-file editing will run out of attention
before it runs out of files.

### 2. Bucket each item

The bucket sets the cost, **not the item's apparent difficulty**. That refusal to look at the
task is the whole of the outside view.

| bucket | p50 | p75 | p90 | typical tool calls | cost p50 | cost p90 | samples |
|---|---:|---:|---:|---:|---:|---:|---:|
| **implementation** | 38 | 58 | 99 | 152 | $22.02 | $45.70 | 50 |
| **read-only review** | 9 | 12 | 12 | 45 | $4.96 | $7.22 | 20 |
| **verify / browser** | 14 | 23 | 23 | 71 | $7.15 | $9.06 | 4 |
| **deploy / remote** | 48 | 62 | 97 | 168 | $27.36 | $95.48 | 19 |
| **documentation** | 11 | 11 | 11 | 70 | $7.08 | $7.08 | 3 |

Minutes of sub-agent wall clock, and this is the script's output rather than a transcription.

A pass is bucketed by **what it produced**, in this priority: three or more commands against
another host is deploy; any write to a file that is not `.md` or `.txt` is implementation;
writes only to `.md` is documentation; no writes with three or more browser calls is
verify/browser; no writes at all is read-only review. **A pass that drives a browser and then
writes source is an implementation pass.** Classifying by tool use instead of by production
collects those into the browser row and inflates it by a factor of three.

The implementation and read-only rows were re-derived under that classification and reproduced
to within 5 and 2 minutes on the same samples. The deploy row moved, from 73/157/184 on six
samples to 48/62/97 on nineteen, so **deploy is no longer nearly twice implementation**. It is
about the same at p50 and it carries the widest cost spread in the table.

Cost is an attempt cost at Claude Opus 5 rates before any context cap, and it falls about 22%
under the cap set in 2b.

**Treat it as pinned.** Three buckets can be leaned on, at 50, 20 and 19 samples. **The
verify/browser and documentation rows stay provisional** at four and three, and a bucket with
three samples is a guess wearing a percentile. They stay thin because almost no pass here is
purely one of those: a pass that takes a screenshot usually also writes the code it is
screenshotting.

A pass is classified by what it *produced*, not by what it was called. A documentation pass that
made sixty source edits is an implementation pass, and the classifier buckets it that way. That
is why the documentation row is as tight as it is. It holds only the passes that really were
prose.

**Two cautions about the two smallest buckets, both learned by getting an estimate wrong.**

**A demonstration is not a browser pass. Cost it as implementation.** A pass sent to restart
infrastructure, wait for recovery and repeat runs was forecast from the verify/browser row at 30
minutes and took **50.6**, which is the implementation row plus its adders almost exactly. The
browser row holds passes that walked a page and took a screenshot; anything that restarts a
container, waits on it, and repeats belongs in implementation however its deliverable reads.

**The verify/browser and documentation rows cannot grow on their own.** Classification looks at
what a pass wrote, and any write to source makes it an implementation pass however its
deliverable reads. A pass that walks three pages and then fixes what it found is therefore
implementation, which is correct and which is also why those two rows stay at four and three
samples. **Do not read their percentiles as having been confirmed by recent work.** Reach for
the implementation row when in doubt, because being wrong in that direction costs a forecast and
being wrong in the other costs a schedule.

How to pick: if it writes source, implementation. If it only reads, review. If its deliverable
is a screenshot or a driven flow and it writes nothing, verify/browser. If it touches a host
that is not this one, deploy, which costs about the same as implementation at the median and
three and a half times as much at p90, so the classification decides the tail rather than the
middle.

### 2b. Check the pass against the context budget

The bucket sets the duration. The context window sets how much one pass can hold, and it is the
number that decides whether two items merge.

| measure | value | samples |
|---|---:|---:|
| prompt growth per tool call, p50 | 1,574 | 96 |
| prompt growth per tool call, p90 | 2,603 | 96 |
| peak prompt of the median pass | 190,402 | 96 |
| peak prompt of the p90 pass | 293,276 | 96 |
| largest pass recorded, no compaction | 689,268 | 1 |
| passes that compacted at all | 4 of 96 | 96 |

Ninety-six recorded passes on a one-million-token window. The four that compacted all ran under
an earlier model with a smaller one.

**Two limits apply, and the lower of the two binds.**

| limit | value | why |
|---|---:|---|
| an implementation pass | 250,000 | cost |
| a read-only or review pass | 150,000 | quality |
| the coordinator session | 350,000 | cost |
| any pass, as a fraction of its window | 60% | quality |

On a one-million-token model the 60% figure is 600,000 and the absolute cap is 250,000, so the
cap binds. On a 262,000-token model the 60% figure is 157,000, so that binds instead.

**The cost limit.** Every turn re-sends the whole prompt, so the price of a turn rises with the
context the pass carries. Measured over 20,405 recorded turns, a turn taken at 600,000 tokens
costs about 6.8 times the same turn taken below 100,000. Capping the recorded history at
250,000 and 150,000 would have cut its cost by 24% for 58 restarts, and at 200,000 and 100,000
by 35% for 123 restarts. The looser set keeps 70% of the money for 47% of the interruptions.

**The quality limit.** Sixty percent is the conservative reading of the long-context literature,
where multi-hop retrieval accuracy falls off between 50% and 65% of an advertised window. The
same literature puts degradation onset at an absolute count of 32,000 to 100,000 rather than at
a fraction. **Neither has been observed in this repository**, where the largest recorded pass
reached 732,644 tokens and produced a 515-file change that survived review. The 150,000 figure
is therefore an aim rather than a limit, and every recorded read-only pass already meets it:
none has ever exceeded 189,928.

### 2c. Convert the cap into tool calls, because a token budget cannot be checked

**An agent cannot see its own context.** Where a harness supplies a live token warning it fires
against the window, not against a budget a plan chose. An agent's sense of its own context is
the same kind of feeling as its sense of its own elapsed time, and that one is wrong by a factor
of two in both directions.

An agent **can** count its own tool calls. At the measured p90 growth rate of 2,603 tokens per
call:

| cap | tool calls at p90 | at p50 |
|---:|---:|---:|
| 150,000 | 58 | 95 |
| 250,000 | 96 | 159 |
| 350,000 | 134 | 222 |

Write the tool-call number into the work package, and use the p90 column. An implementation pass
spends 152 calls against a budget of 96, so **the median implementation pass under this cap
hands over about once.** Say so in the plan rather than discovering it.

Two mechanisms carry the budget when attention does not: `maxTurns` in the agent definition,
which the harness enforces, and the `PostToolUse` counter hook, which puts the number back in
front of the pass at 80%.

These figures are pinned. Read "The tables are pinned" at the end of this file before changing
any of them.

### 3. Add the verification and rebuild cost

Additive to the bucket, because the percentiles come from passes that mostly ran the cheap
checks.

| check | cost |
|---|---:|
| unit tests | < 1 min |
| `cargo check` + `dx check`, warm | 2 min |
| an agent image rebuild, cold | 7 min |
| the same, warm | < 1 min |
| the restart-resilience gate | 6 min |
| a full stack verification | 25 min |
| a browser acceptance pass | 23 min |
| a driven-chat gate | 15 min |

A stack verification and a browser pass in the same item is a 48-minute adder on a 40-minute
bucket. **That arithmetic is telling you the item is really two.**

**Known defect: these adders are counted twice.** The bucket percentiles are total pass minutes,
so a pass that ran a stack verification already carries those 25 minutes inside its bucket
figure, and adding them again on top double-counts. Every estimate in this repository's archive
has this, and the effect is that the median column behaves like a ninetieth percentile. The
measured sprint that came in at 64% of its forecast is the same observation from the other side.
Fixing it means
re-deriving the adder table against the bucket table in one measurement, which is a separate
request from a person. Until then, **read the median forecast as a conservative figure and do
not add a safety margin on top of it.**

Count image rebuilds and stack restarts separately: two items needing the same rebuild pay for
it once *if they are in the same pass* and twice if they are not. This is the only place
batching genuinely saves time.

### 4. Sum, and double for the organizer

`T50 = Σ(bucket p50 + adders)`, `T90` the same at p90. **Report both, never a single figure.**
The distribution is long-tailed and a mean is a commitment nobody can keep.

Then apply the session multiplier, and **it depends on the pass count**:

| plan size | `S / T` | measured range | samples |
|---|---:|---|---:|
| eight passes or more | **1.3** | 1.28 to 1.43 | 4 |
| fewer than eight passes | **3.3** | 1.91 to 6.72 | 4 |

Measured across eight sessions that ran four or more sub-agent passes, counting coordinator time
as active time, meaning the sum of its own gaps of fifteen minutes or less. The four largest
sessions, at 28, 21, 12 and 8 passes, gave 1.29, 1.28, 1.43 and 1.30.

The reason is arithmetic. **Coordinator cost scales with the number of passes and agent cost
scales with the volume of work.** A sprint of many long passes therefore has a low multiplier,
and a short session of four quick passes has a high one, because a fixed coordinator cost sits
on top of almost no agent time. An earlier reading of this file gave a flat `S = T × 2` from
four samples that were mostly the second kind.

**The per-pass part of that cost is small.** The coordinator gap between one pass ending and the
next starting, over 61 recorded pairs, is 1.5 minutes at p50, 2.8 at p75 and 10.4 at p90. Plan
against the median and hold the p90 for a coordinator that is a person reading every diff.
Merging ten passes into one still removes nine review cycles and nine work packages.

**Add half a pass for every item that is not a single mechanical change.** Three of five briefs
in the last sprint needed a resume, and a resume is cheap. It costs no slot and keeps the
agent's context.

## The block every plan carries

```markdown
## Estimate

| # | item | bucket | V + R | T50 | T90 | cost p50 |
|---|---|---|---:|---:|---:|---:|
| 1 | <the item> | implementation | stack verify 25 | 63 | 124 | $22.02 |
| | **totals** | | | **T50** | **T90** | **$** |

**Passes:** N items merged into P passes, M invocations counting resumes and handovers.
**Why P and not fewer:** one line per split, naming what forced it. A different instrument, a
different check, or the context budget.
**Context:** forecast peak prompt for the largest pass, against the cap in 2b, naming any pass
that is forecast above it and therefore runs across two contexts.
**Tool-call budget:** the cap converted at the p90 rate, per pass.
**Agent wall clock:** T50 to T90 minutes. **Session wall clock:** `T × 1.3` at eight passes or
more, `T × 3.3` below that.
**Cost:** forecast at the bucket rates, before the cap.
**Method:** reference class, `.agents/skills/planning-work/reference/estimating.md`.
```

**The final report restates every column, cost included, with actuals beside them.** Cost is
now measurable, and a forecast with no measured outcome beside it is how the old estimates
stayed wrong.

**The final report restates that table with an actuals column beside the forecasts.** One
column, written once, at the end. Its absence is the entire mechanism by which the old
estimates stayed wrong.

## Three things the numbers will not tell you

**An agent cannot measure its own elapsed time, and always overestimates it.** Passes reporting
they had "roughly doubled" a one-hour box had used twenty-four minutes of it; one reporting a
"2.5× overrun" had used forty-seven. **A self-timebox is a budget of effort and attention, not
a clock.** Ask a pass what it did not reach, never how long it took. Wall clock comes from
outside the agent.

**Duration is not success.** These are durations of passes that ran, not of passes that worked.
A pass that spends forty minutes shipping a defect is indistinguishable here from one that
spends forty minutes shipping a feature. Gates are what separate them and they are measured
nowhere.

**The pass count is where the large errors live.** A duration table can only be wrong by the
width of its bucket. A pass count can be wrong by a factor. The two recorded sprints here show
both failures side by side. Sixteen genuinely different items were forecast at 1,105 minutes and
took about 707, an error of 1.6x that lived in the per-pass cost. Ten same-shape items were
forecast at 361 minutes and took 62, an error of 5.8x that lived entirely in the count.
**The final report records the forecast pass count against the actual pass count**, in the same
table as the durations.

## The tables are pinned

Both tables in this file are recorded measurements from **one repository, one harness, one model
family**. That parochialism is deliberate, and it is why none of it transfers.

**Do not regenerate them while planning work.** A pass that re-derives its own reference class
reads whatever history sits on the machine it is running on. A developer using a different
editor, a different agent, or a fresh checkout has a thin history or none, and a thin sample
prints percentiles that look exactly like a measurement. Plan against the numbers as they stand
here, including on a machine that could produce different ones.

**Moving a table is a decision a person makes and asks for.** When that is asked, these two
scripts print a distribution and change no file.

```
.agents/skills/planning-work/reference/mine-wall-clock.py ~/.claude/projects/<project>/
.agents/skills/planning-work/reference/mine-context.py    ~/.claude/projects/<project>/
.agents/skills/planning-work/reference/mine-cost.py       ~/.claude/projects/<project>/
```

The first says how long a pass runs. The second says how much of its window it used and whether
it compacted, and it refuses to print percentiles below twenty passes. The third says what a
pass cost, what it would have cost under a cap, and how many restarts that cap would have added.
Replacing a pinned table means editing this file by hand, keeping the sample count beside each
row, and saying in the plan that the reference class moved.

Two derived facts worth keeping while they hold: **a tool call costs about fourteen seconds**,
and wall clock correlates with tool-call count at r = 0.76 against only 0.46 for edit count,
so tool calls are the size unit and edits are not. An agent that reads a lot is as expensive as
one that writes a lot.

**Do not copy this table into a `Readme.md`, into `docs/`, or into `AGENTS.md`.** It is a
measurement with a half-life, and a tracked file states what is true now.
