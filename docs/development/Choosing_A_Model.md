# Choosing a model

The repository uses four logical roles. Harness configuration supplies their model and effort settings.

The organizer coordinates accepted work and owns authorized Git writes.
It can implement directly when the person requires work without delegation.
The light executor handles ordinary bounded implementation.
The heavy executor handles assignments with substantial state, compatibility, concurrency, or cross-component risk.
The reviewer reports concrete defects and evidence limits.

Select roles from actual responsibility and risk.
A correction does not automatically require the heavy role.
Historical task scores and role quotas do not determine the assignment.

When a model change is requested, compare it on representative work and agreed acceptance conditions.
Verify tool use, available context, completed outcomes, scope adherence, cost, and recovery from failures.
Published benchmarks and price per token do not establish cost per completed repository task.

Use a trial large enough to expose relevant variation and report the actual sample size.
Do not impose a universal call-count test or context fraction.
Use configured platform limits and explicit user budgets.

`.agents/harnesses/model-mappings.md` records the configured roles.
[Working with agents](Working_With_Agents.md) identifies the harness files.
