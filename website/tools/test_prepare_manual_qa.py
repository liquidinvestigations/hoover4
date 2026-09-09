"""Unit tests for manual QA fixture contract outcomes."""

import importlib.util
import contextlib
import io
import hashlib
import os
from pathlib import Path
from email.message import EmailMessage
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "prepare_manual_qa", Path(__file__).with_name("prepare_manual_qa.py"))
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def resolved() -> dict[str, object]:
    return {"datasets": {"testdata_manualqa": [{"path": "/file.txt", "hash": "a", "extracted_by": ["raw_text"]}]},
            "pdf_rows": {"testdata_manualqa": []}, "table_documents": {"testdata_manualqa": []},
            "table_cells": {"manual-qa-table.csv": []}, "image_ocr_rows": {"testdata_manualqa": []}}


class FixtureOutcomeTests(unittest.TestCase):
    def test_missing_fixture_is_unmet(self) -> None:
        contract = {"fixtures": [{"name": "missing", "dataset": "testdata_manualqa", "path": "/missing.txt"}]}
        self.assertEqual(MODULE.fixture_outcomes(contract, resolved())[0]["status"], "unmet")

    def test_forbidden_pdf_source_is_unmet(self) -> None:
        data = resolved()
        data["pdf_rows"]["testdata_manualqa"] = [{"pdf_hash": "a", "source_kind": "original"}, {"pdf_hash": "a", "source_kind": "ocr"}]
        contract = {"fixtures": [{"name": "pdf", "dataset": "testdata_manualqa", "path": "/file.txt", "expected": {"required_pdf_sources": ["original"], "forbidden_pdf_sources": ["ocr"]}}]}
        self.assertEqual(MODULE.fixture_outcomes(contract, data)[0]["status"], "unmet")

    def test_table_value_mismatch_is_unmet(self) -> None:
        data = resolved()
        data["datasets"]["testdata_manualqa"][0]["path"] = "/substitutes/manual-qa-table.csv"
        data["table_documents"]["testdata_manualqa"] = [{"hash": "a", "status": "ok"}]
        contract = {"fixtures": [{"name": "manual_table_substitute", "dataset": "testdata_manualqa", "path": "/substitutes/manual-qa-table.csv", "expected": {"cell_values": ["required"]}}]}
        self.assertEqual(MODULE.fixture_outcomes(contract, data)[0]["status"], "unmet")


class FixtureFailureTests(unittest.TestCase):
    def test_failed_command_preserves_output_and_status(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.run([sys.executable, "-c", "import sys; print('progress'); print('failure detail', file=sys.stderr); sys.exit(7)"])
        self.assertEqual(raised.exception.returncode, 7)
        self.assertIn("progress", stdout.getvalue())
        self.assertIn("failure detail", stderr.getvalue())

    def test_failed_refresh_archives_previous_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool_dir = root / "website/tools"
            reports = root / "website/test_reports"
            tool_dir.mkdir(parents=True)
            reports.mkdir()
            wrapper = tool_dir / "prepare_manual_qa.sh"
            shutil.copyfile(Path(__file__).with_name(wrapper.name), wrapper)
            profile = reports / "manual_qa_fixtures.json"
            profile.write_text('{"old": true}\n', encoding="utf-8")
            executable_dir = root / "bin"
            executable_dir.mkdir()
            docker = executable_dir / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in\n"
                "  *mktemp*) echo /tmp/manual-qa-preparation.test; exit 0;;\n"
                "  'cp '*) exit 0;;\n"
                "  'exec -w '*) echo 'ingest failure' >&2; exit 7;;\n"
                "  *) exit 1;;\n"
                "esac\n", encoding="utf-8")
            docker.chmod(0o755)
            result = subprocess.run(
                ["bash", str(wrapper), "--profile-only"], capture_output=True, text=True,
                env={**os.environ, "PATH": str(executable_dir) + os.pathsep + os.environ["PATH"]})
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertFalse(profile.exists())
            self.assertEqual((reports / "manual_qa_fixtures.previous.json").read_text(), '{"old": true}\n')
            self.assertIn("ingest failure", (reports / "manual_qa_fixtures.worker.log").read_text())


class SourceExpectationTests(unittest.TestCase):
    def test_email_headers_and_attachment_identities_come_from_source_bytes(self) -> None:
        message = EmailMessage()
        message["From"] = "Ana <ana@example.test>"
        message["To"] = "Ștefan <stefan@example.test>"
        message["Cc"] = "Second <second@example.test>"
        message["Subject"] = "Urăsc canicula"
        message.set_content("Body text.")
        message.add_attachment(b"one", maintype="application", subtype="octet-stream", filename="one.bin")
        message.add_attachment(b"different", maintype="application", subtype="octet-stream", filename="two.bin")
        expected = MODULE.email_expectations(message.as_bytes())
        self.assertEqual(expected["subject"], "Urăsc canicula")
        self.assertEqual(expected["envelope"]["to"], [{"name": "Ștefan", "address": "stefan@example.test"}])
        self.assertEqual(expected["envelope"]["cc"], [{"name": "Second", "address": "second@example.test"}])
        self.assertEqual([item["filename"] for item in expected["attachments"]], ["one.bin", "two.bin"])
        self.assertEqual([item["size_bytes"] for item in expected["attachments"]], [3, 9])
        self.assertNotEqual(expected["attachments"][0]["sha256"], expected["attachments"][1]["sha256"])
        self.assertEqual(expected["attachments"][0]["sha3_256"], hashlib.sha3_256(b"one").hexdigest())

    def test_changed_copy_cannot_supply_source_expectations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.txt"
            source.write_bytes(b"original")
            copied = root / "prepared"
            copied.mkdir()
            (copied / "copy.txt").write_bytes(b"changed")
            with patch.object(MODULE, "SOURCES", {"copy.txt": source}):
                with self.assertRaisesRegex(ValueError, "differs from fixture source"):
                    MODULE.source_expectations(copied)

    def test_indexed_identity_must_match_source_bytes(self) -> None:
        data = resolved()
        data["source_expectations"] = {"copied_sources": [
            {"dataset": "testdata_manualqa", "path": "/file.txt", "sha3_256": "different"}]}
        contract = {"fixtures": [{"name": "source", "dataset": "testdata_manualqa", "path": "/file.txt"}]}
        self.assertEqual(MODULE.fixture_outcomes(contract, data)[0]["status"], "unmet")

    def test_indexed_identity_uses_sha3_and_retains_sha256_for_provenance(self) -> None:
        data = resolved()
        data["datasets"]["testdata_manualqa"][0]["hash"] = hashlib.sha3_256(b"source bytes").hexdigest()
        data["source_expectations"] = {"copied_sources": [{
            "dataset": "testdata_manualqa", "path": "/file.txt",
            "sha3_256": hashlib.sha3_256(b"source bytes").hexdigest(),
            "sha256": hashlib.sha256(b"source bytes").hexdigest(),
        }]}
        contract = {"fixtures": [{"name": "source", "dataset": "testdata_manualqa", "path": "/file.txt"}]}
        self.assertEqual(MODULE.fixture_outcomes(contract, data)[0]["status"], "verified")

    def test_email_without_source_expectations_is_unmet(self) -> None:
        contract = {"fixtures": [{"name": "romanian_email", "dataset": "testdata_manualqa", "path": "/file.txt",
                                  "expected": {"attachment_count": 3}}]}
        self.assertEqual(MODULE.fixture_outcomes(contract, resolved())[0]["status"], "unmet")


class DiscoveryTests(unittest.TestCase):
    def test_discover_only_does_not_ingest_or_prepare_sources(self) -> None:
        with patch.object(MODULE, "run") as ingest, patch.object(MODULE, "write_generated_sources") as prepare, \
             patch.object(MODULE, "ensure_errored_operation_fixture") as ops, \
             patch.object(MODULE, "write_discovered_profile", return_value=True) as discover, \
             patch.object(sys, "argv", ["prepare_manual_qa.py", "--discover-only"]), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(MODULE, "CONTRACT_PATH", Path("/tmp/missing-contract.json")):
            # CONTRACT_PATH.read_text still needs a file; patch json load via Path.read_text
            with patch.object(Path, "read_text", return_value='{"schema_version": 2}'):
                self.assertEqual(MODULE.main(), 0)
        ingest.assert_not_called()
        prepare.assert_not_called()
        ops.assert_not_called()
        discover.assert_called_once()

    def test_ingest_commands_include_diskfiles_and_never_run_from_discover(self) -> None:
        commands = MODULE.ingest_commands()
        self.assertTrue(any("diskfiles" in command for command in commands))
        self.assertTrue(all(command[4] == "add-disk-dataset" for command in commands))

    def test_original_cases_remain_incomplete(self) -> None:
        names = {item["name"] for item in MODULE.original_case_status()}
        self.assertEqual(names, {"original_enron_document", "Messinai-szoros.txt", "original_barak_document"})
        self.assertTrue(all(item["status"] == "unmet" for item in MODULE.original_case_status()))
        local_reasons = " ".join(item["reason"] for item in MODULE.original_case_status())
        self.assertIn("enron-kaminski-v", local_reasons)

    def test_discover_original_reasons_omit_local_paths(self) -> None:
        rows = MODULE.original_case_status(discovered=True)
        self.assertEqual({item["name"] for item in rows},
                         {"original_enron_document", "Messinai-szoros.txt", "original_barak_document"})
        self.assertTrue(all(item["status"] == "unmet" for item in rows))
        reasons = " ".join(item["reason"] for item in rows)
        self.assertNotIn("testdata", reasons)
        self.assertNotIn("enron-kaminski-v", reasons)
        self.assertNotIn("stanley.ec02.pdf", reasons)
        self.assertIn("per-target original-case inventory", reasons)

    def test_empty_operation_state_is_distinct_from_errored_confirm(self) -> None:
        empty = {"available": True, "errored_destructive": [], "qa_errored_confirm": "absent"}
        present = {"available": True, "errored_destructive": [{"kind": "delete_dataset", "collection_dataset": MODULE.QA_ERRORED_DATASET}],
                   "qa_errored_confirm": "present"}
        self.assertNotEqual(empty["qa_errored_confirm"], present["qa_errored_confirm"])
        self.assertEqual(empty["errored_destructive"], [])


if __name__ == "__main__":
    unittest.main()
