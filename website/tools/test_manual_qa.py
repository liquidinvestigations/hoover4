"""Unit tests for manual QA selection and prerequisite classification."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("manual_qa", Path(__file__).with_name("manual_qa.py"))
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ManualQaTests(unittest.TestCase):
    def test_default_selection_covers_each_baseline_and_variation(self) -> None:
        cases = MODULE.select_cases("")
        self.assertEqual([case.row for case in cases], list(range(6, 26)))
        self.assertTrue(all(case.variations for case in cases))

    def test_unknown_selection_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown manual QA rows"):
            MODULE.select_cases("5")

    def test_unmet_fixture_marks_the_case_incomplete(self) -> None:
        result = MODULE.prerequisite_status(MODULE.select_cases("6"), {"outcomes": []})
        self.assertEqual(result, [{"row": 6, "status": "unmet_prerequisite", "missing": ["shipping_manifest"]}])
        plan = MODULE.plan(MODULE.select_cases("6"), {"outcomes": []}, Path("/dev/null"))
        self.assertEqual(plan["result"], "incomplete_execution")
        self.assertEqual(plan["capture_scenarios"], [])

    def test_entity_viewer_uses_the_easychair_fixture(self) -> None:
        case = MODULE.select_cases("23")[0]
        self.assertEqual(case.fixtures, ("easychair_office",))

    def test_partial_evidence_keeps_ready_and_unmet_cases_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ini = root / "screenshots.ini"
            ini.write_text("[manual-shipping]\nurl = /\n[manual-sort-dates]\nurl = /\n", encoding="utf-8")
            profile = {"outcomes": [{"fixture": "shipping_manifest", "status": "verified"}]}
            result = MODULE.plan(MODULE.select_cases("6,14"), profile, ini)
        self.assertEqual(result["result"], "ready")
        self.assertEqual([item["status"] for item in result["prerequisites"]], ["ready", "ready"])

    def test_missing_procedure_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {"cases": [{"row": 6, "scenarios": ["manual-shipping"], "variations": ["keyboard-find"]}]}
            (root / "manual-qa-plan.json").write_text(json.dumps(data))
            self.assertEqual(MODULE.summarize(root, ["720p"], 0, 2, 0), 2)
            results = json.loads((root / "manual-qa-results.json").read_text())
            self.assertTrue(all(row["status"] == "incomplete_execution" for row in results["procedures"]))

    def test_unknown_registered_scenario_does_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ini = Path(directory) / "screenshots.ini"
            ini.write_text("[unrelated]\nurl = /\n")
            profile = {"outcomes": [{"fixture": "shipping_manifest", "status": "verified"}]}
            result = MODULE.plan(MODULE.select_cases("6"), profile, ini)
            self.assertEqual(result["capture_scenarios"], [])
            self.assertEqual(result["result"], "incomplete_execution")

    def test_chat_requires_history_at_each_requested_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manual-qa-plan.json").write_text(json.dumps({"cases": [{"row": 25, "variations": []}]}))
            folder = root / "chat/latest/chat"
            folder.mkdir(parents=True)
            conversation = {"submission_ok": True, "turn_started": True, "completed_answer_present": True,
                            "captures": {"720p": [1], "1080p": [1]}, "history": {"by_resolution": {
                                "720p": {"reload_survived": True, "switch": {"attempted": True, "survived": True}}}}}
            (folder / "chat_manifest.json").write_text(json.dumps([conversation]))
            self.assertEqual(MODULE.summarize(root, ["720p", "1080p"], 0, 0, 0), 2)
            records = json.loads((root / "manual-qa-results.json").read_text())["procedures"]
            self.assertEqual([item["status"] for item in records], ["passed", "incomplete_execution"])


if __name__ == "__main__":
    unittest.main()
