#!/usr/bin/env bash
# Product API only — use on Render Account A (2 GB + optional disk).
# One worker: each worker would reload Torch into RAM.
set -euo pipefail

PORT="${PORT:-8000}"
DB="${SKYGUARD_DB:-data/skyguard.db}"
mkdir -p "$(dirname "$DB")"

exec uvicorn skyguard.api.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers 1
