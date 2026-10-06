# `UI-ViewDocumentPage`: document view

## Key

| Tag | Meaning | Definition |
|---|---|---|
| `UI-ViewDocumentPage` | The document viewer route. | [Route inventory](Readme.md) |

`/view_document/:document_identifier/:doc_viewer_state/:viewer_right_tab_state`

Reads one document. `doc_viewer_state` stores the selected source and its view state.
`viewer_right_tab_state` stores the selected right-side tab. The table source stores its
sheet, sort, filters, hidden columns and page in `doc_viewer_state`.

## Controls

| id | control | does | constraint |
|---|---|---|---|
| `.table.columns` | visible-column control | opens the column visibility list | it opens one centred modal with a closing backdrop |
| `.table.column_filter` | column filter control | opens typed filter controls for one column | it opens one centred modal with a closing backdrop |
| `.table.sort` | column sort control | cycles ascending, descending and no order | the changed order resets the result page |
| `.table.sheet` | sheet selector | selects a workbook sheet | it clears sheet-specific columns, sorting and filters |
| `.source.dropdown` | source selector | selects a stored document source | it appears in the search preview and full viewer; a change resets the selected page |
| `.source.retry` | retry button | requests document sources again | it appears when the source request fails |

## States

| state | when | what the page shows |
|---|---|---|
| table loading | the table overview or page request is pending | a loading indicator |
| no visible columns | every sheet column is hidden | a message that directs the reader to the visible-column control |
| column modal | a visibility or filter control is open | one named modal above the grid, with keyboard focus inside it |
| email without body | the email parser stores no readable body | the envelope, attachments, and source selector remain available |
| source failure | the source request fails | an error and retry button appear |
| processing pending | no operation has reached the document | the page states that processing has not reached this document |
| processing active | its unfinished plan belongs to an active operation | the page states that processing runs |
| processing failure | its current operation recorded a file error | the page names the failed tasks |
| processing stopped | its unfinished plan belongs to an ended operation | the page names the operation state |
| processing complete without a source | the plan finished without a preview source | the page states that no text was found |

The PDF source list keeps the original PDF when its OCR variant query fails.
The source response reports the OCR query error beside the available source.
The Word text source precedes Extractous text for binary Word files.

## Constraints

- PDF source changes invalidate previous callbacks and dispose each viewer once.
- PDF disposal completes after its component is removed.
- A missing scroll strategy skips that scroll request and leaves the current viewer running.
- Opening a result in a new tab preserves the search preview and its find query.
- The column modal closes from its backdrop and Escape.
- The modal returns focus to its opening control.
- The application uses the light palette for either browser color preference.

The empty source selector stays hidden. A processing query failure remains separate from an empty extraction.

The Entities tab shows red flag excerpts with matched text marked.
Other signal hits remain in a closed pane.
The information control opens the read-only category and terms page in a new tab.
Document permission checks apply before signal evidence queries.
A signal query failure appears as an error.
