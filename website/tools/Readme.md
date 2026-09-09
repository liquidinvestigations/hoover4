# Website diagnostics

These tools prepare fixtures, drive browser workflows, and write verification evidence.

| script | answers |
|---|---|
| `capture_screenshots.py` | drives a plain browser over a page list and writes a PNG, a DOM text snapshot and console errors per page |
| `capture_credentials.py` | reads `HOOVER4_TEST_USERNAME` and `HOOVER4_TEST_PASSWORD` from the process environment, and writes the image inventory default |
| `capture_credentials.sh` | sourced by the capture wrappers after the login file path is set |
| `chat_observer.py` | drives a chat conversation to completion and writes its screenshots, DOM snapshots and history checks; imports its browser helpers from `capture_screenshots.py` rather than copying them |
| `count_whoami.py` | how many identity requests one navigation costs |
| `check_session_gate.py` | which of the session gate's three states a page settled in |
| `console_whitelist.txt` | console messages the screenshot run treats as expected |
| `manual_qa.py` | validates fixtures, selects cases, and combines procedure evidence |
| `manual_qa_runtime.py` | executes the manual interactions and records each assertion |

All of them run by copying the script into the browser container and executing it there; the
container has no bind mounts, so both the script and its output travel by file copy. They do
not use the browser MCP endpoint, which refuses internal hosts by design.

Screenshot scenarios can use `pointer_click_css`, `press_key`, and `wait_eval` for CDP
input and bounded assertions. Set `color_scheme` to `light` or `dark` before navigation.
Use `history_back` and `history_forward` to navigate actual browser history entries.
Each scenario writes a steps JSON file with input, starting URL, observed values, and API request counts.
An optional `init_script` runs before the scenario's document loads and does not affect later documents.
Scenario navigation waits for a new document and application mount before it performs an action.
The cache regression fixes the browser clock during warm navigation, then advances it six seconds to verify expiry.
The file retains completed steps and the failing action when a later assertion fails.
Failed manual phases also retain the current PDF registry, viewer generation, source, and resource timings before another phase navigates.
Both browser entry points use `browser_lifecycle.py` for bounded startup and awaited process cleanup.
Chromium writes process diagnostics to `chromium.log` in the run output.

Run the capture-driver tests in the browser container.

```sh
docker exec hoover4-mcp-browser mkdir -p /tmp/capture-tests
docker cp website/tools/. hoover4-mcp-browser:/tmp/capture-tests/
docker cp website/screenshots.ini hoover4-mcp-browser:/tmp/capture-tests/screenshots.ini
docker exec -w /tmp/capture-tests hoover4-mcp-browser python3 -m unittest test_capture_screenshots -v
```

Run the browser lifecycle tests in the same container.

```sh
docker cp website/tools/browser_lifecycle.py hoover4-mcp-browser:/tmp/capture-tests/
docker cp website/tools/test_browser_lifecycle.py hoover4-mcp-browser:/tmp/capture-tests/
docker exec -w /tmp/capture-tests hoover4-mcp-browser python3 -m unittest test_browser_lifecycle -v
```

## PDF viewer lifecycle

Run the PDF lifecycle tests in the browser container.
The tests control pending initialization and verify disposal counts and stale layout callbacks.

```sh
docker exec hoover4-mcp-browser mkdir -p /tmp/pdf-lifecycle-tests
docker cp website/tools/test_pdf_viewer_lifecycle.cjs hoover4-mcp-browser:/tmp/pdf-lifecycle-tests/test.cjs
docker cp website/frontend/assets/embed-pdf/_viewer/embed-pdf.js hoover4-mcp-browser:/tmp/pdf-lifecycle-tests/viewer.js
docker exec -e PDF_VIEWER_SCRIPT=/tmp/pdf-lifecycle-tests/viewer.js hoover4-mcp-browser node --test /tmp/pdf-lifecycle-tests/test.cjs
```

## Manual QA fixtures

Run `website/tools/prepare_manual_qa.sh` from the repository root.
The script prepares `testdata_manualqa`, `testdata_excelsc`, `testdata_wide`,
`testdata_leaf`, and `testdata_diskfiles` through disk ingestion.
It writes local document identities, source rows, PDF rows, table rows, and image OCR rows to `website/test_reports/manual_qa_fixtures.json`.

`manual_qa_fixtures.json` is the tracked logical contract.
Each entry identifies its source, dataset, original or substitute state, and expected values.
The resolved profile is ignored because it contains local ingestion results.
Its independent expectations include source metadata, raw relevance scores, original email bytes, and DOCX entity occurrences.
It also records the source revision, copied-file identities, and email envelope and attachment expectations from the original source bytes.
Document identifiers use SHA3-256. Provenance also records SHA-256.
The preparation command rejects a copied file that differs from its source.

The profile also reads `testdata_manualpdf`, which contains one original-only PDF.
Its separate ingestion requires the global PDF provider set to `none`, then restoration of the prior provider.
Ordinary preparation writes its source bytes but does not rescan this dataset under an OCR-enabled provider.
Run `website/run-stack-tests.sh --slow slow_qa_pdf_sources` to verify PDF bytes, source-specific search, both source orders, and permissions.

The profile command returns one when a required fixture is unmet.
`--discover-only` reads indexed identities and operation rows without ingest, rescan, or
recovery. Use it for a remote profile. `--profile-only` writes the local resolved profile
from already prepared sources. Use `--observe-incomplete` only to record an incomplete
local profile without a failure status.
Each invocation moves the previous profile to `manual_qa_fixtures.previous.json` before contacting the worker.
A failed refresh cannot leave that profile at the current result path.
The worker log includes captured command output when ingestion fails.

## Manual QA browser matrix

Interrupted capture wrappers stop only their owned container runner before collecting partial evidence and removing temporary files.
The runner cancels its active task and awaits Chromium cleanup.

Run `website/run-manual-qa.sh` after the fixture profile reports each required fixture as verified.
The command writes `manual-qa-plan.json` beside the capture evidence.
It rejects an empty or unknown case selection.
It records unmet prerequisites and continues the runnable cases.
The observer runs one collection-exploration conversation and its follow-up.
Use `--select 6,18` to run named rows.
Use `--skip-chat` to omit generation. A selected chat case then remains incomplete.
The capture wrapper accepts `--names name-a,name-b` for an exact scenario list.
Each procedure writes its expected result, input steps, observations, request counts, screenshots, and DOM snapshots.
An assertion failure retains earlier evidence and does not prevent the later procedures from running.
The combined `manual-qa-results.json` reports each baseline and variation at each resolution.
An absent or unfinished procedure cannot pass.

The chat observer compares persisted assistant text across reload and navigation.
Use `website/observe-chat.sh --history-only /ai_chat/c/SESSION/9g==/9g==` to verify an existing conversation without submitting a prompt.
The history-only result records no new submission.
The regular observer verifies reload and return navigation at each requested viewport size.
The combined manual result requires successful history evidence for that size.

The optional ignored `website/test_reports/manual_qa_original_cases.json` supplies original corpus expectations that cannot be generated locally.
Its `mail_page_return` object contains `document` with `collection_dataset` and `file_hash`, a one-based `result_ordinal`, and the independently verified `source_sha256`.
The procedure searches for `hoover`, navigates result pages, verifies the exact ordinal, and tests 21 document hits and popup return.
An absent original-case profile remains an unmet prerequisite.

Run the matrix module tests in the browser container.

```sh
docker exec hoover4-mcp-browser mkdir -p /tmp/manual-qa-tests
docker cp website/tools/manual_qa.py hoover4-mcp-browser:/tmp/manual-qa-tests/
docker cp website/tools/test_manual_qa.py hoover4-mcp-browser:/tmp/manual-qa-tests/
docker exec -w /tmp/manual-qa-tests hoover4-mcp-browser python3 -m unittest test_manual_qa -v
```

Run the fixture tests in the worker container.

```sh
docker exec hoover4-worker mkdir -p /tmp/manual-qa-tests
docker cp website/tools/prepare_manual_qa.py hoover4-worker:/tmp/manual-qa-tests/
docker cp website/tools/prepare_manual_qa.sh hoover4-worker:/tmp/manual-qa-tests/
docker cp website/tools/test_prepare_manual_qa.py hoover4-worker:/tmp/manual-qa-tests/
docker exec -w /tmp/manual-qa-tests hoover4-worker uv run --project /app python -m unittest test_prepare_manual_qa -v
```

## Local test login inputs

Agents can read `../TEST_LOGIN.env` for a browser work package.
The file stores the login URL, site URL, username, and password.
Copy `../TEST_LOGIN.env.example` to create it.
The repository ignores the account file. The example contains empty values.
`../take-screenshots.sh` and `../observe-chat.sh` load the file automatically, beside a
`HOOVER4_TEST_USERNAME`/`HOOVER4_TEST_PASSWORD` environment pair that takes precedence
over it. Credential values are not accepted as `--username` or `--password` arguments.
Neither wrapper reads a target from this file; a target comes from `--target`,
`HOOVER4_SITE_URL`, or the built-in local default.
