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
class FinalizeIndexBatchParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str

@dataclass
class RecordIndexedParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    # (shard_name, file_hash) pairs whose writers committed; collection_dataset
    # is uniform for the whole batch.
    entries: list[tuple[str, str]]
