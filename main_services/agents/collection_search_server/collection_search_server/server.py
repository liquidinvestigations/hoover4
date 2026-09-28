"""FastMCP server exposing Hoover4 collection search to agents, bounded by an ACL.

Tools:
    ``list_collections``      what the calling user may read
    ``search_passages``       hybrid keyword and vector passage search, paged by the broker
    ``read_documents``        the extracted text of several documents
    ``list_document_entities`` named entities found in documents, paged by the broker
    ``cite_documents``        verified citations with session handles

Every tool resolves the caller's ACL from request headers (see :mod:`.acl`) before it
touches a database, and every collection name reaching SQL has been validated against
the shared collectionname rule.

The legacy search path is **hybrid** when the embeddings stack is probed (`server_settings.
embeddings_serving_model` + `EMBEDDINGS_URL`): a keyword ranking from the `_pages`
shards and a vector ranking from the `_vectors` shards are RRF-fused
(`agent_common.fusion`, the same module metasearch uses), reranked through the same
cross-encoder client, and put through the per-kind floor so keyword-exact hits cannot
drown semantic ones. With no probe or a dead GPU the tool degrades to the
keyword-only path and says so in `note`. A GPU outage must degrade search quality,
not remove search.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Sequence

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field, model_serializer

from agent_common import batching, retired
from agent_common import embeddings as embeddings_client
from agent_common import fusion, rerank as rerank_client
from collection_search_server import vectors
from collection_search_server.acl import AccessDenied, CallerAcl, parse_acl
from collection_search_server.citations import (
    HandleTable,
    MIN_QUOTE_CHARS,
    citation_find_query,
    find_in_quote,
    QUOTE_MATCH_VERIFIED,
    QUOTE_REASON_ABSENT,
    QUOTE_REASON_LOOKUP_FAILED,
    QUOTE_REASON_SHORT,
    quote_match_in_pages,
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

#: The default and the cap of `max_results` of `search_passages`, for each query form.
#: A model that asks for 10 000 gets the cap. The size of the result is bounded by the
#: page share of the broker, which stores the rows past it for `read_more`.
DEFAULT_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "15"))
MAX_ALLOWED_RESULTS = int(os.getenv("SEARCH_MAX_ALLOWED_RESULTS", "15"))

#: The characters of a snippet that the model reads, cut round the first match by
#: `centred_snippet`. It sets that length and nothing else.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "350"))

#: The characters of candidate text that `_search_one` keeps and the reranker scores.
#: It has no environment key, so a change of the snippet length does not change the rank.
RERANK_TEXT_CHARS = 1200


def centred_snippet(text: str, n: int = SNIPPET_CHARS, words: Sequence[str] = ()) -> str:
    """At most n characters of text round its first match, with "…" at each cut end.
    The first match is the first "**". With no marker, it is the first case-insensitive
    occurrence of a word of `words` of three or more characters. With neither, a prefix."""
    if len(text) <= n:
        return text
    i = text.find("**")
    if i < 0:
        low = text.lower()
        hits = [low.find(w.lower()) for w in words if len(w) >= 3]
        hits = [h for h in hits if h >= 0]
        i = min(hits) if hits else -1
    if i < 0:
        return text[:n].rstrip() + "…"
    start = max(0, min(i - n // 2, len(text) - n))
    return ("…" if start else "") + text[start:start + n].strip() + "…"


def query_words(forms: Sequence[str]) -> list[str]:
    """The words of the query forms, for `centred_snippet`: split on white space, with
    quotes, `|` and a leading `-` removed."""
    words: list[str] = []
    for form in forms:
        for word in form.split():
            word = word.replace('"', "").replace("|", "").lstrip("-")
            if word:
                words.append(word)
    return words

#: How much text one document may contribute to a `read_documents` call.
#: Citation verification does not use this limit. It reads every extracted page.
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "40000"))

#: Extracted pages one verification query fetches. The matcher then folds a window
#: as long as the quote, so a match that crosses this batch still verifies.
VERIFY_PAGE_BATCH = 32

#: Candidate pool per shard (keyword) and per `_vectors` shard (KNN) when the fused
#: pipeline runs, and the cap on the fused pool sent to the reranker.
FUSION_CANDIDATES = int(os.getenv("COLLECTION_SEARCH_FUSION_CANDIDATES", "60"))

#: The per-kind floor after reranking: each of the `keyword` and `vector` kinds keeps
#: its best results even when the other kind dominates the fused order (RRF is a
#: popularity measure; keyword-exact hits would otherwise drown semantic ones).
#:
#: **The floor must stay well under `max_results`.** A reserved slot outranks the cap by
#: design (`per_kind_floor` never evicts one), so a floor of 10 over two kinds reserved 20
#: results and the caller's `max_results=8` did nothing at all: `search_collections` was
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
    # MATCH syntax has to be in here and not only in the agent's system prompt, the
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
            "The queries that returned this passage. Several matching queries can "
            "increase its search rank, but they are one source."
        ),
    )


class _Candidate:
    """One search candidate before fusion: a keyword hit, a vector hit, or both.

    Fused at page granularity. A vector hit knows its chunk, but the answer a hit
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
    """A batch read. The per-document arm is `DocumentText`. Citation verification
    reads extracted pages on its own path so the model excerpt limit does not apply."""

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
    truncated: bool = Field(
        default=False,
        description="The shared budget could not carry every value this document has",
    )
    error: str | None = None


class DocumentsEntities(BaseModel):
    """A batch entity listing. The per-document arm is `DocumentEntities`, unchanged, so
    nothing that reads one document's entities had to learn a new shape."""

    success: bool
    documents: list[DocumentEntities] = Field(default_factory=list)
    note: str | None = Field(
        default=None, description="What was de-duplicated, cut or not read, and why"
    )
    error: str | None = None


#: A content hash as the pipeline writes them: hex, 32-128 chars (md5 through sha3-512).
_HASH_RE = re.compile(r"^[0-9a-f]{32,128}$")


def _is_hash(value: str) -> bool:
    return bool(_HASH_RE.match(value or ""))


#: The shortest start of a file hash that `read_documents` and `cite_documents` accept in
#: place of the whole hash. A model copies a 64-character hash one token at a time and can
#: change a character, so a shorter start that names one document is enough.
MIN_HASH_PREFIX = 12

#: The start of a file hash: hex, from `MIN_HASH_PREFIX` to 63 characters.
_HASH_PREFIX_RE = re.compile(r"^[0-9a-f]{%d,63}$" % MIN_HASH_PREFIX)

def _is_hash_or_start(value: str) -> bool:
    """A whole content hash, or the start of one that `full_hash` can resolve."""
    return _is_hash(value) or bool(_HASH_PREFIX_RE.match(value or ""))


#: A hex value longer than a file hash: a hash that the model copied with extra characters.
_TOO_LONG_HASH_RE = re.compile(r"^[0-9a-f]{65,}$")

#: The count of candidates that the refusal of an ambiguous start names.
MAX_PREFIX_CANDIDATES = 5


class HashPrefixError(ValueError):
    """A file hash start that names more than one document."""


def full_hash(collectionname: str, value: str) -> str:
    """The whole file hash of the one document in `collectionname` whose hash starts with
    `value`. A value that is not a hash start, and a start that names no document, come
    back unchanged, so the caller's own check refuses them. A start that names more than
    one document, and a hex value longer than 64 characters, raise `HashPrefixError`. The
    caller checks the ACL of `collectionname` first."""
    prefix = (value or "").strip().lower()
    if _TOO_LONG_HASH_RE.match(prefix):
        raise HashPrefixError(
            f"the file_hash {value!r} has {len(prefix)} characters, and a file hash has 64. "
            "Copy the whole file_hash of the document you mean from a tool result."
        )
    if not _HASH_PREFIX_RE.match(prefix):
        return value
    rows = clickhouse_query(
        "SELECT DISTINCT hash FROM vfs_files WHERE startsWith(hash, {prefix:String}) "
        "AND is_deleted = 0 ORDER BY hash LIMIT {limit:UInt32}",
        database=collection_db(collectionname),
        params={"prefix": prefix, "limit": MAX_PREFIX_CANDIDATES + 1},
    )
    hashes = [str(row.get("hash") or "") for row in rows if row.get("hash")]
    if len(hashes) == 1:
        return hashes[0]
    if not hashes:
        return value
    listed = ", ".join(hashes[:MAX_PREFIX_CANDIDATES])
    more = " and more" if len(hashes) > MAX_PREFIX_CANDIDATES else ""
    raise HashPrefixError(
        f"the file_hash {value!r} is the start of more than one document in "
        f"{collectionname!r}: {listed}{more}. Copy the whole file_hash of the document "
        "you mean from a tool result."
    )


def full_hashes(collectionname: str, values: Any) -> Any:
    """`full_hash` for each value of a list or for one string, for a collection that the
    caller can read. For any other collection the values come back unchanged, and the
    route refuses the call."""
    try:
        _caller().check([collectionname])
    except AccessDenied:
        return values
    if isinstance(values, str):
        return full_hash(collectionname, values)
    if isinstance(values, list):
        return [full_hash(collectionname, v) if isinstance(v, str) else v for v in values]
    return values


#: The start length that finds the document a model meant when it changed a later
#: character of a whole hash. 16 hex characters name one document in any real collection.
NEAR_MATCH_PREFIX = 16

#: A whole file hash, or a hex value longer than one.
_WHOLE_OR_LONGER_RE = re.compile(r"^[0-9a-f]{64,}$")


def _existing_hashes(collectionname: str, hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    rows = clickhouse_query(
        "SELECT DISTINCT hash FROM vfs_files WHERE hash IN {hashes:Array(String)} "
        "AND is_deleted = 0",
        database=collection_db(collectionname),
        params={"hashes": "['" + "','".join(hashes) + "']"},
    )
    return {str(row.get("hash") or "") for row in rows}


def _near_match(collectionname: str, value: str) -> str | None:
    """The one document whose hash starts with the first `NEAR_MATCH_PREFIX` characters of
    `value`, or `None` when no document or more than one has that start."""
    rows = clickhouse_query(
        "SELECT DISTINCT hash FROM vfs_files WHERE startsWith(hash, {prefix:String}) "
        "AND is_deleted = 0 ORDER BY hash LIMIT 2",
        database=collection_db(collectionname),
        params={"prefix": value[:NEAR_MATCH_PREFIX]},
    )
    hashes = [str(row.get("hash") or "") for row in rows if row.get("hash")]
    return hashes[0] if len(hashes) == 1 else None


#: A value made of hex characters only.
_HEX_RE = re.compile(r"^[0-9a-f]+$")


def _hash_of_name(collectionname: str, name: str) -> str | None:
    """The hash of the one document whose path is `name` or ends with `/name`, or `None`
    when no document or more than one has that name."""
    rows = clickhouse_query(
        "SELECT DISTINCT hash FROM vfs_files WHERE (path = {name:String} OR "
        "endsWith(path, {tail:String})) AND is_deleted = 0 AND hash != '' LIMIT 2",
        database=collection_db(collectionname),
        params={"name": name, "tail": "/" + name.lstrip("/")},
    )
    hashes = [str(row.get("hash") or "") for row in rows if row.get("hash")]
    return hashes[0] if len(hashes) == 1 else None


def resolve_hashes(collectionname: str, values: Any) -> tuple[Any, list[str]]:
    """The hashes of `values` that `read_documents` sends, and a note for each change.

    A hash start becomes its whole hash (`full_hash`). A hex value that no document has,
    as a whole hash or as a start, becomes the one document whose hash has the same first
    `NEAR_MATCH_PREFIX` characters, because the served model changes, adds or drops a
    character in the middle of a hash it copies. A file name becomes the one document with
    that name. A value that matches no document is left out, so the other documents of the
    call are still read. For a collection that the caller cannot read the
    values come back unchanged, and the route refuses the call."""
    try:
        _caller().check([collectionname])
    except AccessDenied:
        return values, []
    items = [values] if isinstance(values, str) else values
    if not isinstance(items, list):
        return values, []
    whole = sorted({v.strip().lower() for v in items
                    if isinstance(v, str) and _WHOLE_OR_LONGER_RE.match(v.strip().lower())})
    existing = _existing_hashes(collectionname, [h for h in whole if len(h) == 64])
    out: list[Any] = []
    notes: list[str] = []
    for value in items:
        text = value.strip().lower() if isinstance(value, str) else ""
        if text in existing:
            out.append(text)
            continue
        if isinstance(value, str) and value.strip() and not _HEX_RE.match(text):
            named = _hash_of_name(collectionname, value.strip())
            if named is not None:
                out.append(named)
                notes.append(f"{value!r} is a file name, not a file_hash. The one document with "
                             f"that name is read: {named}.")
            else:
                notes.append(f"{value!r} is not a file_hash, and no single document in "
                             f"{collectionname!r} has that file name, so this call leaves it "
                             "out. Copy the whole file_hash from a tool result.")
            continue
        if not _WHOLE_OR_LONGER_RE.match(text):
            found = full_hash(collectionname, value) if isinstance(value, str) else value
            if found != value or not _HASH_PREFIX_RE.match(text):
                out.append(found)
                continue
            # A hash start that no document has: a hash with a character dropped.
        near = _near_match(collectionname, text) if len(text) >= NEAR_MATCH_PREFIX else None
        if near is not None:
            out.append(near)
            notes.append(f"no document in {collectionname!r} has the file_hash {value!r}. The one "
                         f"document whose file_hash starts with {text[:NEAR_MATCH_PREFIX]!r} is "
                         f"read in its place: {near}.")
        else:
            notes.append(f"no document in {collectionname!r} has the file_hash {value!r}, so this "
                         "call leaves it out. Copy the whole file_hash from a tool result.")
    return out, notes


def _caller() -> CallerAcl:
    """The ACL of the in-flight request."""
    return parse_acl(dict(get_http_headers()))


def _as_collection_list(value: Any) -> list[str] | None:
    """Coerce whatever the model sent for `collections` into a list of names.

    XML-style tool-call parsers (`qwen3_xml`, which Qwen3.5 requires) hand every
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
        # listing. The agent still needs to know the others exist.
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


def search_passages(
    queries: list[str] | str | None = None,
    collections: list[str] | str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    query: str | None = None,
) -> SearchResponse:
    """Search several queries at once, fanning out over every live shard.

    `query` is still accepted, so a transcript replayed from before the batch form (and
    a model that learned the single-query shape) keeps working. It is folded into
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

    limit = max(1, min(int(max_results), MAX_ALLOWED_RESULTS, ROWS_PER_FORM))

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

    hits = _fuse_across_queries(per_query, ROWS_PER_FORM * len(wanted))
    _attach_paths(hits)
    for hit in hits:
        hit.snippet = centred_snippet(hit.snippet, SNIPPET_CHARS, query_words(hit.matched_queries))

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
    log.info("search_passages: %d quer(ies), %d hit(s)", len(wanted), len(hits))
    return response


#: More query forms than this in one call is a model listing synonyms rather than
#: choosing. The tool schema refuses the surplus, so the model reads the limit.
MAX_QUERIES_PER_CALL = int(os.getenv("SEARCH_MAX_QUERIES", "12"))

#: The rows that each query form of a search keeps: the first rows of a
#: `search_collections` form, and the `max_results` cap of a `search_passages` form.
ROWS_PER_FORM = int(os.getenv("SEARCH_ROWS_PER_FORM", "15"))


def _fuse_across_queries(
    per_query: dict[str, list[SearchHit]], limit: int
) -> list[SearchHit]:
    """Merge each query's ranking into one, recording which queries found each hit.

    Reciprocal rank over the per-query positions, which is the same rule the keyword and
    vector rankings are already fused by one level down. A hit several queries rank
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
            # than once (the shards are searched independently and a page can win a slot
            # in several), and listing "due date" four times says a page is corroborated
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
    #: only logged. A syntax error the model never sees is one it cannot correct.
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
                        text=(row.get("page_text") or "")[:RERANK_TEXT_CHARS],
                    )
                )

    # BM25 statistics are per-table, so scores from different shards are only roughly
    # comparable. The same caveat the website's search fan-out carries.
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
    # verbatim: `no field 'title' found in schema` tells it exactly what to change.
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
    the best per kind. Flooring first would let the reranker reorder an
    already-truncated set. A rerank failure keeps the fused order and says so in the
    notes; a GPU outage must degrade search quality, not remove search.
    """
    by_key: dict[tuple, _Candidate] = {}
    for c in keyword_list:
        by_key.setdefault(c.key(), c)
    vector_candidates: list[_Candidate] = []
    #: Pages whose snippet already came from a chunk. `vector_list` is nearest-first, so
    #: the first chunk seen for a page is its best one, and assigning unconditionally
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
            c.text = v.text[:RERANK_TEXT_CHARS]
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
    log.info(
        "%d keyword + %d vector candidates, %d after fusion%s",
        len(keyword_list), len(vector_list), len(fused),
        f", cross-encoder reranked in {rerank_ms:.0f} ms" if rerank_applied else "",
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
        # interpolated. These come back from Manticore, so they should always be hex.
        # This is the belt to that braces.
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


def read_documents(
    documents: list[dict] | str | None = None,
    collectionname: list[str] | str | None = None,
    file_hash: list[str] | str | None = None,
) -> DocumentsText:
    """Read a batch of documents, sharing one character budget across them.

    The three parameter shapes are all shapes models actually produce: a list of objects
    (what the description asks for), two parallel lists, and (through
    `batching.as_list`) a single pair of bare strings, which is the single-document call
    this replaced. That last one is why no separate compatibility path is needed.
    """
    pairs, malformed = _document_pairs(documents, collectionname, file_hash)
    try:
        pairs = [(c, full_hashes(c, h)) for c, h in pairs]
    except HashPrefixError as exc:
        return DocumentsEntities(success=False, error=str(exc))
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
            if collection and _is_hash_or_start(digest):
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
            if collection and _is_hash_or_start(digest):
                pairs.append((collection, digest))
            else:
                malformed.append(f"{collection}/{digest}"[:80])
    return pairs, malformed


def _read_document_text(collectionname: str, file_hash: str) -> DocumentText:
    """The tool's body, callable from other tools.

    Separate from the decorated function because reaching into a tool object to find the
    callable it wraps is a dependency on the MCP library's internals. The returned text
    is truncated at `MAX_DOCUMENT_CHARS`. Citation verification reads pages separately
    and does not use this excerpt.
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


#: The tool description that `tools_document` registers `list_document_entities` with.
LIST_DOCUMENT_ENTITIES_DESCRIPTION = (
        "List what the pipeline extracted from several documents at once, in two tiers. "
        "Each entry names its collection and the file_hash a search returned. Pass them "
        "as `[{\"collectionname\": \"...\", \"file_hash\": \"...\"}, ...]`, or as two "
        "parallel lists in `collectionname` and `file_hash`. `entities` is a language "
        "model's reading of the prose: people, organisations, locations. `structured` is "
        "what a rule's validator accepted: checksum-validated identifiers, normalised "
        "dates, money with an ISO 4217 code. Treat the two differently, because a name is a "
        "judgement, an IBAN either has a valid check digit or it does not. Ask about "
        "every promising document in one call: this is how you find the names and "
        "identifiers to search for next."
    )


def list_document_entities(
    documents: list[dict] | str | None = None,
    collectionname: list[str] | str | None = None,
    file_hash: list[str] | str | None = None,
) -> DocumentsEntities:
    """List entities for a batch of documents, sharing one value budget across them.

    Same three parameter shapes as `read_documents`, through the same `_document_pairs`:
    a list of objects, two parallel lists, and a bare pair of strings, which is exactly
    the single-document call this replaced, so there is no compatibility branch.
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
        return DocumentsEntities(
            success=False,
            note=note or None,
            error="no document was named; pass the collectionname and file_hash of each",
        )

    per_doc, fits = batching.divide_budget(LIST_ENTITIES_TOTAL_CHARS, len(pairs))
    dropped = [f"{c}/{h}" for c, h in pairs[fits:]]
    pairs = pairs[:fits]
    if dropped:
        note = batching.corrective_note(note, batching.dropped_note(dropped, "document"))

    out = [_document_entities(collection, digest, per_doc) for collection, digest in pairs]
    truncated = [d.file_hash for d in out if d.truncated]
    if truncated:
        note = batching.corrective_note(
            note,
            f"{len(truncated)} document{'' if len(truncated) == 1 else 's'} had more "
            f"entities than the shared budget carries and {'was' if len(truncated) == 1 else 'were'} "
            f"cut to the most frequent: {', '.join(truncated)}. Ask about fewer at a time "
            "to see the whole list.",
        )

    return DocumentsEntities(
        success=any(d.success for d in out),
        documents=out,
        note=note or None,
    )


#: The whole call's entity budget, shared across the documents asked for. Measured in
#: characters, like every other budget here, so one divider serves them all and the
#: minimum-share floor below which documents are dropped means the same thing everywhere.
LIST_ENTITIES_TOTAL_CHARS = int(os.getenv("LIST_ENTITIES_TOTAL_CHARS", "16000"))


def _document_entities(
    collectionname: str, file_hash: str, budget_chars: int
) -> DocumentEntities:
    """One document's two tiers, cut to `budget_chars` across both.

    The rule-scanner tier is filled first and the NER tier takes what is left. That
    ordering is deliberate: a checksum-validated identifier is evidence and a model's
    guess at a span of prose is a lead, so when only one of the two fits, it is the
    evidence that survives.
    """
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
        dataset = _document_dataset(collectionname, file_hash)
        if dataset is None:
            return DocumentEntities(
                success=False, error="no dataset of this collection holds the document"
            )
        # The website's NER read: each value with its stored hit count, most frequent
        # first. The website then recounts each value in the full-text index, and this
        # read does not.
        rows = clickhouse_query(
            "SELECT entity_type, entity_value AS value, count() AS hit_count "
            "FROM entity_hit ARRAY JOIN entity_values AS entity_value "
            "WHERE collection_dataset = {dataset:String} AND file_hash = {hash:String} "
            "GROUP BY entity_type, entity_value "
            "ORDER BY hit_count DESC, entity_type, value LIMIT {limit:UInt32}",
            database=collection_db(collectionname),
            params={"dataset": dataset, "hash": file_hash, "limit": NER_ENTITY_LIMIT},
        )
    except Exception as exc:  # noqa: BLE001
        return DocumentEntities(success=False, error=f"lookup failed: {exc}")
    values_by_type: dict[str, list[str]] = {}
    for row in rows:
        values_by_type.setdefault(row["entity_type"], []).append(str(row["value"]))

    # Every value costs its own length plus a separator, which is what it weighs in the
    # serialised response the budget is really about.
    spent, dropped_any = 0, False
    structured = []
    for entity in _structured_entities(collectionname, file_hash, dataset):
        cost = len(entity.value) + len(entity.surface_text) + 2
        if spent + cost > budget_chars:
            dropped_any = True
            continue
        structured.append(entity)
        spent += cost

    entities: dict[str, list[str]] = {}
    for entity_type, values in values_by_type.items():
        kept = []
        for value in values:
            cost = len(value) + 2
            if spent + cost > budget_chars:
                dropped_any = True
                continue
            kept.append(value)
            spent += cost
        if kept:
            entities[entity_type] = kept

    return DocumentEntities(
        success=True,
        collectionname=collectionname,
        file_hash=file_hash,
        entities=entities,
        structured=structured,
        truncated=dropped_any,
    )


#: How many rule-found values and NER values one document contributes, the website's
#: limits for its entities panel. Both are ordered by occurrence count, so a limit keeps
#: what the document is about.
STRUCTURED_ENTITY_LIMIT = 1000
NER_ENTITY_LIMIT = 500


def _document_dataset(collectionname: str, file_hash: str) -> str | None:
    """The first dataset of the collection that holds `file_hash`, by name."""
    rows = clickhouse_query(
        "SELECT DISTINCT collection_dataset FROM blobs WHERE blob_hash = {hash:String} "
        "ORDER BY collection_dataset LIMIT 1",
        database=collection_db(collectionname),
        params={"hash": file_hash},
    )
    return (rows[0].get("collection_dataset") or None) if rows else None


def _structured_entities(
    collectionname: str, file_hash: str, dataset: str
) -> list[StructuredEntity]:
    """The rule scanner's values for one document, newest rule set only.

    **The same question the website's document viewer asks, and the same shape of answer**,
    `get_document_entities` in the website backend runs this query against the same
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
                    WHERE collection_dataset = {dataset:String} AND file_hash = {hash:String}
                      AND rule_set_version = (
                          SELECT max(rule_set_version) FROM regex_entity_hit
                          WHERE collection_dataset = {dataset:String} AND file_hash = {hash:String}
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
            params={"dataset": dataset, "hash": file_hash, "limit": STRUCTURED_ENTITY_LIMIT},
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
    #: A short exact phrase of the quote. The card opens the document at this phrase.
    #: Empty means the whole quote.
    find: str = ""
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
    #: refusal. The citation still stands and the reader sees it marked.
    quote_verified: bool = False
    #: Why an unverified quote failed the check: `short`, `absent`, or
    #: `lookup_failed`. Empty when the quote verified, and empty on stored results
    #: that never recorded a reason, so a later reader does not invent one.
    quote_reason: str = ""
    #: The find query the card opens the document with: the `find` phrase in double
    #: quotes, or the quote in double quotes when `find` is empty or fails its check.
    find_query: str = ""
    error: str | None = None


class CitationsResponse(BaseModel):
    success: bool
    citations: list[CitationResult] = Field(default_factory=list)
    #: What was asked for versus what was sensible, in words the model can act on.
    note: str = ""
    error: str | None = None

    @model_serializer
    def _slim_result(self) -> dict[str, Any]:
        if not self.success:
            return {"success": False, "error": self.error}
        citations = []
        for result in self.citations:
            row: dict[str, Any] = {"file_hash": result.file_hash[:16]}
            if result.handle:
                row["handle"] = result.handle
            if result.quote_verified:
                row["quote_verified"] = True
            if result.quote_reason:
                row["quote_reason"] = result.quote_reason
            if result.error:
                row["error"] = result.error
            citations.append(row)
        out: dict[str, Any] = {"citations": citations}
        if self.note:
            out["note"] = self.note
        return out


#: Handles live for the life of a chat session, keyed by the session header the website
#: forwards. It carries no authority (the ACL is a different header), and is an
#: isolation key only.
_HANDLES = HandleTable()

#: Citations one call may carry. A model that wants to cite more than this in one turn is
#: listing its search results rather than choosing evidence.
MAX_CITATIONS_PER_CALL = 12


def _session_id() -> str:
    """The chat session this call belongs to, or a per-process fallback.

    An absent header means the caller is not the chat surface (a script, a probe), and
    those share one table rather than each minting a session, because the alternative is
    an unbounded map keyed by nothing.
    """
    headers = {k.lower(): v for k, v in get_http_headers().items()}
    return headers.get("x-hoover4-chat-session") or "_no_session"


@mcp.tool(
    name="cite_documents",
    description=(
        "Create citation handles for documents that support an answer. An answer that "
        "names a document with no handle shows the reader no "
        "document. Each citation names a "
        "document, a quote copied verbatim from it, an optional find phrase (the "
        "shortest exact part of the quote the reader must see, where the card opens the "
        "document), and why it matters. You get back a "
        "handle like [D1] for each; write those handles into your prose where the claim "
        "is made, and the reader sees the document beside it. The quote is checked "
        "against the document's extracted pages, and one that does not check out comes "
        "back marked with the reason, so re-read rather than paraphrase. Cite what you "
        "relied on, not everything a search returned."
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
            error="citations must be a list of {collectionname, file_hash, quote, find, why}",
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
    short = 0
    absent = 0
    lookup_failed = 0
    for citation in parsed:
        result = _cite_one(acl, session, citation)
        if result.quote_reason == QUOTE_REASON_SHORT:
            short += 1
        elif result.quote_reason == QUOTE_REASON_ABSENT:
            absent += 1
        elif result.quote_reason == QUOTE_REASON_LOOKUP_FAILED:
            lookup_failed += 1
        results.append(result)

    if short:
        note_parts.append(
            f"{short} of {len(results)} quotes were too short to check. "
            f"A quote must be at least {MIN_QUOTE_CHARS} characters after "
            "whitespace is folded."
        )
    if absent:
        note_parts.append(
            f"{absent} of {len(results)} quotes were not found in the document they "
            "were attributed to. Those citations are shown to the reader marked as "
            "unverified. Re-read the document and quote it exactly rather than from "
            "memory."
        )
    if lookup_failed:
        note_parts.append(
            f"{lookup_failed} of {len(results)} documents could not be read for "
            "quote verification. Those citations are shown marked."
        )
    find_fallbacks = sum(
        1 for c in parsed if c.find.strip() and not find_in_quote(c.find, c.quote)
    )
    if find_fallbacks:
        note_parts.append(
            f"{find_fallbacks} of {len(results)} find phrases were not an exact part of "
            f"their quote, or were shorter than {MIN_QUOTE_CHARS} characters. Those "
            "cards open the document at the whole quote."
        )
    if any(r.error is None and not r.handle for r in results):
        note_parts.append(
            "This conversation has used every citation handle it can allocate; the "
            "documents above are cited without one."
        )

    from collection_search_server import paging
    paging._note_refs([{
        "handle": result.handle, "collectionname": result.collectionname,
        "collection_dataset": result.collection_dataset, "file_hash": result.file_hash,
        "path": result.path, "quote": result.quote, "why": result.why,
        "quote_verified": result.quote_verified, "quote_reason": result.quote_reason,
        "find_query": result.find_query,
    } for result in results])
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
        # A single citation sent unwrapped is deliberate, not an error.
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


def _extracted_pages(collectionname: str, file_hash: str, collection_dataset: str):
    """Yield extracted page texts in `extracted_by, page_id` order, one query batch at a time.

    Each batch continues after the `(extracted_by, page_id)` key of the last page read, so
    a batch costs the same at the end of a long document as at its start. An empty
    `collection_dataset` reads every dataset of the collection.
    """
    after = ("", 0)
    while True:
        rows = clickhouse_query(
            "SELECT extracted_by, page_id, text FROM text_content FINAL "
            "WHERE ({dataset:String} = '' OR collection_dataset = {dataset:String}) "
            "AND file_hash = {hash:String} "
            "AND (extracted_by, page_id) > ({after_source:String}, {after_page:UInt32}) "
            "ORDER BY extracted_by, page_id "
            "LIMIT {limit:UInt32}",
            database=collection_db(collectionname),
            params={
                "dataset": collection_dataset,
                "hash": file_hash,
                "after_source": after[0],
                "after_page": after[1],
                "limit": VERIFY_PAGE_BATCH,
            },
        )
        if not rows:
            break
        for row in rows:
            yield row.get("text") or ""
        if len(rows) < VERIFY_PAGE_BATCH:
            break
        after = (rows[-1].get("extracted_by") or "", int(rows[-1].get("page_id") or 0))


def _first_and_rest(pages):
    """Split an iterator into its first item and an iterator that still yields it.

    Used so citation verification can tell 'no extracted text' from 'text that does
    not contain the quote' without reading every page first.
    """
    iterator = iter(pages)
    try:
        first = next(iterator)
    except StopIteration:
        return False, iterator

    def remaining():
        yield first
        yield from iterator

    return True, remaining()


def _cite_one(acl: CallerAcl, session: str, citation: Citation) -> CitationResult:
    result = CitationResult(
        collectionname=citation.collectionname,
        file_hash=citation.file_hash,
        quote=citation.quote,
        why=citation.why,
        find_query=citation_find_query(citation.find, citation.quote),
    )
    try:
        acl.check([citation.collectionname])
    except AccessDenied as exc:
        result.error = str(exc)
        return result
    try:
        whole = full_hash(citation.collectionname, citation.file_hash)
    except HashPrefixError as exc:
        result.error = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("the file_hash start %r was not looked up: %s", citation.file_hash, exc)
        whole = citation.file_hash
    if whole != citation.file_hash:
        citation = citation.model_copy(update={"file_hash": whole})
        result.file_hash = whole
    if not _is_hash(citation.file_hash):
        result.error = "file_hash must be a content hash from search_collections"
        return result

    try:
        path_rows = clickhouse_query(
            "SELECT any(path) AS path, any(collection_dataset) AS collection_dataset "
            "FROM vfs_files WHERE hash = {hash:String} AND is_deleted = 0",
            database=collection_db(citation.collectionname),
            params={"hash": citation.file_hash},
        )
        dataset = (path_rows[0].get("collection_dataset") or "") if path_rows else ""
        has_text, pages = _first_and_rest(
            _extracted_pages(citation.collectionname, citation.file_hash, dataset)
        )
    except Exception as exc:  # noqa: BLE001
        result.error = f"lookup failed: {exc}"
        result.quote_reason = QUOTE_REASON_LOOKUP_FAILED
        return result

    if path_rows:
        result.collection_dataset = path_rows[0].get("collection_dataset") or ""
        result.path = path_rows[0].get("path") or None

    if not has_text:
        result.error = "no extracted text for this document"
        result.quote_reason = QUOTE_REASON_LOOKUP_FAILED
        return result

    match = quote_match_in_pages(citation.quote, pages)
    result.quote_verified = match == QUOTE_MATCH_VERIFIED
    if match != QUOTE_MATCH_VERIFIED:
        result.quote_reason = match
    result.handle = _HANDLES.handle_for(
        session, citation.collectionname, citation.file_hash
    )
    return result


# Tool modules import this object and register their decorators at import time. The legacy
# query helpers above remain callable by the unchanged citation and entity tools.
if __name__ == "__main__":
    import sys
    sys.modules["collection_search_server.server"] = sys.modules[__name__]
from collection_search_server import paging, tools_document, tools_folder, tools_search, tools_table  # noqa: E402,F401


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
