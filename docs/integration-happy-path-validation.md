# Integration Happy Path Validation (MYO-42)

Host-only end-to-end validation for:
- Prompt submission
- Worker execution
- Preview smoke checks
- Approval/merge flow
- Post-deploy runtime health

No Docker/Compose/Kubernetes/container path is used.

## Command
```bash
./scripts/integration-happy-path.sh
```

## What it validates
1. API health precheck (`GET /health`).
2. Create run (`POST /api/runs`).
3. Wait for run to reach pre-approval state (`preview_ready` or later).
4. Run preview smoke harness with persistence for the run:
   - `scripts/preview-smoke-e2e.sh --persist-validation --run-id <run_id>`
5. Approve run (`POST /api/runs/{run_id}/approve`) if not already merged.
6. Wait for `merged` state.
7. Execute post-deploy health check:
   - `./scripts/runtime-health-check.sh`
8. Fetch run timeline events (`GET /api/runs/{run_id}/events`).
9. Persist integration evidence to control plane:
   - `run_artifacts.artifact_type=integration_happy_path_report`
   - run event `integration_happy_path_completed`

## Output
- JSON report file under `/tmp` by default.
- Stdout summary payload:
  - `status`
  - `run_id`
  - `artifact_uri`
  - `error` (if failed)

## Useful flags
- `--api-base-url http://127.0.0.1:8000`
- `--proxy-origin http://127.0.0.1:8088`
- `--slot-host-map preview-1=preview1.example.com,preview-2=preview2.example.com,preview-3=preview3.example.com`
- `--changed-route /codex`
- `--output ./artifacts/integration/myo-42-report.json`
- `--skip-health-check` (debug only)
- `--no-persist-evidence` (debug only)
