#!/bin/bash
# Check the migration table parser with names reused by RENAME statements.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
parser_source="${VERIFY_STACK_SOURCE:-$SCRIPT_DIR/verify-stack.sh}"
source <(awk '/^tables_expected\(\) \{/ { copy=1 } copy { print } copy && /^}/ { exit }' \
    "$parser_source")

fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
cat > "$fixture/00001.sql" <<'SQL'
CREATE TABLE IF NOT EXISTS operations;
CREATE TABLE IF NOT EXISTS operations_row_version;
RENAME TABLE operations TO operations_old,
             operations_row_version TO operations;
DROP TABLE operations_old;
CREATE TABLE IF NOT EXISTS processing_errors;
CREATE TABLE IF NOT EXISTS processing_errors_next;
RENAME TABLE processing_errors TO processing_errors_legacy,
             processing_errors_next TO processing_errors;
DROP TABLE processing_errors_legacy;
CREATE TABLE IF NOT EXISTS unexpected;
SQL

expected='operations processing_errors schema_versions unexpected '
actual=$(tables_expected "$fixture")
if [ "$actual" != "$expected" ]; then
    printf 'unexpected table set: [%s], expected [%s]\n' "$actual" "$expected" >&2
    exit 1
fi
printf 'migration table parser retained the final table set\n'
