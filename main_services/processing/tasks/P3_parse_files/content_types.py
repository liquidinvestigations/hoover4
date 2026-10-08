"""Identify content types that determine the parser route."""

import re

AUTHORITATIVE_SNIFF_MIMES = frozenset({
    "text/vcard", "application/vnd.sqlite3", "application/vnd.ms-spreadsheetml",
    "application/x-hoover-html-table", "application/x-hoover-mhtml-workbook",
})
AUTHORITATIVE_ALIASES = AUTHORITATIVE_SNIFF_MIMES | {
    "text/x-vcard", "text/directory", "application/x-sqlite3",
}

#: Binary mail containers. A text file with a `.msg` name is not an Outlook message, so
#: when `file` reads the content as text, these types from the extension are dropped
#: and the content detectors choose the route. `application/mbox` is a text format and
#: is not in the set.
BINARY_MAIL_CONTAINER_MIMES = frozenset({
    "application/vnd.ms-outlook", "application/vnd.ms-outlook-pst",
    "application/x-hoover-pst", "application/ms-tnef", "application/vnd.ms-tnef",
})


def sniff_authoritative(path: str, names: list[str]) -> str:
    """Read content before the email and delimited-text sniffs."""
    from tasks.P3_parse_files.table_markup import sniff_html_table, sniff_spreadsheetml
    with open(path, "rb") as source:
        data = source.read(64 * 1024)
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    text = text.lstrip()
    if re.match(r"BEGIN:VCARD[ \t]*(?:\r\n|\n|\r)", text, re.I):
        first_card = re.split(r"^END:VCARD", text, maxsplit=1, flags=re.I | re.M)[0]
        if re.search(r"^VERSION:[ \t]*(?:2\.1|3\.0|4\.0)[ \t]*\r?$", first_card, re.I | re.M):
            return "text/vcard"
    if data.startswith(b"SQLite format 3\x00"):
        return "application/vnd.sqlite3"
    if sniff_spreadsheetml(data):
        return "application/vnd.ms-spreadsheetml"
    for name in names:
        sniff = sniff_html_table(data, name)
        if sniff:
            return sniff.mime_type
    return ""
