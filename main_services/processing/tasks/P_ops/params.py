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
