# The page list, and reading a run

## Format

One section per screenshot in `website/screenshots.ini`. The section name becomes the file
stem, prefixed with its index, so **reordering renumbers everything; append rather than
insert** when you can.

Per section: the path on the site, an optional viewport, an optional settle time, a
full-page flag, and a list of actions, one per line, each a verb and its argument. The verbs
cover navigation, waiting for text or a selector, clicking by text or selector (optionally
scoped to a container), typing into a selector, pressing enter, hovering, scrolling,
sleeping, and evaluating script.

The long encoded segments in the URLs are route parameters written out rather than driven
through the UI, for the reason in the skill: a URL reaches the page in one step.

## Adding a page

1. Append a section rather than inserting one.
2. Give it the smallest action list that reaches the state you want to see. Every action is a
   failure mode.
3. Prefer waiting on text or a selector over sleeping. A sleep that is long enough on a warm
   stack is short enough to flake on a cold one.
4. Run with the `--only` filter on your new section until it passes, then run the whole list.
   A new page can only break the numbering of the ones after it, and that is worth seeing.

## Reading a run

The run's `report.md` names each page with its worst severity and the reason. Two
severities change the exit status; the rest are recorded but do not:

| verdict | exit effect | means |
|---|---|---|
| `application_error` | exit 1 | an error marker on the page, a non-200 response, or an undeclared error bar: read the page, because the backend is probably the cause |
| `incomplete_execution` | exit 2 (unless an application error also occurred) | a failed login, a stopped browser, or a capture that could not be written |
| `diagnostic_warning` | exit 0 | a console error or warning, a failed subresource request, or a request to an outside origin: the message is in the snapshot beside the image, and it is worth reading even on a clean exit |
| `expected_outcome`, `behavioral_warning`, `trace` | exit 0 | a declared negative state, or a category with no producer in this runner yet |

A page that fails by naming a dataset that does not exist is a **fixture** problem, not a code
problem. The list assumes the corpus the end-to-end verification ingests.

The whitelist file beside the harness holds run-wide console exceptions. A whitelisted match
is still a `diagnostic_warning`, only labelled with the rule that excused it; adding an entry
does not hide it from the report, only from ever changing the exit status.

An action that raises leaves `<resolution>/NN-name.FAILED.png`,
`<resolution>/NN-name.FAILED.snapshot.txt` (the rendered DOM at that moment), and
`diagnostics/<resolution>__NN-name.exception.txt` (the full traceback) beside the scenario's
other files, whether or not the run's overall exit status changed.

## Cropping

A full page screenshot is rarely the evidence; the region under discussion is. Crop before
attaching an image to a report, so the reader is looking at the same thing you are.

Any local image tool does this. Store the cropped image **beside the document that
discusses it**, in that document's own folder. Do not leave it in a temporary directory. A finding whose evidence has been deleted is a finding nobody can check.
