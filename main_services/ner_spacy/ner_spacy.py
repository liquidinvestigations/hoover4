"""spaCy NER over HTTP — the CPU twin of the GPU transformer NER.

Speaks the **same contract** as `ai_services/hoover4_ai_server`'s
`POST /v1/extract-entities`, deliberately down to the response field names, so
`tasks/remote.py` can fall back from one to the other with no branching at the call site
and no second response parser to keep in step.

What it is not
--------------
It is not as good, and the pipeline records that rather than hiding it. Every row it
produces is attributed `nlp_model = 'ner-spacy-xx'`, distinct from the GPU tier's
`ner-gpu-xlmr`, and `entity_hit` carries `nlp_model` in its ORDER BY so the two sets
coexist instead of overwriting each other. When the GPU host comes back, the files it
missed still have no `ner-gpu-xlmr` watermark, so they reprocess under it and both sets
end up present — which is the point: the fallback is visible in the data, not just in a
log line nobody reads.

Model
-----
`xx_ent_wiki_sm` — the multilingual model, matching the `-xx` in the identifier. It
recognises PER / LOC / ORG / MISC, a deliberately narrower set than the GPU model's,
which is why label mapping below is explicit rather than passthrough.
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ner_spacy")

MODEL_NAME = os.getenv("SPACY_MODEL", "xx_ent_wiki_sm")

#: The identifier written to `entity_hit.nlp_model` and `nlp_processed.nlp_model`.
#: Must differ from the GPU tier's, or a fallback silently pollutes the GPU's watermark
#: and those files never get reprocessed when the GPU returns.
NLP_MODEL_ID = os.getenv("NLP_MODEL_ID", "ner-spacy-xx")

#: spaCy releases the GIL only in parts of the pipeline, so more threads than cores buys
#: little and costs memory (one doc per thread).
NER_CONCURRENCY = int(os.getenv("NER_CONCURRENCY", "2"))
NER_QUEUE_DEPTH = int(os.getenv("NER_QUEUE_DEPTH", "16"))

#: Guards against a single enormous page turning one request into a minutes-long stall.
#: spaCy's own default is 1_000_000 characters.
MAX_TEXT_CHARS = int(os.getenv("NER_MAX_TEXT_CHARS", "1000000"))

CONFIG_FINGERPRINT = os.getenv("HOOVER4_CONFIG_FINGERPRINT", "")

app = FastAPI(title="hoover4 spaCy NER (CPU twin)", version="1.0")

_pool = ThreadPoolExecutor(max_workers=NER_CONCURRENCY, thread_name_prefix="ner")
_inflight = threading.Semaphore(NER_CONCURRENCY + NER_QUEUE_DEPTH)
_nlp = None
_load_error = ""

#: spaCy's multilingual labels mapped onto the GPU model's CoNLL-03 vocabulary. Without
#: this the same entity arrives under two different `entity_type` values depending on
#: which provider served it, and the Manticore facet union in P6 shows both as separate
#: facets — which reads as duplicate data rather than as one entity found twice.
_LABEL_MAP: Dict[str, str] = {
    "PER": "PER",
    "PERSON": "PER",
    "LOC": "LOC",
    "GPE": "LOC",
    "ORG": "ORG",
    "MISC": "MISC",
}


def _load_model():
    global _nlp, _load_error
    try:
        import spacy

        _nlp = spacy.load(MODEL_NAME)
        # The entity ruler is all we need; parser and tagger are dead weight per doc.
        log.info("loaded spaCy model %s with pipes %s", MODEL_NAME, _nlp.pipe_names)
    except Exception as exc:  # pragma: no cover - startup path
        _load_error = f"{type(exc).__name__}: {exc}"
        log.error("could not load spaCy model %s: %s", MODEL_NAME, _load_error)


_load_model()


class EntityInfo(BaseModel):
    text: str
    label: str
    start: int
    end: int
    confidence: Optional[float] = None
    text_index: Optional[int] = None


class NERRequest(BaseModel):
    input: Union[str, List[str]] = Field(...)
    model: Optional[str] = Field(default=None)
    include_confidence: Optional[bool] = Field(default=True)
    entity_types: Optional[List[str]] = Field(default=None)


class NERResponse(BaseModel):
    object: str = "list"
    data: List[EntityInfo]
    model: str
    usage: dict


def _extract(texts: List[str], entity_types: Optional[List[str]]) -> List[EntityInfo]:
    out: List[EntityInfo] = []
    wanted = set(entity_types) if entity_types else None

    # `nlp.pipe` batches, which is most of spaCy's throughput on many short texts.
    for index, doc in enumerate(_nlp.pipe(texts)):
        for ent in doc.ents:
            label = _LABEL_MAP.get(ent.label_, ent.label_)
            if wanted and label not in wanted:
                continue
            out.append(EntityInfo(
                text=ent.text,
                label=label,
                start=ent.start_char,
                end=ent.end_char,
                # spaCy's small models expose no per-entity probability. Reporting None
                # is honest; inventing a 1.0 would make a weaker provider look certain.
                confidence=None,
                text_index=index,
            ))
    return out


@app.get("/health")
def health():
    return {
        "status": "healthy" if _nlp is not None else "unhealthy",
        "ner_model_loaded": _nlp is not None,
        "ner_model": MODEL_NAME,
        "nlp_model_id": NLP_MODEL_ID,
        "load_error": _load_error,
        "concurrency": NER_CONCURRENCY,
        "queue_depth": NER_QUEUE_DEPTH,
        "config_fingerprint": CONFIG_FINGERPRINT,
    }


@app.post("/v1/extract-entities", response_model=NERResponse)
def extract_entities(request: NERRequest):
    if _nlp is None:
        raise HTTPException(status_code=503, detail=f"spaCy model not available: {_load_error}")

    texts = [request.input] if isinstance(request.input, str) else list(request.input)
    if not texts:
        raise HTTPException(status_code=400, detail="Input cannot be empty")
    if any(not str(text).strip() for text in texts):
        raise HTTPException(status_code=400, detail="Input texts cannot be empty")

    oversized = [len(t) for t in texts if len(t) > MAX_TEXT_CHARS]
    if oversized:
        raise HTTPException(
            status_code=413,
            detail=f"text of {max(oversized)} chars exceeds NER_MAX_TEXT_CHARS={MAX_TEXT_CHARS}",
        )

    if not _inflight.acquire(blocking=False):
        # Same backpressure contract as the OCR tier: shed rather than queue without
        # bound, and let the client turn it into a retryable Temporal error.
        raise HTTPException(status_code=503, detail="NER queue is full",
                            headers={"Retry-After": "5"})
    try:
        started = time.time()
        entities = _pool.submit(_extract, texts, request.entity_types).result()
        elapsed_ms = int((time.time() - started) * 1000)
        total_chars = sum(len(t) for t in texts)
        log.info("extracted %d entities from %d text(s), %d chars in %d ms",
                 len(entities), len(texts), total_chars, elapsed_ms)
        return NERResponse(
            data=entities,
            model=NLP_MODEL_ID,
            usage={"texts": len(texts), "characters": total_chars, "elapsed_ms": elapsed_ms},
        )
    finally:
        _inflight.release()
