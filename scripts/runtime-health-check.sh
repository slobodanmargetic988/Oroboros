#!/usr/bin/env bash
set -euo pipefail

check() {
  local name="$1"
  local cmd="$2"
  echo "[check] ${name}"
  eval "$cmd"
}

check "api health" "curl -fsS http://127.0.0.1:8000/health >/dev/null"
check "worker health" "curl -fsS http://127.0.0.1:8090/health >/dev/null"
check "proxy app.example.com" "curl -fsS -H 'Host: app.example.com' http://127.0.0.1:8088/health >/dev/null"
./scripts/preview-slots-health-check.sh
check "postgres health" "pg_isready -h 127.0.0.1 -U postgres -d builder_control >/dev/null"
check "redis health" "redis-cli -h 127.0.0.1 ping | grep -q PONG"

echo "All runtime health checks passed."
