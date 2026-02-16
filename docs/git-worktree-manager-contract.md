# Git Worktree Manager Contract (MYO-24)

Defines A1 backend branch/worktree lifecycle behavior bound to preview slots.

## Branch Naming Enforcement
- Canonical branch format is enforced server-side: `codex/run-<run_id>`.
- Branch names are derived from `run_id`; run IDs outside `[A-Za-z0-9-]+` are rejected.
- If a run already has a conflicting `branch_name`, assignment is rejected.

## Slot-to-Worktree Binding Persistence
- `slot_worktree_bindings` stores one persisted binding row per slot:
  - `slot_id`
  - `run_id`
  - `branch_name`
  - `worktree_path`
  - `binding_state` (`active` or `released`)
  - `last_action` (`assigned`, `reused`, `cleaned_up`)
  - `created_at`, `updated_at`, `released_at`
- This table provides an auditable source of slot mapping state.

## Auditing and Event Trail
- Run-level events emitted:
  - `worktree_assigned`
  - `worktree_reused`
  - `worktree_cleaned`
- Audit log actions emitted:
  - `worktree.assign`
  - `worktree.reuse`
  - `worktree.cleanup`

## API Endpoints
- `GET /api/worktrees`
  - Returns current binding state per configured slot.
- `POST /api/worktrees/assign`
  - Body: `{ "run_id": "<id>", "slot_id": "preview-1|2|3" }`
  - Requires an active slot lease for the same `run_id` and `slot_id`.
  - Creates or reuses worktree for the slot path.
- `POST /api/worktrees/{slot_id}/cleanup`
  - Body: `{ "run_id": "<id>" }` (optional run guard)
  - Removes worktree registration and marks binding as released.
- `GET /api/worktrees/contract`
  - Returns branch pattern and supported operations.

## Safety Rules
- Non-interactive git commands only.
- Uses `git worktree add` and `git worktree remove` (no force remove).
- No destructive `reset --hard` or branch rewrite operations.
- Slot assign requires active lease ownership to prevent cross-run clobbering.
