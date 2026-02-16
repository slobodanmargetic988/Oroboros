# BACKEND_TEST_REPORT
Generated: 2026-02-16 12:20 UTC
Tester Agent: backend-tester
Task: MYO-20
Project: Ouroboros (team Myownmint)
Branch: codex/myo-20-preview-runtime-slots
Commit: a08cccb
Harness Mode: developer_handoff
Extra Focus: integration

## Verdict
- Result: PASS
- Review readiness: READY
- Linear transition applied: `Agent work DONE` -> `Agent testing` -> `Agent test DONE`

## Scope Under Test
- Preview slot provisioning automation
- Slot-to-port mapping documentation + env consistency
- Per-slot health exposure
- Dedicated URL routing configuration
- Host-only runtime policy compliance

## Evidence
1. Provisioning automation
   - `scripts/preview-slots-provision.sh --dry-run` passed and emitted expected systemd/env install operations for preview1/2/3.
2. Slot health exposure
   - Direct health checks passed:
     - `3101/health` -> `ok`
     - `3102/health` -> `ok`
     - `3103/health` -> `ok`
3. URL routing definitions
   - `infra/caddy/Caddyfile` includes:
     - `preview1.example.com -> 127.0.0.1:3101`
     - `preview2.example.com -> 127.0.0.1:3102`
     - `preview3.example.com -> 127.0.0.1:3103`
4. Mapping consistency
   - `infra/systemd/env/web-preview1.env`, `web-preview2.env`, `web-preview3.env` match documented slot IDs, URLs, roots, and ports.
5. Host-only policy
   - No Docker/Compose/K8s/container assumptions in tested MYO-20 runtime path.

## Environment Notes
- `caddy` binary is not installed in this tester environment, so routed host-header health execution could not be run live.
- Route config consistency + direct slot health checks are validated and treated as sufficient for this pass.

## Defects
- None blocking.

## Recommendation
- Handoff: reviewer (`Agent review`)
- Task is review-ready.
