# Testing the website

The suites, what each one covers, and the two diagnostics beside them. What each check does
*not* cover is [Running the checks](Running_Checks.md).

Use [Design browser tests around state changes](Browser_Test_Design.md) to define fixtures, ordered interactions, assertions, and evidence.

| what | how |
|---|---|
| unit (Rust) | `cargo test --offline` inside `hoover4-website`, Rust is not on `$PATH` there, so `export PATH=/usr/local/cargo/bin:$PATH` first |
| hook order | `dx check --package frontend` inside `hoover4-website`; `website/run-stack-tests.sh` and `website/development.sh` both run it first |
| live stack | `website/run-stack-tests.sh` (fast only), `./run-stack-tests.sh --slow` (everything) |
| whole stack | `main_services/verify-stack.sh` |
| screenshots | `website/take-screenshots.sh` |

**The stack tests are split by NAME, not by attribute.** Every test in
`website/backend/tests/stack_integration.rs` is `#[ignore]` already, because they all need a live
stack, so `#[ignore]` cannot also mean "slow". The ones that wait on something with its own
clock (the 30 s shard-state cache, a ClickHouse mutation) carry a `slow_` prefix and are
skipped by default. Every other test asserts its own wall time against
`HOOVER4_STACK_TEST_BUDGET_MS` (5 s), which is what notices when an endpoint quietly starts
doing a full scan: without it a test that grows from 0.3 s to 9 s still passes.

**`dx check` runs before the suite because it is the only thing that catches a conditional
hook.** Such a hook traps the WebAssembly runtime on the render that adds it, leaving the
page painted and completely inert. A failure `cargo check` cannot see and the release build
reports only as `RuntimeError: unreachable`. See
[`website/frontend/README.md`](../../website/frontend/README.md).

**`cargo check` does not build test targets, so it cannot see a broken test binary.** A
signature change updated at every call site in `src/` leaves `cargo check` clean and
`cargo test` unable to compile, and nothing between the two says so. The tests do not fail,
because they never get built. `cargo check --workspace --tests` (fast) or `cargo test --no-run`
(slower, and produces the binaries) is what closes that gap; run one of them alongside
`cargo check` whenever a public signature moves.

**Both fixture-driven suites are welded to the corpus `main_services/verify-stack.sh`
ingests**: `website/screenshots.ini`'s routes and `stack_integration.rs`'s `TESTFILES`, `SHAPES`,
`ZIPS` and `other`. On any other corpus they fail by naming a dataset that does not exist,
which reads as a broken page or a broken endpoint and is neither. Run `verify-stack.sh`
before either of them, or read their failures as a missing precondition rather than a
regression.

## Screenshots

`website/take-screenshots.sh` walks `website/screenshots.ini` and, per page, writes the PNG a
person would see, a text outline of the rendered DOM, and (where an action raised) the state
at the moment it failed. Output goes to `website/test_reports/screenshots/`, gitignored, and
is **never wiped**. Each run adds `run-<UTC-timestamp>-<pid>/` and rewrites the `latest`
symlink, so an earlier run stays on disk until removed by hand.

```
website/take-screenshots.sh                          # every page in the list
website/take-screenshots.sh --only search             # one substring of the scenario name
website/take-screenshots.sh --names qa-sort-empty-default,qa-sort-explicit-relevance
website/take-screenshots.sh --resolutions 1080p        # one resolution instead of the default 720p,1080p
website/take-screenshots.sh --target URL
website/take-screenshots.sh --login-env path/to/file   # credentials from a file
```

With no `HOOVER4_TEST_USERNAME`/`HOOVER4_TEST_PASSWORD` pair or `--login-env` file, the run
proceeds unauthenticated (a screenshot page runner can go on without an identity;
`observe-chat.sh`, below, cannot). `TEST_LOGIN.env` beside the script, when present, is the
login-env default; `TEST_LOGIN.env.example` names its keys. Credential values are not
accepted as wrapper arguments.

**Result rules.** Every observation is one of six severities; only two change the exit
status. `application_error` (a missing page, a non-200 main document, or an undeclared error
marker or bar) exits 1. `incomplete_execution` (a failed login, a stopped browser, a missing
fixture, or a capture that could not be written) exits 2 unless an application error also
occurred. A console
error or warning, a failed subresource request, or a request to an outside origin is
`diagnostic_warning` and exits 0, recorded in the report but never gating the run.
`expected_outcome` (a negative state a scenario declared with `expect`) and
`behavioral_warning` also exit 0.

**Output structure**, per run directory: `<resolution>/NN-name.png` and
`.snapshot.txt`; on a raised action, `<resolution>/NN-name.FAILED.png` and
`.FAILED.snapshot.txt` (the same shape, captured at the moment of failure);
`diagnostics/<resolution>__NN-name.json` (console and network records, written whether the
capture passed or raised) and, on a raise, `diagnostics/<resolution>__NN-name.exception.txt`
(the full traceback); `manifest.json`, `image_inventory.json`, `report.md`, `report.html`
for the whole run. Every PNG path appears in the inventory. Review state starts as `unreviewed`
and is stored apart from assertion verdicts.

**Troubleshooting.** A page that names a dataset that does not exist is incomplete execution:
the ini is welded to the corpus `main_services/verify-stack.sh` ingests, so run that
first. A whitelisted console entry in `tools/console_whitelist.txt` stays a
`diagnostic_warning`, only labelled with the rule that excused it; it never changes the exit
status either way.

It does **not** use the browser MCP endpoint. `hoover4-mcp-browser` refuses internal hosts
at two independent layers by design (a deny-list in `urlcheck.py` and a PAC script handed
to Chromium in `netfilter.py`), so `hoover4-website` is unreachable through it. The script
copies `website/tools/capture_screenshots.py` into that container and runs a plain Chromium with
neither filter, touching nothing about the MCP server's own behaviour. The container has no
bind mounts, so both the script and the output travel by `docker cp`.

Two traps the script exists to encapsulate: setting an input's `.value` is invisible to
Dioxus unless you go through the prototype's setter and dispatch a bubbling `input` event,
and the home box submits on `onkeypress`, so Enter has to be a real CDP key event. The long
base64 segments in the ini are CBOR route parameters (`website/frontend/src/data_definitions/url_param.rs`);
`9g==` is `None`.

## Manual QA matrix

`website/run-manual-qa.sh` validates the resolved fixture profile before it starts a browser capture.
It records each selected baseline and annex variation in `manual-qa-plan.json`.
It records each observed outcome in `manual-qa-results.json` and retains partial procedure evidence after failures.
Use `--select` for a row list and `--skip-chat` when the row list does not include chat.
The command uses one chat generation for row 25 and its viewport observations.
Chat history verification compares persisted assistant answers. It excludes temporary disclosures and document previews.

## Observing a chat conversation

`website/observe-chat.sh` drives a real chat conversation to completion in the same
container and by the same mechanism as the screenshot harness, and observes it with one
browser page per resolution watching the same live generation, not two separate
generations. It needs an identity: an empty credential pair from every source is a
validation failure here, unlike the screenshot runner.

```
website/observe-chat.sh --prompts collection-exploration --conversations 1
website/observe-chat.sh --prompts all                      # every fixed prompt, run concurrently
website/observe-chat.sh --prompts p1,p2,p3 --no-followup    # skip the second-turn history check
```

Every selected prompt runs as a concurrent conversation, not one after another, so an
overlap claim measures generations that actually ran at the same time. A local generation
uses the CPU model twins. One turn can take several minutes, a Deep Research turn tens of
minutes. The observer never cancels a live generation and never retries a submitted prompt.
A submission failure, or a missed observation deadline, ends that conversation's own
observation and is recorded, and the turn is left running.

Output lands at `website/test_reports/chat_observer/run-<UTC-timestamp>-<pid>/chat/<prompt-name>/`
(gitignored, never wiped, same `latest` symlink convention), with `pre_send.snapshot.txt`,
`<resolution>/interval-NNN-t<seconds>s.png` and matching `.snapshot.txt` at five-second
deadlines, `<resolution>/completion-top.png` / `completion-bottom.png`,
`document_preview.png`, `conversation.json`, `report.md`, and a run-level `chat_index.md`
with the generating-interval column an overlap claim needs. Same six severities and the same
1/2/0 exit-status rule as the screenshot harness, read from `chat_observer.py`'s own exit
code.

## Two single-question diagnostics next to it

`website/tools/count_whoami.py` prints the number of `/api/whoami` requests per navigation, and
`website/tools/check_session_gate.py` reports which of the gate's three states a page settled in.
Both run the same way: `docker cp` into `hoover4-mcp-browser`, then `docker exec`. They
answer questions the screenshot gate cannot: a page that costs three mint-route calls looks
identical to one that costs one, and a gate stuck on *Sign-in required* renders the same
clean page on every route.
