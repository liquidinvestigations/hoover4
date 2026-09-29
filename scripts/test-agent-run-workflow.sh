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
# that closes in open_run, an agent error that ends the run as failed, identical calls that
# all run, the browser chain, the empty-reply retry, the step limit with no model call (also
# across continue-as-new and in a sub-agent), an answer with open todo items, the citation
# round, and the storage of a plan's sections: a duplicate child start, a child started after
# a stop, a stop that races the last child, a stop during the dispatch, and the run sweep. A
# stop during the stream writes nothing after the ending, and the sweep ends the children of
# a failed organizer. The plan cases: review, rejection, approval and completion with no
# workflow open during review, a nested tree with one sub-agent a section on the frozen
# model, a failed section beside a completed one, an organizer failure, a competing
# organizer start, and a report failure that the fan-in repairs. The ask_user cases verify
# the question flow. Each case terminates its workflows before it deletes its
# rows.
#
# Arguments: optional pytest arguments, for example -k stopped. Settings: AGENT_RUN_CONTAINER
# (default hoover4-worker). Exit status 0 when every case passes, else the pytest status.
set -uo pipefail

container="${AGENT_RUN_CONTAINER:-hoover4-worker}"

docker exec "$container" sh -lc \
    'cd /app && timeout 600 uv run pytest tests/integration/test_agent_run_workflow.py --integration -q "$@" 2>&1' \
    _ "$@"
