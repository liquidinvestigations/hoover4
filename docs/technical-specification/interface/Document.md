# `UI-ViewDocumentPage`: document view

## Key

| Tag | Meaning | Definition |
|---|---|---|
| `UI-ViewDocumentPage` | The document viewer route. | [Route inventory](Readme.md) |

`/view_document/:document_identifier/:doc_viewer_state/:viewer_right_tab_state`

Reads one document. `doc_viewer_state` stores the selected source and its view state.
`viewer_right_tab_state` stores the selected right-side tab. The table source stores its
sheet, sort, filters, hidden columns and page in `doc_viewer_state`. A text source stores
its explicit stored page identifier in `selected_source_page`, and its selected match in
`selected_match`. That match applies only to its own source, page and find query.

## Controls

| id | control | does | constraint |
|---|---|---|---|
| `.table.columns` | visible-column control | opens the column visibility list | it opens one centred modal with a closing backdrop |
| `.table.column_filter` | column filter control | opens typed filter controls for one column | it opens one centred modal with a closing backdrop |
| `.table.sort` | column sort control | cycles ascending, descending and no order | the changed order resets the result page |
| `.table.sheet` | sheet chooser dialog | selects a workbook sheet, and shows the matching rows of each sheet while the find box holds a search | it clears sheet-specific columns, sorting and filters. With a search and no chosen sheet, the viewer opens on the first sheet with matches |
| `.table.cell` | table cell text | it shows selectable text spans without a click action | each cell shows an excerpt of at most five lines in a monospaced font |
| `.table.cell_full` | `Open full cell` control | opens a modal over the page area with the raw value and the cell details | it appears on a cell whose value uses three or more lines |
| `.source.dropdown` | source selector | selects a stored document source | it appears in the search preview; the full viewer uses the source list; a change resets the selected page and match. PDF sources use stored document ranges and preserve their identity after manifest refresh. A source count shows an exact count, a lower bound with `+`, or a failure mark. A failed or timed-out count never shows as zero. |
| `.text.page` | text page group: previous and next arrows, the unit with an editable identifier, and the stored position | opens a stored page of the selected text source | it appears in every text viewer, including the email body. The unit is Page for PDF text and PDF OCR text, Text segment for size-based segments, and Entry for unknown numbering. Enter or leaving the field commits a valid identifier once, Escape restores the shown identifier, and an invalid entry stays for correction. An identifier without stored text stays selected and offers its stored neighbours. The position counts stored entries, so identifiers 3, 7 and 12 show page 12 as 3 of 3 |
| `.text.match` | match group: previous and next match arrows and the editable match number of the page | selects a find-query match | the number counts the matches of the displayed page. At the first or last match of a page, the arrows open the nearest matching page of the same source in page order, and they stop at both ends of the source |
| `.text.content_pages` | `Previous` and `Next` page buttons after the text | open the adjacent stored page | they use the targets of the page group, and the unavailable one is disabled |
| `.text.retry` | retry button beside a failed text request | requests the same page again | the previous page text stays visible |
| `.find.clear` | clear search button | clears the in-document query | the main search, document find, and folder search share the input control |
| `.table.clear_filters` | clear filters button | clears the document query and column filters | it appears when filters return zero rows |
| `.source.retry` | retry button | requests document sources again | it appears when the source request fails |
| `.archive.browse` | `Browse the archive` link on the Archive or Email Archive tab | opens the file browser inside the archive | it appears when the extraction created the archive's folder |

## States

| state | when | what the page shows |
|---|---|---|
| table loading | the table overview or page request is pending | a loading indicator |
| text page loading | a requested text page has not loaded | the previous page stays, and a status beside the page group names the requested page. Before the first page loads, a loading indicator |
| text page failure | a text page request fails | the previous page stays, with the error and the retry button above it |
| text page absent | the requested identifier has no stored text | a statement that no text is stored there, with the page group and the page buttons on its stored neighbours |
| text match failure | a match search or highlight read fails | the error appears beside the match group or above the text, and page navigation and raw text stay usable |
| no visible columns | every sheet column is hidden | a message that directs the reader to the visible-column control |
| column modal | a visibility or filter control is open | one named modal above the grid, with keyboard focus inside it |
| full-cell modal | the full-cell control is open | the raw value in a scrolling area, with column, row, sheet, type, exact integer, formula, link, dataset and document hash; empty values are omitted |
| email without body | the email parser stores no readable body | the envelope, attachments, and source selector remain available |
| source failure | the source request fails | one row above the viewer holds the error and the retry button, and the sources that loaded stay available |
| image preview | the image format has a stored JPEG preview | the viewer shows the preview |
| archive | the document is an archive or a mail store | the Archive or Email Archive tab opens first, with the extracted file count and size, the archive file size and dates, and the dates inside. The empty-source message is not shown |
| image not shown | the browser cannot show the image and no preview exists | a note and a link that downloads the file |
| processing pending | no operation has reached the document | the page states that processing has not reached this document |
| processing active | its unfinished plan belongs to an active operation | the page states that processing runs |
| processing failure | its current operation recorded a file error | the page names the failed tasks |
| processing stopped | its unfinished plan belongs to an ended operation | the page names the operation state |
| processing complete without a source | the plan finished without a preview source | the page states that no text was found |

The PDF source list keeps the original PDF when its OCR variant query fails.
The source response reports the OCR query error beside the available source.
The Word text source precedes Extractous text for binary Word files.
OCR PDF sources precede the original PDF and the PDF preview.

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
The Red flags heading opens the read-only category and terms page in a new tab.
The terms page scrolls across the full content width.
Document permission checks apply before signal evidence queries.
A signal query failure appears as an error.

Email header values use the body highlight engine.
A matching header value opens the details panel.
Entity cards show the value before the category.
Entity counts state that they include all sources.
Text hit navigation finds the current rendered span after query, source, or page changes.
A link without a text page opens the first matching page for a find query, and otherwise the first stored page.
An explicit text page takes precedence over automatic match selection, and clearing the query keeps it.
Explicit page navigation moves the text to its start. Match navigation moves the selected match into view after its page renders.
Count updates and ordinary renders do not move the text.
A late response for an earlier document, source, page or query does not replace the displayed page.
A match step reads index rows of the selected source only, in batches, so the matches after the first 1,000 matching pages stay reachable.
A match step skips index rows whose page has no stored text and returns each page once.
A match action reads at most 4 match steps. An action that reads its allowance shows "Search incomplete", and the next action in that direction continues from its boundary. A step in progress shows "Searching", and a failed step shows "Match search failed" with Retry.
A change of document, source, query or page stops the match steps of the earlier state, and their late results change nothing.
Highlights come from an index row only when its text without the highlight markers equals the stored page. Otherwise the stored page shows without highlights, with the note "The search index holds another version of this page."
A source match count counts only index rows whose text equals the stored page. A source whose index holds another version shows `?` in place of a count.
PDF pointer coordinates remain correct at each browser zoom.
The email headers, expanded details, attachments and body share one scroll container.
A filename-only search match opens the table without a row filter.

Table find searches cells for the words that the search engine matched in the document, and for the find text without its double quotes.
A matched run that crosses a cell or row break splits into one term for each cell.
Match counts, sheet counts, row filters, and cell highlights use the same terms.
Unicode case folding preserves the original text offsets during highlighting.
A table cell excerpt has at most five lines of at most 80 display columns.
A wide character uses two columns.
The excerpt centres on the first match in the cell, and an ellipsis marks omitted text.
Explicit line breaks in the value stay in the excerpt.
A cell keeps its natural height when its value needs fewer than five lines.

The grid moves its first rendered match into view with one smooth scroll of the grid.
Opening a searched table, a new find text, a sheet choice and a pager click each request this movement.
Repeated renders, manual scrolling, sort changes and filter changes do not move the grid.

PDF page input and arrows use document page numbers across source part boundaries.
The viewer requests the required part and preserves zoom and selection coordinates.
PDF search reads all relevant parts and maps each hit to its document page.
Searchable sources include retained native text and their own OCR text.
Image Preview OCR precedes the image source.
Complete multipart downloads use temporary assembly with access verification and cancellation cleanup.
