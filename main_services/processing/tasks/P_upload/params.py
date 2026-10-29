"""Parameter objects of the upload queue and the targeted upload ingest.

Every value here is an id, a count or a flag. No path, file name, manifest or error list
enters a Temporal payload of these workflows. The activities read paths from
`upload_files` by batch id.
"""

from dataclasses import dataclass, field


@dataclass
class UploadQueueParams:
    """The input of `UploadQueue`, and its state across continue-as-new.

    The website starts the queue with `collectionname` and `upload_dataset` only.
    `active_op_id` names the operation that a previous run of the queue started and that
    had not ended at the continuation.
    """

    collectionname: str
    upload_dataset: str
    active_op_id: str = ""


@dataclass
class UploadOperationParams:
    """One upload dataset and one `ingest_upload` operation id."""

    collectionname: str
    upload_dataset: str
    op_id: str


@dataclass
class UploadClaimResult:
    """The answer of `open_upload_operation`.

    `op_id` is empty when no batch waits. `op_state` is the state of the operations row.
    `dataset_live` is false after the dataset was deleted.
    """

    op_id: str = ""
    batch_ids: list[str] = field(default_factory=list)
    op_state: str = ""
    dataset_live: bool = True


@dataclass
class IngestUploadBatchesParams:
    """The input of `IngestUploadBatches`, and its state across continue-as-new.

    `batch_ids` holds at most `database.uploads.BATCHES_PER_OPERATION` ids: the batches
    not yet done in this operation.
    """

    collectionname: str
    upload_dataset: str
    op_id: str
    batch_ids: list[str] = field(default_factory=list)
    selection_done: bool = False
    execution_counts: dict[str, int] = field(default_factory=dict)
    selector_counts: dict[str, int] = field(default_factory=dict)
    batch_states: dict[str, int] = field(default_factory=dict)


@dataclass
class UploadBatchParams:
    """One batch of one `ingest_upload` operation."""

    collectionname: str
    upload_dataset: str
    op_id: str
    batch_id: str


@dataclass
class UploadBatchLimitsResult:
    """The numeric limits of the ingest of one batch, read from the stored batch row.

    `skip` is true when the operation does not own the batch or the batch has its
    outcome already.
    """

    ingest_seconds: int = 0
    file_count: int = 0
    byte_count: int = 0
    skip: bool = False


@dataclass
class FinishUploadBatchesParams:
    """The batches to settle, and the state of their operation.

    `operation_state` is `running` while the operation runs its own finalizer, and the
    terminal state of the operations row when the queue settles the batches afterwards.
    """

    collectionname: str
    upload_dataset: str
    op_id: str
    batch_ids: list[str] = field(default_factory=list)
    operation_state: str = "running"
