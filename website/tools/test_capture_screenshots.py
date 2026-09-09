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
        ini = Path(__file__).resolve().parents[1] / "screenshots.ini"
        if not ini.is_file():
            ini = Path("/tmp/qa-completion-tests/screenshots.ini")
        if not ini.is_file():
            self.skipTest("screenshots.ini is not beside the copied tools")
        pages = {page.name: page for page in MODULE.parse_pages(ini)}
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


if __name__ == "__main__":
    unittest.main()
