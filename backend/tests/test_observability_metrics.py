from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.models import Run
from app.services.metrics_export import collect_core_metrics


class CoreMetricsExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _create_run(self, *, status: str, duration_seconds: int = 0) -> None:
        now = self._utcnow()
        with self.session_factory() as db:
            run = Run(
                title=f"run-{status}",
                prompt="metrics",
                status=status,
                route="/codex",
                created_at=now,
                updated_at=now + timedelta(seconds=duration_seconds),
            )
            db.add(run)
            db.commit()

    def test_collect_core_metrics_returns_expected_queue_and_failure_values(self) -> None:
        self._create_run(status="queued")
        self._create_run(status="planning")
        self._create_run(status="merged", duration_seconds=10)
        self._create_run(status="failed", duration_seconds=30)

        with self.session_factory() as db:
            payload = collect_core_metrics(db)

        self.assertEqual(payload["queue_depth"], 2)
        self.assertEqual(payload["terminal_runs"], 2)
        self.assertEqual(payload["failed_runs"], 1)
        self.assertEqual(payload["failure_rate"], 0.5)
        self.assertEqual(payload["duration_seconds"]["sample_size"], 2)
        self.assertEqual(payload["duration_seconds"]["avg"], 20.0)
        self.assertEqual(payload["duration_seconds"]["max"], 30.0)
        self.assertIn("observed_at", payload)


if __name__ == "__main__":
    unittest.main()
