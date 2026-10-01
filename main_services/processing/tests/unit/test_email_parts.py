"""MIME body and attachment decisions for email extraction."""

from email import policy
from email.parser import BytesParser

from tasks.P3_parse_files.email_parts import body_alternatives, mail_parts, rtf_to_text
from tasks.P3_parse_files.parse_common import split_text_segments


def parse(raw: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw)


def test_alternative_and_mixed_body_exclude_named_text_attachment():
    message = parse(b"""MIME-Version: 1.0
Content-Type: multipart/mixed; boundary=outer

--outer
Content-Type: multipart/alternative; boundary=inner

--inner
Content-Type: text/plain; charset=utf-8

Plain body
--inner
Content-Type: text/html; charset=utf-8

<style>hidden</style><p>HTML body</p><script>hidden</script>
--inner--
--outer
Content-Type: text/plain; name=notes.txt
Content-Disposition: attachment; filename=notes.txt

Attachment words
--outer--
""")
    assert body_alternatives(message) == {"plain": "Plain body", "html": "HTML body"}
    assert [(p.path, p.filename) for p in mail_parts(message) if p.attachment] == [
        ("1.2", "notes.txt")]


def test_nested_message_is_a_child_not_parent_body():
    message = parse(b"""MIME-Version: 1.0
Content-Type: multipart/mixed; boundary=outer

--outer
Content-Type: text/plain

Parent body
--outer
Content-Type: message/rfc822

Subject: child
Content-Type: text/plain

Child body
--outer--
""")
    assert body_alternatives(message) == {"plain": "Parent body"}
    assert [p.path for p in mail_parts(message) if p.nested_message] == ["1.2"]


def test_html_only_charset_and_rtf_alternative():
    html = parse(b"Content-Type: text/html; charset=iso-8859-1\n\n<p>caf\xe9</p>")
    assert body_alternatives(html) == {"html": "caf\xe9"}
    message = parse(b"""MIME-Version: 1.0
Content-Type: multipart/mixed; boundary=x

--x
Content-Type: text/rtf
X-Hoover-Body-Alternative: rtf

{\\rtf1\\ansi Hello\\par world}
--x--
""")
    assert body_alternatives(message) == {"rtf": "Hello\nworld"}
    assert rtf_to_text(r"{\rtf1\ansi\u233? one}") == "\xe9 one"


def test_binary_and_detached_signature_have_no_body():
    message = parse(b"""MIME-Version: 1.0
Content-Type: multipart/signed; boundary=x; protocol="application/pkcs7-signature"

--x
Content-Type: text/plain

Signed body
--x
Content-Type: application/pkcs7-signature
Content-Transfer-Encoding: base64

AAEC
--x--
""")
    assert body_alternatives(message) == {"plain": "Signed body"}
    encrypted = parse(b"Content-Type: application/pkcs7-mime\n\nAAEC")
    assert body_alternatives(encrypted) == {}


def test_duplicate_filenames_keep_distinct_part_paths():
    message = parse(b"""MIME-Version: 1.0
Content-Type: multipart/mixed; boundary=x

--x
Content-Disposition: attachment; filename=same.txt
Content-Type: text/plain

one
--x
Content-Disposition: attachment; filename=same.txt
Content-Type: text/plain

two
--x--
""")
    assert [(p.path, p.filename) for p in mail_parts(message) if p.attachment] == [
        ("1.1", "same.txt"), ("1.2", "same.txt")]
    assert body_alternatives(message) == {}


def test_attached_multipart_does_not_supply_parent_body():
    message = parse(b"""MIME-Version: 1.0
Content-Type: multipart/mixed; boundary=outer

--outer
Content-Type: multipart/alternative; boundary=inner
Content-Disposition: attachment; filename=forwarded.mime

--inner
Content-Type: text/plain

Attached plain
--inner
Content-Type: text/html

<p>Attached HTML</p>
--inner--
--outer--
""")
    assert body_alternatives(message) == {}
    assert [p.path for p in mail_parts(message) if p.attachment] == [
        "1.1", "1.1.1", "1.1.2"]


def test_rtf_surrogates_codepage_and_binary_are_bounded():
    assert rtf_to_text(r"{\rtf1\ansi \u55357?\u56832?}") == "\U0001f600"
    assert rtf_to_text(r"{\rtf1\ansi\ansicpg932 \'82\'a0}") == "\u3042"
    assert rtf_to_text(r"{\rtf1\ansi before \bin5 abcde after}") == "before  after"


def test_one_character_email_body_remains_a_page():
    assert split_text_segments(",", min_chars=1) == [","]


def test_richtext_and_enriched_bodies_are_readable():
    richtext = parse(b"Content-Type: text/richtext\n\n<bold>Hello</bold><nl>world")
    assert body_alternatives(richtext) == {"richtext": "Hello\nworld"}
    enriched = parse(b"Content-Type: text/enriched\n\n<italic>Thank you</italic> for <<mail")
    assert body_alternatives(enriched) == {"richtext": "Thank you for <mail"}


def test_clear_signed_pgp_unescapes_dash_and_excludes_signature():
    message = parse(b"""Content-Type: application/pgp; format=mime; x-action=signclear

-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA256

Content-Type: text/plain; charset=us-ascii

- --
Readable text
-----BEGIN PGP SIGNATURE-----
Version: 2.6

signature-bytes
-----END PGP SIGNATURE-----
""")
    assert body_alternatives(message) == {"plain": "--\r\nReadable text"}
    assert [part.path for part in mail_parts(message)] == ["1", "1.signed"]


def test_incomplete_clear_signature_does_not_supply_body():
    message = parse(b"""Content-Type: application/pgp; x-action=signclear

-----BEGIN PGP SIGNED MESSAGE-----

Readable text
-----BEGIN PGP SIGNATURE-----
""")
    assert body_alternatives(message) == {}
