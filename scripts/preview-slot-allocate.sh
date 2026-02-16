#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

if [[ ! -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
  echo "Missing backend virtualenv. Run ./scripts/db-bootstrap.sh first." >&2
  exit 1
fi

cd "${BACKEND_DIR}"
exec .venv/bin/python -m app.services.slot_allocation_cli "$@"
