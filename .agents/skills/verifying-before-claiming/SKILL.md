---
name: verifying-before-claiming
description: Runs the check that proves a claim before the claim is made, covering builds, type checks, unit tests, stack verification and browser passes. Use before saying anything works, is fixed, passes, is done, compiles, or is ready to commit; before opening a commit or a report; and whenever asked "did you verify", "are you sure", "did you test it", or "prove it". Maps each claim to the one command that settles it and ships those commands as scripts, so the hoover4 incantations (cargo check inside hoover4-website, pytest inside hoover4-worker, dx check, verify-stack.sh) are run rather than retyped. Also covers reporting a cause fix apart from a workaround, and waiting on a long check without disturbing it.
allowed-tools: Bash, Read, Grep, Glob
---

# Verifying before claiming

Evidence before assertion. If the command that proves a claim did not run in this turn, the
claim is not available to you. Say what you actually know instead.

## The gate

Before writing "works", "fixed", "passes", "done", "should be fine", or expressing
satisfaction:

1. **Name the claim.** What exactly are you asserting?
2. **Name the command that settles it**, from the table below.
3. **Run it in full.** Not a subset, not a previous run, not a tail of an old log.
4. **Read the output and the exit code.** Count failures rather than skimming for the word
   "error"; a truncated log has cost a full rebuild cycle here before.
5. **State the claim with the evidence, or state the real status with the evidence.**

Skipping a step is not speed. It converts a five-minute check into a rediscovery the next
session pays for.

## Claim → evidence

| claim | what settles it | how |
|---|---|---|
| the Rust workspace compiles | `cargo check` exit 0, zero `error[` lines | `scripts/cargo-check.sh`: it includes the test targets, and that is not optional |
| the frontend has no hook or `rsx!` defect | `dx check --package frontend` | `scripts/dx-check.sh`: a release build only says `unreachable`, and this names the site |
| the Python unit tests pass | pytest summary, 0 failed | `scripts/pytest-unit.sh` |
| migrations are well-formed | the parity test passes | `scripts/pytest-unit.sh tests/unit/test_migrations_parity.py` |
| the research agent's own tests pass | pytest summary, 0 failed | `scripts/pytest-research-agent.sh`, its image carries neither pytest nor the tests, so nothing else reaches them |
| the pipeline still ingests end to end | `main_services/verify-stack.sh` reaching its final assertion | `reference/verification-runs.md` |
| a container is healthy | `docker ps --format '{{.Names}}\t{{.Status}}'` plus its own logs | `scripts/stack-status.sh` |
| the deploy succeeded | full `./deploy` output read, not the last 50 lines | `deploying-the-stack` |
| the UI change renders | a screenshot or an accessibility snapshot of the page | `driving-the-browser` |
| data landed | a count query against the real table | `querying-the-datastores` |
| a bug is fixed | the original symptom re-triggered and now absent | reproduce it first, or you cannot claim it |
| a sub-agent did the work | the diff, read by you | its report is a claim, not evidence |

Run the scripts, do not retype the commands they wrap. Each one already carries the parts
that are easy to get wrong. The container name, the `PATH` that Rust lives on, the working
directory, the `--offline` flag, the output filter.

```
.agents/skills/verifying-before-claiming/scripts/cargo-check.sh   # ~10 s warm, ~90 s cold
.agents/skills/verifying-before-claiming/scripts/dx-check.sh
.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh [path]
.agents/skills/verifying-before-claiming/scripts/pytest-research-agent.sh [path]
.agents/skills/verifying-before-claiming/scripts/stack-status.sh
```

The repo-relative path is written first because only one harness substitutes
`${CLAUDE_SKILL_DIR}` and the rest run the literal string; where it is substituted,
`${CLAUDE_SKILL_DIR}/scripts/…` is the same file.

## Cause or workaround: say which

A stalled Temporal activity can be cleared with
`temporal activity fail -w <id> --activity-id <n>`. That proves the retry path works and
says nothing about why the task was lost. Report it as a workaround, in those words. The
same applies to a restart that clears a symptom, a retry that happens to succeed, and a
value nudged until the error stops. A fix names the mechanism; anything else names what it
unblocked.

## Waiting without disturbing

Long checks are backgrounded, not polled by hand. `main_services/verify-stack.sh` runs for
tens of minutes inside `hoover4-worker`, and any `./deploy` restarts that container and kills
it. Check what is in flight before deploying, and batch fixes so one restart serves
several.

- Background the command and let the harness notify you, rather than writing an
  `until … grep … do … done` loop or tailing an output file every thirty seconds.
- A monitor that only emits on failure signatures beats polling, but make sure its filter
  would fire on a crash. Silence must not be indistinguishable from success.
- Redirect full output to a file and grep it. Never judge a build from `tail -50`.

## A green suite is not a working feature

The two worst defects of a recent pass survived every unit test and both type checks, and were
found only by driving a real conversation against the running stack. One of them **inverted the
meaning of the signal it reported**. A third shipped a service call that could never have
worked, because the API rejects a field the build has no opinion about.

The pattern: a test exercises the code you wrote, and a type check exercises its shapes.
Neither exercises **the thing on the other side** (a model deciding whether to call a tool,
a server accepting a field name, a page rendering under a real browser). So:

- **A tool is not verified by being registered.** Call it, from a real chat, and read what came
  back.
- **A call across a wire is verified by making the call**, never inferred from a build.
- **A feature whose consumer is a model is verified by watching the model use it**, because
  "the model can see it" and "the model can use it" are different claims.

Cheap and worth the minutes: a real question through the real interface beats another test.

## What does not count

- "Should work now", "I'm confident", "the linter passed", "the logs look fine".
- A check run before the last edit.
- A partial run: one test file when the claim is about the suite, one crate when the claim
  is about the workspace.
- A sub-agent's success report.
- A green `cargo check` standing in for a frontend claim, which misses server-build and
  hook errors that only `dx check` and a real page load surface.

## Two blind spots in the tooling itself

**A plain `cargo check` does not build test targets.** A signature change updated everywhere
in `src/` leaves it green while the test binaries no longer compile. The tests do not fail,
because they are never built, and a broken integration-test binary can sit unnoticed for a long time.
`cargo check --workspace --tests` is the cheap closer, and `scripts/cargo-check.sh` already
passes it.

**Both fixture-driven suites are welded to the corpus the stack verification ingests**. The
screenshot page list and the stack integration tests. Away from that corpus they fail by
naming a dataset that does not exist, which reads as a broken site and is not. Before
concluding anything from a wall of red, check that the fixtures are there.

## References

- `reference/verification-runs.md`, the phases of `main_services/verify-stack.sh`, what it
  asserts, and how to read a partial run.
- `reference/browser-pass.md`, the minimum click-through for a UI claim.
- `docs/development/Running_Checks.md`, the same ground for a person reading cold, with what
  each check does **not** cover.
