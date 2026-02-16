#!/usr/bin/env bash
set -euo pipefail

check() {
  local name="$1"
  local cmd="$2"
  echo "[check] ${name}"
  eval "${cmd}"
}

# Direct per-slot health
check "preview1 direct health" "curl -fsS http://127.0.0.1:3101/health >/dev/null"
check "preview2 direct health" "curl -fsS http://127.0.0.1:3102/health >/dev/null"
check "preview3 direct health" "curl -fsS http://127.0.0.1:3103/health >/dev/null"

# Routed per-slot health
check "preview1 routed health" "curl -fsS -H 'Host: preview1.example.com' http://127.0.0.1:8088/health >/dev/null"
check "preview2 routed health" "curl -fsS -H 'Host: preview2.example.com' http://127.0.0.1:8088/health >/dev/null"
check "preview3 routed health" "curl -fsS -H 'Host: preview3.example.com' http://127.0.0.1:8088/health >/dev/null"

echo "Preview slot health checks passed."
