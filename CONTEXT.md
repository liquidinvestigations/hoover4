# hoover4

This file names the words this tree uses in more than one sense, and the words that compete
for one sense. Read it before you write a term that already has an entry.

## Language

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

**Page**:
A documentation page is one file in the documentation area. A website route is a page in the
frontend area. A text page is the unit of parsed text the pipeline writes, one per file per
extractor variant, in the pipeline and storage area. A result page is one page of search
results, bounded by the reachability ceiling, in the search area. Page cache is reclaimable
operating-system memory, in the operations area.

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
