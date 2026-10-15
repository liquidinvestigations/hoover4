# Investigation board

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Graph node | Select the node and show it in the detail pane. | The address holds the slug of the node. A click does not scroll the pane. |
| Pan | Move the graph view with a press and a drag on the pane. | A drag of at most 4 pixels stays a click on the node under the pointer. |
| Zoom out / Zoom in | Show the graph at 50, 75, 100 or 125 %. | The address holds the zoom. The pane keeps its middle graph point. |
| Show the board overview | Show the board overview in the detail pane. | It is over the top-right corner of the graph pane and shows only while a node is selected. |
| Settings | Open the settings popup: internet tools, pause or resume, drop. | The collections are fixed at creation. Hide internet tools when `internet_tools_enabled` is false. |
| Open the explore chat | Open the chat of the selected intent or finding. | It is at the right of the detail pane title, for a node with a chat. |
| Citation card | Open the explore chat of the finding in a new tab with the document or the web page selected. | The card opens the document at the words of its quote. |
| Reject finding / Reject correction | Reject the selected finding or correction with a reason. | The background context and the goals cannot be rejected. |
| Explore this question | Ask the board to explore one open question of the selected finding. | It is in the bottom-right corner of the question's card in the finding pane. It is absent for an explored question, which links the intent that explores it, a question of a rejected finding, a dropped board and a board at its explore limit. The board keeps its status. |
| Ask | Ask the board to explore the person's own follow-up question about the selected explore finding or the background context. | It shows on a finding of kind sourced, inferred or not found and on the background context. It is absent on a rejected finding, a dropped board and a board at its explore limit. The board keeps its status, and the pane lists the question with its intent. |
| Add goal | Add a goal to the board. | A board has at most 6 goals, and the pane says so at 6. A dropped board and a board at its explore limit have no form. A board in review or complete starts again. |
| Add hint | Add a hint that the next assessment reads. | It shows while the board is active or paused and below its explore limit. |
| Reopen with N more explores / Reopen with the remaining budget | Reopen a board in review or complete to continue its open goals. | It shows when a goal has no accepted answer, the board is below its explore limit and the review has not reopened. In a budget review it is the first action. N is the actual grant. |
| Accept answer / Reject answer | Accept the proposed answer of one goal, or reject it with a correction. | It shows for each goal with a proposed answer, in the goal pane and the overview, in every status but dropped. An accepted answer stays. A rejection lets the board continue at once. |
| Close the board / Continue with a correction | Accept every proposed answer and complete the board, or continue it with a correction. | It shows while the board waits for review. |
| Show all events / Show the newest 200 events | Show every event of the board, or the newest 200. | It shows when the board has more than 200 events. |
| Show details | Open the popup of an assessment with its prompt and its response. | The address holds the assessment number. An assessment that ran before the prompts were stored shows its stored reply only. |
| Open | Open the explore chat of an event's intent or finding in a new tab. | It shows in the links column of an event with a chat. |
| Node link | Select the node that an event names. | It shows in the links column of an event without a chat that names a node. |

## States

A selected node that is not wholly in the graph pane scrolls to the middle of the pane at the first load and after a detail pane link selects it.
A card shows its type in the bottom-left corner and the statuses that the type does not say in the bottom-right corner. A goal card shows its slug in place of its type, and `answered` or `answer proposed`.
The page header items share one middle line with the logo of the left bar.
A button of a person action stays disabled until the board's command writer decides the action. A refused action shows its reason above the board.
A board that used 300 explores shows a notice with a link to the create form. Its answer decisions stay available.
A proposed answer whose findings are all not-found findings says that the records do not answer the goal.
