#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

cd "${BACKEND_DIR}"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing backend virtualenv. Run ./scripts/db-bootstrap.sh first."
  exit 1
fi

".venv/bin/python" -m app.db.seed
