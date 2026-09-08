import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import json


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


if __name__ == "__main__":
    unittest.main()
