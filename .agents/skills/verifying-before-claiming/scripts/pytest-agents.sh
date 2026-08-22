#!/usr/bin/env bash
# Run each MCP server image's unit tests, inside that image.
#
# The pipeline's suite (pytest-unit.sh) runs in hoover4-worker and never reaches these:
# the agents live in their own images, and `agent_common/` is vendored into every one of
# them rather than installed from an index. Its tests are copied to `tests/shared/` in each
# image so this one target reaches both the server's tests and the shared package's --
# a shared-package regression otherwise lands silently in every image at once.
#
# Optional argument narrows the target within each container, e.g. `tests/shared`.
set -uo pipefail
target="${1:-tests}"
failed=0

for container in hoover4-mcp-browser hoover4-mcp-collections hoover4-mcp-metasearch \
                 hoover4-mcp-whois hoover4-mcp-todo; do
    if ! docker ps --format '{{.Names}}' | grep -qx "${container}"; then
        echo "SKIP ${container}: not running"
        continue
    fi
    echo "== ${container} =="
    # `sh -c`, never `sh -lc`: a login shell rebuilds PATH from /etc/profile, and the
    # whois image's interpreter is a virtualenv that PATH is the only thing pointing at.
    # Under -l that container reports pytest as not installed while it is.
    if ! docker exec -w /app "${container}" sh -c \
        "python -m pytest ${target} -q 2>&1 | tail -15"; then
        failed=1
    fi
done

exit "${failed}"
