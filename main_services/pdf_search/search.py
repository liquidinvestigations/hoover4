"""In-document PDF search, for one request, in its own process.

The server starts this script once for each request and the process exits after it.
The operating system then frees all memory that PDFium used for that document.

Usage: python search.py <pdf path> <output path>, with a JSON array of keywords on stdin.
Output: a JSON array of {"keyword", "result_set": {"results", "total"}} in the output file.

The results have the same form and values as the embedpdf PDFium engine
(`searchAllInPage`, `getHighlightRects`, `buildContext` and `tidy` in
components/pdf-viewer/embed-pdf-viewer/packages/engines/src/lib/pdfium/engine.ts).
The website and its tests read that form (`common::pdf_search_results`).
"""

import ctypes
import json
import math
import re
import resource
import sys

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

# MatchFlag.MatchWholeWord | MatchFlag.MatchConsecutive, the flags of the website search.
SEARCH_FLAGS = pdfium_c.FPDF_MATCHWHOLEWORD | pdfium_c.FPDF_CONSECUTIVE


def char_class(code_points, extra=""):
    """A regular expression character class. The code points are numbers, so that this
    source file holds no invisible or typographic characters."""
    return "[" + "".join(re.escape(chr(c)) for c in code_points) + extra + "]"


# The characters that JavaScript `\s` matches. Python `\s` is a different set.
JS_SPACE_POINTS = [0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0xA0, 0x1680, *range(0x2000, 0x200B),
                   0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]
# `WORD_BREAK` of the engine: `\s`, no-break space, ASCII punctuation, the right double
# quotation mark, the en dash and the em dash.
WORD_BREAK = re.compile(char_class(JS_SPACE_POINTS + [ord(c) for c in ".,;:!?()[]{}<>/\\-\"'`"]
                                   + [0x201D, 0x2013, 0x2014]))
SPACE = char_class(JS_SPACE_POINTS)
SPACE_RUN = re.compile(SPACE + "+")
LEADING_SPACE = re.compile("^" + SPACE + "+")
TRAILING_SPACE = re.compile(SPACE + "+$")
# A hyphen, U+FFFE and spaces: PDFium's mark for a word that a line break divides.
SOFT_HYPHEN_BREAK = re.compile("-" + re.escape(chr(0xFFFE)) + SPACE + "*")
# U+FFFE, soft hyphen, zero width space, word joiner and the byte order mark.
INVISIBLE = re.compile(char_class([0xFFFE, 0xAD, 0x200B, 0x2060, 0xFEFF]))


def page_text(textpage, total):
    """The page text as one Python character for each UTF-16 code unit.

    PDFium counts characters in UTF-16 code units, so the match indices fit this string.
    Like the emscripten `UTF16ToString`, the text stops at the first NUL unit, and a text
    longer than 16 units has each unpaired surrogate replaced by U+FFFD.
    """
    if total <= 0:
        return ""
    buffer = (ctypes.c_ushort * (total + 1))()
    pdfium_c.FPDFText_GetText(textpage, 0, total, buffer)
    units = list(buffer)
    if 0 in units:
        units = units[: units.index(0)]
    if len(units) > 16:
        units = replace_unpaired_surrogates(units)
    return "".join(map(chr, units))


def replace_unpaired_surrogates(units):
    out = list(units)
    i = 0
    while i < len(out):
        unit = out[i]
        if 0xD800 <= unit <= 0xDBFF and i + 1 < len(out) and 0xDC00 <= out[i + 1] <= 0xDFFF:
            i += 2
            continue
        if 0xD800 <= unit <= 0xDFFF:
            out[i] = 0xFFFD
        i += 1
    return out


def is_break(char):
    return WORD_BREAK.match(char) is not None


def tidy(text):
    text = SOFT_HYPHEN_BREAK.sub("", text)
    text = INVISIBLE.sub("", text)
    return SPACE_RUN.sub(" ", text)


def build_context(full_text, start, count, window_chars=30):
    """The text around a match, as `buildContext` builds it."""
    length = len(full_text)

    left = start
    while left > 0 and is_break(full_text[left - 1]):
        left -= 1
    collected = 0
    while left > 0 and collected < window_chars:
        left -= 1
        if not is_break(full_text[left]):
            collected += 1
    while left > 0 and not is_break(full_text[left - 1]):
        left -= 1

    right = start + count
    while right < length and is_break(full_text[right]):
        right += 1
    collected = 0
    while right < length and collected < window_chars:
        if not is_break(full_text[right]):
            collected += 1
        right += 1
    while right < length and not is_break(full_text[right]):
        right += 1

    before = LEADING_SPACE.sub("", SPACE_RUN.sub(" ", full_text[left:start]))
    match = full_text[start : start + count]
    after = TRAILING_SPACE.sub("", SPACE_RUN.sub(" ", full_text[start + count : right]))
    return {
        "before": units_to_str(tidy(before)),
        "match": units_to_str(tidy(match)),
        "after": units_to_str(tidy(after)),
        "truncatedLeft": left > 0,
        "truncatedRight": right < length,
    }


def units_to_str(text):
    """Join surrogate pairs into one character. An unpaired surrogate stays as it is."""
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def page_to_device(width, height, rotation, x, y):
    """`convertPagePointToDevicePoint` at scale 1, without normalized rotation."""
    if rotation == 0:
        return x, height - y
    if rotation == 1:
        return y, x
    if rotation == 2:
        return width - x, y
    return width - y, height - x


def highlight_rects(textpage, start, count, width, height, rotation):
    rects = []
    left, top, right, bottom = (ctypes.c_double() for _ in range(4))
    for i in range(pdfium_c.FPDFText_CountRects(textpage, start, count)):
        if not pdfium_c.FPDFText_GetRect(textpage, i, left, top, right, bottom):
            continue
        corners = [
            page_to_device(width, height, rotation, left.value, top.value),
            page_to_device(width, height, rotation, right.value, top.value),
            page_to_device(width, height, rotation, right.value, bottom.value),
            page_to_device(width, height, rotation, left.value, bottom.value),
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        x, y = min(xs), min(ys)
        rects.append({
            "origin": {"x": x, "y": y},
            "size": {"width": math.ceil(max(xs) - x), "height": math.ceil(max(ys) - y)},
        })
    return rects


def search_page(textpage, full_text, keyword_pointer, page_index, width, height, rotation):
    results = []
    handle = pdfium_c.FPDFText_FindStart(textpage, keyword_pointer, SEARCH_FLAGS, 0)
    try:
        while pdfium_c.FPDFText_FindNext(handle):
            start = pdfium_c.FPDFText_GetSchResultIndex(handle)
            count = pdfium_c.FPDFText_GetSchCount(handle)
            results.append({
                "pageIndex": page_index,
                "charIndex": start,
                "charCount": count,
                "rects": highlight_rects(textpage, start, count, width, height, rotation),
                "context": build_context(full_text, start, count),
            })
    finally:
        pdfium_c.FPDFText_FindClose(handle)
    return results


def keyword_buffer(keyword):
    """The keyword as NUL-terminated UTF-16LE, the `FPDF_WIDESTRING` that PDFium reads.
    The caller keeps the returned buffer while PDFium uses the pointer."""
    data = keyword.encode("utf-16-le", "surrogatepass") + b"\x00\x00"
    buffer = ctypes.create_string_buffer(data, len(data))
    return ctypes.cast(buffer, pdfium_c.FPDF_WIDESTRING), buffer


def search(path, keywords):
    """Results for each keyword, in page order. Each page is loaded once and closed after."""
    buffers = [keyword_buffer(keyword) for keyword in keywords]
    per_keyword = [[] for _ in keywords]
    document = pdfium.PdfDocument(path)
    try:
        size = pdfium_c.FS_SIZEF()
        for page_index in range(len(document)):
            if not pdfium_c.FPDF_GetPageSizeByIndexF(document.raw, page_index, size):
                raise RuntimeError(f"FPDF_GetPageSizeByIndexF failed on page {page_index}")
            width, height = size.width, size.height
            page = document[page_index]
            try:
                rotation = pdfium_c.FPDFPage_GetRotation(page.raw) & 3
                textpage = page.get_textpage()
                try:
                    full_text = page_text(textpage.raw, pdfium_c.FPDFText_CountChars(textpage.raw))
                    for results, (pointer, _) in zip(per_keyword, buffers):
                        results.extend(search_page(textpage.raw, full_text, pointer, page_index, width, height, rotation))
                finally:
                    textpage.close()
            finally:
                page.close()
    finally:
        document.close()
    return [
        {"keyword": keyword, "result_set": {"results": results, "total": len(results)}}
        for keyword, results in zip(keywords, per_keyword)
    ]


def main():
    keywords = json.load(sys.stdin)
    results = search(sys.argv[1], keywords)
    with open(sys.argv[2], "w", encoding="ascii") as out:
        json.dump(results, out, separators=(",", ":"))
    # Peak resident memory of this process, in KiB, for the server log.
    print(f"peak_rss_kib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}", file=sys.stderr)


if __name__ == "__main__":
    main()
