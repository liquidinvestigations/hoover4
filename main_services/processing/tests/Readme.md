# Pipeline tests

| path | needs |
|---|---|
| `unit/` | nothing running, pure logic, run inside the worker container |
| `integration/` | a live stack |
| `fixtures/` | small inputs checked in beside the tests |
| `conftest.py` | shared fixtures and collection settings for both |

Format regression tests read `<HOOVER4_TESTDATA>/file-types`.
`HOOVER4_TESTDATA` defaults to the mounted testdata repository's `data` folder.
Set this variable when the mount differs.
Missing format samples produce recorded skips.

Viewer query tests read the current website source.
They use the processing worker's read-only backend source mount when the repository root is unavailable.
Set `HOOVER4_REPO_ROOT` to a mounted or copied repository root when the worker only mounts processing source.
The lifecycle test verifies that disabled NER produces no NER processing error.

Run the authenticated Manticore backup test in `hoover4-ops`.
The processing worker has no datastore backup mounts.

```sh
docker exec -w /app hoover4-ops uv run pytest tests/integration/test_manticore_authenticated_backup.py --integration -q
```

The migration parity test lives in `unit/` and covers the three ways the migration runner's
naive `;` split breaks: a semicolon inside a quoted comment, a semicolon inside a `--`
comment, and prose after the final terminator, which reaches the database as an empty query.

`tests/integration/test_location_refresh.py` covers known bytes that gain a disk or
archive location, and bounded recovery against an isolated stale index. It needs the
live stack.
