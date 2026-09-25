#!/usr/bin/env bash
# Run the AgentRun workflow cases against the stack's Temporal and ClickHouse.
#
# Inside the worker container, the script runs the integration cases of
# tests/integration/test_agent_run_workflow.py. Each case starts a test worker on task queues
# of its own, with the real AgentRun workflow and activities, and a local stub in place of the
# agent service and the browser server. Each case writes rows under a username of its own and
# deletes them at the end.
#
# The cases: a turn with two parallel calls and its rows, a duplicate start, a stopped turn
# that closes in open_run, an agent error that ends the run as failed, the nag rounds, and
# delegation: fan-in once, a depth 1 delegation to depth 2, the run budget, a retry of the
# delegation, a duplicate child start, a child started after a stop, and the agent run sweep.
# Two cases cover the lifecycle: a stop during the stream writes nothing after the ending,
# and the sweep ends the children of a failed parent. Two cases cover the plan layer: a flat plan
# through review, a rejection, an approval and completion, with no workflow open during review,
# and the refusal of a third correction of one section. Each case terminates the workflows it
# started before it deletes its rows.
#
# Arguments: optional pytest arguments, for example -k stopped. Settings: AGENT_RUN_CONTAINER
# (default hoover4-worker). Exit status 0 when every case passes, else the pytest status.
set -uo pipefail

container="${AGENT_RUN_CONTAINER:-hoover4-worker}"

docker exec "$container" sh -lc \
    'cd /app && timeout 600 uv run pytest tests/integration/test_agent_run_workflow.py --integration -q "$@" 2>&1' \
    _ "$@"
