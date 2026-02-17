from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models import Run, RunArtifact, ValidationCheck


class ArtifactsApiTests(unittest.TestCase):
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
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_run(self) -> str:
        with self.session_factory() as db:
            run = Run(
                title="artifact run",
                prompt="artifact run",
                status="testing",
                route="/codex",
            )
            db.add(run)
            db.commit()
            return run.id

    def test_serves_linked_run_artifact_file_content(self) -> None:
        run_id = self._create_run()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_file = Path(tmpdir) / "worker.log"
            artifact_file.write_text("hello artifact log\n", encoding="utf-8")

            with self.session_factory() as db:
                db.add(
                    RunArtifact(
                        run_id=run_id,
                        artifact_type="codex_stdout",
                        artifact_uri=str(artifact_file),
                        metadata_json=None,
                    )
                )
                db.commit()

            with patch.dict(os.environ, {"WORKER_ARTIFACT_ROOT": tmpdir}, clear=False):
                response = self.client.get(
                    f"/api/runs/{run_id}/artifacts/content",
                    params={"uri": str(artifact_file)},
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn("hello artifact log", response.text)

    def test_serves_linked_validation_check_artifact_file_content(self) -> None:
        run_id = self._create_run()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_file = Path(tmpdir) / "lint.log"
            artifact_file.write_text("lint ok\n", encoding="utf-8")

            with self.session_factory() as db:
                db.add(
                    ValidationCheck(
                        run_id=run_id,
                        check_name="lint",
                        status="passed",
                        started_at=None,
                        ended_at=None,
                        artifact_uri=str(artifact_file),
                    )
                )
                db.commit()

            with patch.dict(os.environ, {"WORKER_ARTIFACT_ROOT": tmpdir}, clear=False):
                response = self.client.get(
                    f"/api/runs/{run_id}/artifacts/content",
                    params={"uri": str(artifact_file)},
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn("lint ok", response.text)

    def test_rejects_non_linked_uri(self) -> None:
        run_id = self._create_run()
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_file = Path(tmpdir) / "missing.log"
            artifact_file.write_text("no link\n", encoding="utf-8")
            with patch.dict(os.environ, {"WORKER_ARTIFACT_ROOT": tmpdir}, clear=False):
                response = self.client.get(
                    f"/api/runs/{run_id}/artifacts/content",
                    params={"uri": str(artifact_file)},
                )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json().get("detail"), "artifact_not_linked_to_run")


if __name__ == "__main__":
    unittest.main()
