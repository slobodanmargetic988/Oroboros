#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SLOT_ID=""
SEED_VERSION="v1"
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
    --seed-version)
      SEED_VERSION="$2"
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

SEED_FILE="${ROOT_DIR}/infra/db/preview/seeds/${SEED_VERSION}.sql"
if [[ ! -f "${SEED_FILE}" ]]; then
  echo "Seed file not found: ${SEED_FILE}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[dry-run] Seed DB ${DB_NAME} for slot ${SLOT_ID} with ${SEED_FILE}"
  exit 0
fi

psql "host=${PGHOST} port=${PGPORT} user=${PGUSER} dbname=${DB_NAME}" -v ON_ERROR_STOP=1 -f "${SEED_FILE}" >/dev/null
echo "Seed applied for ${DB_NAME} (version ${SEED_VERSION})"
