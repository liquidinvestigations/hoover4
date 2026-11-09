# `UI-ViewDocumentPage`: document view

## Key

| Tag | Meaning | Definition |
|---|---|---|
| `UI-ViewDocumentPage` | The document viewer route. | [Route inventory](Readme.md) |

`/view_document/:document_identifier/:doc_viewer_state/:viewer_right_tab_state`

Reads one document. `doc_viewer_state` stores the selected source and its view state.
`viewer_right_tab_state` stores the selected right-side tab. The table source stores its
sheet, sort, filters, column selection and page in `doc_viewer_state`. The column selection is
automatic or a chosen list. An older link with a list of hidden columns still opens. A text source stores
its explicit stored page identifier in `selected_source_page`, and its selected match in
`selected_match`. That match applies only to its own source, page and find query.

## Controls

| id | control | does | constraint |
|---|---|---|---|
| `.table.columns` | visible-column control | opens the column visibility list with `N of 60 shown`, `Show the first 60` and `Hide all` | it opens one centred modal with a closing backdrop. The grid shows at most 60 columns. At 60 shown columns, the boxes of hidden columns are disabled. The automatic selection shows the first 60 columns, or the columns with matches of the find text when such columns exist |
| `.table.notice_close` | `Close this notice` control on the truncation notice | hides the notice for the open document | the notice names each storage limit that the parse reached, for example a cut cell |
| `.table.column_filter` | column filter control | opens typed filter controls for one column | it opens one centred modal with a closing backdrop |
| `.table.sort` | column sort control | cycles ascending, descending and no order | the changed order resets the result page |
| `.table.sheet` | sheet chooser dialog | selects a workbook sheet, and shows the matching rows of each sheet while the find box holds a search | it clears sheet-specific columns, sorting and filters. With a search and no chosen sheet, the viewer opens on the first sheet with matches |
| `.table.cell` | table cell text | it shows selectable text spans without a click action | each cell shows an excerpt of at most five lines in a monospaced font |
| `.table.cell_full` | `Open full cell` control | opens a modal over the page area with the raw value and the cell details | it appears on a cell whose value uses three or more lines |
| `.source.dropdown` | source selector | selects a stored document source | it appears in the search preview; the full viewer uses the source list; a change resets the selected page and match. A picked source stays. In an email, the preview selects the first match of that source. A source without a match shows no highlight. PDF sources use stored document ranges and preserve their identity after manifest refresh. A source count shows an exact count, a lower bound with `+`, or a failure mark. A failed or timed-out count never shows as zero. |
| `.email.match` | email match group: previous and next match arrows and the counter `n / N` | selects a header or body match of the email in document order | it replaces the text match group in an email. N counts the matches of the document in all sources. The Email source shows header matches and email parser body matches. Without a selected match in the displayed source, the counter shows `0 / N`. Then the next arrow opens the first match of the document. The previous arrow opens the last match. The source changes to the source of that match |
| `.text.page` | page overlay in the lower-right corner of the text viewport: the editable identifier, the stored position, and the previous and next icon buttons, in a vertical stack | opens a stored page of the selected text source | it appears in every text viewer, including the email body, when the loaded source has more than one stored entry. It does not appear before the source metadata loads, for an empty source, or for a source with one entry. The unit is Page for PDF text and PDF OCR text, Text segment for size-based segments, and Entry for unknown numbering, and it names the field and the buttons for a screen reader. Enter or leaving the field commits a valid identifier once, Escape restores the shown identifier, and an invalid entry stays for correction. The buttons open the stored predecessor and successor. The position counts stored entries, so identifiers 3, 7 and 12 show identifier 7 as `2/3`. An identifier without stored text stays selected with the position `-/3`. The text keeps space below its last line, so the overlay does not cover it at the end of the scroll |
| `.text.match` | match group: previous and next match arrows and the editable match number of the page | selects a find-query match | the number counts the matches of the displayed page. At the first or last match of a page, the arrows open the nearest matching page of the same source in page order, and they stop at both ends of the source |
| `.text.sole_page` | link to the sole stored identifier in the absent-page text | opens the only stored entry of the source | it appears when a link selects an absent identifier of a source with one stored entry, which has no page overlay |
| `.text.retry` | retry button beside a failed text request | requests the same page again | the previous page text stays visible |
| `.find.clear` | clear search button | clears the in-document query | the main search, document find, and folder search share the input control |
| `.table.retry` | retry button beside a failed table read | repeats the overview, page, sheet-count, and column-count requests | generation changes require a fresh overview |
| `.table.clear_filters` | clear filters button | clears the document query and column filters | it appears when filters return zero rows |
| `.source.retry` | retry button | requests document sources again | it appears when the source request fails |
| `.archive.browse` | `Browse the archive` link on the Archive or Email Archive tab | opens the file browser inside the archive in a new tab | it appears when the extraction created the archive's folder |
| `.archive.search` | search link after `Browse the archive` | opens the search page in a new tab, filtered to the archive folder as the `file_paths` parent and to the dataset of the archive | it appears when the archive folder has a search term. The translated text identifies ZIP files separately from other archives |

## States

| state | when | what the page shows |
|---|---|---|
| table loading | the table overview or page request is pending | a loading indicator |
| table failure | an overview, page, sheet-count, column-count, or column-value request fails | the error and a retry action |
| text page loading | a requested text page has not loaded | the previous page stays, and a status in the page overlay names the requested page to a screen reader. Before the first page loads, a loading indicator and no page overlay |
| text page failure | a text page request fails | the previous page stays, with the error and the retry button above it |
| text page absent | the requested identifier has no stored text | a statement that no text is stored there. The page overlay opens its stored neighbours. A source with one entry has no overlay, and the statement links its sole stored identifier |
| text match failure | a match search or highlight read fails | the error appears beside the match group or above the text, and page navigation and raw text stay usable |
| no visible columns | the chosen column list is empty | `No column is shown. Use the Columns button to show one.` |
| column modal | a visibility or filter control is open | one named modal above the grid, with keyboard focus inside it |
| full-cell modal | the full-cell control is open | the raw value in a scrolling area, with column, row, sheet, type, exact integer, formula, link, dataset and document hash; empty values are omitted |
| email without body | the email parser stores no readable body | the envelope, attachments, and source selector remain available |
| source failure | the source request fails | one row above the viewer holds the error and the retry button, and the sources that loaded stay available |
| image preview | the image format has a stored JPEG preview | the viewer shows the preview |
| archive | the document is an archive or a mail store | the Archive or Email Archive tab opens first, with one metadata section titled with the archive kind. Its rows give the extracted file count and size, the archive file size and dates, the dates inside, and the processing errors. Counts and sizes show in `code`, and an unknown value shows as `Unknown`. The empty-source message is not shown |
| image not shown | the browser cannot show the image and no preview exists | a note and a link that downloads the file |
| OCR detection | the Metadata tab is open and the OCR detection stage examined the document | an OCR detection section at the top of the tab, with the pages with text, the examined pages, and each detected language and script with its page count |
| antivirus | the Metadata tab is open | an Antivirus section with the effective verdict, or the status of the latest attempt when no scan completed, and the engine, signature database and scan time. An `infected` file shows `Virus found: <signature>.` in red, and the more-actions menu shows `Download Document` crossed out. The raw `virus_scan_results` table lists every attempt |
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
- Each opened source initializes its controller once. Repeated layout events preserve the controller, page, search, and zoom subscriptions.
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
Selecting a header match opens the details panel before scrolling to its marked span.
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
Highlights require an exact match against the stored page or its deterministic index projection. The projection trims outer whitespace and limits encoded runs. Mapped highlights preserve complete source text and omit removed encoded content. Stale or malformed highlights remain unavailable.
A source match count requires exact stored text or its verified deterministic index projection. A source whose index holds another version shows `?` in place of a count.
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

## Match target response

The backend match response identifies the document and find query.
Header targets identify the field, occurrence, and character span.
Equal recipient values retain distinct occurrence identities.
Body targets identify the extractor, page, and match ordinal.
Count completeness distinguishes complete, limited, and unavailable validation.
Request failures remain errors.

## Email graph response

The graph reader groups exact file hashes across readable collections.
Each logical node retains its readable collection, dataset, and file occurrences.
Removed VFS occurrences do not appear.
The selected readable occurrence remains the representative.
A removed selected occurrence returns an error.
Node limits apply after grouping, and occurrence expansion has a separate limit.
The response reports occurrence truncation and count completeness.
Conflicting nonidentical files remain separate.

Email header and body matches share one navigator across the text sources.
Header targets occur once before body targets in extractor, page, and match order.
The navigator selects the required source and page before revealing a body match.
Equal recipient values retain distinct field and occurrence identities.
Previous and next actions wrap within the validated target list.
Loading, failure, limited counts, and unavailable validation remain separate states.
The URL retains the selected target across source changes.

Table pages, sheet counts, column counts, and column values report their actual published generation.
The viewer rejects a reply whose document, request identity, or generation differs from the current view.
