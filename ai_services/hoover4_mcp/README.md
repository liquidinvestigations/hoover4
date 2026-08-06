# Hoover4 MCP servers

The tool servers the research agents connect to. Each is a standalone FastMCP server in
its own container, reachable only on `127.0.0.1` and joined to the shared `hoover4`
podman network. The agents discover tools over HTTP at `/mcp`.

| Server | Directory | Port | Used by | What it does |
|---|---|---|---|---|
| Collection search | [`collection_search_server/`](collection_search_server/README.md) | 8085 | both agents | ACL-bounded full-text search of the user's own documents (Manticore + ClickHouse) |
| Metasearch | [`metasearch_server/`](metasearch_server/README.md) | 8086 | full research | Web search over four engines, merged with reciprocal rank fusion |
| Browser | [`browser_use_server/`](browser_use_server/README.md) | 8087 | full research | Reads a page with a real headless Chromium, one isolated browser context per chat |
| DuckDuckGo | [`ddg_search_server/`](ddg_search_server/) | 8889 | full research | Single-engine web/news search. Superseded by metasearch but cheap to keep |
| Wikipedia | [`wikipedia_search_server/`](wikipedia_search_server/) | 8093 | full research | Article and summary lookup |
| WHOIS | [`whois_search_server/`](whois_search_server/) | 8092 | full research | Domain registration lookup |

**The internal-search agent gets the collection server only.** A chat about the user's
own documents must not quietly turn into a web search — see
[`../hoover4_research_agent/README.md`](../hoover4_research_agent/README.md).

The Milvus MCP server was removed: nothing in the pipeline ever wrote vectors, so it
searched an empty index. See [`../README.md`](../README.md) for what a vector stage would
have to build first.

## Two patterns in this directory

New servers follow **`collection_search_server`**: a plain `python:3.12-slim` image,
`pip install .`, a `@mcp.custom_route("/health")` endpoint and `mcp.run(transport="http")`.
It builds in seconds and has no build toolchain.

`ddg_search_server`, `wikipedia_search_server` and `whois_search_server` are older and use
a Poetry multi-stage build. They work; do not copy them for anything new.

## Running and testing

Everything comes up with the tier:

```bash
../start-docker.sh                                  # whole AI tier
../start-docker.sh --build hoover4-mcp-collections  # rebuild one service
```

Note that a `--build` alone may leave the old container running against the new image.
Follow it with an explicit recreate:

```bash
cd .. && docker compose up -d --force-recreate hoover4-mcp-collections
```

Each image carries its own tests:

```bash
docker exec hoover4-mcp-collections python -m pytest tests/ -q
docker exec hoover4-mcp-metasearch  python -m pytest tests/ -q
docker exec hoover4-mcp-browser     python -m pytest tests/ -q
```

## Authentication

Every server honours `MCP_SHARED_SECRET` as an `Authorization: Bearer` token. When it is
empty the servers accept any caller and log a warning — survivable only because the ports
are bound to loopback.

The collection server additionally enforces a per-request ACL supplied by its caller in
`X-Hoover4-Collections`. It never derives permissions itself; see
[`collection_search_server/collection_search_server/acl.py`](collection_search_server/collection_search_server/acl.py)
for why that split matters.

A third header, `X-Hoover4-Chat-Session`, travels alongside those two but grants no
authority — it is an **isolation key**, used only by the browser server to give each
conversation its own Chromium context. Do not make anything an access decision on it: it
is a conversation id, and unlike the ACL headers nothing verifies who it belongs to.
