# spaCy NER (CPU twin)

The CPU counterpart of the GPU tier's named-entity recognition. It speaks the same HTTP
contract, so the pipeline falls back to it with no branching at the call site.

The model and its language data are baked into the image. That is the requirement, not an
optimisation: a fallback that needs the internet to come up is not a fallback.

- `ner_spacy.py` — the server
- `Dockerfile` — the image, including the model download at build time
