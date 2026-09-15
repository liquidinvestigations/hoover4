"""Temporal parameters for selecting and reconciling historical Error rows."""

from dataclasses import dataclass, field


@dataclass
class SelectErrorsParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    task_name: str = ""
    hash: str = ""


@dataclass
class SelectionResult:
    selected_errors: int = 0
    plan_hashes: list[str] = field(default_factory=list)


@dataclass
class ReconcileErrorsParams:
    op_id: str
    collectionname: str
    collection_dataset: str
