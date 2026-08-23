# The suites, measured

Every suite this tree carries, how it runs, what it costs, and what it does not cover. The
numbers argue against selecting inside any of them: the fast tier is seconds, and the Rust
suites are compilation-bound, so filtering them still pays the same compile.

## Contents

- [The fast tier](#the-fast-tier)
- [The Rust suites](#the-rust-suites)
- [The slow gates](#the-slow-gates)
- [No coverage tooling](#no-coverage-tooling)

## The fast tier

| suite | how it runs | tests | test time | wall clock |
|---|---|---:|---:|---:|
| Python unit, worker | `.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh` | 919 passed, 2 skipped | 5.85 s | 6.6 s |
| Python agents, five images | `.agents/skills/verifying-before-claiming/scripts/pytest-agents.sh` | 575 passed | 3.1 s summed | 10.3 s |

The agent figure of 575 is five images summed: 177 in `hoover4-mcp-browser`, 150 in
`hoover4-mcp-collections`, 129 in `hoover4-mcp-metasearch`, 54 in `hoover4-mcp-whois`, 65 in
`hoover4-mcp-todo`. Together the two scripts run 1,494 tests in about 17 seconds, counting
the container round trips. That is every Python test in the repository, and it is why
nothing selects inside it.

**What the fast tier does not cover.** Anything requiring Temporal, ClickHouse, Manticore or
Garage. It also does not catch a stale agent image: the code these tests exercise is baked
into each container, so a source edit under `main_services/agents/` needs a rebuild before
the suite tests the new code rather than the old one.

## The Rust suites

| suite | how it runs | tests | test time | wall clock |
|---|---|---:|---:|---:|
| Rust stack integration | `website/run-stack-tests.sh` | 35 passed, 2 filtered | 4.69 s | 1 min 57 s |
| Rust type check, all targets | `.agents/skills/verifying-before-claiming/scripts/cargo-check.sh` | none | none | 10 s warm, 90 s cold |
| Rust scanner battery | `main_services/regex_entity_scanner/test.sh` | 193 functions | not measured | builds an image first if missing |

**The stack suite's 117 seconds of wall clock against 4.69 seconds of test time is
compilation.** `cargo test` builds the whole binary before it runs anything, so filtering
that suite down to one test still pays the same 112 seconds. Nothing selects inside it for
the same reason nothing selects inside the fast tier: the part that costs time is not the
part a selection would skip.

**What the stack suite does not cover.** It needs a live stack, and its slow cases (the ones
waiting on something with its own clock) are skipped by default rather than marked ignored,
because the ignore attribute here already means something else. It is welded to the fixture
corpus the stack ingests. Away from that corpus it fails by naming a dataset that does not
exist, which reads as a broken site and is not.

**What the type check does not cover.** Server-function bodies compiled only by the dev
server, and any hook ordering problem. A plain `cargo check` also does not build test
targets, so a signature change updated everywhere in `src/` can leave the check green while
the test binaries no longer compile; `cargo-check.sh` already passes `--all-targets` to
close that gap.

## The slow gates

These figures are approximate, from `docs/development/Running_Checks.md` and
`.agents/skills/planning-work/reference/estimating.md`, not measured in this pass.

| gate | how it runs | approximate cost |
|---|---|---:|
| whole-stack verification | `main_services/verify-stack.sh` | about 25 min |
| restart resilience | `main_services/verify-stack.sh --restart-resilience` | about 6 min |
| browser acceptance | `website/take-screenshots.sh` | about 23 min |

Each is deliberately off the per-commit path because of that cost, which is why routing
which changes owe one is worth a script. `scripts/gate-map.sh` encodes the routing;
`Running_Checks.md` covers what each gate proves and does not cover.

## No coverage tooling

No `pytest-cov`, `cargo-llvm-cov` or `tarpaulin` exists in any `pyproject.toml`,
`Cargo.toml` or script in this repository, and this table does not carry a coverage column.
That is a decision, not an omission: instrumenting a suite that already runs in seconds
would select inside it, which section [The fast tier](#the-fast-tier) above already argues
against. Coverage would answer a different question, which code has no test at all, and
that question is not this skill's.
