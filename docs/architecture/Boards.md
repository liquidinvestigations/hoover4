# Investigation boards

A board is a long-running investigation of one or more goals over one or more collections.
The worker splits the goals into intents. Each intent runs as one chat turn, which is an
explore, and the explore ends in one board fact with resolved citations. A person reads the
board under AI Chat, adds hints and goals, rejects facts, starts the explore of an open
question, and accepts or rejects the result.

The page names three parts of a board in other words than the code. The **assessment** is the
model call that reads the board and declares intents or proposes the goal answers: the code calls
it a reason (`board_reason`, the events `reason_started` and `reason_result`, the actor
`reason`). The **background context** is the fact of kind `origin`: the collections and the
context of the board. An **open question** is a question that an explore fact leaves for the
board, stored in the fact's `open_questions`.

A board uses the chat stack for its agent work. It adds one tool, `submit_board_fact`, which
only board turns have, and no agent or model route.

## Contents

- [Routes](#routes)
- [Storage](#storage)
- [Workflows](#workflows)
- [The fold](#the-fold)
- [Assessment](#assessment)
- [Explore](#explore)
- [Person actions](#person-actions)
- [The graph](#the-graph)
- [Limits and settings](#limits-and-settings)
- [Changing the board workflows](#changing-the-board-workflows)

## Routes

- `/ai_chat` shows the chat on the left and the board overview on the right: a card per board
  with its title, status, a thumbnail of its graph and the board summary (the first goal
  before the summary exists). The overview shows while the chat gate
  is open, because the explores are chat turns.
- `/ai_chat/boards/new` is the create form. Send opens the new board.
- `/ai_chat/boards/:board_id?selected=&zoom=&assessment=` is the explorer. `selected` is the
  slug of a node, and empty selects the board overview. The page resolves it by slug first and
  then by storage id, so a link with a storage id keeps working. A click on a node puts its
  slug in the address. `zoom` is the zoom of the graph in percent: 50, 75, 100 or 125. Empty or
  another value is 100. A zoom change replaces the address, and a node click keeps the zoom.
  `assessment` is the number of the assessment whose details popup is open, empty for none.
- A board explore chat links back to its board: "Investigation Board" in the row of the
  conversation search selects the chat's intent, and the answer card at the end of the chat
  selects its fact. Both open the board in the same tab.

Every user can own boards. A board belongs to the user who created it, also for
administrators, and the server functions return "not found" for a board of another user.

## Storage

Migration `00043_investigation_boards.sql` adds six tables to the global database.
Migration `00044_board_settings.sql` adds the `internet_tools` column to `boards`.
Migration `00045_board_labels.sql` adds `board_labels`.
Migration `00046_board_assessments.sql` adds `board_assessments`.

| Table | Content | Writer |
|---|---|---|
| `boards` | The definition: owner, first goal, context, collections, internet tools. A drop sets `is_deleted`. A settings change writes a new version of the row. | the website |
| `board_events` | Every action, with a JSON payload. This table is the record of the board. | the website and the worker |
| `board_state` | The status and counters that the last fold wrote. | `board_plan` only |
| `board_intents` | The intents as the last fold derived them. | `board_plan` only |
| `board_facts` | The facts. A fact is written once and never changed. | the website and `conclude_explore` |
| `board_fact_citations` | The documents of each fact, resolved from the explore's `cite_documents` rows. | `conclude_explore` |
| `board_labels` | The generated slug, title and summary of each intent, fact and correction, and one summary row of the board (empty `node_id`). A slug is a display name and an address key. The storage ids do not change. | `label_board` only |
| `board_assessments` | The whole prompt and the whole reply of each assessment, keyed by board and assessment number. An assessment that ran before the table existed has no row. | `board_reason` only |

Ids are deterministic, so a retried activity writes the same row again. An intent is
`i{reason}.{k}` and its fact is `f{reason}.{k}`. The intent that a person starts from open
question N is `i0.N`, because reasons start at 1, and its fact is `f0.N`. An event id is
`{type}:{subject}:{attempt}` for worker events. The explore of an intent runs in the chat session
`board-{board_id}-{intent_id}`.

A board fact has one of six kinds.

| Kind | Meaning |
|---|---|
| `origin` | The background context: the collections and the context, written at creation. |
| `goal` | A goal, written at creation or later by a person. The first goal is `goal`, the next ones `goal-2` to `goal-6`. |
| `sourced` | An explore finding with at least one citation whose quote the chat verified. |
| `inferred` | An explore finding without such a citation. A `sourced` claim without a verified quote is stored as `inferred`. |
| `not_found` | The explore searched and found nothing that answers the intent. |
| `correction` | The text of a person who rejected the review. |

## Workflows

```mermaid
flowchart LR
    D[BoardDispatcher<br/>board-queue] -->|board_plan| CH[(ClickHouse)]
    D -->|board_reason<br/>chat-model-queue| CH
    D -->|child, abandon| E[BoardExplore<br/>board-queue]
    E -->|open_explore_turn| CH
    E -->|child| A[AgentRun<br/>chat-queue]
    A --> CH
    E -->|conclude_explore| CH
```

`BoardDispatcher` has the fixed id `board-dispatcher`. The chat worker starts it at start-up
when it is not running. Every 5 seconds it runs `board_plan`, starts the assessments and explores
that the plan returns, and cancels the explores of paused and dropped boards. After 200
passes it waits for its assessments in flight and continues as new. The dispatcher waits for no
person. A person action is a row in ClickHouse, and the next pass reads it.

`BoardExplore` runs one intent. It opens a chat turn, runs it as an `AgentRun` child, and
concludes it. When the turn ends without a `submit_board_fact` call, it sends one conclude
turn in the same session and concludes again.

### Labels

`board_plan` also names at most one board that needs labels: a node without a current label,
or a board summary whose source text changed (`labels.label_due`). The dispatcher then starts
`label_board` on `chat-model-queue`, one at a time, outside the board model slots. One call of
the summarisation model labels up to 8 nodes, from the full text of each node.

| Node | Slug | Title and summary |
|---|---|---|
| origin (background context) | `background`, fixed | none, the text shows |
| goal | `goal-01`, `goal-02` and so on, fixed | none, the text shows |
| intent | `intent-<words>` | generated from the objective and the brief |
| fact | `fact-<words>` | generated from the kind and the text without `[Dn]` handles |
| correction | `correction-<words>` | generated from the text |
| the board | none | 10 to 15 words, from the origin, every goal, and the titles of the intents, the live facts and the corrections |

The model gives 2 to 4 slug words, a title of 3 to 4 words and a summary of 15 to 20 words.
The code keeps at most 4 slug words and 40 characters, cuts a title at 5 words and a summary at
24 words. A slug that another node of the board has gets `-2`, then `-3`. A slug does not
change after its first write. A changed source text gives a new title and summary under it. A
node that a reply leaves out counts a failed attempt. After 2 failed attempts the code writes a
label from the first words of the node text, with `model = 'fallback'`. A board whose newest
row records a failed attempt waits 60 seconds before its next call. Each call writes an
`llm_call_events` row of kind `board_label` or `board_summary`. Until a node has a label, the
website shows its storage id and the first words of its text.

`board_plan` also reconciles. It reads the Temporal state of each running intent older than
60 seconds. When the `BoardExplore` closed without an end event, it writes
`explore_concluded` if the fact exists, `explore_cancelled` if the workflow never started, and
`explore_failed` otherwise. So a worker restart does not leave an intent running for ever.

## The fold

`tasks/P_board/fold.py` derives the state of a board from its events and facts. It reads no
storage and no clock. The module docstring lists the rules. These rules have the most effect:

- A pause, a resume, a decision and a drop apply in event order. The worker proposes, and a
  person decides.
- An assessment of outcome `review` proposes one answer for each goal without an accepted
  answer, and replaces every earlier proposed answer. The person accepts or rejects each
  answer separately (`goal_answer_accepted`, `goal_answer_rejected`). An accepted answer stays
  in every later state. The board is complete when every goal has an accepted answer. A
  rejected answer moves a board in review to active at once, and the other proposed answers
  wait for their decision. A decision counts only for the proposed answer of the same
  assessment, so a decision on a replaced answer does nothing. In review, `review_accepted`
  ("Finish the board") accepts every proposed answer and completes the board, also with goals
  that have no answer, and `review_rejected` drops the proposed answers and continues.
- A `goal_added` moves a board in review or complete back to active, and marks the checkpoint
  as having work, so the board gets an assessment when that work ends without a new fact. A
  paused board stays paused.
- `question_explored` opens the intent `i0.N` from the fact that asked the question, with the
  question as its objective and no assessment first, and changes no status. On a board in
  review or complete the planner starts only such intents, and no assessment follows. On an
  active board the new fact goes to the next assessment.
- `explore_started` uses one attempt and one explore of the budget. A cancellation returns
  both. An intent fails after 2 failed attempts.
- An assessment is due when the facts, hints, rejections or late goals changed since the last
  valid assessment. It runs only on an active board with no open intent and no assessment in
  flight. A checkpoint written before late goals existed reads their count as 0.
- The board goes to review in three cases. The budget is used, an assessment proposes answers
  from sourced facts, or 3 assessment replies in a row are invalid. The assessment prompt marks
  an accepted goal as closed, and its check drops an answer for it with a note. The check also
  reads a `goals` list without its `review` key, a fenced object without its opening brace,
  and trailing commas. It drops an id that is not a fact, such as a correction, from an answer
  that names other facts.
- The explore budget and the model steps of one explore start at 12 explores and 60 steps. A
  rejected fact or a rejected review adds 4 explores and 20 steps. A hint adds 1 explore and
  5 steps. The caps are 24 explores and 120 steps. A goal added later adds 4 explores above the
  explore cap and 20 steps within the step cap, and an explored open question adds 1 explore
  above the cap, so a person's late request always gets its explore. A repeated event of one
  goal or one question counts once (`Folded.max_explores`, `Folded.explore_steps`).
- An explore that asked a question waits. The next hint opens its intent again.

## Assessment

`board_reason` sends one model call on `chat-model-queue`, with the short-call model of
`hoover4.ini` (`LLM_MODEL`). The prompt holds the goals, the live facts without their citation
labels, the hints, the rejected facts and the intents. The activity writes the prompt and the
whole reply to `board_assessments` before its `reason_result` event, while the board is not
dropped. The reply must be one JSON object with
`intents`, `review` or neither. `contracts.parse_reason` checks it.

- An intent must name live facts in `from`. An intent that repeats an earlier objective is
  dropped. At most 3 intents are kept.
- `review` has one entry per goal, with the facts that answer it and a statement. A goal's
  facts are sourced or not-found facts, and the review needs at least one sourced fact. A
  review that leaves out a goal counts as empty.
- A reply without a JSON object is invalid.

Every change that a check makes is in the `problems` list of the `reason_result` event. The
"Show details" button of an assessment row in the events table opens a popup with the date,
the model, the outcome, the latency, the tokens, these checks, the prompt and the response.
For an assessment that ran before `board_assessments` existed, the popup shows the first 6000
characters of the reply, which the event holds, and says that the prompt was not stored.

## Explore

`open_explore_turn` writes the rows that `send_message` writes for a person: the session with
the board's internet setting and its options locked, the user message, and the stream row.
The turn then runs as an ordinary `AgentRun` of kind `board`, with the model step limit of
the fold. Its model is the agent model of `hoover4.ini`, as for a chat turn. A board turn does
not write follow-up suggestions or a session title.

A board turn has the tool pack `board`, which no chat turn has. Its tool `submit_board_fact`
takes the fact with inline `[Dn]` handles, its kind and at most 3 open questions, and ends the
turn. The workflow writes the fact as the answer of the turn, with the citation metadata of a
chat answer. The chat page shows the answer and, under it, what the turn gave to the board.
`conclude_explore` reads the call and resolves each handle from the `doc_refs` of the
session's `cite_documents` results. A turn that asks the person a question becomes an
`explore_question` event.

Citation labels are local to one chat session. The worker removes them from a fact before the
fact enters another prompt, and the citation rows keep the document identity.

The chat history leaves board sessions out unless the person ticks "Show board chats", and
`send_message` refuses a board session. The explorer links to the session page, where a person
reads the full turn.

## Person actions

| Action | Effect |
|---|---|
| Create | Writes the definition, the `origin` fact, a `goal` fact per goal, `board_created`, and one `hint_added` for each first hint. Every readable collection is selected at first, and the internet tools are on. The collections cannot change later. |
| Settings | Writes a new version of the `boards` row and `settings_changed`. Only the internet tools can change. Explores that run keep the setting they started with. |
| Add hint | Writes `hint_added`. The next assessment reads it. It also opens intents that asked a question. |
| Add goal | Writes the next goal fact and `goal_added`, at any status but dropped, up to 6 goals. The next assessment reads the goal. A board in review or complete becomes active. |
| Explore this question | Writes `question_explored` with the subject `i0.N`, where N counts the explored questions of the board, and the fact id, the position and the text of the question. The fold opens the intent, and the board keeps its status. A question of a rejected fact, or one already explored, is refused. |
| Reject fact | Writes `fact_rejected` with the reason. Later prompts leave the fact out and list it as rejected. The fact detail shows who rejected it, when and why. On a correction the box and the button say "Why the correction is wrong" and "Reject correction". |
| Pause and resume | Write `pause_requested` and `resume_requested`. A pause cancels running explores and does not use their attempts. |
| Accept answer | Writes `goal_answer_accepted` with the goal, the assessment number and the answer. When every goal has an accepted answer, the board is complete. |
| Reject answer | Writes a `correction` fact and `goal_answer_rejected`, whose `from` names the facts of the answer. The board continues at once. |
| Finish the board | In review only. Writes `review_accepted`. Every proposed answer is accepted, and the board is complete. |
| Continue with a correction | In review only. Writes a `correction` fact and `review_rejected`, whose `from` names the facts of the proposed answers. The board is active again. When the explore budget is used, the next pass sends it back to review. |
| Drop | Writes `drop_requested`, sets `is_deleted` on the `boards` row, cancels the running explores, deletes the board's chat sessions as the chat history deletes a chat (a tombstone on the session row), and deletes the rows of the other seven board tables. |

## The graph

The explorer and the overview thumbnail draw one graph (`components/board_graph.rs`). x is
depth: the background context is the first column, the goals are the last column, and every
other node is one column after the deepest node it comes from. Open questions have no node.
The fact pane lists them. The edges follow the encoding of Cairn, which
records a completion as an edge from the facts to the goal and a reopened goal as an edge from
those facts to the person's correction.

| Edge | From | To |
|---|---|---|
| Flow | a fact that an intent names, or an intent | the intent, or the fact of the intent |
| Answers | a fact of the accepted answer of a goal | that goal, in every status. Dashed for a proposed answer that waits for the person. |
| Corrects | a fact of a rejected answer or review | the correction of it |

The layout is computed in one pass before it shows, so no node moves on screen. In each column
a node asks for a y: its earlier y, else the mean y of its placed neighbours. The column sorts
by that y and moves its nodes apart to one row each, so nodes never overlap. A placed node
moves only when a new node needs its room.

A node is 300 by 150 pixels at 100 % zoom, and its fonts are the app's text roles: the title
in bold at the body size, the summary at the detail size in at most 4 lines, and a meta row
in gray monospace with the type of the node on the left and its statuses on the right
(`board_graph::corners`). No card shows its slug, and no status repeats the type.

| Node | Left | Right |
|---|---|---|
| background context | `background` | none |
| goal | its slug, `goal-01` | `answered` or `answer proposed` |
| fact | `fact` | `sourced`, `inferred` or `not found`, and `rejected` |
| correction | `correction` | `rejected` when rejected |
| intent | `intent` | its state |

The background context is white with a black border. The goals are blue with white text. The
background context and the goals show their text with no title. A rejected fact and a
cancelled intent are dimmed, with an opaque white card under them. The detail pane of a node
shows the same type and statuses under its title, and "Open the explore chat" at the right
of the title for an intent or fact with a chat. The graph does not scale to its pane. The pane scrolls, a press and a drag of more than 4 pixels
pans it up to the edges of the graph, and a control in its lower-right corner zooms out to
50 % and in to 125 %. After a zoom change the pane keeps the same graph point in its middle.
While a node is selected, "Show the board overview" is over the top-right corner of the pane.
When the selected node is not wholly in the pane, at the first load of the page or after a
link in a detail pane selects it, the pane scrolls it to its middle. A click on a node does
not scroll.

Every edge is one straight line from the middle of the right side of its source to the middle
of the left side of its target, and every edge is drawn under the nodes.

The board overview on the right shows the review panel while the board waits for review,
the goals with their answers and the form to add a goal, the hint form, the events as a table (date, actor,
event, links, newest first) and the statistics: explores, model steps, assessments, intents
and facts by state, collections, internet tools and the creation date. A person's name shows
in bold and a system actor in italic, and the actor `reason` shows as `assessment`. The text
that a person wrote in an event shows in italic after the fixed text. The links column shows
"Show details" for an assessment, "Open" (a new tab) for an event of an intent or a fact with
an explore chat, and else the slug of the node that the event names, as a link that selects
it. A goal shows its accepted answer, or its proposed answer with "Accept answer" and "Reject
answer", in the overview and in its detail pane. The fact pane lists each open question of the
fact as a card with the question in a larger font and, in its bottom-right corner, "Explore
this question", or "Explored in" and the slug of the intent that follows it.

The brief of an explore allows one tool call per 4 model steps of its budget: 15 calls at the
base budget and 30 at the cap.

## Limits and settings

| Limit | Value | Where |
|---|---|---|
| Board model work of all boards together | `server_settings` key `board_max_parallel_explores`, default 1 | `/admin/settings` |
| Explores of one board | 12, growing with corrections and hints to at most 24, and above that with late goals and explored questions | `tasks/P_board/model.py` |
| Model steps of one explore | 60, growing with corrections and hints to at most 120 | `tasks/P_board/model.py` |
| Goals of one board | 1 to 6 | `common::board_types::MAX_GOALS` |
| Attempts of one intent | 2 | `tasks/P_board/model.py` |
| Intents kept from one assessment | 3 | `tasks/P_board/model.py` |
| Output tokens of one assessment, reasoning included | 16,000 | `tasks/P_board/model.py` (`REASON_MAX_TOKENS`) |

Each running explore and each assessment in flight uses one slot of the global cap. A free slot
goes first to the board with the least work in flight, and then to the board that has
received the fewest explores and assessments, so a new board does not wait for every explore
of an older board. The explore
turns also use the chat queues, so a board turn competes with the chats of people.

## Changing the board workflows

A change to `tasks/P_board/workflows.py` that schedules a different command for an existing
history event needs the drain of
[`tasks/Readme.md`](../../main_services/processing/tasks/Readme.md). Terminate
`board-dispatcher`, cancel every `board-explore-*` workflow, deploy, and let the worker start
the dispatcher again. The next pass reconciles the cancelled intents, and they run again.

A new step that an old history decodes as empty needs no drain. `PlanOutput.labels` is such a
step: a `board_plan` result in an old history decodes with no labels, so a replay schedules no
new command. The evidence for such a change is a `temporalio.worker.Replayer` run of the new
workflow code over the fetched `board-dispatcher` history, before the worker restarts.
