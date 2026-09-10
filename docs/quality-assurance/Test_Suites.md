# Test suites

Every suite this tree runs, with its path, its kind, how it runs, and what it
does not cover. Unit-test counts come from the named scripts.

What each check proves is [Running the checks](Running_Checks.md).
Website commands are [Testing the website](Testing_The_Website.md).
The numbered browser cases are [Browser test cases](Browser_Test_Cases.md).

## Contents

- [Unit tests](#unit-tests)
- [Integration tests](#integration-tests)
- [Browser tests](#browser-tests)
- [Static checks](#static-checks)
- [No coverage tooling](#no-coverage-tooling)
- [Remote targets](#remote-targets)

## Unit tests

| suite | path | how it runs | tests | what it does not cover |
|---|---|---|---|---|
| Python unit, worker | `main_services/processing/tests/unit/` | `.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh` | 947 passed, 2 skipped in 6.53 s | Temporal, ClickHouse, Manticore, Garage. Anything that needs `--integration`. |
| Python agents, five images | each MCP server `tests/` plus vendored `tests/shared/` | `.agents/skills/verifying-before-claiming/scripts/pytest-agents.sh` | 587 passed across five images | A stale agent image. Code under `main_services/agents/` is baked in, so a source edit needs a rebuild before this suite tests the new code. |
| OCR-PDF service | `main_services/ocr_pdf/tests/` | `.agents/skills/verifying-before-claiming/scripts/pytest-ocr-pdf.sh` | 19 passed in 0.51 s | The worker pipeline. This image is not `hoover4-worker`. |
| Research agent | `main_services/agents/research_agent/tests/` | `.agents/skills/verifying-before-claiming/scripts/pytest-research-agent.sh` | run the script | The live LLM. `test_agent_interactive_chat` is deselected. The running container has neither pytest nor the tests, so the script mounts the tree over `hoover4-research-agent:local`. |
| Regex entity scanner | `main_services/regex_entity_scanner/tests/` | `main_services/regex_entity_scanner/test.sh` | run the script | The pipeline's Python callers. The script builds an image when the image is missing. |

The agent figure of 587 is five images summed:

| image | tests |
|---|---|
| `hoover4-mcp-browser` | 178 passed |
| `hoover4-mcp-collections` | 161 passed |
| `hoover4-mcp-metasearch` | 129 passed |
| `hoover4-mcp-whois` | 54 passed |
| `hoover4-mcp-todo` | 65 passed |

The two worker skips are the suite's own skips. They are not failures.

## Integration tests

| suite | path | how it runs | what it does not cover |
|---|---|---|---|
| Rust stack | `website/backend/tests/stack_integration.rs` | `website/run-stack-tests.sh` | A non-local `HOOVER4_SITE_URL`. Slow cases (`slow_` prefix) unless `--slow`. Any corpus other than the one `verify-stack.sh` ingests. |
| Pipeline integration | `main_services/processing/tests/integration/` | `docker exec hoover4-worker uv run pytest tests/integration --integration -q` | A run without `--integration` or `HOOVER4_INTEGRATION=1`. Those tests skip. `pytest-unit.sh` does not pass that flag. |
| Whole-stack verification | `main_services/verify-stack.sh` | `main_services/verify-stack.sh` | A non-local website URL. A worker restart mid-run, which kills the script. Cost is tens of minutes, so it is off the per-commit path. |
| Restart resilience | `main_services/verify-stack.sh --restart-resilience` | the same script with that flag, instead of the checks above | The full ingest matrix. It ingests one fixture, restarts the worker, and asserts per-document chunks, vectors, and an index row. |

The stack suite needs a live stack. Every test is `#[ignore]` because they all need that stack, so slowness is a `slow_` name prefix rather than the ignore attribute.
`run-stack-tests.sh` runs `dx check` first.
Cost and the claim table are [Running the checks](Running_Checks.md).

## Browser tests

| suite | path | how it runs | what it does not cover |
|---|---|---|---|
| Screenshot scenarios | `website/browser-tests/*.ini` (140 files) | `website/take-screenshots.sh` | Ingest. A page whose dataset is missing is `incomplete_execution` and does not pass. Other pages still run. |
| Manual QA matrix | `website/tools/manual_qa.py`, `website/browser-tests/procedures/` | `website/run-manual-qa.sh` | Rows you did not select. Use `--select` for a row list and `--skip-chat` when the list has no chat row. |
| Chat observer | `website/tools/chat_observer.py` | `website/observe-chat.sh` | An empty credential pair. This wrapper requires an identity. |

The capture target is `--target`, then `HOOVER4_SITE_URL` in the environment, then
`HOOVER4_SITE_URL` from the login-env file. There is no built-in default.
The numbered catalogue is [Browser test cases](Browser_Test_Cases.md).
The report table is [Capture report format](Capture_Report_Format.md).

These wrappers copy tools into `hoover4-mcp-browser` and run a plain Chromium.
They do not use that container's MCP endpoint, which refuses internal hosts.

## Static checks

These are not test suites. They are the cheap checks that a claim about compile
or hook order requires.

| check | how it runs | what it does not cover |
|---|---|---|
| Rust type check, all targets | `.agents/skills/verifying-before-claiming/scripts/cargo-check.sh` | Server-function bodies compiled only by the dev server. Hook ordering. |
| Frontend hook check | `.agents/skills/verifying-before-claiming/scripts/dx-check.sh` | Runtime behaviour. A clean run prints `No issues found.` |
| Test reachability | `.agents/skills/verifying-before-claiming/scripts/test-reachability.sh` | The tests themselves. It checks that a runner still names each test directory. |

`cargo-check.sh` already passes `--all-targets`. A plain `cargo check` does not
build test binaries.

## No coverage tooling

No `pytest-cov`, `cargo-llvm-cov`, or `tarpaulin` exists in any `pyproject.toml`,
`Cargo.toml`, or script in this repository. This table has no coverage column.
Instrumenting a suite that already runs in seconds would select inside it.
Coverage would answer which code has no test at all. That is a different question.

## Remote targets

The browser wrappers accept a remote `HOOVER4_SITE_URL` or `--target`.
Those wrappers capture a remote site. They do not ingest.

`verify-stack.sh` and the Rust stack suite refuse a non-local target.
The host rules are [Running the checks](Running_Checks.md#remote-targets).
