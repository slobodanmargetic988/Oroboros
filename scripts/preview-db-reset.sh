#!/usr/bin/env bash
set -euo pipefail

SLOT_ID=""
DRY_RUN="false"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slot)
      SLOT_ID="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${SLOT_ID}" ]]; then
  echo "Missing required argument --slot" >&2
  exit 1
fi

case "${SLOT_ID}" in
  preview1|preview-1) DB_NAME="app_preview_1" ;;
  preview2|preview-2) DB_NAME="app_preview_2" ;;
  preview3|preview-3) DB_NAME="app_preview_3" ;;
  *)
    echo "Unknown slot '${SLOT_ID}'" >&2
    exit 1
    ;;
esac

PSQL_CMD=(psql "host=${PGHOST} port=${PGPORT} user=${PGUSER} dbname=${DB_NAME}" -v ON_ERROR_STOP=1)
SQL=$(cat <<'SQL'
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO CURRENT_USER;
SQL
)

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[dry-run] Reset DB ${DB_NAME} for slot ${SLOT_ID}"
  exit 0
fi

printf "%s\n" "${SQL}" | "${PSQL_CMD[@]}" >/dev/null
echo "Reset completed for ${DB_NAME}"
