"""Reader checks over public mail files at the pinned testdata revision."""

from email import policy
from email.parser import BytesParser
import hashlib
from pathlib import Path
import subprocess

import pytest

from tasks.P3_parse_files.mail_containers import _direct_embedded_parts, extract, mail_format
from tasks.P3_parse_files.sniff_email import strip_email_envelope


pytestmark = pytest.mark.integration
SOURCE = Path("/testdata/hoover-testdata/data/mail-public/sources")
OLD = Path("/testdata/hoover-testdata/data")


def fixture(name: str) -> Path:
    found = list(SOURCE.rglob(name))
    assert found, f"missing public mail fixture {name}"
    return found[0]


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_pff_variants_and_binary_attachment(tmp_path):
    for name, minimum in (("sample2.pst", 1), ("sample1.pst", 1),
                          ("example-2013.ost", 3),
                          ("pstextractortestpdf@outlook.com.ost", 162)):
        path = fixture(name)
        assert mail_format(str(path), []) == "pff"
        out = tmp_path / name
        result = extract(str(path), str(out), "pff")
        assert result["entry_count"] >= minimum
        assert not result["partial_errors"]
        assert len(list(out.rglob("*.eml"))) >= 1
    sample = next((tmp_path / "sample2.pst").rglob("*.eml"))
    message = BytesParser(policy=policy.default).parsebytes(sample.read_bytes())
    assert message["From"] == "Terry Mahaffey <terrymah@microsoft.com>"
    assert message["To"] == "Terry Mahaffey <terrymah@microsoft.com>"
    assert message["Message-ID"]
    attachments = [part for part in message.walk() if part.get_filename()]
    assert len(attachments) == 1
    assert hashlib.sha256(attachments[0].get_payload(decode=True)).hexdigest() == (
        "6cbde5154184f68a2ccefbe1a2d5520efd473576dc60e13665f5706080548f8e"
    )
    other = tmp_path / "sample2-again"
    extract(str(fixture("sample2.pst")), str(other), "pff")
    assert sample.read_bytes() == next(other.rglob("*.eml")).read_bytes()


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_pff_typed_items_and_partial_error(tmp_path):
    result = extract(str(fixture("Outlook.pst")), str(tmp_path / "outlook"), "pff")
    typed = list((tmp_path / "outlook").rglob("*.json"))
    assert typed
    assert b'"item_class"' in typed[0].read_bytes()
    assert result["entry_count"] > 0
    assert not any("readpst" in error for error in result["partial_errors"])
    assert not list((tmp_path / "outlook").rglob("*.mapi"))
    # The Inbox parent has a Message-ID with two `@` signs. The Sent Items copy has none.
    embedded = sorted(path.parent.parent.name.split("-", 2)[2]
                      for path in (tmp_path / "outlook").rglob("embedded-*.eml"))
    assert embedded == ["Inbox"] * 2 + ["Sent Items"] * 2
    partial = extract(str(fixture("Test_part1.pst")), str(tmp_path / "chunk"), "pff")
    assert partial["entry_count"] > 0
    assert partial["partial_errors"]
    damaged = extract(str(fixture("AddingBulkMessagesWithImprovedPerformance.pst")),
                      str(tmp_path / "damaged"), "pff")
    assert damaged["entry_count"] == 0
    assert any("checksum" in error for error in damaged["partial_errors"])


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_pff_delivery_report_keeps_its_status_attachment(tmp_path):
    out = tmp_path / "reports"
    result = extract(str(fixture("passwordprotectedPST.pst")), str(out), "pff")
    assert not any("policy" in error for error in result["partial_errors"])
    reports = [BytesParser(policy=policy.default).parsebytes(path.read_bytes())
               for path in out.rglob("*.eml")]
    reports = [m for m in reports if str(m["X-Hoover-Item-Class"]).endswith("DR")]
    assert sorted(str(m["X-Hoover-Item-Class"]) for m in reports) == (
        ["REPORT.IPM.Note.DR"] * 4 + ["REPORT.IPM.Note.NDR"] * 2)
    for report in reports:
        assert [part.get_filename() for part in report.iter_attachments()] == ["details.txt"]


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_pff_embedded_message_and_stable_bytes(tmp_path):
    source = fixture("submessage.pst")
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert extract(str(source), str(first), "pff") == {
        "entry_count": 2, "partial_errors": [], "partial_error_count": 0}
    assert extract(str(source), str(second), "pff") == {
        "entry_count": 2, "partial_errors": [], "partial_error_count": 0}
    first_files = sorted(path.relative_to(first) for path in first.rglob("*.eml"))
    second_files = sorted(path.relative_to(second) for path in second.rglob("*.eml"))
    assert first_files == second_files
    for relative in first_files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    children = [first / path for path in first_files if "embedded-" in path.name]
    assert len(children) == 1
    child = BytesParser(policy=policy.default).parsebytes(children[0].read_bytes())
    assert child["Subject"] == "This is an embedded message"
    assert "This is the body of an embedded message" in child.get_body().get_content()


def test_embedded_part_collection_keeps_siblings_separate():
    from email.message import EmailMessage

    parent = EmailMessage()
    parent.make_mixed()
    first = EmailMessage()
    first["Subject"] = "first"
    first.make_mixed()
    grandchild = EmailMessage()
    grandchild["Subject"] = "grandchild"
    first.add_attachment(grandchild)
    second = EmailMessage()
    second["Subject"] = "second"
    parent.add_attachment(first)
    parent.add_attachment(second)
    parts = list(_direct_embedded_parts(parent))
    assert len(parts) == 2
    assert [part.get_payload()[0]["Subject"] for part in parts] == ["first", "second"]


def test_mail_reader_stops_child_and_removes_partial_files(tmp_path, monkeypatch):
    from tasks.P3_parse_files import mail_containers, parse_archives, temp_dirs

    source = tmp_path / "mailbox"
    source.write_bytes(b"From sender\nFrom: sender@example.test\n\nBody\n")
    output = tmp_path / "extracted"
    output.mkdir()
    (output / "stale.eml").write_bytes(b"stale")
    monkeypatch.setattr(temp_dirs, "make_temp_dir", lambda *_: str(output))
    monkeypatch.setattr(mail_containers, "mail_format", lambda *_: "mbox")
    monkeypatch.setattr(parse_archives, "worker_is_stopping", lambda: True)
    original_popen = subprocess.Popen
    children = []

    def slow_reader(_command, **options):
        child = original_popen(["/bin/sleep", "30"], **options)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", slow_reader)
    params = parse_archives.ExtractArchiveParams(
        "collection", "dataset", "file-hash", ["application/mbox"], str(source))
    with pytest.raises(RuntimeError, match="mail extraction stopped"):
        parse_archives.extract_archive_to_temp(params)
    assert len(children) == 1
    assert children[0].poll() is not None
    assert not output.exists()


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_msg_nested_binary_and_non_ascii_body(tmp_path):
    from types import SimpleNamespace
    from tasks.P3_parse_files.parse_mime import _detect_by_content

    assert mail_format(str(fixture("testMSG_att_msg.msg")), []) == "msg"
    sniff = _detect_by_content(
        SimpleNamespace(file_path=str(fixture("testMSG_att_msg.msg")), file_names=[]),
        (["application/x-ole-storage"], [], []))
    assert "application/vnd.ms-outlook" in sniff["mime_types"]
    assert "application/vnd.ms-excel" not in sniff["mime_types"]
    nested = extract(str(fixture("testMSG_att_msg.msg")), str(tmp_path / "nested"), "msg")
    assert nested == {"entry_count": 2, "partial_errors": [], "partial_error_count": 0}
    assert len(list((tmp_path / "nested").rglob("*.eml"))) == 2
    binary = extract(str(fixture("testMSG_att_doc.msg")), str(tmp_path / "binary"), "msg")
    assert binary["entry_count"] == 1
    msg = BytesParser(policy=policy.default).parsebytes(
        (tmp_path / "binary" / "message.eml").read_bytes())
    assert any(part.get_filename() == "test-unicode.doc" and part.get_payload(decode=True)
               for part in msg.walk())
    chinese = extract(str(fixture("testMSG_chinese.msg")), str(tmp_path / "chinese"), "msg")
    assert chinese == {"entry_count": 1, "partial_errors": [], "partial_error_count": 0}
    msg = BytesParser(policy=policy.default).parsebytes(
        (tmp_path / "chinese" / "message.eml").read_bytes())
    assert "中文測試" in msg.get_body(preferencelist=("plain",)).get_content()
    derived = extract(str(fixture("test-outlook.msg")), str(tmp_path / "derived"), "msg")
    assert derived["entry_count"] >= 1
    msg = BytesParser(policy=policy.default).parsebytes(
        (tmp_path / "derived" / "message.eml").read_bytes())
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "La réponse à vos attentes" in html
    assert "rÃ©ponse" not in html


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_tnef_and_mbox_boundaries(tmp_path):
    assert mail_format(str(fixture("testWINMAIL.dat")), []) == "tnef"
    assert mail_format(str(fixture("unmunged.mbox.txt")), []) == "mbox"
    tnef = extract(str(fixture("testWINMAIL.dat")), str(tmp_path / "tnef"), "tnef")
    assert tnef == {"entry_count": 6, "partial_errors": [], "partial_error_count": 0}
    mailbox = extract(str(fixture("unmunged.mbox.txt")), str(tmp_path / "mbox"), "mbox")
    assert mailbox == {"entry_count": 4, "partial_errors": [], "partial_error_count": 0}
    assert len(list((tmp_path / "mbox").glob("*.eml"))) == 4


def test_mbox_content_length_and_escaping(tmp_path):
    protected = b"From hidden\n>From escaped\n"
    raw = (b"From first\nFrom: a@example.test\nContent-Length: "
           + str(len(protected)).encode() + b"\n\n" + protected
           + b"From second\nFrom: b@example.test\n\nsecond\n")
    source = tmp_path / "mailbox"
    source.write_bytes(raw)
    result = extract(str(source), str(tmp_path / "out"), "mbox")
    assert result == {"entry_count": 2, "partial_errors": [], "partial_error_count": 0}
    first = (tmp_path / "out" / "message-00000000.eml").read_bytes()
    assert b"From hidden\n>From escaped\n" in first


@pytest.mark.skipif(not SOURCE.is_dir(), reason="public mail fixtures not fetched")
def test_an_mbox_child_with_quoted_from_lines_stays_one_message(tmp_path):
    from tasks.P3_parse_files.sniff_email import MIME_RFC822, sniff_email

    out = tmp_path / "jwz"
    result = extract(str(fixture("jwz.mbox.txt")), str(out), "mbox")
    assert result == {"entry_count": 152, "partial_errors": [], "partial_error_count": 0}
    child = (out / "message-00000051.eml").read_bytes()
    assert b"\n>From within a development environment" in child
    assert sniff_email(child).mime_type == MIME_RFC822


@pytest.mark.skipif(not OLD.is_dir(), reason="existing EMLX fixture not fetched")
def test_emlx_byte_count_excludes_plist():
    path = OLD / "emlx-4-missing-part/1498.partial.emlx"
    raw = path.read_bytes()
    declared = int(raw.split(b"\n", 1)[0].strip())
    message = strip_email_envelope(raw)
    assert len(message) == declared
    assert b"</plist>" not in message
    with pytest.raises(ValueError, match="declared byte count"):
        strip_email_envelope(b"20\nFrom: x\n")


def test_safe_name_fits_a_file_name_in_utf8_bytes():
    from tasks.P3_parse_files.mail_containers import _safe_name

    for subject in ("中" * 80, "א" * 120, "Ж" * 125, "a\x00b" * 100):
        name = _safe_name(subject, "fallback")
        assert len(name.encode("utf-8")) <= 160
        assert "\x00" not in name
        assert name.encode("utf-8").decode("utf-8") == name


def test_two_copies_of_one_message_each_get_their_embedded_child(tmp_path, monkeypatch):
    import sys
    import types
    from tasks.P3_parse_files import mail_containers as mc

    class Entry:
        def __init__(self, s=None, i=None):
            self.data_as_string, self.data_as_integer = s, i

    class RecordSet:
        def __init__(self, props):
            self.props = props

        def get_entry_by_type(self, t):
            return self.props.get(t)

    class Attachment:
        size, long_filename, number_of_sub_items = 0, "fwd.msg", 0

        def read_buffer(self, n):
            return b""

        def get_record_set(self, i):
            return RecordSet({0x3705: Entry(i=5)})

    class Item:
        subject, number_of_attachments, sender_name = "Copy", 1, "a"
        plain_text_body, html_body, rtf_body = b"hello", b"", b""
        client_submit_time = delivery_time = transport_headers = None

        def __init__(self, ident):
            self.identifier = ident

        def get_attachment(self, i):
            return Attachment()

        def get_record_set(self, i):
            return RecordSet({0x001A: Entry("IPM.Note"), 0x1035: Entry("<same@id>")})

    class Folder:
        def __init__(self, ident, name, items, subs=()):
            self.identifier, self.name, self.items, self.subs = ident, name, items, list(subs)
            self.number_of_sub_messages, self.number_of_sub_folders = len(items), len(self.subs)

        def get_sub_message(self, i):
            return self.items[i]

        def get_sub_folder(self, i):
            return self.subs[i]

    root = Folder(1, "", [], [Folder(2, "Inbox", [Item(0x21)]), Folder(3, "Saved", [Item(0x41)])])

    class File:
        root_folder = root

        def open(self, p):
            pass

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pypff", types.SimpleNamespace(file=File))
    monkeypatch.setattr(mc, "_readpst_embedded",
                        lambda path, folder: {("id", "<same@id>"): [b"Subject: inner\r\n\r\nbody\r\n"]})
    errors = []
    mc._extract_pff("/dev/null", tmp_path, errors)
    assert errors == []
    assert len(list(tmp_path.rglob("embedded-0000.eml"))) == 2
    assert not list(tmp_path.rglob("*.mapi"))
