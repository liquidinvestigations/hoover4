# The page list, and reading a run

## Format

One section per screenshot in `website/screenshots.ini`. The section name becomes the file
stem, prefixed with its index — so **reordering renumbers everything; append rather than
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
4. Run with the `--only` filter on your new section until it passes, then run the whole list —
   a new page can only break the numbering of the ones after it, and that is worth seeing.

## Reading a failed run

The run's index names each page with its verdict and the reason. Three failure kinds, and
they mean different things:

| verdict | means |
|---|---|
| an error marker on the page | the site rendered its own failure card — read the page, the backend is probably the cause |
| a non-200 response | the route did not resolve, or the server is not answering |
| an uncovered console error | something threw in the client; the message is in the snapshot beside the image |

A page that fails by naming a dataset that does not exist is a **fixture** problem, not a code
problem. The list assumes the corpus the end-to-end verification ingests.

The whitelist file beside the harness holds run-wide console exceptions. Adding to it is a
decision: an entry hides that error on every page, forever.

## Cropping

A full page screenshot is rarely the evidence; the region under discussion is. Crop before
attaching an image to a report, so the reader is looking at the same thing you are.

Any local image tool does this. What matters is that the cropped image is stored **beside the
document that discusses it**, in that document's own folder, not left in a temporary
directory — a finding whose evidence has been deleted is a finding nobody can check.
