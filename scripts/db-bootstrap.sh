#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

cd "${BACKEND_DIR}"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

".venv/bin/pip" install --upgrade pip
".venv/bin/pip" install -e .

cd "${ROOT_DIR}"
./scripts/db-migrate.sh
./scripts/db-seed.sh
