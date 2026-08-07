"""Dataclasses for the chunk+embed (P5) stage."""

from dataclasses import dataclass


@dataclass
class ChunkEmbedForPlanParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str


@dataclass
class ChunkEmbedParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    hashes: list[str]


@dataclass
class ChunkEmbedResult:
    text_segments: int
    chunks_written: int
    vectors_written: int
