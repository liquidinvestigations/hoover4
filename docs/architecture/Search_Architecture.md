# Search architecture

How a query becomes an answer: what is queried, how the pieces are merged, what is exact and
what is approximate, and how the filters, the sort, the folder tree and the cache behave.

Session handling, database routing and the full-text argument builder are
[Website backend](Website_Backend.md).

## Contents

- [Search fan-out](#search-fan-out)
- [Dates are historical dates only](#dates-are-historical-dates-only)
- [The date histogram](#the-date-histogram)
- [Sorting](#sorting)
- [Only the first 1 000 results are reachable](#only-the-first-1-000-results-are-reachable)
- [Filename search](#filename-search)
- [The folder tree](#the-folder-tree)
- [Cache invalidation](#cache-invalidation)

## Search fan-out

Manticore holds no global search tables. Each collection's search data lives in a
dynamic number of shard tables, `<collectionname>_<n>_pages` (capped by the indexing
planner at 4 GB of text or 2.5 M rows, whichever binds first). Distributed tables are
deliberately not used: Manticore 14.1.0 cannot run this site's stored-field/FACET query
shape over them. Measured, not assumed, and it fails by returning NULL stored fields
rather than by erroring.

**One table per shard, and no JOIN.** Each document's metadata is denormalized onto every
one of its pages rows by the indexer. The JOIN this replaced was the single most expensive
thing in the search path. A nested-loop lookup per left row, evaluated before any
predicate, so an unfiltered entity facet on the largest shard cost 13 s alone and 100 s
under the four-way concurrency of the Entities tab, which is what produced HTTP 504 there.
It was also silently wrong: Manticore's `LEFT JOIN` drops unmatched left rows, 0.28% of
documents on the corpus it was measured against. Denormalized, the same facet is ~1 s and
a `file_types` facet is ~0.27 s, for about 15% more disk. Do not reintroduce a join.

Every search (result list, hit count, string facets, MVA facets, the date histogram) is
therefore built once **per shard** (`website/backend/src/api/search/search_sql.rs`) and fanned out
through a PROCESS-WIDE gate of `MAX_PARALLEL_INDEX_QUERIES = 8` concurrent Manticore
queries (`website/backend/src/api/search/fanout.rs`, override with
`HOOVER4_SEARCH_MAX_PARALLELISM`, clamped to 1..=64; ini key `search_max_parallelism`).
Process-wide rather than per request because the Entities tab opens four fan-outs at once,
and a per-call limit multiplies by four against a daemon that has a dozen worker threads.
Size it to the daemon, not to the shard count.

Selecting datasets in the `collection_dataset` facet prunes whole collections from the
fan-out. One failing shard degrades the response to partial (the UI shows a "some
collections could not be searched" notice); an error is returned only when every shard
fails.

**A timeout is not a partial result.** Every query carries `max_query_time` and
`agent_query_timeout` of 30 s (`HOOVER4_SEARCH_TIMEOUT_SECONDS`, ini key
`search_timeout_seconds`), and the HTTP client applies the same budget plus five seconds
of grace. Manticore's own limit is best-effort and covers neither a connect nor a read
stall. A shard that hits either limit fails the whole request, is never written to the
search cache, and the facet pane offers a Retry button. That is deliberate asymmetry: a
shard that could not be reached is dropped with a visible amber notice, while a shard that
timed out answers with counts that are short by an unknown amount in a response shaped
exactly like a correct one. The retry is never automatic. Retrying by itself doubles the
load on a Manticore that was already too slow.

What is exact, and what is approximate:

- **Exact:** per-shard results and per-shard counts; pagination stability (hits are
  merged by score with a deterministic `(collection_dataset, file_hash)` tie-break).
- **Approximate:** cross-shard/cross-collection **ranking** (BM25 statistics are
  per-table, so there is no global IDF. That is accepted and deliberately not "fixed" with
  a normalisation hack); cross-shard **facet counts** (each shard only returns its top
  buckets, over-fetched to `21 × n_shards`, capped at 200, before the merge sums
  them); the **total hit count** (a sum of per-shard `count(distinct file_hash)`,
  which is an upper bound because the same file can exist in two collections).

The **Collections facet is intersected with the dataset registry** before it is offered
(`search_facets.rs::reconcile_dataset_facets`): a value that names no readable dataset is
dropped, and a readable dataset the index returned no bucket for is added at zero. The
index is not the authority on which datasets exist (`dataset` is), and Manticore keeps
whatever was written under a name until something deletes it, so an abandoned ingest goes
on producing buckets with real counts. Offering one hands the user a filter whose only
possible outcome is `0 documents found`. The guard is display-only: the orphan rows still
inflate unfiltered hit counts, and `main.py purge-dataset` is what removes them.

The four NER Entities facets (`ner_per`, `ner_org`, `ner_loc`, `ner_misc`) and the
document viewer's entities panel are filtered through `website/common/src/entity_stoplist.rs`,
which
rejects mail header names, encoding fragments and letter-spaced PDF headings. The
pipeline drops the same values before storing them
(`main_services/processing/tasks/entity_stoplist.py`), so on freshly extracted data this
finds nothing; it exists because a write-time rule governs only rows written after it,
and on a mail corpus the rows written earlier put `Content-Transfer-Encoding` at the top
of the facet. The duplication is deliberate and mirrors `document_sources.rs`: neither
runtime may depend on the other being right. The stop-list is applied to whatever maps to
the `ner` term field and to nothing else: it exists to drop what a *model* mislabels, and
against a checksummed identifier it would only do damage.

**A facet search box asks the corpus, not the buckets on screen.** A pane holds the top
twenty-one buckets of one query, so narrowing those client-side answers "nothing matches"
for a value that is present and merely unpopular. `search_entity_terms`
(`website/backend/src/api/search/entity_terms.rs`) resolves a needle against
`<collectionname>_entities` (the only table carrying both the text and the term id the
search columns are written in), and the ids narrow the facet query through
`search_string_facet`'s `restrict_to_ids`. `Some(vec![])` is a needle that matched
nothing and returns no buckets; `None` is no needle and returns the whole facet, and
collapsing the two answers a failed search with everything. `file_types` keeps
client-side narrowing: a handful of buckets, all visible, and no rows in the term table.

**One pane serves eleven of the Entities rail's twelve children**, so a rail click changes
that pane's `field` prop rather than building a new pane. Props are not reactive: a
`String` prop is read once into the hooks and never again, and a `use_resource` that
closed over it goes on asking about the column the reader left. The field is therefore a
`ReadSignal`, read *inside* the resource, and the search box empties when it changes. The
failure it prevents is a facet full of values answering "nothing matches" for a needle
typed against a different list.

Those queries are uncached, like the folder tree's, because the table changes while
ingestion runs. **Manticore 14.1.0's SQL grammar has no `EXCLUDE FILTERS` clause** in any
position a `FACET` accepts, so a facet drops its own selection by having it removed from
the query before the query is sent. That also removes the `collection_dataset` filter
permission sanitisation injected, which is safe only for as long as permissions are
collection-granular. A permitted collection implies all of its datasets. Dataset-level
permissions would make that line a leak.

The two copies are held together by a digest rather than by discipline. No path is
visible to both test runs (`hoover4-website` mounts only `website/` and `hoover4-worker`
only `main_services/processing`), so each side hashes its own header names, thresholds and
canonical cases into `STOPLIST_PARITY_DIGEST` and asserts the same literal. A rule changed
on one side alone fails that side's test; updating the digest then fails the other side
until the same change is made there.

Search responses are cached per sub-query in the global `search_manticore_cache`
table; the cache key includes the collection's shard-ledger generation
(`max(updated_at)` of its `manticore_shards` table, cached in-process for 30 s), so a
newly opened shard invalidates that collection's cached searches without touching the
others.

## Dates are historical dates only

There is no upload date and no index date anywhere in the schema, by decision. Every date
the UI shows or filters on came from the document's own metadata, or from an archive that
stored it:

* Tika's `dcterms:created` / `dcterms:modified`, `xmp:CreateDate` / `xmp:ModifyDate`,
  `pdf:docinfo:created` / `pdf:docinfo:modified`, `exif:DateTimeOriginal`;
* an email `Date:` header that actually parsed (`email_headers.date_sent_known = 1`);
* the mtime of an **archive member**, 7z restores the timestamps the archive stored.

Deliberately NOT dates: Tika's `File Modified Date` (the mtime of the worker's temp file,
which would date the whole corpus "today"), and the mtime of a top-level disk file (the
clone or save time of the corpus, recorded in `vfs_files.mtime_source = 'filesystem'` and
never indexed).

A document has a SET of dates, not one, and `document_dates` keeps each with the key it
came from. The viewer's **Dates** section shows all of them with provenance. That is
where a user finds out why a date filter did or did not match.

**`email_headers.date_sent` is a `DateTime` whose fallback is the epoch, and the epoch is
also a real instant**, so nothing but `date_sent_known` separates "sent 1970-01-01" from
"never parsed". Every reader must consult the flag: the email source query emits an empty
string for an unknown date and `DocumentEmailSourceItem::sent_date` rejects the epoch
again on the client, because viewer state restored from a URL carries whatever was written
into it. Printing the sentinel puts a sent date on the preview of a document the Metadata
tab reports as having no confirmed date at all.

**An email's headers and its body are stored independently, and the second is not implied
by the first.** `email_headers` gets a row whenever the file parses at all; `text_content`
gets an `email_parser` row only if the message yielded body text worth storing, and the
text writer drops a page whose stripped text is under two characters. Mail whose whole
`text/plain` part is a single `,` clears the first bar and not the second, exactly like
mail whose only body part is HTML. `DocumentEmailSourceItem` therefore carries
`has_body` alongside the body's page range, and the preview renders the headers with an
explicit "no body text was extracted" line instead of asking for a page that has no row,
which the text endpoint answers, correctly, with a 404 the viewer rendered as *document
not found!* where the body belongs.

**Archive-mtime limitation.** An archive member's mtime is only as good as the archive.
Many archives store the extraction machine's clock rather than the document's, and nothing
in the file distinguishes the two. Those dates are indexed because a wrong-ish date is
more useful than none for narrowing a corpus, and the viewer names the source so the user
can discount it.

**A date range is an interval-overlap test.** The filter compiles to
`date_min <= hi AND date_max >= lo`, not `ANY(dates) BETWEEN lo AND hi`. Manticore 14.1.0
cannot evaluate `ANY(mva)` across the pages⋈meta join in any spelling (see
`search_sql.rs::range_predicate`). A document whose dates STRADDLE the range with none
inside it therefore matches: created 2007, modified 2020, filtered 2013–2016. The error is
one-sided (a superset, never a subset), and the viewer explains each result.

**Three range shapes, one filter.** `RangeFilter`'s bounds are `Option`s and an absent one
compiles to an open end, so a low-pass (`before X`), a high-pass (`after X`) and a
band-pass (`between X and Y`) are the same predicate with different bounds. The Date pane
names all three rather than expecting a user to discover that an empty box means "no
bound". The open low end is `i64::MIN + 1` and not `i64::MIN`, which is what keeps
`DATE_UNKNOWN` documents out of a pure low-pass; `Unknown only` is the separate mode that
asks for them.

## The date histogram

Under the date selector, one bar per computed bin, over **the query without its own date
filter**, a facet that filtered itself would be one solid block inside the cutoffs and
zero outside. The bars the cutoffs cover are drawn in the accent, so the picture is
"what you selected against what is there".

`search_date_histogram` (`website/backend/src/api/search/date_histogram.rs`) does it in two fan-outs:

1. **Measure the domain.** `min(date_min)` and `max(date_max)` over the filtered set, plus
   the undated count. The bounds come from `ORDER BY … LIMIT 1` in each direction rather
   than from `min()`/`max()`, which is not a shape this codebase has ever got an answer
   out of Manticore for. There is no histogram, date-bucket or date-truncate function to
   use instead, and `date_min` is a signed `bigint` rather than a `timestamp` precisely
   because the timestamp type is 32-bit unsigned and cannot hold a 1936 date.
2. **Count the bins.** One `INTERVAL(date_min, e0, e1, …)` + `GROUP BY` per shard. The
   same shape as the size facet, with up to thirty edges instead of three.

Bins are computed, not fixed: a per-year bucket is unreadable for a corpus spanning a week
and useless for one spanning four centuries. The width is chosen off a ladder of durations
people name (hour, day, week, month, quarter, year, decade…), stepped up until the total
fits `HISTOGRAM_MAX_BUCKETS`. **The active cutoffs are forced to be bin edges**, so the
three intervals a band-pass creates each get their own run of bins at a comparable width
and no bar is half-selected. `histogram_edges` is a pure function and is where the tests
live.

Clicking a bar means whatever the active mode means, in `Before` it moves the upper
cutoff, in `After` the lower one, otherwise it selects that bin. Each bar's `title` says
which, because the answer is not visible from the bar.

## Sorting

Four keys: `Relevance` (BM25 `weight()`, unavailable without a query string and resolved
to Date server-side if one is asked for anyway), `Date`, `File size`, `Name`.

`Date` sorts on a different column per direction: newest-first on `date_max`, oldest-first
on `date_min`, because a document spanning 1990..2020 belongs at a different place in each.
Undated documents carry `DATE_UNKNOWN` (`i64::MIN`) and sort last descending, first
ascending.

Sorting is cross-shard, so the per-shard `ORDER BY` and the merge comparator must agree
exactly. The sort column is SELECTed for that reason alone. `merge_hits_sorted` is tested
over every key in both directions for page disjointness.

**The Sort control edits the PENDING query, like everything else in the search toolbar.**
It therefore names the order the results on screen are actually in, and draws an
unapplied choice after it as `applied → pending` in the accent colour; `Search` is
the one control that says whether anything is waiting, and it is disabled when nothing
is. Applying the sort on selection instead is not the small change it looks like: the
apply path pushes the whole pending query, so a sort click would commit filter edits the
user had not confirmed.

## Only the first 1 000 results are reachable

`MAX_PAGINATION_DOCUMENT_LIMIT` (`website/common/src/search_const.rs`) caps how deep the pager
and the next/previous-result buttons go. The hit count above them is the whole match, so
a corpus-wide query says "6 379 documents found" over a pager that ends at `1000`, two
numbers on one line that legitimately disagree. The `i` beside the count explains it
whenever the count exceeds the cap (`search_result_list_controls.rs::PaginationCapNotice`).

The cap is a property of the UI, not of the index: search itself will count and rank the
whole match. Deep paging over a merged, cross-shard result set costs a full re-merge per
page, and past a thousand hits refining the query is the answer rather than paging.

## Filename search

One synthetic pages row per document (`extracted_by = 'filename_index'`, `page_id = -1`)
carries its distinct basenames, so a query for a filename finds the document. It is built
from `vfs_files` paths and never from page text.

**It is not a page**, and every query over a pages table must exclude it: `page_id` is
deserialised as `u32` in the document endpoints, so a leak is a failed query rather than an
off-by-one. `EXCLUDE_FILENAME_ROW` is the predicate; `test_filename_row_excluded.py` greps
for readers that forget it.

Folder names are deliberately NOT in that row. They go through the structure index, where a
folder is one row rather than one row per document under it.

## The folder tree

`<collectionname>_vfs` is one Manticore table per collection (not per shard, not per
dataset) holding one row per VFS node. It powers the storage sidebar, the filter pane's
folder picker, and in-folder search.

**Three independent caps bound what it renders**, and they are separate because they
answer different questions (`website/frontend/src/components/search_components/vfs_tree.rs`):

| cap | bounds | overflow row |
|---|---|---|
| `CHILDREN_PAGE_SIZE` (500) | what is FETCHED per request | `N more…`, fetches the NEXT page and appends |
| `MAX_SIBLINGS_EACH_SIDE` (10) | what is RENDERED either side of the folder you are in | `N more above/below…`, client-side only |
| `MAX_VISIBLE_ANCESTORS` (8) | how many levels of the path to that folder render at all | `N more levels…`, collapses the middle |

The tree asks for folder-like children ONLY (`folders_only`), so `total` counts what it
can draw: a folder holding nothing but files is a leaf rather than a row promising
thousands of children that never appear, and a folder's files can no longer fill the first
page and starve the archives behind them (`ORDER BY kind ASC` puts containers last). The
file-browser content pane asks without the flag, because files belong in the pane. The
server's own `MAX_CHILDREN_PER_PAGE` (2000) is a page-size cap and is deliberately larger
than what the tree asks for: while the two were the same number, a wider request was
clamped back to the page the caller already had.

The last two are measured from the tree's **focus** (the node the URL names), and are
inert in the filter pane, which has no "here". Only one of the first two is ever on screen
at once: while a sibling window is capping, the fetch row is suppressed, because raising
the fetch limit would not reveal anything the window is hiding. `elide_ancestors` and
`window_siblings` are pure functions with unit tests; the fixture that exercises them on
screen is `many-children` (a 42-level chain and a folder of 334 siblings), ingested by
`verify-stack.sh` as `testdata_shapes`.

**The indent counts ladder RUNGS, not tree depth**, and the third cap is what makes that
affordable. A row's rung is its position in the ladder on screen; ancestor elision hides
whole levels without spending rungs, so the deepest folder of a 43-row chain renders on
rung 11 rather than rung 45. Every visible row is therefore indented strictly more than the
row it hangs off, at any depth and at any pane width, which is the thing a tree has to
show. `indent_px` spends 16 px on the first four rungs and 8 px on every rung after them,
bounded by a pixel ceiling and (through a CSS `min()`) by a share of the pane, so
dragging the sidebar narrow tightens the ladder with no re-render. The 8 px step is small
because the app lays out at a 1920 px design width and `zoom`s it to the window
(`assets/main.css`): a 4 px step would be 2.5 device pixels at a 1280 px window, which is
not a step anyone can see. Past four rungs the row also states its true depth in a badge,
because the ladder does not count it.

**That pane share is scaled by the rung, not applied flat**, which is the difference
between a ladder that tightens and one that stops. A flat `min(Npx, 40%)` resolves to one
number for every rung above the percentage, so at the narrowest pane the drag offers, four
to five consecutive levels render at pixel-identical indent, which is the flat cap the
ladder replaced, reached from the other direction. `indent_style` emits
`min(Npx, calc(40% * f))` where `f` is the rung's share of the pixel ceiling, so the
narrow-pane branch is a proportional copy of the wide-pane one: bounded by the same share
of the pane, and still stepping at every rung.

**Refocusing collapses the subtree below the new focus** (`expansion_after_refocus`).
Elision only shortens the ladder ABOVE the focus, so an expanded chain left hanging below
it keeps taking a rung each until the pixel ceiling absorbs them: navigating up from a
44-deep folder to a 26-deep one otherwise leaves twenty-one nested levels rendered as
twenty-one siblings. The path to the focus stays open, including the levels elision hides,
and branches elsewhere in the tree keep whatever the user opened by hand.

**The storage sidebar is resizable and remembers its width**
(`website/frontend/src/components/resizable_sidebar.rs`). The unit is CSS pixels. A percentage or `vw` would
re-scale the pane on every window change, and the width a folder name needs is a number of
pixels, not a share of a screen. Those are LAYOUT pixels, before the app's scale, so the
drag divides the cursor's travel by the scale it measures off `#x-nav-container`; the
scale is a media-query ladder and cannot be a constant on the Rust side. A remembered
width is clamped to 240–720 px on the way in and on the way out, anything that is not a
plain positive integer falls back to the default, and `max-width: 50%` backstops both. The
720 px ceiling is 37 % of the design width, so no window size can put the pane off screen.

**The double-click that resets it is recognised from the two `mousedown`s**, because no
`click` or `dblclick` ever reaches the handle: the first press mounts the full-screen
overlay that catches the drag, the release lands on that overlay, and the overlay unmounts
in the same handler, so the browser has no live common ancestor for the two and drops the
whole activation sequence. `is_double_press` pairs two presses within 400 ms and 4 px of
each other, which is the only path that writes the default width back to storage.

Breadcrumbs resolve through `vfs_tree_path_to`, which walks `parent_key` and therefore
crosses container boundaries: `PathDescriptor` carries a single `container_hash`, so an
archive inside an archive used to render one hop and lose the rest. A container has no
`/` node: what is inside it hangs off the container FILE, so expanding `report.zip` shows
its contents and the trail reads `dataset › folder › report.zip › member`. The content
pane still addresses that level as the descriptor `container_hash + "/"`. A descriptor
and a tree node are different things. Past
`MAX_CRUMBS_SHOWN` (3) the leading crumbs collapse into a `…` chip whose popup lists them.

Every read of it goes through `manticore_search_sql_uncached`: the tree changes while
ingestion runs, watching a folder fill up is the normal case, and a stale tree is worse
than a slow one.

Filtering on a folder finds everything below it **including through containers**, and a
content-addressed container that sits at two paths contributes both ancestries. The
`zip-in-multiple-locations` fixture, which `verify-stack.sh` asserts on. `vfs_nodes.parent_key`
is single-valued and is only for breadcrumbs; membership always uses the full closure.

## Cache invalidation

Every search response is cached under a salt made of the collection's shard-ledger
generation AND `server_settings.cache_epoch`. The generation covers data changes; the epoch
is the manual control for SEMANTICS changes, where every cached response is a correct answer
to a question the code no longer asks. Bump it (any new value) after changing a query
shape.
