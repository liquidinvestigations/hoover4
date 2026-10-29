"""The operations supervisor wakes the upload queue of each dataset with open batches."""

import asyncio

import database.clickhouse as clickhouse
import database.uploads as uploads
from tasks.P_upload.activities import recover_upload_queues
from tasks.P_upload.params import UploadQueueParams


class _Client:
    def __init__(self):
        self.starts = []

    async def start_workflow(self, workflow, arg, **kwargs):
        self.starts.append((workflow, arg, kwargs))


def test_every_dataset_with_an_open_batch_gets_one_signal_with_start(monkeypatch):
    monkeypatch.setattr(clickhouse, "list_collections", lambda: ["a", "b", "broken"])

    def open_batches(collectionname):
        if collectionname == "broken":
            raise RuntimeError("no upload tables")
        return {"a": [("a_up", "b1")], "b": []}[collectionname]

    monkeypatch.setattr(uploads, "datasets_with_open_batches", open_batches)
    client = _Client()
    assert asyncio.run(recover_upload_queues(client)) == 1
    [(workflow, arg, kwargs)] = client.starts
    assert workflow == "UploadQueue"
    assert arg == UploadQueueParams("a", "a_up")
    assert kwargs == {"id": "upload-queue-a_up", "task_queue": "processing-common-queue",
                      "start_signal": "upload_committed", "start_signal_args": [{"batch_id": "b1"}]}
