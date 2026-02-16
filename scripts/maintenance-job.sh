#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <stale-lease-cleanup|preview-reset-integrity|daily-health-summary> [args...]" >&2
  exit 1
fi

JOB="$1"
shift

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
PYTHON_CMD=""
DEPLOY_ROOT="${DEPLOY_ROOT:-/srv/oroboros}"
DEPLOY_CURRENT_LINK="${DEPLOY_CURRENT_LINK:-${DEPLOY_ROOT}/current}"

if [[ -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
  PYTHON_CMD="${BACKEND_DIR}/.venv/bin/python"
elif [[ -n "${DEPLOY_CURRENT_LINK:-}" && -x "${DEPLOY_CURRENT_LINK}/backend/.venv/bin/python" ]]; then
  PYTHON_CMD="${DEPLOY_CURRENT_LINK}/backend/.venv/bin/python"
elif [[ -x "${DEPLOY_ROOT}/current/backend/.venv/bin/python" ]]; then
  PYTHON_CMD="${DEPLOY_ROOT}/current/backend/.venv/bin/python"
else
  echo "Missing backend virtualenv python for maintenance jobs." >&2
  echo "Run ./scripts/db-bootstrap.sh for local usage or set DEPLOY_ROOT/DEPLOY_CURRENT_LINK." >&2
  exit 1
fi

cd "${BACKEND_DIR}"
exec "${PYTHON_CMD}" -m app.services.maintenance_jobs_cli "${JOB}" "$@"
