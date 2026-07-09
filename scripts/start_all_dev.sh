#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

./scripts/start_api.sh &
API_PID=$!

if [ "${AUTO_FIRE_MONITOR:-0}" = "1" ]; then
  ./scripts/start_monitor.sh &
  MONITOR_PID=$!
else
  MONITOR_PID=""
fi

./scripts/start_streamlit.sh &
STREAMLIT_PID=$!

trap 'kill "$API_PID" "$STREAMLIT_PID" ${MONITOR_PID:-} 2>/dev/null || true' EXIT
wait
