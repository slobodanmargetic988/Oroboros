from __future__ import annotations

from datetime import datetime, timezone
import uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())
