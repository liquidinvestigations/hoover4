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
| `get_document_text` | the extracted text of one document, by `file_hash` |
| `list_document_entities` | named entities in one document, for finding what to search next |

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

## MATCH syntax — operators pass through now (Q7)

`sanitize_match_query` used to **strip** every operator character (`!"$()-/<@^|~*`) on the
grounds that an LLM writes prose, not query syntax. Q7 reversed that: the operators are
valuable and the model is told how to use them. The canonical syntax reference lives in
[`collection_search_server/prompts.py`](collection_search_server/prompts.py) and reaches
the model as the server's FastMCP `instructions`, i.e. at tool-discovery time.

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

## The per-kind floor must stay under `max_results`

After RRF and reranking, `per_kind_floor` reserves each of the `keyword` and `vector`
rankings its own best results so an exact-term match cannot drown a semantic one. **A
reserved slot is never evicted by the overall cap**, so the floor has to be well under it:
at `10` per kind, two kinds reserved twenty results and a caller asking for `max_results=8`
got twenty back — at 1200 snippet characters each, into an agent's context window. It is
`3` now.

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
| `SEARCH_MAX_RESULTS` | `8` |
| `SEARCH_SNIPPET_CHARS` | `1200` |
| `COLLECTION_SEARCH_MIN_PER_KIND` / `_MAX_PER_KIND` | `3` / `15` |
| `COLLECTION_SEARCH_FUSION_CANDIDATES` | `60` |
| `MAX_DOCUMENT_CHARS` | `40000` |
| `SERVER_INSTRUCTIONS` | overrides the canonical prompt; empty means use `prompts.py` |

## Tests

```bash
docker exec hoover4-mcp-collections python -m pytest tests/ -q   # 60 tests
```

Everything in `tests/test_acl.py` is pure — no database — because the ACL and the query
sanitiser are the security-relevant parts. The operator table above is asserted case by
case there.
