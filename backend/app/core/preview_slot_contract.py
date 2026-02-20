from __future__ import annotations

from sqlalchemy.engine import make_url

_SLOT_TO_NUM = {
    "preview-1": 1,
    "preview1": 1,
    "preview-2": 2,
    "preview2": 2,
    "preview-3": 3,
    "preview3": 3,
}


def normalize_slot_id(slot_id: str) -> str:
    normalized = (slot_id or "").strip().lower()
    slot_num = _SLOT_TO_NUM.get(normalized)
    if slot_num is None:
        raise ValueError(f"invalid_slot_id:{slot_id}")
    return f"preview-{slot_num}"


def slot_number(slot_id: str) -> int:
    canonical = normalize_slot_id(slot_id)
    return int(canonical.rsplit("-", 1)[1])


def expected_preview_db_name(slot_id: str) -> str:
    return f"app_preview_{slot_number(slot_id)}"


def database_name_from_url(database_url: str) -> str | None:
    value = (database_url or "").strip()
    if not value:
        return None
    try:
        url = make_url(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"database_url_parse_failed:{exc}") from exc
    return url.database


def assert_preview_slot_database_binding(slot_id: str, database_url: str) -> str:
    expected_db = expected_preview_db_name(slot_id)
    db_name = database_name_from_url(database_url)
    if not db_name:
        raise ValueError("missing_database_name")
    if not db_name.startswith("app_preview_"):
        raise ValueError(f"non_preview_database_target:{db_name}")
    if db_name != expected_db:
        raise ValueError(f"slot_database_mismatch:expected={expected_db}:actual={db_name}")
    return expected_db
