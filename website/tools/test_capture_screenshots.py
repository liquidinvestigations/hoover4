import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parent))
MODULE_PATH = Path(__file__).with_name("capture_screenshots.py")
SPEC = importlib.util.spec_from_file_location("capture_screenshots", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _corpus_pages():
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[1] / "browser-tests",
        here.parent / "browser-tests",
        Path("/tmp/capture-tests/browser-tests"),
    ):
        if candidate.is_dir():
            return {page.name: page for page in MODULE.load_scenario_pages(candidate)}
    return None


class ScenarioParsingTests(unittest.TestCase):
    def test_initial_script_is_specific_to_its_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ini = Path(directory) / "screenshots.ini"
            ini.write_text("[timed]\nurl=/\ninit_script=window.clock=1000;\n[ordinary]\nurl=/\n")
            pages = MODULE.parse_pages(ini)
        self.assertEqual(pages[0].init_script, "window.clock=1000;")
        self.assertEqual(pages[1].init_script, "")

    def test_exact_page_selection_rejects_a_missing_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ini = Path(directory) / "screenshots.ini"
            ini.write_text("[alpha]\nurl = /\n[beta]\nurl = /\n", encoding="utf-8")
            pages = MODULE.parse_pages(ini)
        self.assertEqual([page.name for page in MODULE.select_pages(pages, "", "beta")], ["beta"])
        with self.assertRaisesRegex(ValueError, "unknown pages selected: absent"):
            MODULE.select_pages(pages, "", "absent")

    def test_color_scheme_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ini = Path(directory) / "screenshots.ini"
            ini.write_text("[palette]\ncolor_scheme = dark\n", encoding="utf-8")
            page = MODULE.parse_pages(ini)[0]
        self.assertEqual(page.color_scheme, "dark")

    def test_invalid_color_scheme_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ini = Path(directory) / "screenshots.ini"
            ini.write_text("[palette]\ncolor_scheme = sepia\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.parse_pages(ini)

    def test_input_and_wait_actions_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ini = Path(directory) / "screenshots.ini"
            ini.write_text(
                "[table]\nactions =\n pointer_click_css button\n press_key Shift+Tab\n wait_eval return true;\n",
                encoding="utf-8",
            )
            actions = MODULE.parse_pages(ini)[0].actions
        self.assertEqual(
            actions,
            [
                ("pointer_click_css", "button"),
                ("press_key", "Shift+Tab"),
                ("wait_eval", "return true;"),
            ],
        )

    def test_directory_loader_reads_slug_number_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "102-search-later.ini").write_text(
                "[search-later]\nurl = /later\nactions =\n wait_text later\n",
                encoding="utf-8",
            )
            (root / "101-search-first.ini").write_text(
                "[search-first]\nurl = /first\nsummary = Exercises the search first case.\n",
                encoding="utf-8",
            )
            pages = MODULE.load_scenario_pages(root)
        self.assertEqual([page.name for page in pages], ["search-first", "search-later"])
        self.assertEqual([page.slug for page in pages], ["101-search-first", "102-search-later"])
        self.assertEqual(pages[0].url, "/first")
        self.assertEqual(pages[1].actions, [("wait_text", "later")])
        self.assertEqual(pages[0].summary, "Exercises the search first case.")
        self.assertEqual(pages[0].settle_ms, 800)

    def test_numbering_keeps_relative_order_inside_a_block(self) -> None:
        import split_browser_tests as split
        numbered = split.number_sections(["home", "search-b", "search-a", "bad-url-x"])
        by_name = {name: slug for name, _base, slug in numbered}
        self.assertEqual(by_name["home"], "001-home")
        self.assertEqual(by_name["bad-url-x"], "002-bad-url-x")
        self.assertEqual(by_name["search-b"], "101-search-b")
        self.assertEqual(by_name["search-a"], "102-search-a")


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_removes_initial_script_in_the_same_session(self) -> None:
        commands = []

        class Tab:
            async def send(self, request):
                command = next(request)
                commands.append(command)
                if command["method"] == "Page.addScriptToEvaluateOnNewDocument":
                    from nodriver.cdp.page import ScriptIdentifier
                    return ScriptIdentifier("script-1")

        with patch.object(MODULE, "js", AsyncMock(return_value=123)), patch.object(
            MODULE, "wait_eval", AsyncMock()
        ) as ready, patch.object(MODULE, "wait_for_app_mounted", AsyncMock()) as mounted:
            await MODULE.navigate_document(Tab(), "/current", "window.clock=1000;")
        self.assertEqual([command["method"] for command in commands], [
            "Page.enable", "Page.addScriptToEvaluateOnNewDocument", "Page.navigate", "Page.removeScriptToEvaluateOnNewDocument"
        ])
        self.assertEqual(commands[-1]["params"]["identifier"], "script-1")
        ready.assert_awaited_once()
        mounted.assert_awaited_once()

    async def test_back_selects_the_prior_browser_entry(self) -> None:
        commands = []

        class Tab:
            async def send(self, request):
                command = next(request)
                commands.append(command)
                if command["method"] == "Page.getNavigationHistory":
                    return 1, [SimpleNamespace(id_=41), SimpleNamespace(id_=52)]

        await MODULE.navigate_history(Tab(), -1)
        self.assertEqual(commands[-1], {"method": "Page.navigateToHistoryEntry", "params": {"entryId": 41}})

    async def test_missing_history_entry_is_an_assertion_failure(self) -> None:
        class Tab:
            async def send(self, request):
                return 0, [SimpleNamespace(id_=41)]

        with self.assertRaisesRegex(RuntimeError, "no entry"):
            await MODULE.navigate_history(Tab(), -1)

    async def test_failed_action_preserves_prior_observations(self) -> None:
        actions = [("eval", "first"), ("eval", "second"), ("eval", "unreached")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.steps.json"
            with patch.object(MODULE, "js", AsyncMock(return_value={"url": "about:blank"})), patch.object(
                MODULE, "run_action", AsyncMock(side_effect=[{"count": 7}, RuntimeError("assertion failed")])
            ) as run:
                with self.assertRaisesRegex(RuntimeError, "assertion failed"):
                    await MODULE.run_recorded_actions(None, "", actions, path)
                self.assertEqual(run.await_count, 2)
            steps = json.loads(path.read_text())
            self.assertEqual([step["status"] for step in steps], ["completed", "failed"])
            self.assertEqual(steps[0]["observed"], {"count": 7})
            self.assertEqual(steps[1]["error"], "assertion failed")

    async def test_wait_eval_incomplete_is_not_an_application_error(self) -> None:
        with patch.object(MODULE, "js", AsyncMock(return_value={"incomplete": True, "reason": "no errored destructive row"})):
            with self.assertRaises(MODULE.IncompleteCapture) as raised:
                await MODULE.wait_eval(None, "return {incomplete:true};")
        self.assertEqual(MODULE.classify_exception(raised.exception), MODULE.INCOMPLETE_EXECUTION)


class CredentialAndInventoryTests(unittest.TestCase):
    def test_synthetic_credentials_stay_out_of_argument_lists(self) -> None:
        import capture_credentials as creds
        username, password = "syn-user", "syn-pass-value"
        flags = creds.docker_env_name_flags(username, password, "abc123")
        python_argv = ["capture_screenshots.py", "--run-name", "run-1"]
        docker_argv = ["docker", "exec", *flags, "hoover4-mcp-browser", "python", *python_argv]
        self.assertEqual(creds.credentials_in_argv(docker_argv, username, password), [])
        self.assertEqual(creds.credentials_in_argv(python_argv, username, password), [])
        self.assertIn(creds.USERNAME_ENV, flags)
        self.assertIn(creds.PASSWORD_ENV, flags)
        self.assertNotIn(f"{creds.USERNAME_ENV}={username}", flags)
        self.assertNotIn(f"{creds.PASSWORD_ENV}={password}", flags)

    def test_read_credentials_uses_environment_names(self) -> None:
        import capture_credentials as creds
        pair = creds.read_credentials({
            creds.USERNAME_ENV: "syn-user",
            creds.PASSWORD_ENV: "syn-pass-value",
        })
        self.assertEqual(pair, ("syn-user", "syn-pass-value"))
        with self.assertRaises(creds.CredentialError):
            creds.read_credentials({creds.USERNAME_ENV: "syn-user"})

    def test_image_inventory_defaults_review_state(self) -> None:
        import capture_credentials as creds
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "720p").mkdir()
            (root / "720p" / "00-home.png").write_bytes(b"\x89PNG")
            (root / "1080p").mkdir()
            (root / "1080p" / "00-home.FAILED.png").write_bytes(b"\x89PNG")
            entries = creds.collect_image_inventory(root, "local", "rev1")
        self.assertEqual({item["path"] for item in entries}, {"720p/00-home.png", "1080p/00-home.FAILED.png"})
        self.assertTrue(all(item["review_state"] == creds.IMAGE_REVIEW_PENDING for item in entries))
        self.assertTrue(all(item["revision"] == "rev1" for item in entries))
        self.assertTrue(all(item["target"] == "local" for item in entries))

    def test_missing_dataset_is_incomplete_not_success(self) -> None:
        page = MODULE.Page(name="rescan", url="/", requires_dataset=["testdata_diskfiles"])
        self.assertEqual(MODULE.missing_datasets(page, set()), ["testdata_diskfiles"])

    def test_incomplete_capture_is_classified_incomplete(self) -> None:
        self.assertEqual(
            MODULE.classify_exception(MODULE.IncompleteCapture("no errored destructive row")),
            MODULE.INCOMPLETE_EXECUTION,
        )

    def test_document_route_uses_current_profile_identity(self) -> None:
        page = MODULE.Page(
            name="table",
            url="/view_document/old-identity/9g==/tab",
            document_fixture="manual_table_substitute",
        )
        contract = {"fixtures": [{"name": "manual_table_substitute", "dataset": "testdata_manualqa", "path": "/substitutes/manual-qa-table.csv"}]}
        profile = {"datasets": {"testdata_manualqa": [{"path": "/substitutes/manual-qa-table.csv", "hash": "abc123"}]}}
        resolved = MODULE.resolve_document_url(page, profile, contract)
        self.assertTrue(resolved.startswith("/view_document/"))
        self.assertIn("/9g==/tab", resolved)
        self.assertNotIn("old-identity", resolved)
        missing = MODULE.Page(name="table", url="/view_document/old/9g==", document_fixture="manual_table_substitute")
        with self.assertRaises(MODULE.IncompleteCapture):
            MODULE.resolve_document_url(missing, {"datasets": {}}, contract)

    def test_destructive_confirm_actions_never_click_rerun(self) -> None:
        pages = _corpus_pages()
        if pages is None:
            self.skipTest("browser scenario files are not beside the copied tools")
        confirm = pages["admin-operations-destructive-confirm"]
        empty = pages["admin-operations-errored-empty"]
        rescan = pages["admin-dataset-rescan-dispatch"]
        verbs = [verb for verb, _ in confirm.actions]
        self.assertNotIn("click_css", verbs)
        self.assertNotIn("click_text", verbs)
        self.assertNotIn("pointer_click_css", verbs)
        self.assertTrue(any("wrong-target" in argument for verb, argument in confirm.actions if verb == "eval"))
        self.assertTrue(any("clicked:false" in argument for verb, argument in confirm.actions if verb == "eval"))
        self.assertTrue(any("incomplete" in argument for verb, argument in empty.actions))
        self.assertEqual(rescan.actions, [("wait_text", "Rescan disk"), ("sleep", "800")])

    def test_cold_expansion_does_not_toggle_an_open_dataset(self) -> None:
        pages = _corpus_pages()
        if pages is None:
            self.skipTest("browser scenario files are not beside the copied tools")
        actions = pages["qa-storage-cold-expansion"].actions
        verbs = [verb for verb, _ in actions]
        self.assertNotIn("pointer_click_css", verbs)
        expand = [argument for verb, argument in actions if verb == "eval"]
        self.assertTrue(expand)
        self.assertIn("alreadyExpanded", expand[0])
        self.assertIn("if(!expanded)", expand[0])
        self.assertTrue(any(verb == "wait_text_in" and "location-1" in argument for verb, argument in actions))


class ReportVerdictTests(unittest.TestCase):
    def test_each_severity_maps_to_the_named_verdict(self) -> None:
        mapping = {
            MODULE.APPLICATION_ERROR: "FAIL",
            MODULE.EXPECTED_OUTCOME: "PASS",
            MODULE.TRACE: "PASS",
            MODULE.BEHAVIORAL_WARNING: "WARNING",
            MODULE.DIAGNOSTIC_WARNING: "WARNING",
            MODULE.INCOMPLETE_EXECUTION: "INCOMPLETE",
        }
        for severity, verdict in mapping.items():
            self.assertEqual(MODULE.report_verdict(severity), verdict)
        self.assertEqual(MODULE.report_verdict(None), "PASS")
        self.assertEqual(MODULE.report_verdict("ok"), "PASS")
        with self.assertRaises(ValueError):
            MODULE.report_verdict("not_a_severity")

    def test_application_error_row_is_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run-test"
            run_dir.mkdir()
            png_dir = run_dir / "720p"
            png_dir.mkdir()
            (png_dir / "00-broken.png").write_bytes(b"\x89PNG")
            (png_dir / "00-broken.snapshot.txt").write_text("outline\n", encoding="utf-8")
            totals = {sev: 0 for sev in MODULE.ALL_SEVERITIES}
            totals[MODULE.APPLICATION_ERROR] = 1
            manifest = {
                "target_label": "local development target",
                "identity": "anonymous",
                "revision": "rev1",
                "resolutions": {"720p": [1280, 720]},
                "pages": [
                    {
                        "stem": "00-broken",
                        "slug": "002-broken",
                        "summary": "Exercises the broken case.",
                        "url": "/broken",
                        "captures": [{"file": "720p/00-broken.png", "resolution": "720p"}],
                        "observations": [{"severity": MODULE.APPLICATION_ERROR, "message": "missing"}],
                        "verdict": MODULE.APPLICATION_ERROR,
                    },
                    {
                        "stem": "01-skipped",
                        "slug": "003-skipped",
                        "summary": "Exercises the skipped case.",
                        "url": "/skipped",
                        "skipped": "dataset missing",
                        "verdict": MODULE.INCOMPLETE_EXECUTION,
                    },
                ],
                "totals": totals,
            }
            MODULE.write_reports(run_dir, "run-test", manifest, 1)
            markdown = (run_dir / "report.md").read_text(encoding="utf-8")
            html = (run_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("| `002-broken` |", markdown)
            self.assertIn("| FAIL |", markdown)
            self.assertIn('width="500"', markdown)
            self.assertIn('href="720p/00-broken.png"', markdown)
            self.assertIn("[snapshot](720p/00-broken.snapshot.txt)", markdown)
            self.assertIn("FAIL", html)
            self.assertIn('width="500"', html)
            self.assertIn('href="720p/00-broken.png"', html)
            broken_at = markdown.find("`002-broken`")
            skipped_at = markdown.find("`003-skipped`")
            self.assertGreater(skipped_at, broken_at)
            self.assertNotIn("http://", markdown.split("## pages", 1)[1])
            self.assertNotIn("http://", html.split("<h2>Pages</h2>", 1)[1])


class ShardAndMergeTests(unittest.TestCase):
    def _pages(self, names: list[str], procedures: set[str] | None = None) -> list:
        procedures = procedures or set()
        pages = [
            MODULE.Page(
                name=name,
                url=f"/{name}",
                procedure="proc" if name in procedures else "",
                summary=f"Exercises the {name} case.",
                slug=f"{index:03d}-{name}",
            )
            for index, name in enumerate(names)
        ]
        return MODULE.assign_global_indices(pages)

    def test_shard_spec_parses_index_and_count(self) -> None:
        self.assertEqual(MODULE.parse_shard_spec("0/4"), (0, 4))
        self.assertEqual(MODULE.parse_shard_spec("3/4"), (3, 4))
        with self.assertRaisesRegex(ValueError, "not I/N"):
            MODULE.parse_shard_spec("4")
        with self.assertRaisesRegex(ValueError, "outside"):
            MODULE.parse_shard_spec("4/4")
        with self.assertRaisesRegex(ValueError, "at least 1"):
            MODULE.parse_shard_spec("0/0")

    def test_one_shard_is_the_full_list(self) -> None:
        pages = self._pages(["a", "b", "c"])
        self.assertEqual(
            [page.name for page in MODULE.select_shard(pages, 0, 1)],
            ["a", "b", "c"],
        )

    def test_shard_keeps_global_index_from_the_selected_list(self) -> None:
        pages = self._pages(["home", "search", "admin"])
        selected = MODULE.select_pages(pages, "", "search,admin")
        MODULE.assign_global_indices(selected)
        shard = MODULE.select_shard(selected, 0, 2)
        self.assertEqual({page.name: page.global_index for page in selected}, {"search": 0, "admin": 1})
        for page in shard:
            self.assertIn(page.global_index, (0, 1))
            self.assertEqual(MODULE.page_stem(page), f"{page.global_index:02d}-{page.name}")

    def test_procedures_spread_across_shards(self) -> None:
        names = [f"p{i}" for i in range(4)] + [f"q{i}" for i in range(8)]
        pages = self._pages(names, procedures={f"p{i}" for i in range(4)})
        shards = [MODULE.select_shard(pages, index, 4) for index in range(4)]
        procedure_counts = [sum(1 for page in shard if page.procedure) for shard in shards]
        self.assertEqual(procedure_counts, [1, 1, 1, 1])
        held = [page.name for shard in shards for page in shard]
        self.assertEqual(sorted(held), sorted(names))
        self.assertEqual(len(held), len(set(held)))

    def test_shard_applies_after_name_filter(self) -> None:
        pages = self._pages(["keep-a", "drop", "keep-b", "keep-c", "keep-d"])
        selected = MODULE.select_pages(pages, "", "keep-a,keep-b,keep-c,keep-d")
        MODULE.assign_global_indices(selected)
        shards = [MODULE.select_shard(selected, index, 4) for index in range(4)]
        held = sorted(page.name for shard in shards for page in shard)
        self.assertEqual(held, ["keep-a", "keep-b", "keep-c", "keep-d"])
        self.assertNotIn("drop", held)
        self.assertEqual([page.global_index for page in selected], [0, 1, 2, 3])

    def test_merge_orders_pages_by_global_position_and_sums_totals(self) -> None:
        pages = self._pages(["alpha", "beta", "gamma", "delta"])
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for shard_index in range(4):
                shard_pages = MODULE.select_shard(pages, shard_index, 4)
                shard_totals = {sev: 0 for sev in MODULE.ALL_SEVERITIES}
                if shard_index == 0:
                    shard_totals[MODULE.APPLICATION_ERROR] = 1
                    verdict = MODULE.APPLICATION_ERROR
                else:
                    verdict = "ok"
                entries = []
                for page in shard_pages:
                    entries.append({
                        "stem": MODULE.page_stem(page),
                        "slug": page.slug,
                        "summary": page.summary,
                        "url": page.url,
                        "verdict": verdict,
                    })
                MODULE.write_shard_manifest(run_dir, shard_index, {
                    "target_label": "local development target",
                    "identity": "tester",
                    "revision": "rev1",
                    "resolutions": {"720p": [1280, 720]},
                    "pages": entries,
                    "totals": shard_totals,
                })
            template = {
                "target_label": "missing",
                "identity": "anonymous",
                "revision": "",
                "resolutions": {},
            }
            manifest, exit_status = MODULE.merge_shard_manifests(
                pages, run_dir, 4, [1, 0, 0, 0], template,
            )
        self.assertEqual([entry["stem"] for entry in manifest["pages"]], [
            "00-alpha", "01-beta", "02-gamma", "03-delta",
        ])
        self.assertEqual(manifest["totals"][MODULE.APPLICATION_ERROR], 1)
        self.assertEqual(manifest["identity"], "tester")
        self.assertEqual(exit_status, 1)

    def test_dead_shard_pages_are_incomplete_execution(self) -> None:
        pages = self._pages(["alpha", "beta", "gamma", "delta"])
        dead_names = {page.name for page in MODULE.select_shard(pages, 1, 4)}
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for shard_index in range(4):
                if shard_index == 1:
                    continue
                shard_pages = MODULE.select_shard(pages, shard_index, 4)
                entries = [{
                    "stem": MODULE.page_stem(page),
                    "slug": page.slug,
                    "summary": page.summary,
                    "url": page.url,
                    "verdict": "ok",
                } for page in shard_pages]
                MODULE.write_shard_manifest(run_dir, shard_index, {
                    "target_label": "local development target",
                    "identity": "tester",
                    "revision": "rev1",
                    "resolutions": {"720p": [1280, 720]},
                    "pages": entries,
                    "totals": {sev: 0 for sev in MODULE.ALL_SEVERITIES},
                })
            manifest, exit_status = MODULE.merge_shard_manifests(
                pages, run_dir, 4, [0, 137, 0, 0],
                {"target_label": "", "identity": "anonymous", "revision": "", "resolutions": {}},
            )
            MODULE.write_reports(run_dir, "run-dead", manifest, exit_status)
            markdown = (run_dir / "report.md").read_text(encoding="utf-8")
        dead_entries = [
            entry for entry in manifest["pages"]
            if entry.get("verdict") == MODULE.INCOMPLETE_EXECUTION
        ]
        self.assertEqual({entry["slug"] for entry in dead_entries}, {
            next(page.slug for page in pages if page.name == name) for name in dead_names
        })
        self.assertTrue(all("did not finish" in (entry.get("skipped") or "") for entry in dead_entries))
        self.assertEqual(manifest["totals"][MODULE.INCOMPLETE_EXECUTION], len(dead_names))
        self.assertEqual(exit_status, 2)
        for name in dead_names:
            slug = next(page.slug for page in pages if page.name == name)
            self.assertIn(f"| `{slug}` |", markdown)
            self.assertIn("INCOMPLETE", markdown)

    def test_worst_capture_exit_treats_a_signal_as_incomplete(self) -> None:
        self.assertEqual(MODULE.worst_capture_exit(0, 0, 0, 0), 0)
        self.assertEqual(MODULE.worst_capture_exit(0, 2, 0, 0), 2)
        self.assertEqual(MODULE.worst_capture_exit(0, 137, 0, 1), 1)
        self.assertEqual(MODULE.worst_capture_exit(0, 143, 0, 0), 2)


if __name__ == "__main__":
    unittest.main()
