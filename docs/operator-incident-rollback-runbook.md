# Operator Incident and Rollback Runbook (Host-Only)

Validated during MYO-43 failure-mode drills on host-deployed services.

## 1) Readiness / Baseline
```bash
./scripts/runtime-health-check.sh
./scripts/preview-slots-health-check.sh
```

## 2) Worker Timeout Recovery (API Contract)
```bash
RUN_ID=$(curl -fsS -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"title":"timeout drill","prompt":"simulate timeout","route":"/codex"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -fsS -X POST "http://127.0.0.1:8000/api/runs/${RUN_ID}/transition" \
  -H 'Content-Type: application/json' \
  -d '{"to_status":"failed","failure_reason_code":"AGENT_TIMEOUT"}'

curl -fsS -X POST "http://127.0.0.1:8000/api/runs/${RUN_ID}/resume" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

## 3) Slot Exhaustion and Recovery
```bash
# Create 4 runs, acquire slot for each, 4th should return queue_reason WAITING_FOR_SLOT.
curl -fsS -X POST http://127.0.0.1:8000/api/slots/acquire \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"<run_id>"}'

# Recover by releasing occupied slots.
curl -fsS -X POST http://127.0.0.1:8000/api/slots/<slot_id>/release \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"<run_id>"}'
```

## 4) Failed Deploy Drill (Isolated Host Deploy Root)
```bash
DEPLOY_ROOT=/tmp/oroboros-drill
COMMIT_OLD=<known_commit>
COMMIT_NEW=<known_commit>

mkdir -p "$DEPLOY_ROOT/releases/$COMMIT_OLD" "$DEPLOY_ROOT/releases/$COMMIT_NEW"
printf 'commit_sha=%s\n' "$COMMIT_OLD" > "$DEPLOY_ROOT/releases/$COMMIT_OLD/.deploy-meta"
printf 'commit_sha=%s\n' "$COMMIT_NEW" > "$DEPLOY_ROOT/releases/$COMMIT_NEW/.deploy-meta"

DEPLOY_ROOT="$DEPLOY_ROOT" DEPLOY_SKIP_SERVICE_RESTART=1 DEPLOY_SKIP_HEALTHCHECK=1 DEPLOY_SKIP_REGISTRY_UPDATE=1 \
  ./scripts/deploy.sh "$COMMIT_OLD"

# Simulate failed deploy and auto-recovery to previous release.
DEPLOY_ROOT="$DEPLOY_ROOT" DEPLOY_SKIP_SERVICE_RESTART=1 DEPLOY_SKIP_REGISTRY_UPDATE=1 DEPLOY_HEALTHCHECK_CMD='false' \
  ./scripts/deploy.sh "$COMMIT_NEW"
```

## 5) Rollback Command Validation
```bash
DEPLOY_ROOT=/tmp/oroboros-drill

# Expected failure (missing release target)
DEPLOY_ROOT="$DEPLOY_ROOT" ROLLBACK_SKIP_SERVICE_RESTART=1 ROLLBACK_SKIP_REGISTRY_UPDATE=1 ROLLBACK_HEALTHCHECK_CMD='true' \
  ./scripts/rollback.sh missing-release-id

# Valid rollback
DEPLOY_ROOT="$DEPLOY_ROOT" ROLLBACK_SKIP_SERVICE_RESTART=1 ROLLBACK_SKIP_REGISTRY_UPDATE=1 ROLLBACK_HEALTHCHECK_CMD='true' \
  ./scripts/rollback.sh <release_id>
```

## 6) Failed Preview Reset/Migration Drill and Recovery
```bash
# Ensure preview DBs exist in local host postgres.
createdb -h 127.0.0.1 -U postgres app_preview_1
createdb -h 127.0.0.1 -U postgres app_preview_2
createdb -h 127.0.0.1 -U postgres app_preview_3

# Expected failure: nonexistent snapshot version.
./scripts/preview-slot-allocate.sh --run-id <run_id> --strategy snapshot --snapshot-version does-not-exist

# Recovery path with seed.
./scripts/preview-slot-allocate.sh --run-id <run_id> --strategy seed --seed-version v1
./scripts/preview-db-reset-and-seed.sh --slot <slot_id> --run-id <run_id> --strategy seed --seed-version v1
```

## 7) Post-Incident Verification
```bash
./scripts/runtime-health-check.sh
curl -fsS http://127.0.0.1:8000/api/slots | python3 -m json.tool
```

## Notes
- Host-only operations only. No Docker/Compose/Kubernetes procedures in this runbook.
- If `scripts/preview-smoke-e2e.sh` fails in your checkout, use direct fallback:
```bash
cd backend
.venv/bin/python -m app.services.preview_smoke_harness_cli \
  --preview-url preview1.example.com \
  --proxy-origin http://127.0.0.1:8088 \
  --changed-route /health
```
