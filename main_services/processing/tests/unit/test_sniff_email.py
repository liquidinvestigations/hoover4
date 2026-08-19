"""The email content sniff, and the three real files that shaped it.

Each correction case below is named after the file that forced it. They are pinned by
hand-written bytes rather than by reading the fixture, so the test still means something
on a checkout that has not fetched the corpora — the corpus-wide numbers are the
integration gate's job.
"""

from pathlib import Path

import pytest

from tasks.P3_parse_files.sniff_email import (
    MBOX_MINIMUM_EMAILS,
    MIME_EMLX,
    MIME_MBOX,
    MIME_RFC822,
    message_offset,
    should_check_email,
    sniff_email,
    sniff_email_path,
    strip_email_envelope,
)

MIXED_CORPUS = Path("/testdata/hoover-testdata/data")


def test_plain_rfc822_is_accepted():
    data = (
        b"Message-ID: <32592306.1075856435817.JavaMail.evans@thyme>\n"
        b"Date: Thu, 3 May 2001 02:32:00 -0700 (PDT)\n"
        b"From: vince.kaminski@enron.com\n"
        b"Subject: Re: the model\n"
        b"\n"
        b"body text\n"
    )
    sniff = sniff_email(data)
    assert sniff is not None
    assert sniff.mime_type == MIME_RFC822
    assert sniff.emlx_prefix_bytes == 0
    assert "Message-Id" in sniff.headers


def test_domainkey_signature_with_no_space_after_colon():
    """`eml-8-double-encoded` and `eml-2-attachment`: `DomainKey-Signature:a=rsa-sha1;`.

    RFC 5322 permits zero whitespace after the colon. A `^Name:[ \\t]` regex rejects the
    line, spends the junk budget on it, and takes four real fixtures with it.
    """
    data = (
        b"DomainKey-Signature:a=rsa-sha1; q=dns; c=nofws;\n"
        b"Received: from mail.example.com by mx.example.net\n"
        b"From: sender@example.com\n"
        b"To: rcpt@example.net\n"
        b"\n"
        b"body\n"
    )
    sniff = sniff_email(data)
    assert sniff is not None
    assert sniff.mime_type == MIME_RFC822


def test_with_bom_eml():
    """`eml-bom/with-bom.eml`: a UTF-8 BOM ahead of the first header."""
    data = (
        b"\xef\xbb\xbf"
        b"Delivered-To: someone@example.com\n"
        b"Received: by 10.0.0.1 with SMTP id x\n"
        b"From: sender@example.com\n"
        b"Date: Mon, 1 Jan 2018 00:00:00 +0000\n"
        b"\n"
        b"body\n"
    )
    assert message_offset(data) == 3
    assert strip_email_envelope(data).startswith(b"Delivered-To:")
    sniff = sniff_email(data)
    assert sniff is not None
    assert sniff.mime_type == MIME_RFC822


def test_calendar_3_bare_lf_inside_a_header_value():
    """`enron-kaminski-v/calendar/3.`: a `Subject:` value carrying a bare LF.

    The next line is neither a header nor a folded continuation. Two enron files are lost
    without the bounded junk tolerance, and both are perfectly good mail.
    """
    data = (
        b"Message-ID: <1234.JavaMail.evans@thyme>\n"
        b"Date: Tue, 5 Jun 2001 09:00:00 -0700 (PDT)\n"
        b"Subject: Meeting\n"
        b"Room 1234\n"
        b"From: vince.kaminski@enron.com\n"
        b"\n"
        b"body\n"
    )
    sniff = sniff_email(data)
    assert sniff is not None
    assert sniff.mime_type == MIME_RFC822


def test_junk_tolerance_is_bounded():
    """Four unparseable lines is prose, not a malformed header block."""
    data = (
        b"Message-ID: <x@y>\n"
        b"Date: Tue, 5 Jun 2001 09:00:00 -0700\n"
        b"one\ntwo\nthree\nfour\n"
        b"\n"
    )
    assert sniff_email(data) is None


def test_emlx_prefix_offset_is_reported_and_strippable():
    """Apple `.emlx`: a decimal byte count on its own first line."""
    message = (
        b"Return-Path: <sender@example.com>\n"
        b"From: sender@example.com\n"
        b"Subject: hi\n"
        b"\n"
        b"body\n"
    )
    data = str(len(message)).encode() + b"\n" + message
    sniff = sniff_email(data)
    assert sniff is not None
    assert sniff.mime_type == MIME_EMLX
    assert sniff.emlx_prefix_bytes == len(str(len(message))) + 1
    assert strip_email_envelope(data) == message


def test_mbox_threshold():
    """`MBOX_MINIMUM_EMAILS` complete cycles make it a spool, two do not."""
    one = (
        b"From sender@example.com Mon Jan  1 00:00:00 2018\n"
        b"From: sender@example.com\n"
        b"Date: Mon, 1 Jan 2018 00:00:00 +0000\n"
        b"Subject: hi\n"
        b"\n"
        b"body\n"
    )
    assert sniff_email(one * (MBOX_MINIMUM_EMAILS - 1)).mime_type == MIME_RFC822
    assert sniff_email(one * MBOX_MINIMUM_EMAILS).mime_type == MIME_MBOX


def test_two_known_headers_without_a_strong_one_are_not_enough():
    """A Debian control file has `Description:` and `Source:` and is not mail.

    The acceptance rule needs a strong header or `From` and `Date` together, which is the
    clause that keeps the false-positive count at zero on the mixed corpus.
    """
    data = b"Subject: notes\nTo: whoever reads this\n\nnot an email\n"
    assert sniff_email(data) is None


def test_the_cheap_gate():
    assert should_check_email(["text/plain"])
    assert should_check_email([])
    assert should_check_email(["application/octet-stream"])
    assert should_check_email([], magic_output="multipart/mixed")
    assert not should_check_email(["application/pdf"])
    assert not should_check_email(["image/png", "application/zip"])


#: Ten files from the mixed corpus that are emphatically not email. Named rather than
#: globbed so a corpus reshuffle fails loudly instead of quietly testing nothing.
NEGATIVE_FILES = [
    "no-extension/file_docx",
    "no-extension/file_pdf",
    "no-extension/file_zip",
    "no-extension/file_7z",
    "no-extension/file_html",
    "no-extension/file_json",
    "no-extension/file_jpg",
    "no-extension/file_text",
    "words/usr-share-dict-words.txt",
    "disk-files/archives/make-archives.sh",
]


@pytest.mark.skipif(not MIXED_CORPUS.is_dir(), reason="mixed corpus not fetched")
def test_negative_set_from_the_mixed_corpus():
    checked = 0
    for name in NEGATIVE_FILES:
        path = MIXED_CORPUS / name
        if not path.is_file():
            continue
        checked += 1
        assert sniff_email_path(str(path)) is None, f"{name} sniffed as email"
    assert checked >= 5, (
        "fewer than five of the named negative files exist; the corpus moved and this "
        "test is no longer testing anything"
    )
