# Metasearch MCP server

Web search across several engines at once, merged with Reciprocal Rank Fusion. Port
`21931`, container `hoover4-mcp-metasearch`, wired into the **full research agent** only.

Modelled on [`MikeLuu99/metasearch-rust`](https://github.com/MikeLuu99/metasearch-rust) —
the design worth taking is: scrape several engines in parallel, deduplicate on a
normalised URL, and merge with RRF so agreement between engines beats any one engine's
confidence.

## Tools

| Tool | Returns |
|---|---|
| `web_search(query, max_results=8, engines=None)` | RRF-merged results, each with the list of engines that returned it |
| `list_search_engines()` | which engines are configured and which are available |

## Why RRF, and what the `engines` field is for

```
score(url) = Σ over engines of  1 / (60 + rank_in_that_engine)
```

A page two engines both placed at rank 3 outranks one a single engine placed at rank 1.
That is the whole reason to run a metasearch rather than one engine, and it is why every
result carries the list of engines that found it: the model can see corroboration instead
of trusting one scraper.

Measured on the live server, searching for the Manticore MATCH operator documentation:

```
degraded engines: ['startpage']
  [brave,ddg,yahoo] 0.0899 https://manual.manticoresearch.com/Searching/Full_text_matching/Operators
  [brave,ddg,yahoo] 0.0824 https://emmanueloga.github.io/manticoresearch-manual/13-searching.html
  [ddg,yahoo]       0.0611 https://manual.manticoresearch.com/Searching/Expressions
```

Three engines agreed on the correct page and RRF put it first.

## Expect a scraper to rot

Every engine here is **HTML scraping with CSS selectors and no API key**. That is what
makes it free and what makes it fragile: assume at least one selector breaks within
months. Two things make that visible instead of silent.

* **The `degraded` field** on every response names the engines that returned nothing. In
  the run above, Startpage had already stopped matching — the search still worked, and
  said so. Never swallow a zero-result engine.
* **`METASEARCH_ENGINES`** turns a broken engine off without a rebuild:
  `METASEARCH_ENGINES=ddg,brave,yahoo`. Unknown names are dropped with a warning rather
  than raising, because a typo here must not take the server down.

If an engine is degraded, the fix is in `engines.py`: one `_parse_<engine>` function per
engine, each a handful of CSS selectors. `tests/test_engines.py` has a captured fragment
per engine so a selector edit fails a test rather than production.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `METASEARCH_ENGINES` | `ddg,brave,startpage,yahoo` | the set to query |
| `METASEARCH_ENGINE_TIMEOUT` | `8` | per engine, seconds; a slow engine degrades rather than delays |
| `METASEARCH_RRF_K` | `60` | the RRF constant; larger flattens rank differences |
| `MAX_RESULTS` | `8` | default result count |
| `SEARCH_SNIPPET_CHARS` | `400` | snippets land in the agent's context, so they are capped |

## Tests

```bash
docker exec hoover4-mcp-metasearch python -m pytest tests/ -q   # 20 tests
```

They cover URL normalisation, the RRF merge and the per-engine parsers against captured
HTML. They deliberately do **not** hit the live web: a suite that fails whenever an engine
changes its markup would be noise, and that event is what `degraded` reports at runtime.
