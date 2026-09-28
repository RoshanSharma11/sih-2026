#!/usr/bin/env bash
# API and dashboard in one container. The dashboard polls 127.0.0.1 inside this process.
set -euo pipefail

mkdir -p "$(dirname "${SKYGUARD_DB:-/var/lib/skyguard/skyguard.db}")"

uvicorn skyguard.api.main:app --host 0.0.0.0 --port 8000 &
api_pid=$!

streamlit run frontend/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false \
  --server.enableCORS false \
  --server.enableXsrfProtection false &
ui_pid=$!

trap 'kill "$api_pid" "$ui_pid" 2>/dev/null || true' TERM INT

wait -n "$api_pid" "$ui_pid"
status=$?
kill "$api_pid" "$ui_pid" 2>/dev/null || true
wait || true
exit "$status"
