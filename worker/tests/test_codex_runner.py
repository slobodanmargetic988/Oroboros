from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from worker.codex_runner import build_codex_command, run_codex_command
from worker.codex_runner import LeaseExpiredSignal, RunCanceledSignal


class BuildCodexCommandTests(unittest.TestCase):
    def test_build_command_from_template(self) -> None:
        previous = os.environ.get("WORKER_CODEX_COMMAND_TEMPLATE")
        os.environ["WORKER_CODEX_COMMAND_TEMPLATE"] = "codex run --cwd {worktree_path} --prompt {prompt}"
        try:
            command = build_codex_command("hello world", Path("/tmp/example"))
        finally:
            if previous is None:
                os.environ.pop("WORKER_CODEX_COMMAND_TEMPLATE", None)
            else:
                os.environ["WORKER_CODEX_COMMAND_TEMPLATE"] = previous

        self.assertEqual(command[:3], ["codex", "run", "--cwd"])
        self.assertIn("/tmp/example", command)
        self.assertIn("hello world", command)


class RunCodexCommandTests(unittest.TestCase):
    def test_capture_stdout_to_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "run.log"
            result = run_codex_command(
                command=[sys.executable, "-c", "print('worker-output')"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=5,
                poll_interval_seconds=0.05,
            )

            self.assertEqual(result.exit_code, 0)
            self.assertFalse(result.timed_out)
            self.assertFalse(result.canceled)
            self.assertFalse(result.lease_expired)
            self.assertIn("worker-output", output_path.read_text(encoding="utf-8"))

    def test_timeout_kills_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "timeout.log"
            result = run_codex_command(
                command=[sys.executable, "-c", "import time; time.sleep(2)"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=1,
                poll_interval_seconds=0.05,
            )

            self.assertTrue(result.timed_out)

    def test_cancel_stops_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "cancel.log"
            ticks = {"count": 0}

            def should_cancel() -> bool:
                ticks["count"] += 1
                return ticks["count"] >= 2

            result = run_codex_command(
                command=[sys.executable, "-c", "import time; time.sleep(10)"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=30,
                poll_interval_seconds=0.05,
                should_cancel=should_cancel,
            )

            self.assertTrue(result.canceled)

    def test_on_tick_run_canceled_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "cancel-signal.log"

            def on_tick() -> None:
                raise RunCanceledSignal()

            result = run_codex_command(
                command=[sys.executable, "-c", "import time; time.sleep(5)"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=30,
                poll_interval_seconds=0.05,
                on_tick=on_tick,
            )

            self.assertTrue(result.canceled)

    def test_on_tick_lease_expired_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "lease-expired.log"

            def on_tick() -> None:
                raise LeaseExpiredSignal()

            result = run_codex_command(
                command=[sys.executable, "-c", "import time; time.sleep(5)"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=30,
                poll_interval_seconds=0.05,
                on_tick=on_tick,
            )

            self.assertTrue(result.lease_expired)


if __name__ == "__main__":
    unittest.main()
