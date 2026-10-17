---
name: writing-project-docs
description: Update repository documentation, comments, and docstrings when their described behavior changes.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Writing project documentation

Read the documentation beside the affected code.
Update the contract made false by the change and keep unrelated prose unchanged.
Use the shared writing rules in [AGENTS.md](../../../AGENTS.md).
Read [the documentation checks](../../../scripts/docs/README.md) before changing Markdown.

Link file references that readers need to open.
Review every affected heading for a direct subject or instruction, including headings that pass the phrase check.
Remove claims about importance, reader reassurance, and repeated conclusions that add no technical fact.
Update incoming section links when headings change.

Use Mermaid for relationships that a diagram explains better than prose alone.
Verify diagram content against current code before rendering it.
Use the browser skill for screenshots and retain their provenance.
Keep user procedures separate from administrator procedures.

Run [scripts/docs/run.sh](../../../scripts/docs/run.sh) on affected Markdown, then inspect the complete report before completing a documentation review.
Inspect warnings in context and preserve exact quotations and upstream text according to their ownership.
The checker does not determine factual accuracy or authorship.

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
