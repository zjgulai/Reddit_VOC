#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${REDDIT_VOC_DEPLOY_ROOT:-/opt/reddit-voc-site}"
ENV_FILE="${REDDIT_VOC_ENV_FILE:-/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env}"
TIMEZONE="${REDDIT_VOC_TIMEZONE:-Asia/Shanghai}"
RUN_DATE="${REDDIT_VOC_RUN_DATE:-$(TZ="$TIMEZONE" date +%Y%m%d)}"
RUN_ID="${REDDIT_VOC_RUN_ID:-daily_collect_${RUN_DATE}_0700}"
ARTIFACT_BASE_URL="${REDDIT_VOC_ARTIFACT_BASE_URL:-https://reddit.lute-tlz-dddd.top/artifacts}"
DATABASE_PATH="${REDDIT_VOC_DATABASE_PATH:-/app/data/reddit_voc_daily.sqlite3}"
OUTPUT_DIR="${REDDIT_VOC_OUTPUT_DIR:-/app/outputs}"
LOG_DIR="${REDDIT_VOC_LOG_DIR:-/app/logs}"
HOST_OUTPUT_DIR="${DEPLOY_ROOT}/outputs"
HOST_LOG_DIR="${DEPLOY_ROOT}/logs"
COMPOSE_FILE="${DEPLOY_ROOT}/webapp/docker-compose.yml"

mkdir -p "${DEPLOY_ROOT}/data" "${HOST_OUTPUT_DIR}" "${HOST_LOG_DIR}"

write_blocked() {
  local reason="$1"
  local output="${HOST_OUTPUT_DIR}/${RUN_ID}-server-collect-blocked.json"
  python3 - "$output" "$RUN_ID" "$reason" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, run_id, reason = sys.argv[1:4]
payload = {
    "run_id": run_id,
    "status": "blocked",
    "reason": reason,
    "provider_call": False,
    "live_send": False,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print(json.dumps(payload, ensure_ascii=False))
PY
}

if [[ ! -f "$ENV_FILE" ]]; then
  write_blocked "missing_runtime_env_file"
  exit 0
fi

mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
if [[ -n "$mode" && "${mode: -2}" != "00" ]]; then
  write_blocked "runtime_env_file_permissions_blocked"
  exit 0
fi

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a

if [[ "${REDDIT_VOC_ENABLE_TIKHUB:-0}" != "1" || -z "${TIKHUB_API_KEY:-}" ]]; then
  write_blocked "missing_tikhub_runtime_gate_or_key"
  exit 0
fi

docker compose -p reddit_voc_site -f "$COMPOSE_FILE" run --rm --no-deps -T \
  -e REDDIT_VOC_PROJECT_ROOT=/app \
  -e REDDIT_VOC_TIMEZONE="$TIMEZONE" \
  -e REDDIT_VOC_RUN_HOUR="${REDDIT_VOC_RUN_HOUR:-7}" \
  -e REDDIT_VOC_RUN_DATE="$RUN_DATE" \
  -e REDDIT_VOC_RUN_ID="$RUN_ID" \
  -e REDDIT_VOC_ANCHOR_UTC \
  -e REDDIT_VOC_WINDOW_END_UTC \
  -e REDDIT_VOC_ROLLING_WINDOW_HOURS \
  -e REDDIT_VOC_COLLECTION_PROVIDER="${REDDIT_VOC_COLLECTION_PROVIDER:-tikhub}" \
  -e REDDIT_VOC_DATABASE_PATH="$DATABASE_PATH" \
  -e REDDIT_VOC_OUTPUT_DIR="$OUTPUT_DIR" \
  -e REDDIT_VOC_REPORT_OUTPUT_DIR="$OUTPUT_DIR" \
  -e REDDIT_VOC_LOG_DIR="$LOG_DIR" \
  -e REDDIT_VOC_ARTIFACT_BASE_URL="$ARTIFACT_BASE_URL" \
  -e REDDIT_VOC_ENABLE_TIKHUB \
  -e TIKHUB_BASE_URL \
  -e TIKHUB_API_KEY \
  -e REDDIT_VOC_TIKHUB_DAILY_REQUEST_LIMIT \
  -e REDDIT_VOC_SEARCH_TERMS \
  -e REDDIT_VOC_SUBREDDITS \
  -e REDDIT_VOC_LISTING_LIMIT \
  -e REDDIT_VOC_MAX_DETAIL_POSTS \
  reddit_voc_site_app bash /app/scripts/run_daily_collect.sh
