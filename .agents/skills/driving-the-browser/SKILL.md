---
name: driving-the-browser
description: Looks at the running site with a real browser. Screenshots, clicking through a flow, checking that a page renders and that its controls do something. Use when asked to "take a screenshot", "check the UI", "does it render", "click through it", "walk the page", "show me the page", "verify the frontend", or before claiming any visible change works. Covers the screenshot harness that gates on console errors, why it does not go through the browser tool server, the two input traps that make typing into this frontend silently do nothing, driving the browser tool server directly when its wrapper drops output, and what a browser acceptance walk is for.
allowed-tools: Bash, Read, Grep, Glob, mcp__hoover4-browser__browser_navigate, mcp__hoover4-browser__browser_snapshot, mcp__hoover4-browser__browser_click, mcp__hoover4-browser__browser_type, mcp__hoover4-browser__browser_press_key, mcp__hoover4-browser__browser_select_option, mcp__hoover4-browser__read_page
---

# Driving the browser

A visible change is claimed on the strength of a rendered page, never on the strength of a
type check. `cargo check` cannot see a hook that traps the runtime, a control that renders and
does nothing, or a page that loads and shows an error card.

## The screenshot harness

```
website/take-screenshots.sh                    # every page in the list
website/take-screenshots.sh --only search      # one subset
```

It walks a list of pages, and per page writes the PNG a person would see, a text outline of
the rendered DOM with the page's verdict, and (where an action failed) the state at the
moment it failed and the diagnostics recorded at that moment, plus an index of the whole
run. Output goes to a gitignored directory. **A run is never wiped**: each one adds a new
`run-<timestamp>-<pid>/` directory and rewrites a `latest` symlink; every earlier run stays
on disk until removed by hand.

**It is a gate, but a console error alone does not fail it.** Six severities, in
`website/tools/capture_screenshots.py`'s own module docstring: `application_error` (a
missing page, a non-200 main document, or an undeclared error marker) and
`incomplete_execution` (a failed login, a stopped browser, a capture that could not be
written) are the only two that change the exit status, 1 and 2. A console error or warning,
a failed subresource request, or a request to an outside origin is `diagnostic_warning`,
which is recorded but never gates the exit status. `expected_outcome` and
`behavioral_warning` also exit 0. Read the run's `report.md` for what was actually seen; a
clean exit status does not mean the run logged nothing.

## The chat observer

```
website/observe-chat.sh --prompts collection-exploration --conversations 1
```

Drives a real chat conversation to completion and observes it with one browser page per
resolution watching the same live generation, sharing the same mechanism and exit-status
rule as the screenshot harness. A local generation runs on the CPU model twins; a turn takes
minutes, and the script never cancels one or retries a submitted prompt. See
`website/tools/chat_observer.py`'s module docstring for the full output shape.

**It is welded to the corpus that the end-to-end verification ingests.** Away from that
corpus its pages fail by naming a dataset that does not exist, which reads as a broken site
and is not. If you see many red lines, check that the fixtures exist before concluding
anything about the code.

**It does not go through the browser tool server**, and that is deliberate rather than an
oversight: that server refuses internal hosts at two independent layers by design, so the
site is unreachable through it. The harness instead copies a standalone driver script into
the browser container and runs a plain browser with neither filter. Nothing about the tool
server's own filtering is relaxed. The container has no bind mounts, so the script goes in
and the images come out by file copy, every run.

## Two input traps

Both make an interaction silently do nothing, which reads as a broken feature.

- **Setting an input's value directly is invisible to the frontend framework.** The write has
  to go through the prototype setter and then dispatch a bubbling input event, or the
  framework's state never changes while the DOM shows the new text.
- **The home box submits on a key press**, so a search has to be triggered with a real key
  event rather than by setting the value and calling submit.

The page list encapsulates both, which is the reason to add a page to it rather than to
hand-roll a one-off script.

## Reaching a page directly

Route parameters on this site are encoded blobs in the URL. Writing the URL out reaches a
page in one step; typing into the home box and waiting for a navigation is three failure
modes to reach the same place. Prefer the URL.

## Using the browser tool server

For exploratory work (reading a page, following a link, filling a form), the browser tool
server is the right surface: navigate, then take an accessibility snapshot, which gives a
reference for every element you can act on.

One quirk worth knowing before you conclude a tool returned nothing: **its wrapper can
present a synthesised structured result and drop the text alongside it.** If a call looks
empty, drive the endpoint directly over its JSON-RPC port before deciding the browser
failed.

## A browser acceptance walk

The one mechanism that finds the defect no document and no type check can: **a control that
exists and does nothing.** Every such defect found in this system was found by a person
clicking.

Walk the control table for the page in `docs/technical-specification/interface/`. For each
row: exercise the control, and confirm the thing it claims to do happens. A control that is
listed and cannot be exercised is either a specification that has gone stale or a control
that has stopped working. Both are findings, and both are worth reporting.

## References

- `reference/screenshots.md`, the page list's format, adding a page, reading a failed run,
  and cropping an image down to the region under discussion.
