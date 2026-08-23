"""Code shared by the MCP servers in `main_services/agents/`.

Things live here because two or more servers need them and a second copy would
drift: the chat-artifact writer (metasearch writes `search_detail`, the browser router
writes `page_capture`), the rerank client with its circuit breaker (metasearch and
collection search), the RRF/floor fusion machinery (same two), the query-side embedding
client, the S3 helper, and the batching mechanics every list-taking tool repeats. List
coercion, the divided character budget and the corrective note.

**This package is vendored into each image, not installed from an index.** The Dockerfiles
build with `main_services/agents` as their context and `COPY ./agent_common/`. That is why
its dependencies are declared in each consuming `pyproject.toml` rather than here alone:
`pip install ./agent_common` runs before the server's own install in every image.
"""

__all__ = ["artifacts", "batching", "embeddings", "fusion", "s3_store", "rerank"]
