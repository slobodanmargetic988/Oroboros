#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/preview-slot-migrate.sh --slot <preview-1|preview-2|preview-3> [options]

Options:
  --slot <slot_id>                Required.
  --worktree-path <path>          Override slot worktree path (default: $WORKTREE_ROOT/<slot_id>).
  --dry-run                       Resolve and validate target only; do not execute Alembic.

Environment:
  WORKTREE_ROOT                           default: /srv/oroboros/worktrees
  PREVIEW_BACKEND_DATABASE_URL_TEMPLATE   default:
    postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{db_name}
EOF
}

emit_json() {
  python3 - "$@" <<'PY'
import json
import re
import sys

payload = {}
for item in sys.argv[1:]:
    key, _, value = item.partition("=")
    lowered = value.lower()
    if lowered == "true":
        payload[key] = True
    elif lowered == "false":
        payload[key] = False
    elif re.fullmatch(r"-?\d+", value):
        payload[key] = int(value)
    else:
        payload[key] = value
print(json.dumps(payload, sort_keys=True))
PY
}

normalize_slot() {
  case "$1" in
    preview1|preview-1) echo "preview-1" ;;
    preview2|preview-2) echo "preview-2" ;;
    preview3|preview-3) echo "preview-3" ;;
    *)
      emit_json ok=false error=invalid_slot slot_id="$1"
      exit 1
      ;;
  esac
}

slot_num_for() {
  case "$1" in
    preview-1) echo "1" ;;
    preview-2) echo "2" ;;
    preview-3) echo "3" ;;
    *)
      emit_json ok=false error=invalid_slot slot_id="$1"
      exit 1
      ;;
  esac
}

resolve_database_url() {
  local slot_num="$1"
  local db_name="app_preview_${slot_num}"
  local template="${PREVIEW_BACKEND_DATABASE_URL_TEMPLATE:-postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{db_name}}"
  local resolved="${template//\{slot_num\}/${slot_num}}"
  resolved="${resolved//\{slot\}/preview-${slot_num}}"
  resolved="${resolved//\{db_name\}/${db_name}}"
  echo "${resolved}"
}

validate_database_url() {
  local db_url="$1"
  local expected_db="$2"
  if [[ "${db_url}" != *"/${expected_db}"* && "${db_url}" != *"/${expected_db}?"* ]]; then
    emit_json ok=false error=slot_database_mismatch expected_db="${expected_db}"
    exit 1
  fi
  if [[ "${db_url}" == *"/builder_control"* ]]; then
    emit_json ok=false error=unsafe_database_target forbidden_db=builder_control
    exit 1
  fi
  if [[ "${db_url}" != *"/app_preview_"* ]]; then
    emit_json ok=false error=non_preview_database_target expected_prefix=app_preview_
    exit 1
  fi
}

SLOT_ID=""
WORKTREE_PATH=""
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slot)
      SLOT_ID="$2"
      shift 2
      ;;
    --worktree-path)
      WORKTREE_PATH="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      emit_json ok=false error=unknown_argument argument="$1"
      exit 1
      ;;
  esac
done

if [[ -z "${SLOT_ID}" ]]; then
  emit_json ok=false error=missing_slot
  exit 1
fi

CANONICAL_SLOT="$(normalize_slot "${SLOT_ID}")"
SLOT_NUM="$(slot_num_for "${CANONICAL_SLOT}")"
EXPECTED_DB="app_preview_${SLOT_NUM}"
WORKTREE_ROOT="${WORKTREE_ROOT:-/srv/oroboros/worktrees}"
if [[ -z "${WORKTREE_PATH}" ]]; then
  WORKTREE_PATH="${WORKTREE_ROOT}/${CANONICAL_SLOT}"
fi
BACKEND_DIR="${WORKTREE_PATH}/backend"
ALEMBIC_BIN="${BACKEND_DIR}/.venv/bin/alembic"
DATABASE_URL="$(resolve_database_url "${SLOT_NUM}")"

validate_database_url "${DATABASE_URL}" "${EXPECTED_DB}"

if [[ ! -d "${BACKEND_DIR}" ]]; then
  emit_json ok=false error=backend_dir_missing backend_dir="${BACKEND_DIR}" slot_id="${CANONICAL_SLOT}"
  exit 1
fi

if [[ ! -x "${ALEMBIC_BIN}" ]]; then
  emit_json ok=false error=alembic_not_found alembic_bin="${ALEMBIC_BIN}" slot_id="${CANONICAL_SLOT}"
  exit 1
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  emit_json ok=true command=migrate dry_run=true slot_id="${CANONICAL_SLOT}" expected_db="${EXPECTED_DB}" worktree_path="${WORKTREE_PATH}"
  exit 0
fi

if (
  cd "${BACKEND_DIR}" &&
  DATABASE_URL="${DATABASE_URL}" "${ALEMBIC_BIN}" -c alembic.ini upgrade head
); then
  emit_json ok=true command=migrate dry_run=false slot_id="${CANONICAL_SLOT}" expected_db="${EXPECTED_DB}" worktree_path="${WORKTREE_PATH}"
  exit 0
fi

emit_json ok=false command=migrate dry_run=false error=migration_failed slot_id="${CANONICAL_SLOT}" expected_db="${EXPECTED_DB}" worktree_path="${WORKTREE_PATH}"
exit 1
