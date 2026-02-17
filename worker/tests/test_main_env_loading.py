from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
WORKER_ROOT = WORKSPACE_ROOT / "worker"

if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from worker.main import load_worker_env_defaults


class WorkerMainEnvLoadingTests(unittest.TestCase):
    def test_loads_worker_dotenv_defaults_without_overriding_existing_env(self) -> None:
        env_file = WORKER_ROOT / ".env"
        original = env_file.read_text(encoding="utf-8") if env_file.exists() else None
        try:
            env_file.write_text(
                "\n".join(
                    [
                        "WORKER_ALLOWED_PATHS=/tmp/worktrees",
                        "WORKER_ALLOWED_COMMANDS=codex,python",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"WORKER_ALLOWED_COMMANDS": "codex,python,git"},
                clear=False,
            ):
                os.environ.pop("WORKER_ALLOWED_PATHS", None)
                load_worker_env_defaults()
                self.assertEqual(os.environ.get("WORKER_ALLOWED_PATHS"), "/tmp/worktrees")
                self.assertEqual(os.environ.get("WORKER_ALLOWED_COMMANDS"), "codex,python,git")
        finally:
            if original is None:
                try:
                    env_file.unlink()
                except FileNotFoundError:
                    pass
            else:
                env_file.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
