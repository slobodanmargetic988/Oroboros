from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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

        self.assertEqual(Path(command[0]).name, "codex")
        self.assertEqual(command[1:3], ["run", "--cwd"])
        self.assertIn("/tmp/example", command)
        self.assertIn("hello world", command)

    def test_build_command_uses_discovered_codex_binary_when_not_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=False), patch(
            "worker.codex_runner.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            os.environ.pop("WORKER_CODEX_COMMAND_TEMPLATE", None)
            os.environ.pop("WORKER_CODEX_BIN", None)
            command = build_codex_command("hello world", Path("/tmp/example"))

        self.assertEqual(command[0], "/usr/local/bin/codex")
        self.assertIn("hello world", command)


class RunCodexCommandTests(unittest.TestCase):
    @staticmethod
    def _allow_worktree(path: str):
        return patch.dict(os.environ, {"WORKER_ALLOWED_PATHS": path}, clear=False)

    def test_capture_stdout_to_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
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
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
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
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
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
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
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
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
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

    def test_process_start_failure_returns_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
            output_path = Path(tmp) / "start-failed.log"

            def failing_popen(*args, **kwargs):  # noqa: ANN002, ANN003
                raise FileNotFoundError("codex binary not found")

            result = run_codex_command(
                command=["codex", "run", "hello"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=30,
                poll_interval_seconds=0.05,
                popen_factory=failing_popen,
            )

            self.assertEqual(result.exit_code, 127)
            self.assertFalse(result.timed_out)
            self.assertFalse(result.canceled)
            self.assertFalse(result.lease_expired)
            self.assertIn("Failed to start command", output_path.read_text(encoding="utf-8"))

    def test_env_overlay_is_passed_to_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._allow_worktree(tmp):
            output_path = Path(tmp) / "env.log"
            result = run_codex_command(
                command=[sys.executable, "-c", "import os; print(os.getenv('TRACE_ID', 'missing'))"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=5,
                poll_interval_seconds=0.05,
                env={"TRACE_ID": "trace-test-123"},
            )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("trace-test-123", output_path.read_text(encoding="utf-8"))

    def test_command_allowlist_blocks_disallowed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"WORKER_ALLOWED_COMMANDS": "python,python3"},
            clear=False,
        ), self._allow_worktree(tmp):
            output_path = Path(tmp) / "blocked-command.log"
            result = run_codex_command(
                command=["bash", "-lc", "echo nope"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=5,
                poll_interval_seconds=0.05,
            )

            self.assertEqual(result.exit_code, 126)
            self.assertIn("Blocked by command allowlist", output_path.read_text(encoding="utf-8"))

    def test_shell_wrappers_are_blocked_even_if_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"WORKER_ALLOWED_COMMANDS": "python,python3,bash,sh"},
            clear=False,
        ), self._allow_worktree(tmp):
            output_path = Path(tmp) / "blocked-shell.log"
            result = run_codex_command(
                command=["bash", "-lc", "uname -s"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=5,
                poll_interval_seconds=0.05,
            )

            self.assertEqual(result.exit_code, 126)
            self.assertIn("Blocked by command allowlist", output_path.read_text(encoding="utf-8"))

    def test_path_allowlist_blocks_disallowed_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"WORKER_ALLOWED_PATHS": "/srv/oroboros/worktrees"},
            clear=False,
        ):
            output_path = Path(tmp) / "blocked-path.log"
            result = run_codex_command(
                command=[sys.executable, "-c", "print('ok')"],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=5,
                poll_interval_seconds=0.05,
            )

            self.assertEqual(result.exit_code, 126)
            self.assertIn("Blocked by path allowlist", output_path.read_text(encoding="utf-8"))

    def test_preview_subprocess_env_is_isolated_from_parent_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://secret",
                "WORKER_SUBPROCESS_ENV_ALLOWLIST": "PATH",
            },
            clear=False,
        ), self._allow_worktree(tmp):
            output_path = Path(tmp) / "env-isolation.log"
            result = run_codex_command(
                command=[
                    sys.executable,
                    "-c",
                    "import os; print(os.getenv('DATABASE_URL','missing')); print(os.getenv('RUN_ID','missing'))",
                ],
                worktree_path=Path(tmp),
                output_path=output_path,
                timeout_seconds=5,
                poll_interval_seconds=0.05,
                env={"RUN_ID": "run-123"},
            )

            log = output_path.read_text(encoding="utf-8")
            self.assertEqual(result.exit_code, 0)
            self.assertIn("missing", log)
            self.assertIn("run-123", log)


if __name__ == "__main__":
    unittest.main()
