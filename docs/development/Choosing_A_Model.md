# Choosing a model

This repository runs two models rather than one. This page says why, and how a model qualifies
to run work here.

## Contents

- [Two roles](#two-roles)
- [The four gates](#the-four-gates)
- [Cost per resolved pass](#cost-per-resolved-pass)
- [Where the names live](#where-the-names-live)

## Two roles

**A planner reads, decides and reviews.** It scopes the work, writes the work package, reads the
diff that comes back, and decides whether it is accepted. A wrong decision here propagates into
every pass that follows, so this role takes the strongest model available.

**An executor applies a written work package and runs the checks it names.** Its scope is a named
list, its checks are commands with an expected output, and its diff is read by the planner before
anything else happens. A weaker model is viable here because the work is bounded and the result
is checked.

The roles differ in what they need, so they differ in model. Pairing them is only worthwhile when
the executor is genuinely cheaper and genuinely capable, which is what the gates below test.

## The four gates

A model is excluded by a property rather than by name. Model names change every few months, and a
list of names that are too weak goes stale in the direction that blocks a good model.

| gate | the rule |
|---|---|
| **context** | the window must be at least 1.7 times the pass cap, so a pass has room above its budget |
| **tool loop** | the model must sustain a 150-tool-call pass without losing the work package |
| **self-hosting** | the model must be served by a harness this repository can configure |
| **acceptance** | its cost per resolved pass must beat the planner's |

The first three are read off a specification sheet. **Only the fourth can exclude a model that
looks capable and is not**, and it needs a measurement rather than a reputation.

Gate one is worth an example, because it excludes a model that otherwise looks like the obvious
executor. A model whose entire context window equals the pass cap has no room above its budget,
so a pass that runs long has nowhere to go. That is an exclusion by arithmetic against a
published window size, and a reader can check it without an opinion.

## Cost per resolved pass

Price per token does not order these models, because a weaker model retries and each retry costs
a review cycle as well as an attempt.

```
cost per resolved pass = attempt cost / acceptance rate
```

A model at half the price and half the acceptance rate is more expensive. The published figure
worth holding while reading a first result is that about a third of agent-authored changes reach
merge without modification.

**A model qualifies by running three passes from the reference class**, each with a written work
package, each reviewed the way any pass is reviewed. Record four things per pass: the attempt
cost, the wall clock, whether the checks it named reproduce, and whether any file outside the
scope list moved. Three passes give a first acceptance rate, and that is the number the gate
reads.

Decide what would make the trial a failure before it runs, so the result is not argued
afterwards. An edit outside the named scope, a check reported as passing that the reviewer cannot
reproduce, or a second revision round still not meeting the done criteria are each enough.

## Where the names live

`.agents/harnesses/model-pairs.md` holds the current pair per harness, and nothing else in the
tree names a model. That file is expected to go stale and says so. **The gates on this page do
not go stale**, so a reader who finds the names out of date can still decide correctly.

Which model a sub-agent runs is set in the agent definition, and the paths per harness are in
[`Working_With_Agents.md`](Working_With_Agents.md).
