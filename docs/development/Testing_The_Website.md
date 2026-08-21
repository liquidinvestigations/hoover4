# Testing the website

The suites, what each one covers, and the two diagnostics beside them. What each check does
*not* cover is [Running the checks](Running_Checks.md).

| what | how |
|---|---|
| unit (Rust) | `cargo test --offline` inside `hoover4-website` — Rust is not on `$PATH` there, so `export PATH=/usr/local/cargo/bin:$PATH` first |
| hook order | `dx check --package frontend` inside `hoover4-website`; `website/run-stack-tests.sh` and `website/development.sh` both run it first |
| live stack | `website/run-stack-tests.sh` (fast only), `./run-stack-tests.sh --slow` (everything) |
| whole stack | `main_services/verify-stack.sh` |
| screenshots | `website/take-screenshots.sh` |

**The stack tests are split by NAME, not by attribute.** Every test in
`website/backend/tests/stack_integration.rs` is `#[ignore]` already, because they all need a live
stack, so `#[ignore]` cannot also mean "slow". The ones that wait on something with its own
clock — the 30 s shard-state cache, a ClickHouse mutation — carry a `slow_` prefix and are
skipped by default. Every other test asserts its own wall time against
`HOOVER4_STACK_TEST_BUDGET_MS` (5 s), which is what notices when an endpoint quietly starts
doing a full scan: without it a test that grows from 0.3 s to 9 s still passes.

**`dx check` runs before the suite because it is the only thing that catches a conditional
hook.** Such a hook traps the WebAssembly runtime on the render that adds it, leaving the
page painted and completely inert — a failure `cargo check` cannot see and the release build
reports only as `RuntimeError: unreachable`. See
[`website/frontend/README.md`](../../website/frontend/README.md).

**`cargo check` does not build test targets, so it cannot see a broken test binary.** A
signature change updated at every call site in `src/` leaves `cargo check` clean and
`cargo test` unable to compile, and nothing between the two says so — the tests do not fail,
they never get built. `cargo check --workspace --tests` (fast) or `cargo test --no-run`
(slower, and produces the binaries) is what closes that gap; run one of them alongside
`cargo check` whenever a public signature moves.

**Both fixture-driven suites are welded to the corpus `main_services/verify-stack.sh`
ingests** — `website/screenshots.ini`'s routes and `stack_integration.rs`'s `TESTFILES`, `SHAPES`,
`ZIPS` and `other`. On any other corpus they fail by naming a dataset that does not exist,
which reads as a broken page or a broken endpoint and is neither. Run `verify-stack.sh`
before either of them, or read their failures as a missing precondition rather than a
regression.

## Screenshots

`website/take-screenshots.sh` walks `website/screenshots.ini` and writes a PNG, a text snapshot of the
rendered DOM and any console errors per page into `website/test_reports/screenshots/` (gitignored,
wiped each run), plus a `report.md` index.

It does **not** use the browser MCP endpoint. `hoover4-mcp-browser` refuses internal hosts
at two independent layers by design — a deny-list in `urlcheck.py` and a PAC script handed
to Chromium in `netfilter.py` — so `hoover4-website` is unreachable through it. The script
copies `website/tools/capture_screenshots.py` into that container and runs a plain Chromium with
neither filter, touching nothing about the MCP server's own behaviour. The container has no
bind mounts, so both the script and the output travel by `docker cp`.

Two traps the script exists to encapsulate: setting an input's `.value` is invisible to
Dioxus unless you go through the prototype's setter and dispatch a bubbling `input` event,
and the home box submits on `onkeypress`, so Enter has to be a real CDP key event. The long
base64 segments in the ini are CBOR route parameters (`website/frontend/src/data_definitions/url_param.rs`);
`9g==` is `None`.

## Two single-question diagnostics next to it

`website/tools/count_whoami.py` prints the number of `/api/whoami` requests per navigation, and
`website/tools/check_session_gate.py` reports which of the gate's three states a page settled in.
Both run the same way — `docker cp` into `hoover4-mcp-browser`, then `docker exec`. They
answer questions the screenshot gate cannot: a page that costs three mint-route calls looks
identical to one that costs one, and a gate stuck on *Sign-in required* renders the same
clean page on every route.
