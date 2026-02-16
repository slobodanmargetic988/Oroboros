from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Run, SlotLease, SlotWorktreeBinding
from app.services.run_event_log import append_audit_log, append_run_event

BRANCH_PREFIX = "codex/run-"
ACTIVE_BINDING_STATE = "active"
RELEASED_BINDING_STATE = "released"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _configured_slot_ids() -> list[str]:
    settings = get_settings()
    raw = getattr(settings, "slot_ids_csv", "preview-1,preview-2,preview-3")
    slot_ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not slot_ids:
        return ["preview-1", "preview-2", "preview-3"]
    return slot_ids


def _repo_root_path() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "repo_root_path", "/srv/oroboros/repo")).expanduser().resolve()


def _worktree_root_path() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "worktree_root_path", "/srv/oroboros/worktrees")).expanduser().resolve()


def _branch_name_for_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]+", run_id):
        raise ValueError("invalid_run_id_for_branch")
    return f"{BRANCH_PREFIX}{run_id}"


def _slot_worktree_path(slot_id: str) -> Path:
    return (_worktree_root_path() / slot_id).resolve()


def _run_git(
    repo_path: Path,
    args: list[str],
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(repo_path), *args]
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 and not allow_failure:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise ValueError(f"git_command_failed:{stderr or 'unknown_error'}")
    return proc


def _list_registered_worktrees(repo_path: Path) -> dict[str, dict[str, str | None]]:
    proc = _run_git(repo_path, ["worktree", "list", "--porcelain"], allow_failure=True)
    if proc.returncode != 0:
        return {}

    items: dict[str, dict[str, str | None]] = {}
    current_path: str | None = None
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            current_path = None
            continue
        if line.startswith("worktree "):
            current_path = str(Path(line.removeprefix("worktree ").strip()).resolve())
            items[current_path] = {"branch": None, "head": None}
            continue
        if current_path is None:
            continue
        if line.startswith("branch "):
            branch_ref = line.removeprefix("branch ").strip()
            items[current_path]["branch"] = branch_ref.removeprefix("refs/heads/")
        elif line.startswith("HEAD "):
            items[current_path]["head"] = line.removeprefix("HEAD ").strip()
    return items


def _ensure_branch_exists(repo_path: Path, branch_name: str) -> None:
    proc = _run_git(
        repo_path,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        allow_failure=True,
    )
    if proc.returncode == 0:
        return
    _run_git(repo_path, ["branch", branch_name])


def _get_run_or_raise(db: Session, run_id: str) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise ValueError("run_not_found")
    return run


def _validate_slot(slot_id: str) -> None:
    if slot_id not in _configured_slot_ids():
        raise ValueError("invalid_slot_id")


def _ensure_active_slot_lease(db: Session, slot_id: str, run_id: str) -> None:
    now = _utcnow()
    lease = db.query(SlotLease).filter(SlotLease.slot_id == slot_id).first()
    if lease is None:
        raise ValueError("active_lease_required")
    if lease.run_id != run_id:
        raise ValueError("slot_bound_to_other_run")
    if lease.lease_state != "leased":
        raise ValueError("active_lease_required")
    if _normalize_utc(lease.expires_at) <= now:
        raise ValueError("active_lease_required")


def assign_worktree(db: Session, run_id: str, slot_id: str) -> dict[str, Any]:
    _validate_slot(slot_id)
    run = _get_run_or_raise(db, run_id)
    _ensure_active_slot_lease(db, slot_id, run_id)

    branch_name = _branch_name_for_run_id(run_id)
    if run.branch_name and run.branch_name != branch_name:
        raise ValueError("branch_name_conflict")
    if run.slot_id and run.slot_id != slot_id:
        raise ValueError("run_bound_to_other_slot")

    repo_path = _repo_root_path()
    if not (repo_path / ".git").exists():
        raise ValueError("repo_root_not_found")

    worktree_path = _slot_worktree_path(slot_id)
    worktree_root = _worktree_root_path()
    if worktree_root not in worktree_path.parents and worktree_path != worktree_root:
        raise ValueError("worktree_path_out_of_bounds")

    worktree_root.mkdir(parents=True, exist_ok=True)
    registered = _list_registered_worktrees(repo_path)
    resolved_path = str(worktree_path)

    binding = (
        db.query(SlotWorktreeBinding)
        .filter(SlotWorktreeBinding.slot_id == slot_id)
        .with_for_update()
        .first()
    )

    reused = False
    existing = registered.get(resolved_path)
    if (
        existing
        and existing.get("branch") == branch_name
        and binding is not None
        and binding.run_id == run_id
        and binding.binding_state == ACTIVE_BINDING_STATE
    ):
        reused = True
        action = "worktree.reuse"
        event_type = "worktree_reused"
    else:
        if existing and existing.get("branch") != branch_name:
            _run_git(repo_path, ["worktree", "remove", resolved_path])

        _ensure_branch_exists(repo_path, branch_name)
        registered = _list_registered_worktrees(repo_path)
        existing = registered.get(resolved_path)
        if existing and existing.get("branch") == branch_name:
            reused = True
            action = "worktree.reuse"
            event_type = "worktree_reused"
        else:
            _run_git(repo_path, ["worktree", "add", resolved_path, branch_name])
            action = "worktree.assign"
            event_type = "worktree_assigned"

    now = _utcnow()
    if binding is None:
        binding = SlotWorktreeBinding(
            slot_id=slot_id,
            run_id=run_id,
            branch_name=branch_name,
            worktree_path=resolved_path,
            binding_state=ACTIVE_BINDING_STATE,
            last_action="reused" if reused else "assigned",
        )
        db.add(binding)
    else:
        binding.run_id = run_id
        binding.branch_name = branch_name
        binding.worktree_path = resolved_path
        binding.binding_state = ACTIVE_BINDING_STATE
        binding.last_action = "reused" if reused else "assigned"
        binding.released_at = None
        binding.updated_at = now

    run.slot_id = slot_id
    run.branch_name = branch_name
    run.worktree_path = resolved_path

    payload = {
        "slot_id": slot_id,
        "run_id": run_id,
        "branch_name": branch_name,
        "worktree_path": resolved_path,
        "reused": reused,
    }
    append_run_event(db, run_id=run_id, event_type=event_type, payload=payload, actor_id=run.created_by)
    append_audit_log(db, action=action, payload=payload, actor_id=run.created_by)

    return {
        "assigned": True,
        "reused": reused,
        "slot_id": slot_id,
        "run_id": run_id,
        "branch_name": branch_name,
        "worktree_path": resolved_path,
    }


def cleanup_worktree(db: Session, slot_id: str, run_id: str | None = None) -> dict[str, Any]:
    _validate_slot(slot_id)

    binding = (
        db.query(SlotWorktreeBinding)
        .filter(SlotWorktreeBinding.slot_id == slot_id)
        .with_for_update()
        .first()
    )
    if binding is None or binding.binding_state != ACTIVE_BINDING_STATE:
        return {"cleaned": False, "slot_id": slot_id, "run_id": run_id, "reason": "no_active_binding"}

    if run_id is not None and binding.run_id != run_id:
        return {"cleaned": False, "slot_id": slot_id, "run_id": run_id, "reason": "slot_bound_to_other_run"}

    repo_path = _repo_root_path()
    if not (repo_path / ".git").exists():
        raise ValueError("repo_root_not_found")

    resolved_path = str(Path(binding.worktree_path or "").expanduser().resolve())
    registered = _list_registered_worktrees(repo_path)
    if resolved_path in registered:
        _run_git(repo_path, ["worktree", "remove", resolved_path])

    run = db.query(Run).filter(Run.id == binding.run_id).first() if binding.run_id else None
    now = _utcnow()
    binding.binding_state = RELEASED_BINDING_STATE
    binding.last_action = "cleaned_up"
    binding.released_at = now
    binding.updated_at = now

    owning_run_id = binding.run_id
    branch_name = binding.branch_name
    worktree_path = binding.worktree_path

    if run is not None:
        if run.slot_id == slot_id:
            run.slot_id = None
        if run.worktree_path == worktree_path:
            run.worktree_path = None

    payload = {
        "slot_id": slot_id,
        "run_id": owning_run_id,
        "branch_name": branch_name,
        "worktree_path": worktree_path,
    }
    if owning_run_id is not None:
        append_run_event(
            db,
            run_id=owning_run_id,
            event_type="worktree_cleaned",
            payload=payload,
            actor_id=run.created_by if run else None,
        )
    append_audit_log(db, action="worktree.cleanup", payload=payload, actor_id=run.created_by if run else None)

    return {
        "cleaned": True,
        "slot_id": slot_id,
        "run_id": owning_run_id,
        "branch_name": branch_name,
        "worktree_path": worktree_path,
        "reason": None,
    }


def list_worktree_bindings(db: Session) -> list[dict[str, Any]]:
    slot_ids = _configured_slot_ids()
    bindings = (
        db.query(SlotWorktreeBinding)
        .filter(SlotWorktreeBinding.slot_id.in_(slot_ids))
        .order_by(SlotWorktreeBinding.slot_id.asc())
        .all()
    )
    binding_map = {item.slot_id: item for item in bindings}

    rows: list[dict[str, Any]] = []
    for slot_id in slot_ids:
        binding = binding_map.get(slot_id)
        if binding is None:
            rows.append(
                {
                    "slot_id": slot_id,
                    "state": "unbound",
                    "run_id": None,
                    "branch_name": None,
                    "worktree_path": None,
                    "binding_state": None,
                    "last_action": None,
                    "updated_at": None,
                }
            )
            continue

        rows.append(
            {
                "slot_id": slot_id,
                "state": "bound" if binding.binding_state == ACTIVE_BINDING_STATE else "released",
                "run_id": binding.run_id,
                "branch_name": binding.branch_name,
                "worktree_path": binding.worktree_path,
                "binding_state": binding.binding_state,
                "last_action": binding.last_action,
                "updated_at": binding.updated_at,
            }
        )

    return rows
