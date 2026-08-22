# Estimating a plan

A plan says how big the work is. This is how that number is arrived at, in units that the
report which follows can contradict.

## The one rule everything else serves

**Estimate in passes, never in developer days.** A pass is one sub-agent invocation. A
developer day is a unit nothing here has ever been measured in, and a duration that cannot be
falsified by the report that follows it is not an estimate — it is decoration.

The failure this prevents is specific and it has already happened: twenty-one plan headings
carried a parenthetical day-cost, and not one was ever checked against an outcome, because
every report that followed them was written in a different unit. The estimates could not
improve, and each new plan was written by someone reading the last plan's *estimates* rather
than the last plan's *outcomes*.

## The method

Take the **outside view** first: put the item in a class of comparable past work and read the
distribution. Do not reason forward from the item's parts — that is the inside view, and it is
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

### 2. Bucket each item

The bucket sets the cost, **not the item's apparent difficulty**. That refusal to look at the
task is the whole of the outside view.

| bucket | p50 | p75 | p90 | typical tool calls | samples |
|---|---:|---:|---:|---:|---:|
| **implementation** | 41 | 58 | 92 | 156 | 42 |
| **read-only review** | 10 | 12 | 14 | 46 | 24 |
| **verify / browser** | 23 | 29 | 29 | 76 | 4 |
| **deploy / remote** | 73 | 157 | 184 | 134 | 6 |
| **documentation** | 7 | 8 | 8 | 41 | 3 |

Minutes of sub-agent wall clock, and this is the script's output rather than a transcription —
**regenerate it rather than editing it by hand.** The first two buckets can be leaned on; the
last three are provisional at four, six and three samples, and a bucket with three samples is a
guess wearing a percentile.

A pass is classified by what it *cost*, not by what it was called: a documentation pass that
made sixty edits is an implementation pass, and the script buckets it that way. That is why
the documentation row is as tight as it is — it holds only the passes that really were prose.

How to pick: if it writes source, implementation. If it only reads, review. If its deliverable
is a screenshot or a driven flow, verify/browser. If it touches a host that is not this one,
deploy — and that bucket is nearly twice implementation, so the classification is worth getting
right.

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

`T50 = Σ(bucket p50 + adders)`, `T90` the same at p90. **Report both — never a single figure.**
The distribution is long-tailed and a mean is a commitment nobody can keep.

Then `S = T × 2`. Measured across sessions running sub-agents strictly one at a time: 1.1, 1.9,
2.1 and 4.0. Reviewing a diff, re-running a check the pass named, grading a gate and writing
the next work package costs about as much again as the agents do.

**Add half a pass for every item that is not a single mechanical change.** Three of five briefs
in the last sprint needed a resume, and a resume is cheap — it costs no slot and keeps the
agent's context.

## The block every plan carries

```markdown
## Estimate

| # | item | bucket | V + R | T50 | T90 |
|---|---|---|---:|---:|---:|
| 1 | <the item> | implementation | stack verify 25 | 65 | 117 |
| | **totals** | | | **T50** | **T90** |

**Passes:** N items, M invocations counting resumes.
**Agent wall clock:** T50–T90 minutes. **Session wall clock:** 2 × that.
**Method:** reference class, `.agents/skills/planning-work/reference/estimating.md`.
```

**The final report restates that table with an actuals column beside the forecasts.** One
column, written once, at the end. Its absence is the entire mechanism by which the old
estimates stayed wrong.

## Two things the numbers will not tell you

**An agent cannot measure its own elapsed time, and always overestimates it.** Passes reporting
they had "roughly doubled" a one-hour box had used twenty-four minutes of it; one reporting a
"2.5× overrun" had used forty-seven. **A self-timebox is a budget of effort and attention, not
a clock.** Ask a pass what it did not reach, never how long it took — wall clock comes from
outside the agent.

**Duration is not success.** These are durations of passes that ran, not of passes that worked.
A pass that spends forty minutes shipping a defect is indistinguishable here from one that
spends forty minutes shipping a feature. Gates are what separate them and they are measured
nowhere.

## Keeping the table true

```
.agents/skills/planning-work/reference/mine-wall-clock.py ~/.claude/projects/<project>/
```

Regenerate rather than remember. If the numbers have moved, move the table with them — and
note that this reference class is **one repository, one harness, one model family**. That
parochialism is the point, and it is also why none of it transfers.

Two derived facts worth keeping while they hold: **a tool call costs about fourteen seconds**,
and wall clock correlates with tool-call count at r = 0.76 against only 0.46 for edit count —
so tool calls are the size unit and edits are not. An agent that reads a lot is as expensive as
one that writes a lot.

**Do not copy this table into a `Readme.md`, into `docs/`, or into `AGENTS.md`.** It is a
measurement with a half-life, and a tracked file states what is true now.
