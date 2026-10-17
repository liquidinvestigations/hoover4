# Verify known defects and source-defined limitations.

A defect report must identify the source, input, environment, and observed result.
Deployment-specific observations belong in the private infrastructure inventory.
The limits below describe current source behavior and do not establish a runtime failure in another environment.

## Search repair details are absent from the normal result view.

[The match builder](../../website/backend/src/db_utils/manticore_match.rs) returns a prepared expression and repair notes.
[Website query construction](../../website/backend/src/api/search/search_sql.rs) consumes the quoted expression without returning those notes to the result view.
[Agent search](../../website/backend/src/api/agent/search.rs) separately returns query notes.
A browser capture of an uppercase Boolean query showed results without the expected repair notice.
The short-infix notice is separate and appears when its documented length condition applies.

## Collection tools can continue bounded result pages.

Collection tools return a `more` handle when results remain in the current window.
`read_more` continues that result for the same user, conversation, and run.
[Paging](../../main_services/agents/collection_search_server/collection_search_server/paging.py) owns handles and stored windows.
[Search tools](../../main_services/agents/collection_search_server/collection_search_server/tools_search.py) own multi-form continuation.
The first 1,000 full-text document results remain the search reachability limit.
Narrow the query when the required records are outside that range.

## Chat context handling depends on model information.

The agent measures model input and can compact earlier step groups when the provider supplies a context window.
It preserves user messages and the stored transcript.
An unknown context window does not receive a guessed compaction threshold.
[Chat architecture](../architecture/Chat_And_Agents.md) describes the current context and queue contracts.
Model request and queue wait deadlines remain separate configuration settings.
A request deadline can expire while an external provider still processes that request.

## Plan completion can include document errors.

A plan finishes after its stages run, including when individual documents fail.
Inspect operation counts and document errors before treating the collection as complete.
[Operations](../../main_services/processing/tasks/P_ops/Readme.md) record the operation outcome and error counts.
[Processing stages](../architecture/Pipeline_Stages.md) describe the document outcomes and retry contract.

## Worker and migration changes have separate constraints.

Use [the worker restart script](../../main_services/restart-worker.sh) to preserve the configured drain period.
Verify that workflows using changed commands remain compatible with their stored history.
[The workflow diff check](../../.agents/check-workflow-diff.py) identifies changes that need that review.
The migration runner verifies the checksum of the complete applied file, including comments.
Use a new migration or change the reader when an applied contract needs correction.
[Settled decisions](../architecture/Settled_Decisions.md) describe the migration invariant.

## Verify full-text operator behavior.

The user reference documents supported operators and their current migration behavior.
[Read the query table.](../user-manual/User_Manual.md#what-you-can-type)
Word forms do not match automatically.
A stray tilde does not enable legacy edit-distance fuzzy search.
The request layer escapes field operators, so field restrictions use typed filters.
Spelling suggestions require explicit selection and preserve the active filters.
