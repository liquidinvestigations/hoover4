#!/usr/bin/env bash
# Run the research agent's own unit tests.
#
# They need a container of their own rather than a `docker exec` like every other suite
# here, and the reason is worth knowing: the agent's Dockerfile installs with
# `poetry install --without dev` and never copies `tests/`, so the running container has
# neither pytest nor the tests. Nothing else reaches this directory either.
# `pytest-agents.sh` loops over the five MCP server containers, and `pytest-unit.sh` runs in
# hoover4-worker, which has no langchain_core. Without this script these tests execute in
# no suite at all.
#
# So: the built image, the source tree mounted read-only over it, and pytest installed
# into the throwaway container. The image is not modified and nothing is left behind.
#
# `--asyncio-mode=auto` because the async tests declare no marker and pytest-asyncio
# skips them silently otherwise, three of them reported as passed while running nothing.
#
# One test is deselected by default: test_agent_interactive_chat opens a connection to the
# live LLM endpoint, so it is an integration test in a unit directory and fails with a
# ConnectError wherever that endpoint is not reachable. Pass a target to override.
set -uo pipefail
target="${1:-tests}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
agent_dir="${repo_root}/main_services/agents/research_agent"

if ! docker image inspect hoover4-research-agent:local >/dev/null 2>&1; then
    echo "FAIL: hoover4-research-agent:local is not built"
    exit 1
fi

# `sh -c`, never `sh -lc`: the interpreter is a virtualenv that PATH is the only thing
# pointing at, and a login shell rebuilds PATH from /etc/profile.
docker run --rm -v "${agent_dir}":/src:ro -w /src hoover4-research-agent:local sh -c "
    pip install --quiet pytest pytest-asyncio 2>&1 | tail -1
    python -m pytest ${target} -q --asyncio-mode=auto -p no:cacheprovider \
        --deselect tests/test_agent.py::test_agent_interactive_chat 2>&1 | tail -20
"
