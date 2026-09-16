# Choosing a model

This repository assigns four roles to planned work. This page explains how a model qualifies
for an executor role.

## Contents

- [Four roles](#four-roles)
- [The four gates](#the-four-gates)
- [Cost per resolved pass](#cost-per-resolved-pass)
- [Where the names live](#where-the-names-live)

## Four roles

**The organizer scopes work and writes packages.** It assigns one logical role to each pass,
reads the review result and owns Git checkpoints. It does not implement a package.

**The executor-light applies an ordinary original package.** The plan gives it named paths,
checks and expected results. A reviewer reads its diff.

**The executor-heavy applies corrections and selected original packages.** The plan selects
eligible original passes by the score in `planning-work`. Every correction uses this role.

**The reviewer reads the completed diff.** It reports findings by defect class and writes a
correction package when it rejects the pass. It runs no Git write command.

The roles have different model mappings. The gates below qualify the `executor-light` model
against the `executor-heavy` model of the same harness.

## The four gates

A model is excluded by a property rather than by name. Model names change every few months, and a
list of names that are too weak goes stale in the direction that blocks a good model.

| gate | the rule |
|---|---|
| **context** | the window must be at least 1.7 times the pass cap, so a pass has room above its budget |
| **tool loop** | the model must sustain a 150-tool-call pass without losing the work package |
| **self-hosting** | the model must be served by a harness this repository can configure |
| **acceptance** | the `executor-light` model's cost per resolved pass must beat the `executor-heavy` model's cost in the same harness |

The first three are read off a specification sheet. **Only the fourth can exclude a model that
looks capable and is not**, and it needs a measurement rather than a reputation.

Gate one is worth an example, because it excludes a model that otherwise looks like the likely
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

`.agents/harnesses/model-mappings.md` lists the four models per harness. The project role
files set the identifiers used by each harness. Apply the gates on this page when a model
mapping changes.

Which model a sub-agent runs is set in the agent definition, and the paths per harness are in
[`Working_With_Agents.md`](Working_With_Agents.md).
