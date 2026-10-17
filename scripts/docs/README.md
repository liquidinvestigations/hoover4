# Check project documentation.

Run these commands from the repository root.
The runner builds a container with pinned Python dependencies.
The default check has no network access and reads the checkout without changing it.

```sh
scripts/docs/run.sh
scripts/docs/run.sh docs/architecture --json
scripts/docs/run.sh test
scripts/docs/run.sh --require-manifests
scripts/docs/run.sh mermaid plans/documentation-renders
```

The default scan uses tracked Markdown paths, including uppercase extensions and project-written vendor inventories.
Explicit file arguments also allow checking a new file before staging.
Use `--templates` to include Markdown templates whose wording can affect model behavior.

## Find a procedure.

- [Read the findings.](#read-the-findings)
- [Render Mermaid diagrams.](#render-mermaid-diagrams)
- [Record feature coverage.](#record-feature-coverage)
- [Publish reviewed screenshots.](#publish-reviewed-screenshots)
- [Check external links separately.](#check-external-links-separately)

## Read the findings.

Errors return exit status 1.
Warnings require review and do not change the exit status.
The JSON output contains source paths, paragraph start lines, rule names, and findings.

| Check | Result |
|---|---|
| Local links and GitHub heading fragments | Missing files, incorrect case, untracked destinations, and missing anchors are errors. |
| Markdown and HTML images | Missing alternative text and missing files are errors. |
| Heading hierarchy | Missing titles, skipped levels, and repeated explicit HTML IDs are errors. |
| Prose | Prohibited wording and leaked tool citation tokens are errors. |
| Editorial patterns | Context-dependent wording and long or rhetorical headings produce warnings. |
| Unlinked paths | Resolvable Markdown path mentions produce warnings. |
| Source and configuration references | Unresolved source paths and INI keys absent from public defaults produce review warnings. |
| Index reachability | Pages unreachable through README or skill links produce warnings. |
| Feature coverage | Missing, repeated, or unknown feature IDs and routes are errors. |
| Screenshots | Incorrect dimensions, layout, provenance, or file hashes are errors. |

The parser excludes front matter, code blocks, inline code, and block quotations from prose matching.
It joins wrapped text and removes emphasis syntax before phrase matching.
Findings identify the paragraph start when a phrase crosses lines.
Exact quotations remain subject to human verification of their source and purpose.

[The ownership file](ownership.json) names preserved upstream text, captured evidence, and generated instructions.
Project-written wrapper documents remain in scope.
Do not use exclusions to hide editable documentation defects.

Rule examples use paired `prose-examples:start` and `prose-examples:end` HTML comments.
Use these regions only in a document that defines the writing rules.
Ordinary prose in those files remains checked.
The edit hook checks added spans and cannot infer every surrounding Markdown construct.
Run the complete check after editing.

The checks do not establish factual correctness or authorship.
Review commands, configuration names, sources, terminology, and every heading against the current implementation.
The configuration check compares fenced INI examples with public default files.
It cannot determine keys accepted dynamically by a parser.
Do not execute command examples as part of link checking.

## Render Mermaid diagrams.

The Mermaid command extracts fenced blocks and renders each with CLI version `11.12.0`.
It preserves an input file, SVG, log, and source-location manifest in the selected output directory.
The renderer has no network access after its image is downloaded.

Inspect diagrams for readable labels and accurate relationships.
A local render does not establish GitHub renderer compatibility.
Use [GitHub's version procedure](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams#checking-your-version-of-mermaid) before claiming compatibility.
Use [Mermaid's format documentation](https://mermaid.js.org/intro/) when selecting a diagram type.

## Record feature coverage.

The checker reads `docs/documentation-coverage.json` when that file exists.
Use `--require-manifests` to require both coverage and screenshot provenance.
Paths inside these manifests are repository-relative.
Documentation paths can include heading fragments.

Each `features` entry needs `id`, `source`, `docs`, and `audience` fields.
The `source` and `docs` fields contain lists of paths.
Audience values are `user`, `admin`, `operator`, or `developer`.
Each feature also needs `screenshot` and `scenario`, or a `no_screenshot_reason`.
Use existing stable feature IDs from [the register](../../docs/technical-specification/Features.md).

The `routes` object maps every declared route string to its documentation destination.
The checker compares it with [the route declaration](../../website/frontend/src/routes.rs).
These manifests record coverage without copying capability descriptions.

## Publish reviewed screenshots.

Use the [capture procedure](../../.agents/skills/driving-the-browser/reference/screenshots.md).
Published full-screen screenshots use the `docs` profile, which captures exactly 1400 by 900 pixels.
The `720p` profile provides optional layout evidence at 1280 by 720 pixels.
Keep layout evidence in the local run directory.

Prepare a local JSON list with `capture`, `image`, and `scenario` paths.
The capture path is relative to the run directory.
The image and scenario paths are relative to the repository.
The following commands preview publication and then copy the selected files.

```sh
scripts/docs/run.sh publish --run website/test_reports/screenshots/latest --mapping plans/screenshot-selection.json
scripts/docs/run.sh publish --run website/test_reports/screenshots/latest --mapping plans/screenshot-selection.json --write
```

The publisher refuses failed runs, incomplete runs, non-viewport captures, and incorrect dimensions.
It writes selected images and public provenance containing hashes, source revisions, dates, and scenario paths.
Review diagnostic warnings and image content before publication.
Run reports can contain private target details and must remain local.

Display each full-screen screenshot with this HTML structure.
Replace the example filename and alternative text with the actual image details.

```html
<a href="img/search.png"><img src="img/search.png" alt="Search results and document preview" align="right" width="560"></a>

<p>The result list shows the selected document.</p>
<br clear="all">
```

Place the image beside its task instructions and clear the float before the next section.
Verify the GitHub rendering at laptop and narrow widths.
The full-size link preserves access to small interface labels.
Register screenshots outside the manual in the same provenance file.

## Check external links separately.

Save a JSON report from the local check, then run the external check on demand.
The command uses two attempts, ten-second request timeouts, and a one-day cache.
It rejects private destinations and keeps network failures separate from confirmed missing pages.
No scheduled job is installed.

```sh
scripts/docs/run.sh --json > plans/documentation-check.json
scripts/docs/run.sh external plans/documentation-check.json --cache plans/documentation-link-cache.json
```

A response of 404 or 410 returns exit status 1.
Other failures are reported as unavailable and require review.
The external command can access the network and write its local cache.
