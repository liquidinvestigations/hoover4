FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.4.2 pyyaml==6.0.3 zstandard==0.24.0
