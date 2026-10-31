"""Temporal parameters for selecting and reconciling historical Error rows."""

from dataclasses import dataclass, field


@dataclass
class SelectErrorsParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    task_name: str = ""
    hash: str = ""
    #: Error names to select, for a processing update. Empty selects by the two filters
    #: above. A selection uses either this list or those filters.
    task_names: list[str] = field(default_factory=list)


@dataclass
class SelectionResult:
    selected_errors: int = 0
    errors_before_run: int = 0
    removed_stage_off_errors: int = 0
    without_plan_errors: int = 0
    plan_hashes: list[str] = field(default_factory=list)


@dataclass
class ReconcileErrorsParams:
    op_id: str
    collectionname: str
    collection_dataset: str
