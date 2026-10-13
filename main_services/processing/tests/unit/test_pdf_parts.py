"""Verify source segmentation, durable completion, recovery, and removed-source handling."""

import asyncio
import dataclasses
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ocr_store_fake import FakeOcrStore, CD, COLLECTION
from tasks import ocr_targets
from tasks.ocr_targets import Target, SettingVersion
from tasks.P_admin import ocr_rerun
from tasks.P3_parse_files import pdf_parts as parts, pdf_chain
from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams, FileResult
from tasks.P3_parse_files.workflows import route_stages, excluded_name_kind
from tasks.text_sources import pdf_ocr_extracted_by, parse_pdf_ocr_extracted_by, is_ocr_text


class Store(FakeOcrStore):
    def __init__(self):
        super().__init__()
        self.source = []
        self.manifest = []
        self.needs = []
        self.results = []
        self.defects = set()

    def _answer(self, sql, p):
        h = p.get("hash") or p.get("h")
        hashes = set(h) if isinstance(h, list) else {h}
        if "FROM pdf_parts FINAL" in sql:
            chosen = [row for row in self.source if row["hash"] in hashes]
            if sql.startswith("SELECT first_page"):
                return [(r["first_page"], r["last_page"]) for r in chosen]
            return [(r["part_index"], r["first_page"], r["last_page"], r["s3_path"], r["size_bytes"])
                    for r in chosen]
        if "FROM pdf_ocr_parts FINAL" in sql:
            chosen = [r for r in self.manifest if r["hash"] in hashes and r["engine"] == p["en"] and r["languages"] == p["la"]]
            return [(r["part_index"], r["first_page"], r["last_page"], r["blob_key"], r["size_bytes"],
                     r["page_numbers"], r["page_texts"], r["borrows_source"]) for r in chosen]
        if "FROM ocr_page_needs" in sql:
            chosen = [r for r in self.needs if r["hash"] in hashes]
            if sql.startswith("SELECT page_count"):
                return [(r["page_count"], r["ocr_pages"]) for r in chosen]
            return [(r["hash"], r["page_count"], r["ocr_pages"]) for r in chosen]
        if "FROM pdf_ocr_results FINAL" in sql:
            chosen = [r for r in self.results if r["pdf_hash"] in hashes]
            if "en" in p:
                chosen = [r for r in chosen if r["engine"] == p["en"] and r["languages"] == p["la"]]
            if sql.startswith("SELECT count()"):
                return [(len(chosen),)]
            if sql.startswith("SELECT DISTINCT engine"):
                return [(r["engine"],) for r in chosen if not r["text_complete"]]
            if sql.startswith("SELECT pdf_hash"):
                return [(r["pdf_hash"], r["engine"], r["languages"], r["source_kind"])
                        for r in chosen if r["text_complete"]]
            return [tuple(r[key] for key in ("blob_key", "blob_hash", "page_count", "size_bytes", "run_time_ms",
                                            "source_kind", "form", "part_count", "text_complete")) for r in chosen]
        if "FROM pdfs FINAL" in sql and "defect IS NOT NULL" in sql:
            return [(h,) for h in self.defects if h in hashes]
        return super()._answer(sql, p)

    def source_part(self, first=1, last=2, index=1):
        self.source.append(dict(hash="doc", part_index=index, first_page=first, last_page=last,
                                s3_path="", size_bytes=100))

    def ocr_part(self, first=1, last=2, index=1, texts=None, borrowed=0):
        self.manifest.append(dict(hash="doc", part_index=index, first_page=first, last_page=last,
                                 engine="tesseract", languages="eng", blob_key="derived/result.pdf",
                                 size_bytes=110, page_numbers=list(range(first, last + 1)) if texts is not None else [],
                                 page_texts=texts or [], borrows_source=borrowed))


@pytest.fixture
def store(monkeypatch):
    db = Store()
    db.add_pdf("doc")
    import database.clickhouse as clickhouse
    monkeypatch.setattr(clickhouse, "get_collection_client", db.client)
    return db


@pytest.fixture
def params():
    return StageBatchParams(COLLECTION, CD, "plan", engine="tesseract")


@pytest.mark.parametrize("count,size", [(510,130_000_000),(1020,130_000_000),(1,90_000_000),(100,1000),(201,10)])
def test_ranges_cover_the_source_with_the_shared_soft_size_rule(count,size):
    ranges = parts.source_ranges(count,size)
    assert ranges[0][0] == 1 and ranges[-1][1] == count
    assert all(last - first + 1 <= 100 for first,last in ranges)
    assert all(left[1] + 1 == right[0] for left,right in zip(ranges,ranges[1:]))
    expected = min(100,max(1,count*25_000_000//max(size,1)))
    assert ranges[0][1] == min(count,expected)


@pytest.mark.parametrize("texts", [["", ""], ["a", ""], ["first", "second"]])
def test_variant_completion_follows_durable_text_including_empty(store,params,monkeypatch,texts):
    store.source_part(); store.ocr_part(texts=texts)
    events=[]
    import tasks.P3_parse_files.parse_common as common
    monkeypatch.setattr(common,"insert_text_pages",lambda *args: events.append(("text",args[-1])))
    monkeypatch.setattr(parts,"write_row",lambda *args,**kw: events.append(("result",args[2])))
    parts.finalize_variant(store,params,BatchFile("doc","/unused"),"eng")
    assert events[0] == ("text",list(enumerate(texts,1)))
    assert events[1][1]["text_complete"] == 1
    assert events[1][1]["form"] == "overlay"


def test_interrupted_finalization_keeps_parts_and_repeats_no_builder(store,params,monkeypatch):
    store.source_part(); store.ocr_part(texts=["first","second"])
    import tasks.P3_parse_files.parse_common as common
    attempts=[]
    def text(*args):
        attempts.append(args[-1])
        if len(attempts)==1: raise RuntimeError("storage interruption")
    monkeypatch.setattr(common,"insert_text_pages",text)
    rows=[]; monkeypatch.setattr(parts,"write_row",lambda c,t,row,**kw: rows.append(row))
    with pytest.raises(RuntimeError): parts.finalize_variant(store,params,BatchFile("doc","/unused"),"eng")
    assert not rows and len(store.manifest)==1
    parts.finalize_variant(store,params,BatchFile("doc","/unused"),"eng")
    assert attempts[0]==attempts[1] and rows[0]["text_complete"]==1


def test_missing_parts_cannot_complete_a_variant(store,params,monkeypatch):
    store.source_part(1,2,1);store.source_part(3,4,2);store.ocr_part(texts=["one","two"])
    with pytest.raises(RuntimeError,match="cover every source range"):
        parts.finalize_variant(store,params,BatchFile("doc","/unused"),"eng")


def test_multipart_completion_has_no_stored_join_and_accepts_borrowed_ranges(store,params,monkeypatch):
    store.source_part(1,2,1);store.source_part(3,4,2)
    store.ocr_part(texts=["one","two"]);store.ocr_part(3,4,2,borrowed=1)
    import tasks.P3_parse_files.parse_common as common
    monkeypatch.setattr(common,"insert_text_pages",lambda *args: 2)
    rows=[];monkeypatch.setattr(parts,"write_row",lambda c,t,r,**kw: rows.append(r))
    parts.finalize_variant(store,params,BatchFile("doc","/unused"),"eng")
    assert rows[0]["blob_key"]=="" and rows[0]["part_count"]==2 and rows[0]["page_count"]==4


def test_current_completed_preparation_uses_source_alias_without_reading_file(store,params):
    store.source_part();store.needs.append(dict(hash="doc",page_count=2,ocr_pages=[]))
    outcome=parts.prepare_pdf(params,BatchFile("doc","/does-not-exist"))
    assert outcome["parts"][0]["part_key"]=="" and not outcome["has_ocr_pages"]


def test_preparation_failure_settles_the_dependent_variant(store):
    store.errors.append((CD,"doc","pdf_process",10,1))
    targets={Target("doc","pdf_prepare"):SettingVersion(),Target("doc","pdf","tesseract","eng"):SettingVersion()}
    assert ocr_targets.settled(store,CD,targets,parts_version=True)==set(targets)


@pytest.fixture
def image_pdf_dependency(store, monkeypatch):
    import json
    from tasks import ocr_pdf_client
    from tasks.P3_parse_files import image_loader, image_preview, parse_ocr_pdf

    payloads = {}
    builds = []
    original_query = store.query

    def query(sql, parameters=None):
        if sql.startswith("SELECT languages, raw_json FROM raw_ocr_results"):
            return SimpleNamespace(result_rows=[(language, json.dumps(payload))
                                               for language, payload in payloads.items()])
        if sql.startswith("SELECT reason FROM ocr_skips"):
            return SimpleNamespace(result_rows=[])
        return original_query(sql, parameters)

    def build(**request):
        builds.append(request["languages"])
        return SimpleNamespace(dest_key="derived/image.pdf", blob_hash="output",
                               size_bytes=100, run_time_ms=1)

    monkeypatch.setattr(store, "query", query)
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr(ocr_pdf_client, "build_ocr_pdf", build)
    monkeypatch.setattr(parse_ocr_pdf, "_passes_for", lambda *args: ["eng", "fra"])
    monkeypatch.setattr(image_preview, "read_preview_bytes", lambda *args: b"stored image")
    monkeypatch.setattr(image_loader, "image_dimensions", lambda image: (200, 200))
    monkeypatch.setattr(parts, "store_part", lambda *args, **kwargs: None)
    monkeypatch.setattr(parts, "write_row", lambda client, table, row: store.results.append(row))
    return payloads, builds


def test_missing_image_ocr_defers_without_closing_an_unexplained_target(
        store, params, image_pdf_dependency):
    from tasks.P3_parse_files.image_pdf import make_image_pdf
    from tasks.task_timing import SkippedOutcome

    outcome = make_image_pdf(params, BatchFile("doc", "/unused"))
    assert isinstance(outcome, SkippedOutcome)
    assert outcome.value == "image_ocr_incomplete"
    assert image_pdf_dependency[1] == []
    assert store.skips == [] and store.results == []
    target = Target("doc", "image_pdf", "tesseract", "eng")
    targets = {target: SettingVersion()}
    assert not ocr_targets.settled(store, CD, targets, parts_version=True)
    store.errors.append((CD, "doc", "run_ocr_and_store[tesseract]", 10, 1))
    assert ocr_targets.settled(store, CD, targets, parts_version=True) == {target}


def test_missing_image_ocr_preserves_other_languages_and_recovers_without_rebuilding(
        store, params, image_pdf_dependency):
    from tasks.P3_parse_files.image_pdf import make_image_pdf
    from tasks.task_timing import SkippedOutcome

    payloads, builds = image_pdf_dependency
    payloads["fra"] = {"text": "one two three four five", "words": []}
    assert isinstance(make_image_pdf(params, BatchFile("doc", "/unused")), SkippedOutcome)
    assert builds == ["fra"]
    assert store.results[0]["text_complete"] == 1 and store.skips == []
    payloads["eng"] = payloads["fra"]
    assert make_image_pdf(params, BatchFile("doc", "/unused")) == "image_pdf_complete"
    assert builds == ["fra", "eng"]
    assert {row["languages"] for row in store.results} == {"eng", "fra"}


def test_successful_empty_variant_requires_the_explicit_completion_marker(store):
    row=dict(pdf_hash="doc",engine="tesseract",languages="eng",source_kind="original",text_complete=0)
    store.results.append(row)
    target=Target("doc","pdf","tesseract","eng")
    assert not ocr_targets.settled(store,CD,{target:SettingVersion()},parts_version=True)
    row["text_complete"]=1
    assert ocr_targets.settled(store,CD,{target:SettingVersion()},parts_version=True)=={target}


def test_removed_cached_source_cannot_open_or_execute_new_pdf_work(store,params):
    store.removed.add("doc")
    assert parts.prepare_pdf(params,BatchFile("doc","/does-not-exist")).value=="pdf_source_removed"
    target=Target("doc","pdf","tesseract","eng")
    assert ocr_targets.settled(store,CD,{target:SettingVersion()},parts_version=True)=={target}
    assert parts.live_hashes(store,CD,["doc"])==set()
    store.live.add("duplicate");store.removed.discard("doc")
    assert parts.live_hashes(store,CD,["doc","duplicate"])=={"doc","duplicate"}


@pytest.mark.parametrize("backfill,expected", [(False,False),(True,True)])
def test_all_native_pages_skip_new_variants_but_keep_historical_backfill(backfill,expected):
    calls=[]
    async def stage(name,files,engine=""):
        calls.append(name)
        values={"pdf_metadata_batch":{"page_count":2,"size_bytes":100},
                "pdf_prepare_batch":{"parts":[dict(part_index=1,first_page=1,last_page=2,part_key="",ocr_pages=[])],
                                     "has_ocr_pages":False,"saved_engines":["tesseract"] if backfill else []}}
        return [FileResult(f.item_hash,"step","ok",values.get(name,{})) for f in files]
    asyncio.run(pdf_chain.run_pdf_chain([BatchFile("doc","/unused")],stage))
    assert ("pdf_ocr_finalize_batch" in calls)==expected


def test_ocr_source_names_preserve_both_families():
    value=pdf_ocr_extracted_by("tesseract","eng+ron")
    assert value=="pdfocr_tesseract_eng+ron" and parse_pdf_ocr_extracted_by(value)==("tesseract","eng+ron")
    assert is_ocr_text(value) and is_ocr_text("ocr_easyocr_en")


@pytest.mark.parametrize("names,size,kind", [(["Thumbs.db"],0,"thumbs"),(["._photo.jpg"],0,"appledouble"),
                                           (["~$report.docx"],1023,"office_lock"),(["~$report.docx"],1024,""),
                                           (["Thumbs.db","kept.png"],0,"")])
def test_name_exclusions_require_every_name_and_the_lock_size(names,size,kind):
    assert excluded_name_kind(names,size)==kind


def test_client_preserves_legacy_inline_and_new_selected_page_contract(monkeypatch):
    from tasks import ocr_pdf_client as client
    from database import s3
    payloads=[]
    monkeypatch.setattr(s3,"collection_bucket",lambda collection:"source-bucket")
    def post(endpoints,payload,**kwargs):
        payloads.append(payload)
        return SimpleNamespace(provider="stub",data={"pages":[{"page":2,"text":"OCR only"}]})
    monkeypatch.setattr(client,"post_json",post)
    common=dict(collectionname=COLLECTION,collection_dataset=CD,pdf_hash="doc",engine="tesseract",languages="eng")
    legacy=client.build_ocr_pdf(**common,pdf_b64="legacy")
    selected=client.build_ocr_pdf(**common,source_b64="source",ocr_pages=[],dest_key="derived/part.pdf",bucket="stored-bucket")
    assert payloads[0]["pdf_b64"]=="legacy" and "ocr_pages" not in payloads[0]
    assert payloads[1]["source_b64"]=="source" and payloads[1]["ocr_pages"]==[]
    assert payloads[1]["bucket"]=="stored-bucket" and payloads[1]["dest_key"]=="derived/part.pdf"
    assert legacy.pages==selected.pages==[{"page":2,"text":"OCR only"}]


def test_saved_overlay_backfill_keeps_returned_ocr_text_separate_from_native(store,params,monkeypatch,tmp_path):
    import shutil
    from pathlib import Path
    from database import s3
    import tasks.P3_parse_files.parse_common as common
    source=Path(__file__).parents[1]/"fixtures/tiny/tiny.pdf"
    store.source_part(1,1)
    events=[]
    class S3:
        def fget_object(self,bucket,key,path): shutil.copyfile(source,path)
    monkeypatch.setattr(s3,"get_s3_client",lambda:S3())
    monkeypatch.setattr(s3,"collection_bucket",lambda name:"bucket")
    def write(client,table,row,**kwargs):
        events.append((table,row))
        if table=="pdf_ocr_parts": store.manifest.append(row)
    monkeypatch.setattr(parts,"write_row",write)
    text=[];monkeypatch.setattr(common,"insert_text_pages",lambda *args:text.extend(args[-1]))
    parts.backfill_saved_pdf(store,params,BatchFile("doc",str(source)),"eng",
        dict(blob_key="derived/saved.pdf",blob_hash="h",form="overlay",size_bytes=10,run_time_ms=0),
        returned_pages=[{"page":1,"text":"OCR-only words"}])
    assert text==[(1,"OCR-only words")]
    assert events[-1][1]["text_complete"]==1 and events[-1][1]["form"]=="overlay"


def test_native_pdf_text_opens_an_index_target_without_any_ocr_languages(store,monkeypatch):
    store.text.append((CD,"doc","pdftotext",2,"native words",10))
    pairs=ocr_targets.OcrPairs((),())
    targets,_=ocr_rerun._plan_targets(store,COLLECTION,CD,["doc"],pairs,parts_version=True)
    assert Target("doc","pdf_prepare") in targets and Target("doc","index") in targets
    assert not any(target.stage=="pdf" for target in targets)
    assert ocr_targets.text_pending_index(store,CD,["doc"])==["doc"]


def test_new_error_names_have_matching_recovery_and_outcome_names():
    from tasks.P_admin.rerun_selection import recovery_activity
    from tasks.task_timing import _outcome_name
    for activity,task in [("pdf_prepare","pdf_process"),("make_pdf_preview","make_pdf_preview"),
                          ("make_image_preview","make_image_preview"),("make_image_pdf","make_image_pdf[tesseract]")]:
        assert recovery_activity(task)==activity and _outcome_name(activity,"tesseract")==task


def test_language_purge_expands_cached_image_only_variants(monkeypatch):
    from tasks.P_admin import ocr_languages as language
    from database import clickhouse,manticore
    commands=[]
    class DB:
        def query(self,sql,parameters=None):return SimpleNamespace(result_rows=[("text_content",)])
        def command(self,sql,parameters=None):commands.append((sql,parameters))
    @contextmanager
    def client(name):yield DB()
    monkeypatch.setattr(clickhouse,"get_collection_client",client)
    monkeypatch.setattr(manticore,"list_shard_tables",lambda collection:[])
    params=language.PurgeVariantsParams(COLLECTION,CD,["ocr_tesseract_eng"],[["tesseract","eng"]])
    language.purge_dropped_ocr_variants(params)
    assert commands[0][1]["vs"]==["ocr_tesseract_eng","pdfocr_tesseract_eng"]


@pytest.mark.parametrize("fails",[False,True])
def test_owned_object_deletion_precedes_manifest_deletion_and_preserves_borrowed(fails,monkeypatch):
    from tasks.P_admin import ocr_languages as language
    from database import clickhouse,s3
    events=[]
    class DB:
        def query(self,sql,parameters=None):
            if "FROM pdf_ocr_parts" in sql:
                assert "borrows_source = 0" in sql
                return SimpleNamespace(result_rows=[("derived/owned-part.pdf",)])
            return SimpleNamespace(result_rows=[("doc","derived/whole.pdf")])
        def command(self,sql,parameters=None):events.append(("rows",sql))
    @contextmanager
    def client(name):yield DB()
    class S3:
        def remove_object(self,bucket,key):
            events.append(("object",key))
            if fails:raise RuntimeError("storage unavailable")
    monkeypatch.setattr(clickhouse,"get_collection_client",client)
    monkeypatch.setattr(s3,"get_s3_client",lambda:S3())
    monkeypatch.setattr(s3,"collection_bucket",lambda name:"bucket")
    params=language.PurgeVariantsParams(COLLECTION,CD,["ocr_tesseract_eng"],[["tesseract","eng"]])
    if fails:
        with pytest.raises(RuntimeError):language.delete_orphaned_derived_pdfs(params)
        assert all(kind=="object" for kind,value in events)
    else:
        assert language.delete_orphaned_derived_pdfs(params)==2
        assert [kind for kind,value in events]==["object","object","rows","rows"]
        assert all("borrowed" not in value for kind,value in events if kind=="object")


def test_office_only_language_change_reopens_its_live_plan(store,monkeypatch):
    from tasks.P_admin import ocr_languages as language
    store.plan_hits=[(CD,"office","office-plan")]
    store.file_types=[(CD,"office",name,["application/msword"],[],["doc"],[])
                      for name in ("file","magika","extension")]
    commands=[]
    original=store.query
    def query(sql,parameters=None):
        if sql.startswith("SELECT DISTINCT plan_hash"):
            return SimpleNamespace(result_rows=[("office-plan",)])
        return original(sql,parameters)
    monkeypatch.setattr(store,"query",query)
    monkeypatch.setattr(store,"command",lambda sql,parameters=None:commands.append((sql,parameters)))
    assert language.reopen_plans_for_ocr_change(language.ReopenParams(COLLECTION,CD,["tesseract"]))==1
    assert commands[0][1]["ph"]==["office-plan"]


@pytest.mark.parametrize("characters,width,coverage,kind,selected",[
    (19,128,0,"image",True),(20,128,1,"image",False),(20,129,0.10,"image",True),
    (20,129,0.09,"image",False),(20,129,1,"mask",False)])
def test_page_rule_uses_native_floor_image_floor_and_displayed_coverage(monkeypatch,characters,width,coverage,kind,selected):
    import subprocess
    import math
    ppi=width*72/math.sqrt(max(coverage,0.001)*10_000)
    def run(args,**kwargs):
        output=b"Page 1 size: 100 x 100 pts\n" if args[0]=="pdfinfo" else (
            f"1 0 {kind} {width} {width} rgb 3 8 image no 1 0 {ppi} {ppi}\n".encode())
        return SimpleNamespace(stdout=output,returncode=0)
    monkeypatch.setattr(subprocess,"run",run)
    assert parts.page_needs("source.pdf",1,["a"*characters])==([1] if selected else [])


def test_office_conversion_timeout_stops_the_actual_process_group(monkeypatch,tmp_path):
    import subprocess
    import sys
    from tasks.P3_parse_files import pdf_preview
    processes=[]
    original=subprocess.Popen
    def start(args,**kwargs):
        process=original([sys.executable,"-c","import time; time.sleep(60)"],**kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess,"Popen",start)
    with pytest.raises(subprocess.TimeoutExpired):
        pdf_preview.convert_office("source.docx",str(tmp_path),0)
    assert processes[0].poll() is not None


def test_dataset_purge_deletes_only_new_owned_objects_before_rows(monkeypatch):
    from tasks.P_admin import activities
    from database import clickhouse,s3
    events=[]
    class DB:
        def query(self,sql,parameters=None):
            if sql=="SHOW TABLES":return SimpleNamespace(result_rows=[("pdf_parts",),("pdf_previews",),("pdf_ocr_parts",)])
            if sql.startswith("DESCRIBE"):return SimpleNamespace(result_rows=[("collection_dataset",)])
            if "FROM pdf_parts" in sql:return SimpleNamespace(result_rows=[("s3://bucket/original.pdf",),("s3://bucket/derived/pdf-parts/part.pdf",),("",)])
            if "FROM pdf_previews" in sql:return SimpleNamespace(result_rows=[("s3://bucket/derived/pdf-preview/office.pdf",)])
            assert "borrows_source = 0" in sql
            return SimpleNamespace(result_rows=[("derived/ocr-pdf/owned.pdf",)])
        def command(self,sql,parameters=None):events.append(("rows",sql))
    @contextmanager
    def client(name):yield DB()
    class S3:
        def remove_object(self,bucket,key):events.append(("object",key))
    monkeypatch.setattr(clickhouse,"get_collection_client",client)
    monkeypatch.setattr(s3,"get_s3_client",lambda:S3());monkeypatch.setattr(s3,"collection_bucket",lambda name:"bucket")
    activities.purge_dataset_from_clickhouse(activities.PurgeDatasetParams(COLLECTION,CD))
    assert [kind for kind,value in events]==["object"]*3+["rows"]*3
    assert all(value!="original.pdf" for kind,value in events if kind=="object")


def test_legacy_admin_activity_arguments_keep_only_the_original_target_stages(store,monkeypatch):
    store.add_image("image")
    from tasks import ocr_pdf_client
    monkeypatch.setattr(ocr_pdf_client,"service_configured",lambda:True)
    pairs=ocr_targets.OcrPairs((("tesseract","eng",SettingVersion()),),(("tesseract","eng",SettingVersion()),))
    old,_=ocr_rerun._plan_targets(store,COLLECTION,CD,["image","doc"],pairs)
    current,_=ocr_rerun._plan_targets(store,COLLECTION,CD,["image","doc"],pairs,parts_version=True)
    assert {target.stage for target in old}=={"image","pdf"}
    assert {target.stage for target in current}=={"image","image_pdf","pdf_prepare","pdf"}
    assert not ocr_rerun.RerunOcrParams(COLLECTION,CD,"op").parts_version
    assert not ocr_rerun.OcrRunPlanParams(COLLECTION,CD,"op","plan").parts_version


def test_legacy_multipart_overlay_removes_its_whole_copy_after_parts_reach_storage(store,params,monkeypatch,tmp_path):
    from database import s3
    from pathlib import Path
    import tasks.P3_parse_files.parse_common as common
    source=Path(__file__).parents[1]/"fixtures/tiny/tiny.pdf"
    store.source_part(1,1,1);store.source_part(2,2,2)
    events=[]
    class S3:
        def fget_object(self,bucket,key,path):Path(path).write_bytes(source.read_bytes())
        def fput_object(self,bucket,key,path,**kwargs):events.append(("object",key))
        def remove_object(self,bucket,key):events.append(("remove",key))
    monkeypatch.setattr(s3,"get_s3_client",lambda:S3());monkeypatch.setattr(s3,"collection_bucket",lambda name:"bucket")
    monkeypatch.setattr(parts,"split_pdf",lambda src,dest,first,last:Path(dest).write_bytes(source.read_bytes()))
    monkeypatch.setattr(common,"insert_text_pages",lambda *args:events.append(("text",args[-1])))
    def write(client,table,row,**kw):
        events.append((table,row))
        if table=="pdf_ocr_parts":store.manifest.append(row)
    monkeypatch.setattr(parts,"write_row",write)
    parts.backfill_saved_pdf(store,params,BatchFile("doc",str(source)),"eng",
        dict(blob_key="derived/whole.pdf",blob_hash="whole",form="overlay",size_bytes=10,run_time_ms=0),
        returned_pages=[{"page":1,"text":"one"},{"page":2,"text":"two"}])
    remove=next(i for i,event in enumerate(events) if event[0]=="remove")
    assert all(i<remove for i,event in enumerate(events) if event[0]=="pdf_ocr_parts")
    assert events[-1][0]=="pdf_ocr_results" and events[-1][1]["blob_key"]=="" and events[-1][1]["blob_hash"]==""


def test_missing_part_build_reuses_saved_part_text_and_borrows_unselected_ranges(store,params,monkeypatch):
    from tasks import ocr_pdf_client as client
    from tasks.P3_parse_files import parse_ocr_pdf
    store.source_part(1,2,1);store.source_part(3,4,2)
    store.ocr_part(texts=["one","two"])
    monkeypatch.setattr(client,"service_configured",lambda:True)
    monkeypatch.setattr(client,"engines_for_provider",lambda:["tesseract"])
    monkeypatch.setattr(parse_ocr_pdf,"_passes_for",lambda *args:["eng"])
    monkeypatch.setattr(client,"build_ocr_pdf",lambda **kw:pytest.fail("A stored or unselected part sent an OCR request"))
    rows=[];monkeypatch.setattr(parts,"write_row",lambda c,t,row,**kw:rows.append(row))
    parts.build_part(params,BatchFile("doc","/missing",part_index=1,first_page=1,last_page=2,ocr_pages=[1,2]))
    parts.build_part(params,BatchFile("doc","/missing",part_index=2,first_page=3,last_page=4,ocr_pages=[]))
    assert len(rows)==1 and rows[0]["borrows_source"]==1 and rows[0]["blob_key"]==""


def test_part_request_reads_stored_bucket_and_keeps_collection_output(store, params, monkeypatch):
    from database import s3
    from tasks import ocr_pdf_client as client
    from tasks.P3_parse_files import parse_ocr_pdf
    store.source_part()
    store.source[0]["s3_path"] = "s3://stored-source-bucket/source.pdf"
    monkeypatch.setattr(client, "service_configured", lambda: True)
    monkeypatch.setattr(client, "engines_for_provider", lambda: ["tesseract"])
    monkeypatch.setattr(parse_ocr_pdf, "_passes_for", lambda *args: ["eng"])
    monkeypatch.setattr(s3, "collection_bucket", lambda collection: "owned-output-bucket")
    payloads = []
    def post(endpoints, payload, **kwargs):
        payloads.append(payload)
        return SimpleNamespace(provider="stub", data={"pages": [{"page": 1, "text": "stored OCR"}]})
    monkeypatch.setattr(client, "post_json", post)
    rows = []
    monkeypatch.setattr(parts, "write_row", lambda c, t, row, **kw: rows.append(row))
    parts.build_part(params, BatchFile("doc", "/missing", part_index=1, first_page=1,
        last_page=2, part_key=store.source[0]["s3_path"], ocr_pages=[1]))
    assert payloads[0]["source_bucket"] == "stored-source-bucket"
    assert payloads[0]["bucket"] == "owned-output-bucket"
    assert payloads[0]["source_key"] == "source.pdf"
    assert rows[0]["blob_key"] == payloads[0]["dest_key"]


@pytest.mark.parametrize("activity_name",["pdf_extract_batch","run_ocr_pdf_batch"])
def test_direct_legacy_activity_inputs_cannot_restore_removed_sources(store,params,monkeypatch,activity_name):
    from temporalio.testing import ActivityEnvironment
    from tasks.P3_parse_files import parse_pdf,parse_ocr_pdf
    from tasks import ocr_pdf_client
    store.removed.add("doc")
    monkeypatch.setattr(ocr_pdf_client,"service_configured",lambda:True)
    monkeypatch.setattr(ocr_pdf_client,"engines_for_provider",lambda:["tesseract"])
    monkeypatch.setattr(parse_ocr_pdf,"_passes_for",lambda *args:["eng"])
    monkeypatch.setattr(parse_pdf,"pdf_small_extract_text_and_images",lambda *args:pytest.fail("Removed PDF was extracted"))
    monkeypatch.setattr(ocr_pdf_client,"build_ocr_pdf",lambda **kwargs:pytest.fail("Removed PDF reached the builder"))
    params.files=[BatchFile("doc","/removed",page_count=1)]
    fn=getattr(parse_pdf if activity_name=="pdf_extract_batch" else parse_ocr_pdf,activity_name)
    result=ActivityEnvironment().run(fn,params)
    assert result.results[0].status=="skipped" and result.results[0].value=="pdf_source_removed"
