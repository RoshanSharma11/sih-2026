#!/usr/bin/env bash
# Streamlit console only — use on Render Account B.
# Set SKYGUARD_API (and SKYGUARD_PUBLIC_API) to Account A's public URL.
set -euo pipefail

PORT="${PORT:-8501}"

exec streamlit run frontend/app.py \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false \
  --theme.base=light \
  --theme.primaryColor=#0D9488 \
  --theme.backgroundColor=#F8FAFC \
  --theme.secondaryBackgroundColor=#FFFFFF \
  --theme.textColor=#0F172A \
  --theme.base=light \
  --theme.primaryColor=#0D9488 \
  --theme.backgroundColor=#F8FAFC \
  --theme.secondaryBackgroundColor=#FFFFFF \
  --theme.textColor=#0F172A
