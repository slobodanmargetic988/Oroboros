# Worker Security Guardrails (MYO-38)

Host-only hardening for worker execution without container isolation.

## 1) Dedicated worker OS identity
- systemd unit `infra/systemd/ouroboros-worker.service` runs as:
  - `User=oroboros-worker`
  - `Group=oroboros-worker`
- `scripts/systemd-install-runtime.sh` creates this system user/group idempotently and prepares writable directories with restricted ownership.

## 2) Command allowlist enforcement
Worker subprocess execution is blocked unless command executable matches allowlist patterns.

Configuration:
- `WORKER_ALLOWED_COMMANDS`
  - Default: `codex,python,python*,git,npm,node`

Behavior:
- Disallowed commands are refused before process spawn.
- Shell wrappers (`bash`, `sh`, `zsh`, `dash`, `ksh`, `fish`) are always denied to prevent allowlist bypass via `-c` payloads.
- Return code is `126` with a policy message in artifact output.

## 3) Worktree path allowlist enforcement
Worker subprocesses can only execute with `cwd` under allowed path roots.

Configuration:
- `WORKER_ALLOWED_PATHS`
  - Host default: `/srv/oroboros/worktrees`

Behavior:
- Out-of-bounds execution paths are refused before process spawn.
- Return code is `126` with a policy message in artifact output.

## 4) Secret isolation (prod vs preview)
Preview command subprocesses run with a sanitized environment:
- Only allowlisted parent env vars are inherited (`WORKER_SUBPROCESS_ENV_ALLOWLIST`).
- Explicit sensitive keys are removed (`WORKER_SUBPROCESS_ENV_BLOCKLIST`).
- Preview-scoped values are loaded from a separate file (`WORKER_PREVIEW_ENV_FILE`, default `/etc/oroboros/worker-preview.env`).

This prevents worker subprocesses from inheriting production control-plane secrets by default.

## 5) Host service hardening flags
Worker unit uses host-level hardening directives:
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=full`
- `ProtectHome=true`
- `ProtectKernelTunables=true`
- `ProtectKernelModules=true`
- `ProtectControlGroups=true`
- `RestrictSUIDSGID=true`
- `LockPersonality=true`
- `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`
- `ReadWritePaths=/srv/oroboros/worktrees /srv/oroboros/artifacts /tmp`
- `UMask=0077`
