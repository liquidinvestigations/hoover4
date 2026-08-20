"""A sliding window for workflows that fan out over many items.

The alternative is a barrier: start K children, `gather` all K, start the next K. That
makes every batch cost its slowest member, and the pipeline's per-file wall time has a
p99 fifteen times its p50 -- a handful of large files idle a whole batch for tens of
seconds while a few slots do nothing. A window keeps K in flight and starts a
replacement the moment one finishes, so the run costs the *sum* of the work divided by
K rather than the *sum of the maxima* of each batch.

Determinism is the reason this is not two lines of `asyncio`. `workflow.wait` is the
replay-safe form of `asyncio.wait`; iteration over its `done` list is put back into item
order before anything that issues a command, so a replay makes the same decisions in the
same sequence no matter what order completions arrived in.
"""

import asyncio
from typing import Any, Callable, List, Sequence

from temporalio import workflow


async def run_with_window(factories: Sequence[Callable[[], Any]], limit: int) -> List[Any]:
    """Run every factory with at most `limit` in flight; results in factory order.

    Each factory is called once, when its slot opens, and must return an awaitable --
    typically `workflow.execute_activity` or `workflow.execute_child_workflow`. A failure
    is returned in place, the way `gather(return_exceptions=True)` does, so a caller that
    records per-item errors keeps working unchanged.
    """
    total = len(factories)
    results: List[Any] = [None] * total
    if total == 0:
        return results
    limit = max(1, min(limit, total))

    pending: List[Any] = []
    index_of: dict = {}
    started = 0
    while started < total or pending:
        while started < total and len(pending) < limit:
            fut = asyncio.ensure_future(factories[started]())
            pending.append(fut)
            index_of[id(fut)] = started
            started += 1
        done, still = await workflow.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        pending = list(still)
        for fut in sorted(done, key=lambda f: index_of[id(f)]):
            idx = index_of.pop(id(fut))
            try:
                results[idx] = fut.result()
            except Exception as exc:   # noqa: BLE001 -- mirrored from gather(return_exceptions)
                results[idx] = exc
    return results
