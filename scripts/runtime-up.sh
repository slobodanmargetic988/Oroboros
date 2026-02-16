#!/usr/bin/env bash
set -euo pipefail

sudo systemctl enable --now postgresql redis
sudo systemctl enable --now ouroboros-api
sudo systemctl enable --now ouroboros-worker
sudo systemctl enable --now ouroboros-web@main
sudo systemctl enable --now ouroboros-web@preview1
sudo systemctl enable --now ouroboros-web@preview2
sudo systemctl enable --now ouroboros-web@preview3
sudo systemctl enable --now ouroboros-caddy
