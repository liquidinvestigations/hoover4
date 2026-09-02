# Hoover: user manual

Using the site: searching a corpus, filtering it, reading a document, browsing storage,
asking the chat about it, and administering collections. Screenshots are real captures of a
running deployment at 1400x850 unless a caption says otherwise.

How you reach a deployment, and what credentials it wants, depend on that deployment and are
not in this repository. See `INFRASTRUCTURE_INVENTORY.md` at the repository root, which is
local and gitignored.

---

## Contents

1. [Getting in](#1-getting-in)
2. [The layout](#2-the-layout)
3. [Home](#3-home)
4. [Search](#4-search)
5. [Filters](#5-filters)
6. [Sorting and paging](#6-sorting-and-paging)
7. [Reading a document](#7-reading-a-document)
8. [Storage, browsing by folder](#8-storage--browsing-by-folder)
9. [AI chat](#9-ai-chat)
10. [Administration](#10-administration)
11. [Sharing and bookmarking](#11-sharing-and-bookmarking)
12. [Limits worth knowing](#12-limits-worth-knowing)

---

## 1. Getting in

There are two modes, and which one a deployment runs decides what you see first.

**Demo mode.** You arrive as a **guest**, an anonymous account created for your browser
session, named like `guest-376072d767a1` in the screenshots below. A deployment may put a
credential prompt in front of the whole site; where it does, the credentials are held
locally in `INFRASTRUCTURE_INVENTORY.md` rather than on this page. In demo mode a guest is
also an administrator, which is why [Administration](#10-administration) is reachable in
these screenshots.

**Production mode.** Every user is authenticated and no page is anonymous. Your identity
comes from the sign-in the deployment uses, and what you can see is decided by the groups
you belong to and the collections those groups may read.

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
| person (bottom) | your account |

![Home page](img/home.png)

---

## 3. Home

The landing page has two cards.

**Text Search** carries the search box. Type a term and press <kbd>Enter</kbd>, the box
submits on Enter, there is no separate button.

**AI Chat** links to a new conversation or to your earlier ones.

Below them is a feedback link.

---

## 4. Search

Submitting a query opens the search page: the query box and toolbar across the top, the result
list on the left, and the document preview on the right.

![Search results for “computer”](img/search-results.png)

Reading a result card:

* the **number** in the left margin is the result's position in the whole result set. It keeps
  counting across pages, so page 26 starts at `501.`;
* the **title** is the document's filename;
* the **chip on the right** (`testdata_testfiles`, `enron_maildir`, …) is the *dataset* the
  document belongs to, written `<collection>_<dataset>`;
* the **snippet** is text from the document with your search terms highlighted in orange;
* the two buttons at the right of each card are **open in the full-page viewer** and the
  **actions menu**. See [result actions](#result-actions).

Clicking anywhere else on the card selects it and loads it into the preview pane on the right.

![A selected result previewed beside the list](img/search-preview-pdf.png)

### What you can type

The query goes to a full-text engine, so more than plain words is available:

| you type | it means |
|---|---|
| `contract draft` | documents containing both words |
| `"exact phrase"` | those words, adjacent, in that order |
| `contract -draft` | contains `contract`, does not contain `draft` |
| `power \| energy` | either word |
| `comput*` | prefix wildcard |

Punctuation inside a query is handled for you: `it's`, `3/4`, `say"hi` and `"Rule 20.4(c"` are
all accepted and searched literally rather than rejected.

One shape cannot be answered: a query made **only** of exclusions. `-draft` on its own, or
`!a`, has nothing to match before it starts removing things, and the page says so.

![The message shown for a query that only excludes terms](img/search-query-refused.png)

Add at least one word to search *for*: `contract -draft` rather than `-draft`.

### Result actions

The **⋮** button on a result card opens a small menu:

![The per-result actions menu](img/result-menu.png)

* **Copy Document Link.** Puts a permanent link to this document on your clipboard.
* **Download Document.** Downloads the original file with its real name
  (`stanley.ec02.pdf`, not a hash).
* **Open in File Browser.** Jumps to [Storage](#8-storage--browsing-by-folder) with this
  document selected, so you can see what sits next to it on disk.

---

## 5. Filters

**Filter** in the toolbar opens the filter dialog. It has seven panes down the left; changes
accumulate across panes and are applied together by the button at the bottom right, which
tells you how many documents you will get.

**Clear all** (bottom left) drops every filter; **Cancel** closes without applying.

### Collections

Restrict the search to particular datasets. Counts are how many of your current results come
from each.

![The Collections pane](img/filter-collections.png)

### File types

Broad categories, `text`, `email`, `html`, `code`, `pdf`, `doc`, `image`, `archive`, `other`.

![The File types pane](img/filter-file-types.png)

### File size

Four ready-made bands, or your own range in megabytes.

![The File size pane](img/filter-file-size.png)

### File location

A folder tree. Ticking a folder finds **everything below it**, including files inside archives
and attachments inside emails.

![The File location pane](img/filter-file-location.png)

### Date

Four modes (*No filtering*, *Before…*, *After…*, *Between…*) plus **Unknown only** for
documents whose date could not be established. The histogram under them shows how your results
are spread over time, and **clicking a bar filters to that period**.

![The Date pane](img/filter-date.png)

A document matches if **any** of its confirmed dates falls in the range.

### Email

Filter by **Sender** or **Receiver** address, with per-address counts, and a
*Email has attachments* switch.

![The Email pane](img/filter-email.png)

### Entities

People, organisations, locations and other names that were extracted from the documents
automatically. Pick one or several to keep only documents mentioning them.

![The Entities pane](img/filter-entities.png)

### Applied filters

Once applied, the active filters are listed under the toolbar with a **Clear all** beside them,
and the toolbar's **Filter** button gains a count: `Filter (1)`.

![A search with a date range applied](img/search-filter-applied.png)

---

## 6. Sorting and paging

**Sort** offers *Relevance*, *Date*, *File size* and *Name*, and the arrow beside it flips
between ascending and descending.

![The sort menu](img/sort-menu.png)

> Choosing a sort marks your choice; press **Search** to put it into effect.

*Relevance* needs something to be relevant to: with an empty query it falls back to newest
first.

Paging is at the top right of the result list: arrows for previous and next, `1/51` for where
you are, and the up/down arrows next to `- / 1000` step through individual results without
leaving the page.

![Page 26 of a result set](img/search-pagination.png)

**Only the first 1 000 results of any search can be opened**, however many were found. If your
search matches more than that, narrow it with [filters](#5-filters) rather than paging.

---

## 7. Reading a document

Selecting a result opens the viewer, either in the right-hand pane or full-page. Three columns:

* **left**: search within this document, and the list of *sources*;
* **middle**: the document itself;
* **right**: the **Entities** and **Metadata** tabs.

![A text document with its entities](img/document-text.png)

### Sources

One file can be readable in several ways, and each way is a source you can switch between:

| source | what it is |
|---|---|
| **Extracted text** | the text a general extractor pulled out |
| **Plain text** | the raw file as text |
| **Email** | the message rendered as an email, subject, addresses, date, body |
| **Email body** | just the parsed body |
| **PDF** | the real PDF, rendered page by page |
| **PDF · OCR · Tesseract · eng** | the same PDF after optical character recognition |
| **PDF text** | the text layer, without the page images |
| **Office XML** | a `.docx` / `.odt` rendered from its XML |
| **Image** / **OCR · Tesseract · eng** | the picture, and the text read out of it |
| **File locations** | every path in the corpus where this exact file appears |

A PDF gets the full viewer, page navigation, zoom, and the page counter at the bottom right:

![A PDF in the viewer](img/document-pdf.png)

An image shows its dimensions next to the source, and the OCR variant shows what was read out
of it:

![A scanned image and its OCR](img/document-image-ocr.png)

A file found inside an archive shows its container in the breadcrumb, here `parent.zip` above
`parent/child.txt`:

![A file inside an archive](img/document-archive.png)

**File locations** does more than its name suggests: the same content can sit at several paths, and
this is the list of them.

![The File locations source](img/document-file-locations.png)

### Searching inside a document

The box at the top left of the viewer searches the open document. Matches are highlighted and
the arrows beside the counter step between them.

### Entities

The right pane groups the names found in the document into **People**, **Organizations**,
**Locations** and **Misc**, each with the number of times it appears. The box at the top
filters the list.

### Metadata

The **Metadata** tab holds everything the pipeline knows about the file: its dates and why they
are trusted, email headers, blob hashes and size, and the detected file types.

### Downloading

**Download Document** in the ⋮ menu, or the same item in the viewer's own menu, saves the
original file under its real name.

---

## 8. Storage: browsing by folder

The folder icon in the rail opens **Storage**: the corpus as it is laid out on disk.

The landing page lists the collections and how many datasets each has, with the same tree in
the pane on the left.

![Storage, all collections](img/storage-collections.png)

Choosing a collection shows a card per dataset with its document count, total size, how many
are indexed, and how many hit processing errors.

![A collection's datasets](img/storage-collection.png)

Choosing a dataset lists its contents, folders first, with sizes.

![Inside a dataset](img/storage-folder.png)

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

![A deep folder chain in the tree](img/storage-tree-deep.png)

### Finding a file by name

The box above the listing filters the **names** of files under the current folder. It does not
search their contents. `HOUSE` finds `HOUSE_OVERSIGHT_010560.txt`; searching for a word that
only appears *inside* the documents will find nothing.

![Filtering a folder by filename](img/storage-folder-search.png)

For content, use **Open in Search**, which carries the current folder over as a *File location*
filter:

![The same folder, opened in search](img/storage-open-in-search.png)

---

## 9. AI chat

The speech-bubble icon opens a new conversation.

![A new chat](img/chat-new.png)

Two switches sit under the composer:

* **Deep Research**. A longer, multi-step investigation that runs in the background rather
  than inline.
* **Internet tools**. Lets the assistant search the open web and open pages in a real browser.
  With it off, the assistant may only read the collections.

Both are fixed for the whole conversation once you send the first message: the composer shows
**🔒 locked for this conversation**. Start a new chat to change them.

### While it works

The assistant announces each tool it uses as it goes (`list_collections`,
`search_collections`, `web_search`, `browser_navigate`), and shows *The assistant is working…*
with a **■** stop button until the answer arrives.

![A chat in progress](img/chat-working.png)

**Expect this to take minutes, not seconds, on this deployment.** A simple question needed
about five minutes and four model calls.

### Reading the answer

Tool results are shown inline. A collection search renders the documents it found as cards you
can click through to the viewer; each block has an **Expand** control.

![A finished conversation](img/chat-transcript.png)

The assistant's own answer comes **after** the tool output, so scroll to the bottom of the
conversation for it (the tool cards are expanded by default and can bury a
one-line answer)*.

### When it fails

If the assistant cannot finish, the turn ends with a message saying so, and tells you whether
earlier attempts also failed.

![A failed turn](img/chat-error.png)

### Earlier conversations

**History** lists your past chats by their auto-generated titles; opening one restores the whole
transcript.

![Chat history](img/chat-history.png)

---

## 10. Administration

Reachable at `/admin`. On this deployment every guest is an administrator.

### Dashboard

Counts of users, groups, collections and datasets, each linking to its section.

![Admin dashboard](img/admin-dashboard.png)

### Collections

The list shows each collection's display name, dataset count, how many groups have access,
whether it is `public` or `restricted`, and whether its database is ready. The form at the top
adds a collection.

![Admin, collections](img/admin-collections.png)

A collection's own page renames it, links to its processing view, and lists its datasets.

![Admin, one collection](img/admin-collection.png)

### Processing

The most useful page during an ingest. Per dataset it shows the pipeline stages.
**P0 Scan & deduplicate**, **P1 Compute plans**, **P2/P3 Execute plans & parse**,
**P4 Extract entities (NLP)**, **P6 Index for search**, each with a progress bar and a
count, an error count beside the dataset name, a throughput chart, what is running right
now, and a table of where the processing time actually goes.

![Admin, processing](img/admin-processing.png)

### Datasets

A dataset's page shows its type and source path, when it was created, and its processing
statistics: blobs, VFS files, plans total and finished, errors, and the OCR languages in use.

![Admin, one dataset](img/admin-dataset.png)

### Users and groups

Users are listed with their origin; on a demo they are all `guest-…` sessions.

![Admin, users](img/admin-users.png)

A user's page edits their name, email and superuser flag, shows their group memberships, links
to their LLM usage, and holds the delete action.

![Admin, one user](img/admin-user.png)

Groups work the same way, and a group's page is where **collection access** is granted.

![Admin, groups](img/admin-groups.png)

![Admin, one group](img/admin-group.png)

### Settings

This page holds the server settings you can change without a redeploy: chat artifact
retention, guest access mode, the default chat and summarisation models, and the session
lifetime. Below them sits the deployment
configuration that is read-only because it comes from `hoover4.ini`.

![Admin, settings](img/admin-settings.png)

### LLM

The provider table with its model count, when the catalogue was last refreshed and whether it
is stale, a **Refresh catalog** button, the default chat and summarisation models, and the
allow-list of every model the provider offers with usage counts.

![Admin, LLM](img/admin-llm.png)

### AI status

Configured versus actually serving, per capability (embeddings, rerank, NER, OCR, LLM,
browser) with reachability and the endpoint behind each. Below it, the vector shards and the
browser router's live session count.

![Admin, AI status](img/admin-ai-status.png)

This page exists to make silent fallbacks visible: if something says it is configured one way
and served another, this is where you find out.

### Metrics

Live chat turns, then usage over the last 24 hours: events by type, events per hour, and the
busiest users. Events record who, which route or function, and when, never a URL or a query
string.

![Admin, metrics](img/admin-metrics.png)

---

## 11. Sharing and bookmarking

Every view is a URL, and every URL is shareable:

* a search carries its query, filters, sort, page and selected document, so sending someone a
  search sends them the exact search;
* a document has a permanent link, from *Copy Document Link* in the ⋮ menu;
* a chat conversation has one too.

Old links keep working after upgrades; a link that can no longer be understood lands on a
**Page not found** card rather than an error.

![The not-found page](img/not-found.png)

---

## 12. Limits worth knowing

These are properties of how search works here, not faults, and each has a visible sign on
the page.

**Only the first 1 000 documents of a match are reachable.** A corpus-wide query can report
tens of thousands of documents found over a pager that ends at 1 000: the count is the size
of the whole match, and the pager is what you can walk. The page states the difference beside
the count rather than implying the rest are reachable. Narrow the query (with words, a
filter, or a folder) to bring what you want inside the reachable range.

**The assistant's searches are capped per query, and it cannot page past the cap.** When you
ask the assistant a question it runs its own searches, and each one returns at most a set
number of documents. Enough to answer from, not the whole match. There is no "next page" for
it to ask for, so a second search on the same words returns the same documents rather than the
ones after them. It reaches new material by asking a *different* question (other words, a
narrower filter, a particular folder) which is also the most useful way to steer it when an
answer looks thin.

**A document with no confirmed date can never fall inside a date range.** It matches only
through the *no confirmed date* option, which is why that option exists alongside before,
after and between. A range that silently included undated documents would be a different
question from the one you asked.

**Filter counts are counts within the rest of the query**, not counts in the corpus. A chip
showing 12 means twelve documents among those that already match everything else you have
set.

