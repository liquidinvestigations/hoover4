"""Temporal parameters of the processing update workflows and activities.

Every parameter object that names a dataset also names its collection
(`tests/unit/test_params_carry_collection.py`). Target identities stay in the database:
a snapshot carries step ids, fingerprints and short settings, never file lists.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class CheckUpdatesParams:
    #: Scope ids to calculate even when their fingerprints did not change. `*` is every scope.
    forced: List[str] = field(default_factory=list)


@dataclass
class UpdateCandidateParams:
    scope_kind: str
    scope_id: str
    collectionname: str
    collection_dataset: str = ""
    steps: List[str] = field(default_factory=list)
    fingerprints: Dict[str, str] = field(default_factory=dict)


@dataclass
class CheckUpdatesResult:
    candidates: List[UpdateCandidateParams] = field(default_factory=list)
    calculated: int = 0
    duration_ms: int = 0
    #: `[processing_updates] automatic` of the installation.
    automatic: bool = True


@dataclass
class SubmitUpdateParams:
    op_id: str
    candidate: UpdateCandidateParams


@dataclass
class RunUpdateParams:
    """The input of `RunProcessingUpdate`, the child of an update operation."""

    op_id: str
    scope_kind: str
    collectionname: str
    collection_dataset: str = ""
    steps: List[str] = field(default_factory=list)
    #: The fingerprints of the preview that the person saw. Empty accepts the current state.
    fingerprints: Dict[str, str] = field(default_factory=dict)
    automatic: bool = False


@dataclass
class StepSnapshotParams:
    step_id: str
    fingerprint: str
    #: JSON of the desired detail and the selection detail.
    detail: str = "{}"
    pending: int = 0


@dataclass
class UpdateSnapshotResult:
    steps: List[StepSnapshotParams] = field(default_factory=list)


@dataclass
class StepParams:
    op_id: str
    scope_kind: str
    collectionname: str
    collection_dataset: str
    automatic: bool
    step: StepSnapshotParams
    #: The error of a failed adapter, for `finish_update_step`.
    error: str = ""
    state: str = ""


@dataclass
class StepOutcomeResult:
    settled: bool = False
    message: str = ""


@dataclass
class VectorPlansParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    model: str = ""
    after: str = ""
    done: int = 0
    failed: int = 0


@dataclass
class TablePlansParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    after: str = ""
    done: int = 0
    failed: int = 0


@dataclass
class VirusPlansParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    after: str = ""
    done: int = 0
    failed: int = 0


@dataclass
class TablePlanParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    plan_hash: str


@dataclass
class UpdateProgressParams:
    op_id: str
    collectionname: str
    collection_dataset: str
    step_id: str
    state: str
    done: int
    total: int
    message: str = ""
