#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! getent group oroboros-worker >/dev/null; then
  sudo groupadd --system oroboros-worker
fi

if ! id -u oroboros-worker >/dev/null 2>&1; then
  sudo useradd --system --gid oroboros-worker --home /srv/oroboros --shell /usr/sbin/nologin oroboros-worker
fi

sudo mkdir -p /srv/oroboros/worktrees
sudo mkdir -p /srv/oroboros/artifacts/runs
sudo mkdir -p /srv/oroboros/artifacts/maintenance
sudo chown -R oroboros-worker:oroboros-worker /srv/oroboros/worktrees /srv/oroboros/artifacts
sudo chmod 750 /srv/oroboros/worktrees
sudo chmod 750 /srv/oroboros/artifacts

sudo mkdir -p /etc/oroboros
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-api.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-worker.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-web@.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-caddy.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-maintenance-stale-leases.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-maintenance-stale-leases.timer" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-maintenance-preview-reset-audit.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-maintenance-preview-reset-audit.timer" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-maintenance-daily-health-summary.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-maintenance-daily-health-summary.timer" /etc/systemd/system/

sudo cp "${ROOT_DIR}/infra/systemd/env/api.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/worker.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/worker-preview.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-main.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-preview1.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-preview2.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-preview3.env" /etc/oroboros/
sudo chown root:oroboros-worker /etc/oroboros/worker.env /etc/oroboros/worker-preview.env
sudo chmod 640 /etc/oroboros/worker.env /etc/oroboros/worker-preview.env

sudo systemctl daemon-reload
