"""Extract mail containers into files for the existing member scanner."""

from __future__ import annotations

import hashlib
import codecs
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import Parser
from email.parser import BytesParser
from email.utils import format_datetime, parsedate_to_datetime
from datetime import timezone


MAIL_MIMES = {
    "application/x-hoover-pst": "pff",
    "application/vnd.ms-outlook": "msg",
    "application/mbox": "mbox",
    "application/ms-tnef": "tnef",
}


def is_msg_ole(path: str) -> bool:
    """Find the Outlook property stream in an OLE directory."""
    import olefile

    try:
        with olefile.OleFileIO(path) as source:
            return source.exists("__properties_version1.0")
    except (OSError, ValueError):
        return False


def mail_format(path: str, mime_types: list[str]) -> str | None:
    """Use bytes before detector names for the supported container formats."""
    try:
        with open(path, "rb") as source:
            head = source.read(16384)
    except FileNotFoundError:
        head = b""
    if head.startswith(b"!BDN") and len(head) >= 12:
        return "pff"
    if head.startswith(bytes.fromhex("d0cf11e0a1b11ae1")) and is_msg_ole(path):
        return "msg"
    if head.startswith(bytes.fromhex("789f3e22")):
        return "tnef"
    if head.removeprefix(b"\xef\xbb\xbf").startswith(b"From "):
        return "mbox"
    for mime in mime_types:
        if mime in MAIL_MIMES:
            return MAIL_MIMES[mime]
    return None


def _safe_name(name: object, fallback: str) -> str:
    text = str(name or fallback).replace("\\", "/").split("/")[-1]
    text = re.sub(r"[\x00-\x1f\x7f]", "_", text).strip(" .")
    # A file name has at most 255 bytes. The callers add at most 30 ASCII bytes.
    return text.encode("utf-8")[:160].decode("utf-8", "ignore").strip(" .") or fallback


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _header(value: object) -> str:
    return " ".join(str(value or "").splitlines()).strip()


def _body_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value or "").encode("utf-8")


def _utf8_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    try:
        return _body_bytes(value).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _message_bytes(identity: str, subject: object, sender: object, date: object,
                   item_class: str, plain: object, html: object, rtf: object,
                   attachments: list[tuple], source_headers: object = None,
                   fallback_headers: dict[str, object] | None = None,
                   body_charset: str = "") -> bytes:
    message = EmailMessage(policy=policy.SMTP)
    if source_headers:
        source = Parser(policy=policy.default).parsestr(
            _body_bytes(source_headers).decode("utf-8", "replace"), headersonly=True)
        for name, value in source.raw_items():
            if name.lower() not in {"content-type", "content-transfer-encoding",
                                    "mime-version", "content-disposition", "content-length"}:
                try:
                    message[name] = _header(value)
                except (TypeError, ValueError):
                    continue
    for name, value in (fallback_headers or {}).items():
        if value and name not in message:
            try:
                message[name] = _header(value)
            except (TypeError, ValueError):
                continue
    if "Subject" not in message:
        message["Subject"] = _header(subject)
    if sender and "From" not in message:
        message["From"] = _header(sender)
    if date and "Date" not in message:
        try:
            stamp = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
            message["Date"] = format_datetime(stamp)
        except (TypeError, ValueError):
            pass
    message["X-Hoover-Item-Class"] = _header(item_class)
    plain_bytes = _body_bytes(plain)
    html_bytes = _body_bytes(html)
    rtf_bytes = _body_bytes(rtf)
    if plain_bytes:
        plain_text = _utf8_text(plain)
        if isinstance(plain, bytes) and body_charset:
            message.set_content(plain_bytes, maintype="text", subtype="plain")
            message.set_param("charset", body_charset, header="Content-Type")
        elif plain_text is None:
            message.set_content(plain_bytes, maintype="text", subtype="plain")
        else:
            message.set_content(plain_text)
    elif html_bytes:
        message.set_content("")
    elif rtf_bytes:
        message.set_content("")
    else:
        message.set_content("")
    if html_bytes:
        if isinstance(html, bytes):
            message.add_alternative(html_bytes, maintype="text", subtype="html")
            if body_charset:
                message.get_payload()[-1].set_param("charset", body_charset,
                                                    header="Content-Type")
        else:
            message.add_alternative(str(html), subtype="html")
    if rtf_bytes:
        message.add_attachment(rtf_bytes, maintype="text", subtype="rtf",
                               disposition="inline")
        message.get_payload()[-1]["X-Hoover-Body-Alternative"] = "rtf"
    for index, attachment in enumerate(attachments):
        name, data = attachment[:2]
        mime = attachment[2] if len(attachment) > 2 else ""
        cid = attachment[3] if len(attachment) > 3 else ""
        main, _, sub = str(mime or "").partition("/")
        # The generator cannot write raw bytes under a message type, for example
        # message/delivery-status. Detection types the stored bytes later.
        if (not main or not sub or main.lower() == "message"
                or not re.fullmatch(r"[A-Za-z0-9.+_-]+", main + sub)):
            main, sub = "application", "octet-stream"
        options = {"cid": _header(cid)} if cid else {}
        message.add_attachment(data, maintype=main, subtype=sub,
                               filename=_safe_name(name, f"attachment-{index:04d}"),
                               **options)
    for index, part in enumerate(message.walk()):
        if part.is_multipart():
            token = hashlib.sha256(f"{identity}:{index}".encode()).hexdigest()[:32]
            part.set_boundary(f"hoover4-{token}")
    return message.as_bytes(policy=policy.SMTP)


def _item_path(root: Path, folders: tuple[str, ...], item_id: int,
               subject: object, extension: str) -> Path:
    folder = root.joinpath(*folders)
    return folder / f"item-{item_id:08x}-{_safe_name(subject, 'untitled')}.{extension}"


def _pff_class(message) -> str:
    try:
        entry = message.get_record_set(0).get_entry_by_type(0x001A)
        return str(entry.data_as_string or "") if entry else ""
    except Exception:
        return ""


def _pff_string(item, tag: int) -> str:
    try:
        entry = item.get_record_set(0).get_entry_by_type(tag)
        return str(entry.data_as_string or "") if entry else ""
    except Exception:
        return ""


def _pff_metadata(item, item_class: str) -> dict:
    properties = {}
    for set_index in range(item.number_of_record_sets):
        record_set = item.get_record_set(set_index)
        for index in range(record_set.number_of_entries):
            try:
                entry = record_set.get_entry(index)
                value = entry.data_as_string
                if value:
                    properties[f"{set_index}:{entry.entry_type:04x}:{index}"] = value
            except (AttributeError, OSError, ValueError):
                continue
    return {"item_class": item_class,
            "subject": _pff_string(item, 0x0037).lstrip("\x01\x01"),
            "properties": properties}


def _pff_attachment_bytes(attachment) -> bytes:
    chunks = []
    left = attachment.size
    while left:
        chunk = attachment.read_buffer(min(left, 1024 * 1024))
        if not chunk:
            raise ValueError("attachment ends before its declared size")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _direct_embedded_parts(message):
    """Return embedded parts without treating their descendants as siblings."""
    pending = [message]
    while pending:
        part = pending.pop()
        if part.get_content_type() == "message/rfc822":
            yield part
        elif part.is_multipart():
            pending.extend(reversed(part.get_payload()))


def _utc_second(value) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat()


def _readpst_parent_key(parent) -> tuple[str, ...] | None:
    """Key an exported parent by its Message-ID, or else by its subject and send time.

    The raw header keeps a Message-ID such as ``<a$@b@c>`` whole. The structured
    parser shortens it. A sent copy often has no Message-ID, so it needs the second key.
    """
    raw = {name.lower(): value for name, value in parent.raw_items()}
    identifier = " ".join(str(raw.get("message-id", "")).split())
    if identifier:
        return ("id", identifier)
    try:
        sent = parsedate_to_datetime(" ".join(str(raw.get("date", "")).split()))
    except (TypeError, ValueError):
        return None
    return ("sent", str(parent.get("Subject") or "").strip(), _utc_second(sent))


def _pff_parent_key(item, subject: object) -> tuple[str, ...] | None:
    identifier = _pff_string(item, 0x1035).strip()
    if identifier:
        return ("id", identifier)
    sent = getattr(item, "client_submit_time", None)
    if sent is None:
        return None
    return ("sent", str(subject or "").strip(), _utc_second(sent))


def _readpst_embedded(path: str, root_folder) -> dict[tuple[str, ...], list[bytes]]:
    """Use libpst only for embedded messages absent from pypff's item tree."""
    pending = [root_folder]
    while pending:
        folder = pending.pop()
        # readpst replaces slash and backslash but accepts dot-only names.
        if folder.name in (".", ".."):
            raise ValueError("readpst cannot safely export a dot-only folder name")
        pending.extend(folder.get_sub_folder(i)
                       for i in range(folder.number_of_sub_folders))
    messages: dict[tuple[str, ...], list[bytes]] = {}
    ambiguous: set[tuple[str, ...]] = set()
    with tempfile.TemporaryDirectory(prefix="hoover4-readpst-") as temporary:
        result = subprocess.run(
            # One job: parallel jobs can write two exports to one file name.
            ["readpst", "-e", "-D", "-t", "e", "-q", "-j", "0", "-o", temporary, path],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=1800,
        )
        if result.returncode:
            raise RuntimeError(f"readpst exited {result.returncode}: {result.stderr[:300]!r}")
        root = Path(temporary)
        for exported in root.rglob("*.eml"):
            if exported.is_symlink() or not exported.resolve().is_relative_to(root):
                raise ValueError("readpst output escapes its temporary directory")
            parent = BytesParser(policy=policy.default).parsebytes(exported.read_bytes())
            key = _readpst_parent_key(parent)
            if key is None:
                continue
            embedded = []
            for index, part in enumerate(_direct_embedded_parts(parent)):
                payload = part.get_payload()
                if not isinstance(payload, list) or not payload:
                    continue
                raw_child = payload[0].as_bytes(policy=policy.SMTP).lstrip(b"\r\n")
                if raw_child.startswith((b"From ", b">From ")):
                    _, _, raw_child = raw_child.partition(b"\n")
                child = BytesParser(policy=policy.SMTP).parsebytes(raw_child)
                # readpst writes random boundaries. A position token keeps the bytes stable
                # and equal for two exported copies of one message.
                for part_index, nested in enumerate(child.walk()):
                    if nested.is_multipart():
                        token = hashlib.sha256(
                            f"{index}:{part_index}".encode()).hexdigest()[:32]
                        nested.set_boundary(f"hoover4-{token}")
                embedded.append(child.as_bytes(policy=policy.SMTP))
            if not embedded:
                continue
            if key in messages and messages[key] != embedded:
                if key[0] == "id":
                    raise ValueError(f"readpst found conflicting messages for {key[1]}")
                ambiguous.add(key)
            messages[key] = embedded
    for key in ambiguous:
        del messages[key]
    return messages


def _extract_pff(path: str, root: Path, errors: list[str]) -> int:
    import pypff

    source = pypff.file()
    count = 0
    readpst_children = None
    # Two copies of one message share a key, so each item counts its own children.
    used_children: dict[int, int] = {}
    try:
        source.open(path)
        pending = [(source.root_folder, ())]
        seen = set()
        while pending:
            folder, ancestry = pending.pop()
            folder_id = folder.identifier
            if folder_id in seen:
                errors.append(f"folder {folder_id}: repeated identifier")
                continue
            seen.add(folder_id)
            location = ancestry + (f"folder-{folder_id:08x}-{_safe_name(folder.name, 'unnamed')}",)
            for index in range(folder.number_of_sub_messages):
                try:
                    item = folder.get_sub_message(index)
                    item_id = item.identifier
                    item_class = _pff_class(item)
                    subject = getattr(item, "subject", None) or _pff_string(item, 0x0037).lstrip("\x01\x01")
                    attachments = []
                    for attachment_index in range(getattr(item, "number_of_attachments", 0)):
                        try:
                            attachment = item.get_attachment(attachment_index)
                            name = attachment.long_filename or f"attachment-{attachment_index:04d}"
                            data = _pff_attachment_bytes(attachment)
                            attachments.append((name, data,
                                                _pff_string(attachment, 0x370E),
                                                _pff_string(attachment, 0x3712)))
                            method_entry = attachment.get_record_set(0).get_entry_by_type(0x3705)
                            method = method_entry.data_as_integer if method_entry else 0
                            if method == 5 and not attachment.number_of_sub_items:
                                if readpst_children is None:
                                    try:
                                        readpst_children = _readpst_embedded(path, source.root_folder)
                                    except Exception as exc:
                                        errors.append(f"readpst embedded export: {exc}")
                                        readpst_children = {}
                                parent_key = _pff_parent_key(item, subject)
                                ordinal = used_children.get(item_id, 0)
                                siblings = readpst_children.get(parent_key, [])
                                if ordinal < len(siblings):
                                    nested_path = _item_path(root, location, item_id,
                                                             subject, "eml").with_suffix("")
                                    _write(nested_path / f"embedded-{attachment_index:04d}.eml",
                                           siblings[ordinal])
                                    used_children[item_id] = ordinal + 1
                                    attachments.pop()
                                    count += 1
                                else:
                                    raw_path = _item_path(root, location, item_id,
                                                          subject, "eml").with_suffix("")
                                    _write(raw_path / f"embedded-{attachment_index:04d}.mapi", data)
                                    count += 1
                                    errors.append(f"item {item_id} attachment {attachment_index}: "
                                                  "readpst did not return its embedded message")
                            for embedded_index in range(attachment.number_of_sub_items):
                                embedded = attachment.get_sub_item(embedded_index)
                                count += _write_embedded_pff(root, location, item_id,
                                                             attachment_index, embedded_index,
                                                             embedded, errors)
                        except Exception as exc:
                            errors.append(f"item {item_id} attachment {attachment_index}: {exc}")
                    is_message = hasattr(item, "plain_text_body")
                    plain = _pff_property(item, "plain_text_body", errors, item_id) if is_message else b""
                    html = _pff_property(item, "html_body", errors, item_id) if is_message else b""
                    rtf = _pff_property(item, "rtf_body", errors, item_id) if is_message else b""
                    if is_message and (item_class.lower().startswith(
                            ("ipm.note", "ipm.post", "report.")) or not item_class):
                        sender = getattr(item, "sender_name", "") or _pff_string(item, 0x0C1A)
                        date = getattr(item, "client_submit_time", None) or getattr(item, "delivery_time", None)
                        data = _message_bytes(f"pff:{item_id}", subject, sender, date,
                                              item_class, plain, html, rtf, attachments,
                                              getattr(item, "transport_headers", None),
                                              {"To": _pff_string(item, 0x0E04),
                                               "Cc": _pff_string(item, 0x0E03),
                                               "Bcc": _pff_string(item, 0x0E02),
                                               "Message-ID": _pff_string(item, 0x1035),
                                               "In-Reply-To": _pff_string(item, 0x1042),
                                               "References": _pff_string(item, 0x1039),
                                               "Thread-Topic": _pff_string(item, 0x0070)})
                        target = _item_path(root, location, item_id, subject, "eml")
                    else:
                        metadata = {**_pff_metadata(item, item_class),
                                    "sender": getattr(item, "sender_name", ""),
                                    "date": str(getattr(item, "client_submit_time", None) or
                                                getattr(item, "delivery_time", None) or ""),
                                    "plain_body": _body_bytes(plain).decode("utf-8", "replace"),
                                    "html_body": _body_bytes(html).decode("utf-8", "replace"),
                                    "rtf_body_bytes": len(_body_bytes(rtf))}
                        data = (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode()
                        target = _item_path(root, location, item_id, subject, "json")
                        for attachment_index, (name, payload, _mime, _cid) in enumerate(attachments):
                            child = target.with_suffix("") / f"attachment-{attachment_index:04d}-{_safe_name(name, 'file')}"
                            _write(child, payload)
                            count += 1
                    _write(target, data)
                    count += 1
                except Exception as exc:
                    errors.append(f"folder {folder_id} item {index}: {exc}")
            for index in range(folder.number_of_sub_folders):
                try:
                    pending.append((folder.get_sub_folder(index), location))
                except Exception as exc:
                    errors.append(f"folder {folder_id} child {index}: {exc}")
    except Exception as exc:
        errors.append(f"PFF source: {exc}")
    finally:
        try:
            source.close()
        except Exception as exc:
            errors.append(f"PFF close: {exc}")
    return count


def _pff_property(item, name: str, errors: list[str], item_id: int):
    try:
        return getattr(item, name)
    except Exception as exc:
        errors.append(f"item {item_id} {name}: {exc}")
        return b""


def _write_embedded_pff(root: Path, location: tuple[str, ...], item_id: int,
                        attachment_index: int, embedded_index: int, embedded,
                        errors: list[str]) -> int:
    subject = getattr(embedded, "subject", "embedded")
    attachments = []
    count = 0
    for index in range(getattr(embedded, "number_of_attachments", 0)):
        try:
            attachment = embedded.get_attachment(index)
            payload = _pff_attachment_bytes(attachment)
            name = attachment.long_filename or f"attachment-{index:04d}"
            attachments.append((name, payload, _pff_string(attachment, 0x370E),
                                _pff_string(attachment, 0x3712)))
        except Exception as exc:
            errors.append(f"embedded item {item_id} attachment {index}: {exc}")
    data = _message_bytes(f"pff:{item_id}:{attachment_index}:{embedded_index}",
                          subject, getattr(embedded, "sender_name", ""),
                          getattr(embedded, "client_submit_time", None),
                          _pff_class(embedded),
                          _pff_property(embedded, "plain_text_body", errors, item_id),
                          _pff_property(embedded, "html_body", errors, item_id),
                          _pff_property(embedded, "rtf_body", errors, item_id), attachments,
                          getattr(embedded, "transport_headers", None))
    folder = _item_path(root, location, item_id, subject, "eml").with_suffix("")
    target = folder / f"embedded-{attachment_index:04d}-{embedded_index:04d}.eml"
    _write(target, data)
    return count + 1


def _extract_msg(path: str, root: Path, errors: list[str]) -> int:
    import extract_msg

    message = extract_msg.openMsg(path)
    try:
        return _write_msg(message, root, "msg:0", errors)
    finally:
        message.close()


def _msg_property(message, name: str, identity: str, errors: list[str]):
    try:
        return getattr(message, name, None)
    except Exception as exc:
        errors.append(f"{identity} {name}: {exc}")
        return None


def _msg_bodies(message, identity: str, errors: list[str]) -> tuple[object, object, object, str]:
    rtf = _msg_property(message, "rtfBody", identity, errors)
    html = message.getStream("__substg1.0_1013001E")
    if html is None:
        html = message.getStream("__substg1.0_10130102")
    if html is None:
        html = _msg_property(message, "htmlBody", identity, errors)
        # extract-msg returns HTML that it derives from the RTF body as UTF-8 bytes.
        # The RTF code page does not apply to it.
        if isinstance(html, bytes):
            try:
                html = html.decode("utf-8")
            except UnicodeDecodeError:
                pass
    charset = ""
    if isinstance(html, bytes):
        match = re.search(br"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", html[:4096], re.I)
        if match:
            charset = match.group(1).decode("ascii")
    if not charset and isinstance(rtf, bytes):
        match = re.search(br"\\ansicpg(\d+)", rtf[:4096])
        if match:
            charset = f"cp{match.group(1).decode('ascii')}"
    if not charset:
        charset = str(getattr(message, "stringEncoding", "") or "")
    try:
        codecs.lookup(charset)
    except LookupError:
        errors.append(f"{identity} unknown body charset {charset}")
        charset = ""
    plain = message.getStream("__substg1.0_1000001E")
    if plain is None:
        plain = _msg_property(message, "body", identity, errors)
    if isinstance(plain, bytes) and charset:
        try:
            plain.decode(charset)
        except UnicodeDecodeError as exc:
            errors.append(f"{identity} plain body {charset}: {exc}")
    return plain, html, rtf, charset


def _write_msg(message, root: Path, identity: str, errors: list[str]) -> int:
    attachments = []
    count = 0
    for index, attachment in enumerate(message.attachments):
        try:
            data = attachment.data
            if isinstance(data, bytes):
                attachments.append((attachment.name or f"attachment-{index:04d}", data,
                                    getattr(attachment, "mimetype", ""),
                                    getattr(attachment, "cid", "") or
                                    getattr(attachment, "contentId", "")))
            elif hasattr(data, "attachments"):
                count += _write_msg(data, root / f"embedded-{index:04d}",
                                    f"{identity}:{index}", errors)
            else:
                errors.append(f"{identity} attachment {index}: unsupported data")
        except Exception as exc:
            errors.append(f"{identity} attachment {index}: {exc}")
    item_class = str(getattr(message, "classType", "") or "")
    plain, html, rtf, charset = _msg_bodies(message, identity, errors)
    subject = getattr(message, "subject", "")
    if item_class.lower().startswith(("ipm.note", "ipm.post", "report.")) or not item_class:
        data = _message_bytes(identity, subject, getattr(message, "sender", ""),
                              getattr(message, "receivedTime", None), item_class,
                              plain, html, rtf, attachments,
                              getattr(message, "header", None),
                              {"To": getattr(message, "to", None),
                               "Cc": getattr(message, "cc", None),
                               "Bcc": getattr(message, "bcc", None),
                               "Message-ID": getattr(message, "messageId", None)},
                              charset)
        target = root / "message.eml"
    else:
        plain_text = _decode_metadata_body(plain, charset, identity, errors)
        html_text = _decode_metadata_body(html, charset, identity, errors)
        metadata = {"item_class": item_class, "subject": subject,
                    "plain_body": plain_text, "html_body": html_text,
                    "rtf_body_bytes": len(_body_bytes(rtf))}
        data = (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode()
        target = root / "item.json"
        for index, (name, payload, _mime, _cid) in enumerate(attachments):
            _write(root / f"attachment-{index:04d}-{_safe_name(name, 'file')}", payload)
            count += 1
    _write(target, data)
    return count + 1


def _decode_metadata_body(value: object, charset: str, identity: str,
                          errors: list[str]) -> str:
    if isinstance(value, str):
        return value
    data = _body_bytes(value)
    try:
        return data.decode(charset or "utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{identity} metadata body decode: {exc}")
        return data.decode(charset or "utf-8", "replace")


def _extract_tnef(path: str, root: Path, errors: list[str]) -> int:
    from tnefparse import TNEF

    tnef = TNEF(Path(path).read_bytes())
    count = 0
    for index, attachment in enumerate(tnef.attachments):
        try:
            name = attachment.long_filename() or attachment.name
            _write(root / f"attachment-{index:04d}-{_safe_name(name, 'file')}",
                   attachment.data)
            count += 1
        except Exception as exc:
            errors.append(f"TNEF attachment {index}: {exc}")
    for extension, body in (("txt", tnef.body), ("html", tnef.htmlbody),
                            ("rtf", tnef.rtfbody)):
        if body:
            _write(root / f"body.{extension}", _body_bytes(body))
            count += 1
    return count


def _extract_mbox(path: str, root: Path, errors: list[str]) -> int:
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    lines = data.splitlines(keepends=True)
    starts = []
    offset = 0
    body_until = -1
    for index, line in enumerate(lines):
        if line.startswith(b"From ") and offset >= body_until:
            starts.append((index, offset))
            header_end = index + 1
            header_offset = offset + len(line)
            content_length = None
            while header_end < len(lines) and lines[header_end].strip(b"\r\n"):
                match = re.match(br"Content-Length:\s*(\d+)", lines[header_end], re.I)
                if match:
                    content_length = int(match.group(1))
                header_offset += len(lines[header_end])
                header_end += 1
            if content_length is not None and header_end < len(lines):
                body_until = header_offset + len(lines[header_end]) + content_length
        offset += len(line)
    for index, (_, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(data)
        envelope_end = data.find(b"\n", start, end)
        if envelope_end < 0:
            errors.append(f"mbox message {index}: envelope has no newline")
            continue
        # The `>From ` lines keep their bytes. Without the `>`, a message body with
        # several `From ` lines reads as a mailbox and is split again.
        message = data[envelope_end + 1:end]
        _write(root / f"message-{index:08d}.eml", message)
    return len(starts) - len(errors)


def extract(path: str, output: str, kind: str) -> dict:
    """Return the member count and all recoverable extraction errors."""
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    try:
        if kind == "pff":
            count = _extract_pff(path, root, errors)
        elif kind == "msg":
            count = _extract_msg(path, root, errors)
        elif kind == "tnef":
            count = _extract_tnef(path, root, errors)
        elif kind == "mbox":
            count = _extract_mbox(path, root, errors)
        else:
            raise ValueError(f"unsupported mail container {kind}")
    except Exception as exc:
        errors.append(f"{kind} source: {exc}")
        count = sum(len(files) for _, _, files in os.walk(root))
    if count == 0 and not errors and kind != "pff":
        errors.append(f"{kind} source contains no readable items")
    return {"entry_count": count, "partial_errors": errors}


if __name__ == "__main__":
    result = extract(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(result, ensure_ascii=False))
