"""FastMCP server exposing Hoover4 collection search to agents, bounded by an ACL.

Tools:
    ``list_collections``      what the calling user may read
    ``search_collections``    hybrid search across the permitted Manticore shards
    ``get_document_text``     the extracted text of one document
    ``list_document_entities`` named entities found in one document

Every tool resolves the caller's ACL from request headers (see :mod:`.acl`) before it
touches a database, and every collection name reaching SQL has been validated against
the shared collectionname rule.

Search is **hybrid** when the embeddings stack is probed (`server_settings.
embeddings_serving_model` + `EMBEDDINGS_URL`): a keyword ranking from the `_pages`
shards and a vector ranking from the `_vectors` shards are RRF-fused
(`agent_common.fusion`, the same module metasearch uses), reranked through the same
cross-encoder client, and put through the per-kind floor so keyword-exact hits cannot
drown semantic ones. With no probe or a dead GPU the tool degrades to the
keyword-only path and says so in `note` — a GPU outage must degrade search quality,
not remove search.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from agent_common import embeddings as embeddings_client
from agent_common import fusion, rerank as rerank_client
from collection_search_server import vectors
from collection_search_server.acl import AccessDenied, CallerAcl, parse_acl
from collection_search_server.backends import (
    GLOBAL_DB,
    clickhouse_query,
    collection_db,
    manticore_query,
    prepare_match_query,
)
from collection_search_server.prompts import MATCH_SYNTAX, SERVER_INSTRUCTIONS

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

#: Default and hard cap on results. The cap exists because every hit carries a text
#: snippet into the agent's context window; an unbounded search would blow the context
#: long before it blew any database. A model that asks for 10 000 gets 200.
#:
#: The default is deliberately most of the cap. Latency here is one provider round trip
#: per tool call and is almost independent of how much comes back, so a search that has
#: to be run four times to see what one run could have shown costs four times as much
#: wall clock for the same answer — the weight of a result set is bounded by
#: `SNIPPET_BUDGET_CHARS` below, not by counting it.
DEFAULT_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "50"))
MAX_ALLOWED_RESULTS = int(os.getenv("SEARCH_MAX_ALLOWED_RESULTS", "200"))

#: How much page text one hit may contribute, in characters.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "1200"))

#: Total snippet text one search may return, across every hit.
#:
#: **A result count is not a size.** 46 hits of 1 200 characters is a 27 800-token prompt
#: and a 22 KB transcript page, and neither number is visible in `max_results`, so the cap
#: on the count cannot be the only bound — it is why the website truncates a stored
#: `tool_output` at the same 24 000 characters (`common/src/chat_types.rs`). The per-hit
#: allowance is this budget divided by the number of hits, clamped between
#: `MIN_SNIPPET_CHARS` and `SNIPPET_CHARS`: a handful of hits still get the full 1 200
#: each, and a 200-hit survey gets a line apiece, which is what a survey is for. Reading
#: one properly is `get_document_text`.
SNIPPET_BUDGET_CHARS = int(os.getenv("SEARCH_SNIPPET_BUDGET_CHARS", "24000"))

#: Floor on the per-hit snippet, so a large result set still says why each hit matched.
MIN_SNIPPET_CHARS = int(os.getenv("SEARCH_MIN_SNIPPET_CHARS", "120"))

#: How much text `get_document_text` may return in one call.
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "40000"))

#: Candidate pool per shard (keyword) and per `_vectors` shard (KNN) when the fused
#: pipeline runs, and the cap on the fused pool sent to the reranker.
FUSION_CANDIDATES = int(os.getenv("COLLECTION_SEARCH_FUSION_CANDIDATES", "60"))

#: The per-kind floor after reranking: each of the `keyword` and `vector` kinds keeps
#: its best results even when the other kind dominates the fused order (RRF is a
#: popularity measure; keyword-exact hits would otherwise drown semantic ones).
#:
#: **The floor must stay well under `max_results`.** A reserved slot outranks the cap by
#: design (`per_kind_floor` never evicts one), so a floor of 10 over two kinds reserved 20
#: results and the caller's `max_results=8` did nothing at all — `search_collections` was
#: returning 20 hits to a model that asked for 8, at 1200 snippet characters each. Three
#: is enough to keep a minority ranking visible without overriding the cap.
#:
#: `MAX_PER_KIND` is a diversity guard for small result sets and is raised to `max_results`
#: when that is larger: left at a constant it becomes the real cap on a hybrid search (two
#: kinds x 15 = 30 hits, whatever was asked for), and a tool that advertises 200 must be
#: able to return them when the embeddings stack happens to be up.
MIN_PER_KIND = int(os.getenv("COLLECTION_SEARCH_MIN_PER_KIND", "3"))
MAX_PER_KIND = int(os.getenv("COLLECTION_SEARCH_MAX_PER_KIND", "15"))

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_collection_search"),
    # The canonical text lives in `prompts.py`; the env var is a thin override for
    # experiments. This string is what the model reads at tool-discovery time, so the
    # MATCH syntax has to be in here and not only in the agent's system prompt — the
    # full-research agent has its own prompt and would otherwise never see it.
    instructions=os.getenv("SERVER_INSTRUCTIONS", SERVER_INSTRUCTIONS),
)


class CollectionInfo(BaseModel):
    collectionname: str = Field(description="Identifier to pass to the other tools")
    fullname: str = Field(description="Human-readable collection name")
    document_count: int = Field(description="Documents indexed for search")


class SearchHit(BaseModel):
    collectionname: str
    collection_dataset: str = Field(description="Dataset within the collection")
    file_hash: str = Field(description="Document id, pass to get_document_text")
    path: str | None = Field(default=None, description="File path, when known")
    page_id: int = Field(description="Page or segment number within the document")
    score: float | None = Field(
        default=None,
        description="BM25 for keyword-only searches, the fused RRF score when the vector pipeline ran",
    )
    snippet: str = Field(description="Matching text")
    match_sources: list[str] = Field(
        default_factory=list,
        description="Which rankings found this hit: keyword, vector, or both",
    )


class _Candidate:
    """One search candidate before fusion: a keyword hit, a vector hit, or both.

    Fused at page granularity — a vector hit knows its chunk, but the answer a hit
    points at is the page, and the chunk text becomes the snippet (the matched
    passage, more precise than a page excerpt).
    """

    __slots__ = ("collectionname", "collection_dataset", "file_hash", "page_id",
                 "keyword_score", "text")

    def __init__(self, collectionname: str, collection_dataset: str, file_hash: str,
                 page_id: int, keyword_score: float = 0.0, text: str = ""):
        self.collectionname = collectionname
        self.collection_dataset = collection_dataset
        self.file_hash = file_hash
        self.page_id = page_id
        self.keyword_score = keyword_score
        self.text = text

    def key(self) -> tuple[str, str, str, int]:
        return (self.collectionname, self.collection_dataset, self.file_hash, self.page_id)


class SearchResponse(BaseModel):
    success: bool
    query: str
    collections_searched: list[str]
    results: list[SearchHit]
    error: str | None = None
    note: str | None = Field(
        default=None, description="Caveats about this result set, if any"
    )


class DocumentText(BaseModel):
    success: bool
    collectionname: str = ""
    file_hash: str = ""
    path: str | None = None
    text: str = ""
    truncated: bool = False
    error: str | None = None


class DocumentEntities(BaseModel):
    success: bool
    collectionname: str = ""
    file_hash: str = ""
    entities: dict[str, list[str]] = Field(
        default_factory=dict, description="Entity type -> distinct values"
    )
    error: str | None = None


#: A content hash as the pipeline writes them: hex, 32-128 chars (md5 through sha3-512).
_HASH_RE = re.compile(r"^[0-9a-f]{32,128}$")


def _is_hash(value: str) -> bool:
    return bool(_HASH_RE.match(value or ""))


def _caller() -> CallerAcl:
    """The ACL of the in-flight request."""
    return parse_acl(dict(get_http_headers()))


def _as_collection_list(value: Any) -> list[str] | None:
    """Coerce whatever the model sent for `collections` into a list of names.

    XML-style tool-call parsers — `qwen3_xml`, which Qwen3.5 requires — hand every
    parameter across as a **string**, so a `list[str]` argument arrives as the literal
    `'["testdata"]'` rather than a list. Pydantic then rejects it, the tool returns a
    validation error, and the model retries the identical call forever: the agent burned
    its entire 25-step recursion budget without ever running a search. A one-line
    coercion here is much cheaper than that failure, and it costs nothing when the
    argument already arrives well-formed.

    Accepts a real list, a JSON-encoded list, or a bare/comma-separated name.
    """
    if value is None or isinstance(value, list):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _shard_tables(collectionname: str) -> list[str]:
    """Live Manticore page-table names for a collection, newest shard first.

    Read from the collection's own shard ledger rather than `SHOW TABLES` so a shard
    that exists in Manticore but is not registered (a half-finished migration) is not
    searched.
    """
    rows = clickhouse_query(
        "SELECT DISTINCT shard_name FROM manticore_shards FINAL ORDER BY shard_name DESC",
        database=collection_db(collectionname),
    )
    return [f"{r['shard_name']}_pages" for r in rows if r.get("shard_name")]


@mcp.tool(
    name="list_collections",
    description=(
        "List the document collections this user is allowed to search. Always call "
        "this before searching so you use real collection names."
    ),
)
def list_collections() -> list[CollectionInfo]:
    acl = _caller()
    log.info("list_collections user=%s acl=%s", acl.username, list(acl.collections))

    infos: list[CollectionInfo] = []
    for name in acl.collections:
        fullname = name
        rows = clickhouse_query(
            "SELECT fullname FROM collections FINAL WHERE collectionname = {name:String} "
            "AND is_deleted = 0",
            database=GLOBAL_DB,
            params={"name": name},
        )
        if rows:
            fullname = rows[0].get("fullname") or name

        # A collection whose database is not provisioned yet raises rather than
        # returning zero, and one unprovisioned collection must not break the whole
        # listing — the agent still needs to know the others exist.
        try:
            counted = clickhouse_query(
                "SELECT uniqExact(file_hash) AS n FROM index_state",
                database=collection_db(name),
            )
            document_count = int(counted[0]["n"]) if counted else 0
        except Exception as exc:  # noqa: BLE001 - surfaced as a zero count, logged here
            log.warning("could not count documents in %s: %s", name, exc)
            document_count = 0

        infos.append(
            CollectionInfo(
                collectionname=name, fullname=fullname, document_count=document_count
            )
        )
    return infos


def _snippet_chars_for(hit_count: int) -> int:
    """The per-hit snippet allowance for a result set of `hit_count` hits."""
    if hit_count <= 0:
        return SNIPPET_CHARS
    share = SNIPPET_BUDGET_CHARS // hit_count
    return max(MIN_SNIPPET_CHARS, min(SNIPPET_CHARS, share))


def _apply_snippet_budget(hits: list[SearchHit]) -> None:
    """Trim snippets in place so the whole result set fits the budget.

    Applied after ranking, never before: the fused order and the cross-encoder both score
    the full passage, and scoring a truncated one would change which documents come back,
    not only how much of them does.
    """
    allowance = _snippet_chars_for(len(hits))
    for hit in hits:
        if len(hit.snippet) > allowance:
            hit.snippet = hit.snippet[:allowance].rstrip() + "…"


@mcp.tool(
    name="search_collections",
    description=(
        "Full-text search across the user's document collections. Returns matching "
        "text passages with the document id needed to read the full document. Phrase "
        "the query as a sentence or several descriptive words rather than one keyword. "
        f"Leave max_results at the default of {DEFAULT_MAX_RESULTS}: it is already a "
        "broad look at the collections, and asking for more returns a shorter passage "
        "from each rather than more to read. Use get_document_text to read a hit in full."
    ),
)
def search_collections(
    query: str,
    collections: list[str] | str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> SearchResponse:
    """Search, fanning out over every live shard of every permitted collection.

    `collections` is typed to accept a string as well as a list because XML-style
    tool-call parsers send it as one — see :func:`_as_collection_list`. Declaring the
    union keeps the coercion out of pydantic's way rather than fighting it.
    """
    try:
        acl = _caller()
        targets = acl.check(_as_collection_list(collections))
    except AccessDenied as exc:
        return SearchResponse(
            success=False, query=query, collections_searched=[], results=[], error=str(exc)
        )

    if not query or not query.strip():
        return SearchResponse(
            success=False,
            query=query,
            collections_searched=targets,
            results=[],
            error="query cannot be empty",
        )

    limit = max(1, min(int(max_results), MAX_ALLOWED_RESULTS))
    prepared = prepare_match_query(query)
    if not prepared.expr:
        # Hand back the syntax reference along with the complaint: the model gets one
        # shot at understanding what went wrong, and "unbalanced quote" is only
        # actionable next to the rules it broke.
        return SearchResponse(
            success=False,
            query=query,
            collections_searched=targets,
            results=[],
            error=f"{prepared.error or 'query contained no searchable terms'}\n\n{MATCH_SYNTAX}",
        )
    match_expr = prepared.expr

    notes = list(prepared.repairs)

    # The vector branch decides the keyword candidate budget: a keyword-only search
    # fetches `limit` rows per shard as it always did, while a fused search needs a
    # candidate pool deep enough for RRF and the reranker to be worth running.
    vector_model = None
    if embeddings_client.endpoint():
        try:
            vector_model = vectors.serving_model()
        except Exception as exc:  # noqa: BLE001 - degrade to keyword-only, say so
            log.warning("could not read embeddings_serving_model: %s", exc)
            notes.append(f"vector search unavailable: could not read the serving model ({exc})")
    per_shard_limit = max(FUSION_CANDIDATES, limit) if vector_model else limit

    candidates: list[_Candidate] = []
    failed_targets: list[str] = []
    #: Manticore's own words about a bad query. Kept so they can be returned rather than
    #: only logged — a syntax error the model never sees is one it cannot correct.
    shard_errors: list[str] = []

    for collectionname in targets:
        try:
            tables = _shard_tables(collectionname)
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot list shards of %s: %s", collectionname, exc)
            failed_targets.append(collectionname)
            continue

        for table in tables:
            # Per-shard limit is the full limit: a shard that holds every good match
            # must be able to supply them all. Over-fetching is trimmed after merging.
            sql = (
                f"SELECT collection_dataset, file_hash, page_id, page_text, WEIGHT() AS score "
                f"FROM {table} WHERE MATCH('{match_expr}') "
                f"ORDER BY score DESC LIMIT {per_shard_limit} OPTION max_matches={per_shard_limit * 10}"
            )
            try:
                rows = manticore_query(sql)
            except Exception as exc:  # noqa: BLE001 - one bad shard must not blank the page
                log.warning("shard %s failed: %s", table, exc)
                failed_targets.append(table)
                shard_errors.append(str(exc))
                continue

            for row in rows:
                candidates.append(
                    _Candidate(
                        collectionname=collectionname,
                        collection_dataset=row.get("collection_dataset", ""),
                        file_hash=row.get("file_hash", ""),
                        page_id=int(row.get("page_id") or 0),
                        keyword_score=float(row["score"]) if row.get("score") is not None else 0.0,
                        text=(row.get("page_text") or "")[:SNIPPET_CHARS],
                    )
                )

    # BM25 statistics are per-table, so scores from different shards are only roughly
    # comparable — the same caveat the website's search fan-out carries.
    candidates.sort(key=lambda c: c.keyword_score, reverse=True)
    keyword_list = candidates

    # The vector half: embed the query with the probed serving model's query
    # convention, KNN every live _vectors shard, nearest first.
    vector_list: list[vectors.VectorCandidate] = []
    vector_branch_ran = False
    if vector_model:
        try:
            query_vector = embeddings_client.embed_query(query, vector_model)
            vector_branch_ran = True
            vector_list = vectors.search(query_vector, targets)
        except embeddings_client.EmbeddingUnavailable as exc:
            notes.append(f"vector search unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001 - a search must still answer
            log.exception("vector search failed")
            notes.append(f"vector search failed: {exc}")

    if vector_branch_ran:
        hits = _fused_pipeline(query, keyword_list, vector_list, limit, notes)
    else:
        hits = [
            SearchHit(
                collectionname=c.collectionname,
                collection_dataset=c.collection_dataset,
                file_hash=c.file_hash,
                page_id=c.page_id,
                score=c.keyword_score,
                snippet=c.text,
                match_sources=["keyword"],
            )
            for c in keyword_list[:limit]
        ]
    _attach_paths(hits)
    _apply_snippet_budget(hits)

    if failed_targets:
        notes.append(
            f"{len(failed_targets)} shard(s) could not be queried; results are partial"
        )

    # Every shard failing on the same query is a query problem, not an infrastructure
    # problem, and the model is the only one who can fix it. Surface Manticore's text
    # verbatim — `no field 'title' found in schema` tells it exactly what to change.
    error = None
    if shard_errors and not hits:
        error = f"{sorted(set(shard_errors))[0]}\n\n{MATCH_SYNTAX}"

    return SearchResponse(
        success=not error,
        query=query,
        collections_searched=targets,
        results=hits,
        error=error,
        note="; ".join(notes) or None,
    )


def _fused_pipeline(
    query: str,
    keyword_list: list[_Candidate],
    vector_list: "list[vectors.VectorCandidate]",
    limit: int,
    notes: list[str],
) -> list[SearchHit]:
    """Fuse keyword + vector rankings (RRF), rerank, apply the per-kind floor.

    The order is not interchangeable: rerank the whole fused candidate pool, THEN take
    the best per kind — flooring first would let the reranker reorder an
    already-truncated set. A rerank failure keeps the fused order and says so in the
    notes; a GPU outage must degrade search quality, not remove search.
    """
    by_key: dict[tuple, _Candidate] = {}
    for c in keyword_list:
        by_key.setdefault(c.key(), c)
    vector_candidates: list[_Candidate] = []
    #: Pages whose snippet already came from a chunk. `vector_list` is nearest-first, so
    #: the first chunk seen for a page is its best one — and assigning unconditionally
    #: meant the *last*, i.e. the FARTHEST, chunk of a multi-chunk page won. That text is
    #: also what the reranker scores, so a page was being judged on its least relevant
    #: passage and then shown to the user with it.
    snippet_from_chunk: set[tuple] = set()
    for v in vector_list:
        key = (v.collectionname, v.collection_dataset, v.file_hash, v.page_id)
        c = by_key.get(key)
        if c is None:
            c = _Candidate(
                collectionname=v.collectionname,
                collection_dataset=v.collection_dataset,
                file_hash=v.file_hash,
                page_id=v.page_id,
            )
            by_key[key] = c
        if v.text and key not in snippet_from_chunk:
            # The chunk is the matched passage; it makes a better snippet than the
            # page excerpt the keyword half brought.
            c.text = v.text[:SNIPPET_CHARS]
            snippet_from_chunk.add(key)
        vector_candidates.append(c)

    fused = fusion.fuse_ranked_lists(
        {"keyword": keyword_list, "vector": vector_candidates},
        key_of=lambda c: c.key(),
        # Never fewer candidates than the caller asked for results, or the pool decides
        # the answer size instead of `max_results`.
        max_results=max(FUSION_CANDIDATES, limit),
    )

    ordered = fused
    rerank_applied = False
    try:
        scores, rerank_ms = rerank_client.rerank(query, [f.item.text for f in fused])
        if scores:
            seen: set[int] = set()
            ordered = []
            for s in scores:
                if 0 <= s.index < len(fused) and s.index not in seen:
                    seen.add(s.index)
                    ordered.append(fused[s.index])
            # A partial rerank response must not delete the candidates it did not score:
            # they were real hits with a real fused position, and dropping them silently
            # shrinks the search. They keep their fused order behind the scored ones.
            ordered += [f for i, f in enumerate(fused) if i not in seen]
            rerank_applied = True
    except rerank_client.RerankUnavailable as exc:
        notes.append(f"rerank unavailable ({exc}); showing the fused order")
    except Exception as exc:  # noqa: BLE001 - a search must still answer
        log.exception("rerank failed unexpectedly")
        notes.append(f"rerank failed: {exc}; showing the fused order")

    final = fusion.per_kind_floor(
        ordered,
        max_results=limit,
        kind_of=lambda f: "vector" if "vector" in f.source_ranks else "keyword",
        min_per_kind=MIN_PER_KIND,
        max_per_kind=max(MAX_PER_KIND, limit),
    )
    notes.append(
        f"{len(keyword_list)} keyword + {len(vector_list)} vector candidates, "
        f"{len(fused)} after fusion"
        + (f", cross-encoder reranked in {rerank_ms:.0f} ms" if rerank_applied else "")
    )
    return [
        SearchHit(
            collectionname=f.item.collectionname,
            collection_dataset=f.item.collection_dataset,
            file_hash=f.item.file_hash,
            page_id=f.item.page_id,
            score=round(f.score, 6),
            snippet=f.item.text,
            match_sources=sorted(f.source_ranks.keys()),
        )
        for f in final
    ]


def _attach_paths(hits: list[SearchHit]) -> None:
    """Fill in `path` for each hit, one query per collection rather than one per hit."""
    by_collection: dict[str, list[SearchHit]] = {}
    for hit in hits:
        if hit.file_hash:
            by_collection.setdefault(hit.collectionname, []).append(hit)

    for collectionname, group in by_collection.items():
        # The array literal below is assembled by hand (ClickHouse takes Array params as
        # text), so anything that is not a plain content hash is dropped rather than
        # interpolated. These come back from Manticore, so they should always be hex —
        # this is the belt to that braces.
        hashes = sorted({h.file_hash for h in group if _is_hash(h.file_hash)})
        if not hashes:
            continue
        try:
            rows = clickhouse_query(
                "SELECT hash, any(path) AS path FROM vfs_files "
                "WHERE hash IN {hashes:Array(String)} GROUP BY hash",
                database=collection_db(collectionname),
                params={"hashes": "['" + "','".join(hashes) + "']"},
            )
        except Exception as exc:  # noqa: BLE001 - a missing path is cosmetic
            log.warning("path lookup failed for %s: %s", collectionname, exc)
            continue
        paths = {r["hash"]: r["path"] for r in rows}
        for hit in group:
            hit.path = paths.get(hit.file_hash)


@mcp.tool(
    name="get_document_text",
    description=(
        "Read the extracted text of one document, identified by the file_hash returned "
        "from search_collections. Use this to check a promising hit before citing it."
    ),
)
def get_document_text(collectionname: str, file_hash: str) -> DocumentText:
    try:
        acl = _caller()
        acl.check([collectionname])
    except AccessDenied as exc:
        return DocumentText(success=False, error=str(exc))

    if not _is_hash(file_hash):
        return DocumentText(
            success=False,
            error="file_hash must be a content hash from search_collections",
        )

    try:
        rows = clickhouse_query(
            "SELECT text FROM text_content FINAL WHERE file_hash = {hash:String} "
            "ORDER BY extracted_by, page_id",
            database=collection_db(collectionname),
            params={"hash": file_hash},
        )
        path_rows = clickhouse_query(
            "SELECT any(path) AS path FROM vfs_files WHERE hash = {hash:String}",
            database=collection_db(collectionname),
            params={"hash": file_hash},
        )
    except Exception as exc:  # noqa: BLE001
        return DocumentText(success=False, error=f"lookup failed: {exc}")

    if not rows:
        return DocumentText(
            success=False,
            collectionname=collectionname,
            file_hash=file_hash,
            error="no extracted text for this document",
        )

    text = "\n\n".join(r.get("text", "") for r in rows)
    truncated = len(text) > MAX_DOCUMENT_CHARS
    return DocumentText(
        success=True,
        collectionname=collectionname,
        file_hash=file_hash,
        path=(path_rows[0].get("path") if path_rows else None) or None,
        text=text[:MAX_DOCUMENT_CHARS],
        truncated=truncated,
    )


@mcp.tool(
    name="list_document_entities",
    description=(
        "List the named entities (people, organisations, locations) the pipeline "
        "extracted from one document. Useful for finding names to search for next."
    ),
)
def list_document_entities(collectionname: str, file_hash: str) -> DocumentEntities:
    try:
        acl = _caller()
        acl.check([collectionname])
    except AccessDenied as exc:
        return DocumentEntities(success=False, error=str(exc))

    if not _is_hash(file_hash):
        return DocumentEntities(
            success=False,
            error="file_hash must be a content hash from search_collections",
        )

    try:
        # `entity_values` is itself an Array(String) per row, so the per-type list is a
        # flatten of the group before it is deduplicated.
        rows = clickhouse_query(
            "SELECT entity_type, arrayDistinct(arrayFlatten(groupArray(entity_values))) AS values "
            "FROM entity_hit FINAL WHERE file_hash = {hash:String} GROUP BY entity_type",
            database=collection_db(collectionname),
            params={"hash": file_hash},
        )
    except Exception as exc:  # noqa: BLE001
        return DocumentEntities(success=False, error=f"lookup failed: {exc}")

    return DocumentEntities(
        success=True,
        collectionname=collectionname,
        file_hash=file_hash,
        entities={r["entity_type"]: list(r["values"]) for r in rows},
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "hoover4-collection-search"})


def main() -> None:
    log.info("Starting Hoover4 collection search MCP server")
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8085")),
    )


if __name__ == "__main__":
    main()
