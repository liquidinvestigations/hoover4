"""The worker supervisor preserves recovered Abort and confirmed collection deletion."""
import asyncio
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from database import clickhouse
from tasks.P_upload.activities import recover_upload_queues
from .test_table_publication_receipts import collection

pytestmark=pytest.mark.integration


def test_terminal_receiver_state_and_deleted_collection_do_not_restart_ingestion(collection,monkeypatch):
    name=collection
    now=datetime.now(timezone.utc).replace(tzinfo=None,microsecond=0)
    with clickhouse.get_global_client() as client:
        client.insert("collections",[[name,"upload recovery fixture",1,now,now,0]],column_names=["collectionname","fullname","is_public","created_at","updated_at","is_deleted"])
    try:
        with clickhouse.get_collection_client(name) as client:
            client.insert("upload_batches",[["aborted","dataset","cancelled",1],["waiting","dataset","queued",1]],column_names=["batch_id","upload_dataset","state","row_version"])
        calls=[]
        async def start(*args,**kwargs):
            calls.append((args,kwargs))
        original=clickhouse.list_collections
        monkeypatch.setattr(clickhouse,"list_collections",lambda:[value for value in original() if value==name])
        assert asyncio.run(recover_upload_queues(SimpleNamespace(start_workflow=start)))==1
        assert calls[0][1]["start_signal_args"]==[{"batch_id":"waiting"}]
        with clickhouse.get_collection_client(name) as client:
            client.command("DELETE FROM upload_batches WHERE batch_id='waiting' SETTINGS mutations_sync=2")
        calls.clear()
        clickhouse.reset_client_pool_for_tests()
        assert asyncio.run(recover_upload_queues(SimpleNamespace(start_workflow=start)))==0
        assert calls==[]
        with clickhouse.get_collection_client(name) as client:
            client.insert("upload_batches",[["deleted-pending","dataset","queued",1]],column_names=["batch_id","upload_dataset","state","row_version"])
        with clickhouse.get_global_client() as client:
            client.insert("collections",[[name,"upload recovery fixture",1,now,now+timedelta(seconds=1),1]],column_names=["collectionname","fullname","is_public","created_at","updated_at","is_deleted"])
        clickhouse.reset_client_pool_for_tests()
        assert asyncio.run(recover_upload_queues(SimpleNamespace(start_workflow=start)))==0
        assert calls==[]
    finally:
        with clickhouse.get_global_client() as client:
            client.command("DELETE FROM collections WHERE collectionname={name:String} SETTINGS mutations_sync=2",parameters={"name":name})
