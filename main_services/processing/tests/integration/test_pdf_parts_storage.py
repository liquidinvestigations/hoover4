"""Verify current PDF manifests and completion against migrated collection storage."""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import shutil
import zipfile

import clickhouse_connect
import pytest

from database import clickhouse as db
from tasks.P3_parse_files import pdf_parts, pdf_preview
from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams

pytestmark = pytest.mark.integration


@pytest.fixture
def storage():
    collection = "pdfparts" + uuid4().hex[:8]
    database = db.COLLECTION_DB_PREFIX + collection
    cluster = db._cluster()
    admin = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
        password=db.CLICKHOUSE_PASS, settings=db.CLIENT_SETTINGS)
    cluster.migrate(database, db.COLLECTION_MIGRATIONS_PATH, cluster_name=None,
                    create_db_if_no_exists=True, multi_statement=True)
    client = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
        password=db.CLICKHOUSE_PASS, database=database, settings=db.CLIENT_SETTINGS)
    try:
        yield collection, client
    finally:
        db.reset_client_pool_for_tests()
        admin.command(f"DROP DATABASE IF EXISTS `{database}`")
        client.close();admin.close()


def live_source(client,dataset,file_hash,size,name):
    client.insert("vfs_files",[[dataset,"",name,file_hash,"test",size]],
                  column_names=["collection_dataset","container_hash","path","hash","user_id","file_size_bytes"])
    client.insert("blobs",[[dataset,file_hash,size,"",1]],
                  column_names=["collection_dataset","blob_hash","blob_size_bytes","s3_path","stored_in_clickhouse"])


def test_preparation_source_alias_and_successful_empty_text_are_durable(storage):
    collection,client=storage
    path=Path(__file__).parents[1]/"fixtures/tiny/tiny.pdf"
    cd="dataset";h="pdf"
    live_source(client,cd,h,path.stat().st_size,"tiny.pdf")
    params=StageBatchParams(collection,cd,"plan",engine="tesseract")
    file=BatchFile(h,str(path),path.stat().st_size)
    prepared=pdf_parts.prepare_pdf(params,file)
    assert prepared["page_count"]==1 and prepared["parts"][0]["part_key"]==""
    assert client.query("SELECT page_id FROM text_content WHERE extracted_by='pdftotext'").result_rows==[(1,)]
    first=prepared["parts"][0]
    part=BatchFile(h,str(path),first["file_size_bytes"],first_page=1,last_page=1,part_index=1)
    pdf_parts.store_part(client,params,part,"eng",key="derived/test-empty.pdf",size=100,pages=[(1,"")])
    pdf_parts.finalize_variant(client,params,file,"eng")
    assert client.query("SELECT text_complete,part_count,source_kind,form FROM pdf_ocr_results FINAL").result_rows==[(1,1,"original","overlay")]
    assert client.query("SELECT count() FROM text_content WHERE startsWith(extracted_by,'pdfocr_')").result_rows==[(0,)]
    assert client.query("EXISTS TABLE pdf_parts_ready").result_rows==[(1,)]
    again=pdf_parts.prepare_pdf(params,BatchFile(h,"/missing-source"))
    assert again["parts"]==prepared["parts"]


def test_office_conversion_and_preparation_preserve_existing_native_identity(storage,monkeypatch,tmp_path):
    collection,client=storage
    path=tmp_path/"document.docx"
    with zipfile.ZipFile(path,"w") as archive:
        archive.writestr("[Content_Types].xml",'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>''')
        archive.writestr("_rels/.rels",'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''')
        archive.writestr("word/document.xml",'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Office preview keeps the original native source identity.</w:t></w:r></w:p></w:body></w:document>''')
    live_source(client,"dataset","office",path.stat().st_size,"document.docx")
    from database import s3
    objects={}
    class S3:
        def fput_object(self,bucket,key,path,**kwargs):objects[bucket,key]=Path(path).read_bytes()
        def fget_object(self,bucket,key,path):Path(path).write_bytes(objects[bucket,key])
    monkeypatch.setattr(s3,"get_s3_client",lambda:S3())
    from tasks.P3_parse_files.parse_common import insert_text_pages
    insert_text_pages(collection,"dataset","office","office_xml",[(1,"Native Office text")])
    params=StageBatchParams(collection,"dataset","plan")
    file=BatchFile("office",str(path),path.stat().st_size,file_names=["document.docx"],source_kind="preview")
    converted=pdf_preview.make_pdf_preview(params,file)
    assert converted["page_count"]==1
    prepared=pdf_parts.prepare_pdf(params,file)
    assert prepared["source_kind"]=="preview"
    assert client.query("SELECT DISTINCT extracted_by FROM text_content").result_rows==[("office_xml",)]


def test_known_pdf_defects_store_normal_metadata_without_a_processing_error(storage,tmp_path):
    import subprocess
    from tasks.P3_parse_files.parse_pdf import PdfMetaParams,pdf_get_metadata_and_store
    collection,client=storage
    source=Path(__file__).parents[1]/"fixtures/tiny/tiny.pdf"
    locked=tmp_path/"locked.pdf"
    subprocess.run(["qpdf","--encrypt","reader","owner","256","--",str(source),str(locked)],check=True,capture_output=True)
    outcome=pdf_get_metadata_and_store(PdfMetaParams(collection,"dataset","locked",str(locked)))
    assert outcome["defect"]=="passworded" and outcome["page_count"]==0
    damaged=tmp_path/"damaged.pdf";damaged.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n")
    outcome=pdf_get_metadata_and_store(PdfMetaParams(collection,"dataset","damaged",str(damaged)))
    assert outcome["defect"]=="damaged" and outcome["page_count"]==0
    assert client.query("SELECT pdf_hash,defect FROM pdfs ORDER BY pdf_hash").result_rows==[("damaged","damaged"),("locked","passworded")]
    assert client.query("SELECT count() FROM processing_errors").result_rows==[(0,)]


def test_partial_and_repeated_member_cleanup_preserve_live_duplicates_and_cached_orphans(storage,monkeypatch):
    from contextlib import contextmanager
    from database import manticore
    from tasks.P_admin.ocr_rerun import remove_pdf_members,RerunOcrParams,_plan_targets
    from tasks import ocr_targets
    from tasks.P6_index_data import activities as index
    collection,client=storage
    client.insert("pdfs",[["dataset","parent",2]],column_names=["collection_dataset","pdf_hash","page_count"])
    client.insert("archives",[["dataset","parent","pdf"]],column_names=["collection_dataset","archive_hash","archive_type"])
    client.insert("vfs_files",[["dataset","parent","one.pdf","orphan","test",10],
                               ["dataset","parent","two.pdf","duplicate","test",10],
                               ["dataset","","kept.pdf","duplicate","test",10]],
                  column_names=["collection_dataset","container_hash","path","hash","user_id","file_size_bytes"])
    client.insert("index_state",[["dataset","orphan","shard"],["dataset","duplicate","shard"]],
                  column_names=["collection_dataset","file_hash","shard_name"])
    client.insert("pdf_ocr_results",[["dataset","orphan","tesseract","eng","derived/cached.pdf"]],
                  column_names=["collection_dataset","pdf_hash","engine","languages","blob_key"])
    indexed={"orphan","duplicate"};failures=[True]
    class Search:
        def cursor(self):return self
        def execute(self,sql,values):
            if failures and failures.pop():raise RuntimeError("interrupted cleanup")
            indexed.difference_update(values[1:])
        def commit(self):pass
    @contextmanager
    def search(table):yield Search()
    monkeypatch.setattr(manticore,"client_for_table",search)
    monkeypatch.setattr(manticore,"list_shard_tables",lambda collection:["pages"])
    monkeypatch.setattr(manticore,"vfs_table_name",lambda collection:"vfs")
    monkeypatch.setattr(index,"build_vfs_nodes",lambda params:None)
    monkeypatch.setattr(index,"index_vfs_structure",lambda params:None)
    params=RerunOcrParams(collection,"dataset","op",parts_version=True)
    with pytest.raises(RuntimeError,match="interrupted cleanup"):remove_pdf_members(params)
    assert client.query("SELECT count() FROM archives").result_rows==[(0,)]
    result=remove_pdf_members(params)
    assert result["paths"]==0 and result["deindexed"]==1
    assert indexed=={"duplicate"}
    assert client.query("SELECT file_hash FROM index_state").result_rows==[("duplicate",)]
    assert client.query("SELECT count() FROM pdf_ocr_results").result_rows==[(1,)]
    assert _plan_targets(client,collection,"dataset",["orphan"],ocr_targets.OcrPairs((),()),parts_version=True)==({},[])
    assert remove_pdf_members(params)=={"paths":0,"deindexed":0}
