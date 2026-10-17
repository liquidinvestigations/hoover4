FROM python:3.11.14-slim
WORKDIR /repo
COPY requirements.txt /tmp/docs-requirements.txt
RUN pip install --no-cache-dir -r /tmp/docs-requirements.txt
ENTRYPOINT ["python3", "scripts/docs/check.py"]
