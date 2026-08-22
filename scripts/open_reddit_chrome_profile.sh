#!/usr/bin/env bash
set -euo pipefail

ROOT="${REDDIT_VOC_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

PROFILE_DIR="${REDDIT_VOC_CHROME_USER_DATA_DIR:-$HOME/.reddit-voc/chrome-profile}"
START_URL="${REDDIT_VOC_CHROME_START_URL:-https://www.reddit.com/login/}"
OPEN_CHROME="${REDDIT_VOC_OPEN_CHROME:-1}"
REMOTE_DEBUG_PORT="${REDDIT_VOC_CHROME_REMOTE_DEBUG_PORT:-}"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m reddit_voc.cli browser-profile-init --profile-dir "$PROFILE_DIR"

if [[ "$OPEN_CHROME" == "1" ]]; then
  CHROME_ARGS=(
    "--user-data-dir=$PROFILE_DIR" \
    "--profile-directory=Default"
  )
  if [[ -n "$REMOTE_DEBUG_PORT" ]]; then
    CHROME_ARGS+=("--remote-debugging-port=$REMOTE_DEBUG_PORT")
  fi
  CHROME_ARGS+=("$START_URL")
  open -na "Google Chrome" --args "${CHROME_ARGS[@]}"
  if [[ -n "$REMOTE_DEBUG_PORT" ]]; then
    printf '{"status":"launch_requested","profile_dir":"%s","start_url":"%s","browser_cdp_url":"http://127.0.0.1:%s","provider_call":false,"live_send":false,"reddit_write":false}\n' "$PROFILE_DIR" "$START_URL" "$REMOTE_DEBUG_PORT"
  else
    printf '{"status":"launch_requested","profile_dir":"%s","start_url":"%s","provider_call":false,"live_send":false,"reddit_write":false}\n' "$PROFILE_DIR" "$START_URL"
  fi
else
  if [[ -n "$REMOTE_DEBUG_PORT" ]]; then
    python3 -m reddit_voc.cli browser-profile-launch-command --profile-dir "$PROFILE_DIR" --start-url "$START_URL" --remote-debug-port "$REMOTE_DEBUG_PORT"
  else
    python3 -m reddit_voc.cli browser-profile-launch-command --profile-dir "$PROFILE_DIR" --start-url "$START_URL"
  fi
fi
