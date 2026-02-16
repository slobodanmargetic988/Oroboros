#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SLOT_ID=""
RUN_ID=""
STRATEGY="seed"
SEED_VERSION="v1"
SNAPSHOT_VERSION=""
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slot)
      SLOT_ID="$2"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
      shift 2
      ;;
    --strategy)
      STRATEGY="$2"
      shift 2
      ;;
    --seed-version)
      SEED_VERSION="$2"
      shift 2
      ;;
    --snapshot-version)
      SNAPSHOT_VERSION="$2"
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

if [[ -z "${SLOT_ID}" || -z "${RUN_ID}" ]]; then
  echo "Missing required arguments --slot and/or --run-id" >&2
  exit 1
fi

RESET_ARGS=(--slot "${SLOT_ID}")
SEED_ARGS=(--slot "${SLOT_ID}" --seed-version "${SEED_VERSION}")

if [[ "${DRY_RUN}" == "true" ]]; then
  RESET_ARGS+=(--dry-run)
  SEED_ARGS+=(--dry-run)
fi

"${ROOT_DIR}/scripts/preview-db-reset.sh" "${RESET_ARGS[@]}"

if [[ "${STRATEGY}" == "seed" ]]; then
  "${ROOT_DIR}/scripts/preview-db-seed.sh" "${SEED_ARGS[@]}"
elif [[ "${STRATEGY}" == "snapshot" ]]; then
  if [[ -z "${SNAPSHOT_VERSION}" ]]; then
    echo "snapshot strategy requires --snapshot-version" >&2
    exit 1
  fi

  SNAPSHOT_FILE="${ROOT_DIR}/infra/db/preview/snapshots/${SNAPSHOT_VERSION}.sql"
  if [[ ! -f "${SNAPSHOT_FILE}" ]]; then
    echo "Snapshot file not found: ${SNAPSHOT_FILE}" >&2
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

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] Apply snapshot ${SNAPSHOT_VERSION} to ${DB_NAME}"
  else
    psql "host=${PGHOST:-127.0.0.1} port=${PGPORT:-5432} user=${PGUSER:-postgres} dbname=${DB_NAME}" -v ON_ERROR_STOP=1 -f "${SNAPSHOT_FILE}" >/dev/null
    echo "Snapshot ${SNAPSHOT_VERSION} applied to ${DB_NAME}"
  fi
else
  echo "Unknown strategy '${STRATEGY}'" >&2
  exit 1
fi

echo "preview_db_reset_and_seed complete: run_id=${RUN_ID} slot=${SLOT_ID} strategy=${STRATEGY} seed_version=${SEED_VERSION} snapshot_version=${SNAPSHOT_VERSION:-none}"
