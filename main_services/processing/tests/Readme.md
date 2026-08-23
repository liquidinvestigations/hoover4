# Pipeline tests

| path | needs |
|---|---|
| `unit/` | nothing running, pure logic, run inside the worker container |
| `integration/` | a live stack |
| `fixtures/` | small inputs checked in beside the tests |
| `conftest.py` | shared fixtures and collection settings for both |

The migration parity test lives in `unit/` and covers the three ways the migration runner's
naive `;` split breaks: a semicolon inside a quoted comment, a semicolon inside a `--`
comment, and prose after the final terminator, which reaches the database as an empty query.
