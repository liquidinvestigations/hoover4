# Collection search MCP server

ACL-bounded search and document reads for the user's permitted collections. Port `21930`,
container `hoover4-mcp-collections`. Both agents use this server.

Search goes through **Manticore**, not vectors: the pipeline writes its page text to
Manticore shards and its extracted text to ClickHouse. The Milvus tier was removed
because nothing ever populated it.

## Tools

| Tool | Purpose |
|---|---|
| `list_collections` | collection names and dataset counts this user may read |
| `search_collections` | documents from selected permitted collections, for one query or a list of up to 8 query forms in one call |
| `read_documents` | one text page of each selected document, with its page range and the pages with hits |
| `search_passages` | passages from keyword and vector ranking together, for several queries in one call |
| `list_document_entities` | what the pipeline found in several documents, in two tiers, sharing one budget |
| `cite_documents` | put documents forward as evidence, with a verified quote and a `[Dn]` handle |

The agent API supplies the extended `list_collections`, `search_collections`, and
`read_documents` tools.
`search_passages` and `list_document_entities` compute their result in this server, and
`LocalPagedTool` pages the complete result with `page_result`, so `read_more` continues
them as it continues a route tool. It also supplies search, document, PDF, table, and folder read tools.
Each returns one canonical result page. A page can contain a continuation token for
`read_more`. The server forwards only the caller identity and collection headers to the API.
The API checks every requested collection.
Row and tree pages keep other response fields in `fields`. Folder items carry their
`children` or `files` field name.

The route decides paging. `paging.py` applies one route paging policy to every route tool:
the units are the list the route names, and the next request carries the route's
`next_position` as its `position`. A backend window that fits one page is returned whole. A
window that does not fit is stored once, as one required raw artifact, on its first page.
Its later pages read byte ranges of that artifact with `artifacts.read_range`, which checks
that the caller owns the artifact in this chat and cuts the range to its size, and
call no route. The page share is the `X-Hoover4-Page-Share` header of the call, which the
agent sets from its batch result budget, or 24,000 bytes when the header is absent. Every
page, a later page of a stored window included, is at most the share of its own call. A
page keeps the window fields when one unit fits with them, and leaves them out otherwise.
A `search_collections` row does not include a facet whose count list is empty.
`search_passages` and `list_document_entities` compute their whole
result in this server, and page it as one window in the same way. Every paged tool result
also carries the `build_page` measure of its page as an embedded resource with the URI
`hoover4://call-measure`, after the page text. The page text is the only text block. The
store target of a unit is the share less the measured envelope of its window: a zero-unit
page with the columns and a continuation that holds the largest position values. The
window fields are not in that envelope, so a page that cannot hold the fields and one unit
leaves the fields for a later page before a unit is cut. A unit larger than that target is
stored with string fields moved out, largest first, until the rest fits. The fields
`file_hash`, `path`, `collectionname`, `dataset` and `collection_dataset` never move, so a
cut search row keeps them and loses its snippet first. Its page is cut inside the first moved field and carries
`{"cut": {"field", "returned_bytes", "total_bytes", "next_fields"}}`. `next_fields` lists the
other moved fields. The continuations read the rest of each moved field in that order, and
then the next unit. When not one unit fits the share of a later call, the page returns the
next unit as its canonical JSON text, cut by bytes, with `{"cut": {"field": "",
"start_bytes", "total_bytes"}}` in its fields. So every stored unit stays readable at a
smaller share. Only a share smaller than the page envelope plus one byte gets
`invalid_argument`, and the same continuation then works in a step with fewer calls. Only text is a
blob page: a diff and a table cell. A `ValueKey` position accepts every character in its
`value`, because the route issued that cell text and binds it as a parameter. The client does not retry
a `504` whose body is the route's own `timed_out` answer.

| Tool | Purpose |
|---|---|
| `read_more` | read the next page from a result page continuation |
| `search_facet_values` | find values for a search facet |
| `search_histogram` | return document date, mentioned date or file size buckets |
| `search_entity_explainer` | explain one extracted entity value |
| `doc_sources` | list every source of a document, with hit counts for a query |
| `doc_search_text` | list the hits of a query in one text source, in page order |
| `doc_metadata` | return document metadata, dates, locations, and links |
| `doc_email` | return email fields, attachments, and graph links |
| `doc_diff_sources` | compare two extracted document sources |
| `pdf_search` | find text positions in a PDF source, in a range of PDF pages |
| `table_overview` | list table sheets and columns |
| `table_page` | return 50 rows of at most 60 chosen columns, from `row_start`, sorted and filtered |
| `table_cell` | read one long table cell, 2,000 characters a page |
| `table_column_values` | list values for one table column, with a `search` needle |
| `table_search_cells` | find matching cells in a table sheet |
| `folder_overview` | return storage counts for a collection or dataset |
| `folder_list` | return a folder breadcrumb, children, and files |
| `folder_search` | find folders and files by name |

## Two tiers of entity, and why they are not merged

`list_document_entities` answers with `entities` (an NER model's reading of the prose)
and `structured`, the rule scanner's checksum-validated identifiers, normalised dates and
money. They stay in separate blocks because the confidence behind them is not comparable:
a name is a judgement, an IBAN either has a valid check digit or it does not. Merging them
would tell the model the two are the same kind of fact.

It takes the same three argument shapes as `read_documents` (a list of objects, two
parallel lists, and a bare pair of strings, which is the single-document call it replaced)
and shares one character budget across the batch. **The rule-scanner tier is filled first
and the NER tier takes what is left**: when only one of the two fits, it is the
checksum-validated evidence that survives and the model's guess at a span of prose that
goes. A document that was cut says so in `truncated`, and the batch's `note` names them.
Each tier reads one dataset of the collection that holds the hash, the first by name, at
the website's limits: 500 NER values and 1,000 rule values, most frequent first. The NER
values carry the stored count and skip the website's full-text recount of each value.

The `structured` query is the same one the website's document viewer runs against the same
table, and for the same reason: two different answers to "what identifiers are in this
file" would put the model and the reader in different conversations about one document. It
reads only the newest rule set (the table keeps every rule set's results side by side so a
version bump can be rescanned without destroying what came before) sums counts across
segments, and takes the maximum across text variants, because a document parsed twice
carries the same occurrences under both. A scanner that has never run leaves no rows, and
the block is then absent rather than an error.

## Citations

`cite_documents` is how the agent says which documents its answer rests on, as against
which documents a search happened to return. Each citation names a document, a quote and
one line of why, and gets back a handle (`[D1]`, `[D2]`) that the model writes into its
prose; the reader sees the handle as a chip and the document beneath the answer.

**The quote is checked** against the document's extracted pages before a handle is issued,
after folding whitespace, case and typographic punctuation. Verification reads every
extracted page in bounded batches, each continuing after the `(extracted_by, page_id)` key of
the last page read, and is independent of `MAX_DOCUMENT_CHARS`, which only
bounds the excerpt `read_documents` shows the model. A model quoting a sentence it read
reproduces the words, not the extractor's line breaks, and an exact-substring test
rejects nearly every accurate quote. A quote that does not check out is returned **flagged,
never refused**, with a reason of `short`, `absent`, or `lookup_failed`. A model that stops
citing is a worse outcome than a citation the reader sees marked. A quote too short to
prove anything is unverified for the same reason a check that always passes is not a check.
A paraphrase is absent wording. A stored citation that never recorded a reason stays
readable and does not display a reason that was never established. Pages are fetched in
batches of 32 (`VERIFY_PAGE_BATCH`). A match that crosses a batch or a page still
verifies, because the pages are joined with the same separator a full-document read uses.

**Handles are allocated per chat session**, not per turn. `[D7]` from the first turn has to
still resolve in the ninth, because the answer that used it is still on screen. The table
is bounded and evicts whole sessions rather than individual handles: a session that falls
out gets fresh numbering, and `[D3]` meaning two documents inside one conversation is worse
than `[D1]` starting over.

## Collection access

The server forwards caller identity and collection headers to the website agent API.
The API checks access for every requested collection.
The server checks collection access for tools that read the datastore directly.
See [`collection_search_server/acl.py`](collection_search_server/acl.py).

## MATCH syntax: operators pass through

`sanitize_match_query` used to **strip** every operator character (`!"$()-/<@^|~*`) on the
grounds that an LLM writes prose, not query syntax. That is wrong: the operators are
valuable and the model is told how to use them. The canonical syntax reference lives in
[`collection_search_server/prompts/`](collection_search_server/prompts/) and reaches the
model as the server's FastMCP `instructions`, i.e. at tool-discovery time. The instructions
are rendered from `SERVER_TOOLS`, the tool names this server registers, and
`tests/test_prompts.py` fails when that list stops matching what `server.py` decorates,
so a renamed tool is caught rather than left as prose telling a model to call something
that no longer exists.

What the sanitiser does instead is head off the three shapes that come back as an HTTP 500
the model cannot interpret, plus the empty query that is worse than an error:

| Input | Before | Now |
|---|---|---|
| `-zzz` | 500 `non-computable (single NOT operator)` | refused with "add at least one word to search for" |
| `"test` / `(test` | 500 `syntax error, unexpected $end` | repaired to `test` / `(test)` |
| `who paid @acme` | 500 `no field 'acme' found in schema` | searched as `who paid acme` |
| `@title test` | 500 `no field 'title' found in schema` | searched as `title test` |
| `''` | **matched every row in the shard** | refused |
| `a OR b`, `a AND b`, `a NOT b` | searched for the words `OR`, `AND` and `NOT` | searched as `a \| b`, `a b`, `a -b` |
| `name@host.com` | searched as `namehost.com` | searched as the address, with `\@` |

`OR`, `AND` and `NOT` are ordinary words to Manticore. `_rewrite_boolean_words` reads the
upper-case words as `|`, as nothing and as `-`, and drops an `OR` or `NOT` with no term on
one side. It replaces each operator word in place and changes nothing inside double quotes.
The website search has the same rule in `website/backend/src/db_utils/manticore_match.rs`,
and the two copies change in one patch.

Repairs are reported back in the response's `note`, and Manticore's own error text is now
returned in `error` rather than only logged. A syntax error the model never sees is one
it cannot correct.

`search_collections` gets the repairs of the website search in `query_notes`. With a
`queries` list, and `query` as its first form when both are given, each form is one route
search. The rows merge by `(collectionname, file_hash)` in the order they are first found,
and each row gets `matched_queries`, the forms that found it. A form that fails adds its
error to `query_notes`, and the other forms still run. Each form gives the first route page
of its rows, and a form with more rows says so in `query_notes`. The merged rows page
through `read_more` as a `LocalPagedTool` result.

**The escaping is unchanged and is the injection barrier.** `\` and `'` are what could
break out of the single-quoted SQL literal; that is a separate concern from the query
language living inside it, and passing operators through does not weaken it (`"` is
harmless in a single-quoted literal).

`page_text` is the **only** full-text field. Everything else in the shard schema
(`collection_dataset`, `file_hash`, `extracted_by`, `page_id`, `ner_*`) is an attribute
and belongs in `WHERE`.

## Wildcards work now

Infix indexing was turned on in `main_services/processing/database/manticore.py` and the
collections reindexed. Before, `doc*` returned a *wrong* answer rather than none, the
star was dropped during tokenisation and a truncated literal was searched:

| query | before | after |
|---|---|---|
| `document` | 16 | 16 |
| `docum*` | 0 | 19 |
| `*ocument*` | 0 | 42 |
| `doc*` | **7 (wrong)** | 34 |
| `te*t` | **3 (wrong)** | 28 |

Changing that setting requires a **reindex**: `ALTER TABLE` updates the metadata and
leaves the old index in place, so `SHOW TABLE ... SETTINGS` will report the new value
while queries keep returning the old answers. See
[`../../../main_services/processing/database/Readme.md`](../../../main_services/processing/database/Readme.md).

## How big a `search_passages` result may be

**The size of the serialised response is the bound. The count is only a ceiling.**

`_apply_payload_budget` measures `SearchResponse.model_dump_json()` and holds it under
`SEARCH_PAYLOAD_BUDGET_CHARS` (24 000). It first shrinks every snippet to an equal share
of what is left after the envelopes, clamped between `SEARCH_MIN_SNIPPET_CHARS` (120) and
`SEARCH_SNIPPET_CHARS` (1200); when the envelopes alone no longer leave room for a
readable line each, it drops the lowest-ranked hits and says so in `note`. Eight hits
still get the full 1 200 characters each; a request for 200 comes back as ~60 with a line
apiece. Reading them properly is `read_documents`.

Bounding a field is not bounding a payload. A per-snippet budget with a count cap leaves
every hit's envelope (`collection_dataset`, `collectionname`, a 64-character `file_hash`,
`match_sources`, `page_id`, `path`, `score`) unmeasured at ~250 characters each, so 200
results are 50 000 characters of ids and paths on top of whatever the snippets are allowed:
a prompt that is heavier than the one a count cap alone produces, while the cap does exactly
what it says. Envelopes also vary (a deep path costs several times a shallow one) which is
why they are measured per hit rather than assumed.

The budget matches the website's cap on a stored `tool_output`
(`common/src/chat_types.rs`), and that is the point: a result that fits is stored whole,
so `chat_messages.tool_output` is an accurate copy of what the model saw rather than a
truncated one that cannot answer the question. Every call also logs
`search_passages payload: N chars, K of M hit(s) returned`, which is the only place
the size the model actually received is observable.

`max_results` is clamped to `SEARCH_MAX_ALLOWED_RESULTS` (200) and defaults to
`SEARCH_MAX_RESULTS` (50) (a model that asks for `10000` gets 200), but it decides how
deep the search goes, not how much comes back. The default is most of
the cap on purpose: a tool call costs one provider round trip regardless of how much comes
back, so running the same search four times to see what one run could have shown is four
times the wall clock for the same answer.

The trim runs **after** ranking. The fused order and the cross-encoder both score the full
passage; scoring a truncated one would change which documents come back, not only how much
of each does.

## The per-kind floor must stay under `max_results`

After RRF and reranking, `per_kind_floor` reserves each of the `keyword` and `vector`
rankings its own best results so an exact-term match cannot drown a semantic one. **A
reserved slot is never evicted by the overall cap**, so the floor has to be well under it:
at `10` per kind, two kinds reserved twenty results and a caller asking for `max_results=8`
got twenty back, at 1200 snippet characters each, into an agent's context window. It is
`3` now.

The *ceiling* has the opposite failure. `COLLECTION_SEARCH_MAX_PER_KIND` is a diversity
guard for small result sets, and left at a constant it silently becomes the real cap on a
hybrid search, two kinds x 15 is 30 hits however many were asked for. It is raised to
`max_results` when that is larger, as are the fusion pool and the per-shard fetch, so the
cap the tool advertises is the cap it can deliver.

Two more rules the fused path follows, both of which read identically to their wrong
versions:

* **The snippet of a multi-chunk page is its *nearest* chunk.** KNN returns nearest first,
  so assigning unconditionally left the farthest chunk in place. That text is also the
  document string handed to the cross-encoder, so a page was scored on its least relevant
  passage and then shown to the user with it.
* **A partial rerank response does not delete the candidates it skipped.** They keep their
  fused position behind the scored ones; dropping them would turn a partial rerank into a
  partial search.

## Configuration

| Variable | Default |
|---|---|
| `CLICKHOUSE_URL` / `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` | `http://clickhouse:8123`, `hoover4`, `hoover4` |
| `MANTICORE_URL` | `http://manticore:9308` |
| `SEARCH_MAX_RESULTS` / `SEARCH_MAX_ALLOWED_RESULTS` | `50` / `200` |
| `SEARCH_SNIPPET_CHARS` | `1200` |
| `SEARCH_PAYLOAD_BUDGET_CHARS` / `SEARCH_MIN_SNIPPET_CHARS` | `24000` / `120` |
| `COLLECTION_SEARCH_MIN_PER_KIND` / `_MAX_PER_KIND` | `3` / `15` |
| `COLLECTION_SEARCH_FUSION_CANDIDATES` | `60` |
| `MAX_DOCUMENT_CHARS` | `40000` (model-facing `read_documents` excerpt only) |
| `SERVER_INSTRUCTIONS` | overrides the rendered instructions; empty means render `prompts/` |

## Tests

```bash
docker exec hoover4-mcp-collections python -m pytest tests/ -q   # 161 tests
```

Everything in `tests/test_acl.py` is pure (no database), because the ACL and the query
sanitiser are the security-relevant parts. The operator table above is asserted case by
case there.
