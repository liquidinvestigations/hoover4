#!/bin/bash
set -ex

cd "$(dirname "${BASH_SOURCE[0]}")"


. .env.development

echo clickhouse: $CLICKHOUSE_URL
echo manticore: $MANTICORE_URL

time dx serve --fullstack --package frontend --platform web