# Capture and review screenshots.

Use [the capture script](../../../../website/take-screenshots.sh) from the repository root.
It copies the browser tools into the existing browser container and preserves each run in a new output directory.
The container does not need a repository mount.

## Select the capture size.

Use `--resolutions docs` for published screenshots at exactly 1400 by 900 pixels.
Use `--resolutions docs,720p` when a second layout check is needed.
The second profile captures 1280 by 720 pixels and remains local verification evidence.
The default test profiles remain unchanged for existing browser checks.

A scenario's `viewport` setting overrides the selected profile.
Remove that override from a documentation scenario or create a separate scenario when the override tests required layout behavior.
Use viewport PNGs for documentation.
Keep `full_page` images and failure captures in the run evidence.

## Prepare the scenario and fixtures.

Scenario files live in [the browser test directory](../../../../website/browser-tests/Readme.md).
Their numbered filenames determine execution order.
Add scenarios for new controls or states that the manual explains.
Reuse existing navigation, selector waits, and input actions.
Prefer a selector or state wait to a fixed delay.

Verify the configured target, browser container, credentials, and required datasets before starting.
Read private target details from the local infrastructure inventory.
Pass credentials through the environment or `--login-env`.
A target supplied by a login file requires `--remote-target`.
Do not put credential values in command arguments or tracked documentation.

Use `--only` while developing a case, or `--names` for an exact list of scenarios.
Use `--shards 1` for a sequential capture run.
The separate `--dispatch` cases submit server operations.
Select them only when that operation is within the accepted task.

```sh
website/take-screenshots.sh --resolutions docs --shards 1 --only search
```

This example requires target and credential variables to be supplied through the private environment.
The script requires the existing browser service and its configured enablement.
It does not start the stack or ingest missing fixtures.

## Review the report and images.

Each run contains `report.md`, `report.html`, `manifest.json`, PNGs, snapshots, and diagnostics.
The manifest records the source revision, requested dimensions, actual dimensions, and observations.
The `latest` symlink points to the most recent run without deleting earlier runs.

| Result | Required action |
|---|---|
| `application_error` returns 1. | Inspect the failure and correct the cause before publication. |
| `incomplete_execution` returns 2 unless an application error exists. | Supply the missing fixture or correct the interrupted capture. |
| `diagnostic_warning` can return 0. | Read the warning and record its disposition. |
| Other reported observations can return 0. | Verify that the visible state matches the intended example. |

Inspect every image selected for publication.
Verify populated content, completed loading, labels, selected controls, and readable text.
Verify that no credentials, private addresses, or private document content appear.
An exit status alone does not establish these facts.

A failed action preserves a `.FAILED.png`, snapshot, and exception report.
Do not publish those files as successful examples.
Preserve raw reports locally because they can contain private target details and captured model output.

## Publish selected viewport images.

Use [the publication helper](../../../../scripts/docs/README.md#publish-reviewed-screenshots) to copy selected captures and record provenance.
The helper uses a local mapping from capture files to documentation images and scenario paths.
Preview that mapping before using `--write`.
The helper does not crop, resize, or alter the captured image.

Use the same presentation for full-screen screenshots in manuals and other documentation.
Display each image at the available page width near the related task.
Use `width="100%"` without an alignment attribute.
Link the displayed image to its full-size file and provide alternative text.
Place each image between paragraphs.
Verify the rendered page at laptop and narrow widths.
Keep diagnostic crops separate from the published full-screen sequence.
