---
name: driving-the-browser
description: Verify a rendered page and its controls with the repository browser harness, or inspect an external page with browser tools.
allowed-tools: Bash, Read, Grep, Glob, mcp__hoover4-browser__browser_navigate, mcp__hoover4-browser__browser_snapshot, mcp__hoover4-browser__browser_click, mcp__hoover4-browser__browser_type, mcp__hoover4-browser__browser_press_key, mcp__hoover4-browser__browser_select_option, mcp__hoover4-browser__read_page
---

# Driving the browser

Use `website/take-screenshots.sh` for rendered-page checks.
Select the affected cases with its `--only` option.
Use `website/observe-chat.sh` for a real chat conversation and preserve the run report.

Verify required fixtures before interpreting failures.
Read the report and captured output, including diagnostic warnings.
The screenshot harness distinguishes application failures from expected outcomes and warnings.
A successful exit alone does not establish that every diagnostic is harmless.

Exercise the changed controls and verify their effects.
A type check cannot establish that an interaction works.
Consult the affected interface specification when selecting the walk.

The internal-site harness uses its own browser driver because the product browser tool filters internal destinations.
Do not weaken those filters to test the website.
The browser container can require script and artifact copies because it has no repository mount.

Set input through its prototype setter and dispatch a bubbling input event when driving the DOM directly.
Use a real key event for controls that submit on key press.
Prefer an existing harness interaction to duplicating those details.

For external exploration, navigate and read the accessibility snapshot before acting.
If a tool wrapper drops result text, inspect the underlying response before declaring the page empty.
Read [screenshot procedures](reference/screenshots.md) when adding or diagnosing a case.
