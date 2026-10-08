"""Verify the configured Tika server with document and output-limit samples."""

import os
from pathlib import Path
import requests
import pytest

from tasks.P3_parse_files import parse_tika as tika

pytestmark = pytest.mark.skipif(not os.environ.get("TIKA_TEST_URL"), reason="Tika test server is not configured")
DATA = Path(os.environ.get("TIKA_TEST_DATA", "/testdata"))


def parse(path, *, types=(), routes=(), file_type=""):
    params = tika.RunTikaParams("c", "ds", "h", str(path),
        tika.try_budget_seconds("tika_text_batch", path.stat().st_size),
        mime_types=list(types), routes=list(routes), file_mime_type=file_type)
    return tika.parse_document(params)


@pytest.fixture(autouse=True)
def configured_server(monkeypatch):
    monkeypatch.setenv("TIKA_URL", os.environ["TIKA_TEST_URL"])
    version = requests.get(os.environ["TIKA_TEST_URL"] + "/version", timeout=10)
    assert version.status_code == 200 and "4.1.0" in version.text


@pytest.mark.parametrize("relative,expected,types,routes", [
    ("disk-files/pdf-doc-txt/stanley.ec02.pdf", "application/pdf", (), ()),
    ("file-types/sqlite/contacts-orders.sqlite3", "application/x-sqlite3", (), ()),
    ("file-types/vcard/vcard-3.0-photo.vcf", "text/x-vcard", ("text/vcard",), ("text",)),
    ("text-spam/calendar-attach.ics", "text/calendar", ("text/calendar",), ("text",)),
    ("disk-files/pdf-doc-txt/easychair.txt", "text/plain", (), ()),
])
def test_document_types(relative, expected, types, routes):
    answer = parse(DATA / relative, types=types, routes=routes)
    assert answer.error is None
    assert tika.document_type(answer.metadata) == expected
    if routes:
        assert answer.text == ""


def test_cjk_write_limit(tmp_path):
    path = tmp_path / "cjk.txt"
    with path.open("wb") as data:
        for _ in range(30):
            data.write(("漢" * 1_000_000).encode())
    answer = parse(path)
    assert answer.error is None
    assert answer.metadata["tk:exception:write-limit-reached"] == "true"
    assert len(answer.text) == 20_000_000


def test_nested_xml_entities(tmp_path):
    path = tmp_path / "entities.xml"
    path.write_text('''<?xml version="1.0"?>
<!DOCTYPE root [<!ENTITY a "abc"><!ENTITY b "&a;&a;"><!ENTITY c "&b;&b;">]>
<root>&c;</root>''')
    answer = parse(path)
    assert answer.error is None
    assert "abcabcabcabc" in answer.text
    assert len(answer.text) < 100


def test_rar_split_part_keeps_java_failure():
    path = DATA / "disk-files/archives/generated/split/rar1/rar_split1.part12.rar"
    answer = parse(path, types=["application/x-rar-compressed"], routes=["archive"])
    assert answer.error.type == "TikaParseFailed"
    assert answer.error.non_retryable
    assert "tk:exception:container-exception" in answer.metadata


def test_msg_archive_keeps_body_member(tmp_path, monkeypatch):
    from email import policy
    from email.parser import BytesParser
    from tasks.P3_parse_files import parse_archives, temp_dirs
    from tasks.P3_parse_files.email_parts import body_alternatives
    from temporalio.testing import ActivityEnvironment
    import extract_msg

    path = next(DATA.glob("mail-public/sources/apache-tika/**/testMSG_att_doc.msg"))
    with extract_msg.openMsg(str(path)) as source:
        expected = source.body.strip()
    out = tmp_path / "members"
    monkeypatch.setattr(temp_dirs, "make_temp_dir", lambda *a: str(out))
    result = ActivityEnvironment().run(parse_archives.extract_archive_to_temp,
        parse_archives.ExtractArchiveParams("c", "ds", "h", ["application/vnd.ms-outlook"], str(path)))
    assert result["entry_count"] > 0
    emitted = BytesParser(policy=policy.default).parsebytes((out / "message.eml").read_bytes())
    bodies = body_alternatives(emitted)
    assert expected in "\n".join(bodies.values())


def test_email_outer_body_excludes_attachment(tmp_path):
    from email.message import EmailMessage
    message = EmailMessage()
    message["Subject"] = "Outer body test"
    message.set_content("OUTER_BODY_SENTINEL")
    message.add_attachment("ATTACHMENT_TEXT_SENTINEL", filename="attachment.txt")
    path = tmp_path / "email.eml"
    path.write_bytes(bytes(message))
    answer = parse(path)
    assert answer.error is None and "OUTER_BODY_SENTINEL" in answer.text
    assert "ATTACHMENT_TEXT_SENTINEL" not in answer.text
    metadata = parse(path, types=["message/rfc822"], routes=["email", "text"])
    assert metadata.error is None and metadata.text == ""


@pytest.mark.parametrize("relative,has_body", [
    ('mail-public/sources/nauru-police-force/czarist-daniel/czarist-daniel/recoverableitemsdeletions/2023.eml', True),
    ('mail-public/sources/nauru-police-force/rosella-dageago/rosella-dageago/sentitems/86.eml', False),
    ('mail-public/sources/nauru-police-force/brown-capelle/brown-capelle/sentitems/742.eml', True),
    ('mail-public/sources/nauru-police-force/peter-leaupepe/peter-leaupepe/sentitems/1283.eml', True),
    ('mail-public/sources/nauru-police-force/peter-leaupepe/peter-leaupepe/inbox/1385.eml', False),
])
def test_nauru_email_bodies(relative, has_body):
    from email import policy
    from email.parser import BytesParser
    from tasks.P3_parse_files.email_parts import body_alternatives

    path = DATA / relative
    answer = parse(path)
    assert answer.error is None
    assert answer.text.strip()
    source = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    bodies = body_alternatives(source)
    assert bool(bodies) == has_body
    text = " ".join(answer.text.split())
    if has_body:
        assert any(" ".join(body.split())[:40] in text for body in bodies.values())
    else:
        assert " ".join(str(source["Subject"]).split()) in text
    for part in source.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload()
            if isinstance(payload, str) and len(payload) > 200:
                assert payload[:200] not in answer.text
    metadata = parse(path, types=["message/rfc822"], routes=["email", "text"])
    assert metadata.error is None
    assert metadata.text == ""
