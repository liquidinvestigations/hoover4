"""A table and NER update settle in one durable operation after worker replacement."""
import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from temporalio import activity,workflow
from temporalio.client import Client
from temporalio.worker import Worker,Replayer
from database import clickhouse,processing_updates
from tasks.P_admin.updates import activities as updates,entities,registry,selectors,table_receipts
from tasks.P_admin.updates.params import RunUpdateParams,UpdateSnapshotResult,StepSnapshotParams,TablePlansParams
from tasks.P_admin.updates.workflows import RunProcessingUpdate,UpdateDatasetEntities
from tasks.P4_extract_entities.activities import extract_entities_for_hashes
from tasks.P4_extract_entities import activities as ner
from tasks.P4_extract_entities.params import ExtractEntitiesParams
from tasks.run_worker import sandboxed_runner
from tasks.temporal_readiness import TEMPORAL_ADDRESS
from .test_archive_and_index_publication import search_collection
from .test_table_publication_receipts import collection

pytestmark=pytest.mark.integration


@workflow.defn(name="UpdateDatasetTables")
class TableAdapter:
    @workflow.run
    async def run(self,params:TablePlansParams)->int:
        await workflow.execute_activity("publish_changed_table",params,start_to_close_timeout=timedelta(minutes=1))
        return 1


def test_changed_table_then_entities_settle_after_unchanged_worker_restart(search_collection,tmp_path,monkeypatch):
    name=search_collection
    dataset=name+"_documents"
    operation="entity-table-"+uuid.uuid4().hex
    path=tmp_path/"source.csv"
    path.write_text("Name,Count\nCurrent Person,10\n")
    monkeypatch.setenv("NER_URL","http://ner-fixture.invalid")
    monkeypatch.setenv("EMBEDDINGS_URL","")
    from tasks.P_admin.updates import workflows
    monkeypatch.setattr(workflows,"dataset_search_attributes",lambda _dataset:{})
    calls=[]
    def infer(texts):
        calls.append(texts)
        return [{"PER":["Current Person"],"ORG":[],"LOC":[],"MISC":[]} for _ in texts],"ner-gpu-xlmr"
    monkeypatch.setattr(ner,"extract_ner_from_texts",infer)
    with clickhouse.get_collection_client(name) as stored:
        stored.insert("vfs_files",[[dataset,"","/source.csv","source"]],column_names=["collection_dataset","container_hash","path","hash"])
        stored.insert("table_documents",[[dataset,"source",6,"ok",1]],column_names=["collection_dataset","hash","reader_version","status","generation"])
        stored.insert("text_content",[[dataset,"source","table_text",1,"Earlier table text",18,1]],column_names=["collection_dataset","file_hash","extracted_by","page_id","text","text_bytes","version"])
        stored.insert("manticore_shard_assignments",[[dataset,"source",name+"_1"]],column_names=["collection_dataset","file_hash","shard_name"])
    @activity.defn(name="snapshot_processing_update")
    async def snapshot(params:RunUpdateParams)->UpdateSnapshotResult:
        result=[]
        ctx=selectors.ScopeContext("dataset",dataset,name)
        with clickhouse.get_collection_client(name) as stored:
            for step in registry.steps_of("dataset"):
                if step.step_id in params.steps:
                    key,target=selectors.target_key(step,ctx)
                    wanted=registry.desired(step,key)
                    selection=selectors.select(step,ctx,stored,target)
                    result.append(StepSnapshotParams(step.step_id,wanted.fingerprint,json.dumps(wanted.detail()),selection.count))
        assert [step.step_id for step in result]==["tables","entities"]
        return UpdateSnapshotResult(result)
    @activity.defn(name="report_update_progress")
    async def progress(params:dict)->None:
        pass
    @activity.defn(name="refresh_update_checks")
    async def refresh(params:RunUpdateParams)->int:
        return 0
    @activity.defn(name="publish_changed_table")
    def publish(params:TablePlansParams)->None:
        from tasks.P3_parse_files.parse_table import parse_table_and_store,ParseTableParams
        from tasks.P6_index_data.activities import index_text_pages_with_receipts,index_entity_terms
        from tasks.P6_index_data.params import IndexShardParams,BuildVfsNodesParams
        from tasks.red_flags import text_digest
        result=parse_table_and_store(ParseTableParams(name,dataset,"source",str(path),900,mime_types=["text/csv"],file_names=["source.csv"]))
        assert result["status"]=="ok"
        with clickhouse.get_collection_client(name) as stored:
            rows=stored.query("SELECT page_id,argMax(text,version),max(version) FROM text_content WHERE collection_dataset={cd:String} AND extracted_by='table_text' GROUP BY page_id",parameters={"cd":dataset}).result_rows
            for page,text,version in rows:
                stored.insert("signal_scanned",[[dataset,"source","table_text",page,"fixture",version,text_digest(text),version]],column_names=["collection_dataset","file_hash","extracted_by","page_id","signal_set_version","text_version","text_digest","scan_version"])
                stored.insert("regex_scanned",[[dataset,"source","table_text",page,1,len(text)]],column_names=["collection_dataset","file_hash","extracted_by","page_id","rule_set_version","text_bytes"])
        extract_entities_for_hashes(ExtractEntitiesParams(name,dataset,"table-fixture",["source"],operation))
        index_text_pages_with_receipts(IndexShardParams(name,dataset,"table-fixture",name+"_1",["source"]))
        index_entity_terms(BuildVfsNodesParams(name,dataset))
        with clickhouse.get_collection_client(name) as stored:
            generation=stored.query("SELECT generation FROM table_documents FINAL WHERE collection_dataset={cd:String}",parameters={"cd":dataset}).result_rows[0][0]
            table_receipts.write_receipts(stored,table_receipts.TableReceiptParams(name,dataset,operation,["source"],list(table_receipts.STAGES),{"source":generation}))
    async def run():
        client=await Client.connect(TEMPORAL_ADDRESS)
        with ThreadPoolExecutor(max_workers=4) as pool:
            def common():
                return Worker(client,task_queue="processing-common-queue",workflows=[RunProcessingUpdate,UpdateDatasetEntities,TableAdapter],
                    activities=[snapshot,updates.begin_update_step,updates.finish_update_step,updates.settle_update_step,progress,refresh,entities.list_entity_update_hashes,publish],activity_executor=pool,workflow_runner=sandboxed_runner())
            async with Worker(client,task_queue="processing-nlp-queue",activities=[extract_entities_for_hashes],activity_executor=pool):
                first=common();task=asyncio.create_task(first.run())
                handle=await client.start_workflow(RunProcessingUpdate.run,RunUpdateParams(operation,"dataset",name,dataset,["entities","tables"]),id=operation,task_queue="processing-common-queue",execution_timeout=timedelta(minutes=3))
                for _ in range(600):
                    try:
                        child=await client.get_workflow_handle("update-entities-"+operation).describe()
                        if any(p.activity_type.name=="finish_entity_update" for p in child.raw_description.pending_activities):
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(.05)
                else:
                    pytest.fail("Entity indexing did not reach its durable restart boundary")
                await first.shutdown();await task
                async with common(),Worker(client,task_queue="processing-indexing-queue",activities=[entities.finish_entity_update],activity_executor=pool):
                    assert await handle.result()=={"steps":["tables","entities"]}
            history=await handle.fetch_history()
            await Replayer(workflows=[RunProcessingUpdate],workflow_runner=sandboxed_runner()).replay_workflow(history)
        with clickhouse.get_collection_client(name) as stored:
            ctx=selectors.ScopeContext("dataset",dataset,name)
            assert selectors.select_tables(stored,ctx).count==0
            assert selectors.select(registry.STEPS_BY_ID["entities"],ctx,stored).count==0
        applied=processing_updates.stored_applied([dataset])
        assert applied[dataset,"tables"]["op_id"]==operation
        assert applied[dataset,"entities"]["op_id"]==operation
        assert len(calls)==1
    asyncio.run(run())
