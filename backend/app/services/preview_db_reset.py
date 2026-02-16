from __future__ import annotations

from pathlib import Path
import subprocess

SLOT_ALIASES = {
    "preview1": "preview1",
    "preview-1": "preview1",
    "preview2": "preview2",
    "preview-2": "preview2",
    "preview3": "preview3",
    "preview-3": "preview3",
}

SLOT_DB_MAP = {
    "preview1": "app_preview_1",
    "preview2": "app_preview_2",
    "preview3": "app_preview_3",
}


def normalize_slot(slot_id: str) -> str:
    key = slot_id.strip().lower()
    if key not in SLOT_ALIASES:
        raise ValueError(f"Unknown slot_id '{slot_id}'")
    return SLOT_ALIASES[key]


def db_name_for_slot(slot_id: str) -> str:
    return SLOT_DB_MAP[normalize_slot(slot_id)]


def project_root() -> Path:
    # backend/app/services -> backend/app -> backend -> repo root
    return Path(__file__).resolve().parents[3]


def reset_and_seed_slot(
    *,
    slot_id: str,
    run_id: str,
    seed_version: str,
    strategy: str,
    snapshot_version: str | None = None,
    dry_run: bool = False,
) -> dict[str, str | bool | None]:
    root = project_root()
    script = root / "scripts" / "preview-db-reset-and-seed.sh"

    cmd = [
        str(script),
        "--slot",
        slot_id,
        "--run-id",
        run_id,
        "--strategy",
        strategy,
        "--seed-version",
        seed_version,
    ]
    if snapshot_version:
        cmd.extend(["--snapshot-version", snapshot_version])
    if dry_run:
        cmd.append("--dry-run")

    subprocess.run(cmd, check=True)

    return {
        "slot_id": normalize_slot(slot_id),
        "db_name": db_name_for_slot(slot_id),
        "strategy": strategy,
        "seed_version": seed_version,
        "snapshot_version": snapshot_version,
        "dry_run": dry_run,
    }
