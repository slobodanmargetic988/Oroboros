# Preview Runtime Slots (MYO-20)

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
