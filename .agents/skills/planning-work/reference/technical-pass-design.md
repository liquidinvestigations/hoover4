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

Use the plan's technical design document for each technical pass.
Link to its exact section from each prompt.
Keep all implementation-critical information outside disposable research folders.
Extract useful findings and check their primary sources before treating them as requirements.

## The design document

A plan with a technical pass has one technical design before its work packages. A `reviewer`
reads it against the source at the design's commit stamp. The review report gives `accept` or
`reject` and uses the finding columns in `reviewing-changes`. Correct a rejected design before
writing packages that depend on it.

| section | required content |
|---|---|
| Owned paths | Give one owner pass for each changed path. |
| Component sections | Give the interfaces, algorithms, state and data listed above. |
| Deleted code and files | Name every removed path and every reference that must change. |
| Documentation that moves | Name each Readme, documentation page, skill and specification row. |
| Decisions a pass measures | Give the pass, starting value, one alternative and measurement. |
| Retry, concurrency and size | Complete the checklist below when the affected operations use it. |
| Risks | State failures that no planned check can detect. |

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
Give pseudo-code for every loop, retry, claim and state transition that a pass changes.
Give type and schema stubs for each new or changed type, table and message.
Give the order of edits and the dependency that sets that order.

## Define acceptance

Each task names a check and the behavior that check proves.
Give normal, boundary, and failure cases where each protects a relevant invariant.
Expected results come from the requirement, a hand calculation, or an independent reference.
Name runtime checks when compilation cannot prove the behavior.

Distinguish existing commands from commands the pass creates.
For a new command, specify its arguments, outputs, exit status, runtime environment, and timeout.
State dependencies that must exist before it runs.
Do not present a planned command as a check already available in the tree.
Put the commands in a table with arguments, output, exit status and timeout.
Put all checks in one command block, with a timeout on each long command.
Give each count, size, duration and threshold an expected result from a hand calculation or
a measured baseline. Record the baseline's date and command.
For a value the plan does not fix, measure the starting value and one named alternative.
Report both values. Do not loosen the acceptance check to make either value pass.
Anchor each source symbol as `path:line` at the package's commit stamp.
Name missing dependencies and the required behavior until they exist.

## Retry, concurrency and size

Complete this section when a pass changes a Temporal activity, workflow, or ClickHouse or
Manticore write.

1. **Repeated writes.** Temporal retries the whole activity. Give each write's idempotency
   key or the immutable input from which a count is read.
2. **Concurrent writers.** Name every writer of each changed row. Use per-column updates or
   one writer when a whole-row write can erase another update.
3. **Workflow history.** Calculate events per unit times the largest unit count on the demo
   box. Compare the result with Temporal's 51,200-event limit. Define the split if it exceeds
   that limit.
4. **Check then insert.** Use an atomic statement or a lock when two callers can pass the
   same pre-insert read.
5. **Identifier resolution.** State the clock resolution, call rate and random or sequence
   part of an identifier derived from time.
6. **Retry and heartbeat values.** Name each attempt count and timeout, with the file that
   sets it. State how the components agree on failure.

## Report actual outcomes

The report links each task to changed files and captured check output.
It identifies deviations, unresolved questions, and checks that were not run.
Planning examples and acceptance commands do not constitute implementation evidence.
