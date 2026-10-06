"""Verify unfolded card and calendar text without binary property values."""

import pytest

from tasks.P3_parse_files.structured_text import structured_text


@pytest.mark.parametrize("parameter", ["ENCODING=B", "ENCODING=BASE64", "BASE64", "VALUE=BINARY"])
def test_binary_values_are_replaced_in_cards(parameter):
    text = structured_text(f"BEGIN:VCARD\nFN:Contact\nPHOTO;TYPE=JPEG;{parameter}:YWJj\nEND:VCARD\n".encode(), "vcard")
    assert "FN:Contact" in text
    assert "[PHOTO JPEG removed, 3 bytes]" in text
    assert "YWJj" not in text


def test_unindented_base64_and_data_uri_are_removed():
    source = b"BEGIN:VCARD\nX-PICTURE;BASE64:\nYWJj\nZGVm\n\nFN:Contact\nPHOTO:data:image/png;base64,YWJj\nEND:VCARD\n"
    text = structured_text(source, "vcard")
    assert "X-PICTURE;BASE64:[X-PICTURE removed, 6 bytes]" in text
    assert "PHOTO:[PHOTO image/png removed, 3 bytes]" in text
    assert "FN:Contact" in text
    assert "YWJj" not in text


def test_calendar_binary_properties_have_no_markers():
    text = structured_text(b"BEGIN:VCALENDAR\nATTACH;ENCODING=BASE64:YWJj\nSUMMARY:June air\n port Border\nEND:VCALENDAR\n", "ical")
    assert "ATTACH" not in text
    assert "removed" not in text
    assert "June airport Border" in text


def test_quoted_printable_soft_breaks_and_text_escapes_are_decoded():
    text = structured_text(b"NOTE;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:June=20air=\nport\\nBorder\\, Test\n", "vcard")
    assert "June airport\nBorder, Test" in text


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-8", "latin-1"])
def test_card_encoding_and_malformed_lines_remain_readable(encoding):
    text = structured_text("BEGIN:VCARD\nFN:André\ninvalid line\nEND:VCARD\n".encode(encoding), "vcard")
    assert "FN:André" in text
    assert "invalid line" in text
