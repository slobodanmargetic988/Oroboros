#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

cd "${BACKEND_DIR}"

if [[ ! -x ".venv/bin/alembic" ]]; then
  echo "Missing backend virtualenv with Alembic. Run ./scripts/db-bootstrap.sh first."
  exit 1
fi

".venv/bin/alembic" -c alembic.ini upgrade head
