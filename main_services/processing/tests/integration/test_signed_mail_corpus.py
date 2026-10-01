"""Readable signed mail checks over the pinned public corpus."""

from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

from tasks.P3_parse_files.email_parts import body_alternatives, mail_parts


CORPUS = Path("/testdata/hoover-testdata/data/mail-public")


def read_message(relative_path: str):
    path = CORPUS / relative_path
    if not path.exists():
        pytest.skip("public mail corpus is not mounted")
    return BytesParser(policy=policy.default).parsebytes(path.read_bytes())


def test_opaque_cms_signed_body_keeps_outer_attachment():
    message = read_message(
        "sources/thunderbird/mailnews/test/data/smime/alice.sig.SHA256.opaque.eml")
    assert body_alternatives(message) == {
        "plain": "This is a test message from Alice to Bob."}
    assert [(part.path, part.filename) for part in mail_parts(message) if part.attachment] == [
        ("1", "smime.p7m")]


def test_cms_enveloped_content_has_no_readable_body():
    message = read_message("sources/thunderbird/mailnews/test/data/smime/alice.env.eml")
    assert body_alternatives(message) == {}


def test_clear_signed_pgp_corpus_body_has_no_signature():
    message = read_message("derived-eml/jwz/0087.eml")
    body = body_alternatives(message)["plain"]
    assert "KNOWN HOAX" in body
    assert "\r\n--\r\nInternet:" in body
    assert "BEGIN PGP SIGNATURE" not in body
    assert "iQCVAw" not in body


def test_nested_cms_binary_content_stays_out_of_body():
    message = read_message("derived-eml/jwz/0107.eml")
    assert body_alternatives(message) == {}
    assert [part.content_type for part in mail_parts(message)] == [
        "application/x-pkcs7-mime", "application/x-pkcs7-mime", "image/jpeg"]


def test_legacy_pkcs_signed_message_has_plain_body():
    message = read_message("derived-eml/jwz/0096.eml")
    body = body_alternatives(message)["plain"]
    assert "successfully decoded and read" in body
    assert "pkcs/MIME signed message" in body


def test_certificate_only_cms_attachment_keeps_plain_body():
    message = read_message("derived-eml/content-length/0008.eml")
    assert "here's my encryption certificate" in body_alternatives(message)["plain"]
    assert [part.filename for part in mail_parts(message) if part.attachment] == ["eric.p7c"]


def test_unreadable_signed_cms_body_still_fails():
    message = read_message("derived-eml/content-length/0013.eml")
    with pytest.raises(ValueError, match="signed CMS content could not be read"):
        body_alternatives(message)


def test_unreadable_signed_root_with_a_filename_still_fails():
    import base64

    path = CORPUS / "sources/thunderbird/mailnews/test/data/smime/alice.sig.SHA256.opaque.eml"
    if not path.exists():
        pytest.skip("public mail corpus is not mounted")
    message = BytesParser(policy=policy.compat32).parsebytes(path.read_bytes())
    message.set_payload(base64.encodebytes(message.get_payload(decode=True)[:24]).decode())
    truncated = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
    assert truncated.get_filename() == "smime.p7m"
    with pytest.raises(ValueError, match="signed CMS content could not be read"):
        body_alternatives(truncated)
