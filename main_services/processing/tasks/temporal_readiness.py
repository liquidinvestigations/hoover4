"""Wait until Temporal and its database are ready before a workflow starts.

A start that reaches Temporal while its Cassandra store restarts fails with
`shard status unknown`, and the caller gets that error with no retry. Every CLI command
that starts a top-level workflow therefore connects with :func:`connect_when_ready`,
which runs :func:`wait_for_temporal` after the connect and before any other call.

The gate probes Temporal every second. One probe is four calls, in this order, each
with a timeout of ``PROBE_TIMEOUT_SECONDS``:

1. the frontend health check;
2. a describe of the namespace ``default``, which reads Cassandra;
3. a list of one workflow;
4. a describe of the collector workflow ``collect-eta-samples``, which reads a history
   shard. A ``NOT_FOUND`` answer counts as good, because the collector does not exist on
   a stack whose worker has not started it yet.

Temporal is ready when every probe is good for ``READY_STABLE_SECONDS`` without a break.
A bad probe starts the count again. After ``READY_DEADLINE_SECONDS`` the gate raises
:class:`TemporalNotReady` with ``READY_ERROR_TEXT``, and the workflow does not start.

The worker singletons in ``tasks/run_worker.py`` and the ``IndexDatasetPlan`` starts of
the reindex activity do not use the gate. A worker starts them after it connects, and
they are not a request from a person.

The constants and the error text are mirrored in
``website/backend/src/temporal_ready.rs``. Change both files together. A unit test in
each runtime reads the other file and compares the values.
"""

import asyncio
import time
from datetime import timedelta

# Mirrored in website/backend/src/temporal_ready.rs.
READY_STABLE_SECONDS = 5
READY_DEADLINE_SECONDS = 60
PROBE_INTERVAL_SECONDS = 1
PROBE_TIMEOUT_SECONDS = 5
COLLECTOR_WORKFLOW_ID = "collect-eta-samples"
READY_ERROR_TEXT = (
    "Temporal did not stay ready for 5 s within 60 s, so the workflow was not started. "
    "Last error: {last_error}"
)

#: The limit on `Client.connect` for a start path. Not mirrored: the website talks to
#: Temporal over HTTP and connects per request.
CONNECT_TIMEOUT_SECONDS = 30

#: The limit on each start request of a start path, given to the SDK as `rpc_timeout`.
START_RPC_TIMEOUT = timedelta(seconds=30)

TEMPORAL_ADDRESS = "temporal:7233"


class TemporalNotReady(RuntimeError):
    """Temporal did not stay ready for the stable time within the deadline."""


async def _call(awaitable):
    return await asyncio.wait_for(awaitable, PROBE_TIMEOUT_SECONDS)


async def probe(client) -> None:
    """Run the four probe calls in order. Raise at the first call that is not good."""
    from temporalio.api.workflowservice.v1 import (
        DescribeNamespaceRequest,
        ListWorkflowExecutionsRequest,
    )
    from temporalio.service import RPCError, RPCStatusCode

    rpc_timeout = timedelta(seconds=PROBE_TIMEOUT_SECONDS)
    if not await _call(client.service_client.check_health(timeout=rpc_timeout)):
        raise RuntimeError("the Temporal frontend reports that it is not serving")
    await _call(client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace="default"), timeout=rpc_timeout,
    ))
    await _call(client.workflow_service.list_workflow_executions(
        ListWorkflowExecutionsRequest(namespace="default", page_size=1), timeout=rpc_timeout,
    ))
    try:
        await _call(client.get_workflow_handle(COLLECTOR_WORKFLOW_ID).describe(
            rpc_timeout=rpc_timeout,
        ))
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise


async def wait_for_temporal(client, clock=time.monotonic, sleep=asyncio.sleep,
                            probe_once=probe) -> None:
    """Return when every probe is good for 5 s. Raise `TemporalNotReady` after 60 s.

    The deadline is checked after each probe, so the gate can end one probe after
    60 s. A probe stops at its first failed call, and each call has a 5 s limit, so one
    probe takes at most 4 x 5 s = 20 s.
    """
    deadline = clock() + READY_DEADLINE_SECONDS
    good_since = None
    last_error = "no probe finished"
    while True:
        try:
            await probe_once(client)
            if good_since is None:
                good_since = clock()
            if clock() - good_since >= READY_STABLE_SECONDS:
                return
        except Exception as exc:  # noqa: BLE001 - any failed call resets the good run
            good_since = None
            last_error = f"{type(exc).__name__}: {exc}"
        if clock() >= deadline:
            raise TemporalNotReady(READY_ERROR_TEXT.format(last_error=last_error))
        await sleep(PROBE_INTERVAL_SECONDS)


async def connect_when_ready(address: str = TEMPORAL_ADDRESS):
    """Connect within 30 s, then wait for the gate. Return the client."""
    from temporalio.client import Client

    client = await asyncio.wait_for(Client.connect(address), CONNECT_TIMEOUT_SECONDS)
    await wait_for_temporal(client)
    return client
