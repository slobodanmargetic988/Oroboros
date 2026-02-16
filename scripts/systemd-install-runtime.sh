#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo mkdir -p /etc/oroboros
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-api.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-worker.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-web@.service" /etc/systemd/system/
sudo cp "${ROOT_DIR}/infra/systemd/ouroboros-caddy.service" /etc/systemd/system/

sudo cp "${ROOT_DIR}/infra/systemd/env/api.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/worker.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-main.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-preview1.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-preview2.env" /etc/oroboros/
sudo cp "${ROOT_DIR}/infra/systemd/env/web-preview3.env" /etc/oroboros/

sudo systemctl daemon-reload
