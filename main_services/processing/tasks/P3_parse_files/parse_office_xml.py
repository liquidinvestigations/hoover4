"""Second text extractor for zip-based office documents: read the XML parts directly.

Why a second one
----------------
Until now a .docx/.xlsx/.pptx/.odt had exactly ONE extractor, Extractous (native Tika).
When Tika fails the document keeps no searchable text at all -- only its filename.
`testdata/.../pdf-doc-txt/easychair.docx` is a live example: a perfectly valid zip whose
`word/document.xml` reads back in full, which OOXMLParser refuses with
`TIKA-198: Illegal IOException`. Nothing about that file is recoverable by retrying.

This is the same shape as the PDF path, where a file gets both `extractous` and
`pdftotext`: `text_content.extracted_by` exists precisely so several extractors coexist
per file, and the document viewer already renders one chip per source. So this runs
*alongside* Extractous, not only when it fails -- a fallback that only runs on failure is
a fallback nobody notices is broken.

The word-boundary trap
----------------------
Stripping tags with a regex is wrong in a way that is invisible until you search for a
word. Two different things happen at a tag boundary in OOXML:

    <w:t>Docu</w:t></w:r><w:r><w:t>ments</w:t>     -> "Documents"   (no separator!)
    ...EPiC Series</w:p><w:p>...Andrei Voronkov    -> needs a newline

Both are from `easychair.docx`. Word splits a *word* across runs whenever formatting or
the spell-checker language changes mid-word ("Kry"/"š"/"tof Hoder"), so joining adjacent
`<w:t>` with a space would corrupt the text as surely as joining paragraphs without one
would. The separator therefore belongs to the *element*, not to the tag boundary: `w:t`
concatenates, `w:p`/`w:tr` end a line, `w:tab` is a tab, `w:br` is a newline. That is
what the walker below implements, and it is why it walks a parsed tree rather than a
byte string.

OpenDocument nests differently again -- text lives directly inside `text:p` with
`text:span` children and *tails* between them (`Kry<text:span>š</text:span>tof Hoder`) --
so it is walked in mixed-content mode, where every element's text and tail count.
"""

import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence
from xml.etree import ElementTree as ET

from temporalio import activity

from tasks.heartbeat import HeartbeatClock, with_heartbeat

log = logging.getLogger(__name__)

#: `extracted_by` for this extractor. Plain, like its neighbours (`extractous`,
#: `pdftotext`, `raw_text`) -- it is the label on the viewer's source selector, not an
#: internal key. See tasks/text_sources.py.
OFFICE_XML_SOURCE = "office_xml"


#: Largest single XML part read out of the zip, and the total across all parts. Both are
#: enforced on the *read*, not on the zip's declared sizes, so a false local header buys
#: nothing. The neighbouring extractors bound themselves the same way (a subprocess
#: timeout for qpdf/pdftotext/Extractous); an in-process reader has to bound bytes
#: instead, because a zip bomb costs memory rather than wall clock.
_MAX_PART_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 128 * 1024 * 1024

#: Ceiling on how many parts one document may contribute (slides, chapters, sheets).
_MAX_PARTS = 512


def _local(tag) -> str:
    """Local name of a `{namespace}tag`, or "" for comments and processing instructions."""
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


@dataclass(frozen=True)
class _Rules:
    """How one XML dialect turns into text.

    ``mixed_content`` is the real dividing line. OOXML is element-only: text appears
    solely inside the tags named in ``text_tags`` and everything between tags is
    pretty-printing whitespace that must be dropped. OpenDocument and XHTML are mixed:
    an element's own text *and* its tail are content, and dropping tails loses the
    " and Kry" between two spans.
    """
    mixed_content: bool
    text_tags: frozenset = frozenset()
    block_tags: frozenset = frozenset()
    break_tags: frozenset = frozenset()
    tab_tags: frozenset = frozenset()
    space_tags: frozenset = frozenset()
    skip_tags: frozenset = frozenset()


# `w:t` and `a:t` share the local name `t`, which is why WordprocessingML and the
# DrawingML inside text boxes and slides need only one rule set between them.
_OOXML_RULES = _Rules(
    mixed_content=False,
    text_tags=frozenset({"t"}),
    block_tags=frozenset({"p", "tr"}),
    break_tags=frozenset({"br", "cr"}),
    tab_tags=frozenset({"tab", "tc"}),
)

_ODF_RULES = _Rules(
    mixed_content=True,
    block_tags=frozenset({"p", "h", "table-row", "list-item"}),
    break_tags=frozenset({"line-break"}),
    tab_tags=frozenset({"tab", "table-cell"}),
    space_tags=frozenset({"s"}),
)

_XHTML_RULES = _Rules(
    mixed_content=True,
    block_tags=frozenset({
        "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "blockquote", "pre", "figcaption",
    }),
    break_tags=frozenset({"br"}),
    tab_tags=frozenset({"td", "th"}),
    skip_tags=frozenset({"script", "style", "head"}),
)


def _xml_to_text(data: bytes, rules: _Rules) -> str:
    """Walk parsed XML into text, inserting separators the *elements* imply.

    The traversal uses an explicit stack rather than recursion: element depth is
    attacker-controlled here, and a RecursionError in an extractor that is supposed to
    tolerate malformed input would be a crash rather than a dropped part.
    """
    root = ET.fromstring(data)
    out: List[str] = []
    # (element, closing?) -- an element is pushed twice so the close separator and the
    # tail land after everything nested inside it.
    stack = [(root, False)]
    while stack:
        el, closing = stack.pop()
        tag = _local(el.tag)
        if closing:
            if tag in rules.block_tags:
                out.append("\n")
            if rules.mixed_content and el.tail:
                out.append(el.tail)
            continue
        if tag in rules.skip_tags or not isinstance(el.tag, str):
            # A comment's `.text` is the comment body; it is markup, not content. The
            # tail still belongs to the surrounding flow.
            if rules.mixed_content and el.tail:
                out.append(el.tail)
            continue
        if tag in rules.break_tags:
            out.append("\n")
        elif tag in rules.tab_tags:
            out.append("\t")
        elif tag in rules.space_tags:
            out.append(" ")
        if el.text and (rules.mixed_content or tag in rules.text_tags):
            out.append(el.text)
        stack.append((el, True))
        for child in reversed(el):
            stack.append((child, False))
    return "".join(out)


def _normalize(text: str) -> str:
    """Trim trailing whitespace per line and collapse blank-line runs.

    A Word document is one `w:p` per line *including* every empty one, so the raw walk
    of a title page is mostly newlines. This is cosmetic for search but not for the
    document viewer, which shows the text as stored.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: List[str] = []
    blank_run = 0
    for line in lines:
        line = line.rstrip()
        if line.strip():
            blank_run = 0
            kept.append(line)
        else:
            blank_run += 1
            if blank_run <= 1:
                kept.append("")
    return "\n".join(kept).strip()


def _natural_key(name: str):
    """Sort `slide2.xml` before `slide10.xml`; plain lexicographic does not."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


@dataclass
class OfficeXmlResult:
    """What one document yielded, and everything it did not.

    ``dropped`` is the point of the dataclass: a part that failed to read or parse is a
    normal outcome for this extractor, but it is never a silent one -- the caller logs
    every entry and records it against the file.
    """
    text: str = ""
    kind: str = ""
    parts_read: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text)


def _read_part(zf: zipfile.ZipFile, name: str, budget: List[int],
               dropped: List[str]) -> Optional[bytes]:
    """Read one member under the per-part and total budgets, or explain why not."""
    if budget[0] <= 0:
        dropped.append(f"{name}: total byte budget exhausted")
        return None
    limit = min(_MAX_PART_BYTES, budget[0])
    try:
        with zf.open(name) as handle:
            data = handle.read(limit + 1)
    except (KeyError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        # RuntimeError: an encrypted member. NotImplementedError: a compression method
        # this Python was not built with. Both are properties of the file, not bugs.
        dropped.append(f"{name}: unreadable ({type(exc).__name__}: {exc})")
        return None
    if len(data) > limit:
        dropped.append(f"{name}: larger than the {limit} byte budget, skipped")
        return None
    if b"<!ENTITY" in data:
        # ElementTree expands internal entities, so a billion-laughs part would be
        # expanded in this process. No office format declares entities; refusing is
        # cheaper and more correct than trying to bound the expansion.
        dropped.append(f"{name}: declares XML entities, refused")
        return None
    budget[0] -= len(data)
    return data


def _text_from_parts(zf: zipfile.ZipFile, names: Sequence[str], rules: _Rules,
                     budget: List[int], result: OfficeXmlResult,
                     on_progress: Optional[Callable[[str], None]] = None) -> List[str]:
    blocks: List[str] = []
    for name in names[:_MAX_PARTS]:
        if on_progress:
            on_progress(name)
        data = _read_part(zf, name, budget, result.dropped)
        if data is None:
            continue
        try:
            block = _xml_to_text(data, rules)
        except ET.ParseError as exc:
            result.dropped.append(f"{name}: malformed XML ({exc})")
            continue
        result.parts_read.append(name)
        if block.strip():
            blocks.append(block)
    if len(names) > _MAX_PARTS:
        result.dropped.append(f"{len(names) - _MAX_PARTS} further parts over the {_MAX_PARTS} part cap")
    return blocks


def _word_parts(names: Sequence[str]) -> List[str]:
    ordered = ["word/document.xml"]
    ordered += sorted((n for n in names if re.fullmatch(r"word/header\d*\.xml", n)), key=_natural_key)
    ordered += sorted((n for n in names if re.fullmatch(r"word/footer\d*\.xml", n)), key=_natural_key)
    ordered += [n for n in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")
                if n in names]
    return ordered


def _slide_parts(names: Sequence[str]) -> List[str]:
    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=_natural_key)
    notes = sorted((n for n in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)),
                   key=_natural_key)
    return slides + notes


def _sheet_parts(names: Sequence[str]) -> List[str]:
    return sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                  key=_natural_key)


def _shared_strings(data: bytes) -> List[str]:
    """`xl/sharedStrings.xml` as an index-addressable list.

    A rich-text `si` holds one `t` per formatting run and they concatenate with no
    separator, exactly like `w:t` -- same trap, same answer.
    """
    root = ET.fromstring(data)
    strings: List[str] = []
    for si in root:
        if _local(si.tag) != "si":
            continue
        strings.append("".join(el.text or "" for el in si.iter() if _local(el.tag) == "t"))
    return strings


def _sheet_to_text(data: bytes, shared: Sequence[str]) -> str:
    """One line per row, cells tab-separated, `t="s"` cells resolved through `shared`.

    Resolving is not optional: an unresolved shared-string cell stores only its index, so
    a sheet dumped without `sharedStrings.xml` is a grid of integers.
    """
    root = ET.fromstring(data)
    lines: List[str] = []
    for row in (el for el in root.iter() if _local(el.tag) == "row"):
        cells: List[str] = []
        for cell in row:
            if _local(cell.tag) != "c":
                continue
            cell_type = cell.get("t")
            if cell_type == "inlineStr":
                value = "".join(el.text or "" for el in cell.iter() if _local(el.tag) == "t")
            else:
                v = next((el for el in cell if _local(el.tag) == "v"), None)
                raw = (v.text or "") if v is not None else ""
                if cell_type == "s":
                    try:
                        value = shared[int(raw)]
                    except (ValueError, IndexError):
                        value = ""
                else:
                    value = raw
            if value:
                cells.append(value)
        if cells:
            lines.append("\t".join(cells))
    return "\n".join(lines)


def _epub_parts(names: Sequence[str]) -> List[str]:
    return sorted(
        (n for n in names
         if n.lower().endswith((".xhtml", ".html", ".htm")) and not n.startswith("META-INF/")),
        key=_natural_key,
    )


def extract_office_xml_text(file_path: str,
                            on_progress: Optional[Callable[[str], None]] = None
                            ) -> OfficeXmlResult:
    """Pull text out of a zip-based office document by reading its XML parts.

    Never raises for a bad input: a file that is not a zip, a zip with none of the parts
    this understands, a member that will not decompress and a part that will not parse
    all come back as an empty or partial result with the reason in ``dropped``.
    """
    result = OfficeXmlResult()
    try:
        zf = zipfile.ZipFile(file_path)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        result.dropped.append(f"{file_path}: not a readable zip ({type(exc).__name__}: {exc})")
        return result

    budget = [_MAX_TOTAL_BYTES]
    with zf:
        names = zf.namelist()
        name_set = set(names)
        blocks: List[str] = []

        if "word/document.xml" in name_set:
            result.kind = "ooxml_word"
            blocks = _text_from_parts(zf, _word_parts(name_set), _OOXML_RULES,
                                      budget, result, on_progress)
        elif any(n.startswith("ppt/slides/slide") for n in name_set):
            result.kind = "ooxml_powerpoint"
            blocks = _text_from_parts(zf, _slide_parts(name_set), _OOXML_RULES,
                                      budget, result, on_progress)
        elif "xl/workbook.xml" in name_set:
            result.kind = "ooxml_excel"
            blocks = _excel_blocks(zf, name_set, budget, result, on_progress)
        elif "content.xml" in name_set:
            result.kind = "opendocument"
            blocks = _text_from_parts(zf, ["content.xml"], _ODF_RULES,
                                      budget, result, on_progress)
        elif "META-INF/container.xml" in name_set:
            result.kind = "epub"
            blocks = _text_from_parts(zf, _epub_parts(name_set), _XHTML_RULES,
                                      budget, result, on_progress)
        else:
            result.dropped.append(
                f"{file_path}: a zip with no part this understands "
                f"({len(names)} members, first: {names[:3]})"
            )
            return result

    result.text = _normalize("\n".join(blocks))
    return result


def _excel_blocks(zf: zipfile.ZipFile, name_set, budget: List[int],
                  result: OfficeXmlResult,
                  on_progress: Optional[Callable[[str], None]]) -> List[str]:
    shared: List[str] = []
    if "xl/sharedStrings.xml" in name_set:
        data = _read_part(zf, "xl/sharedStrings.xml", budget, result.dropped)
        if data is not None:
            try:
                shared = _shared_strings(data)
                result.parts_read.append("xl/sharedStrings.xml")
            except ET.ParseError as exc:
                # Losing the table does not lose the sheets: numbers, dates and inline
                # strings still come through, and the reason is on the record.
                result.dropped.append(f"xl/sharedStrings.xml: malformed XML ({exc})")

    blocks: List[str] = []
    sheets = _sheet_parts(name_set)
    for name in sheets[:_MAX_PARTS]:
        if on_progress:
            on_progress(name)
        data = _read_part(zf, name, budget, result.dropped)
        if data is None:
            continue
        try:
            block = _sheet_to_text(data, shared)
        except ET.ParseError as exc:
            result.dropped.append(f"{name}: malformed XML ({exc})")
            continue
        result.parts_read.append(name)
        if block.strip():
            blocks.append(block)
    if len(sheets) > _MAX_PARTS:
        result.dropped.append(f"{len(sheets) - _MAX_PARTS} further sheets over the {_MAX_PARTS} part cap")
    if not blocks and shared:
        # No sheet survived, but the strings did. They are unaddressed and unordered,
        # which is worse than a grid -- and still infinitely better than nothing.
        blocks.append("\n".join(s for s in shared if s.strip()))
    return blocks


@dataclass
class ParseOfficeXmlParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


def _record_skip(params: ParseOfficeXmlParams, run_time_ms: int, reason: str) -> None:
    """Record what this extractor could not read, without failing the activity.

    A .docx that is not a zip, or a zip with no part this understands, is a *data* fact
    and must not consume retries. It must also not vanish: the whole reason this
    extractor exists is that a silent extraction failure looks exactly like an empty
    document. Same shape as `parse_ocr._record_skip`.
    """
    from tasks.P2_execute_plan.activities import (
        RecordProcessingErrorsParams,
        record_processing_errors,
    )

    record_processing_errors(RecordProcessingErrorsParams(
        collectionname=params.collectionname,
        errors=[{
            "collection_dataset": params.collection_dataset,
            "hash": params.file_hash,
            "task_name": "parse_office_xml_and_store",
            "run_time_ms": run_time_ms,
            "error_logs": f"{reason}: {params.file_path}",
        }],
    ))


@activity.defn
@with_heartbeat
def parse_office_xml_and_store(params: ParseOfficeXmlParams) -> Dict[str, Any]:
    """Store a zip-based office document's own XML text as a second `text_content` variant.

    Runs alongside Extractous rather than after it, for the same reason a PDF gets both
    `extractous` and `pdftotext`: the variants are cheap, `text_content` is keyed to hold
    several per file, and a fallback wired only to the failure path is one nobody
    notices has itself stopped working.
    """
    from tasks.P3_parse_files.parse_common import insert_text_chunks

    started = time.time()
    log.info("[P3] Reading office XML parts of %s", params.file_path)

    # Class B: a real loop over parts, so beat inside it -- that is evidence of forward
    # progress rather than evidence of a live pump thread.
    heartbeat = HeartbeatClock()
    result = extract_office_xml_text(
        params.file_path,
        on_progress=lambda part: heartbeat.beat(f"office_xml {part}"),
    )
    run_time_ms = max(int((time.time() - started) * 1000), 0)

    for reason in result.dropped:
        log.warning("[P3] office_xml dropped for %s: %s", params.file_hash, reason)

    if not result.ok:
        why = result.dropped[0] if result.dropped else "produced no text"
        _record_skip(params, run_time_ms, f"office_xml_no_text ({result.kind or 'unknown'}) {why}")
        return {"kind": result.kind, "chars": 0, "segments": 0,
                "parts_read": result.parts_read, "dropped": result.dropped}

    segments = insert_text_chunks(params.collectionname, params.collection_dataset,
                                  params.file_hash, OFFICE_XML_SOURCE, result.text)

    if result.dropped:
        # Partial success is still a loss, and it is invisible in `text_content`: the
        # rows that are there look complete.
        _record_skip(params, run_time_ms,
                     "office_xml_partial: " + "; ".join(result.dropped[:5]))

    log.info("[P3] office_xml %s: %d chars from %d parts in %d ms (%s)",
             result.kind, len(result.text), len(result.parts_read),
             run_time_ms, params.file_hash)
    return {"kind": result.kind, "chars": len(result.text), "segments": segments,
            "parts_read": result.parts_read, "dropped": result.dropped}
