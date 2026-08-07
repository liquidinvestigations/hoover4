"""Code shared by the MCP servers in `main_services/agents/`.

Three things live here because two or more servers need them and a second copy would
drift: the chat-artifact writer (metasearch writes `search_detail`, the browser router
writes `page_capture`), the rerank client with its circuit breaker (metasearch today,
collection search in Phase 4), and the MinIO helper both of those sit on.

**This package is vendored into each image, not installed from an index.** The Dockerfiles
build with `main_services/agents` as their context and `COPY ./agent_common/`. That is why
its dependencies are declared in each consuming `pyproject.toml` rather than here alone —
`pip install ./agent_common` runs before the server's own install in every image.
"""

__all__ = ["artifacts", "minio_store", "rerank"]
