"""Verify route encoding and procedure failure evidence."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from manual_qa_runtime import Run, cbor, query, route, unroute


class RouteTests(unittest.TestCase):
    def test_cbor_wire_values(self):
        self.assertEqual(cbor(None), b"\xf6")
        self.assertEqual(cbor({"String": "testdata_manualqa"}).hex(),
                         "a166537472696e677174657374646174615f6d616e75616c7161")

    def test_unicode_signed_and_nested_route_roundtrip(self):
        value = {"text": "Iași / PDF", "min": -(1 << 63), "max": (1 << 64) - 1,
                 "nested": [None, False, True, {"String": "dataset"}]}
        self.assertEqual(unroute(route(value)), value)
        self.assertNotIn("/", route(value))

    def test_dataset_scope_uses_the_applied_facet(self):
        self.assertEqual(query()["facet_filters"], {"collection_dataset": [{"String": "testdata_manualqa"}]})
        self.assertEqual(query(datasets=[])["facet_filters"], {})


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_keeps_completed_phase_and_failed_step(self):
        class Harness:
            async def run_action(self, tab, base, verb, argument):
                if argument == "bad":
                    raise AssertionError("observed value differs")
                return {"value": argument}

            async def screenshot(self, tab, full):
                return b"image"

            async def js_async(self, tab, expression):
                return {"generation": 7, "hasViewer": True, "documentState": {"loading": True}}

            async def snapshot(self, tab):
                return {"lines": []}

        class Network:
            def api_summary(self):
                return "0"

        with tempfile.TemporaryDirectory() as directory:
            run = Run(None, "", Network(), Path(directory), "case", Harness(), {}, {})
            await run.phase("first", "The first value is available.", lambda: run.action("eval", "good"))
            await run.phase("second", "The second value is available.", lambda: run.action("eval", "bad"))
            data = json.loads((Path(directory) / "case.procedures.json").read_text())
            self.assertEqual([phase["status"] for phase in data], ["passed", "application_error"])
            self.assertEqual(data[1]["steps"][0]["status"], "failed")
            self.assertEqual(data[1]["failure_state"]["generation"], 7)
            self.assertTrue(data[1]["failure_state"]["documentState"]["loading"])
            self.assertEqual(data[0]["steps"][0]["observed"], {"value": "good"})


if __name__ == "__main__":
    unittest.main()
