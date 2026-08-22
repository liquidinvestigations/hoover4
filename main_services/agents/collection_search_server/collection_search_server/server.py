"""FastMCP server exposing Hoover4 collection search to agents, bounded by an ACL.

Tools:
    ``list_collections``      what the calling user may read
    ``search_collections``    hybrid search across the permitted Manticore shards
    ``read_documents``        the extracted text of several documents
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

from agent_common import batching, retired
from agent_common import embeddings as embeddings_client
from agent_common import fusion, rerank as rerank_client
from collection_search_server import vectors
from collection_search_server.acl import AccessDenied, CallerAcl, parse_acl
from collection_search_server.citations import (
    HandleTable,
    MIN_QUOTE_CHARS,
    quote_occurs_in,
)
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
#: `PAYLOAD_BUDGET_CHARS` below, not by counting it. Neither number is a size, and the
#: budget is what actually decides how many results come back.
DEFAULT_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "50"))
MAX_ALLOWED_RESULTS = int(os.getenv("SEARCH_MAX_ALLOWED_RESULTS", "200"))

#: How much page text one hit may contribute, in characters.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "1200"))

#: Total size of the serialised result, across every hit, envelopes included.
#:
#: **A result count is not a size, and neither is a snippet budget.** Bounding only the
#: snippet text leaves every hit's envelope unbounded — `collection_dataset`,
#: `collectionname`, a 64-character `file_hash`, `match_sources`, `page_id`, `path`,
#: `score` measure ~250 characters and tokenise badly — so 200 hits carrying 24 000
#: characters of snippet are a 74 000-character payload: a heavier prompt than the one an
#: uncapped count produces, which is the trap in bounding a field instead of the message.
#: What the model receives is the serialised `SearchResponse`, so that is what is
#: measured and that is what is bounded, by dropping the lowest-ranked hits until it
#: fits. `max_results` is a ceiling on the count and never a promise.
#:
#: 24 000 is the same figure the website truncates a stored `tool_output` at
#: (`common/src/chat_types.rs`), which is the point: a result that fits the budget is
#: stored whole, so `chat_messages.tool_output` is an honest copy of what the model saw
#: instead of a truncated one that cannot be used to check the size.
PAYLOAD_BUDGET_CHARS = int(os.getenv("SEARCH_PAYLOAD_BUDGET_CHARS", "24000"))

#: Floor on the per-hit snippet, so a large result set still says why each hit matched.
MIN_SNIPPET_CHARS = int(os.getenv("SEARCH_MIN_SNIPPET_CHARS", "120"))

#: How much text one document may contribute to a `read_documents` call.
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

mcp.add_middleware(
    retired.RetiredNames(
        {
            "get_document_text": (
                "read_documents",
                "it reads several documents in one call, each named by its "
                "collectionname and file_hash",
            ),
        }
    )
)


class CollectionInfo(BaseModel):
    collectionname: str = Field(description="Identifier to pass to the other tools")
    fullname: str = Field(description="Human-readable collection name")
    document_count: int = Field(description="Documents indexed for search")


class SearchHit(BaseModel):
    collectionname: str
    collection_dataset: str = Field(description="Dataset within the collection")
    file_hash: str = Field(description="Document id, pass to read_documents")
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
    matched_queries: list[str] = Field(
        default_factory=list,
        description=(
            "Which of your queries returned this passage. A hit several queries agree "
            "on is better corroborated than one only a single query found."
        ),
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
    #: Every query this call ran, joined. Kept alongside `queries` because the website's
    #: transcript renderer and every stored historical row read this field, and a card
    #: that renders old rows is not optional.
    query: str
    queries: list[str] = Field(
        default_factory=list, description="The queries this call ran, after de-duplication"
    )
    collections_searched: list[str]
    results: list[SearchHit]
    error: str | None = None
    note: str | None = Field(
        default=None, description="Caveats about this result set, if any"
    )


class DocumentText(BaseModel):
    success: bool
    collectionname: str = ""
    #: The dataset the document is in. Without it the website renders the document as a
    #: non-clickable stub: a link needs the dataset as well as the hash, and a card that
    #: cannot be opened is the difference between a citation and a claim.
    collection_dataset: str = ""
    file_hash: str = ""
    path: str | None = None
    text: str = ""
    truncated: bool = False
    error: str | None = None


class DocumentsText(BaseModel):
    """A batch read. The per-document arm is `DocumentText`, unchanged and still used by
    `cite_documents`, so nothing that reads one document had to learn a new shape."""

    success: bool
    documents: list[DocumentText] = Field(default_factory=list)
    note: str | None = Field(
        default=None, description="What was de-duplicated, truncated or not read, and why"
    )
    error: str | None = None


class StructuredEntity(BaseModel):
    """One value a rule's validator accepted, with what the validator worked out.

    A different tier of evidence from the NER dictionary above it: a model's guess at a
    span of prose against a checksum that either passes or does not. Kept in a separate
    block rather than merged into `entities` because merging them would tell the model
    that a name and an IBAN are the same kind of fact.
    """

    #: Scanner entity type: `email`, `money`, `bank_account`, `date`, ...
    entity_type: str
    #: The normalised value, which is what a facet or another document joins on.
    value: str
    #: The rule that accepted it, e.g. `bank.iban`. Names the FollowTheMoney schema the
    #: value feeds, and is the key an explainer card is fetched with.
    rule_id: str = ""
    #: The text as the document wrote it, when that differs from `value`. A normalised
    #: phone number appears verbatim in almost no document.
    surface_text: str = ""
    #: Occurrences in the document.
    count: int = 0


class DocumentEntities(BaseModel):
    success: bool
    collectionname: str = ""
    file_hash: str = ""
    entities: dict[str, list[str]] = Field(
        default_factory=dict, description="Entity type -> distinct values"
    )
    structured: list[StructuredEntity] = Field(
        default_factory=list,
        description=(
            "Checksum-validated identifiers, normalised dates and money, from the rule "
            "scanner rather than from a language model. Empty when the scanner has not "
            "run over this document."
        ),
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


def _envelope_chars(hit: SearchHit) -> int:
    """What one hit costs with no snippet at all: its keys, ids, path and separator.

    Measured on the hit rather than estimated, because it is the part that varies —
    a deep path and a long dataset name cost several times what a short one does.
    """
    return len(hit.model_copy(update={"snippet": ""}).model_dump_json()) + 1


def _apply_payload_budget(response: SearchResponse) -> tuple[int, int]:
    """Trim snippets, then drop whole hits, until the serialised response fits the budget.

    Returns `(size_chars, dropped)`. Applied after ranking, never before: the fused order
    and the cross-encoder both score the full passage, and scoring a truncated one would
    change which documents come back, not only how much of them does.

    The order matters. Snippets are shortened first so a broad survey keeps its breadth,
    and only when the envelopes alone no longer fit does the tail get dropped — a hit
    that cannot carry `MIN_SNIPPET_CHARS` of text says nothing about why it matched, so
    it is worth less than the room it takes.
    """
    hits = response.results
    if not hits:
        return len(response.model_dump_json()), 0

    base = len(response.model_copy(update={"results": []}).model_dump_json())
    budget = max(PAYLOAD_BUDGET_CHARS - base, MIN_SNIPPET_CHARS)

    kept = 0
    spent = 0
    for hit in hits:
        envelope = _envelope_chars(hit)
        if kept and spent + envelope + MIN_SNIPPET_CHARS > budget:
            break
        spent += envelope
        kept += 1

    dropped = len(hits) - kept
    del hits[kept:]
    allowance = max(MIN_SNIPPET_CHARS, min(SNIPPET_CHARS, (budget - spent) // kept))
    for hit in hits:
        if len(hit.snippet) > allowance:
            hit.snippet = hit.snippet[:allowance].rstrip() + "…"

    # The estimate above counts characters; JSON escaping of newlines and quotes inside a
    # snippet costs more than one each, so the measured size can still overshoot. Measure
    # and shed the tail rather than trust the arithmetic.
    size = len(response.model_dump_json())
    while len(hits) > 1 and size > PAYLOAD_BUDGET_CHARS:
        hits.pop()
        dropped += 1
        size = len(response.model_dump_json())
    return size, dropped


@mcp.tool(
    name="search_collections",
    description=(
        "Full-text search across the user's document collections. Returns matching "
        "text passages with the document id needed to read the full document.\n\n"
        "**Pass several queries at once** in `queries` — different angles on the same "
        "question, phrased as sentences or several descriptive words rather than single "
        "keywords. They run together and the results are merged, and **every hit lists "
        "the queries that found it** in `matched_queries`: a passage three of your "
        "queries agree on is better corroborated than one only a single query returned. "
        "Two or three distinct angles in one call beats the same number of separate "
        "calls. Repeating a query you already sent does nothing and is reported back "
        "to you.\n\n"
        f"Leave max_results at the default of {DEFAULT_MAX_RESULTS}: it is already a "
        "broad look at the collections. One result set has a fixed size budget shared "
        "across all your queries, so asking for more returns a shorter passage from "
        "each and then drops the weakest hits, never more to read. Use read_documents "
        "to read hits in full."
    ),
)
def search_collections(
    queries: list[str] | str | None = None,
    collections: list[str] | str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    query: str | None = None,
) -> SearchResponse:
    """Search several queries at once, fanning out over every live shard.

    `query` is still accepted, so a transcript replayed from before the batch form — and
    a model that learned the single-query shape — keeps working. It is folded into
    `queries` rather than handled separately: one code path, and the batch of one is not
    a special case.

    `queries` and `collections` are typed to accept a string as well as a list because
    XML-style tool-call parsers send every list parameter as one. Declaring the union
    keeps the coercion out of pydantic's way rather than fighting it.
    """
    try:
        acl = _caller()
        targets = acl.check(_as_collection_list(collections))
    except AccessDenied as exc:
        return SearchResponse(
            success=False, query="", collections_searched=[], results=[], error=str(exc)
        )

    asked = batching.as_list(queries) + batching.as_list(query)
    wanted, repeats = batching.dedupe(asked)
    over_cap = wanted[MAX_QUERIES_PER_CALL:]
    wanted = wanted[:MAX_QUERIES_PER_CALL]

    if not wanted:
        return SearchResponse(
            success=False,
            query="",
            collections_searched=targets,
            results=[],
            error="queries cannot be empty; pass a list of one or more search phrases",
        )

    limit = max(1, min(int(max_results), MAX_ALLOWED_RESULTS))

    notes: list[str] = []
    corrective = batching.corrective_note(
        batching.repeats_note(repeats, "query"),
        (
            f"{len(over_cap)} quer{'y' if len(over_cap) == 1 else 'ies'} beyond the "
            f"{MAX_QUERIES_PER_CALL}-per-call limit "
            f"{'was' if len(over_cap) == 1 else 'were'} not run: {', '.join(over_cap)}. "
            "Send the most distinct angles first."
            if over_cap
            else ""
        ),
    )
    if corrective:
        notes.append(corrective)

    per_query: dict[str, list[SearchHit]] = {}
    errors: list[str] = []
    for one in wanted:
        hits, query_notes, error = _search_one(one, targets, limit, notes)
        per_query[one] = hits
        if error:
            errors.append(error)
        notes.extend(query_notes)

    hits = _fuse_across_queries(per_query, limit)
    _attach_paths(hits)

    # Every query failing the same way is a query problem, not an infrastructure one.
    error = errors[0] if errors and not hits else None

    response = SearchResponse(
        success=not error,
        query="; ".join(wanted),
        queries=wanted,
        collections_searched=targets,
        results=hits,
        error=error,
        note="; ".join(dict.fromkeys(notes)) or None,
    )
    found = len(hits)
    size, dropped = _apply_payload_budget(response)
    if dropped:
        # The model has to know the set was cut, or it reads "12 results" as "there are
        # twelve". The note is inside the budget: it is added before the final measure.
        response.note = "; ".join(
            filter(None, [response.note,
                          f"{dropped} lower-ranked result(s) omitted to fit the "
                          f"{PAYLOAD_BUDGET_CHARS}-character tool payload budget"])
        )
        size, extra = _apply_payload_budget(response)
        dropped += extra
    # The one number that says how heavy this tool call was. `chat_messages.tool_output`
    # cannot answer it — that column is truncated and the model's copy is not — so the
    # size the model actually received is only observable if it is recorded here.
    log.info(
        "search_collections payload: %d chars, %d quer(ies), %d of %d hit(s), %d dropped",
        size, len(wanted), len(response.results), found, dropped,
    )
    return response


#: More angles than this in one call is a model listing synonyms rather than choosing.
#: The surplus is refused by name — silently running the first few would hide the cost.
#:
#: Eight rather than five because a capable model asks for six unprompted on an ordinary
#: question, and a limit reached in ordinary use is measuring the limit rather than the
#: behaviour it was meant to catch. Each angle costs a full hybrid fan-out and a rerank —
#: about a third of a second each — so eight is still well short of where the search
#: dominates the turn.
MAX_QUERIES_PER_CALL = int(os.getenv("SEARCH_MAX_QUERIES", "8"))


def _fuse_across_queries(
    per_query: dict[str, list[SearchHit]], limit: int
) -> list[SearchHit]:
    """Merge each query's ranking into one, recording which queries found each hit.

    Reciprocal rank over the per-query positions, which is the same rule the keyword and
    vector rankings are already fused by one level down — a hit several queries rank
    highly beats one query's top hit, and no query's scores have to be comparable with
    another's for that to hold. BM25 across two different queries is not comparable at
    all, so summing scores here would be arithmetic on unrelated units.

    `matched_queries` is the point of the whole batch form: corroboration is only usable
    by the model if it can see it **on the hit**.
    """
    merged: dict[tuple, SearchHit] = {}
    fused_score: dict[tuple, float] = {}
    matched: dict[tuple, list[str]] = {}

    for one, hits in per_query.items():
        for position, hit in enumerate(hits):
            key = (hit.collectionname, hit.file_hash, hit.page_id)
            fused_score[key] = fused_score.get(key, 0.0) + 1.0 / (RRF_K + position + 1)
            # Distinct queries only. One query's ranking can carry the same page more
            # than once — the shards are searched independently and a page can win a slot
            # in several — and listing "due date" four times says a page is corroborated
            # when only one query found it, which inverts the meaning of the field.
            seen = matched.setdefault(key, [])
            if one not in seen:
                seen.append(one)
            kept = merged.get(key)
            if kept is None:
                merged[key] = hit
            elif len(hit.snippet) > len(kept.snippet):
                # Keep the longest snippet: different queries match different passages of
                # the same page, and the fuller one is the more useful evidence.
                merged[key] = hit

    ordered = sorted(merged.items(), key=lambda kv: -fused_score[kv[0]])
    out: list[SearchHit] = []
    for key, hit in ordered[:limit]:
        hit.matched_queries = matched[key]
        hit.score = round(fused_score[key], 6) if len(per_query) > 1 else hit.score
        out.append(hit)
    return out


#: RRF's rank offset for the cross-query fusion, matching the convention used one level
#: down for keyword-vs-vector. It damps the top rank's dominance so a hit that is second
#: for three queries outranks one that is first for exactly one.
RRF_K = 60


def _search_one(
    query: str, targets: list[str], limit: int, shared_notes: list[str]
) -> tuple[list[SearchHit], list[str], str | None]:
    """One query's hybrid search. `(hits, notes, error)`; never raises."""
    notes: list[str] = []
    prepared = prepare_match_query(query)
    if not prepared.expr:
        # Hand back the syntax reference along with the complaint: the model gets one
        # shot at understanding what went wrong, and "unbalanced quote" is only
        # actionable next to the rules it broke.
        return (
            [],
            notes,
            f"{prepared.error or 'query contained no searchable terms'}\n\n{MATCH_SYNTAX}",
        )
    match_expr = prepared.expr

    notes.extend(prepared.repairs)

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

    for hit in hits:
        hit.matched_queries = [query]
    return hits, notes, error


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
    name="read_documents",
    description=(
        "Read the extracted text of several documents at once. Each entry names its "
        "collection and the file_hash a search returned — pass them as "
        "`[{\"collectionname\": \"...\", \"file_hash\": \"...\"}, ...]`, or as two "
        "parallel lists in `collectionname` and `file_hash`. Read every promising hit "
        "in one call rather than one per turn. The character budget is shared across "
        "the batch, so a document that had to be cut says so, and documents that did "
        "not fit are named rather than dropped silently."
    ),
)
def read_documents(
    documents: list[dict] | str | None = None,
    collectionname: list[str] | str | None = None,
    file_hash: list[str] | str | None = None,
) -> DocumentsText:
    """Read a batch of documents, sharing one character budget across them.

    The three parameter shapes are all shapes models actually produce: a list of objects
    (what the description asks for), two parallel lists, and — through
    `batching.as_list` — a single pair of bare strings, which is the single-document call
    this replaced. That last one is why no separate compatibility path is needed.
    """
    pairs, malformed = _document_pairs(documents, collectionname, file_hash)
    wanted, repeats = batching.dedupe([f"{c}\x00{h}" for c, h in pairs], casefold=False)
    pairs = [tuple(k.split("\x00", 1)) for k in wanted]

    note = batching.corrective_note(
        batching.repeats_note([r.replace("\x00", "/") for r in repeats], "document"),
        (
            f"{len(malformed)} entr{'y' if len(malformed) == 1 else 'ies'} could not be "
            f"read as a collection and file hash: {', '.join(malformed)}. Each needs "
            "both, exactly as search_collections returned them."
            if malformed
            else ""
        ),
    )

    if not pairs:
        return DocumentsText(
            success=False,
            documents=[],
            note=note or None,
            error="no document was named; pass the collectionname and file_hash of each",
        )

    per_doc, fits = batching.divide_budget(READ_DOCUMENTS_TOTAL_CHARS, len(pairs))
    dropped = [f"{c}/{h}" for c, h in pairs[fits:]]
    pairs = pairs[:fits]
    if dropped:
        note = batching.corrective_note(note, batching.dropped_note(dropped, "document"))

    out: list[DocumentText] = []
    for collection, digest in pairs:
        one = _read_document_text(collection, digest)
        if one.text and len(one.text) > per_doc:
            one.text, cut = batching.truncate(one.text, per_doc)
            one.truncated = one.truncated or cut
        out.append(one)

    return DocumentsText(
        success=any(d.success for d in out),
        documents=out,
        note=note or None,
    )


#: The whole call's text budget, shared across the documents asked for. Sized to match
#: the search tool's payload budget: a batch read of six hits should not cost more than
#: the search that produced them.
READ_DOCUMENTS_TOTAL_CHARS = int(os.getenv("READ_DOCUMENTS_TOTAL_CHARS", "40000"))


def _document_pairs(
    documents: object, collectionname: object, file_hash: object
) -> tuple[list[tuple[str, str]], list[str]]:
    """`(pairs, malformed)` from any of the three shapes. Never raises."""
    pairs: list[tuple[str, str]] = []
    malformed: list[str] = []

    entries: list = []
    if isinstance(documents, str):
        text = documents.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                entries = parsed
    elif isinstance(documents, list):
        entries = documents

    for entry in entries:
        if isinstance(entry, dict):
            collection = str(entry.get("collectionname") or "").strip()
            digest = str(entry.get("file_hash") or "").strip()
            if collection and _is_hash(digest):
                pairs.append((collection, digest))
                continue
        malformed.append(str(entry)[:80])

    # Two parallel lists, and the bare-string pair that was the single-document call.
    collections = batching.as_list(collectionname)
    hashes = batching.as_list(file_hash)
    if collections and hashes:
        if len(collections) == 1 and len(hashes) > 1:
            collections = collections * len(hashes)
        for collection, digest in zip(collections, hashes):
            if collection and _is_hash(digest):
                pairs.append((collection, digest))
            else:
                malformed.append(f"{collection}/{digest}"[:80])
    return pairs, malformed


def _read_document_text(collectionname: str, file_hash: str) -> DocumentText:
    """The tool's body, callable from other tools.

    Separate from the decorated function because reaching into a tool object to find the
    callable it wraps is a dependency on the MCP library's internals, and the quote check
    in `cite_documents` needs exactly this and nothing else.
    """
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
            "SELECT any(path) AS path, any(collection_dataset) AS collection_dataset "
            "FROM vfs_files WHERE hash = {hash:String} AND is_deleted = 0",
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
        collection_dataset=(path_rows[0].get("collection_dataset") if path_rows else "") or "",
        file_hash=file_hash,
        path=(path_rows[0].get("path") if path_rows else None) or None,
        text=text[:MAX_DOCUMENT_CHARS],
        truncated=truncated,
    )


@mcp.tool(
    name="list_document_entities",
    description=(
        "List what the pipeline extracted from one document, in two tiers. `entities` is "
        "a language model's reading of the prose: people, organisations, locations. "
        "`structured` is what a rule's validator accepted: checksum-validated "
        "identifiers, normalised dates, money with an ISO 4217 code. Treat the two "
        "differently — a name is a judgement, an IBAN either has a valid check digit or "
        "it does not. Useful for finding names and identifiers to search for next."
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
        structured=_structured_entities(collectionname, file_hash),
    )


#: How many rule-found values one document contributes to a tool response.
#:
#: Ordered by occurrence count, so the cap keeps what the document is about. A mail
#: archive routinely names hundreds of addresses and the tail of that list is not what
#: anyone asked.
STRUCTURED_ENTITY_LIMIT = 200


def _structured_entities(collectionname: str, file_hash: str) -> list[StructuredEntity]:
    """The rule scanner's values for one document, newest rule set only.

    **The same question the website's document viewer asks, and the same shape of answer**
    — `get_document_entities` in the website backend runs this query against the same
    table. Two different answers to "what identifiers are in this file" would put the
    model and the reader in different conversations about the same document.

    Three things the query has to get right:

    * only the newest rule set, because the table keeps every rule set's results side by
      side so a version bump can be rescanned without destroying what came before;
    * counts summed across segments and MAXed across text variants, because a document
      parsed twice carries the same occurrences under both;
    * the five value arrays joined together in one `ARRAY JOIN`, because they are
      parallel and joining them separately produces the cross product.

    A scanner that has never run leaves no rows, and that returns an empty list rather
    than an error: the block is absent, and nothing raises.
    """
    try:
        rows = clickhouse_query(
            """
            SELECT entity_type, value, any(rule_id) AS rule_id,
                   any(surface_text) AS surface_text, max(variant_count) AS count
            FROM (
                SELECT entity_type, entity_value AS value, extracted_by,
                       any(rule_id) AS rule_id, any(surface_text) AS surface_text,
                       sum(occurrences) AS variant_count
                FROM (
                    SELECT entity_type, extracted_by, entity_values, entity_rule_ids,
                           entity_counts, entity_texts
                    FROM regex_entity_hit FINAL
                    WHERE file_hash = {hash:String}
                      AND rule_set_version = (
                          SELECT max(rule_set_version) FROM regex_entity_hit
                          WHERE file_hash = {hash:String}
                      )
                )
                ARRAY JOIN
                    entity_values AS entity_value,
                    entity_rule_ids AS rule_id,
                    entity_counts AS occurrences,
                    entity_texts AS surface_text
                GROUP BY entity_type, value, extracted_by
            )
            GROUP BY entity_type, value
            ORDER BY count DESC
            LIMIT {limit:UInt32}
            """,
            database=collection_db(collectionname),
            params={"hash": file_hash, "limit": STRUCTURED_ENTITY_LIMIT},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("structured entities unavailable for %s: %s", file_hash, exc)
        return []

    return [
        StructuredEntity(
            entity_type=row["entity_type"],
            value=row["value"],
            rule_id=row["rule_id"],
            # Carried only when it differs. Storing the same string twice invites a
            # renderer to show it twice and a model to treat them as two values.
            surface_text="" if row["surface_text"] == row["value"] else row["surface_text"],
            count=int(row["count"]),
        )
        for row in rows
    ]


class Citation(BaseModel):
    """One document the agent is putting forward as evidence for one point."""

    collectionname: str
    file_hash: str
    #: A span copied from the document, checked against its text before a handle is
    #: issued. Not a paraphrase: the check is what makes the difference between a
    #: citation and a claim.
    quote: str = ""
    #: What this document supports, in the agent's own words. Shown on the card.
    why: str = ""


class CitationResult(BaseModel):
    handle: str = ""
    collectionname: str = ""
    collection_dataset: str = ""
    file_hash: str = ""
    path: str | None = None
    quote: str = ""
    why: str = ""
    #: The quoted span was found in the document's extracted text. False is not a
    #: refusal — the citation still stands and the reader sees it marked.
    quote_verified: bool = False
    error: str | None = None


class CitationsResponse(BaseModel):
    success: bool
    citations: list[CitationResult] = Field(default_factory=list)
    #: What was asked for versus what was sensible, in words the model can act on.
    note: str = ""
    error: str | None = None


#: Handles live for the life of a chat session, keyed by the session header the website
#: forwards. It carries no authority — the ACL is a different header — and is an
#: isolation key only.
_HANDLES = HandleTable()

#: Citations one call may carry. A model that wants to cite more than this in one turn is
#: listing its search results rather than choosing evidence.
MAX_CITATIONS_PER_CALL = 12


def _session_id() -> str:
    """The chat session this call belongs to, or a per-process fallback.

    An absent header means the caller is not the chat surface — a script, a probe — and
    those share one table rather than each minting a session, because the alternative is
    an unbounded map keyed by nothing.
    """
    headers = {k.lower(): v for k, v in get_http_headers().items()}
    return headers.get("x-hoover4-chat-session") or "_no_session"


@mcp.tool(
    name="cite_documents",
    description=(
        "Put documents forward as the evidence for your answer. Each citation names a "
        "document, a quote copied verbatim from it, and why it matters. You get back a "
        "handle like [D1] for each; write those handles into your prose where the claim "
        "is made, and the reader sees the document beside it. The quote is checked "
        "against the document's text — one that does not check out comes back marked, so "
        "re-read rather than paraphrase. Cite what you relied on, not everything a "
        "search returned."
    ),
)
def cite_documents(citations: list[Citation] | str) -> CitationsResponse:
    """Verify each quote, allocate a session handle, and return the cards to render."""
    try:
        acl = _caller()
    except AccessDenied as exc:
        return CitationsResponse(success=False, error=str(exc))

    parsed = _as_citation_list(citations)
    if parsed is None:
        return CitationsResponse(
            success=False,
            error="citations must be a list of {collectionname, file_hash, quote, why}",
        )
    if not parsed:
        return CitationsResponse(success=False, error="no citations were given")

    note_parts: list[str] = []
    if len(parsed) > MAX_CITATIONS_PER_CALL:
        note_parts.append(
            f"{len(parsed)} citations were given and the first {MAX_CITATIONS_PER_CALL} "
            "were kept. Cite the documents you actually relied on rather than every hit."
        )
        parsed = parsed[:MAX_CITATIONS_PER_CALL]

    session = _session_id()
    results: list[CitationResult] = []
    unverified = 0
    for citation in parsed:
        result = _cite_one(acl, session, citation)
        if result.error is None and not result.quote_verified:
            unverified += 1
        results.append(result)

    if unverified:
        note_parts.append(
            f"{unverified} of {len(results)} quotes were not found in the document they "
            "were attributed to. Those citations are shown to the reader marked as "
            "unverified. Re-read the document and quote it exactly rather than from "
            "memory."
        )
    if any(r.error is None and not r.handle for r in results):
        note_parts.append(
            "This conversation has used every citation handle it can allocate; the "
            "documents above are cited without one."
        )

    return CitationsResponse(
        success=True, citations=results, note=" ".join(note_parts)
    )


def _as_citation_list(value: Any) -> list[Citation] | None:
    """Coerce whatever the model sent into a list of citations.

    The same problem `_as_collection_list` solves, one level deeper: an XML-style
    tool-call parser hands a list argument across as a JSON string, so a `list[Citation]`
    arrives as `'[{"collectionname": ...}]'`. Rejecting it teaches the model nothing at
    the moment it made the mistake, and it retries the identical call.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        # A single citation sent unwrapped is an obvious intention, not an error.
        value = [value]
    if not isinstance(value, list):
        return None
    out: list[Citation] = []
    for item in value:
        if isinstance(item, Citation):
            out.append(item)
            continue
        if not isinstance(item, dict):
            return None
        try:
            out.append(Citation(**item))
        except Exception:  # noqa: BLE001 - a malformed entry is a caller error
            return None
    return out


def _cite_one(acl: CallerAcl, session: str, citation: Citation) -> CitationResult:
    result = CitationResult(
        collectionname=citation.collectionname,
        file_hash=citation.file_hash,
        quote=citation.quote,
        why=citation.why,
    )
    try:
        acl.check([citation.collectionname])
    except AccessDenied as exc:
        result.error = str(exc)
        return result
    if not _is_hash(citation.file_hash):
        result.error = "file_hash must be a content hash from search_collections"
        return result

    document = _read_document_text(citation.collectionname, citation.file_hash)
    if not document.success:
        result.error = document.error or "the document could not be read"
        return result

    result.collection_dataset = document.collection_dataset
    result.path = document.path
    # A quote too short to check is reported as unverified rather than as verified: "the"
    # occurs in every document, and a check that always passes proves nothing.
    result.quote_verified = quote_occurs_in(citation.quote, document.text)
    if not result.quote_verified and len(citation.quote.strip()) < MIN_QUOTE_CHARS:
        result.why = result.why or ""
    result.handle = _HANDLES.handle_for(
        session, citation.collectionname, citation.file_hash
    )
    return result


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
