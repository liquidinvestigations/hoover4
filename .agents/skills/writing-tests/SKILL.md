---
name: writing-tests
description: Answers which tests a change puts at risk and where a new test belongs, before the change lands. Use when about to change code and needing to know what covers it, about to fix a bug, about to write a test, or asking which tests a change endangers. Ships `scripts/gate-map.sh`, which routes a changed path to the gates it owes rather than selecting inside a suite, because the whole fast Python tier runs in about 17 seconds. Covers the four routing rules, the measured suite table, and the shape of a good test against its three anti-patterns. Fires before a change is written, where `verifying-before-claiming` fires once a claim about the result is about to be made.
allowed-tools: Bash, Read, Grep, Glob
---

# Writing tests

The fast Python tier runs in seconds. Nothing here selects a subset of it, because
selecting inside a suite that already runs in seconds saves nothing. The Rust suites are
compilation-bound: filtering the stack suite still pays the compile.
[`docs/quality-assurance/Test_Suites.md`](../../../docs/quality-assurance/Test_Suites.md)
carries the measured table. `reference/suites.md` points there.

**What is worth routing is the gate a change owes**, because the gates that cost 6 to 25
minutes are the ones this repository documents as deliberately off the per-commit path, and
they are the ones a change actually skips.

## The four rules

1. **Always run the fast tier.** `pytest-unit.sh` and `pytest-agents.sh`, both of them,
   after any Python change.
2. **Rebuild before believing an agent suite.** The agent tests run inside the images and
   the agent code is baked into them. A source edit under `main_services/agents/` that is
   not followed by an image rebuild leaves the suite testing the previous image, and it
   passes.
3. **Route the expensive gates by path**, with `scripts/gate-map.sh`. It names the gates a
   set of changed paths owes and the couplings to check by hand. It never selects a subset
   of a suite and it never claims a change is safe. It names what is owed and the person or
   the pass decides what to spend. Run it with no argument to route
   `git diff --name-only HEAD`, or `--self-check` to verify the table against the tree
   instead of routing a change.
4. **For a symbol, ask serena. For a coupling, read the list.**
   `find_referencing_symbols` (`finding-code`, `reference/serena-calls.md`) answers who else
   uses a changed symbol, for Python and Rust. Five couplings are not reachable that way,
   because none of them is a symbol reference: a mirrored constant, a Temporal registration
   bound by name, a wire format, a writer contract, and migration text split by a runner
   that does not parse SQL. `reviewing-changes` names each one, and `gate-map.sh` points at
   that list rather than repeating it.

## A repair carries a regression test

Where a fast suite already reaches the changed code, a repair carries a regression test.
`docs/quality-assurance/Running_Checks.md` already settles a fix by the failing case reproduced before and absent
after, and a regression test is that sentence made durable.

**Three areas have no fast-test interface**: the frontend, configuration, and scripts.
There, a passing `dx-check.sh` plus a screenshot, or the check that a script's own output
names, is the evidence a fast suite would otherwise give.

## Running a check

`gate-map.sh` names the command; it does not run it and does not wrap it a second time.
Run the named script from `verifying-before-claiming`, and read
`docs/quality-assurance/Running_Checks.md` for what each one does and does not cover.

## References

- [`docs/quality-assurance/Test_Suites.md`](../../../docs/quality-assurance/Test_Suites.md), the measured table for every suite, how it runs, and what it does not cover.
- `reference/suites.md`, a pointer to that table.
- `reference/test-shapes.md`, what a good test is and the three anti-patterns.
- `scripts/gate-map.sh`, the router.
