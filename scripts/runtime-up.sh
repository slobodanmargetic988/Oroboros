#!/usr/bin/env bash
set -euo pipefail

sudo systemctl enable --now postgresql redis
sudo systemctl enable --now ouroboros-api
sudo systemctl enable --now ouroboros-worker
sudo systemctl enable --now ouroboros-web@main
./scripts/preview-slots-provision.sh
sudo systemctl enable --now ouroboros-caddy
