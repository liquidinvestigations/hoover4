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


@dataclass
class ScanRegexEntitiesForPlanParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str


@dataclass
class ScanRegexEntitiesParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    hashes: list[str]


@dataclass
class ScanRegexEntitiesResult:
    text_segments: int
    entity_groups: int
    #: The rule set the values were produced under, which is what a rescan compares
    #: against to decide whether anything is stale.
    rule_set_version: int
