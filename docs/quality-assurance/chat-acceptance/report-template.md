# Chat acceptance run report

Copy this file once for each run. Fill every field. Write "not seen" when a field has no data, and do not leave it empty.

## The run

| field | value |
|---|---|
| story | the story file, for example `05-nili-priell-barak-fortress.md` |
| mode | chat or deep research, internet tools on or off |
| session id | the 64-character id |
| chat page | `/ai_chat/c/<session id>/9g==/9g==` on the site under test |
| account | the account that owns the chat |
| model | the `model` column of the assistant rows |
| start and end | the `created_ms` of the first and the last row |
| wall time of each turn | from the driver output or the row times |
| peak context | `peak_context_tokens` of the session, and the context window |
| data state | which collections were searchable, and whether an ingest was running |

## Verdicts

Give each category PASS, FAIL or PARTIAL. Give the message sequence number (`seq`) of the evidence for each.

| category | verdict | seq | what the reviewer saw |
|---|---|---|---|
| First todo write. The first `write_todo` is accepted, with plain ids. | | | |
| Todo upkeep. Items move to `in_progress` and `done` as the work happens, and the list is not marked done after the answer. | | | |
| Search scope. The first search covers every collection in scope, in one call, with no collection named unless the user narrowed the scope. | | | |
| Query variants. One call carries the variants the story needs: quotes and no quotes, spellings, scripts, the address and the name. | | | |
| Query syntax. No `OR`, `AND` or other Elasticsearch syntax. `|` for either word. | | | |
| Argument shape. No collection written as `collection/dataset`, no dataset name as a collection, no invented hash, no filter the user did not ask for. | | | |
| Tool errors. Each error is read and the next call corrects it. No error is ignored. | | | |
| Reads before claims. Each fact in the answer comes from a document the agent read or a result it received. | | | |
| Web use. The web is used only where the story needs it, and web facts are marked as such. | | | |
| Document cards. `cite_documents` shows the user each document the answer talks about. | | | |
| Passage. Each card carries a verbatim quote that the page can open at. | | | |
| Completion. The answer does what the prompt asked. | | | |
| Deep research only. The plan has one node for each part of the question, and each sub-agent runs on a real plan node id. | | | |

The run passes when "Reads before claims", "Document cards" and "Completion" pass and no other category fails.

## Where the agent leaves the data

List each point where the answer states something that no tool result holds, or where the agent moves to the web while the documents hold the answer. For each point give the `seq`, the claim, and the result that contradicts it or the result that is missing.

| seq | claim in the answer | what the data holds | kind |
|---|---|---|---|

Kinds are "no result behind it", "contradicts a result", "web in place of documents", "count or scope wrong", and "stopped early".

## Where the user cannot verify the answer

This is a question about the page as much as the model. For each point, say what the user sees and what they would need to check the claim themselves.

| seq | what the answer says | what the page shows | what is missing |
|---|---|---|---|

Look at these four things.

1. A document named in the prose with no card.
2. A card with no quote, or a quote that the check marked as not verified.
3. A search result that the model received and the user cannot open, for example a hit with no path or hash.
4. A web claim with no link to the page it came from.

## Tool calls

One row for each tool row of the chat, in `seq` order.

| seq | tool | arguments, in short | result, in short | correct call, when this one was wrong |
|---|---|---|---|---|

## Reviewer notes

Write these notes in any form. Name the story fact that the answer missed and the tool whose description sent the model the wrong way. Name anything the page did that the story did not expect.

## Debugging avenues

Read these on the host that ran the chat. The chat tables are in the database `Hoover4_Processing`. Each table below has a session id column. Read only the rows of the run's session id. Read a table that the list names with `FINAL` with that modifier, so that each row occurs once.

| question | where to read |
|---|---|
| What did the user see, in order? | `chat_messages FINAL`, ordered by `seq`. `tool_input`, `tool_output` and `doc_refs` hold the call, the result and the cards. |
| What did the model receive and send on each call? | `agent_run_messages FINAL`, ordered by `thread_id` and `idx`. `tool_calls_json` holds the raw call as the model wrote it, before argument decoding. |
| Which runs took part, and why did each end? | `agent_runs FINAL`. Read `kind`, `purpose`, `state`, `error`, `refused_json` and `tool_turns_used`. |
| Did a sub-agent get refused? | `refused_json` on the organizer row, and the `run_subagent` row in `chat_messages`. |
| What did the todo list hold at each step? | `chat_todos`, ordered by `version`. |
| Which cards and page captures exist? | `chat_artifacts FINAL`. `kind` is `agent_raw_result`, `search_detail` or a page capture. |
| Did a model call fail or take long? | `llm_call_events`. Read `ok`, `error`, `latency_ms` and `prompt_tokens`. |
| Did compaction drop history? | `chat_compactions`, `evicted` and `summary`. |
| Was a search result cut before the path and the hash? | the `cut` object of each item in the `search_collections` output, and `total_units` against `returned_units`. |
| Is the fact in the data at all? | a text scan of `Hoover4_Collection_<name>.text_content`, joined to `vfs_files` for the path. |
| Did the tool server log an error? | `docker logs` of the collection search, todo, browser and research agent containers, for the minutes of the turn. |
| Did the workflow retry? | the Temporal workflow of the turn, `temporal workflow show`, and the `chat-queue` and `chat-model-queue` task queues. |
