#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${REDDIT_VOC_DEPLOY_ROOT:-/opt/reddit-voc-site}"
ENV_FILE="${REDDIT_VOC_ENV_FILE:-/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env}"
TIMEZONE="${REDDIT_VOC_TIMEZONE:-Asia/Shanghai}"
RUN_DATE="${REDDIT_VOC_RUN_DATE:-$(TZ="$TIMEZONE" date +%Y%m%d)}"
RUN_ID="${REDDIT_VOC_RUN_ID:-daily_collect_${RUN_DATE}_0700}"

HOST_LOG_DIR="${DEPLOY_ROOT}/logs"
COLLECT_SCRIPT="${DEPLOY_ROOT}/scripts/server_daily_collect.sh"
REPORT_SCRIPT="${DEPLOY_ROOT}/scripts/server_daily_report.sh"

mkdir -p "$HOST_LOG_DIR"

write_blocked() {
  local reason="$1"
  local output="$HOST_LOG_DIR/${RUN_ID}-server-cycle-blocked.json"
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

set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a

if [[ "${REDDIT_VOC_ENABLE_TIKHUB:-0}" != "1" || -z "${TIKHUB_API_KEY:-}" ]]; then
  write_blocked "missing_tikhub_runtime_gate_or_key"
  exit 0
fi

if [[ "${REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND:-0}" != "1" ]]; then
  printf 'WARN: REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND is not enabled; report step will run as dry_run.\n'
fi

collect_rc=0
report_rc=0

REDDIT_VOC_RUN_ID="$RUN_ID" \
REDDIT_VOC_RUN_DATE="$RUN_DATE" \
REDDIT_VOC_SOURCE_RUN_ID="$RUN_ID" \
REDDIT_VOC_PROJECT_ROOT="$DEPLOY_ROOT" \
bash "$COLLECT_SCRIPT" >> "$HOST_LOG_DIR/${RUN_ID}-daily-cycle.log" 2>&1 || collect_rc=$?

if [[ "$collect_rc" -ne 0 ]]; then
  write_blocked "collect_failed"
  exit "$collect_rc"
fi

REDDIT_VOC_RUN_ID="$RUN_ID" \
REDDIT_VOC_RUN_DATE="$RUN_DATE" \
REDDIT_VOC_SOURCE_RUN_ID="$RUN_ID" \
REDDIT_VOC_PROJECT_ROOT="$DEPLOY_ROOT" \
bash "$REPORT_SCRIPT" >> "$HOST_LOG_DIR/${RUN_ID}-daily-cycle.log" 2>&1 || report_rc=$?

if [[ "$report_rc" -ne 0 ]]; then
  write_blocked "report_failed"
  exit "$report_rc"
fi

printf '{"run_id":"%s","collect_rc":%s,"report_rc":%s,"created_at_utc":"%s"}\n' \
  "$RUN_ID" "$collect_rc" "$report_rc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
