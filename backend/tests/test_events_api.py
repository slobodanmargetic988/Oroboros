from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.api import events as events_api
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models import AuditLog


class EventsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db_session] = override_db
        self.events_session_patch = patch.object(events_api, "SessionLocal", self.session_factory)
        self.events_session_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.events_session_patch.stop()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_events_timeline_stream_and_schema_are_versioned(self) -> None:
        create_response = self.client.post(
            "/api/runs",
            json={
                "title": "Streamable run",
                "prompt": "Build event stream",
                "route": "/codex",
                "created_by": None,
                "note": "timeline test",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        run_id = create_response.json()["id"]

        timeline_response = self.client.get(f"/api/runs/{run_id}/events")
        self.assertEqual(timeline_response.status_code, 200)
        events = timeline_response.json()
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "run_created")
        self.assertEqual(events[0]["schema_version"], 1)
        self.assertEqual(events[0]["payload"]["schema_version"], 1)

        stream_response = self.client.get(
            f"/api/runs/{run_id}/events/stream",
            params={"follow": "false"},
        )
        self.assertEqual(stream_response.status_code, 200)
        self.assertIn("event: run_event", stream_response.text)
        self.assertIn('"schema_version": 1', stream_response.text)

        schema_response = self.client.get("/api/events/schema")
        self.assertEqual(schema_response.status_code, 200)
        schema_payload = schema_response.json()
        self.assertEqual(schema_payload["version"], 1)
        self.assertEqual(schema_payload["stream"]["protocol"], "sse")

        with self.session_factory() as db:
            actions = [row.action for row in db.query(AuditLog).order_by(AuditLog.id.asc()).all()]
            self.assertIn("run.prompt.submitted", actions)


if __name__ == "__main__":
    unittest.main()
