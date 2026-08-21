# Website diagnostics

Single-question scripts, each answering something a screenshot cannot.

| script | answers |
|---|---|
| `capture_screenshots.py` | drives a plain browser over a page list and writes a PNG, a DOM text snapshot and console errors per page |
| `count_whoami.py` | how many identity requests one navigation costs |
| `check_session_gate.py` | which of the session gate's three states a page settled in |
| `console_whitelist.txt` | console messages the screenshot run treats as expected |

All of them run by copying the script into the browser container and executing it there; the
container has no bind mounts, so both the script and its output travel by file copy. They do
not use the browser MCP endpoint, which refuses internal hosts by design.
