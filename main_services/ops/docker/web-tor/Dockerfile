FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tor ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY start.py /usr/local/bin/start-web-tor
USER debian-tor
CMD ["python", "/usr/local/bin/start-web-tor"]
