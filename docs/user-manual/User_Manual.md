# Hoover: user manual

Use this manual to search collections, read documents, browse folders, ask chat questions, and work with investigation boards.
[The administration manual](Admin_Manual.md) explains collection management and processing.
Your administrator supplies the site address and account access.

---

## Contents

1. [Getting in](#1-getting-in)
2. [The layout](#2-the-layout)
3. [Home](#3-home)
4. [Search](#4-search)
5. [Filters](#5-filters)
6. [Sorting and paging](#6-sorting-and-paging)
7. [Reading a document](#7-reading-a-document)
8. [Storage, browsing by folder](#8-storage-browsing-by-folder)
9. [AI chat](#9-ai-chat)
10. [Investigation boards](#10-investigation-boards)

11. [Sharing and bookmarking](#11-sharing-and-bookmarking)
12. [Review search and processing limits.](#12-review-search-and-processing-limits)

---

## 1. Getting in

Sign in through your deployment's sign-in page.
Your group memberships determine which collections you can read.
Ask your administrator when an expected collection is absent.
Administration controls appear only for accounts with administrator access.

---

## 2. The layout

Every page shares the dark rail down the left edge. From the top:

| icon | goes to |
|---|---|
| **H** | the home page |
| house | Home |
| magnifier | Search |
| folder | Storage (the file browser) |
| speech bubble | AI chat |
| bug (bottom) | report a bug or send feedback |
| person (bottom) | administration, for administrators only |

Hold the pointer over an icon to show its name beside it.

Some pages have a divider between two panes: search results and the preview, the storage
listing and the preview, the three panes of a document tab, and a conversation and its side
pane. Drag a divider to change the width of a pane, and double-click it to put it back. Each
width is remembered on this browser.

<a href="img/home.png"><img src="img/home.png" alt="Home page" align="right" width="560"></a>

---

<br clear="all">

## 3. Home

The landing page has two cards.

**Text Search** carries the search box. Type a term and press <kbd>Enter</kbd>, the box
submits on Enter, there is no separate button.

**AI Chat** links to a new conversation or to your earlier ones.

Below them is a feedback card. Its button opens the same report as the bug icon in the rail.

### Reporting a bug or sending feedback

<a href="img/feedback-form.png"><img src="img/feedback-form.png" alt="Feedback form with captured page and debug context" align="right" width="560"></a>

Select the bug icon at the bottom of the rail. The icon turns red while the browser copies the
page and draws an image of it. A full-screen form then shows the image, the size of the image
and of the page copy, the browser information and the browser log. Select **Bug** or
**Feedback**, write a title and a description, and select **Send**. You can paste links to
other pages of the application into the description. Frames, some canvases and some embedded
viewers can look different in the image, and the form names them when the page has them.

<br clear="all">

---

## 4. Search

Submitting a query opens the search page: the query box and toolbar across the top, the result
list on the left, and the document preview on the right.

<a href="img/search-results.png"><img src="img/search-results.png" alt="Search results for “easychair”" align="right" width="560"></a>

Reading a result card:

* the **number** in the left margin is the result's position in the whole result set. It keeps
  counting across pages, so page 26 starts at `501.`;
* the **title** is the document's filename;
* the **chip on the right** (`testdata_testfiles`, `enron_maildir`, …) is the *dataset* the
  document belongs to, written `<collection>_<dataset>`;
* the **snippet** is text from the document with your search terms highlighted in orange;
* the two buttons at the right of each card are **open in the full-page viewer** and the
  **actions menu**. See [result actions](#result-actions);
* under the two buttons are the **file size** and a **date**. The date is the latest date of
  the document when the list is sorted newest first, and its earliest date otherwise. A value
  that the index does not know leaves its line empty.

Clicking anywhere else on the card selects it and loads it into the preview pane on the right.

<br clear="all">

<a href="img/search-preview-pdf.png"><img src="img/search-preview-pdf.png" alt="A selected result previewed beside the list" align="right" width="560"></a>

<br clear="all">

### What you can type

<a href="img/search-repair.png"><img src="img/search-repair.png" alt="Uppercase Boolean query results" align="right" width="560"></a>

The image shows uppercase Boolean query results.

<br clear="all">

The query accepts these full-text operators.

| You type | The search does this. |
|---|---|
| `contract draft` | It requires both words. |
| `"exact phrase"` | It requires adjacent words in this order. |
| `contract -draft` | It excludes documents with `draft`. |
| `power \| energy` | It requires either word. |
| `comput*` | It matches this prefix. |
| `*pollut*` | It matches words containing at least three specified letters. |
| `dasovi?h` | It matches one varying character. |
| `dasovic%` | It matches zero or one character. |
| `"water pollution"~10` | It matches words within ten positions. |
| `"water pollution plant"/2` | It requires any two words. |
| `water NEAR/5 pollution` | It matches nearby words in either order. |
| `water NOTNEAR/5 pollution` | It excludes nearby occurrences of the second word. |
| `skilling << resigned` | It requires this word order. |
| `"(water \| sewage) plant"` | It accepts either word inside the phrase. |
| `"(water \| sewage) plant"~10` | It accepts either word inside the proximity search. |
| `"(water \| sewage) plant"/2` | It accepts an alternative inside the quorum search. |

Word forms do not match automatically. Search `contract \| contracts` or `contract*` to include both forms.
The search repairs unmatched quotes, brackets, and stray operator characters.
The normal result view does not display these repair details.
A short-infix notice explains the three-character minimum when it applies.
A query needs at least one positive word. Use `contract -draft` when you need an exclusion.

### Apply a search scope.

Open **Filter**, then **Collections**.
Select the datasets you need and apply the filter.
An empty query lists documents within the selected scope.
Your account must have access to at least one readable collection.
Clearing a dataset restriction returns to the permitted search scope.

### Move searches from legacy Hoover.

| Legacy input | Hoover4 instruction |
|---|---|
| `water AND pollution` | Hoover4 rewrites uppercase `AND` and requires both words. |
| `water OR sewage` | Hoover4 rewrites uppercase `OR` to `\|`. |
| `water NOT sewage` | Hoover4 rewrites uppercase `NOT` to exclusion. Keep a positive term. |
| `water and pollution` | Lowercase `and`, `or`, and `not` remain ordinary search words. |
| `from:john.smith@example.com` | The prefix is removed and the address becomes text. Use **Email Sender** for a sender restriction. |
| `to:john.smith@example.com` | The prefix is removed and the address becomes text. Use **Email Receiver** for a recipient restriction. |
| `filename:invoice.pdf` | Field-prefix syntax does not select a filename field. Search the filename text or use Storage name search. |
| `filetype:email` | Use the **File types** filter. |
| `@field value` | Field operators are unavailable. Use the corresponding filter. |
| `comput*` and `*pollut*` | Prefix and infix wildcards remain available. An infix needs at least three characters. |
| `word~1` | This is not a legacy fuzzy edit-distance query. A stray tilde becomes a separator. Use the documented wildcard operators. |
| `"water pollution"~10` | This is a phrase proximity query. The number describes word positions. |
| Earlier bookmarks | Recreate legacy queries with current filters. Legacy addresses have no automatic migration contract. |

The collection tools report query repairs to the assistant.
The normal search result view does not show the same repair notes.
Use the operator reference to interpret a repaired expression.
Public tags, private tags, stars, batch-search screens, and Nextcloud upload controls have no established current equivalent.
Use collection filters, document links, Storage, and the supported dataset ingestion procedure for the relevant current tasks.

### When no result is found

<a href="img/search-suggestions.png"><img src="img/search-suggestions.png" alt="Similar word suggestions for an empty result" align="right" width="560"></a>

The image shows similar word suggestions for an empty result.

<br clear="all">

The result area shows **No results** and the query.
A loading line appears while the search verifies similar indexed words.
When similar words have matches under your filters, buttons show their queries and document counts.
Select a button to search that query with the same filters.
When no suggestion exists, the page says that no similar words were found in the selected collections.
A partial notice identifies incomplete suggestions or search results. An empty query shows no suggestion section.

### Result actions

The **⋮** button on a result card opens a small menu:

<a href="img/result-menu.png"><img src="img/result-menu.png" alt="The per-result actions menu" align="right" width="560"></a>

* **Copy Document Link.** Puts a permanent link to this document on your clipboard.
* **Download Document.** Downloads the original file with its real name
  (`stanley.ec02.pdf`, not a hash).
* **Open in File Browser.** Jumps to [Storage](#8-storage-browsing-by-folder) with this
  document selected, so you can see what sits next to it on disk.

---

<br clear="all">

## 5. Filters

**Filter** in the toolbar opens the filter dialog. Select a pane on the left. Changes
accumulate across panes. The button at the bottom right applies them together and states how
many documents you will get.

**Clear all** (bottom left) drops every filter; **Cancel** closes without applying.

### Collections

Restrict the search to particular datasets. Counts are how many of your current results come
from each.

<a href="img/filter-collections.png"><img src="img/filter-collections.png" alt="The Collections pane" align="right" width="560"></a>

<br clear="all">

### File types

Broad categories, `text`, `email`, `html`, `code`, `pdf`, `doc`, `image`, `archive`, `other`.

<a href="img/filter-file-types.png"><img src="img/filter-file-types.png" alt="The File types pane" align="right" width="560"></a>

<br clear="all">

### Language

<a href="img/filter-language.png"><img src="img/filter-language.png" alt="Filter language" align="right" width="560"></a>

The image shows the filter language controls.

<br clear="all">

The languages detected in the documents' text. For an email, the language comes from its
body and not from its headers.

### Text source

<a href="img/filter-text-source.png"><img src="img/filter-text-source.png" alt="Filter text source" align="right" width="560"></a>

The image shows the filter text source controls.

<br clear="all">

Where the matching text came from: for example **Raw file text**, **Email body**, or an OCR
engine such as **OCR · Tesseract · eng**. Ticking a source keeps documents whose text from
that source matches the query.

### File size

Four ready-made bands, or your own range in megabytes.

<a href="img/filter-file-size.png"><img src="img/filter-file-size.png" alt="The File size pane" align="right" width="560"></a>

<br clear="all">

### File location

A folder tree. Ticking a folder finds **everything below it**, including files inside archives
and attachments inside emails.

<a href="img/filter-file-location.png"><img src="img/filter-file-location.png" alt="The File location pane" align="right" width="560"></a>

<br clear="all">

### Date

Four modes (*No filtering*, *Before…*, *After…*, *Between…*) plus **Unknown only** for
documents whose date could not be established. The histogram under them shows how your results
are spread over time, and **clicking a bar filters to that period**.

<a href="img/filter-date.png"><img src="img/filter-date.png" alt="The Date pane" align="right" width="560"></a>

A document matches when its earliest-to-latest confirmed date interval overlaps the selected range.
For example, confirmed dates in 2000 and 2010 make the document match a range in 2005.
This does not establish that the document contains an individual date in 2005.
**Unknown only** selects documents without a confirmed document date.
**Mentioned Date** filters dates extracted from document text and uses separate entity values.

<br clear="all">

### Email

Filter by **Sender** or **Receiver** address, with per-address counts, and a
*Email has attachments* switch.

<a href="img/filter-email.png"><img src="img/filter-email.png" alt="The Email pane" align="right" width="560"></a>

<br clear="all">

### Entities

People, organisations, locations and other names that were extracted from the documents
automatically. Pick one or several to keep only documents mentioning them.

<a href="img/filter-entities.png"><img src="img/filter-entities.png" alt="The Entities pane" align="right" width="560"></a>

<br clear="all">

### Red flags

<a href="img/filter-red-flags.png"><img src="img/filter-red-flags.png" alt="Filter red flags" align="right" width="560"></a>

The image shows the filter red flags controls.

<br clear="all">

Select **Red flags** in the filter dialog.
Select one or more categories and apply them.
Counts use the other active search restrictions.
A red flag directs document review and does not establish misconduct.
Open a matching document to inspect its scored passages and supporting signals.

### Applied filters

Once applied, the active filters are listed under the toolbar with a **Clear all** beside them,
and the toolbar's **Filter** button gains a count: `Filter (1)`.



---

## 6. Sorting and paging

**Sort** offers *Relevance*, *Date*, *File size* and *Name*.
The arrow changes direction for Date, File size, and Name.
Relevance always uses descending score order.

<a href="img/sort-menu.png"><img src="img/sort-menu.png" alt="The sort menu" align="right" width="560"></a>

> Choosing a sort marks your choice; press **Search** to put it into effect.

*Relevance* orders by the search score. With an empty query every document has the same
score, so choose *Date* to order such a list by time.

Paging is at the top right of the result list: arrows for previous and next, `1/51` for where
you are, and the up/down arrows next to `- / 1000` step through individual results without
leaving the page.

<br clear="all">

<a href="img/search-pagination.png"><img src="img/search-pagination.png" alt="The second page of a result set" align="right" width="560"></a>

**Only the first 1 000 results of any search can be opened**, however many were found. If your
search matches more than that, narrow it with [filters](#5-filters) rather than paging.

---

<br clear="all">

## 7. Reading a document

Selecting a result opens the viewer, either in the right-hand pane or full-page. Three columns:

* **left**: search within this document, and the list of *sources*;
* **middle**: the document itself;
* **right**: the **Entities**, **File Locations**, and **Metadata** tabs.

<a href="img/document-text.png"><img src="img/document-text.png" alt="A text document with its entities" align="right" width="560"></a>

<br clear="all">

### Sources

<a href="img/document-archive.png"><img src="img/document-archive.png" alt="Archive member file locations" align="right" width="560"></a>

The image shows archive member file locations.

<br clear="all">

One file can be readable in several ways, and each way is a source you can switch between:

| source | what it is |
|---|---|
| **Extracted text** | the text a general extractor pulled out |
| **Plain text** | the raw file as text |
| **Email** | the message rendered as an email, subject, addresses, date, body |
| **Email body** | the selected parsed body |
| **PDF** | the real PDF, rendered page by page |
| **PDF · OCR · Tesseract · eng** | the same PDF after optical character recognition |
| **PDF text** | the text layer, without the page images |
| **PDF OCR · Tesseract · eng** | OCR text from selected PDF pages |
| **PDF preview** | a PDF preview of a supported Office document |
| **PDF preview · OCR · Tesseract · eng** | a searchable Office preview |
| **Preview OCR · Tesseract · eng** | a searchable image preview |
| **Office XML** | a `.docx` / `.odt` rendered from its XML |
| **Image** / **OCR · Tesseract · eng** | the picture, and the text read out of it |
| **Table** | a spreadsheet or delimited-text grid with sheet and column controls |
| **File Locations tab** | every path in the collection where this exact content appears |

A PDF gets the full viewer, page navigation, zoom, and the page counter at the bottom right:

<a href="img/document-pdf.png"><img src="img/document-pdf.png" alt="A PDF in the viewer" align="right" width="560"></a>

PDF navigation uses document page numbers across all parts.
The viewer loads the required part when you change pages.
Complete PDF downloads include every part.

An image shows its dimensions next to the source, and the OCR variant shows what was read out
of it. A browser shows only some image formats. For the others, such as HEIC, TIFF and SVG,
the pipeline stores a JPEG copy, and the viewer and the text recognition use that copy. A
video shows its first frame before you start it. When an image has no such copy and the
browser cannot show it, the viewer gives a link that downloads the file.

<br clear="all">

<a href="img/document-image-ocr.png"><img src="img/document-image-ocr.png" alt="A scanned image and its OCR" align="right" width="560"></a>

A file found inside an archive shows its container in the breadcrumb, here `parent.zip` above
`parent/child.txt`:



Select the **File Locations** tab to list the paths that contain the same content.
Use a path control to open its folder or copy the path.

<br clear="all">

<a href="img/document-file-locations.png"><img src="img/document-file-locations.png" alt="The File locations source" align="right" width="560"></a>

<br clear="all">

### Searching inside a document

The box at the top left of the viewer searches the open document. Matches are highlighted and
the arrows beside the counter step between them.

### Entities

The right pane groups extracted names and structured values by category.
Model groups include **People**, **Organizations**, **Locations**, and **Misc**.
Structured categories include addresses, identifiers, amounts, and mentioned dates.
Counts include all sources. Use the box at the top to filter the list.

### Inspect an entity and its passages.

<a href="img/document-red-flags.png"><img src="img/document-red-flags.png" alt="Scored red flag passages" align="right" width="560"></a>

The image shows scored red flag passages.

<br clear="all">

<a href="img/document-entity.png"><img src="img/document-entity.png" alt="Document entity" align="right" width="560"></a>

The image shows the document entity controls.

<br clear="all">

<a href="img/red-flag-terms.png"><img src="img/red-flag-terms.png" alt="Red flag terms" align="right" width="560"></a>

The image shows the red flag terms controls.

<br clear="all">

Select a structured entity value in the document pane to open its explainer.
Read the validated value, type, and detail rows.
Validation establishes the recorded property, such as a checksum, and does not establish ownership or authenticity.
Use source counts and matching passages to locate the extracted value.
Follow the available links to search that entity in permitted collections.

Open the red flag section to read the scored passages.
Expand a passage to inspect its supporting signals and source text.
Open **Red flag terms** to inspect the categories and terms used for scoring.

### Read a spreadsheet or table.

<a href="img/document-table.png"><img src="img/document-table.png" alt="Document table" align="right" width="560"></a>

The image shows the document table controls.

<br clear="all">

<a href="img/table-sheets.png"><img src="img/table-sheets.png" alt="Table sheets" align="right" width="560"></a>

The image shows the table sheets controls.

<br clear="all">

<a href="img/table-filter.png"><img src="img/table-filter.png" alt="Table filter" align="right" width="560"></a>

The image shows the table filter controls.

<br clear="all">

Select **Table** in the source list.
Choose a sheet from the sheet control.
Enter text in the cell search control to locate matching cells.
Cell search applies to the selected table and is separate from collection search.
Open a column control to inspect its values and apply a text, number, or date filter when available.
Select a column sort direction to order the matching rows.
Use the column controls to hide columns and restore them when needed.
Use the page controls to read additional rows.
Open a long cell value to read its complete stored text.
The server returns at most 200 rows and 60 visible columns per request.
A clamp or extraction notice describes a limit that affected the returned table.

### Read connected email.

<a href="img/connected-emails.png"><img src="img/connected-emails.png" alt="Connected email graph and selected message" align="right" width="560"></a>

The image shows connected email graph and selected message.

<br clear="all">

Select the **Email** source to read the subject, addresses, date, body, and attachments.
Expand header details when you need the complete stored headers.
Select an attachment to open its document.
Open the connected-email control to show the graph centered on this message.
Select a message node to read it in the preview.
Reply links show stored message relationships.
Time placement uses known message dates, while messages without known dates remain identified separately.
The graph contains at most 50 messages and traverses at most three relationship levels.
An absent message can be outside those limits. Search for it separately before concluding that it is absent from the collection.

### Metadata

<a href="img/document-metadata.png"><img src="img/document-metadata.png" alt="Document metadata" align="right" width="560"></a>

The image shows the document metadata controls.

<br clear="all">

The **Metadata** tab holds everything the pipeline knows about the file: its dates and why they
are trusted, email headers, blob hashes and size, and the detected file types.

A PDF defect appears as `passworded` or `damaged` in its metadata.
The pipeline retains that metadata and skips later PDF processing.

### Downloading

**Download Document** in the ⋮ menu, or the same item in the viewer's own menu, saves the
original file under its real name.

---

## 8. Storage: browsing by folder

The folder icon in the rail opens **Storage**: the corpus as it is laid out on disk.

The landing page shows one card for each collection, with the same tree in the pane on the
left. A card shows the number of datasets and the summed documents, total size, indexed
documents and processing errors of those datasets. A card marked Processing belongs to a
collection whose data is changing.

<a href="img/storage-collections.png"><img src="img/storage-collections.png" alt="Storage, all collections" align="right" width="560"></a>

Choosing a collection shows a card per dataset with its document count, total size, how many
are indexed, and how many hit processing errors. The pipeline counts these numbers during and
after processing. A dataset that it has not counted yet says so.

<br clear="all">

<a href="img/storage-collection.png"><img src="img/storage-collection.png" alt="A collection&#x27;s datasets" align="right" width="560"></a>

Choosing a dataset lists its contents, folders first, with **Files** and **Size** columns.
Files counts nested archive members and email attachments under each path.
Size counts bytes at the current container level, so archive members do not add their bytes to the archive size again.
Unavailable statistics remain unavailable until the pipeline computes them.
Select a file to open its preview beside the listing.

<br clear="all">

<a href="img/storage-folder.png"><img src="img/storage-folder.png" alt="Inside a dataset" align="right" width="560"></a>

<br clear="all">

### The tree

In the left pane, the chevron opens a row and the label navigates to it, two separate
gestures, so you can look inside a folder without leaving the one you are in.

Large folders are summarised rather than dumped: a folder of 150 mailboxes shows the first
twenty and then `129 more below…`, which expands the rest on demand.

Deep paths are summarised the same way, in the other direction: the top of the path stays
put, the middle collapses into `35 more levels…` (click it to see them all), and the rows
around the folder you are in keep stepping in, so the chain reads as a chain however far
down it goes. Each of those rows also states its true depth in a `depth N` badge.

Drag the divider on the right edge of the pane to make it wider, and double-click the
divider to put it back. The width is remembered on this browser.

<a href="img/storage-tree-deep.png"><img src="img/storage-tree-deep.png" alt="A deep folder chain in the tree" align="right" width="560"></a>

<br clear="all">

### Finding a file by name

<a href="img/storage-open-in-search.png"><img src="img/storage-open-in-search.png" alt="Folder scope opened in Search" align="right" width="560"></a>

The image shows folder scope opened in Search.

<br clear="all">

The box above the listing filters the **names** of files under the current folder. It does not
search their contents. `HOUSE` finds `HOUSE_OVERSIGHT_010560.txt`; searching for a word that
only appears *inside* the documents will find nothing.

<a href="img/storage-folder-search.png"><img src="img/storage-folder-search.png" alt="Filtering a folder by filename" align="right" width="560"></a>

For content, use **Open in Search**, which carries the current folder over as a *File location*
filter:



---

<br clear="all">

## 9. AI chat

The speech-bubble icon opens a new conversation.



The Internet tools option permits web searches and browser reads.
With this option off, the assistant reads the selected collections.
Your deployment can hide internet tools when they are unavailable.
The option stays fixed after the first message.
Start a new conversation to change it.

You do not choose a model. The deployment configuration sets the model of every chat.

A long message of yours shows its first three lines. **Show** in its top-right corner shows the
whole message, and **Hide** cuts it to three lines again. **Search in conversation** finds
text in the messages of the conversation, and its arrows move between the matches.

### While it works

The assistant announces each tool it uses as it goes (`list_collections`,
`search_collections`, `web_search`, `browser_navigate`), and shows a turning icon and
*The bot is working...* with a **■** stop button until the answer arrives.



Wait while the progress controls show active work.
Use the stop button to cancel the active turn.
Response time depends on the question, selected collections, model, and available services.

### Reading the answer

Tool results are shown inline. A collection search renders the documents it found as cards you
can click through to the viewer; each block has an **Expand** control.



Scroll to the end of the turn to read the answer.
Expand a tool group to inspect its work and returned documents.
Select an inline citation or source card to open its supporting document or captured web page.
Document citations can identify a source and page. Verify the cited passage before using the answer.

### When it fails

If the assistant cannot finish, the turn ends with a message saying so, and tells you whether
earlier attempts also failed.



### Continue a conversation.

Select a follow-up suggestion to copy its text into the composer.
Review or change the text, then send it.
When the assistant asks a question, choose an offered answer or enter your own response.
Context notices describe summaries used for long conversations.
Expand a notice to inspect its details and displayed token counts.
A summary can omit earlier detail. Repeat a source or requirement when it remains necessary.

### Earlier conversations

**History** lists your past chats by their auto-generated titles; opening one restores the whole
transcript.
Use the history deletion control to delete a conversation you no longer need.
Chats remain stored until a person deletes them.



## 10. Investigation boards

An investigation board works on one or more goals over your collections for a long time,
without you in the conversation. The board splits the goals into intents, explores each intent
in a chat of its own, and writes each finding with its sources. The boards show on
the right of the AI chat page, each with its title, its status, a small picture of its graph
and a short summary.

### Create a board.

<a href="img/board-create.png"><img src="img/board-create.png" alt="Board create" align="right" width="560"></a>

The image shows the board create controls.

<br clear="all">

 **New board** asks for a title, one to six goals, the background context
(what the board should know before it starts), the collections and first hints. The collections
cannot change later.

### Read the graph.

 The board page shows a graph on the left and the selected card on the
right. The graph reads from the background context on the left to the goals on the right. Each
card names its type in its lower-left corner and its status in its lower-right corner:

| Card | What it is |
|---|---|
| background | The collections and the background context of the board. White with a black border. |
| goal-01, goal-02 | A goal. Blue. It says answered when you accepted its answer, and answer proposed while an answer waits for you. |
| intent | A direction that the board explores, with its state: open, running, concluded, failed, question or cancelled. |
| finding | A finding: sourced (a document supports it), inferred, or not found. |
| correction | Your correction of a rejected answer or review. |

Drag the graph to move it, and use **-** and **+** in its lower-right corner to zoom out and in.
Click a card to see it in full on the right. The address of the page names the selected card,
so you can send it as a link. **Show the board overview** over the top-right corner of the
graph returns to the overview.

### Read findings and ask questions.

 A finding shows its text with its source cards. A source card opens the
explore chat of the finding in a new tab, with that document open. **Open the explore chat**, at
the right of the title, opens the whole chat. A finding lists its open questions, each in its own
card. **Explore this question**, in the corner of the card, asks the board to explore it at
once. The board keeps its status: on a complete board only that explore runs. The card then
links to the intent that explores it. To ask your own question about a finding or the
background context, write it under the card and click **Ask**. An explore answers it as a new
finding, and the card lists your question with its intent. A question does not hold the board
open. When the board must answer it before it is complete, add it as a goal. Write why a finding is wrong and click **Reject finding**, or
**Reject correction** on a correction. The board stops using it. The intent that made the finding
stays.

### Review answers and change settings.

 In the overview:

- **Add goal** adds a goal at any time, also after the board is complete. The board then works
  on the new goal.
- **Add hint** gives the next assessment a hint. A hint also answers an explore that asked you
  a question.
- An assessment can propose answers for some goals and continue to work on the others. When
  every open goal has a proposed answer, the board waits for your review. Each goal shows its
  proposed answer, in the overview and when you select the goal. An answer whose findings are
  all searches that found nothing says that the records do not answer the goal. Accept it to
  record that, or reject it to continue the investigation. **Accept answer** keeps the
  answer, also when later work starts the board again. Write why an answer
  is wrong and click **Reject answer**: the board continues at once with your correction, and
  the other answers wait for you. When every goal has an accepted answer, the board is
  complete. **Close the board** accepts every proposed answer and stops the board.
  **Continue with a correction** gives it your correction, and it continues.
- **Settings** turns the internet tools on or off for later explores, pauses and resumes the
  board, and drops it.
- A button stays gray until the board has taken your action. When the board refuses it, for
  example because a newer assessment replaced the answer, the reason shows above the board.

### Read the explore budget.

 A board starts with 30 explores. Each goal after the first adds 25,
and each hint, question and correction adds 4. A board never uses more than 300 explores, so
near that limit an action adds less, and the event line says how much the budget grew. When
the explores reach the budget, the board makes one last assessment of its findings and then waits
for your review. **Reopen with 50 more explores** continues the open goals and keeps the findings
and the accepted answers. Near the limit the button names the explores that it adds, and at
a budget of 300 it says **Reopen with the remaining budget**. A complete board with a goal
that has no accepted answer shows the same button. A board that used 300 explores starts no
more work, and its page links to a new board.

### Read events and statistics.

 The **Events** table lists the newest 200 actions, newest first, and
**Show all** lists every action. Your own actions
show your name in bold. The last column links to the explore chat of the row (**Open**, in a new
tab), or to the card that the row names. An assessment is the step that reads the board and
decides the next intents or proposes the review. **Show details** on an assessment row shows
its prompt and its response. **Statistics** under the events counts the explores, the
assessments, the intents and the findings.

A board chat has an **Investigation Board** link at the right of its search row, and the
pink card at its end opens the board with that chat's finding selected.

---

## 11. Sharing and bookmarking

Copy a view address to share its query or selected item:

* a search carries its query, filters, sort, page and selected document, so sending someone a
  search sends them the exact search;
* a document has a permanent link, from *Copy Document Link* in the ⋮ menu;
* a chat conversation has one too.

Recipients need permission to read the selected collections.
Chats belong to their owner, so copying a chat address does not grant another account access.
Board addresses also require the owning account.
Earlier Hoover4 search fields can take their current defaults when a bookmark omits them.
Legacy Hoover URLs do not automatically migrate to Hoover4.
A route that cannot be decoded shows **Page not found**.

<a href="img/not-found.png"><img src="img/not-found.png" alt="The not-found page" align="right" width="560"></a>

---

<br clear="all">

## 12. Review search and processing limits.

These are properties of how search works here, not faults, and each has a visible sign on
the page.

**Only the first 1 000 documents of a match are reachable.** A corpus-wide query can report
tens of thousands of documents found over a pager that ends at 1 000: the count is the size
of the whole match, and the pager is what you can walk. The page states the difference beside
the count rather than implying the rest are reachable. Narrow the query (with words, a
filter, or a folder) to bring what you want inside the reachable range.

**Assistant tools can continue results.** When a collection tool returns a `more` handle, the assistant can call `read_more`.
The handle belongs to the same user, conversation, and run.
Continuation follows the original search window and does not remove the backend result limit.
Full-text document search can reach the first 1,000 matching documents.
Passage retrieval has a separate per-query limit, which defaults to 15 and follows deployment configuration.
Ask a narrower question when the available results do not cover the required material.

**A document with no confirmed date can never fall inside a date range.** It matches only
through the *no confirmed date* option, which is why that option exists alongside before,
after and between. A range that silently included undated documents would be a different
question from the one you asked.

**Filter counts are counts within the rest of the query**, not counts in the corpus. A chip
showing 12 means twelve documents among those that already match everything else you have
set.
