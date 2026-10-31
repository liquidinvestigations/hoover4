# hoover4

This file names the words this tree uses in more than one sense, and the words that compete
for one sense. Read it before you write a term that already has an entry.

## Language

**Assessment**:
In investigation boards, an assessment is the model call that reads a board and declares new
intents or proposes the review. The code, the stored events and the actor name call it a
reason (`board_reason`, `reason_result`). It is distinct from the reasoning (thinking) of a
model in a chat turn.

**Background context**:
In investigation boards, the background context is the board fact of kind `origin`: the
collections and the context text written at creation. The page calls it background context,
and the code and the stored fact kind call it origin.

**Corpus**:
In architecture and pipeline documentation, an informal name for a body of ingested or
searchable data, never an administrative unit and never an identifier. In the website's
stack-verification tests, the two-collection fixture those tests ingest and query.

**Date**:
A document date is a date attached to a document as metadata, in the storage and pipeline
area. A Mentioned Date is a date an entity extraction found inside a document's text, in the
search and entities area.

**Driver**:
In ingestion and tuning, a driver is the Temporal workflow that runs one plan's files in
series. In storage and database code, a driver is a client library for ClickHouse, Manticore
or another datastore.

**Error**:
A per-document processing failure is stored in `processing_errors`. Each current row
identifies one source execution, document and task.

**Fact**:
In entity explainer cards, a fact is one label and value row of sub-metadata. In
investigation boards, a board fact is one stored finding of a board, with a kind and its
citations. The interface calls it a finding. Code identifiers and stored slugs retain `fact`.

**Failure**:
An above-document record of why a pipeline operation or stage stopped is stored in
`operation_failures`. Each row is one node of that operation's failure tree.

**Page**:
A documentation page is one file in the documentation area. A website route is a page in the
frontend area. A text page is the unit of parsed text the pipeline writes, one per file per
extractor variant, in the pipeline and storage area. A result page is one page of search
results, bounded by the reachability ceiling, in the search area. Page cache is reclaimable
operating-system memory, in the operations area.

**Open question**:
In investigation boards, an open question is a question that an explore fact leaves for the
board (`open_questions`). It has no graph node. A person can start its explore from the fact
pane. An intent in the state `question` is
a different thing: its explore asked the person a question, and a hint answers it.

**Pass**:
An escaping pass is one full scan of text being quoted for a query, in the search
query-encoding area. A low-pass, a high-pass and a band-pass are date-predicate shapes open on
one side, both sides or neither, in the search area. A test passes or fails, in the testing
area. A sub-agent pass is this repository's unit of estimation, in the planning area. Passing
a value is handing an argument to a function, in ordinary code.

**Table**:
In storage documentation, a table is a ClickHouse or Manticore relation, such as a shard table
or the operations table. In document reading, a table is a spreadsheet or delimited-text
document's grid of sheets, columns and cells.

**Term**:
In search-query syntax, a term is a word or phrase typed into a query and matched against the
index. In the search index, a term is a facet's normalised value, kept in a term dictionary
and distinct from the entity it was extracted from.

**Tier**:
In [ai_services/](ai_services), a tier is the GPU service tier. A planned pass names a logical role.
The harness maps that role to a model. The plan names its harness for cost estimates.
In the signal lexicon, a tier is the L, M, or H class that sets a term's scoring points.

**Signal**:
In the scanner, a signal is a lexicon match with source offsets and context flags.

**Red flag**:
In search and the document viewer, a red flag is a category whose passage meets the configured scoring rule.
A red flag directs document review and does not establish misconduct.

**Passage**:
In red flag scoring, a passage is a word window or a group of adjacent qualifying windows.

**Processing update**:
A processing update brings the stored results of a dataset or a collection to what the
current code, settings and inputs produce. The interface calls the action Update processing
or Update collection. The operation kinds are `update_dataset` and `update_collection`. The
word update alone also names a settings save and a database mutation, so write processing
update for this sense.

**Update step**:
An update step is one entry of the processing update registry
([registry.py](main_services/processing/tasks/P_admin/updates/registry.py)), for example `ocr` or `folder_counts`. It is distinct
from a pipeline stage. One step can run more than one stage.

**Fingerprint**:
In processing updates, the desired fingerprint names the output that a step should leave
now. The applied fingerprint names the output that last settled. A step waits while the two
differ. In deployment, the configuration fingerprint (`HOOVER4_CONFIG_FINGERPRINT`) names the
rendered configuration of a service, which is a different value.

**Input revision**:
The input revision of a dataset is the newest terminal operation of the dataset or its
collection that is not a processing update. The unfinished and failed files steps include
it in their fingerprint, so new files and interrupted work make them calculate again.

**Stage version**:
A stage version is the integer in [stage_versions.py](main_services/processing/tasks/stage_versions.py) that names the output format of
one canonical stage. Some stages keep an older constant name, for example
`OCR_PAGE_RULE_VERSION` or `READER_VERSION`. The registry exposes each one under its stage.
