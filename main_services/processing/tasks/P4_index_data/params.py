"""Dataclasses for indexing workflow parameters."""

from dataclasses import dataclass

@dataclass
class IndexDatasetPlanParams:
    collection_dataset: str
    plan_hash: str

@dataclass
class IndexTextContentParams:
    collection_dataset: str
    plan_hash: str
    hashes: list[str]