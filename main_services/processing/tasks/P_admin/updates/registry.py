"""The update steps that bring the stored results of existing data up to date.

A **processing update** is one versioned change to the stored results of a dataset or a
collection. The interface calls the action "Update processing". In code, one entry of
`STEPS` is an update step.

Each step has four contracts, and `selectors.py` and `workflows.py` implement them:

1. a live selector, which counts the files that the step changes now;
2. an invalidation rule, which says what stored output becomes stale;
3. its work and the downstream stages that the work runs;
4. a settlement rule, which verifies the output after the work. A successful activity
   return alone does not prove that the output exists.

The desired fingerprint of a step joins its own version, the versions of the stages that
it runs, the settings that it depends on (`target_key`) and, for the steps that select
unfinished work, the input revision of the dataset. A changed fingerprint makes the
coordinator calculate the step again. An unchanged one costs no count query.

Collection steps are prerequisites. They run as their own `update_collection`
operation, before any dataset operation that needs them, and never as a child of a
dataset operation, because admission makes a collection operation wait for every live
operation of its collection.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from tasks.stage_versions import STAGE_VERSIONS

SCOPE_DATASET = "dataset"
SCOPE_COLLECTION = "collection"

#: The `user_id` of an operation that the coordinator starts.
AUTOMATIC_USER = "processing-updates"


@dataclass(frozen=True)
class UpdateStep:
    step_id: str
    scope: str
    #: The step's own version. Raise it when its selector, work or settlement changes
    #: the output that it leaves.
    version: int
    #: The canonical stages whose versions the step's output depends on.
    stages: Tuple[str, ...]
    #: Whether the coordinator may start the step without a person.
    automatic: bool
    #: Whether the input revision of the dataset is part of the fingerprint. True for the
    #: steps that select work which new ingestion or an interruption can leave.
    uses_input_revision: bool
    #: Collection steps that must be up to date before this step writes.
    prerequisites: Tuple[str, ...]
    #: Steps of the same run that must succeed before this one starts.
    requires: Tuple[str, ...]
    title: str
    #: What changes, for an administrator. `{files}` is replaced by the file count.
    explanation: str
    #: The runs that follow.
    runs: str
    #: The unit of the count: files, folders for the folder counts, or search tables.
    unit: str = "files"


STEPS: Tuple[UpdateStep, ...] = (
    UpdateStep(
        step_id="search_schema", scope=SCOPE_COLLECTION, version=1, stages=("index_text",),
        automatic=True, uses_input_revision=False, prerequisites=(), requires=(),
        title="Search index schema",
        explanation="{files} search tables of the collection miss a column that the search index needs. "
                    "The column is added to each table. Search keeps working.",
        runs="Search index tables", unit="tables"),
    UpdateStep(
        step_id="unfinished", scope=SCOPE_DATASET, version=1, stages=(),
        automatic=True, uses_input_revision=True, prerequisites=("search_schema",), requires=(),
        title="Unfinished processing",
        explanation="{files} files are not processed to the end. This includes files without a "
                    "processing plan, for example after an interrupted ingestion. Their processing completes.",
        runs="All processing stages for these files"),
    UpdateStep(
        step_id="failed_files", scope=SCOPE_DATASET, version=1, stages=tuple(sorted(STAGE_VERSIONS)),
        automatic=True, uses_input_revision=True, prerequisites=("search_schema",), requires=(),
        title="Failed files",
        explanation="{files} files have a processing error. The failed stages run again for them. "
                    "The automatic run retries a file once for each new version of the stage that failed.",
        runs="The failed stages, then entity extraction, embedding and indexing"),
    UpdateStep(
        step_id="tables", scope=SCOPE_DATASET, version=1, stages=("table",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Tables",
        explanation="{files} files are JSON or JSON Lines files without a table of the current reader, or "
                    "tables that an earlier reader cut at 300 columns. They are read again. JSON files "
                    "that an earlier reader read as CSV get their JSON table, and the earlier cells stop "
                    "being shown.",
        runs="Table reading, then the file type and indexing of these files"),
    UpdateStep(
        step_id="ocr", scope=SCOPE_DATASET, version=1,
        stages=("ocr_image", "ocr_pdf", "image_pdf", "image_preview", "pdf"),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="OCR",
        explanation="About {files} files have no OCR text for the current languages, or keep OCR text of "
                    "languages that the settings no longer include. OCR runs for the current languages, and "
                    "the text of the removed languages is deleted.",
        runs="OCR and searchable PDFs, then entity extraction, embedding and indexing of the new text"),
    UpdateStep(
        step_id="vectors", scope=SCOPE_DATASET, version=1, stages=("embed", "index_vectors"),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Vectors",
        explanation="{files} files with text have no vectors of the embedding model that the "
                    "installation serves. Their vectors are computed and indexed.",
        runs="Embedding and vector indexing"),
    UpdateStep(
        step_id="folder_counts", scope=SCOPE_DATASET, version=1, stages=("vfs_stats",),
        automatic=True, uses_input_revision=False, prerequisites=(), requires=(),
        title="Folder counts",
        explanation="{files} folders have no file count or size, or have values of an earlier "
                    "version. The counts are calculated again.",
        runs="Folder tree", unit="folders"),
)

STEPS_BY_ID: Dict[str, UpdateStep] = {step.step_id: step for step in STEPS}


def steps_of(scope: str) -> Tuple[UpdateStep, ...]:
    """The steps of one scope, in run order."""
    return tuple(step for step in STEPS if step.scope == scope)


def step_version(step: UpdateStep) -> str:
    """The version string of a step: its own version and those of its stages."""
    stages = ",".join(f"{stage}={STAGE_VERSIONS[stage]}" for stage in step.stages)
    return f"{step.version}|{stages}"


def fingerprint(step: UpdateStep, target_key: str, input_revision: str = "") -> str:
    """The desired fingerprint of a step for a target key and an input revision."""
    payload = json.dumps({
        "step": step.step_id,
        "version": step_version(step),
        "target_key": target_key,
        "input_revision": input_revision if step.uses_input_revision else "",
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


@dataclass
class Desired:
    """What one step of one scope should produce now."""

    step_id: str
    fingerprint: str
    version: str
    target_key: str
    input_revision: str = ""
    extra: Dict[str, object] = field(default_factory=dict)

    def detail(self) -> dict:
        return {"version": self.version, "target_key": self.target_key,
                "input_revision": self.input_revision, **self.extra}


def desired(step: UpdateStep, target_key: str, input_revision: str = "",
            extra: Optional[dict] = None) -> Desired:
    return Desired(step.step_id, fingerprint(step, target_key, input_revision),
                   step_version(step), target_key,
                   input_revision if step.uses_input_revision else "", dict(extra or {}))
