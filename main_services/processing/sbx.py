"""How long does the sandbox take to instantiate the real workflow classes?"""
import time, sys
sys.path.insert(0, "/app")
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions
from temporalio.worker.workflow_sandbox._importer import Importer

from tasks.P3_parse_files.workflows import ParseSingleFile
from tasks.P3_parse_files.parse_email import EmailExtractionAndScan
from tasks.P2_execute_plan.workflows import ProcessItemsBatched

r = SandboxRestrictions.default
for label, n in (("cold", 1), ("warm", 5)):
    t = time.time()
    for _ in range(n):
        imp = Importer(r, lambda: None) if False else None
    # Measure the real thing: importing the workflow module inside a fresh sandbox env
    from temporalio.worker.workflow_sandbox._in_sandbox import InSandbox  # noqa
    print(label, "skip")
    break

# Direct measure: time a fresh import of the module graph, which is what the sandbox
# redoes for every workflow instance it creates.
import importlib
mods = ["tasks.P3_parse_files.workflows", "tasks.P2_execute_plan.workflows"]
for m in mods:
    for name in [k for k in list(sys.modules) if k.startswith("tasks.")]:
        del sys.modules[name]
    t = time.time()
    importlib.import_module(m)
    print("%s: fresh import %.0f ms" % (m, 1000 * (time.time() - t)))
