"""Dataclasses for indexing workflow parameters."""

from dataclasses import dataclass, field
from typing import List

@dataclass
class IndexDatasetPlanParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    op_id: str = ""
    vectors_only: bool = False
    #: The files to read. Empty reads every file of the plan, through `fetch_plan_hashes`.
    item_hashes: List[str] = field(default_factory=list)

@dataclass
class PlanShardsParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    hashes: list[str]
    vectors_only: bool = False

@dataclass
class IndexShardParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    shard_name: str
    hashes: list[str]
    op_id: str = ""

@dataclass
class BuildVfsNodesParams:
    """Dataset-scoped, not plan-scoped: the tree is a property of the whole dataset and
    a plan only ever holds a slice of it."""
    collectionname: str
    collection_dataset: str


@dataclass
class ResolveCanonicalFileTypeParams:
    """Scoped to a plan's hashes, or dataset-wide when `item_hashes` is empty.

    Both forms exist because a document's evidence can arrive in a different plan from
    its detections: the plan-scoped call is what gets a document a canonical type before
    it is indexed, and the dataset-wide sweep afterwards is what catches the ones whose
    evidence crossed a plan boundary."""
    collectionname: str
    collection_dataset: str
    item_hashes: list[str]


@dataclass
class FinalizeIndexBatchParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str

@dataclass
class CompactCollectionShardsParams:
    """Select the collection and whether open shards are excluded."""
    collectionname: str
    closed_only: bool
    op_id: str = ""

#: One OCR text segment that a text-page writer read and committed:
#: `(file_hash, extracted_by, page_id, text_version)`.
OcrTextReceipt = tuple[str, str, int, int]


@dataclass
class IndexedTextResult:
    """What one text-page writer committed.

    `committed_hashes` are the documents whose rows were written or removed.
    `ocr_text_versions` holds one receipt for each OCR segment that the writer read, with
    the version it read, for the committed documents only.
    """

    committed_hashes: list[str] = field(default_factory=list)
    ocr_text_versions: list[OcrTextReceipt] = field(default_factory=list)


@dataclass
class RecordIndexedParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    # (shard_name, file_hash) pairs whose writers committed; collection_dataset
    # is uniform for the whole batch.
    entries: list[tuple[str, str]]
    #: The OCR segment versions that the committed writers read. Empty writes no receipt.
    ocr_text_versions: list[OcrTextReceipt] = field(default_factory=list)


@dataclass
class RefreshDocumentLocationsParams:
    """Rewrite page-row folder attributes for documents whose locations changed.

    `item_hashes` empty means select the stale set from current `vfs_files` and
    the indexed `file_paths`. A supplied list is the recovery target and is still
    intersected with shard assignments.
    """
    collectionname: str
    collection_dataset: str
    item_hashes: list[str]


@dataclass
class RefreshDocumentLocationsResult:
    """What one location refresh rewrote, and what it compared against."""

    collectionname: str
    collection_dataset: str
    indexed_documents: int
    affected_count: int
    refreshed_count: int
    mechanism: str


@dataclass
class BuildEmailGraphParams:
    """Collection-scoped work triggered by one dataset finishing.

    `collection_dataset` says which dataset's `email_identity` rows to refresh; the edges
    and clusters are rebuilt for the WHOLE collection either way, because the most common
    edge is the same message present in two datasets and that edge cannot be seen from
    inside one of them."""
    collectionname: str
    collection_dataset: str
