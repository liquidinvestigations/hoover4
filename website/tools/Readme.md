# Website diagnostics

Single-question scripts, each answering something a screenshot cannot.

| script | answers |
|---|---|
| `capture_screenshots.py` | drives a plain browser over a page list and writes a PNG, a DOM text snapshot and console errors per page |
| `chat_observer.py` | drives a chat conversation to completion and writes its screenshots, DOM snapshots and history checks; imports its browser helpers from `capture_screenshots.py` rather than copying them |
| `count_whoami.py` | how many identity requests one navigation costs |
| `check_session_gate.py` | which of the session gate's three states a page settled in |
| `console_whitelist.txt` | console messages the screenshot run treats as expected |

All of them run by copying the script into the browser container and executing it there; the
container has no bind mounts, so both the script and its output travel by file copy. They do
not use the browser MCP endpoint, which refuses internal hosts by design.

## Local test login inputs

Agents can read `../TEST_LOGIN.env` for a browser work package.
The file stores the login URL, site URL, username, and password.
Copy `../TEST_LOGIN.env.example` to create it.
The repository ignores the account file. The example contains empty values.
`../take-screenshots.sh` and `../observe-chat.sh` load the file automatically, beside a
`--username`/`--password` pair and a `HOOVER4_TEST_USERNAME`/`HOOVER4_TEST_PASSWORD`
environment pair that both take precedence over it. Neither wrapper reads a target from
this file; a target comes from `--target`, `HOOVER4_SITE_URL`, or the built-in local
default.
