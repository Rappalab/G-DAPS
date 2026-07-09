#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

export PYTHONPATH="$APP_DIR"
set -a
[ -f .env ] && source .env
set +a

INTERVAL="${AUTO_FIRE_INTERVAL:-120}"
exec "$APP_DIR/.venv/bin/python" -m app.wildfire_monitor --loop --interval "$INTERVAL"
