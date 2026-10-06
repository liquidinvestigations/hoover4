"""Verify mail text bodies, headers, nested messages, and fallback behavior."""

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from tasks.P3_parse_files import email_parts
from tasks.P3_parse_files.email_parts import mail_raw_text
from tasks.P3_parse_files.workflows import route_stages


def message():
    mail = EmailMessage()
    mail["Subject"] = "Stored mail text"
    mail.set_content("A readable body.", cte="base64")
    mail.add_alternative('<p>HTML body</p><img src="data:image/png;base64,aW5saW5l">', subtype="html")
    mail.add_attachment(b"secret attachment payload", maintype="application", subtype="octet-stream", filename="attachment.bin")
    return mail.as_bytes()


def test_decoded_bodies_remain_without_attachment_headers_or_bytes():
    data = message()
    text = mail_raw_text(data)
    assert "Subject: Stored mail text" in text
    assert "A readable body." in text
    assert "<p>HTML body</p>" in text
    assert "data:image/png;base64,aW5saW5l" in text
    assert "attachment.bin" not in text
    assert "secret attachment payload" not in text
    assert base64.b64encode(b"secret attachment payload").decode() not in text
    assert text.count("Subject: Stored mail text") == 1
    parsed = BytesParser(policy=policy.default).parsebytes(data)
    for part in email_parts.mail_parts(parsed):
        if part.content_type.startswith("text/") and not part.attachment and not part.nested_message:
            assert email_parts.decode_body(part) in text


def test_nested_message_root_keeps_only_outer_headers():
    data = b"Subject: Outer\nContent-Type: message/rfc822\n\nSubject: Inner\n\nNested body."
    text = mail_raw_text(data)
    assert "Subject: Outer" in text
    assert "Subject: Inner" not in text
    assert "Nested body" not in text


def test_mail_part_failure_keeps_headers_without_a_partial_body(monkeypatch):
    def fail(_message):
        raise ValueError("Signed body could not be decoded.")
    monkeypatch.setattr(email_parts, "mail_parts", fail)
    text = mail_raw_text(message())
    assert "Subject: Stored mail text" in text
    assert "readable body" not in text


def test_parse_failure_keeps_source_header_bytes(monkeypatch):
    class Parser:
        def __init__(self, **_kwargs):
            pass
        def parsebytes(self, _data):
            raise ValueError("Malformed message.")
    monkeypatch.setattr(email_parts, "BytesParser", Parser)
    assert mail_raw_text(b"Subject: Test\r\n\r\nBody") == "Subject: Test"


@pytest.mark.parametrize("mime", ["application/x-hoover-pst", "application/vnd.ms-outlook-pst", "application/vnd.ms-outlook", "application/mbox", "application/ms-tnef", "application/vnd.ms-tnef"])
def test_mail_containers_only_expand_members(mime):
    assert route_stages(dict(coarse_types=["text", "email"], mime_types=[mime, "text/plain"], mime_encodings=[])) == ["archive"]


def test_invalid_header_bytes_can_be_stored_as_utf8():
    text = mail_raw_text(b"Subject: Invalid \xff byte\nContent-Type: text/plain\n\nReadable body.")
    assert "Readable body." in text
    assert "Subject: Invalid" in text
    assert text.encode("utf-8")


def test_mail_container_ignores_conflicting_document_routes():
    assert route_stages(dict(coarse_types=["text", "email", "pdf", "image", "xls"],
        mime_types=["application/mbox", "text/csv"], mime_encodings=[])) == ["archive"]
