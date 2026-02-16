#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh <commit_sha>

Environment overrides:
  REPO_ROOT                  Source git repository root (default: current repo)
  DEPLOY_ROOT                Deployment root (default: /srv/oroboros)
  DEPLOY_RELEASES_DIR        Releases directory (default: $DEPLOY_ROOT/releases)
  DEPLOY_CURRENT_LINK        Current symlink path (default: $DEPLOY_ROOT/current)
  DEPLOY_SKIP_SERVICE_RESTART  Set to 1 to skip systemd restart
  DEPLOY_SKIP_HEALTHCHECK      Set to 1 to skip health gate
  DEPLOY_HEALTHCHECK_CMD       Override health check command
  DEPLOY_REGISTRY_CMD          Override release registry command
  DEPLOY_SERVICES              Space-separated systemd units to restart

Host-only deployment only. No Docker/Compose/Kubernetes usage.
EOF
}

TRACE_ID="${TRACE_ID:-${OUROBOROS_TRACE_ID:-}}"
RUN_ID="${RUN_ID:-${OUROBOROS_RUN_ID:-}}"
SLOT_ID="${SLOT_ID:-${OUROBOROS_SLOT_ID:-}}"

structured_log() {
  local event="$1"
  local message="${2:-}"
  if ! command -v python3 >/dev/null 2>&1; then
    return
  fi
  python3 - "$event" "$message" "${TRACE_ID:-}" "${RUN_ID:-}" "${SLOT_ID:-}" "${COMMIT_SHA:-${OUROBOROS_COMMIT_SHA:-}}" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys

event = sys.argv[1]
message = sys.argv[2]
trace_id = sys.argv[3] or None
run_id = sys.argv[4] or None
slot_id = sys.argv[5] or None
commit_sha = sys.argv[6] or None

payload = {
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "component": "deploy",
    "event": event,
    "message": message,
    "trace_id": trace_id,
    "run_id": run_id,
    "slot_id": slot_id,
    "commit_sha": commit_sha,
}
print(json.dumps(payload, sort_keys=True))
PY
}

log() {
  echo "[deploy] $*"
  structured_log "deploy_log" "$*"
}

die() {
  echo "[deploy] ERROR: $*" >&2
  structured_log "deploy_error" "$*"
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

COMMIT_SHA="$1"
if [[ -n "${COMMIT_SHA:-}" ]]; then
  export COMMIT_SHA
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR_DEFAULT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="${REPO_ROOT:-${ROOT_DIR_DEFAULT}}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/srv/oroboros}"
DEPLOY_RELEASES_DIR="${DEPLOY_RELEASES_DIR:-${DEPLOY_ROOT}/releases}"
DEPLOY_CURRENT_LINK="${DEPLOY_CURRENT_LINK:-${DEPLOY_ROOT}/current}"
TMP_RELEASE_DIR="${DEPLOY_RELEASES_DIR}/${COMMIT_SHA}.tmp.$$"
RELEASE_DIR="${DEPLOY_RELEASES_DIR}/${COMMIT_SHA}"
RELEASE_METADATA_FILE="${RELEASE_DIR}/.deploy-meta"

SERVICES_DEFAULT="ouroboros-api ouroboros-worker ouroboros-web@main ouroboros-web@preview1 ouroboros-web@preview2 ouroboros-web@preview3 ouroboros-caddy"
DEPLOY_SERVICES="${DEPLOY_SERVICES:-${SERVICES_DEFAULT}}"
DEPLOY_HEALTHCHECK_CMD="${DEPLOY_HEALTHCHECK_CMD:-${DEPLOY_CURRENT_LINK}/scripts/runtime-health-check.sh}"
DEPLOY_REGISTRY_CMD="${DEPLOY_REGISTRY_CMD:-${SCRIPT_DIR}/release-registry.sh}"
PREVIOUS_TARGET=""
PREVIOUS_RELEASE_ID=""
PREVIOUS_RELEASE_COMMIT=""

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

  if [[ "${DEPLOY_SKIP_REGISTRY_UPDATE:-0}" == "1" ]]; then
    log "Skipping release registry update (DEPLOY_SKIP_REGISTRY_UPDATE=1)"
    return
  fi

  if [[ ! -x "${DEPLOY_REGISTRY_CMD}" ]]; then
    log "Release registry command not executable; skipping update: ${DEPLOY_REGISTRY_CMD}"
    return
  fi

  local cmd=(
    "${DEPLOY_REGISTRY_CMD}"
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

cleanup_tmp() {
  if [[ -n "${TMP_RELEASE_DIR}" && -d "${TMP_RELEASE_DIR}" ]]; then
    rm -rf "${TMP_RELEASE_DIR}"
  fi
}

trap cleanup_tmp EXIT

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
  if [[ "${DEPLOY_SKIP_SERVICE_RESTART:-0}" == "1" ]]; then
    log "Skipping service restart (DEPLOY_SKIP_SERVICE_RESTART=1)"
    return
  fi

  require_cmd sudo
  require_cmd systemctl
  log "Restarting services: ${DEPLOY_SERVICES}"
  # shellcheck disable=SC2086
  sudo systemctl restart ${DEPLOY_SERVICES}
}

run_health_gate() {
  if [[ "${DEPLOY_SKIP_HEALTHCHECK:-0}" == "1" ]]; then
    log "Skipping health gate (DEPLOY_SKIP_HEALTHCHECK=1)"
    return
  fi

  log "Running post-deploy health gate: ${DEPLOY_HEALTHCHECK_CMD}"
  if ! (
    cd "${DEPLOY_CURRENT_LINK}" &&
    bash -lc "${DEPLOY_HEALTHCHECK_CMD}"
  ); then
    log "Health gate failed"
    if [[ -n "${PREVIOUS_TARGET}" ]]; then
      log "Rolling back symlink to previous release: ${PREVIOUS_TARGET}"
      switch_current_link "${PREVIOUS_TARGET}"
      restart_services
    fi
    registry_upsert "${COMMIT_SHA}" "${COMMIT_SHA}" "deploy_failed"
    if [[ -n "${PREVIOUS_RELEASE_ID}" ]]; then
      registry_upsert "${PREVIOUS_RELEASE_ID}" "${PREVIOUS_RELEASE_COMMIT:-${PREVIOUS_RELEASE_ID}}" "deployed"
    fi
    die "Deployment failed health gate"
  fi
}

build_release() {
  local target_dir="$1"
  require_cmd python3
  require_cmd git

  if command -v npm >/dev/null 2>&1; then
    log "Building frontend artifacts"
    (
      cd "${target_dir}/frontend"
      npm ci
      npm run build
    )
    rm -rf "${target_dir}/infra/web-main"
    mkdir -p "${target_dir}/infra/web-main"
    cp -R "${target_dir}/frontend/dist/." "${target_dir}/infra/web-main/"
  else
    log "npm not found; leaving existing static web-main content unchanged"
  fi

  log "Preparing backend virtual environment"
  python3 -m venv "${target_dir}/backend/.venv"
  "${target_dir}/backend/.venv/bin/pip" install --upgrade pip
  "${target_dir}/backend/.venv/bin/pip" install -e "${target_dir}/backend"

  log "Preparing worker virtual environment"
  python3 -m venv "${target_dir}/worker/.venv"
  "${target_dir}/worker/.venv/bin/pip" install --upgrade pip
  "${target_dir}/worker/.venv/bin/pip" install -e "${target_dir}/worker"

  cat >"${target_dir}/.deploy-meta" <<EOF
commit_sha=${COMMIT_SHA}
built_at_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
build_host=$(hostname)
EOF
}

require_cmd git
git -C "${REPO_ROOT}" cat-file -e "${COMMIT_SHA}^{commit}" || die "Commit not found: ${COMMIT_SHA}"
structured_log "deploy_started" "Starting deployment pipeline"

mkdir -p "${DEPLOY_RELEASES_DIR}"

if [[ ! -d "${RELEASE_DIR}" ]]; then
  log "Creating release directory from commit ${COMMIT_SHA}: ${RELEASE_DIR}"
  mkdir -p "${TMP_RELEASE_DIR}"
  git -C "${REPO_ROOT}" archive "${COMMIT_SHA}" | tar -x -C "${TMP_RELEASE_DIR}"
  build_release "${TMP_RELEASE_DIR}"
  mv "${TMP_RELEASE_DIR}" "${RELEASE_DIR}"
else
  log "Release directory already exists: ${RELEASE_DIR}"
  if [[ ! -f "${RELEASE_METADATA_FILE}" ]]; then
    log "Existing release has no .deploy-meta; continuing"
  fi
fi

if [[ -L "${DEPLOY_CURRENT_LINK}" ]]; then
  PREVIOUS_TARGET="$(readlink -f "${DEPLOY_CURRENT_LINK}" || true)"
  if [[ -n "${PREVIOUS_TARGET}" ]]; then
    PREVIOUS_RELEASE_ID="$(basename "${PREVIOUS_TARGET}")"
    PREVIOUS_RELEASE_COMMIT="$(read_meta_value "${PREVIOUS_TARGET}/.deploy-meta" "commit_sha")"
  fi
fi

registry_upsert "${COMMIT_SHA}" "${COMMIT_SHA}" "deploying"
log "Switching current symlink atomically to ${RELEASE_DIR}"
switch_current_link "${RELEASE_DIR}"

restart_services
run_health_gate

registry_upsert "${COMMIT_SHA}" "${COMMIT_SHA}" "deployed"
if [[ -n "${PREVIOUS_RELEASE_ID}" && "${PREVIOUS_RELEASE_ID}" != "${COMMIT_SHA}" ]]; then
  registry_upsert "${PREVIOUS_RELEASE_ID}" "${PREVIOUS_RELEASE_COMMIT:-${PREVIOUS_RELEASE_ID}}" "replaced"
fi

log "Deployment succeeded"
log "Current release: ${RELEASE_DIR}"
structured_log "deploy_succeeded" "Deployment pipeline completed"
