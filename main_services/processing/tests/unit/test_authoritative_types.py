"""Verify authoritative routing and bounded filename inputs."""

import json
import pytest
from temporalio.converter import default

from tasks.P3_parse_files.content_types import sniff_authoritative
from tasks.P3_parse_files.file_names import bounded_file_names
from tasks.P3_parse_files.table_formats import table_reader_for
from tasks.P3_parse_files.workflows import combine_detector_results, route_stages
from tasks.P6_index_data.canonical_file_type import resolve_canonical
from tasks.P3_parse_files.table_text import TableText
from tasks.P3_parse_files.table_readers import RawCell
from tasks.payload_guard import payload_size
from tasks.P2_execute_plan.activities import DownloadPlanFilesParams
from tasks.P2_execute_plan.workflows import ProcessItemsBatchedParams, PLAN_GROUP_SIZE, MAX_PLAN_DRIVERS


@pytest.mark.parametrize("body,name,expected", [
    (b"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Person\r\nEND:VCARD", "card.eml", "text/vcard"),
    (b"\xef\xbb\xbfbegin:vcard\nversion:4.0\nend:vcard", "card", "text/vcard"),
    ("BEGIN:VCARD\nVERSION:2.1\nEND:VCARD".encode("utf-16"), "card.eml", "text/vcard"),
    (b"##fileformat=VCFv4.3\n#CHROM\tPOS\tID\n", "genome.vcf", ""),
    (b"SQLite format 3\x00", "database.eml", "application/vnd.sqlite3"),
    (b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"/>', "sheet.txt", "application/vnd.ms-spreadsheetml"),
    ('<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"/>'.encode("utf-16"), "sheet.xml", "application/vnd.ms-spreadsheetml"),
    (b"<html><body><table><tr><td>1</td></tr></table></body></html>", "sheet.xls", "application/x-hoover-html-table"),
    (b"<html><body><p>Prose</p><table><tr><td>1</td></tr></table></body></html>", "prose.xls", ""),
])
def test_content_sniff(tmp_path, body, name, expected):
    path = tmp_path / "hash"
    path.write_bytes(body)
    assert sniff_authoritative(str(path), [name]) == expected


def result(mimes, coarse=()):
    return {"mime_types": list(mimes), "coarse_types": list(coarse)}


def test_card_named_eml_has_only_text_route():
    combined = combine_detector_results([
        result(["text/plain"], ["text"]), result(["text/csv"], ["text"]),
        result(["message/rfc822"], ["email"]), result(["text/vcard"], ["text"]),
    ])
    assert route_stages(combined) == ["text"]
    assert combined["authoritative_types"] == ["text/vcard"]
    canonical = resolve_canonical({"extension": ["message/rfc822"], "content_sniff": ["text/vcard"]}, set())
    assert (canonical.file_type, canonical.mime_type, canonical.decided_by) == ("text", "text/vcard", "content_sniff_type")


def test_genomics_name_does_not_supply_card_type():
    combined = combine_detector_results([result(["text/plain"], ["text"]), result(["text/plain"], ["text"]),
                                         result(["text/vcard"], ["text"]), result([])])
    assert "text/vcard" not in combined["mime_types"]
    assert combined["authoritative_types"] == []


def test_magika_alone_does_not_select_table_or_specific_text():
    combined = combine_detector_results([result(["text/plain"], ["text"]), result(["text/csv"], ["text"]),
                                         result([]), result([])])
    assert route_stages(combined) == ["text"]
    canonical = resolve_canonical({"file": ["text/plain"], "magika": ["text/x-python"]}, set())
    assert canonical.mime_type == "text/plain"


def test_csv_named_xls_uses_delimited_reader():
    combined = combine_detector_results([result(["text/plain"], ["text"]), result([]),
        result(["application/vnd.ms-excel"], ["xls"]), result(["text/csv"], ["text"])])
    assert "application/vnd.ms-excel" not in combined["mime_types"]
    assert route_stages(combined) == ["text", "table"]
    assert table_reader_for(combined["mime_types"], "input.xls", content_type="text/plain") == "csv"


def test_text_message_named_msg_takes_the_email_route():
    combined = combine_detector_results([
        result(["text/plain"], ["text"]), result(["message/rfc822"], ["email"]),
        result(["application/vnd.ms-outlook"], ["email"]), result([]),
    ])
    assert "application/vnd.ms-outlook" not in combined["mime_types"]
    assert route_stages(combined) == ["email", "text"]
    canonical = resolve_canonical({"file": ["text/plain"], "magika": ["message/rfc822"],
                                   "extension": ["application/vnd.ms-outlook"]}, {"email"})
    assert canonical.mime_type == "message/rfc822"


def test_binary_msg_keeps_the_mail_container_route():
    combined = combine_detector_results([
        result(["application/vnd.ms-outlook"], ["email"]), result(["application/vnd.ms-outlook"], ["email"]),
        result(["application/vnd.ms-outlook"], ["email"]), result([]),
    ])
    assert route_stages(combined) == ["archive"]


@pytest.mark.parametrize("stem", ['a', '"', '\\', 'é', '文', '😀', '\x01', '\n'])
def test_named_plan_payloads_keep_the_guard_limits(stem):
    names = bounded_file_names([stem * 255 + extension for extension in ['.eml', '.vcf', '.txt', '.csv']])
    assert len(names) <= 4 and len(json.dumps(names).encode()) <= 120
    assert names[0].endswith('.eml')
    collection = 'c' * 48
    dataset = collection + '_' + 'd' * 48
    items = [{"item_hash": f"{i:064x}", "file_size_bytes": 123456789,
              "s3_url": f"s3://hoover4-c-{collection}/{dataset}/{i:064x}", "file_names": names}
             for i in range(1000)]
    download = DownloadPlanFilesParams(collection, dataset, 'f' * 40,
        [{k: v for k, v in item.items() if k != 'file_names'} for item in items], '/tmp/hoover4-processing')
    converter = default().payload_converter
    size = lambda value: payload_size(converter.to_payloads([value])[0])
    assert size(download) < 350000
    groups = [ProcessItemsBatchedParams(collection, dataset, 'f' * 40,
        f'/tmp/hoover4-processing/{dataset}/' + 'f' * 40, items[i:i + PLAN_GROUP_SIZE], 'o' * 36)
        for i in range(0, 1000, PLAN_GROUP_SIZE)]
    assert sum(size(group) for group in groups[:MAX_PLAN_DRIVERS]) < 400000


def test_filename_extensions_are_distinct_and_retained():
    assert bounded_file_names(['one.txt', 'two.txt', 'three.csv', 'four.xls', 'five.pdf']) == ['one.txt', 'three.csv', 'four.xls', 'five.pdf']
    assert bounded_file_names(['name.' + 'x' * 17]) == []


def test_table_text_omits_blobs_and_bounds_unicode_segments():
    text = TableText(max_characters=80, segment_bytes=16)
    text.add(0, "Contacts", RawCell(1, 1, 'text', 'name'), 'name')
    text.add(0, "Contacts", RawCell(2, 1, 'text', '漢' * 100), '漢' * 100)
    text.add(0, "Contacts", RawCell(2, 2, 'text', '[BLOB 5 bytes]', is_blob=True), '[BLOB 5 bytes]')
    pages = text.pages()
    joined = ''.join(page for _, page in pages)
    assert joined.startswith('[Contacts]\n1\tname\n2\t')
    assert 'BLOB' not in joined and len(joined) == 80 and text.truncated
    assert all(len(page.encode()) <= 16 for _, page in pages)
