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
check "proxy preview1.example.com" "curl -fsS -H 'Host: preview1.example.com' http://127.0.0.1:8088/health >/dev/null"
check "proxy preview2.example.com" "curl -fsS -H 'Host: preview2.example.com' http://127.0.0.1:8088/health >/dev/null"
check "proxy preview3.example.com" "curl -fsS -H 'Host: preview3.example.com' http://127.0.0.1:8088/health >/dev/null"
check "postgres health" "docker compose -f infra/docker-compose.runtime.yml exec -T postgres pg_isready -U postgres -d builder_control >/dev/null"
check "redis health" "docker compose -f infra/docker-compose.runtime.yml exec -T redis redis-cli ping | grep -q PONG"

echo "All runtime health checks passed."
