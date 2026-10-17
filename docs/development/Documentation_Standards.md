# Write current technical documentation.

Apply these rules to project Markdown, comments, docstrings, and product text.
[AGENTS.md](../../AGENTS.md#how-to-write) defines the vocabulary and sentence rules.
Use Simplified Technical English and the plain-language principles stated there.

## Describe current behavior.

Verify each claim against its source, inputs, and applicable configuration.
State prerequisites, actions, outputs, failure behavior, and limits that affect the reader's task.
Keep implementation history and proposals in local plans.
Tracked documentation must not depend on local planning files.

Preserve the operational fact when removing an account of an earlier defect.
For example, describe how a blocking call prevents activity progress while heartbeats continue.
Do not retain a deployment anecdote as a general performance claim.

Keep private infrastructure details in the local, gitignored `INFRASTRUCTURE_INVENTORY.md`.
Do not publish real target addresses, credentials, or deployment access details.
Capture provenance can contain public source revisions, dates, scenario paths, and image hashes.
Keep raw run reports local when they contain private deployment information.

## Use direct headings and sentences.

A heading must identify the section's subject or state its action.
Remove metaphors, theatrical phrasing, reader reassurance, and claims about the importance of information.
Delete a clause when its removal preserves every technical fact and instruction.
Use the same term for the same concept throughout the documentation.
Read [the terminology register](../../CONTEXT.md) before introducing a term already defined there.

Review all headings, including headings without a prohibited phrase.
Review context-dependent warnings manually.
Update contents lists and incoming section links when a heading changes.
The checks identify writing defects without establishing who wrote the text.

## Place information beside its owner.

| Information | Destination |
|---|---|
| Directory contents and local contracts | Use the README beside the code. |
| Subsystem components and interactions | Use [architecture pages](../architecture/Readme.md). |
| User and administrator procedures | Use the appropriate [manual](../user-manual/Readme.md). |
| Operator procedures | Use [operations documentation](../operations/Readme.md). |
| Development procedures | Use [development documentation](Readme.md). |
| Verification procedures and coverage | Use [quality assurance documentation](../quality-assurance/Readme.md). |
| Agent procedures | Use the relevant skill. |
| Editing constraints | Use the applicable repository rule. |
| Product capabilities | Update the [feature register](../technical-specification/Features.md). |

Read the documentation beside affected code before changing its behavior.
Correct documentation made false by the change.
A documentation review can cover additional pages when the requested scope includes them.

## Link references and explain diagrams.

Link surrounding documentation and repository paths when the reader needs to open them.
Use relative links with descriptive labels.
Keep private inventory references as inline code because the file is not published.
Add a contents list when a page exceeds approximately 100 lines.

Use Mermaid where a relationship, sequence, state, or data structure benefits from a diagram.
Keep diagrams small enough to explain one documented contract.
Verify each relationship against the current implementation.
Do not create quantities, dates, or satisfaction scores to fill a diagram type.
Keep a written explanation beside each diagram.

## Capture reproducible screenshots.

Use the [screenshot procedure](../../.agents/skills/driving-the-browser/reference/screenshots.md).
Published full-screen screenshots measure 1400 by 900 pixels.
Display them at 560 pixels wide, aligned right, with descriptive alternative text and a link to the original image.
Clear each float before the next section.
Record the source revision, scenario, capture date, and file hash in the public provenance manifest.

## Write comments that explain a contract.

Describe units, invariants, failure behavior, or decisions that the identifier and type cannot explain.
Remove commented-out code.
Keep proposed work and implementation history out of comments.
Update affected comments in the same patch as the behavior they describe.
Do not change an applied migration, including its comments.

Do not generate filler to satisfy a missing-documentation lint.
Report items where the identifier and type already state the complete contract.
Use [the lint procedure](../../.agents/skills/writing-project-docs/reference/lint-honesty.md) for these cases.
Comment density does not establish documentation quality.

## Run the applicable checks.

Use [the documentation tools](../../scripts/docs/README.md) for links, headings, prose, diagrams, coverage, and screenshot records.
The edit hook rejects prohibited wording in added spans.
The complete Markdown check also inspects paragraph context and file relationships.
A passing check does not establish factual accuracy or adequate coverage.

Review quoted examples, generated text, and upstream material according to their ownership.
Correct generated documents through their source when appropriate.
Preserve captured evidence as the record of the original output.
