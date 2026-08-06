# spaCy NER over HTTP. CPU only, deliberately: this is the twin that keeps working when
# the GPU host is unreachable, so it must not depend on it in any way.
FROM python:3.13-slim

ARG SPACY_MODEL=xx_ent_wiki_sm

WORKDIR /app

# The model is baked into the image, not downloaded at start. A first-run download is
# what turned EasyOCR's cold start into a model-download storm across seven worker
# processes, and a CPU twin that needs the internet to come up is not a fallback.
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.34" \
        "pydantic>=2.9" \
        "spacy>=3.8" \
    && python -m spacy download ${SPACY_MODEL}

COPY ner_spacy.py /app/ner_spacy.py

ENV HOST=0.0.0.0 \
    PORT=8000 \
    SPACY_MODEL=${SPACY_MODEL}

EXPOSE 8000

# One uvicorn worker: concurrency is bounded inside the app, and a second process would
# double both the thread pool and the loaded model's memory behind the app's back.
CMD ["sh", "-c", "uvicorn ner_spacy:app --host ${HOST} --port ${PORT} --workers 1"]
