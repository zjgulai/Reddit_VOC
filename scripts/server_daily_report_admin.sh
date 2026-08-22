#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REDDIT_VOC_HOST_PYTHON_BIN:-python3}"

export PYTHONNOUSERSITE=1
exec "$PYTHON_BIN" "$ROOT/scripts/report_control.py" admin "$@"
