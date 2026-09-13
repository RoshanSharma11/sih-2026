#!/usr/bin/env bash
# Hugging Face Space entrypoint: API + Palam streamer + Streamlit console.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export SKYGUARD_API="${SKYGUARD_API:-http://127.0.0.1:8000}"
UI_PORT="${PORT:-7860}"

python -m uvicorn skyguard.api.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

python - <<'PY'
import sys
import time
import urllib.request

deadline = time.time() + 180
last = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2) as response:
            if response.status == 200:
                sys.exit(0)
    except Exception as exc:
        last = exc
    time.sleep(1)
print(f"API did not become healthy: {last}", file=sys.stderr)
sys.exit(1)
PY

python -m skyguard.data.stream \
  --api "$SKYGUARD_API" \
  --ms 200 \
  --start 2024-07-01T00:00:00Z \
  --stations 42181 \
  --with-buddies &
STREAM_PID=$!

cleanup() {
  kill "$API_PID" "$STREAM_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python -m streamlit run frontend/app.py \
  --server.address 0.0.0.0 \
  --server.port "$UI_PORT" \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false
