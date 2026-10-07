# Chat session

## Controls

| Control | Behavior | Constraint |
|---|---|---|
| Source card | Open its document or captured web page in the preview pane. | Web pages use the captured Markdown version. |
| Web source title | Open the source website in a new tab. | The captured preview stays available through the card. |
| Citation handle | Scroll to the source card beside this claim. | Repeated handles resolve within their answer. |
| Search-term line | Open the originating search with the cited document selected. | The line requires a query association in the stored trace. |
| Find exact text | Highlight exact, case-sensitive matches in the captured page. | Formatting boundaries can occur inside a match. |
| Previous match | Select and scroll to the previous exact match. | Selection wraps through the available matches. |
| Next match | Select and scroll to the next exact match. | Selection wraps through the available matches. |
| Close preview | Close the captured page pane. | The conversation stays open. |
| Tool group | Show or hide the tools, instructions, and superseded answers. | Completed groups start closed. |

## States

Citation cards appear beside their claims, in response order.
Bold and italic citation handles keep their source controls and validation.
A comma-separated citation group renders and verifies each handle.
Tables show each source card after its cited row.
Document cards contain the matching source excerpt.
Web cards show a linked title, domain, and verified source excerpt.
Top-level todo changes show numbered additions and struck-through removals.
The todo display includes completion and note changes.
Unverified document quotes retain their verification failure message.
An unavailable captured page shows a loading failure.
Exact find shows the current match and total count.

## Constraints

Captured Markdown cannot execute HTML or create citation controls.
Page content and exact find state survive URL reload.
Page reads enforce the existing artifact ownership access check.
Citation cards omit tool diagnostics and publication metadata.
The search-term line is absent when its originating search cannot be reconstructed.
The answer omits redundant citation-status and tool-scope text.
