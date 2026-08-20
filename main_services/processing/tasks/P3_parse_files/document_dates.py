"""Resolve the historical dates of a document, with provenance.

One document has a *set* of dates, not one date. A PDF written in 2007 and re-saved
in 2013 has both; an email carrying a 2013 ``Date:`` header with a 2016 attachment has
both. Search filters on "any of them falls in the range", so this stage collects every
date it can confirm rather than picking a winner -- which is also why every date keeps
the key it came from: the document viewer shows the provenance, and that is how a user
learns why a date filter did or did not match.

What counts as a historical date
--------------------------------
Only metadata written by whoever produced the document, or by an archive that stored it:

* the Tika keys in :data:`TIKA_DATE_KEYS`;
* an email ``Date:`` header that actually parsed (``email_headers.date_sent_known``);
* the mtime of an archive member (``vfs_files.mtime_source == 'archive'`` -- 7z restores
  the timestamps the archive stored).

What is NOT a date, and why it is easy to get wrong:

* **Tika's ``File Modified Date``** is the mtime of the temp file the worker handed
  Tika. It is always "a few seconds ago" and it is in the metadata of nearly every
  document, so including it would give every document a 2026 date and make date
  filtering worthless. It is in :data:`EXCLUDED_TIKA_DATE_KEYS` and the allowlist and
  the exclusion set are asserted disjoint.
* **Top-level filesystem mtimes** (``mtime_source == 'filesystem'``) are the clone or
  save time of the corpus, not of the document.
* **Upload/index time** does not exist in this schema at all, by decision.

The sanity window
-----------------
Garbage dates in document metadata are the norm. One PDF claiming 4004 BC ruins every
histogram and every "sort by date" page, so anything outside
``[1800-01-01, now + 1 year]`` is dropped and counted -- never clamped, because a
clamped date is a wrong answer that looks like a right one.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import re

from temporalio import activity

from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)


#: Tika metadata keys that carry a date the *document's producer* wrote.
#:
#: Order matters only for readability -- the result is a set, sorted before it is
#: written. Each maps to the provenance label stored in ``document_dates.source`` and
#: shown in the viewer.
TIKA_DATE_KEYS: dict[str, str] = {
    "dcterms:created": "tika:dcterms:created",
    "dcterms:modified": "tika:dcterms:modified",
    "xmp:CreateDate": "tika:xmp:CreateDate",
    "xmp:ModifyDate": "tika:xmp:ModifyDate",
    "pdf:docinfo:created": "tika:pdf:docinfo:created",
    "pdf:docinfo:modified": "tika:pdf:docinfo:modified",
    "exif:DateTimeOriginal": "tika:exif:DateTimeOriginal",
}

#: Keys that look like dates and must never be consulted. See the module docstring --
#: `File Modified Date` is the worker temp file's mtime and would date every document
#: "now".
EXCLUDED_TIKA_DATE_KEYS: frozenset[str] = frozenset({
    "File Modified Date",
    "File Modified Date/Time",
    "Last-Modified",
    "Last-Save-Date",
    "meta:save-date",
})

assert not (set(TIKA_DATE_KEYS) & EXCLUDED_TIKA_DATE_KEYS), (
    "a Tika key is both allowed and excluded"
)

#: Provenance labels for the two non-Tika sources.
EMAIL_DATE_SOURCE = "email:date"
ARCHIVE_MTIME_SOURCE = "archive:mtime"

SANITY_MIN = datetime(1800, 1, 1, tzinfo=timezone.utc)
SANITY_MAX_LOOKAHEAD = timedelta(days=365)

#: PDF's own date syntax, which Tika sometimes passes through untouched:
#: ``D:20070101224400+03'00'``.
_PDF_DATE_RE = re.compile(
    r"^D:(?P<y>\d{4})(?P<mo>\d{2})?(?P<d>\d{2})?"
    r"(?P<h>\d{2})?(?P<mi>\d{2})?(?P<s>\d{2})?"
    r"(?P<tz>Z|[+-]\d{2}'?\d{2}'?)?$"
)


def parse_metadata_datetime(raw: object) -> datetime | None:
    """Parse one metadata date string into an aware UTC datetime, or None.

    Tolerates what Tika actually emits: a trailing ``Z``, a numeric offset, a bare
    ``yyyy-MM-dd'T'HH:mm:ss`` with no zone at all, a bare date, and PDF's own
    ``D:20070101224400`` form. A naive value is read as UTC -- it is the only defensible
    guess, and being an hour or two out never changes which year-sized bucket a document
    lands in.

    Returns None rather than raising: garbage in document metadata is normal, and one
    unparseable string must not fail a whole plan.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    parsed: datetime | None = None

    pdf = _PDF_DATE_RE.match(text)
    if pdf:
        g = pdf.groupdict()
        try:
            parsed = datetime(
                int(g["y"]), int(g["mo"] or 1), int(g["d"] or 1),
                int(g["h"] or 0), int(g["mi"] or 0), int(g["s"] or 0),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
        # The offset is deliberately ignored: PDF writes it as +03'00', normalising it
        # buys at most a few hours, and a malformed one must not lose the date.
        return parsed

    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def in_sanity_window(when: datetime, now: datetime | None = None) -> bool:
    """Whether a date is plausible enough to index. See the module docstring."""
    now = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return SANITY_MIN <= when <= (now + SANITY_MAX_LOOKAHEAD)


def _tika_values(metadata: dict, key: str) -> list[str]:
    """Tika values are JSON arrays of strings, but a bare string shows up too."""
    value = metadata.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def resolve_dates(
    tika_metadata_json: str | dict | None = None,
    email_date_sent: datetime | None = None,
    archive_mtimes: list[datetime] | tuple[datetime, ...] = (),
    now: datetime | None = None,
) -> list[tuple[datetime, str]]:
    """Every confirmed historical date of one document, as ``(utc_datetime, source)``.

    Deduplicated on ``(second, source)`` and sorted. The caller passes
    ``email_date_sent`` only when ``date_sent_known`` is 1 and ``archive_mtimes`` only
    for ``vfs_files`` rows whose ``mtime_source`` is ``'archive'`` -- this function does
    not re-litigate trust, it applies the sanity window and the key allowlist.

    Pure, so the interesting cases (ISO variants, the sanity window, the excluded key)
    are unit-testable without a stack.
    """
    now = now or datetime.now(timezone.utc)
    found: set[tuple[int, str]] = set()
    rejected: list[tuple[str, str]] = []

    metadata: dict = {}
    if isinstance(tika_metadata_json, dict):
        metadata = tika_metadata_json
    elif tika_metadata_json:
        try:
            loaded = json.loads(tika_metadata_json)
            metadata = loaded if isinstance(loaded, dict) else {}
        except (ValueError, TypeError):
            metadata = {}

    def offer(when: datetime | None, source: str, raw: str) -> None:
        if when is None:
            rejected.append((raw, f"{source}: unparseable"))
            return
        if not in_sanity_window(when, now):
            rejected.append((raw, f"{source}: outside the sanity window"))
            return
        found.add((int(when.timestamp()), source))

    for key, source in TIKA_DATE_KEYS.items():
        for raw in _tika_values(metadata, key):
            offer(parse_metadata_datetime(raw), source, raw)

    if email_date_sent is not None:
        offer(_as_utc(email_date_sent), EMAIL_DATE_SOURCE, str(email_date_sent))

    for mtime in archive_mtimes or ():
        offer(_as_utc(mtime), ARCHIVE_MTIME_SOURCE, str(mtime))

    if rejected:
        log.info("date_rejects: %s", rejected)

    return sorted(
        (datetime.fromtimestamp(epoch, tz=timezone.utc), source)
        for epoch, source in found
    )


def _as_utc(value) -> datetime | None:
    """Coerce whatever the caller has into an aware UTC datetime.

    ClickHouse `DateTime` columns come back through `query_arrow().to_pylist()` as raw
    epoch INTEGERS, not datetimes — which is not what reading the schema suggests, and
    is the kind of thing that only shows up as `'int' object has no attribute 'tzinfo'`
    in a worker log. Accepting both keeps the pure function usable from tests (which
    pass datetimes) and from the activity (which does not).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class ResolveDocumentDatesParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str


@activity.defn
@with_heartbeat
def resolve_document_dates(params: ResolveDocumentDatesParams) -> str:
    """Write the ``document_dates`` rows for every document in one plan.

    Runs after the parse stages and before indexing: P6 builds the `dates` search
    attribute from this table, so a document indexed before its dates were resolved
    would be permanently undated until the next re-index.

    Idempotent by construction -- ``document_dates`` is a ReplacingMergeTree keyed on
    ``(collection_dataset, hash, date, source)``, so re-running a plan rewrites the same
    rows. It is insert-only: a date that stops resolving (metadata changed under a
    re-parse) would linger, which is why every read of the table uses FINAL and the
    viewer shows the source of each row.
    """
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa

    collection_dataset = params.collection_dataset
    with get_collection_client(params.collectionname) as client:
        hashes = client.query_arrow("""
            SELECT item_hashes
            FROM processing_plans
            WHERE collection_dataset = {collection_dataset:String}
              AND plan_hash = {plan_hash:String}
        """, {
            "collection_dataset": collection_dataset,
            "plan_hash": params.plan_hash,
        }).to_pylist()
        item_hashes = sorted(set(hashes[0]["item_hashes"])) if hashes else []
        if not item_hashes:
            return "0 dates (empty plan)"

        # FINAL on all three: every one is a ReplacingMergeTree and an unmerged part
        # would give this activity a stale (or duplicated) view of the metadata.
        tika_rows = client.query_arrow("""
            SELECT hash, tika_metadata_json
            FROM tika_metadata FINAL
            WHERE collection_dataset = {collection_dataset:String}
              AND hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
        }).to_pylist()

        email_rows = client.query_arrow("""
            SELECT email_hash, date_sent
            FROM email_headers FINAL
            WHERE collection_dataset = {collection_dataset:String}
              AND email_hash IN {item_hashes:Array(String)}
              AND date_sent_known = 1
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
        }).to_pylist()

        archive_rows = client.query_arrow("""
            SELECT hash, mtime
            FROM vfs_files FINAL
            WHERE collection_dataset = {collection_dataset:String}
              AND hash IN {item_hashes:Array(String)}
              AND mtime_source = 'archive'
              AND mtime > 0
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
        }).to_pylist()

    tika_by_hash = {row["hash"]: row["tika_metadata_json"] for row in tika_rows}
    email_by_hash = {row["email_hash"]: row["date_sent"] for row in email_rows}
    archive_by_hash: dict[str, list] = {}
    for row in archive_rows:
        archive_by_hash.setdefault(row["hash"], []).append(row["mtime"])

    out_hash: list[str] = []
    out_date: list[int] = []
    out_source: list[str] = []
    for item_hash in item_hashes:
        for when, source in resolve_dates(
            tika_metadata_json=tika_by_hash.get(item_hash),
            email_date_sent=email_by_hash.get(item_hash),
            archive_mtimes=archive_by_hash.get(item_hash, []),
        ):
            out_hash.append(item_hash)
            out_date.append(int(when.timestamp()))
            out_source.append(source)

    if not out_hash:
        return f"0 dates for {len(item_hashes)} documents"

    with get_collection_client(params.collectionname) as client:
        insert_arrow_idempotent(client, "document_dates", pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(out_hash), type=pa.string()),
            "hash": pa.array(out_hash, type=pa.string()),
            "date": pa.array(out_date, type=pa.int64()),
            "source": pa.array(out_source, type=pa.string()),
        }))

    log.info(
        "[P3] %s (plan %s): resolved %d dates over %d documents",
        collection_dataset, params.plan_hash[:8], len(out_hash), len(item_hashes),
    )
    return f"{len(out_hash)} dates for {len(item_hashes)} documents"
