#!/bin/bash
set -ex

cd "$(dirname "${BASH_SOURCE[0]}")"


. .env.development

echo clickhouse: $CLICKHOUSE_URL
echo manticore: $MANTICORE_URL

# A hook called conditionally or inside a closure shifts every hook index after it on the
# render that adds it and traps the WebAssembly runtime -- the page paints and then nothing
# re-renders and no handler fires. `cargo check` cannot see it and the release build says
# only `RuntimeError: unreachable`, so gate the serve on the one tool that names the site.
dx check --package frontend

time dx serve --fullstack --package frontend --platform web