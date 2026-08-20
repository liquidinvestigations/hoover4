"""CapabilityGate sheds load rather than queueing without bound."""

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from admission import CapabilityGate


class CapabilityGateTests(unittest.TestCase):
    def test_refuses_when_concurrency_plus_queue_are_held(self):
        gate = CapabilityGate(concurrency=1, queue_depth=1, name="ner")
        self.assertTrue(gate.try_acquire())
        self.assertTrue(gate.try_acquire())
        self.assertFalse(gate.try_acquire())
        gate.release()
        self.assertTrue(gate.try_acquire())
        gate.release()
        gate.release()

    def test_submit_runs_off_the_calling_thread(self):
        gate = CapabilityGate(concurrency=1, queue_depth=0, name="embed")
        caller = threading.get_ident()

        def work():
            return threading.get_ident()

        self.assertTrue(gate.try_acquire())
        try:
            worker_ident = gate.submit(work)
        finally:
            gate.release()
        self.assertNotEqual(worker_ident, caller)


if __name__ == "__main__":
    unittest.main()
