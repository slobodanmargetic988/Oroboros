# COMMIT REVIEW TASKS

## MYO-23 Review

### Executive Summary
- Review target: `codex/myo-23-preview-db-reset-seed` (active head `72ec350`; tested handoff commit referenced in Linear: `c42c035`).
- Gate check: **passed** (`Agent test DONE`).
- Acceptance criteria coverage in code:
  - reset scripts implemented per slot DB (`scripts/preview-db-reset.sh`, `scripts/preview-db-seed.sh`, `scripts/preview-db-reset-and-seed.sh`).
  - seed/snapshot provenance tracked (`backend/app/models/preview_db_reset.py`, migration `backend/alembic/versions/20260216_0002_preview_db_resets.py`).
  - allocation flow integration implemented (`backend/app/services/slot_allocation.py`, `backend/app/services/slot_allocation_cli.py`).
- Host-only policy check: pass (no Docker/container orchestration in implementation paths).
- Verification rerun:
  - `bash -n scripts/preview-db-reset.sh scripts/preview-db-seed.sh scripts/preview-db-reset-and-seed.sh scripts/preview-slot-allocate.sh`
  - `PYTHONPATH=. .venv/bin/python -m compileall app`
  - `DATABASE_URL=sqlite+pysqlite:////tmp/oroboros_myo23_review.sqlite .venv/bin/alembic -c alembic.ini upgrade head`
  - live repro (below) confirms slot lease contract regression.

### Findings (P0-P3)

#### P0

##### Finding MYO23-P0-1
- **Priority:** P0
- **Commit hash:** `72ec35057a34ac6bbc85f3fff10469138cd10ed1`
- **File + line:**
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/app/services/slot_allocation.py:12`
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/app/services/slot_allocation.py:39`
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/app/services/slot_allocation.py:117`
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/app/core/config.py:11`
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/app/services/slot_lease_manager.py:85`
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/app/services/slot_lease_manager.py:103`
- **Issue summary:** `slot_allocation` diverges from MYO-21 slot contract by using slot IDs `preview1|2|3` and lease state `active`, while lease manager/config use `preview-1|2|3` and state `leased`.
- **Impact:** Allocation can ignore occupied leased slots and create parallel lease rows for alias slot IDs, breaking exclusivity and creating double-allocation risk.
- **Evidence (live repro):**
  - Seeded `slot_leases` with `('preview-1','run-existing','leased')`.
  - Called allocation for new run with `dry_run=True`.
  - Result:
    - `allocated_slot preview1`
    - `lease_rows [('preview-1', 'run-existing', 'leased'), ('preview1', 'run-target', 'active')]`
- **Recommended fix:** Reuse shared slot/lease contract semantics: configured slot IDs (`slot_ids_csv`) and `leased`/`released`/`expired` lease states; avoid introducing alias IDs into persisted `slot_leases`; add regression test covering pre-existing leased `preview-1` allocation behavior.
- **Confidence:** high
- **Verification steps:**
  1. Create temp DB and migrate head.
  2. Insert run + leased slot row with `slot_id='preview-1'`, `lease_state='leased'`.
  3. Invoke `allocate_slot_for_run(..., dry_run=True)`.
  4. Confirm allocator must not return same semantic slot and must not create `preview1` alias row.
- **Status:** OPEN

#### P1

##### Finding MYO23-P1-1
- **Priority:** P1
- **Commit hash:** `72ec35057a34ac6bbc85f3fff10469138cd10ed1`
- **File + line:**
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/alembic/versions/20260216_0002_preview_db_resets.py:16`
  - `/Users/slobodan/.codex/worktrees/7e30/Oroboros/backend/alembic/versions/20260216_0002_slot_worktree_bindings.py:16`
- **Issue summary:** MYO-23 and MYO-24 both define Alembic revision `20260216_0002` with same `down_revision`, creating a multi-head/conflict risk when the unmerged chain is integrated.
- **Impact:** Merge/integration migration flow becomes ambiguous and can break `alembic upgrade head` expectations in combined branch.
- **Recommended fix:** Rebase one branch migration to a unique revision ID (and corresponding `down_revision` chain or explicit merge migration) before human merge.
- **Confidence:** high
- **Verification steps:**
  1. Compare revision constants in both migration files.
  2. In integrated branch containing both migrations, run `alembic heads` and `alembic upgrade head`.
  3. Confirm single linear head after fix.
- **Status:** OPEN

#### P2
- No findings.

#### P3

##### Finding MYO23-P3-1
- **Priority:** P3
- **Issue summary:** Tested handoff SHA (`c42c035`) and active review branch SHA (`72ec350`) differ due rebase/main-sync branch handling.
- **Impact:** Low traceability risk during final handoff.
- **Recommended fix:** Keep a single canonical review branch reference in Linear comments and indicate which SHA is final merge candidate.
- **Confidence:** high
- **Verification steps:**
  1. Compare `refs/remotes/origin/codex/myo-23-preview-db-reset-seed` and `refs/remotes/origin/codex/myo-23-preview-db-reset-seed-rebased-main`.
  2. Ensure reviewer target SHA is explicitly pinned.
- **Status:** OPEN

### Duplicate Merge Notes
- MYO-23 source files are patch-equivalent between `c42c035` and `72ec350` for feature implementation paths; divergence is primarily branch-management/report metadata.

MYO-23 decision: CHANGES_REQUIRED

---

## MYO-24 Review

### Executive Summary
- Review target: `codex/myo-24-worktree-manager` (active head `7f106e8`; tested handoff commit referenced in Linear: `4c4e39c`).
- Gate check: **passed** (`Agent test DONE`).
- Acceptance criteria coverage in code:
  - branch naming enforcement `codex/run-<id>` (`backend/app/services/git_worktree_manager.py`).
  - create/reuse/cleanup flow implemented (`backend/app/api/worktrees.py`, `backend/app/services/git_worktree_manager.py`).
  - persisted auditable slot-worktree mapping (`backend/app/models/slot_worktree_binding.py`, migration `backend/alembic/versions/20260216_0002_slot_worktree_bindings.py`, run events + audit logs).
- Host-only policy check: pass (no Docker/container dependency introduced).
- Verification rerun:
  - `DATABASE_URL=sqlite+pysqlite:////tmp/oroboros_myo24_review.sqlite .venv/bin/alembic -c alembic.ini upgrade head`
  - `PYTHONPATH=. .venv/bin/python -m compileall app`

### Findings (P0-P3)

#### P0
- No findings.

#### P1

##### Finding MYO24-P1-1
- **Priority:** P1
- **Commit hash:** `7f106e8d7e6d7a80d40c9799f92283a30c7edc4e`
- **File + line:**
  - `/Users/slobodan/.codex/worktrees/7e30/Oroboros/backend/alembic/versions/20260216_0002_slot_worktree_bindings.py:16`
  - `/Users/slobodan/.codex/worktrees/e72c/Oroboros/backend/alembic/versions/20260216_0002_preview_db_resets.py:16`
- **Issue summary:** Alembic revision ID collision with MYO-23 (`20260216_0002`) in unmerged chain context.
- **Impact:** Integration/migration sequencing risk for combined release branch.
- **Recommended fix:** Renumber/rebase one migration so integrated chain has a single deterministic head.
- **Confidence:** high
- **Verification steps:**
  1. Verify duplicate revision IDs in both migration files.
  2. Build integrated branch with both commits and run `alembic heads`.
  3. Ensure fix leaves one intended head.
- **Status:** OPEN

#### P2
- No findings.

#### P3

##### Finding MYO24-P3-1
- **Priority:** P3
- **Issue summary:** Tested SHA (`4c4e39c`) and active branch SHA (`7f106e8`) differ due post-test main-sync/rebase branching.
- **Impact:** Low provenance ambiguity.
- **Recommended fix:** Keep one canonical merge-target SHA in Linear and link companion sync branch explicitly.
- **Confidence:** high
- **Verification steps:**
  1. Compare `origin/codex/myo-24-worktree-manager` vs `origin/codex/myo-24-worktree-manager-main-sync`.
  2. Confirm reviewer is pointed at intended SHA for merge.
- **Status:** OPEN

### Duplicate Merge Notes
- MYO-24 implementation files are patch-equivalent between `4c4e39c` and `7f106e8`; diffs are in coordination/report metadata (`README.md`, `reports/SPRINT_EXECUTION_LOG.md`).

MYO-24 decision: CHANGES_REQUIRED
