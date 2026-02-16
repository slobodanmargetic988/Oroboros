#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[setup] Root: ${ROOT_DIR}"
echo "[setup] Copying .env.example to .env if needed"
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
fi

echo "[setup] Done. Install dependencies per docs/local-development.md"
