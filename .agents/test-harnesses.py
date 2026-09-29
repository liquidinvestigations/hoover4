#!/usr/bin/env python3
"""Verify harness adapters and installers with temporary configuration files."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ".agents" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HarnessTests(unittest.TestCase):
    def test_cursor_jsonc_and_crash_setting(self):
        cursor = load("update-cursor-config")
        source = '{// Keep this comment.\n"path": "//home/example", "pattern": "/*/",}\n'
        self.assertEqual(cursor.parse_json_object(source, "fixture"), {
            "path": "//home/example", "pattern": "/*/",
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "argv.json"
            for source in (
                '{\n// "enable-crash-reporter": false\n"other": true // Keep this comment.\n}\n',
                '{\n/* "enable-crash-reporter": true */\n"enable-crash-reporter": true,\n}\n',
                '{\n// Keep this comment.\n}\n',
            ):
                with self.subTest(source=source):
                    path.write_text(source)
                    self.assertFalse(cursor.argv_is_off(path))
                    rendered = cursor.argv_text(path)
                    path.write_text(rendered)
                    self.assertTrue(cursor.argv_is_off(path))
                    self.assertEqual(cursor.argv_text(path), rendered)
                    if "Keep this comment." in source:
                        self.assertIn("Keep this comment.", rendered)

    def test_cursor_installer_preserves_user_values(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            paths = {name: home / f"{name}.json" for name in (
                "permissions", "settings", "cli-config", "argv", "claude-settings",
            )}
            paths["settings"].write_text('{"window.setting": true}')
            paths["claude-settings"].write_text(json.dumps({
                "autoMode": {"environment": ["Use the development host."], "allow": ["$defaults"]},
            }))
            command = [sys.executable, str(ROOT / ".agents/update-cursor-config.py")]
            for name, path in paths.items():
                command.extend([f"--{name}", str(path)])
            subprocess.run(command + ["--apply"], check=True, capture_output=True)
            subprocess.run(command + ["--check"], check=True, capture_output=True)
            settings = json.loads(paths["settings"].read_text())
            self.assertTrue(settings["window.setting"])
            permissions = json.loads(paths["permissions"].read_text())
            self.assertIn("Use the development host.", permissions["autoRun"]["allow_instructions"])

    def test_kimi_installer_preserves_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / "config.toml"
            config.write_text('default_model = "example"\n[models.example]\nmodel = "example"\n')
            tui = home / "tui.toml"
            tui.write_text('[display]\ncolor = true\n')
            command = [sys.executable, str(ROOT / ".agents/update-kimi-config.py"), "--home", directory]
            subprocess.run(command + ["--apply"], check=True, capture_output=True)
            subprocess.run(command + ["--check"], check=True, capture_output=True)
            settings = tomllib.loads(config.read_text())
            self.assertEqual(settings["models"]["example"]["model"], "example")
            settings = tomllib.loads(tui.read_text())
            self.assertTrue(settings["disable_feedback_survey"])
            self.assertEqual(settings["display"], {"color": True})

    def hook(self, event, payload, env=None):
        result = subprocess.run(
            [sys.executable, str(ROOT / ".agents/hooks/cursor-wrap.py"), event],
            input=json.dumps(payload), text=True, capture_output=True, check=True, env=env,
        )
        return json.loads(result.stdout) if result.stdout else {}

    def test_cursor_tool_decisions(self):
        bad = self.hook("before-shell", {"command": "grep -rn example ."})
        good = self.hook("before-shell", {"command": "grep -rn example --include=*.py ."})
        self.assertEqual(bad["permission"], "deny")
        self.assertEqual(good["permission"], "allow")

    def test_cursor_concurrent_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, XDG_RUNTIME_DIR=directory, HOOVER4_MAX_SUBAGENTS="2")
            payload = {"subagent_type": "generalPurpose"}
            with ThreadPoolExecutor(max_workers=8) as pool:
                decisions = list(pool.map(lambda _: self.hook("subagent-start", payload, env), range(8)))
            self.assertEqual(sum(item["permission"] == "allow" for item in decisions), 2)
            self.assertEqual(self.hook("subagent-start", {"subagent_type": "explore"}, env)["permission"], "allow")
            self.hook("subagent-stop", {"subagent_type": "explore"}, env)
            self.assertEqual(self.hook("subagent-start", payload, env)["permission"], "deny")
            self.hook("subagent-stop", payload, env)
            self.assertEqual(self.hook("subagent-start", payload, env)["permission"], "allow")

    def test_cursor_agents_render_from_claude_roles(self):
        path = ROOT / ".agents" / "harnesses" / "render_cursor_agents.py"
        spec = importlib.util.spec_from_file_location("render_cursor_agents", path)
        render = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(render)
        models = json.loads((ROOT / ".agents/harnesses/cursor.json").read_text())["models"]
        files = render.render_all()
        self.assertEqual(set(files), {"organizer", "executor-light", "executor-heavy", "reviewer"})
        for role, text in files.items():
            with self.subTest(role=role):
                self.assertTrue(text.startswith(f"---\nname: {role}\n"))
                self.assertIn(f"\nmodel: {models[role]}\n", text)
                self.assertNotIn("\neffort:", text)
                self.assertEqual("\nreadonly: true\n" in text, role == "reviewer")
        result = subprocess.run([sys.executable, str(path), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


class BudgetHookTests(unittest.TestCase):
    """Verify opt-in counting through the hook's public input and output."""

    def invoke(self, directory, budget=None, payload=None):
        env = dict(os.environ, XDG_RUNTIME_DIR=directory)
        env.pop("HOOVER4_TOOL_BUDGET", None)
        if budget is not None:
            env["HOOVER4_TOOL_BUDGET"] = budget
        result = subprocess.run(
            [sys.executable, str(ROOT / ".agents/hooks/warn-tool-call-budget.py")],
            input=json.dumps(payload if payload is not None else {"agent_id": "worker"}),
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_default_and_invalid_budgets_are_silent(self):
        for value in (None, "", "0", "-1", "invalid"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                self.assertEqual(self.invoke(directory, value), "")
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_explicit_budget_warns_at_thresholds_only(self):
        with tempfile.TemporaryDirectory() as directory:
            output = [self.invoke(directory, "20") for _ in range(21)]
            self.assertEqual([i + 1 for i, text in enumerate(output) if text], [16, 19])
            event = json.loads(output[15])["hookSpecificOutput"]
            self.assertEqual(event["hookEventName"], "PostToolUse")
            self.assertIn("4 left", event["additionalContext"])

    def test_missing_agent_id_does_not_create_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.invoke(directory, "20", {"session_id": "root"}), "")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_agents_have_separate_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.invoke(directory, "2", {"agent_id": "first"}),
                             self.invoke(directory, "2", {"agent_id": "second"}))
            self.assertEqual(self.invoke(directory, "2", {"agent_id": "first"}), "")

    def test_orientation_preserves_compaction_signal(self):
        result = subprocess.run(
            ["bash", str(ROOT / ".agents/hooks/session-start-orientation.sh")],
            input='{"source":"compact"}', capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        event = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(event["hookEventName"], "SessionStart")
        self.assertIn("Context was just compacted.", event["additionalContext"])
        self.assertIn("AGENTS.md", event["additionalContext"])


if __name__ == "__main__":
    unittest.main()
