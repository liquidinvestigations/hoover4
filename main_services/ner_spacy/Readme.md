# Serve named entities with spaCy on CPU.

[The server](ner_spacy.py) implements the NER request contract used by the pipeline.
[The Dockerfile](Dockerfile) packages the model and language data in the image.
Enable the service when the selected NER configuration requires it.

[The NER client](../processing/tasks/P4_extract_entities/extract_ner_from_text.py) can supply this endpoint after a configured GPU endpoint.
[The remote client](../processing/tasks/remote.py) selects fallback only under its connection-failure rules.
An unavailable primary endpoint and a disabled primary capability have different behavior.
An empty primary NER endpoint skips NER before attempting fallback.
[AI architecture](../../docs/architecture/AI_Services.md) describes provider selection and disabled capabilities.
