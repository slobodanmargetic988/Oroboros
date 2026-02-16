#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop ouroboros-caddy || true
sudo systemctl stop ouroboros-web@preview3 || true
sudo systemctl stop ouroboros-web@preview2 || true
sudo systemctl stop ouroboros-web@preview1 || true
sudo systemctl stop ouroboros-web@main || true
sudo systemctl stop ouroboros-worker || true
sudo systemctl stop ouroboros-api || true
sudo systemctl stop ouroboros-maintenance-daily-health-summary.timer || true
sudo systemctl stop ouroboros-maintenance-preview-reset-audit.timer || true
sudo systemctl stop ouroboros-maintenance-stale-leases.timer || true
