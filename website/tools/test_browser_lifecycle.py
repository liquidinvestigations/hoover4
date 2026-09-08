import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from browser_lifecycle import BrowserOwner, close_owner, stop_process, stop_run


class BrowserLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_termination_is_awaited(self):
        process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(), wait=AsyncMock(return_value=0))
        await stop_process(process)
        process.terminate.assert_called_once()
        process.wait.assert_awaited_once()
        process.kill.assert_not_called()

    async def test_termination_timeout_kills_and_reaps(self):
        process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                  wait=AsyncMock(side_effect=[asyncio.TimeoutError(), 0]))
        await stop_process(process, timeout=0.01)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.await_count, 2)

    async def test_connection_error_preserves_process_cleanup(self):
        process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
        connection = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("connection failure")))
        browser = SimpleNamespace(tabs=[connection], aclose=AsyncMock())
        owner = BrowserOwner(process, Mock(), Mock(), browser)
        with self.assertRaises(ExceptionGroup):
            await close_owner(owner)
        process.wait.assert_awaited_once()
        owner.profile.cleanup.assert_called_once()
        owner.log.close.assert_called_once()
        self.assertTrue(owner.closed)
        await close_owner(owner)
        process.wait.assert_awaited_once()

    async def test_owned_group_is_stopped_after_parent_exit(self):
        import signal
        process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
        with patch("browser_lifecycle.os.killpg") as kill_group:
            await stop_process(process, process_group=42)
        self.assertEqual(kill_group.call_args_list[0].args, (42, signal.SIGTERM))
        self.assertEqual(kill_group.call_args_list[1].args, (42, signal.SIGKILL))


class RunnerOwnershipTests(unittest.TestCase):
    def test_interruption_stops_only_the_exact_runner_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            script = directory / "capture_screenshots.py"
            script.write_text("import time\ntime.sleep(60)\n")
            owned = subprocess.Popen([sys.executable, str(script)])
            unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                stop_run(directory, timeout=2)
                owned.wait(timeout=3)
                self.assertIsNone(unrelated.poll())
            finally:
                for process in (owned, unrelated):
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
