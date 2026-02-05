#!/bin/bash
set -ex
. .env.development

echo clickhouse: $CLICKHOUSE_URL
echo manticore: $MANTICORE_URL

time dx serve --fullstack --package frontend --platform web