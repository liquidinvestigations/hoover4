# Chat session

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Source card | Open its document or captured web page in the preview pane. | Web pages use the captured Markdown version. |
| Web source title | Open the source website in a new tab. | The captured preview stays available through the card. |
| Citation handle | Select its source and scroll to the existing card. | Each source has one card across the conversation. |
| Search-term line | Open the originating search with the cited document selected. | The line requires a query association in the stored trace. |
| Find exact text | Highlight exact, case-sensitive matches in the captured page. | Formatting boundaries can occur inside a match. |
| Previous match | Select and scroll to the previous exact match. | Selection wraps through the available matches. |
| Next match | Select and scroll to the next exact match. | Selection wraps through the available matches. |
| Close preview | Close the captured page pane. | The conversation stays open. |
| Search in conversation | Find messages containing the entered text and move between matches. | The count updates while typing. The input is at most 350 pixels wide, and the counter and the buttons follow it. |
| Investigation Board | Open the board of a board explore chat, with the chat's intent selected. | It shows only in a board explore chat, at the right end of the search row. It opens in the same tab. |
| Board answer card | Open the board of a board explore chat, with the fact of the turn selected. | It is the card at the end of a board explore chat. It opens in the same tab. |
| Workspace | Open the workspace pane with the files that the assistant wrote in the conversation. | It is in the title row. The pane is read-only. Its file and version are in the address. |
| Workspace file | Show the current version of the file in the workspace pane. | The list shows each file with its current version and length. |
| Open in the workspace | Open the pinned report version of an answer in the workspace pane. | It is in the line above an answer that shows a report. |
| Close the workspace | Close the workspace pane. | The conversation stays open. |
| Follow-up suggestion | Fill and focus the composer with the selected prompt. | The user edits or sends it explicitly. |
| Send | Submit the composer text. | Empty text and a closed chat gate disable Send. The navigation arrow button includes a Send tooltip. |
| Tool group | Show or hide the tools, instructions, superseded answers, and the reasoning of the round. | Completed groups start closed. |
| Todo call card | Expand the stored arguments, the result or failure, and the list after the call. | Every todo call has one card inside its group. |
| Reasoning | Show or hide the model's reasoning for the answer. | It is inside the group before the answer, or beside an answer that has no group. |
| Tool images | Show each document image and each `read_page` screenshot that the model received after a tool result. | The previews are under the tool card. A browser tool shows its screenshot on its own card. |
| Narration | Show the model's text before a tool call, in gray above the card of that call. | A closed group shows its newest narration above its line. The reasoning view leaves the narration out. A board explore chat shows it too. |
| Show / Hide | Show the full text of a user message, or cut it to three lines again. | The toggle is in the top-right corner of the message and shows only when the message is longer than three lines. |
| Internet tools | Show the internet tools option only when `internet_tools_enabled` is true. Show it in the composer before locking and beside the title afterwards. | The checkbox is disabled after the first turn. Its tooltip is "Start a new chat to change this setting." |

## States

Citation cards appear at their first visible marker, in response order.
Successful citations without markers appear after the final answer and before the token footer.
Their citation reason appears above the card.
Later markers select the existing card.
Separate verified document passages share one card and open their own find queries.
Bold and italic citation handles keep their source controls and validation.
A comma-separated citation group renders and verifies each handle.
Tables show a source card after the first row that cites it.
Document cards contain the matching source excerpt.
Web cards show a linked title, its domain on the line under the title, and the verified source excerpt below them.
Document and web cards show their citation handle in the card header.
They are 124px high, with the 23px body line height.
Two 13px lines under the card controls show the file size and the earliest confirmed date of the document. They stay empty while the values load and after a failed read.
The card text shows at most three complete lines, with an ellipsis when text is omitted, and does not scroll.
Each passage in the card text opens its source on click, Enter, or Space.
A task summary follows the group of a todo call that changed the visible task state.
It shows the bold goal and an unnumbered task list, with the task icon in its upper-right corner.
It uses the neutral surface colour, fits its text, and takes at most 80% of the transcript width.
A done task is struck through and followed by the first three words of its reason in bold.
A replaced task stays struck through directly above the task that replaces it.
A failed, unchanged, or unstored todo call shows no new summary.
An answer whose turn wrote a workspace file shows the last file version of the turn as its text, under a line with the file name and the version. The chat text of the answer follows it in a muted colour.
An answer whose report version cannot be read shows its chat text and says so.
The board writes a "Submitted by the board" finding card after the answer of a board explore turn.
An active turn shows one line with a turning icon and the text "The bot is working...".
A queued turn adds the slot that it waits for under that line.
Failed document quotes allocate no new handles.
Finished answers show three generated follow-up prompts when generation succeeds.
The prompts occupy three columns inside a card with a question icon and the heading "Suggested next...".
The centered token footer has a faint separator beneath it.
An unavailable captured page shows a loading failure.
Exact find shows the current match and total count.
A user message shows at most three lines, with an ellipsis, until "Show" is clicked. It then shows its full text and the toggle says "Hide".
A user message that holds the active conversation find match shows its full text.
When the page opens with a selected source, the transcript scrolls once to put that card in the middle of the view.
The board answer card has a pointer cursor and a deeper pink background under the mouse.
A source card has a pointer cursor and a light blue background under the mouse, unless it is selected.

## Constraints

Captured Markdown cannot execute HTML or create citation controls.
Page content and exact find state survive URL reload.
Page reads enforce the existing artifact ownership access check.
Citation cards omit tool diagnostics and publication metadata.
A bracket after a backslash, such as `\[D9]`, and a bracket in code are text, not citation handles.
A later edit of a file does not change the report of an earlier answer.
The search-term line is absent when its originating search cannot be reconstructed.
The answer omits redundant citation-status and tool-scope text.
