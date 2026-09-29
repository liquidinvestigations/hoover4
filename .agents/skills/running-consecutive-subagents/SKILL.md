---
name: running-consecutive-subagents
description: Delegate an authorized repository task to another agent in the shared checkout. Use only when delegation is requested or permitted for the current work.
allowed-tools: Task, Read, Write, Edit, Glob, Grep, Bash
---

# Running consecutive subagents

Delegate a bounded task that benefits from a separate context. Do not delegate when the person asked for direct work.
Run one subagent at a time in the shared checkout. Wait for it before launching the next.
Do not edit its owned paths while it runs.

Give the agent its role, requested outcome, relevant decisions, owned paths, checks, and report destination.
Link existing design and evidence. Do not require the agent to repeat settled research.
Use the [package template](reference/work-package-template.md) when the assignment needs a file.
Keep model and effort selection in the harness role mapping.

A material uncertainty can block dependent work. Routine implementation choices do not require a new interview.
A subagent cannot expand the objective or authorize commits, deployment, or external communication.
Executors and reviewers run no Git write commands.

Use actual session limits or a budget explicitly set by the person.
There is no default tool-call budget, task quota, or extension limit.
Resume the same assignment when useful work remains. A continuation needs updated context, not another full package.

Read the resulting diff and relevant evidence before accepting the report.
Correct a concrete blocking defect within the existing scope. Select the correction role from its actual risk.
Repeated defects require diagnosis. Their count does not create another pass or review batch.
Reuse valid checks for unchanged code and environment.

Record delivered behavior, remaining requirements, and necessary next actions in the plan.
If work must stop, preserve current state and the next action using the planning handoff guidance.
