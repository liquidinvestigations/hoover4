# PDF search service

This service finds keywords in a PDF and gives the position of each match on its page.
The website calls it for in-document search, see
[Website_Backend.md](../../docs/architecture/Website_Backend.md#in-document-pdf-search).

| File | Content |
|---|---|
| [server.py](server.py) | The HTTP server on port 13500. It starts one search process for each request and runs at most 4 at the same time. |
| [search.py](search.py) | The search in one process, with the native PDFium library from `pypdfium2`. |
| [tests/](tests) | Unit tests for the match context and the result form. |

## Request and response

Send `POST /?keywords=<JSON array of strings>` with the PDF bytes as the body.
The response is a JSON array with one `{"keyword", "result_set": {"results", "total"}}` for each keyword.
Each result has `pageIndex`, `charIndex`, `charCount`, `rects` and `context`.
`GET /health` returns 200 when the server answers.

| Status | Cause |
|---|---|
| 400 | The keywords or the body are missing. |
| 500 | The search process failed. `details` gives the last line of its error output, or its exit code. A negative exit code is the signal that stopped it. |
| 504 | The search process ran for more than 150 s. |

## Memory

The search process exits after its request, so the operating system frees all memory that PDFium used.
The search loads one page at a time and closes it before the next page.
The server writes the request body to a temporary file, so the body does not stay in the server memory.
The compose file sets a fixed container memory limit of 12 GB.

## Tests

Run the unit tests in the container:

```
docker exec hoover4-pdf-search python -m pytest -q /app/tests
```
