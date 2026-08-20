"""Synthetic Temporal throughput probe: no pipeline code, no I/O, just executions."""
import asyncio, sys, time, uuid
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

import os
Q = "probe-queue-" + uuid.uuid4().hex[:8]
CHILD_ACTS = os.environ.get("CHILD_ACTS", "3")

@activity.defn
async def noop(i: int) -> int:
    return i

@workflow.defn
class FanOut:
    @workflow.run
    async def run(self, n: int, conc: int) -> int:
        done = 0
        pending = set()
        it = iter(range(n))
        async def one(i):
            return await workflow.execute_activity(
                noop, i, start_to_close_timeout=timedelta(seconds=30))
        for _ in range(min(conc, n)):
            pending.add(asyncio.ensure_future(one(next(it))))
        while pending:
            fin, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            done += len(fin)
            for _ in fin:
                try:
                    pending.add(asyncio.ensure_future(one(next(it))))
                except StopIteration:
                    break
        return done

@workflow.defn
class ChildPerItem:
    @workflow.run
    async def run(self, n: int, conc: int) -> int:
        done = 0
        pending = set()
        it = iter(range(n))
        async def one(i):
            kids = int(CHILD_ACTS)
            return await workflow.execute_child_workflow(
                FanOut.run, args=[kids, max(1, kids)],
                id=workflow.info().workflow_id + "-c%d" % i,
                task_queue=workflow.info().task_queue)
        for _ in range(min(conc, n)):
            pending.add(asyncio.ensure_future(one(next(it))))
        while pending:
            fin, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            done += len(fin)
            for _ in fin:
                try:
                    pending.add(asyncio.ensure_future(one(next(it))))
                except StopIteration:
                    break
        return done

async def main():
    mode = sys.argv[1]
    n = int(sys.argv[2]); conc = int(sys.argv[3])
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    slots = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    client = await Client.connect("temporal:7233")
    ws = [Worker(client, task_queue=Q, workflows=[FanOut, ChildPerItem],
                 activities=[noop], max_concurrent_activities=slots,
                 max_concurrent_workflow_tasks=slots * 2)
          for _ in range(workers)]
    import contextlib
    async with contextlib.AsyncExitStack() as stack:
        for w in ws:
            await stack.enter_async_context(w)
        parents = int(sys.argv[6]) if len(sys.argv) > 6 else 1
        t0 = time.time()
        wf = FanOut.run if mode == "act" else ChildPerItem.run
        per = max(1, n // parents)
        got = sum(await asyncio.gather(*[
            client.execute_workflow(wf, args=[per, max(1, conc // parents)],
                                    id="probe-%d-%s" % (k, uuid.uuid4().hex[:8]),
                                    task_queue=Q)
            for k in range(parents)]))
        dt = time.time() - t0
        unit = "activities" if mode == "act" else "child workflows"
        print("%s: %d %s in %.1fs = %.1f/s  (workers=%d slots=%d conc=%d parents=%d)"
              % (mode, got, unit, dt, got / dt, workers, slots, conc, parents))

if __name__ == "__main__":
    asyncio.run(main())
