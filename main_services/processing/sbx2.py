"""Time a real sandbox workflow-instance creation, with and without passthrough."""
import sys, time
sys.path.insert(0, "/app")
import asyncio
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions
from temporalio.worker._workflow_instance import WorkflowInstanceDetails
from temporalio.worker._interceptor import Interceptor
from temporalio import workflow
import temporalio.converter
from tasks.P3_parse_files.workflows import ParseSingleFile

defn = workflow._Definition.must_from_class(ParseSingleFile)

def timeit(runner, n=12):
    runner.prepare_workflow(defn)
    det = WorkflowInstanceDetails(
        payload_converter_class=temporalio.converter.default().payload_converter_class,
        failure_converter_class=temporalio.converter.default().failure_converter_class,
        interceptor_classes=[],
        defn=defn,
        info=None,
        randomness_seed=1,
        extern_functions={},
        disable_eager_activity_execution=False,
        worker_level_failure_exception_types=[],
    )
    t = time.time()
    ok = 0
    for _ in range(n):
        try:
            runner.create_instance(det)
            ok += 1
        except Exception as e:
            return "create_instance failed: %s: %s" % (type(e).__name__, e)
    return "%.1f ms per instance (%d ok)" % (1000 * (time.time() - t) / n, ok)

async def main():
    print("default        :", timeit(SandboxedWorkflowRunner()))
    print("passthrough    :", timeit(SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "tasks", "database"))))

asyncio.run(main())
