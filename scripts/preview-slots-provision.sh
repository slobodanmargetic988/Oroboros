#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN="false"

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN="true"
fi

run_cmd() {
  local cmd="$1"
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] ${cmd}"
  else
    eval "${cmd}"
  fi
}

echo "Provisioning fixed preview runtime slots (preview1/preview2/preview3)"

declare -a SLOT_ENVS=(
  "web-preview1.env"
  "web-preview2.env"
  "web-preview3.env"
)

for env_file in "${SLOT_ENVS[@]}"; do
  SRC="${ROOT_DIR}/infra/systemd/env/${env_file}"
  DST="/etc/oroboros/${env_file}"
  run_cmd "sudo install -D -m 0644 '${SRC}' '${DST}'"
done

run_cmd "sudo systemctl daemon-reload"
run_cmd "sudo systemctl enable --now ouroboros-web@preview1"
run_cmd "sudo systemctl enable --now ouroboros-web@preview2"
run_cmd "sudo systemctl enable --now ouroboros-web@preview3"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Preview slot provisioning dry-run complete."
else
  echo "Preview slot provisioning complete."
fi
