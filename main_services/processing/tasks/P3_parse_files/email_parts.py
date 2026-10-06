"""Select email body alternatives and identify attachment MIME parts."""

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
import logging
import re
import subprocess

log = logging.getLogger(__name__)

_SIGNED_DATA_OID = bytes.fromhex("2a864886f70d010702")
_MAX_SIGNED_BYTES = 16 * 1024 * 1024
_MAX_SIGNED_DEPTH = 4


def _cms_content_oid(payload: bytes) -> bytes | None:
    """Read the ContentInfo OID without parsing the encapsulated ASN.1 value."""
    if not payload.startswith(b"\x30") or len(payload) < 4:
        return None
    length_octet = payload[1]
    offset = 2
    if length_octet & 0x80:
        length_size = length_octet & 0x7f
        if length_size > 4 or offset + length_size > len(payload):
            return None
        offset += length_size
    if offset + 2 > len(payload) or payload[offset] != 6:
        return None
    oid_length = payload[offset + 1]
    if oid_length & 0x80 or offset + 2 + oid_length > len(payload):
        return None
    return payload[offset + 2:offset + 2 + oid_length]


def _signed_cms_message(part: Message) -> Message | None:
    payload = part.get_payload(decode=True)
    if not payload or len(payload) > _MAX_SIGNED_BYTES:
        return None
    if _cms_content_oid(payload) != _SIGNED_DATA_OID:
        return None
    try:
        result = subprocess.run(
            ["openssl", "cms", "-verify", "-inform", "DER", "-nosigs", "-noverify"],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10, check=False, start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("signed CMS content could not be read") from exc
    if result.returncode or not result.stdout or len(result.stdout) > _MAX_SIGNED_BYTES:
        raise ValueError("signed CMS content could not be read")
    return BytesParser(policy=policy.default).parsebytes(result.stdout)


def _clear_signed_message(part: Message) -> Message | None:
    if part.get_param("x-action") != "signclear":
        return None
    payload = part.get_payload(decode=True)
    if not payload or len(payload) > _MAX_SIGNED_BYTES:
        return None
    lines = payload.splitlines()
    if not lines or lines[0] != b"-----BEGIN PGP SIGNED MESSAGE-----":
        return None
    start = 1
    while start < len(lines) and lines[start]:
        if not lines[start].startswith(b"Hash:"):
            return None
        start += 1
    if start >= len(lines):
        return None
    start += 1
    try:
        end = lines.index(b"-----BEGIN PGP SIGNATURE-----", start)
    except ValueError:
        return None
    if b"-----END PGP SIGNATURE-----" not in lines[end + 1:]:
        return None
    cleartext = b"\r\n".join(
        line[2:] if line.startswith(b"- ") else line
        for line in lines[start:end]
    )
    return BytesParser(policy=policy.default).parsebytes(cleartext)


class _ReadableHTML(HTMLParser):
    BLOCKS = {"address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
              "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "ol", "p", "pre",
              "section", "table", "td", "th", "tr", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.hidden += 1
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines()
                         if line.strip())


def html_to_text(markup: str) -> str:
    parser = _ReadableHTML()
    parser.feed(markup)
    parser.close()
    return parser.text()


class _ReadableRichText(_ReadableHTML):
    BLOCKS = _ReadableHTML.BLOCKS | {"nl", "paragraph", "excerpt"}

    def handle_starttag(self, tag, attrs):
        if tag == "lt":
            self.parts.append("<")
        elif tag == "param":
            self.hidden += 1
        else:
            super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "param":
            self.hidden = max(0, self.hidden - 1)
        else:
            super().handle_endtag(tag)


def richtext_to_text(markup: str) -> str:
    parser = _ReadableRichText()
    parser.feed(markup.replace("<<", "&lt;"))
    parser.close()
    return parser.text()


def rtf_to_text(rtf: str) -> str:
    """Read ordinary RTF text, including Unicode escapes and code-page hex bytes."""
    if not rtf.lstrip().startswith("{\\rtf"):
        raise ValueError("RTF body has no RTF header")
    skip_destinations = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
                         "header", "footer", "xmlnstbl", "generator"}
    output: list[str] = []
    stack: list[bool] = [False]
    skip_next = 0
    unicode_skip = 1
    codepage = "cp1252"
    hex_bytes = bytearray()

    def flush_hex():
        if hex_bytes:
            if not stack[-1]:
                try:
                    output.append(hex_bytes.decode(codepage, errors="replace"))
                except LookupError:
                    output.append(hex_bytes.decode("cp1252", errors="replace"))
            hex_bytes.clear()

    i = 0
    while i < len(rtf):
        ch = rtf[i]
        if ch == "{":
            flush_hex()
            stack.append(stack[-1])
            i += 1
        elif ch == "}":
            flush_hex()
            if len(stack) > 1:
                stack.pop()
            i += 1
        elif ch == "\\":
            match = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?", rtf[i:])
            if match:
                flush_hex()
                word, number = match.group(1), match.group(2)
                i += len(match.group())
                if word in skip_destinations:
                    stack[-1] = True
                elif word == "ansicpg" and number:
                    codepage = f"cp{number}"
                elif word == "uc" and number:
                    unicode_skip = max(0, int(number))
                elif word == "u" and number:
                    if not stack[-1]:
                        output.append(chr(int(number) % 65536))
                    skip_next = unicode_skip
                elif word == "bin" and number:
                    i += max(0, int(number))
                elif word in {"par", "line"} and not stack[-1]:
                    output.append("\n")
                elif word == "tab" and not stack[-1]:
                    output.append("\t")
                continue
            if i + 3 < len(rtf) and rtf[i + 1] == "'":
                try:
                    value = int(rtf[i + 2:i + 4], 16)
                except ValueError:
                    value = None
                if skip_next:
                    skip_next -= 1
                elif value is not None and not stack[-1]:
                    hex_bytes.append(value)
                i += 4
                continue
            flush_hex()
            if i + 1 < len(rtf):
                special = rtf[i + 1]
                if special == "*":
                    stack[-1] = True
                elif special in "{}\\" and not stack[-1]:
                    if skip_next:
                        skip_next -= 1
                    else:
                        output.append(special)
                i += 2
            else:
                i += 1
        else:
            flush_hex()
            if ch not in "\r\n" and not stack[-1]:
                if skip_next:
                    skip_next -= 1
                else:
                    output.append(ch)
            i += 1
    flush_hex()
    text = "".join(output).encode("utf-16-le", "surrogatepass").decode(
        "utf-16-le", "replace")
    return html_to_text(text) if "\\fromhtml" in rtf else text.strip()


@dataclass(frozen=True)
class MailPart:
    path: str
    message: Message
    content_type: str
    disposition: str
    filename: str | None
    content_id: str | None
    transfer_encoding: str
    defects: tuple[str, ...]
    attachment: bool
    nested_message: bool


def mail_parts(message: Message) -> list[MailPart]:
    """Record stable MIME paths before separate body and attachment decisions."""
    result: list[MailPart] = []

    def visit(part: Message, path: str, parent_attachment: bool = False,
              signed_depth: int = 0, signed_body_allowed: bool = True):
        ctype = part.get_content_type().lower()
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        nested = ctype == "message/rfc822"
        alternative = part.get("X-Hoover-Body-Alternative", "").lower() == "rtf"
        attachment = parent_attachment or nested or disposition == "attachment" or bool(filename and not alternative)
        result.append(MailPart(path, part, ctype, disposition, filename,
                               part.get("Content-ID"),
                               (part.get("Content-Transfer-Encoding") or "7bit").lower(),
                               tuple(str(d) for d in part.defects),
                               attachment, nested))
        if nested:
            return
        if signed_depth < _MAX_SIGNED_DEPTH:
            inner = None
            if ctype in {"application/pkcs7-mime", "application/x-pkcs7-mime",
                         "application/x-pkcs"}:
                try:
                    inner = _signed_cms_message(part)
                except ValueError:
                    # A certificate-only `.p7c` attachment has no content to read.
                    # It stays an attachment. An unreadable signed body still fails,
                    # also at the message root, where `smime.p7m` has a filename.
                    if not attachment or path == "1":
                        raise
                    log.warning("[P3] signed CMS attachment at part %s has no readable content",
                                path)
            elif ctype == "application/pgp":
                inner = _clear_signed_message(part)
            if inner is not None:
                visit(inner, f"{path}.signed", parent_attachment or not signed_body_allowed,
                      signed_depth + 1, signed_body_allowed)
                return
        if part.is_multipart():
            for ordinal, child in enumerate(part.iter_parts(), 1):
                child_disposition = (child.get_content_disposition() or "").lower()
                child_attachment = (attachment or child_disposition == "attachment"
                                    or bool(child.get_filename()))
                visit(child, f"{path}.{ordinal}", attachment, signed_depth,
                      signed_body_allowed and not child_attachment)

    visit(message, "1")
    return result


def decode_body(part: MailPart) -> str:
    """Decode transfer bytes first, then the declared character set."""
    payload = part.message.get_payload(decode=True)
    defects = tuple(str(defect) for defect in part.message.defects)
    if defects:
        log.warning("[P3] MIME defects at part %s: %s", part.path, defects)
    if payload is None:
        raw = part.message.get_payload()
        if not isinstance(raw, str):
            raise ValueError(f"MIME part {part.path} has no text payload")
        payload = raw.encode("ascii", errors="surrogateescape")
    if part.content_type in {"text/rtf", "application/rtf"}:
        return payload.decode("latin1")
    charset = part.message.get_content_charset() or "ascii"
    try:
        return payload.decode(charset)
    except (LookupError, UnicodeError) as exc:
        log.warning("[P3] MIME charset fallback at part %s (%s): %s", part.path, charset, exc)
        return payload.decode("utf-8", errors="replace")


def body_alternatives(message: Message) -> dict[str, str]:
    """Return readable body text by format without attachment or nested-message text."""
    parts: dict[str, list[str]] = {"plain": [], "html": [], "rtf": [], "richtext": []}
    for part in mail_parts(message):
        if part.attachment or part.nested_message:
            continue
        kind = {"text/plain": "plain", "text/html": "html",
                "text/richtext": "richtext", "text/enriched": "richtext",
                "text/rtf": "rtf", "application/rtf": "rtf"}.get(part.content_type)
        if kind is None:
            continue
        content = decode_body(part)
        if kind == "html":
            content = html_to_text(content)
        elif kind == "rtf":
            content = rtf_to_text(content)
        elif kind == "richtext":
            content = richtext_to_text(content)
        if content.strip():
            parts[kind].append(content.strip())
    return {kind: "\n\n".join(texts) for kind, texts in parts.items() if texts}


def mail_raw_text(data: bytes) -> str:
    """Keep message headers and decoded text bodies without attachment payloads."""
    from tasks.P3_parse_files.sniff_email import strip_email_envelope

    def header_text(part: Message) -> str:
        headers = "\n".join(f"{name}: {value}" for name, value in part.raw_items())
        return headers.encode("utf-8", "surrogateescape").decode("utf-8", "replace")

    message = None
    source = data
    try:
        source = strip_email_envelope(data)
        message = BytesParser(policy=policy.default).parsebytes(source)
        headers = header_text(message)
        output = [headers]
        for part in mail_parts(message):
            if part.attachment or part.nested_message or part.message.is_multipart():
                continue
            if not part.content_type.startswith("text/"):
                continue
            if part.path != "1":
                output.append(header_text(part.message))
            output.append(decode_body(part))
        return "\n\n".join(output)
    except Exception:
        if message is not None:
            return header_text(message)
        return re.split(rb"\r?\n\r?\n", source, maxsplit=1)[0].decode("utf-8", "replace")
