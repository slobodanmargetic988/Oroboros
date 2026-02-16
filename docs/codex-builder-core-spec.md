# Codex Builder Core - Product and Technical Specification (v0.1)

## 1. Purpose
Codex Builder Core is a self-hosted application framework that lets users build and evolve websites or web apps by requesting changes in natural language. The system uses an AI coding agent (Codex CLI) to implement changes in isolated git worktrees, validate results, expose live preview environments, and merge approved changes into production.

## 2. Goals
1. Ship a stable production app from `main` at all times.
2. Allow users to request changes through a dedicated Codex interface and a global in-page shortcut.
3. Generate and test changes in isolated preview slots before merge.
4. Require explicit approval before merge to production.
5. Provide complete transparency of all handed-off tasks and run outcomes.
6. Keep operations auditable, secure, and rollback-safe.

## 3. Non-Goals (MVP)
1. Multi-tenant SaaS hosting in v1.
2. Unlimited concurrent previews.
3. Automatic database rollback for every arbitrary migration without predefined rules.
4. Full autonomous infra changes (DNS, cloud IAM, network policies) by AI agent.

## 4. Target Stack
1. Frontend: Vue 3 + Vite + TypeScript.
2. Backend API: Python FastAPI.
3. ORM: SQLAlchemy 2.x + Alembic.
4. Database: PostgreSQL.
5. Queue/Workers: Redis + RQ (or Celery; choose one, RQ preferred for MVP simplicity).
6. Reverse proxy: Caddy or Nginx.
7. Process runtime: Docker Compose or systemd services.
8. Agent runtime: Codex CLI installed on same Linux host.

## 5. High-Level Architecture
1. `web-main`: production app from `main` branch.
2. `web-preview-1`, `web-preview-2`, `web-preview-3`: fixed preview app instances.
3. `api`: FastAPI service for chat, run orchestration, diff/test/deploy metadata.
4. `worker`: background job executor invoking Codex CLI and validation pipeline.
5. `slot-manager`: lease allocator for preview slots and worktrees.
6. `postgres`: metadata DB + dedicated preview app DBs.
7. `redis`: queue, locks, heartbeat/lease coordination.
8. `git-control`: service module for branch/worktree lifecycle.

## 6. URLs and Environment Model
1. Production URL: `app.example.com` (always `main`).
2. Codex control page: `app.example.com/codex`.
3. Preview URLs: `preview1.example.com`, `preview2.example.com`, `preview3.example.com`.
4. Preview slot mapping is static:
5. `preview-1` -> worktree path `/srv/oroboros/worktrees/preview-1` -> DB `app_preview_1`.
6. `preview-2` -> worktree path `/srv/oroboros/worktrees/preview-2` -> DB `app_preview_2`.
7. `preview-3` -> worktree path `/srv/oroboros/worktrees/preview-3` -> DB `app_preview_3`.

## 7. User Experience
### 7.1 Primary Surfaces
1. Dedicated `/codex` page with chat, run list, and review actions.
2. Global shortcut (`Cmd/Ctrl+K`) opens Codex overlay from any page.
3. In-page context capture includes route, page title, selected element hint, optional screenshot.

### 7.2 Run Inbox (Task Visibility)
Every request becomes a tracked run visible in a "Codex Runs" inbox.

Each run displays:
1. Run ID and generated title.
2. User prompt and author.
3. Context route and element note.
4. Current state and progress stage.
5. Assigned preview slot and URL.
6. Diff summary (files changed, migration flag).
7. Validation summary (lint/tests/smoke).
8. Actions: `Open Preview`, `Approve Merge`, `Reject`, `Retry`, `Cancel`.

### 7.3 Per-Page Awareness
1. Show badge on pages with related active runs.
2. Filter runs by route and by status.
3. Show timeline of events for each run.

## 8. Run State Machine
Allowed states:
1. `queued`
2. `planning`
3. `editing`
4. `testing`
5. `preview_ready`
6. `needs_approval`
7. `approved`
8. `merging`
9. `deploying`
10. `merged`
11. `failed`
12. `canceled`
13. `expired`

Rules:
1. State transitions are append-only events plus current-state snapshot.
2. `failed`, `canceled`, `expired`, `merged` are terminal states.
3. Retry creates a new run linked to parent run ID.
4. Merge only allowed from `needs_approval` with valid preview lease.

## 9. Preview Slot Lease System
1. Exactly 3 slots exist.
2. Lease fields: `slot_id`, `run_id`, `leased_at`, `expires_at`, `heartbeat_at`.
3. Worker sends heartbeat every 15-30 seconds.
4. Lease TTL default 30 minutes idle, configurable.
5. Stale lease auto-reaped and slot returned to pool.
6. If all slots busy, run remains `queued` with reason `WAITING_FOR_SLOT`.
7. Optional policy: allow user to force-replace oldest idle `preview_ready` run.

## 10. Git and Worktree Strategy
1. Canonical repo at `/srv/oroboros/repo`.
2. Per-run branch naming: `codex/run-<run_id>`.
3. Worktree created in slot path and hard-bound to slot lease.
4. Merge target is always `main`.
5. No direct edits on `main` working directory by worker.
6. Use non-interactive git commands only.
7. Final merge gate reruns checks on exact commit hash.

## 11. Agent Execution Flow
1. User submits prompt with optional context note.
2. API creates run in `queued` and enqueues worker job.
3. Worker allocates preview slot lease.
4. Worker creates branch/worktree and injects structured task brief.
5. Codex CLI generates edits in that worktree.
6. Validation pipeline executes.
7. If validation passes, preview environment is started/reloaded and run enters `needs_approval`.
8. User tests live preview and chooses `Approve` or `Reject`.
9. On `Approve`, system reruns merge gate checks.
10. If gate passes, merge to `main`, deploy production, set run `merged`.
11. On `Reject`, run stays unmerged and slot can be released or retained briefly.

## 12. Validation Pipeline
Minimum checks:
1. Format/lint.
2. Unit tests.
3. App health check.
4. Route smoke tests including changed route and core routes.
5. Migration safety checks.

Policy:
1. Any failed required check blocks `needs_approval` and moves run to `failed`.
2. Check artifacts and logs are persisted and viewable.

## 13. Database Strategy
### 13.1 Control Plane DB
Use PostgreSQL database `builder_control` for metadata.

### 13.2 Preview App DBs
Use three fixed preview DBs:
1. `app_preview_1`
2. `app_preview_2`
3. `app_preview_3`

### 13.3 Deterministic Data
1. Reset preview DB from snapshot or deterministic seed before each new run.
2. Seed version is tracked per run for reproducibility.
3. Migration outcomes are logged per preview DB.

## 14. Security and Guardrails
1. Codex worker runs as restricted OS user with least privilege.
2. Command allowlist for tool execution.
3. Path allowlist for writable project directories.
4. Secret isolation between production and preview environments.
5. Network egress controls where feasible.
6. Risk policy engine marks sensitive changes as `manual_approval_required`.

Sensitive change examples:
1. Auth and permissions.
2. Billing and payments.
3. Destructive migrations.
4. Secrets, infra configs, deployment scripts.

## 15. Change Review and Approval UX
Before merge, UI must show:
1. Unified file diff.
2. Migration diff and impact warning.
3. Validation results.
4. Commands executed by agent.
5. Policy warnings and required approvals.

Approval actions:
1. `Approve and Merge`.
2. `Reject` with reason.
3. `Request Revision` (new linked run).

## 16. Deploy and Rollback
### 16.1 Deploy
1. Production deploy only from `main`.
2. Deploy is triggered automatically after approved merge.
3. Health checks must pass before run marked `merged`.

### 16.2 Rollback
1. Keep release records with `release_id`, commit SHA, DB migration marker.
2. Provide one-click rollback to last healthy release.
3. Rollback policy documented for irreversible migrations.

## 17. Observability and Auditability
1. Structured logs with `run_id`, `slot_id`, `commit_sha`, `user_id`.
2. Metrics: queue depth, run duration, failure rate, merge success rate, slot utilization.
3. Event timeline per run.
4. Append-only audit log for prompt, decisions, diffs, approvals, merge, deploy.
5. Trace IDs propagated from API through worker and deploy components.

## 18. API Specification (MVP)
### 18.1 Runs
1. `POST /api/runs` create run from prompt/context.
2. `GET /api/runs` list with filters.
3. `GET /api/runs/{run_id}` details.
4. `POST /api/runs/{run_id}/cancel` cancel.
5. `POST /api/runs/{run_id}/retry` retry as child run.

### 18.2 Review
1. `GET /api/runs/{run_id}/diff` diff payload.
2. `GET /api/runs/{run_id}/checks` validation summary.
3. `POST /api/runs/{run_id}/approve` approve merge.
4. `POST /api/runs/{run_id}/reject` reject run.

### 18.3 Slots and Preview
1. `GET /api/slots` slot statuses.
2. `GET /api/runs/{run_id}/preview` preview metadata.

### 18.4 Events
1. `GET /api/runs/{run_id}/events` run timeline.
2. SSE or WebSocket endpoint for live status updates.

## 19. Suggested Data Model (SQLAlchemy)
Core tables:
1. `users`
2. `runs`
3. `run_events`
4. `run_context`
5. `run_artifacts`
6. `validation_checks`
7. `slot_leases`
8. `approvals`
9. `releases`
10. `audit_log`

Critical columns:
1. `runs`: `id`, `title`, `prompt`, `status`, `route`, `slot_id`, `branch_name`, `worktree_path`, `commit_sha`, `parent_run_id`, `created_by`, `created_at`, `updated_at`.
2. `slot_leases`: `slot_id`, `run_id`, `lease_state`, `leased_at`, `expires_at`, `heartbeat_at`.
3. `validation_checks`: `run_id`, `check_name`, `status`, `started_at`, `ended_at`, `artifact_uri`.
4. `audit_log`: immutable entries with actor, action, payload hash, timestamp.

## 20. Configuration
Use environment-driven config for:
1. Repo paths.
2. Slot count and slot mapping.
3. Lease TTL and heartbeat interval.
4. Queue concurrency limits.
5. Policy guardrail toggles.
6. Preview DB reset strategy.
7. Deploy command and health check endpoint.

## 21. Failure Handling
1. Hard timeout for each run phase.
2. Codex process kill on timeout.
3. Automatic transition to `failed` with reason code.
4. Slot release on terminal states.
5. Resume support from safe checkpoints where possible.

## 22. Performance and Limits
1. Max active preview runs: 3.
2. Queue backpressure when slot pool exhausted.
3. Global run timeout default 30-60 minutes.
4. Log/artifact retention windows configurable.

## 23. MVP Delivery Phases
### Phase 1
1. `/codex` page.
2. Run creation and queue.
3. Worker integration with Codex CLI.
4. Basic run inbox with state updates.

### Phase 2
1. Slot manager with 3 preview worktrees.
2. Preview URLs and deterministic DB resets.
3. Validation pipeline and artifacts.

### Phase 3
1. Change review UI.
2. Approve/reject flow.
3. Merge gate and production deploy.

### Phase 4
1. Global shortcut overlay on all pages.
2. Per-page run context badges.
3. Rollback UX and audit improvements.

## 24. Acceptance Criteria (MVP)
1. User can submit a request from `/codex` and from page overlay.
2. System allocates a free preview slot or queues request.
3. Codex edits only slot-bound worktree branch.
4. Required checks run and results are visible.
5. User can test preview live and approve/reject.
6. Approved run merges to `main` and deploys automatically.
7. System records full audit trail.
8. Production remains on stable `main` during all preview activity.

## 25. Open Decisions
1. Queue implementation: RQ vs Celery.
2. Preview deployment mode: separate containers vs separate process ports.
3. Exact smoke test framework for Vue app.
4. Rollback strategy for non-reversible DB migrations.
5. Authentication provider and RBAC roles.

## 26. Important Notes and Extra Suggestions
1. Start with one repository and one app runtime model before introducing plugin-like project generation.
2. Keep agent prompts structured and templated for repeatability.
3. Record every command executed by worker and expose to admins.
4. Add feature flags to disable autonomous merge instantly.
5. Require explicit human approval for any migration in MVP, even if checks pass.
6. Implement "safe mode" fallback where agent can suggest diffs without applying them.
7. Add nightly health task to verify slot cleanup, preview DB reset integrity, and stale leases.
8. Add cost and token usage tracking per run for capacity planning.

## 27. Suggested Next Step
Convert this specification into implementation tickets by phase and map them into Linear as Epics/Projects with concrete acceptance tests.
