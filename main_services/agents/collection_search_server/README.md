# Collection search MCP server

ACL-bounded full-text search of the user's own documents. Port `21930`, container
`hoover4-mcp-collections`. **Both** agents use it, and it is the only tool the
internal-search agent has.

Search goes through **Manticore**, not vectors: the pipeline writes its page text to
Manticore shards and its extracted text to ClickHouse. The Milvus tier was removed
because nothing ever populated it.

## Tools

| Tool | Purpose |
|---|---|
| `list_collections` | what this user may read — always call first |
| `search_collections` | full-text search across the permitted shards |
| `read_documents` | the extracted text of several documents, each by `collectionname` + `file_hash`, sharing one budget |
| `list_document_entities` | what the pipeline found in several documents, in two tiers, sharing one budget |
| `cite_documents` | put documents forward as evidence, with a verified quote and a `[Dn]` handle |

## Two tiers of entity, and why they are not merged

`list_document_entities` answers with `entities` — an NER model's reading of the prose —
and `structured`, the rule scanner's checksum-validated identifiers, normalised dates and
money. They stay in separate blocks because the confidence behind them is not comparable:
a name is a judgement, an IBAN either has a valid check digit or it does not. Merging them
would tell the model the two are the same kind of fact.

It takes the same three argument shapes as `read_documents` — a list of objects, two
parallel lists, and a bare pair of strings, which is the single-document call it replaced —
and shares one character budget across the batch. **The rule-scanner tier is filled first
and the NER tier takes what is left**: when only one of the two fits, it is the
checksum-validated evidence that survives and the model's guess at a span of prose that
goes. A document that was cut says so in `truncated`, and the batch's `note` names them.

The `structured` query is the same one the website's document viewer runs against the same
table, and for the same reason: two different answers to "what identifiers are in this
file" would put the model and the reader in different conversations about one document. It
reads only the newest rule set — the table keeps every rule set's results side by side so a
version bump can be rescanned without destroying what came before — sums counts across
segments, and takes the maximum across text variants, because a document parsed twice
carries the same occurrences under both. A scanner that has never run leaves no rows, and
the block is then absent rather than an error.

## Citations

`cite_documents` is how the agent says which documents its answer rests on, as against
which documents a search happened to return. Each citation names a document, a quote and
one line of why, and gets back a handle — `[D1]`, `[D2]` — that the model writes into its
prose; the reader sees the handle as a chip and the document beneath the answer.

**The quote is checked** against the document's extracted text before a handle is issued,
after folding whitespace, case and typographic punctuation — a model quoting a sentence it
read reproduces the words, not the extractor's line breaks, and an exact-substring test
rejects nearly every honest quote. A quote that does not check out is returned **flagged,
never refused**: a model that stops citing is a worse outcome than a citation the reader
sees marked as unverified. A quote too short to prove anything is unverified for the same
reason a check that always passes is not a check.

**Handles are allocated per chat session**, not per turn. `[D7]` from the first turn has to
still resolve in the ninth, because the answer that used it is still on screen. The table
is bounded and evicts whole sessions rather than individual handles: a session that falls
out gets fresh numbering, and `[D3]` meaning two documents inside one conversation is worse
than `[D1]` starting over.

## The ACL

The agent acts *on behalf of a user*, so every call is bounded by two headers:

* `Authorization: Bearer <MCP_SHARED_SECRET>` — proves the caller is the website/agent
  tier and not something else that found the port.
* `X-Hoover4-Collections` — the user's permitted collections, resolved by the website
  backend, which is the only component that can read `collection_group_permissions`.

**This server never derives permissions**, it only enforces the list it is handed. Putting
the ACL in a tool argument would let the model choose its own permissions; re-deriving it
here would mean a second implementation of the group/public union that could drift from
the website's. See [`collection_search_server/acl.py`](collection_search_server/acl.py).

## MATCH syntax — operators pass through

`sanitize_match_query` used to **strip** every operator character (`!"$()-/<@^|~*`) on the
grounds that an LLM writes prose, not query syntax. That is wrong: the operators are
valuable and the model is told how to use them. The canonical syntax reference lives in
[`collection_search_server/prompts/`](collection_search_server/prompts/) and reaches the
model as the server's FastMCP `instructions`, i.e. at tool-discovery time. The instructions
are rendered from `SERVER_TOOLS`, the tool names this server registers, and
`tests/test_prompts.py` fails when that list stops matching what `server.py` decorates —
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

Repairs are reported back in the response's `note`, and Manticore's own error text is now
returned in `error` rather than only logged — a syntax error the model never sees is one
it cannot correct.

**The escaping is unchanged and is the injection barrier.** `\` and `'` are what could
break out of the single-quoted SQL literal; that is a separate concern from the query
language living inside it, and passing operators through does not weaken it (`"` is
harmless in a single-quoted literal).

`page_text` is the **only** full-text field. Everything else in the shard schema
(`collection_dataset`, `file_hash`, `extracted_by`, `page_id`, `ner_*`) is an attribute
and belongs in `WHERE`.

## Wildcards work now

Infix indexing was turned on in `main_services/processing/database/manticore.py` and the
collections reindexed. Before, `doc*` returned a *wrong* answer rather than none — the
star was dropped during tokenisation and a truncated literal was searched:

| query | before | after |
|---|---|---|
| `document` | 16 | 16 |
| `docum*` | 0 | 19 |
| `*ocument*` | 0 | 42 |
| `doc*` | **7 (wrong)** | 34 |
| `te*t` | **3 (wrong)** | 28 |

Changing that setting requires a **reindex** — `ALTER TABLE` updates the metadata and
leaves the old index in place, so `SHOW TABLE ... SETTINGS` will report the new value
while queries keep returning the old answers. See
[`../../../main_services/processing/database/Readme.md`](../../../main_services/processing/database/Readme.md).

## How big a search result may be

**The size of the serialised response is the bound. The count is only a ceiling.**

`_apply_payload_budget` measures `SearchResponse.model_dump_json()` and holds it under
`SEARCH_PAYLOAD_BUDGET_CHARS` (24 000). It first shrinks every snippet to an equal share
of what is left after the envelopes, clamped between `SEARCH_MIN_SNIPPET_CHARS` (120) and
`SEARCH_SNIPPET_CHARS` (1200); when the envelopes alone no longer leave room for a
readable line each, it drops the lowest-ranked hits and says so in `note`. Eight hits
still get the full 1 200 characters each; a request for 200 comes back as ~60 with a line
apiece. Reading them properly is `read_documents`.

Bounding a field is not bounding a payload. A per-snippet budget with a count cap leaves
every hit's envelope — `collection_dataset`, `collectionname`, a 64-character `file_hash`,
`match_sources`, `page_id`, `path`, `score` — unmeasured at ~250 characters each, so 200
results are 50 000 characters of ids and paths on top of whatever the snippets are allowed:
a prompt that is heavier than the one a count cap alone produces, while the cap does exactly
what it says. Envelopes also vary — a deep path costs several times a shallow one — which is
why they are measured per hit rather than assumed.

The budget matches the website's cap on a stored `tool_output`
(`common/src/chat_types.rs`), and that is the point: a result that fits is stored whole,
so `chat_messages.tool_output` is an honest copy of what the model saw rather than a
truncated one that cannot answer the question. Every call also logs
`search_collections payload: N chars, K of M hit(s) returned` — the only place the size
the model actually received is observable.

`max_results` is clamped to `SEARCH_MAX_ALLOWED_RESULTS` (200) and defaults to
`SEARCH_MAX_RESULTS` (50) — a model that asks for `10000` gets 200 — but it decides how
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
got twenty back — at 1200 snippet characters each, into an agent's context window. It is
`3` now.

The *ceiling* has the opposite failure. `COLLECTION_SEARCH_MAX_PER_KIND` is a diversity
guard for small result sets, and left at a constant it silently becomes the real cap on a
hybrid search — two kinds x 15 is 30 hits however many were asked for. It is raised to
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
| `MAX_DOCUMENT_CHARS` | `40000` |
| `SERVER_INSTRUCTIONS` | overrides the rendered instructions; empty means render `prompts/` |

## Tests

```bash
docker exec hoover4-mcp-collections python -m pytest tests/ -q   # 72 tests
```

Everything in `tests/test_acl.py` is pure — no database — because the ACL and the query
sanitiser are the security-relevant parts. The operator table above is asserted case by
case there.
