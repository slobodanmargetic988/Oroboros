from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from sqlalchemy.orm import Session

from app.models import Run


ACTIVE_QUEUE_STATES = {"queued", "planning", "editing", "testing"}
TERMINAL_STATES = {"merged", "failed", "canceled", "expired"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(started_at: datetime, ended_at: datetime) -> float:
    return max(0.0, (ended_at - started_at).total_seconds())


def collect_core_metrics(db: Session) -> dict[str, object]:
    queue_depth = (
        db.query(Run)
        .filter(Run.status.in_(sorted(ACTIVE_QUEUE_STATES)))
        .count()
    )

    terminal_runs = (
        db.query(Run)
        .filter(Run.status.in_(sorted(TERMINAL_STATES)))
        .all()
    )
    terminal_count = len(terminal_runs)
    failed_count = sum(1 for item in terminal_runs if item.status == "failed")
    durations = [_duration_seconds(item.created_at, item.updated_at) for item in terminal_runs]

    avg_duration_seconds = float(mean(durations)) if durations else 0.0
    max_duration_seconds = max(durations) if durations else 0.0
    failure_rate = (failed_count / terminal_count) if terminal_count else 0.0

    return {
        "observed_at": _utcnow_iso(),
        "queue_depth": queue_depth,
        "duration_seconds": {
            "avg": round(avg_duration_seconds, 3),
            "max": round(max_duration_seconds, 3),
            "sample_size": terminal_count,
        },
        "failure_rate": round(failure_rate, 6),
        "failed_runs": failed_count,
        "terminal_runs": terminal_count,
    }
