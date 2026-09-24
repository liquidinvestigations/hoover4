#!/bin/sh
# Entrypoint of temporal-cassandra. It writes the chunk cache size into cassandra.yaml
# and then runs the image's own entrypoint.
#
# Cassandra 3.11 reads file_cache_size_in_mb only from cassandra.yaml, and no
# environment variable of the image sets it. The file is inside the image and not in
# the data volume, so this edit runs again at each container start.
#
# The edit writes with sed to a temporary file and copies it back with cat, as the
# image's own _sed-in-place does. The pattern matches the commented or the active
# setting line only. A comment further down names the key followed by a comma.
set -eu

conf="${CASSANDRA_CONF:-/etc/cassandra}/cassandra.yaml"
cache_mb="${CASSANDRA_CHUNK_CACHE_MB:-}"

if [ -n "$cache_mb" ]; then
    case "$cache_mb" in
        *[!0-9]*)
            echo "hoover4-cassandra-entrypoint: CASSANDRA_CHUNK_CACHE_MB is not a whole number: $cache_mb" >&2
            exit 1
            ;;
    esac
    tmp="$(mktemp)"
    sed "s/^#\? *file_cache_size_in_mb:.*/file_cache_size_in_mb: ${cache_mb}/" "$conf" > "$tmp"
    cat "$tmp" > "$conf"
    rm -f "$tmp"
    if ! grep -q "^file_cache_size_in_mb: ${cache_mb}\$" "$conf"; then
        echo "hoover4-cassandra-entrypoint: no file_cache_size_in_mb line in $conf" >&2
        exit 1
    fi
fi

exec docker-entrypoint.sh cassandra -f
