# Design browser tests around state changes

This method defines browser scenarios with explicit state, ordered actions, independent expectations, and retained evidence.
Use [Testing the website](Testing_The_Website.md) for commands and diagnostic outcomes.
The numbered cases are [Browser test cases](Browser_Test_Cases.md).
Use the [browser tools documentation](../../website/tools/Readme.md) for the capture implementation.

## Contents

- [Define the fixture and expected values.](#define-the-fixture-and-expected-values)
- [Select states and ordered transitions.](#select-states-and-ordered-transitions)
- [Wait for observable completion.](#wait-for-observable-completion)
- [Control delayed work.](#control-delayed-work)
- [Exercise input, focus, and appearance.](#exercise-input-focus-and-appearance)
- [Test a PDF source change.](#test-a-pdf-source-change)
- [Test a table dialog.](#test-a-table-dialog)
- [Retain evidence and coverage.](#retain-evidence-and-coverage)
- [Use the scenario template.](#use-the-scenario-template)
- [Review the scenario.](#review-the-scenario)

## Define the fixture and expected values.

Record the fixture revision, dataset, document identity, available sources, and completed ingestion prerequisites.
Use document identities when result order can change.
Keep an unavailable original distinct from a substitute that exercises the same control.
A substitute cannot establish the original document's content expectations.

Define expected values before the browser observes the result.
Use authored source content, a reviewed fixture contract, or an independently derived corpus count.
Record the derivation beside each expectation.
Keep PDF byte pages, parsed text pages, search result pages, and find matches distinct.

State which layer an assertion verifies.
Agreement between an API response and its rendered value verifies presentation consistency.
It does not establish that the API calculated the correct value.
Never obtain both expected and actual values from the response under test.

Start independent cases from known browser and application state.
Keep intentional state transitions inside one scenario.
Restore temporary hooks, media emulation, and test-owned state after failure as well as success.
These isolation rules apply [Selenium's shared-state guidance](https://www.selenium.dev/documentation/test_practices/encouraged/avoid_sharing_state/).

## Select states and ordered transitions.

List the factors that can affect the action.
For a PDF, include source, find query, selected match, viewer readiness, and pending work.
For a tree, include selected path, expanded ancestors, cache freshness, and browser history.
Define the expected state before and after each action.

Preserve the action order from a supplied reproduction.
Entering find text before a source change creates a different transition from opening that source with empty find text.
NIST's [event-sequence testing method](https://www.nist.gov/publications/combinatorial-methods-event-sequence-testing) treats event order as a coverage requirement.

Use pairwise combinations to bound independent configuration factors.
Add required triples for known interactions, such as source, active find, and completion order.
Add explicit ordered sequences after selecting configuration combinations.
Pairwise configuration coverage does not establish ordered-event coverage.
NIST's [higher-strength testing guidance](https://www.nist.gov/publications/practical-combinatorial-testing-beyond-pairwise) supports testing interactions beyond pairs.

Give each stateful case a relevant negative transition and a recovery action.
Examples include an unmatched query, reversed date bounds, an empty table filter, or a missing saved entity.
Verify the declared negative state before applying recovery.
Avoid combining unrelated invalid inputs in one assertion.

## Wait for observable completion.

Give each transition a readiness condition and a bounded deadline.
Locate replaced elements again while waiting.
Document readiness alone does not establish that a dynamic control is ready.
This follows [Selenium's waiting guidance](https://www.selenium.dev/documentation/webdriver/waits/).

Wait for the requested identity, expected data, and usable control together when all three define completion.
A PDF element can exist before its controller or highlight is ready.
A source label can change before its bytes and search results change.
A fixed sleep provides no evidence that these operations finished.
Before Back or another reversing action, wait for the intermediate component state to finish rendering.
A changed URL or selected-row marker can precede the tree update that the next action would cancel.

## Control delayed work.

Identify the old request or controller before replacing its state.
Hold that work while the new state finishes loading.
Release the old work after the current source becomes usable.
Verify that the old completion cannot change current data, selection, navigation, or focus.

Hold only the intended old operation.
Do not block the current operation and then accept a source label as completion.
Record that the delayed operation started and how it completed or was cancelled.
Restore interception and release pending work during cleanup.
The [CDP Fetch domain](https://chromedevtools.github.io/devtools-protocol/1-3/Fetch/) supports explicit request suspension and continuation.

## Exercise input, focus, and appearance.

Use the Dioxus-aware text input helper and actual keyboard events.
Use pointer events at visible target coordinates for modal and overlay interactions.
Verify the hit target before the click.
A programmatic DOM click can activate an obscured control that a person cannot reach.

Verify keyboard operation and visible focus for each relevant transition.
Include a narrow viewport when controls depend on available width.
The applicable requirements come from [WCAG keyboard, focus, and reflow criteria](https://www.w3.org/TR/WCAG22/).
Test wide data content separately from the controls that must remain reachable.

Exercise affected controls under both browser color preferences.
For the application's fixed light palette, assert computed foreground, background, border, and backdrop colors.
Verify geometry while an overlay remains open during a viewport change.
The [CDP Emulation domain](https://chromedevtools.github.io/devtools-protocol/1-3/Emulation/) supplies viewport and media controls.

## Test a PDF source change.

Use a fixture with independently known source identities, page bounds, and find results.
Include a source pair with different bytes or positions when verifying source-specific search.

1. Open the original PDF and wait for its rendered content.
2. Enter a known find query.
3. Verify its exact count, selected result, and rendered highlight.
4. Select another PDF source while a result remains active.
5. Verify the new source identity, its page bounds, and retained query.
6. Verify its own results and rendered highlight.
7. Navigate to another result and verify the changed selection and position.
8. Return to the original source and verify its own results again.

Run a separate controlled-delay variant with the old search completing after the replacement source is ready.
Also exercise leaving PDF for text, returning to PDF, and navigating away during an open request.
Run the source-order variants with the same document and query to expose an incorrect cache key.
Verify preview and full-viewer behavior independently.

## Test a table dialog.

Use known cells and a column filter with an exact expected result.
Record the dialog's opening control before activating it.

1. Open the column dialog with a pointer event.
2. Verify one named modal, centered geometry, opaque content, and initial focus.
3. Use Tab and Shift+Tab to verify focus containment.
4. Click the backdrop where another column trigger is covered.
5. Verify closure without activation of the covered control.
6. Click the uncovered trigger to open the other dialog.
7. Press Escape and verify focus returns to the opening control.
8. Reopen the filter dialog and apply a known filter.
9. Verify closure and the exact visible cells.

Verify that content clicks retain the modal and that background controls remain inactive.
These focus and background rules follow the [WAI-ARIA modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/).
Repeat the affected geometry and palette assertions under both browser color preferences.

## Retain evidence and coverage.

Start console, exception, and request observation before the tested action, including in every newly opened tab.
Record each step's initial state, action, expected value, observed value, and completion event.
Save the failure screenshot, DOM snapshot, diagnostics, and partial results when an assertion fails.
Capture the active controller and component state before a later scenario navigates away from the failed state.
An image supports appearance review but cannot prove a prior transition or request bound.

Preserve the harness's documented diagnostic severities.
Use explicit semantic assertions for required behavior.
Keep unrelated console warnings visible without changing their global outcome rule.
Record an expected negative state separately from an unexpected application failure.

Report missing fixtures, missing expectations, and unexecuted cases separately from passing behavior.
Verify that the selected case set is nonempty and covers every required baseline and variation.
A case name in a manifest is not execution evidence.
For a chat scenario, record an actual submitted turn and its completion or failure.
Reuse the same completed conversation for additional viewport observations when another generation adds no required coverage.

## Use the scenario template.

| Field | Required content |
|---|---|
| Purpose | State the behavior and defect mechanism that the scenario verifies. |
| Fixture | Name its provenance, revision, identity, source variants, and preparation command. |
| Expectations | Record each expected value and its independent derivation. |
| Initial state | Define the route, selection, controls, browser preferences, and pending work. |
| Sequence | List ordered actions with readiness conditions and deadlines. |
| Assertions | Name the identity, count, value, order, focus, geometry, or request bound after each action. |
| Variations | List selected configurations, required event orders, and one relevant negative transition. |
| Recovery | Define the action that restores a usable state. |
| Cleanup | Restore hooks and preferences and close test-owned tabs on every outcome. |
| Evidence | Name the step records, images, snapshots, diagnostics, and partial-output locations. |
| Coverage | Map each required behavior to its procedure and actual execution outcome. |

## Review the scenario.

- Verify that the fixture and expected values exist before the run.
- Verify that assertions detect the stated failure mechanism.
- Verify that selected state is supported by changed data or rendered behavior.
- Verify that delayed work cannot prevent the current operation from completing.
- Verify that keyboard and pointer actions follow reachable user paths.
- Verify that every required variation has an executable procedure and an observed outcome.
- Verify that failures retain evidence and that cleanup also runs after a failed assertion.
- Verify that the served code matches the source being evaluated.
