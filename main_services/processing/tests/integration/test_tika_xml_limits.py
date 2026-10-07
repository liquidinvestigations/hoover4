"""Verify escaped XML text and retained entity controls in the configured Tika server."""

import os

import pytest
import requests

from tasks.P3_parse_files import parse_tika as tika

pytestmark = pytest.mark.skipif(
    not os.environ.get("TIKA_TEST_URL"), reason="Tika test server is not configured")


@pytest.fixture(autouse=True)
def configured_server(monkeypatch):
    endpoint = os.environ["TIKA_TEST_URL"]
    monkeypatch.setenv("TIKA_URL", endpoint)
    version = requests.get(endpoint + "/version", timeout=(2, 10))
    assert version.status_code == 200 and "4.1.0" in version.text


def parse_xml(tmp_path, body):
    path = tmp_path / "xml-limits.xml"
    path.write_text('<?xml version="1.0"?>\n' + body)
    params = tika.RunTikaParams(
        "c", "ds", "h", str(path),
        tika.try_budget_seconds("tika_text_batch", path.stat().st_size),
        mime_types=["application/xml"], file_mime_type="application/xml", file_name=path.name)
    return tika.parse_document(params)


def test_many_escaped_characters_keep_the_complete_text(tmp_path):
    answer = parse_xml(tmp_path, '<root>' + '&amp;' * 250_000 + 'END_XML_MARKER</root>')
    assert answer.error is None
    assert tika.document_type(answer.metadata) == "application/xml"
    assert answer.text.count('&') == 250_000
    assert "END_XML_MARKER" in answer.text


def test_xml_output_limit_keeps_truncated_text(tmp_path):
    answer = parse_xml(tmp_path, '<root>' + '&amp;' * 21_000_000 + 'END_XML_MARKER</root>')
    assert answer.error is None
    assert answer.metadata["tk:exception:write-limit-reached"] == "true"
    assert len(answer.text) == 20_000_000
    assert "END_XML_MARKER" not in answer.text


def test_nested_entity_expansion_remains_limited(tmp_path):
    declarations = ['<!ENTITY a0 "ENTITY_MARKER">']
    for level in range(1, 10):
        declarations.append(f'<!ENTITY a{level} "&a{level-1};&a{level-1};">')
    answer = parse_xml(tmp_path, '<!DOCTYPE root [' + ''.join(declarations) + ']><root>&a9;</root>')
    assert answer.error.type == "TikaParseFailed"
    assert answer.error.non_retryable
    assert "entityExpansionLimit" in answer.metadata["tk:exception:container-exception"]


def test_external_entity_does_not_read_the_server_configuration(tmp_path):
    answer = parse_xml(tmp_path, '''<!DOCTYPE root [<!ENTITY x SYSTEM "file:///tika-config.json">]>
<root>BEFORE&x;AFTER</root>''')
    assert answer.error is None
    assert "BEFOREAFTER" in answer.text
    assert "allowPerRequestConfig" not in answer.text
