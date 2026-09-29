---
name: writing-project-docs
description: Update repository documentation, comments, and docstrings when their described behavior changes.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Writing project documentation

Read the documentation beside the affected code.
Update the contract made false by the change and keep unrelated prose unchanged.
Use the shared writing rules in `AGENTS.md`.

Describe current behavior, inputs, outputs, failure behavior, and non-obvious constraints.
Do not add a comment that only restates the next line of code.
Choose a structure that helps the reader find and act on the information.

Keep working history and future proposals in the plan.
Tracked documentation uses durable public references and contains no private infrastructure details.
A capability change updates its technical-specification row in the same patch.

An applied migration is immutable, including its comments.
Put a correction beside its reader or in a new migration when the behavior requires one.

Do not fill missing documentation with guessed explanations.
Use [the lint guidance](reference/lint-honesty.md) when a documentation lint reports missing descriptions.
