# Running the checks

What each check proves, what it costs, and (the part that matters) what it does **not**
cover. A check whose scope is misread is worse than no check, because it is quoted as
evidence for something it never examined.

## Contents

- [The claim-to-evidence table](#the-claim-to-evidence-table)
- [Rust type check](#rust-type-check)
- [Frontend hook check](#frontend-hook-check)
- [Python unit tests](#python-unit-tests)
- [Stack tests](#stack-tests)
- [Whole-stack verification](#whole-stack-verification)
- [Test reachability](#test-reachability)
- [Screenshots](#screenshots)
- [Waiting without disturbing](#waiting-without-disturbing)

The scripts that wrap each of these live beside the verifying skill, in
`.agents/skills/verifying-before-claiming/scripts/`. Run those rather than retyping the
commands: each already carries the container name, the working directory, and the flags that
are commonly got wrong.

## The claim-to-evidence table

| claim | the evidence that supports it |
|---|---|
| "it compiles" | `cargo check` inside the website container, full output read |
| "the frontend renders" | `dx check --package frontend`, then a screenshot of the page |
| "the pipeline logic is right" | the Python unit tests |
| "the endpoint works" | a stack test, or a request made from inside a container |
| "ingestion works end to end" | `main_services/verify-stack.sh` |
| "a worker restart loses nothing" | `main_services/verify-stack.sh --restart-resilience`, per-document assertions read |
| "it is deployed" | the container is up *and* answering, checked from inside the network |
| "the bug is fixed" | the failing case reproduced before, and not reproducible after |
| "the prose obeys the register" | `.agents/check-prose-style.py` over the changed paths, exit 0 |
| "every test directory has a runner" | `scripts/test-reachability.sh`, exit 0 |

Nothing on the left may be claimed on the strength of reading code.

## Rust type check

Rust is not on `$PATH` in the website container; it lives under the container's cargo
directory. The check runs offline against the workspace and type-checks both halves in about
ninety seconds cold and ten seconds warm, far cheaper than finding the same error by
waiting for a dev-server rebuild.

**It does not cover**: server-function bodies compiled only by the dev server, and any hook
ordering problem.

**And it does not build test targets unless you ask it to.** A plain `cargo check` leaves a
signature change that was updated everywhere in `src/` looking clean while the test binaries
no longer compile. The tests do not fail, because they are never built, so a broken integration-test
binary can sit unnoticed indefinitely. Pass `--workspace --tests` (or `--all-targets`, which
the check script uses); it is the cheap closer.

## Frontend hook check

A conditional hook traps the WebAssembly runtime on the render that adds it, leaving the page
painted and completely inert. The type check cannot see it and a release build reports it
only as an `unreachable` trap with no site named. `dx check --package frontend` names the
site, which is the whole reason it runs before the suite.

## Python unit tests

Run inside the worker container, against `tests/unit`. They need no stack. The migration
parity test lives here and covers the three ways the migration runner's naive `;` split
breaks.

**They do not cover**: anything requiring Temporal, ClickHouse, Manticore or Garage.

## Stack tests

Every test in the backend's stack integration suite needs a live stack, so the ignore
attribute cannot also mean "slow". Slowness is carried in the test **name** instead: the ones
that wait on something with its own clock carry a prefix and are skipped by default. Every
other test asserts its own wall time against a budget, which is what notices an endpoint that
quietly starts doing a full scan. Without that budget, a test that grows from a third of a
second to nine seconds still passes.

## Whole-stack verification

`main_services/verify-stack.sh` drives real ingestion from disk to index and asserts the
invariants that only appear end to end, including that no blob row references derived
storage.

It runs for tens of minutes. **Any deploy restarts the worker it runs inside and kills it.**
Check what is in flight before deploying, and batch fixes so one restart serves several.

On a host whose fixtures sit at a different depth, the ingest-root environment overrides are
mandatory.

**Both fixture-driven suites are welded to the corpus this run ingests**: the screenshot
page list and the stack integration tests. Away from that corpus they fail by naming a dataset that
does not exist, which reads as a broken site and is not. Check the fixtures before concluding
anything from a wall of red lines.

### Restart resilience

`main_services/verify-stack.sh --restart-resilience` runs **instead of** the checks above, not
before them. It ingests one fixture dataset, stops and starts the worker in the middle of it,
and then asserts what the workflow status does not: that every document ends up with chunks,
with vectors, and with an index row.

**That last part is what the assertion exists for.** A plan is marked finished when its stages *ran*, not
when every document succeeded, so workflow status reports success over documents whose
embeddings were lost. Only a per-document assertion tells the two apart.

It is **deliberately not on the per-deploy or per-commit path.** It costs a worker restart and
several minutes, and a gate that expensive stops being run. Run it when the worker's process
lifecycle changes: `tasks/run_worker.py`, `tasks/heartbeat.py`, the graceful shutdown
configuration, or the worker's stop grace period. It purges its own fixture dataset first, so
it is repeatable; without that a second run would pass over the first run's data having tested
nothing.

Two things it prints that are not failures. The re-drive after the restart can fail with
`WorkflowAlreadyStartedError`: that is durable execution working. The workflows survived and
the client that died was only sequencing them. And `INGEST_ROOT_RESTART` selects the fixture,
defaulting to the same testdata root the normal run uses.

## Test reachability

`scripts/test-reachability.sh` enumerates every test directory this repository owns and
confirms each is reached by a runner, meaning a script that actually executes it. It fails
and names the directory when none reaches it, rather than passing silently on a suite that
ships inside an image and runs nowhere.

**It does not run the tests themselves.** It checks that a runner exists and still names the
directory it was built for; the runner's own exit code is a separate claim, settled by
running that script.

## Screenshots

The screenshot script walks a page list and writes a PNG, a text snapshot of the rendered DOM
and any console errors per page, plus an index.

It does **not** go through the browser MCP endpoint: that server refuses internal hosts at two
independent layers by design, so the website is unreachable through it. The script instead
runs a plain browser inside that container with neither filter, and moves itself and its
output by file copy because the container has no bind mounts.

Two traps it exists to encapsulate: setting an input's value is invisible to the frontend
framework unless it goes through the prototype setter and dispatches a bubbling input event,
and the home box submits on key press, so Enter must be a real key event.

## Waiting without disturbing

Background a long check and watch for failure signatures rather than polling for progress,
but make sure the filter would fire on a crash, because silence must not be indistinguishable
from success. Never deploy over a live verification.
