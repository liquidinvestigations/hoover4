"""Dataclasses for the entity-extraction (NLP/NER) stage."""

from dataclasses import dataclass


@dataclass
class ExtractEntitiesForPlanParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str


@dataclass
class ExtractEntitiesParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    hashes: list[str]


@dataclass
class ExtractEntitiesResult:
    text_segments: int
    entity_groups: int
