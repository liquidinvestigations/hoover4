# AI services and their CPU twins

The accelerated tier is a **separate stack**: its own compose project, its own private
network, and no dependency on the main stack in either direction. Nothing in it calls back
into the pipeline; the pipeline reaches it over published ports only.

`ai_services/README.md` is the operator's document for that tier: overlays, flags and the GPU
preflight. This page is the shape and the reason.

## Contents

- [What is in the tier](#what-is-in-the-tier)
- [The CPU twins live on the main side](#the-cpu-twins-live-on-the-main-side)
- [How a caller falls back without branching](#how-a-caller-falls-back-without-branching)
- [The security constraint is structural](#the-security-constraint-is-structural)
- [Where the accelerated work actually goes](#where-the-accelerated-work-actually-goes)

## What is in the tier

Three optional overlays, each selected by a configuration flag:

| service | serves | used by |
|---|---|---|
| the model server | embeddings, reranking, named-entity recognition | the entity stage, the chunk-and-embed stage, search reranking |
| the local model server | an OpenAI-compatible chat model | the chat agents, when a self-hosted model is selected |
| accelerated OCR | optical character recognition over HTTP | the parse stage, for image and scanned-PDF pages |

All three are off by default. With none of them enabled the stack runs end to end: a cloud
provider serves the chat, and the CPU twins serve the rest.

## The CPU twins live on the main side

`main_services/ocr_tesseract/` and `main_services/ner_spacy/` are the CPU counterparts of the
accelerated OCR and entity services. **They are on the main side deliberately. That is the
whole point of a twin.** A fallback that lives with the thing it is a fallback for is not a
fallback.

Two properties make them usable as one:

- **They speak the same HTTP contract as their accelerated counterpart**, request and
  response, so the caller sends one shape to either.
- **Their model and language data is baked into the image.** A twin that needs the internet
  to come up is not a fallback either; whatever the network is doing when the accelerated
  tier is unreachable is likely to be doing it to the download too.

Each twin's health endpoint reports what it can actually serve (which languages the OCR
image carries, which model the entity service loaded), so a caller can tell a service that
is up from a service that is up and useless.

## How a caller falls back without branching

`main_services/processing/tasks/remote.py` owns the choice. Because the contracts are
identical, the call site does not know which tier answered: the client tries the accelerated
endpoint, and on a connect failure or a circuit that has opened it uses the twin. The
connect timeout, the fallback switch and how long a broken endpoint stays out of rotation are
configuration keys, listed in
[Configuration reference](../operations/Configuration_Reference.md).

**Detection latency is deliberately not tied to work duration.** The connect deadline is a
few seconds while the read deadline is minutes, because a dead host must be noticed
immediately and a slow inference must not be interrupted. A single total timeout cannot do
both.

## The security constraint is structural

The model server and the OCR service are **unauthenticated**, and the local model server's
API key is its only protection. The tier is therefore bound to a private interface and the
two hosts share a private network. An exposed local model server is a free accelerator for
anyone who finds it; an exposed OCR endpoint is a free denial-of-service surface.

The bind address is a configuration key, not a literal. Which address a given deployment uses
is in `INFRASTRUCTURE_INVENTORY.md` at the repository root (local and gitignored), and never
in this tree.

## Where the accelerated work actually goes

Two facts worth having before sizing anything:

**Embedding is the largest single cost.** Chunking and embedding run **per text variant**: a
file with native text and two OCR variants is three chunk sets and three vector sets. That is
the accepted cost of complete attribution (a search hit can be traced to the extractor that
produced the text it matched), and it is why the embedding stage dominates the tier's load.

**Throughput is bandwidth-bound rather than compute-bound at small batch sizes.** Per-stream
decode stays flat out to sixteen concurrent streams, so batching several requests together is
nearly free and serialising them wastes the hardware.

The vectors this tier produces are the **durable** store in ClickHouse. The search engine's
nearest-neighbour tables are a disposable in-memory copy that the indexing stage rebuilds
from them, which is what makes a lost search volume a re-index rather than a re-embed.
