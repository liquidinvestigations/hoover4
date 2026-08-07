"""A zip-based office document must have a second extractor, and it must not glue words.

Two independent things are under test here.

The first is that `parse_office_xml` extracts anything at all: `easychair.docx` is a
valid zip whose `word/document.xml` reads back in full and which Extractous (native
Tika) refuses with `TIKA-198: Illegal IOException`. Before this extractor that document
had zero rows in `text_content` and was findable only by its filename.

The second is the word-boundary trap, which is the whole reason this is a tree walk and
not a regex. In OOXML a tag boundary means two opposite things depending on the element:

    <w:t>Docu</w:t></w:r><w:r><w:t>ments</w:t>   -> "Documents", no separator
    ...EPiC Series</w:p><w:p>Andrei Voronkov    -> a newline, or two words become one

`re.sub(r'<[^>]+>', '', xml)` gets the first right and the second wrong; joining every
`<w:t>` with a space gets the second right and the first wrong. Both are corruptions
that only show up when someone searches for the word that was mangled.
"""

import zipfile
from pathlib import Path

import pytest

from tasks.P3_parse_files.parse_office_xml import (
    OFFICE_XML_SOURCE,
    extract_office_xml_text,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"


# The corpus is gitignored (fetch-testdata.sh), and lives at a different path inside the
# worker container than in a checkout. Tests over it skip rather than fail when absent,
# so `tests/unit` still passes on a bare laptop as tests/conftest.py promises.
_HERE = Path(__file__).resolve()
_CORPUS_ROOTS = [Path("/testdata/hoover-testdata/data")] + [
    parent / "testdata" / "hoover-testdata" / "data" for parent in _HERE.parents
]


def corpus(relative: str) -> str:
    for root in _CORPUS_ROOTS:
        candidate = root / relative
        if candidate.is_file():
            return str(candidate)
    pytest.skip(f"corpus fixture missing: {relative} (run ./fetch-testdata.sh)")


def write_zip(path, members: dict) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return str(path)


def docx(path, body_xml: str) -> str:
    return write_zip(path, {
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body_xml}</w:body></w:document>',
    })


# --------------------------------------------------------------------------- real files


def test_the_docx_tika_cannot_read_yields_its_text():
    result = extract_office_xml_text(corpus("disk-files/pdf-doc-txt/easychair.docx"))
    assert result.kind == "ooxml_word"
    assert result.ok
    assert "word/document.xml" in result.parts_read
    assert not result.dropped
    for word in ("Voronkov", "EasyChair", "Manchester", "Abstract"):
        assert word in result.text, word


def test_runs_split_mid_word_are_rejoined_without_a_gap():
    """`easychair.docx` really does store "Docu" and "ments" as separate runs, and
    "Kry"/"š"/"tof" as three -- Word splits a run whenever formatting or the
    spell-checker language changes. Joining runs with a space corrupts all three."""
    text = extract_office_xml_text(corpus("disk-files/pdf-doc-txt/easychair.docx")).text
    assert "Documents" in text
    assert "Docu ments" not in text
    assert "Kryštof" in text
    assert "Kry štof" not in text


def test_paragraph_ends_separate_words_that_would_otherwise_merge():
    text = extract_office_xml_text(corpus("disk-files/pdf-doc-txt/easychair.docx")).text
    assert "EPiC Series" in text
    # The title's last word and the author line's first word are adjacent in the XML.
    assert "SeriesAndrei" not in text
    assert "\nAndrei" in text


def test_the_odt_that_already_works_gains_a_second_variant():
    """The .odt extracts fine with Extractous today; this extractor must produce its own
    variant for it anyway, exactly as a PDF carries both `extractous` and `pdftotext`."""
    result = extract_office_xml_text(corpus("disk-files/pdf-doc-txt/easychair.odt"))
    assert result.kind == "opendocument"
    assert result.parts_read == ["content.xml"]
    assert not result.dropped
    for word in ("Voronkov", "EasyChair", "Kryštof"):
        assert word in result.text, word


def test_a_real_xlsx_resolves_its_shared_strings():
    """A sheet stores `t="s"` cells as an index into `xl/sharedStrings.xml`. Dumping the
    sheet without resolving them produces a grid of integers that matches nothing."""
    result = extract_office_xml_text(
        corpus("www.learningcontainer.com/excels/sample-xlsx-file-for-testing.xlsx"))
    assert result.kind == "ooxml_excel"
    assert "xl/sharedStrings.xml" in result.parts_read
    assert "Government\tCanada" in result.text
    assert "January" in result.text


# ------------------------------------------------------------------- the boundary rules


def test_adjacent_runs_concatenate_but_paragraphs_do_not(tmp_path):
    path = docx(tmp_path / "split.docx",
                "<w:p><w:r><w:t>Docu</w:t></w:r><w:r><w:t>ments</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Andrei</w:t></w:r></w:p>")
    text = extract_office_xml_text(path).text
    assert text == "Documents\nAndrei"


def test_tabs_breaks_and_table_rows_become_the_separators_they_mean(tmp_path):
    path = docx(tmp_path / "shapes.docx",
                "<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t></w:r></w:p>"
                "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc>"
                "<w:tc><w:p><w:r><w:t>y</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    text = extract_office_xml_text(path).text
    assert "a\tb" in text
    assert "b\nc" in text
    assert "x" in text and "y" in text


def test_pretty_printed_ooxml_does_not_leak_its_indentation(tmp_path):
    """OOXML is element-only: everything between tags is layout, not content. A walker
    that collected tails as well would turn a re-serialised .docx into ragged text."""
    path = docx(tmp_path / "pretty.docx",
                "\n  <w:p>\n    <w:r>\n      <w:t>Docu</w:t>\n    </w:r>\n"
                "    <w:r>\n      <w:t>ments</w:t>\n    </w:r>\n  </w:p>\n")
    assert extract_office_xml_text(path).text == "Documents"


def test_opendocument_keeps_the_text_between_its_spans(tmp_path):
    """ODF is mixed content: `Kry<text:span>š</text:span>tof` puts "tof" in the span's
    *tail*. Reading only element text loses every second fragment."""
    path = write_zip(tmp_path / "doc.odt", {
        "mimetype": "application/vnd.oasis.opendocument.text",
        "content.xml": (
            f'<office:document-content xmlns:office="{OFFICE_NS}" xmlns:text="{TEXT_NS}">'
            f'<office:body><office:text>'
            f'<text:p>Kry<text:span>š</text:span>tof Hoder</text:p>'
            f'<text:p>Andrei Voronkov</text:p>'
            f'</office:text></office:body></office:document-content>'
        ),
    })
    assert extract_office_xml_text(path).text == "Kryštof Hoder\nAndrei Voronkov"


def test_slides_are_read_in_slide_order_not_lexicographic(tmp_path):
    def slide(word):
        return (f'<p:sld xmlns:p="x" xmlns:a="{A}"><p:cSld><a:p><a:r><a:t>{word}</a:t>'
                f'</a:r></a:p></p:cSld></p:sld>')

    path = write_zip(tmp_path / "deck.pptx", {
        "ppt/slides/slide1.xml": slide("first"),
        "ppt/slides/slide2.xml": slide("second"),
        "ppt/slides/slide10.xml": slide("tenth"),
    })
    result = extract_office_xml_text(path)
    assert result.kind == "ooxml_powerpoint"
    assert [line for line in result.text.split("\n") if line] == ["first", "second", "tenth"]


def test_inline_strings_and_numbers_survive_a_missing_shared_string_table(tmp_path):
    path = write_zip(tmp_path / "book.xlsx", {
        "xl/workbook.xml": f'<workbook xmlns="{SS}"/>',
        "xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns="{SS}"><sheetData>'
            f'<row><c t="inlineStr"><is><t>Total</t></is></c><c><v>42</v></c></row>'
            f'</sheetData></worksheet>'
        ),
    })
    assert extract_office_xml_text(path).text == "Total\t42"


# ------------------------------------------------------------------- failure is normal


def test_a_file_that_is_not_a_zip_is_a_result_not_an_exception(tmp_path):
    path = tmp_path / "not.docx"
    path.write_bytes(b"%PDF-1.4 this is not a zip at all")
    result = extract_office_xml_text(str(path))
    assert not result.ok
    assert result.kind == ""
    assert any("not a readable zip" in reason for reason in result.dropped)


def test_an_empty_file_is_a_result_not_an_exception(tmp_path):
    path = tmp_path / "empty.docx"
    path.write_bytes(b"")
    assert not extract_office_xml_text(str(path)).ok


def test_a_missing_file_is_a_result_not_an_exception(tmp_path):
    result = extract_office_xml_text(str(tmp_path / "nope.docx"))
    assert not result.ok
    assert result.dropped


def test_a_zip_without_the_expected_part_says_so(tmp_path):
    """A .docx whose `word/document.xml` was never written is still a valid zip. It must
    name what it did not find -- an empty result with an empty `dropped` would be
    indistinguishable from a genuinely empty document."""
    path = write_zip(tmp_path / "hollow.docx", {
        "[Content_Types].xml": "<Types/>",
        "docProps/app.xml": "<Properties/>",
    })
    result = extract_office_xml_text(path)
    assert not result.ok
    assert result.kind == ""
    assert any("no part this understands" in reason for reason in result.dropped)


def test_a_word_document_missing_only_its_footnotes_still_yields_the_body(tmp_path):
    path = write_zip(tmp_path / "partial.docx", {
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>'
                             f'<w:p><w:r><w:t>Voronkov</w:t></w:r></w:p></w:body></w:document>',
    })
    result = extract_office_xml_text(path)
    assert result.text == "Voronkov"
    # `word/footnotes.xml` is absent, not broken -- nothing to report about it.
    assert result.dropped == []


def test_malformed_xml_drops_the_part_with_a_reason_and_keeps_the_rest(tmp_path):
    path = write_zip(tmp_path / "broken.docx", {
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>'
                             f'<w:p><w:r><w:t>Voronkov</w:t></w:r></w:p></w:body></w:document>',
        "word/footnotes.xml": "<w:footnotes><w:p><w:t>unclosed",
    })
    result = extract_office_xml_text(path)
    assert result.text == "Voronkov"
    assert result.parts_read == ["word/document.xml"]
    assert any("word/footnotes.xml" in reason and "malformed XML" in reason
               for reason in result.dropped)


def test_every_part_malformed_is_an_empty_result_with_every_reason(tmp_path):
    path = write_zip(tmp_path / "allbroken.docx", {"word/document.xml": "<w:document><<<"})
    result = extract_office_xml_text(path)
    assert not result.ok
    assert result.kind == "ooxml_word"
    assert any("malformed XML" in reason for reason in result.dropped)


def test_a_part_declaring_xml_entities_is_refused_rather_than_expanded(tmp_path):
    """Billion laughs. ElementTree expands internal entities in-process and no office
    format declares any, so the part is refused instead of bounded."""
    bomb = (
        '<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p>'
        f'</w:body></w:document>'
    )
    path = write_zip(tmp_path / "bomb.docx", {"word/document.xml": bomb})
    result = extract_office_xml_text(path)
    assert not result.ok
    assert any("declares XML entities" in reason for reason in result.dropped)


def test_an_oversized_part_is_skipped_with_a_reason(tmp_path, monkeypatch):
    from tasks.P3_parse_files import parse_office_xml

    monkeypatch.setattr(parse_office_xml, "_MAX_PART_BYTES", 128)
    filler = "x" * 500
    path = docx(tmp_path / "huge.docx", f"<w:p><w:r><w:t>{filler}</w:t></w:r></w:p>")
    result = extract_office_xml_text(path)
    assert not result.ok
    assert any("byte budget" in reason for reason in result.dropped)


def test_the_source_label_is_a_native_extractor_not_an_ocr_variant():
    """`extracted_by` is a storage key and a viewer label at once; a name that parsed as
    an OCR variant would render as a broken OCR chip in the source selector."""
    from tasks.text_sources import parse_ocr_extracted_by

    assert OFFICE_XML_SOURCE == "office_xml"
    assert parse_ocr_extracted_by(OFFICE_XML_SOURCE) is None


def test_progress_callback_sees_every_part_it_reads(tmp_path):
    """The activity feeds this to HeartbeatClock: a document with many slides must prove
    forward progress, not merely that a pump thread is alive."""
    seen = []
    path = write_zip(tmp_path / "deck.pptx", {
        f"ppt/slides/slide{i}.xml": f'<p:sld xmlns:a="{A}"><a:p><a:t>s{i}</a:t></a:p></p:sld>'
        for i in range(1, 4)
    })
    extract_office_xml_text(path, on_progress=seen.append)
    assert seen == ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml", "ppt/slides/slide3.xml"]
