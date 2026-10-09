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
| Search in conversation | Find messages containing the entered text and move between matches. | The count updates while typing. |
| Follow-up suggestion | Fill and focus the composer with the selected prompt. | The user edits or sends it explicitly. |
| Tool group | Show or hide the tools, instructions, and superseded answers. | Completed groups start closed. |

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
They use the same height as search result cards.
The card text shows at most three complete lines, with an ellipsis when text is omitted, and does not scroll.
Each passage in the card text opens its source on click, Enter, or Space.
The todo card shows the current bold goal and an unnumbered task list.
It uses white text on black and strikes through completed tasks.
Failed document quotes allocate no new handles.
Finished answers show three generated follow-up prompts when generation succeeds.
The centered token footer has a faint separator beneath it.
An unavailable captured page shows a loading failure.
Exact find shows the current match and total count.

## Constraints

Captured Markdown cannot execute HTML or create citation controls.
Page content and exact find state survive URL reload.
Page reads enforce the existing artifact ownership access check.
Citation cards omit tool diagnostics and publication metadata.
The search-term line is absent when its originating search cannot be reconstructed.
The answer omits redundant citation-status and tool-scope text.
