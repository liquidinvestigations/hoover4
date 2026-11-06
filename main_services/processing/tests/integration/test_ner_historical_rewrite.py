"""Verify historical NER replacement and dependent search settlement in isolated storage."""

import hashlib

import pytest
from database import clickhouse, manticore
from tasks.P4_extract_entities import activities
from tasks.P4_extract_entities.params import ExtractEntitiesParams
from tasks.P_admin.updates import entities, selectors, registry
from .test_archive_and_index_publication import search_collection
from .test_table_publication_receipts import collection

pytestmark = pytest.mark.integration


def seed(name):
    with clickhouse.get_collection_client(name) as client:
        client.insert("vfs_files", [["dataset","","/source.txt","source"]], column_names=["collection_dataset","container_hash","path","hash"])
        for page in [1,2]:
            text = f"Full page {page} with a person near its end."
            client.insert("text_content", [["dataset","source","raw_text",page,text,len(text),1]],
                column_names=["collection_dataset","file_hash","extracted_by","page_id","text","text_bytes","version"])
            from tasks.red_flags import text_digest
            client.insert("signal_scanned", [["dataset","source","raw_text",page,"fixture",1,text_digest(text),1]],
                column_names=["collection_dataset","file_hash","extracted_by","page_id","signal_set_version","text_version","text_digest","scan_version"])
            client.insert("nlp_processed", [["dataset","source","raw_text",page,"ner-gpu-xlmr",len(text)]],
                column_names=["collection_dataset","file_hash","extracted_by","page_id","nlp_model","text_bytes"])
        client.insert("entity_hit", [["dataset","source","raw_text",1,"ner-gpu-xlmr","PER",["Earlier Person"]],
                                     ["dataset","source","raw_text",1,"ner-spacy-xx","ORG",["CPU Company"]],
                                     ["other","source","raw_text",1,"ner-gpu-xlmr","PER",["Other Dataset"]]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","nlp_model","entity_type","entity_values"])
        text="An unchanged alternate variant."
        client.insert("text_content",[["dataset","source","alternate",1,text,len(text),1]],column_names=["collection_dataset","file_hash","extracted_by","page_id","text","text_bytes","version"])
        client.insert("nlp_processed",[["dataset","source","alternate",1,"ner-gpu-xlmr",len(text),2,1,hashlib.sha256(text.encode()).hexdigest()]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","nlp_model","text_bytes","stage_version","text_version","text_digest"])
        client.insert("entity_hit",[["dataset","source","alternate",1,"ner-gpu-xlmr",kind,["Variant Person"] if kind=="PER" else []] for kind in ["PER","ORG","LOC","MISC"]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","nlp_model","entity_type","entity_values"])
        client.insert("signal_scanned",[["dataset","source","alternate",1,"fixture",1,hashlib.sha256(text.encode()).hexdigest(),1]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","signal_set_version","text_version","text_digest","scan_version"])
        client.insert("regex_entity_hit",[["dataset","source","raw_text",1,1,"email",["kept@example.org"],["fixture"],["{}"],[1],["kept@example.org"]]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","rule_set_version","entity_type","entity_values","entity_rule_ids","entity_value_json","entity_counts","entity_texts"])
        client.insert("text_chunk_vectors",[["dataset","source","raw_text",1,0,"kept-model",2,[0.1,0.2]]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","chunk_index","embedding_model","dims","embedding"])
        client.insert("manticore_shard_assignments", [["dataset","source",name+"_1"]],
            column_names=["collection_dataset","file_hash","shard_name"])


def selection(client,name):
    return selectors.select(registry.STEPS_BY_ID["entities"],selectors.ScopeContext("dataset","dataset",name),client)


def test_successful_old_output_remains_selected_until_current_index_settles(search_collection,monkeypatch):
    name = search_collection
    seed(name)
    from tasks.P6_index_data.activities import index_text_pages
    from tasks.P6_index_data.params import IndexShardParams
    index_text_pages(IndexShardParams(name,"dataset","initial",name+"_1",["source"]))
    with clickhouse.get_collection_client(name) as client:
        client.command("DELETE FROM signal_scanned WHERE collection_dataset='dataset' SETTINGS mutations_sync=2")
    def non_ner_rows():
        with manticore.get_manticore_client() as connection:
            cursor=connection.cursor()
            cursor.execute(f"SELECT * FROM {name}_1_pages WHERE collection_dataset='dataset' ORDER BY id ASC LIMIT 100")
            return [{key:value for key,value in zip(cursor.column_names,row) if key not in {"ner_per","ner_org","ner_loc","ner_misc"}} for row in cursor.fetchall()]
    previous_index=non_ner_rows()
    monkeypatch.setenv("NER_URL","http://ner-fixture.invalid")
    monkeypatch.setenv("NER_PROVIDER","gpu")
    calls = []
    def infer(texts):
        calls.append(texts)
        return [{"PER":["Current Person"],"ORG":[],"LOC":[],"MISC":[]} for _ in texts],"ner-gpu-xlmr"
    monkeypatch.setattr(activities,"extract_ner_from_texts",infer)
    with clickhouse.get_collection_client(name) as client:
        assert selection(client,name).count == 1
    scope = ExtractEntitiesParams(name,"dataset","plan",["source"])
    activities.extract_entities_for_hashes(scope)
    with clickhouse.get_collection_client(name) as client:
        assert selection(client,name).count == 1
        rows = client.query("SELECT nlp_model,entity_values FROM entity_hit FINAL WHERE collection_dataset='dataset' AND extracted_by='raw_text' AND page_id=1 AND entity_values != []").result_rows
        assert set((model,tuple(values))for model,values in rows) == {("ner-gpu-xlmr",("Current Person",)),("ner-spacy-xx",("CPU Company",))}
        assert client.query("SELECT entity_values FROM entity_hit FINAL WHERE collection_dataset='other'").result_rows == [(["Other Dataset"],)]
    params = entities.EntityUpdateParams(name,"dataset","operation",["source"])
    original = entities.verify_index
    monkeypatch.setattr(entities,"verify_index",lambda _params: (_ for _ in ()).throw(RuntimeError("index interruption")))
    with pytest.raises(RuntimeError,match="index interruption"):
        entities.finish_entity_update(params)
    assert non_ner_rows()==previous_index
    with clickhouse.get_collection_client(name) as client:
        assert selection(client,name).count == 1
    activities.extract_entities_for_hashes(scope)
    assert len(calls) == 1
    monkeypatch.setattr(entities,"verify_index",original)
    entities.finish_entity_update(params)
    assert non_ner_rows()==previous_index
    with clickhouse.get_collection_client(name) as client:
        assert client.query("SELECT entity_values FROM entity_hit FINAL WHERE collection_dataset='dataset' AND extracted_by='alternate' AND entity_type='PER'").result_rows==[(["Variant Person"],)]
        assert client.query("SELECT entity_values FROM regex_entity_hit FINAL WHERE collection_dataset='dataset'").result_rows==[(["kept@example.org"],)]
        assert client.query("SELECT count() FROM string_term_id_to_text FINAL WHERE collection_dataset='dataset' AND term_field='ner' AND term_value='Earlier Person'").result_rows==[(0,)]
        assert client.query("SELECT embedding_model,dims FROM text_chunk_vectors FINAL WHERE collection_dataset='dataset'").result_rows==[("kept-model",2)]
        assert client.query("SELECT count() FROM signal_scanned WHERE collection_dataset='dataset'").result_rows==[(0,)]
        assert selection(client,name).count == 0
        assert entities.list_entity_update_hashes(entities.EntityUpdateParams(name,"dataset")) == []
    activities.extract_entities_for_hashes(scope)
    assert len(calls) == 1
    with clickhouse.get_collection_client(name) as client:
        client.insert("vfs_files", [["dataset","","/later.txt","later"]],column_names=["collection_dataset","container_hash","path","hash"])
        client.insert("text_content", [["dataset","later","raw_text",1,"Missing new output",18,1]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","text","text_bytes","version"])
    monkeypatch.setenv("NER_URL","")
    ctx=selectors.ScopeContext("dataset","dataset",name)
    disabled_key,_=selectors.target_key(registry.STEPS_BY_ID["entities"],ctx)
    with clickhouse.get_collection_client(name) as client:
        assert selection(client,name).count == 0
    monkeypatch.setenv("NER_URL","http://ner-fixture.invalid")
    enabled_key,_=selectors.target_key(registry.STEPS_BY_ID["entities"],ctx)
    assert registry.desired(registry.STEPS_BY_ID["entities"],disabled_key).fingerprint != registry.desired(registry.STEPS_BY_ID["entities"],enabled_key).fingerprint
    with clickhouse.get_collection_client(name) as client:
        assert selection(client,name).count == 1



def test_later_request_failure_preserves_earlier_output(collection,monkeypatch):
    seed(collection)
    monkeypatch.setenv("NER_URL","http://ner-fixture.invalid")
    monkeypatch.setattr(activities,"batch_texts_by_chars",lambda texts: ([text]for text in texts))
    calls=[]
    def infer(texts):
        calls.append(texts)
        if len(calls)==2:
            raise RuntimeError("later window failed")
        return [{"PER":["Replacement"]}],"ner-gpu-xlmr"
    monkeypatch.setattr(activities,"extract_ner_from_texts",infer)
    with pytest.raises(RuntimeError,match="later window"):
        activities.extract_entities_for_hashes(ExtractEntitiesParams(collection,"dataset","plan",["source"]))
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT entity_values FROM entity_hit FINAL WHERE collection_dataset='dataset' AND extracted_by='raw_text' AND nlp_model='ner-gpu-xlmr'").result_rows == [(["Earlier Person"],)]
        assert selection(client,collection).count == 1


def test_table_receipts_keep_unchanged_outputs_but_earlier_readers_stay_selected(collection):
    from tasks.P_admin.updates import table_receipts
    from tasks.P3_parse_files.table_formats import READER_VERSION
    with clickhouse.get_collection_client(collection) as client:
        client.insert("vfs_files",[["dataset","","/same.csv","same"],["dataset","","/old.csv","old"]],column_names=["collection_dataset","container_hash","path","hash"])
        client.insert("table_documents",[["dataset","same",READER_VERSION,"ok",1],["dataset","old",READER_VERSION-1,"ok",1]],
            column_names=["collection_dataset","hash","reader_version","status","generation"])
        previous=table_receipts.accepted_contracts()[1]
        client.insert("processing_output_receipts",[["dataset",h,"table","1",previous,stage,"earlier-operation"] for h in ["same","old"] for stage in table_receipts.STAGES],
            column_names=["collection_dataset","file_hash","output_kind","output_identity","fingerprint","stage","op_id"])
        selected=selectors.select_tables(client,selectors.ScopeContext("dataset","dataset",collection))
        hashes=client.query(selected.hash_sql,parameters=selected.parameters).result_rows
        assert hashes==[("old",)]


def test_table_entity_receipt_requires_current_provider_source(collection,monkeypatch):
    from tasks.P_admin.updates import table_receipts
    from tasks.P4_extract_entities.completion import NER_STAGE_VERSION
    monkeypatch.setenv("NER_URL","http://ner-fixture.invalid")
    monkeypatch.setenv("NER_PROVIDER","gpu")
    params=table_receipts.TableReceiptParams(collection,"dataset","operation",["source"],["entities"])
    with clickhouse.get_collection_client(collection) as client:
        client.insert("text_content",[["dataset","source","table_text",1,"Current text",12,20]],
            column_names=["collection_dataset","file_hash","extracted_by","page_id","text","text_bytes","version"])
        columns=["collection_dataset","file_hash","extracted_by","page_id","nlp_model","stage_version","text_version"]
        client.insert("nlp_processed",[["dataset","source","table_text",1,"ner-spacy-xx",NER_STAGE_VERSION,20],
            ["dataset","source","table_text",1,"ner-gpu-xlmr",NER_STAGE_VERSION,10]],column_names=columns)
        with pytest.raises(RuntimeError,match="entity extraction"):
            table_receipts.verify_stages(client,params)
        client.insert("nlp_processed",[["dataset","source","table_text",1,"ner-gpu-xlmr",NER_STAGE_VERSION,20]],column_names=columns)
        table_receipts.verify_stages(client,params)
        client.insert("nlp_processed",[["dataset","source","table_text",1,"ner-spacy-xx",NER_STAGE_VERSION,10]],column_names=columns)
        table_receipts.verify_stages(client,params)


def test_current_completion_with_missing_group_repeats_inference(collection,monkeypatch):
    seed(collection)
    monkeypatch.setenv("NER_URL","http://ner-fixture.invalid")
    monkeypatch.setenv("NER_PROVIDER","gpu")
    calls=[]
    def infer(texts):
        calls.append(texts)
        return [{"PER":["Current Person"]} for _ in texts],"ner-gpu-xlmr"
    monkeypatch.setattr(activities,"extract_ner_from_texts",infer)
    scope=ExtractEntitiesParams(collection,"dataset","plan",["source"])
    activities.extract_entities_for_hashes(scope)
    count=len(calls)
    with clickhouse.get_collection_client(collection) as client:
        client.command("DELETE FROM entity_hit WHERE collection_dataset='dataset' AND file_hash='source' "
            "AND extracted_by='raw_text' AND page_id=1 AND nlp_model='ner-gpu-xlmr' AND entity_type='LOC' SETTINGS mutations_sync=2")
        assert selection(client,collection).count==1
    activities.extract_entities_for_hashes(scope)
    assert len(calls)==count+1
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT uniqExact(entity_type) FROM entity_hit FINAL WHERE collection_dataset='dataset' "
            "AND file_hash='source' AND extracted_by='raw_text' AND page_id=1 AND nlp_model='ner-gpu-xlmr'").result_rows==[(4,)]
