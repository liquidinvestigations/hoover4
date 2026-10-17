"""Exercise Markdown parsing, diagnostics, and screenshot publication failures."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/docs"))
from markdown import parse
from check import Audit, markdown_path
from publish_screenshots import prepare
from external_links import check as check_external


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = load("hook", ROOT / ".agents/hooks/deny-claudisms.py")
PROSE = load("prose", ROOT / ".agents/check-prose-style.py")


class MarkdownTests(unittest.TestCase):
    def test_prose_ignores_code_quotes_and_frontmatter(self):
        source = "---\nname: worth knowing\n---\n# Read results.\n\nThe **whole**\npoint is visible.\n\n`worth knowing`\n\n```text\nworth knowing\n```\n\n> worth knowing\n"
        parsed = parse(source)
        text = " ".join(row[1] for row in parsed["prose"])
        self.assertIn("The whole point", text)
        self.assertNotIn("worth knowing", text)
        self.assertEqual(parsed["headings"][0][0], 4)

    def test_duplicate_unicode_and_setext_anchors(self):
        parsed = parse("# Привет 你好\n\n## A `value`\n\n## A value\n\nA value\n-------\n\n## A value-1\n")
        self.assertEqual([h[3] for h in parsed["headings"]], ["привет-你好", "a-value", "a-value-1", "a-value-2", "a-value-1-1"])

    def test_links_references_html_and_nested_parentheses(self):
        source = '# Title\n\n[manual][ref]\n\n[ref]: file(1).md#part\n\n<a href="img.png"><img src="img.png" alt="Results" align="right" width="560"></a>\n'
        parsed = parse(source)
        self.assertEqual(parsed["links"][0].url, "file(1).md#part")
        image = next(x for x in parsed["links"] if x.image)
        self.assertEqual(image.attrs["_href"], "img.png")
        self.assertEqual(image.alt, "Results")

    def test_explicit_ids_are_checked_across_inline_and_block_html(self):
        parsed = parse('# Read.\n\nText <span id="repeat">one</span>.\n\n<div id="repeat">two</div>\n')
        self.assertEqual(parsed["duplicate_ids"], [(5, "repeat")])

    def test_diagrams_exclude_other_fences(self):
        parsed = parse("# Draw\n\n```text\n```mermaid\n```\n\n~~~mermaid\nflowchart LR\n A --> B\n~~~\n")
        self.assertEqual(len(parsed["diagrams"]), 1)
        self.assertEqual(parsed["diagrams"][0][0], 7)

    def test_extensions_are_case_insensitive_and_templates_explicit(self):
        self.assertTrue(markdown_path("Guide.MD"))
        self.assertFalse(markdown_path("prompt.md.j2"))
        self.assertTrue(markdown_path("prompt.MD.j2", True))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_file_case_ignored_target_anchor_and_escape(self):
        self.file("README.md", "# Read.\n\n[case](guide.md) [local](local.md) [anchor](Guide.MD#wrong) [escape](../../outside.md)\n")
        self.file("Guide.MD", "# Valid\n")
        self.file("local.md", "# Local\n")
        audit = Audit(self.root, ["README.md", "Guide.MD"])
        audit.scan(["README.md"])
        self.assertEqual({f["rule"] for f in audit.findings}, {"link-missing", "link-untracked", "link-anchor", "link-outside"})

    def test_formatted_and_wrapped_phrases_and_narrow_name_exception(self):
        self.file("README.md", "# Limits **worth knowing**\n\nThis is the whole\npoint. NICE Actimize supplies data. A nice result.\n")
        audit = Audit(self.root, ["README.md"])
        audit.scan(["README.md"])
        findings = [f for f in audit.findings if f["rule"] == "prose"]
        self.assertEqual(len(findings), 3)
        self.assertIn("worth knowing", findings[0]["message"])
        self.assertFalse(any("NICE" in f["message"] for f in findings))

    def test_directory_fragments_resolve_through_readme(self):
        self.file("README.md", "# Root\n\n[valid](folder/#read) [invalid](folder/#missing)\n")
        self.file("folder/Readme.md", "# Read\n")
        audit = Audit(self.root, ["README.md", "folder/Readme.md"])
        audit.scan(["README.md"])
        self.assertEqual([f["rule"] for f in audit.findings], ["link-anchor"])

    def test_example_markers_do_not_exempt_ordinary_pages(self):
        source = "# Read.\n\n<!-- prose-examples:start -->\nWorth knowing.\n<!-- prose-examples:end -->\n"
        self.file("README.md", source)
        audit = Audit(self.root, ["README.md"])
        audit.scan(["README.md"])
        self.assertTrue(any(f["rule"] == "prose" for f in audit.findings))
        self.file("AGENTS.md", source + "\nWorth reading.\n")
        audit = Audit(self.root, ["AGENTS.md"])
        audit.scan(["AGENTS.md"])
        self.assertEqual([f["message"] for f in audit.findings if f["rule"] == "prose"], ["Remove the prohibited wording: Worth reading"])

    def test_unlinked_paths_and_linked_labels(self):
        self.file("README.md", "# Read.\n\n`Guide.MD` and [Guide.MD](Guide.MD).\n")
        self.file("Guide.MD", "# Guide\n")
        audit = Audit(self.root, ["README.md", "Guide.MD"])
        audit.scan(["README.md"])
        self.assertEqual(len([f for f in audit.findings if f["rule"] == "unlinked-path"]), 1)

    def test_ownership_does_not_exclude_wrappers(self):
        self.file("components/pdf-viewer/README.md", "# Limits worth knowing\n")
        audit = Audit(self.root, ["components/pdf-viewer/README.md"], {"components/pdf-viewer/upstream.md": "Preserve upstream text."})
        audit.scan(["components/pdf-viewer/README.md"])
        self.assertTrue(any(f["rule"] == "prose" for f in audit.findings))

    def test_headings_alt_text_and_tool_citations(self):
        self.file("README.md", "## Heading\n\n#### More\n\n![](image.png)\n\nturn12search3\n")
        (self.root / "image.png").write_bytes(b"image")
        audit = Audit(self.root, ["README.md", "image.png"])
        audit.scan(["README.md"])
        self.assertEqual({f["rule"] for f in audit.findings}, {"heading-title", "heading-level", "image-alt", "citation-token"})

    def test_broken_coverage_is_reported(self):
        self.file("docs/technical-specification/Features.md", "| `F-test-01` | One |\n| `F-test-01` | Two |\n")
        self.file("website/frontend/src/routes.rs", '#[route("/search")]')
        self.file("docs/documentation-coverage.json", json.dumps({"features": [], "routes": {}}))
        audit = Audit(self.root, [])
        audit.coverage("docs/documentation-coverage.json")
        self.assertEqual({f["rule"] for f in audit.findings}, {"feature-duplicate", "feature-coverage", "route-coverage"})

    def test_complete_coverage_and_screenshot_records_pass(self):
        import hashlib
        self.file("docs/technical-specification/Features.md", "| `F-test-01` | Search |\n")
        self.file("website/frontend/src/routes.rs", '#[route("/search")]')
        self.file("website/browser-tests/001-search.ini", "[search]\nurl=/search\n")
        self.file("docs/user-manual/User_Manual.md", '# Search.\n\n<a href="img/search.png"><img src="img/search.png" alt="Search results" align="right" width="560"></a>\n')
        png = self.root / "docs/user-manual/img/search.png"
        png.parent.mkdir()
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1400, 900))
        feature = {"id": "F-test-01", "source": ["website/frontend/src/routes.rs"], "docs": ["docs/user-manual/User_Manual.md#search"], "audience": "user", "screenshot": "docs/user-manual/img/search.png", "scenario": "website/browser-tests/001-search.ini"}
        self.file("docs/documentation-coverage.json", json.dumps({"features": [feature], "routes": {"/search": "docs/user-manual/User_Manual.md#search"}}))
        record = {"image": "docs/user-manual/img/search.png", "scenario": "website/browser-tests/001-search.ini", "revision": "a" * 40, "captured_at": "2026-01-01", "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}
        self.file("docs/screenshot-provenance.json", json.dumps({"screenshots": [record]}))
        tracked = [p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()]
        audit = Audit(self.root, tracked)
        audit.scan(["docs/user-manual/User_Manual.md"])
        audit.coverage("docs/documentation-coverage.json")
        audit.provenance("docs/screenshot-provenance.json")
        self.assertEqual(audit.findings, [])
        png.write_bytes(png.read_bytes() + b"changed")
        audit.provenance("docs/screenshot-provenance.json")
        self.assertEqual([f["rule"] for f in audit.findings], ["screenshot-hash"])

    def test_source_and_config_warnings_request_review(self):
        self.file("hoover4.ini.development", "[search]\nworkers=2\n")
        self.file("README.md", "# Configure search.\n\n`missing/source.py`\n\n```ini\n[search]\nworkres=2\n```\n")
        audit = Audit(self.root, ["README.md"])
        audit.scan(["README.md"])
        self.assertEqual({f["rule"] for f in audit.findings}, {"source-reference", "config-review"})
        self.assertTrue(all(f["severity"] == "warning" for f in audit.findings))

    def test_unclosed_rule_region_is_an_error(self):
        self.file("AGENTS.md", "# Write.\n\n<!-- prose-examples:start -->\n")
        audit = Audit(self.root, ["AGENTS.md"])
        audit.scan(["AGENTS.md"])
        self.assertEqual([f["rule"] for f in audit.findings], ["prose-examples"])

    def test_legacy_checker_handles_wrapped_headings(self):
        path = self.file("sample.MD", "# Limits **worth knowing**\n\nThe whole\npoint remains.\n")
        found = PROSE.check_markdown(path, "sample.MD", False, False)
        self.assertEqual(len(found), 2)


class HookTests(unittest.TestCase):
    def test_legacy_walker_includes_owned_markdown_in_vendor_paths(self):
        names = {str(ROOT / "main_services/regex_entity_scanner/vendored/README.md"),
                 str(ROOT / "website/backend/pdf-viewer/_server/dist/engines/README.md")}
        paths = set(PROSE.walk([str(ROOT / "main_services/regex_entity_scanner/vendored"),
                                str(ROOT / "website/backend/pdf-viewer/_server/dist")], names))
        self.assertIn(str(ROOT / "main_services/regex_entity_scanner/vendored/README.md"), paths)
        self.assertNotIn(str(ROOT / "website/backend/pdf-viewer/_server/dist/engines/README.md"), paths)

    def test_rule_lists_match(self):
        self.assertEqual(HOOK.PHRASES, PROSE._PHRASES)

    def payload(self, name, data):
        result = subprocess.run([sys.executable, str(ROOT / ".agents/hooks/deny-claudisms.py")], input=json.dumps({"tool_name": name, "tool_input": data}), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_new_markdown_heading_is_denied(self):
        for path in ("guide.MD", "prompt.md.j2"):
            self.assertIn('"deny"', self.payload("Write", {"file_path": path, "content": "# Limits **worth\nknowing**"}))

    def test_code_and_deletion_are_allowed(self):
        self.assertEqual(self.payload("Write", {"file_path": "guide.md", "content": "# Read.\n\n`worth knowing`\n"}), "")
        self.assertEqual(self.payload("Edit", {"file_path": "guide.md", "old_string": "Limits worth knowing", "new_string": "Read the limits."}), "")

    def test_edit_and_patch_match_across_unchanged_context(self):
        self.assertIn('"deny"', self.payload("Edit", {"file_path": "guide.md", "old_string": "The whole\nsection.", "new_string": "The whole\npoint."}))
        self.assertIn('"deny"', self.payload("apply_patch", {"command": "*** Begin Patch\n*** Update File: guide.md\n@@\n The whole\n-section.\n+point.\n*** End Patch"}))

    def test_existing_phrase_does_not_hide_a_new_phrase(self):
        self.assertIn('"deny"', self.payload("Edit", {"file_path": "guide.md", "old_string": "Worth knowing.", "new_string": "Worth knowing. Under the hood."}))

    def test_rule_examples_are_scoped(self):
        text = "<!-- prose-examples:start -->\nWorth knowing.\n<!-- prose-examples:end -->"
        self.assertEqual(self.payload("Write", {"file_path": "AGENTS.md", "content": text}), "")
        self.assertIn('"deny"', self.payload("Write", {"file_path": "guide.md", "content": text}))

    def test_multiedit_uses_the_result_of_the_previous_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.md"
            path.write_text("The whole section.")
            self.assertIn('"deny"', self.payload("MultiEdit", {"file_path": str(path), "edits": [
                {"old_string": "section", "new_string": "passage"},
                {"old_string": "passage", "new_string": "point"}]}))

    def test_owned_vendor_readme_is_checked_and_upstream_is_preserved(self):
        data = {"file_path": "main_services/regex_entity_scanner/vendored/README.md", "content": "Limits worth knowing."}
        self.assertIn('"deny"', self.payload("Write", data))
        data["file_path"] = "website/backend/pdf-viewer/_server/dist/engines/README.md"
        self.assertEqual(self.payload("Write", data), "")

    def test_patch_and_multiedit_are_denied(self):
        self.assertIn('"deny"', self.payload("apply_patch", {"command": "*** Begin Patch\n*** Update File: guide.md\n+## Behind the scenes\n*** End Patch"}))
        self.assertIn('"deny"', self.payload("MultiEdit", {"file_path": "guide.md", "edits": [{"old_string": "", "new_string": "Please note the setting."}]}))


class RendererTests(unittest.TestCase):
    def test_timeout_removes_only_its_named_container(self):
        from mermaid import render
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "manifest.json").write_text(json.dumps([{"source": "page.md", "line": 3, "file": "diagram.mmd"}]))
            with patch("mermaid.subprocess.run") as run:
                run.side_effect = [subprocess.TimeoutExpired("docker", 90), subprocess.CompletedProcess([], 0)]
                self.assertEqual(render(output), 1)
                command = run.call_args_list[0].args[0]
                name = command[command.index("--name") + 1]
                self.assertEqual(run.call_args_list[1].args[0], ["docker", "rm", "-f", name])
            self.assertIn("90 seconds", (output / "diagram.mmd.log").read_text())


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.run = self.root / "run"
        self.run.mkdir()
        self.scenario = self.root / "website/browser-tests/001-search.ini"
        self.scenario.parent.mkdir(parents=True)
        self.scenario.write_text("[search]\nurl=/\n")
        self.source = self.run / "search.png"
        self.source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1400, 900))
        self.manifest = dict(revision="a" * 40, target_label="private", identity="private", totals={}, pages=[dict(slug="001-search", verdict="ok", captures=[dict(file="search.png", actual_png=[1400, 900], requested=[1400, 900])])])
        self.mapping = [dict(capture="search.png", image="docs/user-manual/img/search.png", scenario="website/browser-tests/001-search.ini")]

    def prepare(self):
        (self.run / "manifest.json").write_text(json.dumps(self.manifest))
        return prepare(self.root, self.run, self.mapping)

    def test_provenance_contains_only_public_fields(self):
        rows = self.prepare()
        record = rows[0][2]
        self.assertEqual(set(record), {"image", "scenario", "revision", "captured_at", "sha256"})
        self.assertNotIn("private", json.dumps(record))

    def test_refuses_incomplete_and_wrong_dimensions(self):
        self.manifest["totals"]["incomplete_execution"] = 1
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.prepare()
        self.manifest["totals"] = {}
        self.source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1400, 857))
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.prepare()

    def test_refuses_a_different_scenario(self):
        self.manifest["pages"][0]["slug"] = "002-admin"
        with self.assertRaisesRegex(ValueError, "scenario"):
            self.prepare()

    def test_refuses_destination_escape(self):
        self.mapping[0]["image"] = "../outside.png"
        with self.assertRaises(ValueError):
            self.prepare()

    def test_network_errors_are_separate_from_missing_pages(self):
        from urllib.error import HTTPError
        with patch("external_links.public_url"), patch("external_links.build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://example.org", 404, "Missing", {}, None)
            self.assertEqual(check_external("https://example.org")["status"], "missing")
            opener.return_value.open.side_effect = OSError("Unavailable")
            with patch("external_links.time.sleep"):
                self.assertEqual(check_external("https://example.org")["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
