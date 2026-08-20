"""Deciding the one definitive type of a document from five disagreeing detectors.

Detection is deliberately parallel and deliberately contradictory: `file`, Tika, Magika,
the filename and the content sniff each write their own `file_types` row, every detected
type is processed, and the losing detections stay on the record. That is what makes a
.docx get its office text extracted even though libmagic calls it a zip.

It is also what made the file-type facet unusable, because a document that three
detectors describe three ways appeared under three headings at once. This module is the
last pass: once every parser has run, it picks the winner.

The resolution is a total order over *evidence*, not a vote:

1. a parse succeeded and produced rows — the document is a docx because the docx parser
   read text out of it, not because a lookup table says .docx is not a zip;
2. a zip-based document MIME beats `archive`;
3. the content sniff saying email beats `text`;
4. the filename detector agreeing with any content detector beats that detector alone;
5. otherwise the most specific coarse type present, by the ladder below.

`decided_by` records which rule fired, so a wrong answer is diagnosable from the metadata
tab without re-running anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type, is_zip_based_document_mime

#: Most specific first. A document that is both an email and text is an email, an image
#: encoded as text is an image, and a docx that is also a zip is a document.
#:
#: `table` sits above `doc`/`xls` and above `text` because it is the strongest statement
#: available about a document: we did not guess from a MIME, we read a grid out of it. It
#: sits below `email` and `pdf`, the two it can never collide with. A spreadsheet we could
#: read therefore leaves the `xls` bucket of the file-type facet, and a CSV we could read
#: leaves `text` -- which is the point: those buckets now hold exactly the spreadsheets
#: and the text files that are NOT browsable as tables.
SPECIFICITY = (
    "email", "pdf", "table", "doc", "xls", "ppt", "image", "video", "audio",
    "archive", "html", "text", "other",
)

_SPECIFICITY_RANK = {name: index for index, name in enumerate(SPECIFICITY)}

#: When several MIME types map to the winning coarse type, this is whose answer is quoted.
#: The sniff and the filename are the two detectors that know something the bytes alone
#: do not, so they speak first.
_DETECTOR_PREFERENCE = ("content_sniff", "extension", "tika", "magika", "file")

#: Types too vague to quote as the definitive MIME when a real one is available.
_VAGUE_MIMES = frozenset({
    "application/octet-stream", "application/x-empty", "text/plain",
    "inode/x-empty", "application/zip",
})


@dataclass
class Canonical:
    mime_type: str
    file_type: str
    decided_by: str
    losers: list[str] = field(default_factory=list)


def _rank(coarse: str) -> int:
    return _SPECIFICITY_RANK.get(coarse, len(SPECIFICITY))


def _most_specific(coarse_types) -> str:
    candidates = [c for c in coarse_types if c]
    if not candidates:
        return "other"
    return min(candidates, key=_rank)


def _pick_mime(detections: dict[str, list[str]], coarse: str) -> str:
    """A representative MIME for the winning coarse type.

    Falls back to the most specific non-vague MIME any detector reported when *no*
    detected MIME maps to the winner. `table` is the case that needs it: no MIME maps to
    it -- `coarse_file_type` deliberately still calls a spreadsheet `xls` and a CSV
    `text` -- so without the fallback a parsed workbook would carry an empty
    `mime_type`, `document_metadata` would build an empty `file_mime_types` MVA from it,
    and the metadata tab would show a blank where the spreadsheet MIME belongs.
    """
    matching: list[tuple[int, int, str]] = []
    for index, detector in enumerate(_DETECTOR_PREFERENCE):
        for mime in detections.get(detector, ()):
            if coarse_file_type(mime) == coarse:
                matching.append((0 if mime not in _VAGUE_MIMES else 1, index, mime))
    for detector, mimes in detections.items():
        if detector in _DETECTOR_PREFERENCE:
            continue
        for mime in mimes:
            if coarse_file_type(mime) == coarse:
                matching.append((0 if mime not in _VAGUE_MIMES else 1, len(_DETECTOR_PREFERENCE), mime))
    if not matching:
        return _most_specific_mime(detections)
    return min(matching)[2]


def _most_specific_mime(detections: dict[str, list[str]]) -> str:
    """The best MIME any detector reported, ranked by its coarse type then by detector."""
    ranked: list[tuple[int, int, int, str]] = []
    for detector, mimes in detections.items():
        try:
            preference = _DETECTOR_PREFERENCE.index(detector)
        except ValueError:
            preference = len(_DETECTOR_PREFERENCE)
        for mime in mimes:
            if not mime:
                continue
            ranked.append((
                0 if mime not in _VAGUE_MIMES else 1,
                _rank(coarse_file_type(mime)),
                preference,
                mime,
            ))
    if not ranked:
        return ""
    return min(ranked)[3]


def resolve_canonical(
    detections: dict[str, list[str]],
    parsed: set[str],
    archive_member_count: int = 0,
) -> Canonical:
    """The definitive type of one document.

    `detections` maps ``extracted_by`` to the MIME types that detector reported.
    `parsed` is the set of coarse types a parser actually produced rows for — `email`
    from `emails`, `pdf` from `pdfs`, `image` from `image`, `doc`/`xls`/`ppt` from the
    office extractor, `archive` from `archives`. `archive_member_count` is how many
    members the archive branch actually produced.
    """
    all_mimes: list[str] = sorted({m for mimes in detections.values() for m in mimes if m})
    coarse_present = {coarse_file_type(m) for m in all_mimes}

    # An archive that produced no members is not an archive. An empty tar is text, an
    # email whose attachment extraction failed is an email, and a .docx exploded into
    # nothing is whatever else was detected. This is the demotion the file-type facet
    # needed: half a million container nodes corpus-wide hold nothing at all.
    empty_archive = "archive" in coarse_present and archive_member_count <= 0
    evidence = set(parsed)
    if empty_archive:
        evidence.discard("archive")

    winner = ""
    decided_by = ""

    if evidence:
        winner = _most_specific(evidence)
        decided_by = "parse_succeeded"
    elif any(is_zip_based_document_mime(m) for m in all_mimes):
        winner = _most_specific(
            coarse_file_type(m) for m in all_mimes if is_zip_based_document_mime(m)
        )
        decided_by = "zip_based_document"
    elif any(coarse_file_type(m) == "email" for m in detections.get("content_sniff", ())):
        winner = "email"
        decided_by = "content_sniff_email"
    else:
        name_coarse = {coarse_file_type(m) for m in detections.get("extension", ())}
        content_coarse = {
            coarse_file_type(m)
            for detector, mimes in detections.items() if detector != "extension"
            for m in mimes
        }
        agreed = (name_coarse & content_coarse) - ({"archive"} if empty_archive else set())
        if agreed:
            winner = _most_specific(agreed)
            decided_by = "extension_agrees"

    if not winner:
        candidates = coarse_present - ({"archive"} if empty_archive else set())
        winner = _most_specific(candidates)
        decided_by = "empty_archive_demoted" if empty_archive else "specificity_ladder"

    if empty_archive and winner != "archive" and decided_by != "empty_archive_demoted":
        decided_by = f"{decided_by}+empty_archive_demoted"

    mime_type = _pick_mime(detections, winner)
    losers = sorted(
        (m for m in all_mimes if m != mime_type),
        key=lambda m: (_rank(coarse_file_type(m)), m),
    )
    return Canonical(
        mime_type=mime_type,
        file_type=winner,
        decided_by=decided_by,
        losers=losers,
    )
