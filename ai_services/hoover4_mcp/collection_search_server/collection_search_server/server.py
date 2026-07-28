"""FastMCP server exposing Hoover4 collection search to agents, bounded by an ACL.

Tools:
    ``list_collections``      what the calling user may read
    ``search_collections``    full-text search across the permitted Manticore shards
    ``get_document_text``     the extracted text of one document
    ``list_document_entities`` named entities found in one document

Every tool resolves the caller's ACL from request headers (see :mod:`.acl`) before it
touches a database, and every collection name reaching SQL has been validated against
the shared collectionname rule.

Search goes through **Manticore**, not Milvus: the ingestion pipeline writes its text to
Manticore shards and its extracted text to ClickHouse, and never populates Milvus (see
`plans/3-auth-and-ai/open-questions.md` Q1/Q3).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from collection_search_server.acl import AccessDenied, CallerAcl, parse_acl
from collection_search_server.backends import (
    GLOBAL_DB,
    clickhouse_query,
    collection_db,
    manticore_query,
    sanitize_match_query,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

#: Default and hard cap on results. The cap exists because every hit carries a text
#: snippet into the agent's context window; an unbounded search would blow the context
#: long before it blew any database.
DEFAULT_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "8"))
MAX_ALLOWED_RESULTS = int(os.getenv("SEARCH_MAX_ALLOWED_RESULTS", "50"))

#: How much page text one hit may contribute, in characters.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "1200"))

#: How much text `get_document_text` may return in one call.
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "40000"))

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_collection_search"),
    instructions=os.getenv(
        "SERVER_INSTRUCTIONS",
        "Search the user's document collections in Hoover4. Call list_collections "
        "first to see what is available. Queries should be well-phrased search "
        "phrases: several words describing the content you need works far better "
        "than a single keyword. Use get_document_text to read a promising hit in "
        "full before answering.",
    ),
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
    score: float | None = Field(default=None, description="Relevance score (BM25)")
    snippet: str = Field(description="Matching text")


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


@mcp.tool(
    name="search_collections",
    description=(
        "Full-text search across the user's document collections. Returns matching "
        "text passages with the document id needed to read the full document. Phrase "
        "the query as a sentence or several descriptive words rather than one keyword."
    ),
)
def search_collections(
    query: str,
    collections: list[str] | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> SearchResponse:
    """Search, fanning out over every live shard of every permitted collection."""
    try:
        acl = _caller()
        targets = acl.check(collections)
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
    match_expr = sanitize_match_query(query)
    if not match_expr:
        return SearchResponse(
            success=False,
            query=query,
            collections_searched=targets,
            results=[],
            error="query contained no searchable terms",
        )

    hits: list[SearchHit] = []
    failed_targets: list[str] = []

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
                f"ORDER BY score DESC LIMIT {limit} OPTION max_matches={limit * 10}"
            )
            try:
                rows = manticore_query(sql)
            except Exception as exc:  # noqa: BLE001 - one bad shard must not blank the page
                log.warning("shard %s failed: %s", table, exc)
                failed_targets.append(table)
                continue

            for row in rows:
                text = (row.get("page_text") or "")[:SNIPPET_CHARS]
                hits.append(
                    SearchHit(
                        collectionname=collectionname,
                        collection_dataset=row.get("collection_dataset", ""),
                        file_hash=row.get("file_hash", ""),
                        page_id=int(row.get("page_id") or 0),
                        score=float(row["score"]) if row.get("score") is not None else None,
                        snippet=text,
                    )
                )

    # BM25 statistics are per-table, so scores from different shards are only roughly
    # comparable — the same caveat the website's search fan-out carries.
    hits.sort(key=lambda h: h.score or 0.0, reverse=True)
    hits = hits[:limit]
    _attach_paths(hits)

    note = None
    if failed_targets:
        note = f"{len(failed_targets)} shard(s) could not be queried; results are partial"

    return SearchResponse(
        success=True,
        query=query,
        collections_searched=targets,
        results=hits,
        note=note,
    )


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
