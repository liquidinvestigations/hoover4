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

## States

| state | when | what the page shows |
|---|---|---|
| table loading | the table overview or page request is pending | a loading indicator |
| no visible columns | every sheet column is hidden | a message that directs the reader to the visible-column control |
| column modal | a visibility or filter control is open | one named modal above the grid, with keyboard focus inside it |

## Constraints

- PDF source changes invalidate previous callbacks and dispose each viewer once.
- PDF disposal completes after its component is removed.
- Opening a result in a new tab preserves the search preview and its find query.
- The column modal closes from its backdrop and Escape.
- The modal returns focus to its opening control.
- The application uses the light palette for either browser color preference.
