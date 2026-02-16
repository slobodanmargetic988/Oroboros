# Preview Runtime Slots (MYO-20 / MYO-23)

This document defines fixed preview slot provisioning for host-level deployment.

## Dedicated Preview URLs
- `preview1.example.com`
- `preview2.example.com`
- `preview3.example.com`

## Slot-to-Port Mapping

| Slot ID | URL | systemd unit | Local port | Static root |
|---|---|---|---:|---|
| preview1 | `preview1.example.com` | `ouroboros-web@preview1` | 3101 | `/srv/oroboros/infra/web-preview-1` |
| preview2 | `preview2.example.com` | `ouroboros-web@preview2` | 3102 | `/srv/oroboros/infra/web-preview-2` |
| preview3 | `preview3.example.com` | `ouroboros-web@preview3` | 3103 | `/srv/oroboros/infra/web-preview-3` |

Routing is handled by Caddy in `infra/caddy/Caddyfile`:
- `preview1.example.com -> 127.0.0.1:3101`
- `preview2.example.com -> 127.0.0.1:3102`
- `preview3.example.com -> 127.0.0.1:3103`

## Provisioning Automation

Install/update slot env files and start the three preview services:
```bash
./scripts/preview-slots-provision.sh
```

Dry-run mode:
```bash
./scripts/preview-slots-provision.sh --dry-run
```

## Health Checks (per slot)

Direct + routed checks:
```bash
./scripts/preview-slots-health-check.sh
```

This is host-only provisioning: no Docker/Compose/Kubernetes/containers.

## Deterministic DB Reset + Seed Strategy (MYO-23)

Each preview slot has a dedicated database:
- `preview1` -> `app_preview_1`
- `preview2` -> `app_preview_2`
- `preview3` -> `app_preview_3`

Reset script per slot DB:
```bash
./scripts/preview-db-reset.sh --slot preview1
```

Deterministic seed apply:
```bash
./scripts/preview-db-seed.sh --slot preview1 --seed-version v1
```

Combined reset + load strategy (seed or snapshot):
```bash
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id <run_id> --strategy seed --seed-version v1
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id <run_id> --strategy snapshot --snapshot-version <snapshot_version>
```

Dry-run examples:
```bash
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id dry-run --strategy seed --seed-version v1 --dry-run
```

## Slot Allocation Flow Integration

Use allocation CLI to lock a slot and execute the deterministic DB reset/seed flow as part of allocation:
```bash
./scripts/preview-slot-allocate.sh --run-id <run_id> --seed-version v1 --strategy seed
```

This flow records per-run reset provenance in control-plane table `preview_db_resets`:
- `run_id`
- `slot_id`
- `db_name`
- `strategy`
- `seed_version`
- `snapshot_version`
- `reset_status`
- timestamps and details payload
