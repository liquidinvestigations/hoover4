"""Verify the encoded text rule at content boundaries."""

import pytest
from database.manticore import limit_encoded_runs


@pytest.mark.parametrize("text, expected", [
    ("Evidence\n42\nConclusion\n", "Evidence\n42\nConclusion\n"),
    ("a" * 64 + "\n" + "b" * 64 + "\nEvidence\n", "a" * 64 + "b\nEvidence\n"),
    ("x" * 200 + "!", "x" * 200 + "!"),
    ("value=" + "a" * 201 + "!", "value=" + "a" * 59 + " !"),
    ("".join("a" * 76 + "\r\n" for _ in range(10)) + "Evidence\r\n", "a" * 65 + "\r\nEvidence\r\n"),
    ("PHOTO;ENCODING=b:\n " + "A" * 76 + "\n " + "B" * 76 + "\nFN:Person\n", "PHOTO;ENCODING=b:\n" + "A" * 65 + "\nFN:Person\n"),
    ("-----BEGIN CERTIFICATE-----\n" + "X" * 76 + "\n" + "Y" * 76 + "\n-----END CERTIFICATE-----\n", "-----BEGIN CERTIFICATE-----\n" + "X" * 65 + "\n-----END CERTIFICATE-----\n"),
    ("https://example.org/commit/" + "a" * 40, "https://example.org/commit/" + "a" * 40),
    ("A" * 76 + "\nEvidence\n" + "B" * 76 + "\nConclusion", "A" * 65 + "\nEvidence\n" + "B" * 65 + "\nConclusion"),
    ("a" * 59 + "\nWord\n", "a" * 59 + "\nWord\n"),
    ("x " + "a" * 200 + " y", "x " + "a" * 200 + " y"),
    ("x " + "a" * 201 + " y", "x " + "a" * 65 + "  y"),
])
def test_limits_keep_boundaries_and_are_idempotent(text, expected):
    assert limit_encoded_runs(text) == expected
    assert limit_encoded_runs(expected) == expected
