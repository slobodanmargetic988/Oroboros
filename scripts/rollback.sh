#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/rollback.sh <release_id>

Environment overrides:
  DEPLOY_ROOT                    Deployment root (default: /srv/oroboros)
  DEPLOY_RELEASES_DIR            Releases directory (default: $DEPLOY_ROOT/releases)
  DEPLOY_CURRENT_LINK            Current symlink path (default: $DEPLOY_ROOT/current)
  ROLLBACK_SKIP_SERVICE_RESTART  Set to 1 to skip systemd restart
  ROLLBACK_SKIP_HEALTHCHECK      Set to 1 to skip health gate
  ROLLBACK_HEALTHCHECK_CMD       Override health check command
  ROLLBACK_REGISTRY_CMD          Override release registry command
  ROLLBACK_SERVICES              Space-separated systemd units to restart

Host-only rollback only. No Docker/Compose/Kubernetes usage.
EOF
}

log() {
  echo "[rollback] $*"
}

die() {
  echo "[rollback] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || die "Required command not found: ${cmd}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

TARGET_RELEASE_ID="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/srv/oroboros}"
DEPLOY_RELEASES_DIR="${DEPLOY_RELEASES_DIR:-${DEPLOY_ROOT}/releases}"
DEPLOY_CURRENT_LINK="${DEPLOY_CURRENT_LINK:-${DEPLOY_ROOT}/current}"
TARGET_RELEASE_DIR="${DEPLOY_RELEASES_DIR}/${TARGET_RELEASE_ID}"
ROLLBACK_REGISTRY_CMD="${ROLLBACK_REGISTRY_CMD:-${SCRIPT_DIR}/release-registry.sh}"

SERVICES_DEFAULT="ouroboros-api ouroboros-worker ouroboros-web@main ouroboros-web@preview1 ouroboros-web@preview2 ouroboros-web@preview3 ouroboros-caddy"
ROLLBACK_SERVICES="${ROLLBACK_SERVICES:-${SERVICES_DEFAULT}}"
ROLLBACK_HEALTHCHECK_CMD="${ROLLBACK_HEALTHCHECK_CMD:-${DEPLOY_CURRENT_LINK}/scripts/runtime-health-check.sh}"

PREVIOUS_TARGET=""
PREVIOUS_RELEASE_ID=""
PREVIOUS_RELEASE_COMMIT=""
TARGET_RELEASE_COMMIT="${TARGET_RELEASE_ID}"

read_meta_value() {
  local file="$1"
  local key="$2"
  [[ -f "${file}" ]] || return 0
  sed -n "s/^${key}=//p" "${file}" | head -n 1
}

registry_upsert() {
  local release_id="$1"
  local commit_sha="$2"
  local status="$3"
  local marker="${4:-}"

  if [[ "${ROLLBACK_SKIP_REGISTRY_UPDATE:-0}" == "1" ]]; then
    log "Skipping release registry update (ROLLBACK_SKIP_REGISTRY_UPDATE=1)"
    return
  fi

  if [[ ! -x "${ROLLBACK_REGISTRY_CMD}" ]]; then
    log "Release registry command not executable; skipping update: ${ROLLBACK_REGISTRY_CMD}"
    return
  fi

  local cmd=(
    "${ROLLBACK_REGISTRY_CMD}"
    upsert
    --release-id "${release_id}"
    --commit-sha "${commit_sha}"
    --status "${status}"
  )
  if [[ -n "${marker}" ]]; then
    cmd+=(--migration-marker "${marker}")
  fi

  if ! "${cmd[@]}" >/dev/null; then
    log "Release registry update failed (non-fatal): release=${release_id} status=${status}"
  fi
}

switch_current_link() {
  local target="$1"
  local next_link="${DEPLOY_CURRENT_LINK}.next.$$"
  ln -s "${target}" "${next_link}"
  python3 - "${next_link}" "${DEPLOY_CURRENT_LINK}" <<'PY'
import os
import sys

src = sys.argv[1]
dst = sys.argv[2]
os.replace(src, dst)
PY
}

restart_services() {
  if [[ "${ROLLBACK_SKIP_SERVICE_RESTART:-0}" == "1" ]]; then
    log "Skipping service restart (ROLLBACK_SKIP_SERVICE_RESTART=1)"
    return
  fi

  require_cmd sudo
  require_cmd systemctl
  log "Restarting services: ${ROLLBACK_SERVICES}"
  # shellcheck disable=SC2086
  sudo systemctl restart ${ROLLBACK_SERVICES}
}

run_health_gate() {
  if [[ "${ROLLBACK_SKIP_HEALTHCHECK:-0}" == "1" ]]; then
    log "Skipping health gate (ROLLBACK_SKIP_HEALTHCHECK=1)"
    return 0
  fi

  log "Running post-rollback health gate: ${ROLLBACK_HEALTHCHECK_CMD}"
  if ! bash -lc "${ROLLBACK_HEALTHCHECK_CMD}"; then
    log "Rollback health gate failed"
    return 1
  fi

  return 0
}

if [[ ! -d "${TARGET_RELEASE_DIR}" ]]; then
  registry_upsert "${TARGET_RELEASE_ID}" "${TARGET_RELEASE_ID}" "rollback_target_missing"
  die "Target release directory does not exist: ${TARGET_RELEASE_DIR}"
fi

TARGET_RELEASE_COMMIT="$(read_meta_value "${TARGET_RELEASE_DIR}/.deploy-meta" "commit_sha")"
TARGET_RELEASE_COMMIT="${TARGET_RELEASE_COMMIT:-${TARGET_RELEASE_ID}}"

if [[ -L "${DEPLOY_CURRENT_LINK}" ]]; then
  PREVIOUS_TARGET="$(readlink -f "${DEPLOY_CURRENT_LINK}" || true)"
fi
if [[ -n "${PREVIOUS_TARGET}" ]]; then
  PREVIOUS_RELEASE_ID="$(basename "${PREVIOUS_TARGET}")"
  PREVIOUS_RELEASE_COMMIT="$(read_meta_value "${PREVIOUS_TARGET}/.deploy-meta" "commit_sha")"
fi

registry_upsert "${TARGET_RELEASE_ID}" "${TARGET_RELEASE_COMMIT}" "rollback_in_progress"

log "Switching current symlink atomically to ${TARGET_RELEASE_DIR}"
switch_current_link "${TARGET_RELEASE_DIR}"

restart_services

if ! run_health_gate; then
  registry_upsert "${TARGET_RELEASE_ID}" "${TARGET_RELEASE_COMMIT}" "rollback_failed"
  if [[ -n "${PREVIOUS_TARGET}" ]]; then
    log "Restoring previous symlink target: ${PREVIOUS_TARGET}"
    switch_current_link "${PREVIOUS_TARGET}"
    restart_services
    if [[ -n "${PREVIOUS_RELEASE_ID}" ]]; then
      registry_upsert "${PREVIOUS_RELEASE_ID}" "${PREVIOUS_RELEASE_COMMIT:-${PREVIOUS_RELEASE_ID}}" "deployed"
    fi
  fi
  die "Rollback failed health gate"
fi

registry_upsert "${TARGET_RELEASE_ID}" "${TARGET_RELEASE_COMMIT}" "rolled_back"
if [[ -n "${PREVIOUS_RELEASE_ID}" && "${PREVIOUS_RELEASE_ID}" != "${TARGET_RELEASE_ID}" ]]; then
  registry_upsert "${PREVIOUS_RELEASE_ID}" "${PREVIOUS_RELEASE_COMMIT:-${PREVIOUS_RELEASE_ID}}" "replaced_by_rollback"
fi

log "Rollback succeeded"
log "Current release: ${TARGET_RELEASE_DIR}"
