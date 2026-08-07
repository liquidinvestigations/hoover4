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
    #: Chunks the non-linguistic filter held back (`tasks.text_quality`) — base64
    #: attachment bodies, pixel data. Counted rather than merely logged: a jump here is
    #: how you notice the heuristic has started eating real documents.
    chunks_skipped_non_linguistic: int = 0
