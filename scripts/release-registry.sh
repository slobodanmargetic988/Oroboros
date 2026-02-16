#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
PYTHON_CMD=""

if [[ -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
  PYTHON_CMD="${BACKEND_DIR}/.venv/bin/python"
elif [[ -n "${DEPLOY_CURRENT_LINK:-}" && -x "${DEPLOY_CURRENT_LINK}/backend/.venv/bin/python" ]]; then
  PYTHON_CMD="${DEPLOY_CURRENT_LINK}/backend/.venv/bin/python"
elif [[ -x "/srv/oroboros/current/backend/.venv/bin/python" ]]; then
  PYTHON_CMD="/srv/oroboros/current/backend/.venv/bin/python"
else
  echo "Missing backend virtualenv python for release registry operations." >&2
  echo "Run ./scripts/db-bootstrap.sh for local usage or set DEPLOY_CURRENT_LINK." >&2
  exit 1
fi

cd "${BACKEND_DIR}"
exec "${PYTHON_CMD}" -m app.services.release_registry_cli "$@"
