"""Execute captured legacy OCR activity inputs against the current activity implementation."""

import asyncio
import base64
import dataclasses
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.protobuf.json_format import ParseDict
from temporalio.api.common.v1 import Payloads
from temporalio.converter import DataConverter
from temporalio.testing import ActivityEnvironment

from test_pdf_parts import Store
from tasks.P3_parse_files.batch_runner import StageBatchParams
from tasks.P3_parse_files import parse_ocr_pdf, pdf_parts
from tasks import ocr_pdf_client

ARGUMENTS = os.getenv("HOOVER4_LEGACY_ACTIVITY_ARGUMENTS", "")


def _captured():
    if not ARGUMENTS:
        return []
    return [entry for entry in json.loads(Path(ARGUMENTS).read_text()) if entry["activity"]=="run_ocr_pdf_batch"]


@pytest.mark.skipif(not ARGUMENTS,reason="Set HOOVER4_LEGACY_ACTIVITY_ARGUMENTS to captured arguments")
@pytest.mark.parametrize("entry",_captured(),ids=lambda e:e["workflow_id"][-12:]+":"+e["event_id"])
def test_captured_whole_file_contract_executes_and_stores_ocr_only_text(entry,monkeypatch):
    from database import clickhouse,s3
    import tasks.P3_parse_files.parse_common as common
    payloads=ParseDict(entry["arguments"],Payloads())
    decoded=asyncio.run(DataConverter.default.decode(payloads.payloads,[StageBatchParams]))[0]
    assert all(file.first_page==0 and file.last_page==0 for file in decoded.files)
    if not decoded.files:
        return
    source=Path(__file__).parents[1]/"fixtures/tiny/tiny.pdf"
    file=dataclasses.replace(decoded.files[0],item_hash="doc",file_path=str(source))
    params=dataclasses.replace(decoded,files=[file],collectionname="c",collection_dataset="c_ds",engine="tesseract")
    db=Store();db.add_pdf("doc");db.source_part(1,1);db.needs.append(dict(hash="doc",page_count=1,ocr_pages=[1]))
    monkeypatch.setattr(clickhouse,"get_collection_client",db.client)
    monkeypatch.setattr(parse_ocr_pdf,"_passes_for",lambda *args:["eng"])
    monkeypatch.setattr(ocr_pdf_client,"service_configured",lambda:True)
    monkeypatch.setattr(ocr_pdf_client,"engines_for_provider",lambda:["tesseract"])
    monkeypatch.setattr(ocr_pdf_client,"build_ocr_pdf",lambda **kwargs:ocr_pdf_client.OcrPdfOutcome(
        "derived/legacy.pdf","hash",1,1,100,"tesseract","eng",1,"stub",[{"page":1,"text":"OCR-only"}]))
    class S3:
        def fget_object(self,bucket,key,path):shutil.copyfile(source,path)
    monkeypatch.setattr(s3,"get_s3_client",lambda:S3());monkeypatch.setattr(s3,"collection_bucket",lambda name:"bucket")
    writes=[]
    def write(client,table,row,**kwargs):
        writes.append((table,row))
        if table=="pdf_ocr_parts":db.manifest.append(row)
    monkeypatch.setattr(pdf_parts,"write_row",write)
    text=[];monkeypatch.setattr(common,"insert_text_pages",lambda *args:text.extend(args[-1]))
    result=ActivityEnvironment().run(parse_ocr_pdf.run_ocr_pdf_batch,params)
    assert result.results[0].status=="ok" and result.results[0].value=="ocr_pdf_ok_1_variants"
    assert text==[(1,"OCR-only")]
    assert writes[-1][1]["form"]=="overlay" and writes[-1][1]["text_complete"]==1


@pytest.mark.skipif(not ARGUMENTS,reason="Set HOOVER4_LEGACY_ACTIVITY_ARGUMENTS to captured arguments")
@pytest.mark.parametrize("entry",[e for e in json.loads(Path(ARGUMENTS).read_text()) if e["activity"]=="pdf_extract_batch"] if ARGUMENTS else [],ids=lambda e:e["workflow_id"][-12:]+":"+e["event_id"])
def test_captured_pdf_extraction_contract_still_executes(entry,monkeypatch,tmp_path):
    from tasks.P3_parse_files import parse_pdf,temp_dirs
    payloads=ParseDict(entry["arguments"],Payloads())
    decoded=asyncio.run(DataConverter.default.decode(payloads.payloads,[StageBatchParams]))[0]
    if not decoded.files:return
    source=Path(__file__).parents[1]/"fixtures/tiny/tiny.pdf"
    file=dataclasses.replace(decoded.files[0],file_path=str(source),page_count=1,pdf_size_bytes=source.stat().st_size)
    params=dataclasses.replace(decoded,files=[file])
    monkeypatch.setattr(pdf_parts,"live_hashes",lambda client,dataset,hashes:set(hashes))
    from contextlib import contextmanager
    from database import clickhouse
    @contextmanager
    def collection(name):yield object()
    monkeypatch.setattr(clickhouse,"get_collection_client",collection)
    folder=tmp_path/"legacy";folder.mkdir()
    monkeypatch.setattr(temp_dirs,"make_temp_dir",lambda *args:str(folder))
    stored=[];monkeypatch.setattr(parse_pdf,"_insert_pdf_text_pages",lambda *args:stored.extend(args[-1]))
    monkeypatch.setattr(parse_pdf,"record_archive_container",lambda params:None)
    result=ActivityEnvironment().run(parse_pdf.pdf_extract_batch,params)
    assert result.results[0].status=="ok" and stored
    assert "member_count" in result.results[0].value
