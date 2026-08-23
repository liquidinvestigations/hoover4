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

| bucket | p50 | p75 | p90 | typical tool calls | samples |
|---|---:|---:|---:|---:|---:|
| **implementation** | 43 | 58 | 92 | 156 | 50 |
| **read-only review** | 10 | 12 | 14 | 46 | 24 |
| **verify / browser** | 23 | 29 | 29 | 76 | 4 |
| **deploy / remote** | 73 | 157 | 184 | 134 | 6 |
| **documentation** | 7 | 8 | 8 | 41 | 3 |

Minutes of sub-agent wall clock, and this is the script's output rather than a transcription.
**Treat it as pinned.** The first two buckets can be leaned on; the last three are provisional
at four, six and three samples, and a bucket with three samples is a guess wearing a percentile.

A pass is classified by what it *cost*, not by what it was called: a documentation pass that
made sixty edits is an implementation pass, and the script buckets it that way. That is why
the documentation row is as tight as it is. It holds only the passes that really were prose.

**Two cautions about the two smallest buckets, both learned by getting an estimate wrong.**

**A demonstration is not a browser pass. Cost it as implementation.** A pass sent to restart
infrastructure, wait for recovery and repeat runs was forecast from the verify/browser row at 30
minutes and took **50.6**, which is the implementation row plus its adders almost exactly. The
browser row holds passes that walked a page and took a screenshot; anything that restarts a
container, waits on it, and repeats belongs in implementation however its deliverable reads.

**The verify/browser and documentation rows cannot grow on their own.** Classification looks at
the description first, so a pass whose title happens to avoid the words *verify*, *browser*,
*acceptance*, *smoke* or *screenshot* falls through to the cost-based default. That is the right
default and it is why those two rows stay small and stale. **Do not read their percentiles as
having been confirmed by recent work**. Reach for the implementation row when in doubt, because
being wrong in that direction costs a forecast and being wrong in the other costs a schedule.

How to pick: if it writes source, implementation. If it only reads, review. If its deliverable
is a screenshot or a driven flow, verify/browser. If it touches a host that is not this one,
deploy, and that bucket is nearly twice implementation, so the classification is worth getting
right.

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

**Budget 60% of the window.** On a one-million-token model that is 600,000 tokens, which buys
about 230 tool calls at the p90 growth rate and about 380 at p50. An implementation pass in the
bucket table above spends 156 tool calls. **One context holds two to three of the passes this
repository writes today.**

Sixty percent is the conservative reading of the long-context literature, where multi-hop
retrieval accuracy falls off between 50% and 65% of an advertised window. A pass is an easier
shape of long context than multi-hop retrieval, because the model wrote most of its own context
in the order it will be needed. The largest pass recorded here stayed correct under review at
69%. Plan against 60% and stop adding work at 70%.

On a model with a smaller window, scale the budget and keep the rule. Half a 500,000-token
window is 300,000 tokens, which is about 115 tool calls at the p90 growth rate. Where a vendor
prices a prompt in tiers, the tier boundary is the budget, whatever the window says.

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

Count image rebuilds and stack restarts separately: two items needing the same rebuild pay for
it once *if they are in the same pass* and twice if they are not. This is the only place
batching genuinely saves time.

### 4. Sum, and double for the organizer

`T50 = Σ(bucket p50 + adders)`, `T90` the same at p90. **Report both, never a single figure.**
The distribution is long-tailed and a mean is a commitment nobody can keep.

Then `S = T × 2`. Measured across sessions running sub-agents strictly one at a time: 1.1, 1.9,
2.1 and 4.0. Reviewing a diff, re-running a check the pass named, grading a gate and writing
the next work package costs about as much again as the agents do.

**That cost is per pass, so it falls with the pass count.** On the four-package run measured
here the coordinator gaps between packages were 5.1, 20.7 and 2.3 minutes, which is 28 minutes
of review and repackaging against 112 minutes of agent work. Merging ten passes into one removes
nine review cycles and nine work packages. Multiply by two for a plan with many different items,
and expect much less for a plan whose passes were merged.

**Add half a pass for every item that is not a single mechanical change.** Three of five briefs
in the last sprint needed a resume, and a resume is cheap. It costs no slot and keeps the
agent's context.

## The block every plan carries

```markdown
## Estimate

| # | item | bucket | V + R | T50 | T90 |
|---|---|---|---:|---:|---:|
| 1 | <the item> | implementation | stack verify 25 | 65 | 117 |
| | **totals** | | | **T50** | **T90** |

**Passes:** N items merged into P passes, M invocations counting resumes.
**Why P and not fewer:** one line per split, naming what forced it. A different instrument, a
different check, or the context budget.
**Context:** forecast peak prompt for the largest pass, against the 60% budget.
**Agent wall clock:** T50 to T90 minutes. **Session wall clock:** twice that for a plan of
different items, less for a plan whose items were merged.
**Method:** reference class, `.agents/skills/planning-work/reference/estimating.md`.
```

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
```

The first says how long a pass runs. The second says how much of its window it used and whether
it compacted, and it refuses to print percentiles below twenty passes. Replacing a pinned table
means editing this file by hand, keeping the sample count beside each row, and saying in the
plan that the reference class moved.

Two derived facts worth keeping while they hold: **a tool call costs about fourteen seconds**,
and wall clock correlates with tool-call count at r = 0.76 against only 0.46 for edit count,
so tool calls are the size unit and edits are not. An agent that reads a lot is as expensive as
one that writes a lot.

**Do not copy this table into a `Readme.md`, into `docs/`, or into `AGENTS.md`.** It is a
measurement with a half-life, and a tracked file states what is true now.
