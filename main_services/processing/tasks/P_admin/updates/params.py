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
    #: The pass returns one candidate for each track of a dataset, the free capacity of
    #: each cap class, and no NER or vector candidate whose service is not ready. False is
    #: the pass of a coordinator run that started before the tracks.
    tracks: bool = False


@dataclass
class UpdateCandidateParams:
    scope_kind: str
    scope_id: str
    collectionname: str
    collection_dataset: str = ""
    steps: List[str] = field(default_factory=list)
    fingerprints: Dict[str, str] = field(default_factory=dict)
    #: The track of a dataset candidate of a tracks pass, else "".
    track: str = ""


@dataclass
class CheckUpdatesResult:
    candidates: List[UpdateCandidateParams] = field(default_factory=list)
    calculated: int = 0
    duration_ms: int = 0
    #: `[processing_updates] automatic` of the installation.
    automatic: bool = True
    #: Free slots of each cap class (`database.operations.update_cap_class`): the cap less
    #: the live operations of the class. A tracks pass fills it.
    capacity: Dict[str, int] = field(default_factory=dict)
    #: The live automatic update operations, `op_id` to state. A tracks pass fills it.
    live: Dict[str, str] = field(default_factory=dict)


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
    #: The track of the operation, and its execution profile. Both are "" for a legacy
    #: operation, which keeps its earlier behavior. See `registry.py`.
    track: str = ""
    profile: str = ""


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
    #: Verify the search copy of each plan after its indexing. False in a run that
    #: started before the verification.
    verify: bool = False
    #: Plans in flight at once. 0 keeps the earlier `VECTOR_PLAN_WINDOW`.
    window: int = 0


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
    #: The antivirus scan is complete, and the pages compare the search attribute.
    attributes: bool = False
    #: The last plan whose search attribute the attribute pages compared.
    stale_after: str = ""
    #: The files whose search rows the attribute pages wrote again.
    reindexed: int = 0


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
