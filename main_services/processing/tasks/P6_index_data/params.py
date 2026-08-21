"""Dataclasses for indexing workflow parameters."""

from dataclasses import dataclass

@dataclass
class IndexDatasetPlanParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str

@dataclass
class PlanShardsParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    hashes: list[str]

@dataclass
class IndexShardParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    shard_name: str
    hashes: list[str]

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
class OptimizeShardsParams:
    """The shards one plan wrote to, offered for compaction."""
    collectionname: str
    collection_dataset: str
    plan_hash: str
    shard_names: list[str]

@dataclass
class RecordIndexedParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    # (shard_name, file_hash) pairs whose writers committed; collection_dataset
    # is uniform for the whole batch.
    entries: list[tuple[str, str]]


@dataclass
class BuildEmailGraphParams:
    """Collection-scoped work triggered by one dataset finishing.

    `collection_dataset` says which dataset's `email_identity` rows to refresh; the edges
    and clusters are rebuilt for the WHOLE collection either way, because the most common
    edge is the same message present in two datasets and that edge cannot be seen from
    inside one of them."""
    collectionname: str
    collection_dataset: str
