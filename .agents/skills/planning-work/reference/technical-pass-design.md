# Technical pass design

A technical prompt carries enough detail for an executor to implement its tasks without choosing the architecture again.
Scale the detail to the work. A literal rename needs less design than a new interpreter.

## Resolve decisions before writing the design

Ask about architecture choices before developing the affected design.
Separate facts read from code, source-backed findings, user decisions, and proposed implementation details.
Keep unanswered choices out of executable work packages.
Continue work that does not depend on the answer.

## Describe the implementation

| area | information the executor needs |
|---|---|
| Ownership | Name files and symbols to create or change. Name shared files and their owner. |
| Current behavior | Cite source paths and symbols. State which defects affect the task. |
| Interfaces | Give signatures, field types, units, valid values, ownership, and lifecycle. |
| Algorithms | Give ordered steps, invariants, tie rules, stopping conditions, and complexity where relevant. |
| State | Define initialization, transitions, persistence, reset, retry, and recovery. |
| Data | Give schemas, identifiers, version rules, ordering, and migration behavior. |
| Integration | Name each caller, host, registry, build artifact, and documentation row that moves with the change. |
| Failure behavior | State observable errors and recovery. Preserve approved behavior and its conditions. |

Use a shared design document when several passes depend on the same interface.
Link to its exact section from each prompt.
Keep all implementation-critical information outside disposable research folders.
Extract useful findings and check their primary sources before treating them as requirements.

## Connect evidence to decisions

Give direct links to papers, specifications, or upstream source files.
Name the relevant section, equation, table, or symbol.
Explain which part the implementation uses and which experimental conditions limit the result.
Separate an adaptation from a reproduction of a published algorithm.
Do not transfer performance claims between datasets, opponents, or scoring methods.

## Show difficult operations

Include short examples for operations that an executor could reasonably misimplement.
Useful examples include boundary conversion, incremental updates, observation masking, and state recovery.
State whether each example is executable code or pseudocode.
Give its input, expected output, and omitted integration work.
Avoid full implementations that obscure the interface or duplicate source files.

## Define acceptance

Each task names a check and the behavior that check proves.
Give normal, boundary, and failure cases where each protects a relevant invariant.
Expected results come from the requirement, a hand calculation, or an independent reference.
Name runtime checks when compilation cannot prove the behavior.

Distinguish existing commands from commands the pass creates.
For a new command, specify its arguments, outputs, exit status, runtime environment, and timeout.
State dependencies that must exist before it runs.
Do not present a planned command as a check already available in the tree.

## Report actual outcomes

The report links each task to changed files and captured check output.
It identifies deviations, unresolved questions, and checks that were not run.
Planning examples and acceptance commands do not constitute implementation evidence.
