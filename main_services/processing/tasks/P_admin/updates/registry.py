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
it runs, the settings that it depends on (`target_key`), for the steps that select
unfinished work the input revision of the dataset, and for NER and vectors the
dependency revision of the dataset: the newest ended update operation that ran a step
which can write text (`writes_text`). A text writer that ends, also after a failure or a
cancellation, therefore makes NER and vectors calculate again. A changed fingerprint makes the
coordinator calculate the step again. An unchanged one costs no count query.

Collection steps are prerequisites. They run as their own `update_collection`
operation, before any dataset operation that needs them, and never as a child of a
dataset operation, because admission makes a collection operation wait for every live
operation of its collection.

Each dataset step belongs to one **track**: `ocr`, `ner`, `vectors` or `main`. The
coordinator starts one `update_dataset` operation for each track of a dataset that has
automatic work, with `track` and `profile` (`PROFILE_TRACKS`) in its detail. Each track
has its own cap in admission (`[operations] update_<track>_cap`), so a slow OCR operation
does not use the slots of the other tracks. An operation without a track is a legacy
operation: a manual request that selects steps of more than one track, or an operation
that started before the tracks. It runs its steps as before and counts against
`update_dataset_cap`.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from tasks.stage_versions import STAGE_VERSIONS

SCOPE_DATASET = "dataset"
SCOPE_COLLECTION = "collection"

TRACK_OCR = "ocr"
TRACK_NER = "ner"
TRACK_VECTORS = "vectors"
TRACK_MAIN = "main"
#: The dataset tracks. Each one is a cap class of admission (`database/operations.py`).
TRACKS = (TRACK_OCR, TRACK_NER, TRACK_VECTORS, TRACK_MAIN)
#: The execution profile of an operation that runs the steps of one track. A legacy
#: operation has the empty profile and keeps its earlier behavior.
PROFILE_TRACKS = "tracks-v1"
#: The service capability that each track needs before the coordinator starts it
#: (`tasks/service_readiness.py`).
TRACK_CAPABILITY = {TRACK_NER: "ner", TRACK_VECTORS: "embeddings"}

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
    #: The track of a dataset step. A collection step has none.
    track: str = ""
    #: Whether the step can write `text_content`. The newest ended update operation with
    #: such a step is the dependency revision of its dataset.
    writes_text: bool = False
    #: Whether the dependency revision of the dataset is part of the fingerprint. True for
    #: the steps that read text which another update step can write: NER and vectors.
    uses_dependency_revision: bool = False


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
        runs="All processing stages for these files",
        track=TRACK_MAIN, writes_text=True),
    UpdateStep(
        step_id="failed_files", scope=SCOPE_DATASET, version=1, stages=tuple(sorted(STAGE_VERSIONS)),
        automatic=True, uses_input_revision=True, prerequisites=("search_schema",), requires=(),
        title="Failed files",
        explanation="{files} files have a processing error. The failed stages run again for them. "
                    "The automatic run retries a file once for each new version of the stage that failed.",
        runs="The failed stages, then entity extraction, embedding and indexing",
        track=TRACK_MAIN, writes_text=True),
    UpdateStep(
        step_id="virus_scan", scope=SCOPE_DATASET, version=1, stages=("virus_scan",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Virus scan",
        explanation="{files} files have no antivirus verdict. They are scanned. A file that the scanner "
                    "finds infected is marked in search, and its original and searchable PDF downloads "
                    "are refused.",
        runs="Antivirus scan, then the search attribute of infected files",
        track=TRACK_MAIN),
    UpdateStep(
        step_id="tables", scope=SCOPE_DATASET, version=2,
        stages=("table", "entities", "regex", "embed", "index_text", "index_vectors"),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Tables",
        explanation="{files} files have earlier table readings or incomplete dependent output. Their stored results are updated.",
        runs="Table reading, entities, signals, embedding, and both indexes",
        track=TRACK_MAIN, writes_text=True),
    UpdateStep(
        step_id="archive_members", scope=SCOPE_DATASET, version=1, stages=("archive",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Archive members",
        explanation="{files} split archives need their current member list. Their members and search output are updated.",
        runs="Archive extraction, member reconciliation, and dependent processing",
        track=TRACK_MAIN, writes_text=True),
    UpdateStep(
        step_id="image_previews", scope=SCOPE_DATASET, version=2, stages=("image_preview",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Image previews",
        explanation="{files} uncommon images have no preview. Their previews are created again.",
        runs="Image preview creation and verification",
        track=TRACK_MAIN),
    UpdateStep(
        step_id="ocr_detection", scope=SCOPE_DATASET, version=4, stages=("ocr_detection",),
        automatic=True, uses_input_revision=True, prerequisites=("search_schema",), requires=(),
        title="OCR detection",
        explanation="{files} files have no detected text, script or language. Each image and each page "
                    "selected for OCR is examined in bounded batches.",
        runs="Detection, then the search attributes of these files",
        track=TRACK_OCR),
    UpdateStep(
        step_id="ocr", scope=SCOPE_DATASET, version=4,
        stages=("ocr_image", "ocr_pdf", "image_pdf", "image_preview", "pdf", "ocr_detection", "ocr_plan"),
        automatic=True, uses_input_revision=True, prerequisites=("search_schema",), requires=(),
        title="OCR",
        explanation="{files} files need automatic OCR. Earlier OCR text that contains the detected language is kept "
                    "without a new OCR request. Other pages get OCR with the installed model of the detected language. "
                    "Superseded variants are removed after the replacement is complete.",
        runs="OCR and searchable PDFs, then signals and indexing of the new text. Entity extraction "
             "and embedding of the new text follow.",
        track=TRACK_OCR, writes_text=True),
    UpdateStep(
        step_id="pdf_text", scope=SCOPE_DATASET, version=3, stages=("pdf_text_layer",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Searchable PDF text",
        explanation="{files} files have searchable PDFs with an earlier text layer. That layer copied each "
                    "letter outside the Western European alphabets as a black square. PDFs of languages "
                    "with only Western European letters are kept. The other PDFs are read, and the parts "
                    "with black squares are built again. An image PDF uses the stored OCR words. A PDF "
                    "page gets a new OCR request.",
        runs="Searchable PDF parts, then OCR text indexing of the rebuilt PDFs",
        track=TRACK_OCR, writes_text=True),
    UpdateStep(
        step_id="text_rows", scope=SCOPE_DATASET, version=1, stages=("text_rows",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Text split",
        explanation="{files} files have text from an earlier split. PDF text moves into one row for "
                    "each PDF part, and long text gets cuts with a short overlap. No new OCR or parsing runs.",
        runs="Text split, then entity extraction, embedding and indexing of the new text",
        track=TRACK_MAIN, writes_text=True),
    UpdateStep(
        step_id="entities", scope=SCOPE_DATASET, version=1,
        stages=("entities", "index_text", "index_terms"), automatic=True, uses_input_revision=True,
        prerequisites=("search_schema",), requires=(), title="Named entities",
        explanation="{files} files need complete current entity extraction or searchable output. Earlier successful results are replaced after inference completes.",
        runs="Named entity extraction, text attributes, and searchable entity terms",
        track=TRACK_NER, uses_dependency_revision=True),
    UpdateStep(
        step_id="page_text", scope=SCOPE_DATASET, version=1, stages=("index_page_text",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Indexed page text",
        explanation="{files} files have pages that search holds only up to a NUL byte. The complete "
                    "text goes into the search index.",
        runs="Search index text of these pages",
        track=TRACK_MAIN),
    UpdateStep(
        step_id="vectors", scope=SCOPE_DATASET, version=2, stages=("embed", "index_vectors"),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Vectors",
        explanation="{files} files with text have no current vectors of the embedding model that the "
                    "installation serves. Missing and outdated vectors are computed again and indexed.",
        runs="Embedding and vector indexing",
        track=TRACK_VECTORS, uses_dependency_revision=True),
    UpdateStep(
        step_id="search_terms", scope=SCOPE_DATASET, version=3, stages=("index_terms",),
        automatic=True, uses_input_revision=False, prerequisites=("search_schema",), requires=(),
        title="Search terms",
        explanation="{files} search tables need current filter terms. Language, OCR, script, and red-flag terms become searchable.",
        runs="Filter term indexing and verification", unit="tables",
        track=TRACK_MAIN),
    UpdateStep(
        step_id="folder_counts", scope=SCOPE_DATASET, version=1, stages=("vfs_stats",),
        automatic=True, uses_input_revision=False, prerequisites=(), requires=(),
        title="Folder counts",
        explanation="{files} folders have no file count or size, or have values of an earlier "
                    "version. The counts are calculated again.",
        runs="Folder tree", unit="folders",
        track=TRACK_MAIN),
)

STEPS_BY_ID: Dict[str, UpdateStep] = {step.step_id: step for step in STEPS}

#: The dataset steps that can write `text_content`, for the dependency revision.
TEXT_WRITER_STEPS: Tuple[str, ...] = tuple(step.step_id for step in STEPS if step.writes_text)


def steps_of(scope: str) -> Tuple[UpdateStep, ...]:
    """The steps of one scope, in run order."""
    return tuple(step for step in STEPS if step.scope == scope)


def track_of_steps(step_ids) -> str:
    """The one track of dataset steps, or "" for steps of more than one track or unknown steps."""
    tracks = {STEPS_BY_ID[s].track if s in STEPS_BY_ID else "" for s in step_ids}
    return tracks.pop() if len(tracks) == 1 else ""


def valid_track_request(scope_kind: str, step_ids, track: str, profile: str) -> str:
    """The reason why track metadata of a request is invalid, or "" when it is valid.

    A request without a track and without a profile is a legacy request and valid here.
    """
    if not track and not profile:
        return ""
    if scope_kind != SCOPE_DATASET:
        return "A collection update has no track."
    if track not in TRACKS:
        return f"Unknown update track: {track!r}."
    if profile != PROFILE_TRACKS:
        return f"Unknown update profile: {profile!r}."
    if track_of_steps(step_ids) != track:
        return f"The selected steps are not all steps of the {track} track."
    return ""


def step_version(step: UpdateStep) -> str:
    """The version string of a step: its own version and those of its stages."""
    stages = ",".join(f"{stage}={STAGE_VERSIONS[stage]}" for stage in step.stages)
    return f"{step.version}|{stages}"


def fingerprint(step: UpdateStep, target_key: str, input_revision: str = "",
                dependency_revision: str = "") -> str:
    """The desired fingerprint of a step for a target key, an input and a dependency revision.

    The dependency revision is in the payload only for the steps that use it, so the
    fingerprints of the other steps stay as they were before it existed.
    """
    content = {
        "step": step.step_id,
        "version": step_version(step),
        "target_key": target_key,
        "input_revision": input_revision if step.uses_input_revision else "",
    }
    if step.uses_dependency_revision:
        content["dependency_revision"] = dependency_revision
    payload = json.dumps(content, sort_keys=True)
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
    dependency_revision: str = ""

    def detail(self) -> dict:
        detail = {"version": self.version, "target_key": self.target_key,
                  "input_revision": self.input_revision, **self.extra}
        if self.dependency_revision:
            detail["dependency_revision"] = self.dependency_revision
        return detail


def desired(step: UpdateStep, target_key: str, input_revision: str = "",
            extra: Optional[dict] = None, dependency_revision: str = "") -> Desired:
    return Desired(step.step_id, fingerprint(step, target_key, input_revision, dependency_revision),
                   step_version(step), target_key,
                   input_revision if step.uses_input_revision else "", dict(extra or {}),
                   dependency_revision if step.uses_dependency_revision else "")
