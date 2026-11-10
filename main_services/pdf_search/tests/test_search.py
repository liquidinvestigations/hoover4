"""Unit tests for search.py. Run them in the hoover4-pdf-search container."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import search  # noqa: E402


def one_page_pdf(text, rotate=0):
    """A PDF with one 600 x 800 page that shows `text` in Helvetica at (100, 700).
    PDFium rebuilds the cross-reference table, so the offsets need not be exact."""
    stream = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Rotate {rotate} "
        f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def write_pdf(tmp_path, data):
    path = tmp_path / "doc.pdf"
    path.write_bytes(data)
    return str(path)


def test_whole_words_match_with_positions_and_context(tmp_path):
    path = write_pdf(tmp_path, one_page_pdf("hello world, hello again"))
    [hello, partial] = search.search(path, ["hello", "hell"])
    assert hello["keyword"] == "hello"
    assert hello["result_set"]["total"] == 2
    first, second = hello["result_set"]["results"]
    assert (first["pageIndex"], first["charIndex"], first["charCount"]) == (0, 0, 5)
    assert (second["charIndex"], second["charCount"]) == (13, 5)
    assert first["context"] == {
        "before": "", "match": "hello", "after": " world, hello again",
        "truncatedLeft": False, "truncatedRight": False,
    }
    [rect] = first["rects"]
    # The text starts at x = 100. The device y axis goes down from the page top at 800.
    assert 99 <= rect["origin"]["x"] <= 101
    assert 85 <= rect["origin"]["y"] <= 100
    assert rect["size"]["width"] > 0 and rect["size"]["height"] > 0
    assert partial["result_set"] == {"results": [], "total": 0}


def test_rotated_page_swaps_the_axes(tmp_path):
    path = write_pdf(tmp_path, one_page_pdf("hello", rotate=90))
    [[result]] = [r["result_set"]["results"] for r in search.search(path, ["hello"])]
    [rect] = result["rects"]
    # At 90 degrees the device x is the page y and the device y is the page x.
    assert 690 <= rect["origin"]["x"] <= 715
    assert 99 <= rect["origin"]["y"] <= 101


def test_context_keeps_whole_words_and_marks_truncation():
    text = " ".join(f"w{i:02d}" for i in range(40))
    start = text.index("w20")
    context = search.build_context(text, start, 3)
    assert context["match"] == "w20"
    # 30 non-break characters on each side, extended to a whole word. As in the engine,
    # only the outer end of each side is trimmed, so the space next to the match stays.
    assert context["before"] == "w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 "
    assert context["after"] == " w21 w22 w23 w24 w25 w26 w27 w28 w29 w30"
    assert context["truncatedLeft"] and context["truncatedRight"]


def test_tidy_joins_a_divided_word_and_drops_invisible_characters():
    divided = "infor-" + chr(0xFFFE) + "\r\nmation"
    assert search.tidy(divided) == "information"
    assert search.tidy("a" + chr(0xAD) + "b" + chr(0x200B) + "c\n\n d") == "abc d"


def test_page_text_replaces_unpaired_surrogates_only_in_long_text():
    assert search.replace_unpaired_surrogates([0x61, 0xD800, 0x62]) == [0x61, 0xFFFD, 0x62]
    assert search.replace_unpaired_surrogates([0xD83D, 0xDE00]) == [0xD83D, 0xDE00]


def test_a_file_that_is_not_a_pdf_fails(tmp_path):
    path = write_pdf(tmp_path, b"not a pdf")
    try:
        search.search(path, ["x"])
    except Exception as error:  # pypdfium2 raises PdfiumError
        assert "Failed to load document" in str(error)
    else:
        raise AssertionError("a file that is not a PDF must fail")
