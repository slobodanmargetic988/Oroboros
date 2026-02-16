# Preview Smoke/E2E Harness (MYO-32)

Host-only, headless smoke harness for preview environments.

## Purpose
- Run smoke checks against one or more preview URLs.
- Include changed-route targeting in addition to core routes.
- Emit machine-consumable JSON for validation pipelines.
- Optionally persist check records to control-plane DB.

No Docker/Compose/Kubernetes assumptions are used.

## Command
```bash
./scripts/preview-smoke-e2e.sh \
  --preview-url https://preview1.example.com \
  --preview-url https://preview2.example.com \
  --changed-route /codex/runs/123 \
  --output /tmp/preview-smoke-report.json
```

## Changed-route targeting
- Use `--changed-route` repeatedly for route-specific checks.
- Core routes default to:
  - `/health`
  - `/`
- You can override/add core routes via repeated `--core-route`.

## Host-routed local mode
For host header routing through local Caddy:
```bash
./scripts/preview-smoke-e2e.sh \
  --preview-url preview1.example.com \
  --proxy-origin http://127.0.0.1:8088 \
  --changed-route /codex
```

This sends requests to the proxy origin while preserving host routing with `Host` header.

## Validation-pipeline consumable output
The CLI writes a JSON report (`--output`) and prints a compact JSON payload to stdout:
- `status` (`passed` or `failed`)
- `artifact_uri` (file URI to report)
- `failed_checks`
- `total_checks`

Exit codes:
- `0`: all checks passed
- `2`: one or more checks failed
- non-zero: invocation/runtime error

## Optional DB persistence
Persist to `validation_checks`, `run_artifacts`, and `run_events`:
```bash
./scripts/preview-smoke-e2e.sh \
  --preview-url https://preview1.example.com \
  --run-id <run_id> \
  --persist-validation
```

Stored records:
- `validation_checks.check_name = preview_smoke_e2e`
- `run_artifacts.artifact_type = preview_smoke_e2e_report`
- run event: `preview_smoke_e2e_completed`
