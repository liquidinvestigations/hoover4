"""Parameter objects for the operations layer.

Dataclasses rather than dicts because these cross the Temporal wire and a typo in a
dict key is a runtime failure inside a workflow, where it costs a whole execution to
discover.
"""

from dataclasses import dataclass, field


@dataclass
class OperationParams:
    """Everything the `Operation` workflow needs to run one operation.

    `op_id` is also this workflow's id, so the workflow can always find its own row
    without being told where it is.
    """

    op_id: str
    kind: str
    collectionname: str = ""
    collection_dataset: str = ""
    dataset_path: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class OperationStateParams:
    """One write to the operations row."""

    op_id: str
    state: str = ""
    error: str = ""
    progress_done: int = 0
    progress_total: int = 0


@dataclass
class DatasetProgressParams:
    """Which dataset's plan counts to sample for a progress update."""

    op_id: str
    collectionname: str
    collection_dataset: str


@dataclass
class DatasetRegistryParams:
    """Which dataset's registry row to tombstone.

    Separate from the purge: the registry row lives in the global database and is what
    every other surface reads to decide the dataset exists, while the purge only ever
    touches the collection's own stores.
    """

    op_id: str
    collectionname: str
    collection_dataset: str


@dataclass
class RetryFailedFilesParams:
    """Which dataset's failures to retry, and which stage recorded them.

    `task_name` is the `processing_errors.task_name` to retry and it is required: one
    dispatch retries one stage, because retrying every stage at once re-runs the whole
    pipeline for every failed document, which is the thing the operation exists to
    avoid.
    """

    op_id: str
    collectionname: str
    collection_dataset: str
    task_name: str = ""


@dataclass
class RetryPlanResult:
    """What one `retry_failed_files` dispatch is going to re-run.

    Computed once, before anything re-runs, and carried through the workflow: the
    verification at the end compares against exactly these hashes, and `started_at` is
    read from the ClickHouse server's clock rather than a worker's, because the
    `processing_errors` rows it is compared against are timestamped by other hosts.
    """

    task_name: str = ""
    retry_kind: str = ""
    plan_hashes: list[str] = field(default_factory=list)
    hashes: list[str] = field(default_factory=list)
    started_at: str = ""


@dataclass
class ExportParams:
    """Which collection is being exported, and where its artifacts are being written.

    `destination` names a **subdirectory** of the backup root and never a path: a caller
    cannot ask for a directory that is not mounted. `directory` is the staging directory
    the first activity created, carried to the rest so that every store writes into the
    same run's tree rather than deriving a path of its own.
    """

    op_id: str
    collectionname: str
    destination: str = ""
    directory: str = ""


@dataclass
class ExportStoreResult:
    """What one store contributed to a backup.

    `detail` is per store and goes into the manifest as it is — the artifact names, their
    sizes and their checksums — because what a restore needs to know differs by store and
    flattening it here would lose the parts only one of them has.
    """

    store: str = ""
    bytes_written: int = 0
    seconds: float = 0.0
    detail: dict = field(default_factory=dict)


@dataclass
class FinishRetryParams:
    """The verification pass that decides which error rows a retry may delete."""

    op_id: str
    collectionname: str
    collection_dataset: str
    task_name: str = ""
    retry_kind: str = ""
    hashes: list[str] = field(default_factory=list)
    started_at: str = ""
