#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/preview-backend-runtime.sh <command> --slot <preview-1|preview-2|preview-3> [options]

Commands:
  start      Start slot backend runtime and wait for health.
  stop       Stop slot backend runtime.
  restart    Restart slot backend runtime with fail-safe health gate.
  status     Show slot backend runtime status.
  health     Probe slot backend /health endpoint.

Options:
  --slot <slot_id>             Required for all commands.
  --worktree-path <path>       Override slot worktree path (default: $WORKTREE_ROOT/<slot_id>).
  --health-timeout-seconds <n> Health wait timeout for start/restart (default: 30).

Environment:
  WORKTREE_ROOT                         default: /srv/oroboros/worktrees
  PREVIEW_BACKEND_PID_DIR               default: /tmp/oroboros-preview-backend
  PREVIEW_BACKEND_LOG_DIR               default: /tmp/oroboros-preview-backend
  PREVIEW_BACKEND_DATABASE_URL_TEMPLATE optional:
    e.g. postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{db_name}
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

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    emit_json ok=false error=missing_command command="${cmd}"
    exit 1
  fi
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

slot_port_for() {
  local slot_num="$1"
  echo "$((8100 + slot_num))"
}

slot_db_for() {
  local slot_num="$1"
  echo "app_preview_${slot_num}"
}

resolve_database_url() {
  local slot_num="$1"
  local db_name="$2"
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
    emit_json ok=false error=slot_database_mismatch expected_db="${expected_db}" slot_id="${CANONICAL_SLOT}"
    exit 1
  fi
  if [[ "${db_url}" == *"/builder_control"* ]]; then
    emit_json ok=false error=unsafe_database_target forbidden_db=builder_control slot_id="${CANONICAL_SLOT}"
    exit 1
  fi
  if [[ "${db_url}" != *"/app_preview_"* ]]; then
    emit_json ok=false error=non_preview_database_target expected_prefix=app_preview_ slot_id="${CANONICAL_SLOT}"
    exit 1
  fi
}

is_pid_running() {
  local pid="$1"
  if [[ -z "${pid}" ]]; then
    return 1
  fi
  kill -0 "${pid}" >/dev/null 2>&1
}

wait_for_health() {
  local url="$1"
  local timeout_seconds="$2"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

COMMAND="${1:-}"
if [[ -z "${COMMAND}" || "${COMMAND}" == "-h" || "${COMMAND}" == "--help" ]]; then
  usage
  exit 0
fi
shift

SLOT_ID=""
WORKTREE_PATH=""
HEALTH_TIMEOUT_SECONDS="30"

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
    --health-timeout-seconds)
      HEALTH_TIMEOUT_SECONDS="$2"
      shift 2
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

if ! [[ "${HEALTH_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]]; then
  emit_json ok=false error=invalid_health_timeout health_timeout_seconds="${HEALTH_TIMEOUT_SECONDS}"
  exit 1
fi

require_cmd python3
require_cmd curl

CANONICAL_SLOT="$(normalize_slot "${SLOT_ID}")"
SLOT_NUM="$(slot_num_for "${CANONICAL_SLOT}")"
SLOT_BACKEND_PORT="$(slot_port_for "${SLOT_NUM}")"
SLOT_DB_NAME="$(slot_db_for "${SLOT_NUM}")"
WORKTREE_ROOT="${WORKTREE_ROOT:-/srv/oroboros/worktrees}"

if [[ -z "${WORKTREE_PATH}" ]]; then
  WORKTREE_PATH="${WORKTREE_ROOT}/${CANONICAL_SLOT}"
fi

BACKEND_DIR="${WORKTREE_PATH}/backend"
RUNTIME_DIR="${PREVIEW_BACKEND_PID_DIR:-/tmp/oroboros-preview-backend}"
LOG_DIR="${PREVIEW_BACKEND_LOG_DIR:-/tmp/oroboros-preview-backend}"
PID_FILE="${RUNTIME_DIR}/${CANONICAL_SLOT}.pid"
LOG_FILE="${LOG_DIR}/${CANONICAL_SLOT}.log"
HEALTH_URL="http://127.0.0.1:${SLOT_BACKEND_PORT}/health"

mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}"

read_pid() {
  if [[ -f "${PID_FILE}" ]]; then
    tr -d '[:space:]' <"${PID_FILE}"
  fi
}

start_slot() {
  local existing_pid
  existing_pid="$(read_pid || true)"
  if [[ -n "${existing_pid}" ]] && is_pid_running "${existing_pid}"; then
    emit_json ok=false command=start slot_id="${CANONICAL_SLOT}" reason=already_running pid="${existing_pid}" port="${SLOT_BACKEND_PORT}"
    exit 1
  fi

  if [[ ! -d "${BACKEND_DIR}" ]]; then
    emit_json ok=false command=start slot_id="${CANONICAL_SLOT}" reason=backend_dir_missing backend_dir="${BACKEND_DIR}"
    exit 1
  fi

  local uvicorn_bin="${BACKEND_DIR}/.venv/bin/uvicorn"
  local run_cmd=()
  if [[ -x "${uvicorn_bin}" ]]; then
    run_cmd=("${uvicorn_bin}" "app.main:app" "--host" "127.0.0.1" "--port" "${SLOT_BACKEND_PORT}")
  else
    run_cmd=("python3" "-m" "uvicorn" "app.main:app" "--host" "127.0.0.1" "--port" "${SLOT_BACKEND_PORT}")
  fi

  local database_url="${DATABASE_URL:-}"
  if [[ -z "${database_url}" ]]; then
    database_url="$(resolve_database_url "${SLOT_NUM}" "${SLOT_DB_NAME}")"
  fi
  validate_database_url "${database_url}" "${SLOT_DB_NAME}"

  (
    cd "${BACKEND_DIR}"
    env \
      SLOT_ID="${CANONICAL_SLOT}" \
      SLOT_NUM="${SLOT_NUM}" \
      SLOT_BACKEND_PORT="${SLOT_BACKEND_PORT}" \
      SLOT_DB_NAME="${SLOT_DB_NAME}" \
      SLOT_WORKTREE_PATH="${WORKTREE_PATH}" \
      DATABASE_URL="${database_url}" \
      "${run_cmd[@]}" >>"${LOG_FILE}" 2>&1 &
    echo $! >"${PID_FILE}"
  )

  local started_pid
  started_pid="$(read_pid || true)"
  if [[ -z "${started_pid}" ]] || ! is_pid_running "${started_pid}"; then
    rm -f "${PID_FILE}"
    emit_json ok=false command=start slot_id="${CANONICAL_SLOT}" reason=process_start_failed port="${SLOT_BACKEND_PORT}" log_file="${LOG_FILE}"
    exit 1
  fi

  if ! wait_for_health "${HEALTH_URL}" "${HEALTH_TIMEOUT_SECONDS}"; then
    kill "${started_pid}" >/dev/null 2>&1 || true
    rm -f "${PID_FILE}"
    emit_json ok=false command=start slot_id="${CANONICAL_SLOT}" reason=healthcheck_timeout pid="${started_pid}" health_url="${HEALTH_URL}" log_file="${LOG_FILE}"
    exit 1
  fi

  emit_json ok=true command=start slot_id="${CANONICAL_SLOT}" pid="${started_pid}" port="${SLOT_BACKEND_PORT}" health_url="${HEALTH_URL}" log_file="${LOG_FILE}" worktree_path="${WORKTREE_PATH}" db_name="${SLOT_DB_NAME}"
}

stop_slot() {
  local existing_pid
  existing_pid="$(read_pid || true)"
  if [[ -z "${existing_pid}" ]] || ! is_pid_running "${existing_pid}"; then
    rm -f "${PID_FILE}"
    emit_json ok=true command=stop slot_id="${CANONICAL_SLOT}" stopped=false reason=not_running
    return
  fi

  kill "${existing_pid}" >/dev/null 2>&1 || true
  sleep 1
  if is_pid_running "${existing_pid}"; then
    kill -9 "${existing_pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${PID_FILE}"
  emit_json ok=true command=stop slot_id="${CANONICAL_SLOT}" stopped=true pid="${existing_pid}"
}

status_slot() {
  local existing_pid
  existing_pid="$(read_pid || true)"
  if [[ -n "${existing_pid}" ]] && is_pid_running "${existing_pid}"; then
    emit_json ok=true command=status slot_id="${CANONICAL_SLOT}" running=true pid="${existing_pid}" port="${SLOT_BACKEND_PORT}" health_url="${HEALTH_URL}" worktree_path="${WORKTREE_PATH}" log_file="${LOG_FILE}"
    return
  fi

  rm -f "${PID_FILE}"
  emit_json ok=true command=status slot_id="${CANONICAL_SLOT}" running=false pid= port="${SLOT_BACKEND_PORT}" health_url="${HEALTH_URL}" worktree_path="${WORKTREE_PATH}" log_file="${LOG_FILE}"
}

health_slot() {
  if curl -fsS --max-time 3 "${HEALTH_URL}" >/dev/null 2>&1; then
    emit_json ok=true command=health slot_id="${CANONICAL_SLOT}" healthy=true health_url="${HEALTH_URL}"
    return
  fi
  emit_json ok=false command=health slot_id="${CANONICAL_SLOT}" healthy=false health_url="${HEALTH_URL}"
  exit 1
}

restart_slot() {
  stop_slot >/dev/null
  start_slot
}

case "${COMMAND}" in
  start) start_slot ;;
  stop) stop_slot ;;
  restart) restart_slot ;;
  status) status_slot ;;
  health) health_slot ;;
  *)
    emit_json ok=false error=unknown_command command="${COMMAND}"
    exit 1
    ;;
esac
