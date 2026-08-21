# Browser launch failures

A library that "cannot connect to the browser" may never have launched one. nodriver treats
an explicitly configured `host` + `port` as *attach to something already running* and
silently skips the launch — its error then blames your privileges.

Same family: its connect loop allows about 2.7 s, and Chromium with two MV3 extensions needs
5–6 s.

Before believing a connection error, prove the thing you are connecting to exists, from
inside the container:

    docker exec hoover4-mcp-browser curl -sS http://127.0.0.1:<port>/json/version

In this area an error message routinely names the wrong half of the problem.

Chromium also writes a continuous stream of D-Bus and GCM errors to stderr. On a `PIPE`
nobody reads, that pipe fills and the browser blocks on write, which reads as a hang in the
calling code. Drain it or send it to `DEVNULL`.
