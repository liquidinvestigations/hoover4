# Capture report format

Each screenshot run writes a table, one row per scenario. The four verdict
words are PASS, FAIL, WARNING, and INCOMPLETE. INCOMPLETE rows sort last.

The six recorded severities stay in `manifest.json`. An unknown severity raises
`ValueError`. It does not become PASS.

See [Testing the website](Testing_The_Website.md) for commands and exit status.
See [Browser test cases](Browser_Test_Cases.md) for the numbered rows.

## Contents

- [Verdict mapping](#verdict-mapping)
- [Report columns](#report-columns)
- [Where the artefacts land](#where-the-artefacts-land)
- [How a person uses the report](#how-a-person-uses-the-report)

## Verdict mapping

| recorded severity | report word |
|---|---|
| `application_error` | FAIL |
| `expected_outcome` | PASS |
| `trace` | PASS |
| `behavioral_warning` | WARNING |
| `diagnostic_warning` | WARNING |
| `incomplete_execution` | INCOMPLETE |
| none, empty, or `ok` | PASS |

`application_error` is an unexpected missing page, a non-200 main document, or an undeclared error marker.
`expected_outcome` is a negative state the scenario declared with `expect`.
`trace` is a count or a selected document that differs from an earlier run.
`behavioral_warning` is a find term with no match, or a control with no observable effect.
`diagnostic_warning` is a console error or warning, a failed subresource, or a request to an outside origin.
`incomplete_execution` is a missing fixture, a failed login, a stopped browser, a capture that could not be written, or a capture shard that did not finish.

Exit status still follows the severities. `application_error` exits 1.
`incomplete_execution` exits 2 when no application error also occurred.
The other four severities exit 0.

## Report columns

The markdown report and the HTML report share one table.

| column | content |
|---|---|
| slug | the scenario file stem, such as `001-home` |
| summary | the `summary` field from the scenario file |
| verdict | PASS, FAIL, WARNING, or INCOMPLETE |
| images | each PNG as an HTML `img` of width 500, inside a link to the original file |
| snapshot | a relative link to the matching `.snapshot.txt`, when that file exists |

Every `href` and `img src` is relative to the run directory.
The HTML file adds verdict CSS classes and `img { width: 500px; height: auto; }`.

The totals list above the table still counts the six recorded severities, plus the process exit status.

## Where the artefacts land

Default output is `website/test_reports/screenshots/`, gitignored, never wiped.
Each run adds `run-<UTC-timestamp>-<pid>/` and rewrites `latest`.

Inside the run directory:

| artefact | holds |
|---|---|
| `report.md` | the markdown table |
| `report.html` | the same table as HTML |
| `manifest.json` | per-page recorded severity, slug, summary, and the six-severity totals |
| `image_inventory.json` | every PNG path, with review state starting as `unreviewed` |
| `<resolution>/NN-name.png` | the pixels at that size |
| `<resolution>/NN-name.snapshot.txt` | the rendered DOM outline |
| `diagnostics/` | console and network records per capture |

One level up, `index.md` points at the latest run's `report.md`.

## How a person uses the report

Open the HTML report or the markdown report. Read FAIL rows first, then WARNING, then PASS.
INCOMPLETE rows sit at the bottom. They did not run, so they are not failures of the page.

Click the image to open the original PNG. Open the snapshot link for the DOM outline.
Review state in `image_inventory.json` is separate from the verdict.
Marking a PNG reviewed does not change PASS, FAIL, WARNING, or INCOMPLETE.
