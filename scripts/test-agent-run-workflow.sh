#!/usr/bin/env bash
# Run the AgentRun workflow cases against the stack's Temporal and ClickHouse.
#
# Inside the worker container, the script runs the integration cases of
# tests/integration/test_agent_run_workflow.py. Each case starts a test worker on task queues
# of its own, with the real AgentRun workflow and activities, and a local stub in place of the
# agent service and the browser server. Each case writes rows under a username of its own and
# deletes them at the end.
#
# The cases verify parallel calls, duplicate starts, stopped turns, agent errors,
# browser call order, empty replies, step limits, todos, citations, questions, and run cleanup.
# Each case terminates its workflows before it deletes its rows.
#
# Arguments: optional pytest arguments, for example -k stopped. Settings: AGENT_RUN_CONTAINER
# (default hoover4-worker). Exit status 0 when every case passes, else the pytest status.
set -uo pipefail

container="${AGENT_RUN_CONTAINER:-hoover4-worker}"

docker exec "$container" sh -lc \
    'cd /app && timeout 600 uv run pytest tests/integration/test_agent_run_workflow.py --integration -q "$@" 2>&1' \
    _ "$@"
