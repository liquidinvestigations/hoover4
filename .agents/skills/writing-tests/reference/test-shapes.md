# Tests for changed behavior

Prefer assertions on behavior a caller depends on.
Use independent expected values and cases that reproduce the actual failure.
A test that recomputes the implementation can repeat its defect.

Mock dependencies when isolation helps expose the relevant behavior.
An internal helper can be a valid test target when it owns a meaningful contract.
Do not change the public API only to avoid testing an internal function.

Inspect storage or diagnostics when they are part of the behavior under test.
A log line alone cannot establish that a user-facing operation completed.

Use integration checks for service contracts and browser checks for controls.
Use a real model case when acceptance depends on its tool choice or answer quality.
Keep these claims distinct from deterministic unit results.
