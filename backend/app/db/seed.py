from __future__ import annotations

from app.db.session import SessionLocal
from app.models import Run, RunContext, User
from app.services.run_event_log import append_audit_log, append_run_event


def seed_local_data() -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "dev@ouroboros.local").first()
        if existing:
            return

        user = User(email="dev@ouroboros.local", name="Local Developer", role="developer")
        db.add(user)
        db.flush()

        run = Run(
            title="Local seeded run",
            prompt="Seeded control-plane example",
            status="queued",
            route="/codex",
            created_by=user.id,
            slot_id="preview-1",
            branch_name="codex/run-seed",
        )
        db.add(run)
        db.flush()

        db.add(
            RunContext(
                run_id=run.id,
                route="/codex",
                page_title="Codex",
                note="Seed data for local development",
                metadata_json={"source": "seed"},
            )
        )

        append_run_event(
            db,
            run_id=run.id,
            event_type="queued",
            status_to="queued",
            payload={"source": "seed"},
            actor_id=user.id,
        )

        append_audit_log(db, actor_id=user.id, action="seed.local_data", payload={"run_id": run.id})

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_local_data()
