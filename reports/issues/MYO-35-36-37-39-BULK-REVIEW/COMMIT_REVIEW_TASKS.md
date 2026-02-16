# COMMIT REVIEW TASKS

Task identifier: `MYO-35-36-37-39-BULK-REVIEW`  
Mode: `review`  
Tracking mode: `local`  
Review selector: `commits=4`  
Review range: `6873cc2..b6c1727`  
Merged commits in scope: `90c959b` (MYO-35), `5d3ed28` (MYO-36), `ad231db` (MYO-37), `b6c1727` (MYO-39)

## Executive Summary
Review result: `review_blocked`.

No P0 issues were found. Two P1 regressions were confirmed with failing tests: missing audit actions in approvals flow (`P1-1`) and missing audit actions in worker lifecycle flow (`P1-2`). Two P2 correctness risks were found in lifecycle notifications (`P2-1`, `P2-2`). One cross-task trace-correlation gap is ambiguous and marked `NEEDS_MANUAL_VERIFICATION` (`P3-1`).

## Top Urgent Items
1. `P1-1` - Restore MYO-36 audit action coverage in approvals transitions.
2. `P1-2` - Restore MYO-36 audit action coverage in worker run lifecycle transitions.
3. `P2-1` - Add `expired` notification trigger so MYO-39 recoverable-timeout flows are visible.

## Findings By Priority (P0-P3)
### P0
None.

### P1
#### P1-1
Task: `MYO-36`  
Severity: `P1`  
Summary: Approvals flow no longer writes required audit actions; append-only audit trail coverage regressed.

Evidence:
- `backend/app/api/approvals.py:66` writes `RunEvent` directly in `_add_status_transition_event` instead of using `append_run_event(..., audit_action=...)`.
- `backend/app/api/approvals.py:130` and `backend/app/api/approvals.py:145` write approval/transition events directly without audit actions.
- `backend/tests/test_approvals_merge_gate.py:92` expects `run.approve.accepted`/merge/deploy actions in `audit_log`.
- Repro command failure:
  - `python3 -m unittest backend/tests/test_approvals_merge_gate.py`
  - Failure: `AssertionError: 'run.approve.accepted' not found in []`.

Impact:
- MYO-36 acceptance criteria for append-only audit action coverage is not met for approval/merge lifecycle actions.
- Forensics/compliance trail is incomplete.

Verification steps:
1. Run `python3 -m unittest backend/tests/test_approvals_merge_gate.py` and confirm failing assertion at `backend/tests/test_approvals_merge_gate.py:92`.
2. Execute a successful approve path and query `audit_log` for actions `run.approve.accepted`, `run.merge.started`, `run.deploy.started`, `run.deploy.completed`.

#### P1-2
Task: `MYO-36`  
Severity: `P1`  
Summary: Worker lifecycle transitions/events are written without audit actions; expected worker audit trail is missing.

Evidence:
- `worker/worker/orchestrator.py:469`, `worker/worker/orchestrator.py:526`, `worker/worker/orchestrator.py:656`, `worker/worker/orchestrator.py:701` write `RunEvent` directly for edit/test transitions/check events.
- `worker/tests/test_orchestrator_validation_pipeline.py:165` expects worker audit actions such as `run.edit.started` and `run.test.completed`.
- Repro command failure:
  - `python3 -m unittest tests/test_orchestrator_validation_pipeline.py` (from `/worker`)
  - Failure: `AssertionError: 'run.edit.started' not found in []`.

Impact:
- MYO-36 audit coverage is incomplete for worker execution lifecycle.
- Run lifecycle evidence is present in `run_events` but not mirrored into required append-only audit actions.

Verification steps:
1. Run `python3 -m unittest tests/test_orchestrator_validation_pipeline.py` in `/Users/slobodan/Projects/Oroboros/worker`.
2. Process a run and inspect `audit_log` for `run.edit.started`, `run.edit.completed`, `run.test.started`, `run.test.check_completed`, `run.test.completed`.

### P2
#### P2-1
Task: `MYO-37` (cross-task with `MYO-39`)  
Severity: `P2`  
Summary: Notification triggers omit `expired` state, so recoverable timeout outcomes from MYO-39 may not surface to users.

Evidence:
- `frontend/src/components/RunLifecycleNotifications.vue:75` defines `WATCHED_STATUSES` as `preview_ready`, `failed`, `merged`, `canceled` and excludes `expired`.
- MYO-39 recovery semantics rely on timeout/expiry flows (resume-eligible outcomes).

Impact:
- Users can miss notification of `expired` runs that are recoverable via resume semantics.
- Cross-task UX gap between MYO-37 notifications and MYO-39 timeout recovery behavior.

Verification steps:
1. Force a run to `expired` (preview timeout path).
2. Observe inbox/toast behavior in `RunLifecycleNotifications`.
3. Confirm no notification appears for `expired` transition while other watched states still notify.

#### P2-2
Task: `MYO-37`  
Severity: `P2`  
Summary: Notification polling is bounded to first 200 runs sorted by creation time, which can miss lifecycle transitions for older runs.

Evidence:
- `frontend/src/components/RunLifecycleNotifications.vue:243` polls `/api/runs` with `limit=200&offset=0`.
- `backend/app/api/runs.py:319` orders run list by `created_at.desc()` (not transition time / `updated_at`).

Impact:
- “Live” notifications are incomplete under larger datasets.
- Older runs outside first 200 can transition without producing notifications.

Verification steps:
1. Seed >200 runs.
2. Transition a run older than the newest 200 into a watched state (e.g., `failed`).
3. Confirm no new inbox/toast notification is generated.

### P3
#### P3-1 (NEEDS_MANUAL_VERIFICATION)
Task: `MYO-35` (cross-task with `MYO-39`)  
Severity: `P3`  
Summary: `cancel` and `resume` API endpoints do not explicitly carry trace fields/log emission like create/retry/transition paths.

Evidence:
- `backend/app/api/runs.py:391` (`cancel_run`) does not call `current_trace_id()` or emit `emit_structured_log(...)`.
- `backend/app/api/runs.py:468` (`resume_run`) does not call `current_trace_id()` and does not emit structured API log.
- `retry_run` does include trace wiring (`backend/app/api/runs.py:442`, `backend/app/api/runs.py:456`).

Impact:
- Potential trace-correlation inconsistency across API lifecycle operations.
- Severity kept low because desired trace behavior for these endpoints is not explicitly asserted in current tests/contracts.

Verification steps:
1. Call cancel/resume endpoints with `X-Trace-Id` set.
2. Inspect resulting run events and API logs.
3. Confirm whether trace linkage is expected for these operations under MYO-35 observability contract.

## Findings Grouped By Task
- `MYO-35`: `P3-1`
- `MYO-36`: `P1-1`, `P1-2`
- `MYO-37`: `P2-1`, `P2-2`
- `MYO-39`: `P2-1`, `P3-1`

## Duplicate Merge Notes
1. `P1-1` and `P1-2` share the same merge-interaction pattern: MYO-36 introduced audit/event helper usage, but merged result in critical files kept direct `RunEvent` writes while MYO-36 tests expecting audit actions remained.
2. Evidence of overlap/conflict surfaces in files touched by both MYO-35 and MYO-36 (`backend/app/api/approvals.py`, `worker/worker/orchestrator.py`), where observability-focused edits and audit-focused edits intersected.

## Per-Task Verdicts
### MYO-35 Verdict
`AT_RISK` - Trace/correlation infrastructure is broadly present, but cross-task API trace consistency remains uncertain (`P3-1`).

### MYO-36 Verdict
`FAIL` - Required append-only audit action coverage is regressed in approvals and worker lifecycle paths (`P1-1`, `P1-2`).

### MYO-37 Verdict
`AT_RISK` - Core notification UI exists, but trigger coverage and dataset-scaling behavior risk missed lifecycle transitions (`P2-1`, `P2-2`).

### MYO-39 Verdict
`PARTIAL_PASS_WITH_RISK` - Cancel/retry/resume core behavior is implemented, but cross-task visibility/tracing concerns remain (`P2-1`, `P3-1`).

## Review Checks Run
- `python3 -m unittest backend/tests/test_approvals_merge_gate.py` -> fail (`P1-1` evidence)
- `python3 -m unittest tests/test_orchestrator_validation_pipeline.py` (worker dir) -> fail (`P1-2` evidence)
- `python3 -m unittest backend/tests/test_runs_resilience.py` -> pass
- `python3 -m unittest backend/tests/test_events_api.py` -> pass
- `python3 -m unittest backend/tests/test_observability_metrics.py` -> pass

## Decision
- Decision: `review_blocked`
- Handoff target: `developer`
