# Investigation board

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Graph node | Select the node and show it in the detail pane. | The address holds the slug of the node. A click does not scroll the pane. |
| Pan | Move the graph view with a press and a drag on the pane. | A drag of at most 4 pixels stays a click on the node under the pointer. |
| Zoom out / Zoom in | Show the graph at 50, 75, 100 or 125 %. | The address holds the zoom. The pane keeps its middle graph point. |
| Show the board overview | Show the board overview in the detail pane. | It is over the top-right corner of the graph pane and shows only while a node is selected. |
| Settings | Open the settings popup: internet tools, pause or resume, drop. | The collections are fixed at creation. |
| Open the explore chat | Open the chat of the selected intent or fact. | It is at the right of the detail pane title, for a node with a chat. |
| Citation card | Open the explore chat of the fact in a new tab with the document selected. | The card opens the document at the words of its quote. |
| Reject fact / Reject correction | Reject the selected fact or correction with a reason. | The background context and the goals cannot be rejected. |
| Explore this question | Ask the board to explore one open question of the selected fact. | It is in the bottom-right corner of the question's card in the fact pane. It is absent for an explored question, which links the intent that follows it, a question of a rejected fact and a dropped board. The board keeps its status. |
| Add goal | Add a goal to the board. | A board has at most 6 goals. A dropped board has no form. A board in review or complete starts again. |
| Add hint | Add a hint that the next assessment reads. | It shows while the board is active or paused. |
| Accept answer / Reject answer | Accept the proposed answer of one goal, or reject it with a correction. | It shows for each goal with a proposed answer, in the goal pane and the overview, in every status but dropped. An accepted answer stays. A rejection lets the board continue at once. |
| Finish the board / Continue with a correction | Accept every proposed answer and complete the board, or continue it with a correction. | It shows while the board waits for review. |
| Show details | Open the popup of an assessment with its prompt and its response. | The address holds the assessment number. An assessment that ran before the prompts were stored shows its stored reply only. |
| Open | Open the explore chat of an event's intent or fact in a new tab. | It shows in the links column of an event with a chat. |
| Node link | Select the node that an event names. | It shows in the links column of an event without a chat that names a node. |

## States

A selected node that is not wholly in the graph pane scrolls to the middle of the pane at the first load and after a detail pane link selects it.
A card shows its type in the bottom-left corner and the statuses that the type does not say in the bottom-right corner. A goal card shows its slug in place of its type, and `answered` or `answer proposed`.
The page header items share one middle line with the logo of the left bar.
