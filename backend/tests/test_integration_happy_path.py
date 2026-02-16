from __future__ import annotations

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
from app.models import Run, RunArtifact, RunEvent
from app.services.integration_happy_path import (
    parse_slot_host_map,
    persist_happy_path_report_for_run,
    resolve_preview_host,
)


class IntegrationHappyPathServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_slot_host_map_parser_and_resolution(self) -> None:
        slot_map = parse_slot_host_map("preview-1=preview1.example.com,preview-2=preview2.example.com")
        self.assertEqual(slot_map["preview-1"], "preview1.example.com")
        self.assertEqual(resolve_preview_host("preview-2", slot_map), "preview2.example.com")
        self.assertEqual(resolve_preview_host("preview-9", slot_map), "preview1.example.com")

    def test_persist_happy_path_report_writes_artifact_and_event(self) -> None:
        with self.session_factory() as db:
            run = Run(
                title="Integration run",
                prompt="validate full path",
                status="merged",
                route="/codex",
            )
            db.add(run)
            db.commit()
            run_id = run.id

        report = {
            "summary": {"overall_status": "passed"},
            "post_deploy_health": {"status": "passed"},
            "events_count": 42,
        }
        artifact_uri = "file:///tmp/integration-report.json"

        with self.session_factory() as db:
            persist_happy_path_report_for_run(
                db=db,
                run_id=run_id,
                report=report,
                artifact_uri=artifact_uri,
            )

        with self.session_factory() as db:
            artifact = db.query(RunArtifact).filter(RunArtifact.run_id == run_id).first()
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.artifact_type, "integration_happy_path_report")
            self.assertEqual(artifact.artifact_uri, artifact_uri)

            event = (
                db.query(RunEvent)
                .filter(RunEvent.run_id == run_id, RunEvent.event_type == "integration_happy_path_completed")
                .first()
            )
            self.assertIsNotNone(event)
            payload = event.payload or {}
            self.assertEqual(payload.get("overall_status"), "passed")
            self.assertEqual(payload.get("artifact_uri"), artifact_uri)


if __name__ == "__main__":
    unittest.main()
