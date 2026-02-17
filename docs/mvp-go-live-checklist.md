# MVP Go-Live Checklist (MYO-44)

Last updated: 2026-02-17

Scope: Final gate for MVP release readiness and signoff.

Mandatory constraint:
- Host deployment only (no Docker/Compose/Kubernetes release path).

## 1) Prerequisite Issues
- MYO-42 `[INT-01]` status: Done (completed 2026-02-16)
- MYO-43 `[INT-02]` status: Done (completed 2026-02-17)

## 2) Acceptance Criteria to Evidence Mapping

### A) MVP acceptance criteria mapped to concrete evidence
- Happy-path integration run reached merged/deploy states with expected timeline.
  - Evidence: MYO-42 tester event (`AGENT_EVENT_V1`, comment id `539c40aa-2c89-4fe2-9558-0254eed62c38`)
  - Evidence files:
    - `artifacts/integration/myo-42-02c5629a-00e9-4528-bc75-3085ab5012c5-run-20260216T231159.json`
    - `artifacts/integration/myo-42-02c5629a-00e9-4528-bc75-3085ab5012c5-checks-20260216T231159.json`
    - `artifacts/integration/myo-42-02c5629a-00e9-4528-bc75-3085ab5012c5-events-20260216T231159.json`
- Post-deploy health check succeeded.
  - Evidence file:
    - `artifacts/integration/myo-42-runtime-health-20260216T231159.log`

### B) Open high-priority risks documented and accepted/mitigated
- MYO-43 blockers were fixed and retested:
  - `POST /api/runs` invalid `created_by` now returns `422 invalid_created_by`
  - `scripts/preview-smoke-e2e.sh` wrapper now executes correctly
  - Evidence: MYO-43 retest event (`AGENT_EVENT_V1`, comment id `b150d7f5-2e76-4c93-a1f5-058ede62ad0f`)
  - Fix commit on `main`: `50e8302`

Residual risk register:
1. Reviewer identity input quality (operational)
   - Description: Approval/review flows assume `reviewer_id` is either omitted or an existing `users.id`.
   - Severity: Medium
   - Mitigation: UI/API clients must send known reviewer IDs or omit reviewer ID.
   - Owner: Operations/Control-plane API consumer.
   - Status: Mitigated by operating procedure; no blocker for MVP release.

### C) Go-live signoff recorded
- Signoff decision: Pending explicit owner confirmation.
- Approver: Pending
- Timestamp: Pending

## 3) Non-Container Compliance Gate
Validated as PASS.
- Runtime model and deployment scripts are host/service based.
- Integration validation (MYO-42) executed on host runtime.
- Failure-mode drills and rollback runbook (MYO-43) are host-only.
- Runbook path: `docs/operator-incident-rollback-runbook.md`

## 4) Release Decision
- Engineering readiness: PASS
- Operational drill readiness: PASS
- Remaining blocker to close MYO-44: explicit owner go-live signoff entry (approver + decision).
