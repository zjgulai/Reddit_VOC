#!/usr/bin/env bash
set -euo pipefail

ROOT="${REDDIT_VOC_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"
. "$ROOT/scripts/load_runtime_env.sh"

LOCAL_TZ="${REDDIT_VOC_TIMEZONE:-Asia/Shanghai}"
RUN_DATE="${REDDIT_VOC_RUN_DATE:-$(TZ="$LOCAL_TZ" date +%Y%m%d)}"
RUN_ID="${REDDIT_VOC_SOURCE_RUN_ID:-${REDDIT_VOC_RUN_ID:-daily_collect_${RUN_DATE}_0700}}"
DATABASE="${REDDIT_VOC_DATABASE_PATH:-data/reddit_voc.sqlite3}"
OUTPUT_DIR="${REDDIT_VOC_REPORT_OUTPUT_DIR:-${REDDIT_VOC_OUTPUT_DIR:-outputs}}"
LOG_DIR="${REDDIT_VOC_LOG_DIR:-logs}"
LOG_KEEP_LAST="${REDDIT_VOC_LOG_KEEP_LAST:-30}"
TRANSLATION_MODE="${REDDIT_VOC_TRANSLATION_MODE:-dry_run}"
ARTIFACT_BASE_URL="${REDDIT_VOC_ARTIFACT_BASE_URL:-}"
REQUIRED_KEYWORD="${DINGTALK_REQUIRED_KEYWORD:-}"
LOG_FILE="$LOG_DIR/${RUN_ID}-daily-report.log"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"
exec 3>&1
printf 'run_id=%s phase=report start=%s provider_call=false live_send=false translation_mode=%s\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TRANSLATION_MODE" >> "$LOG_FILE"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

report_args=(
  -m reddit_voc.cli build-daily-report
  --database "$DATABASE"
  --output-dir "$OUTPUT_DIR"
  --run-id "$RUN_ID"
  --translation-mode "$TRANSLATION_MODE"
)

if [[ -n "$ARTIFACT_BASE_URL" ]]; then
  report_args+=(--artifact-base-url "$ARTIFACT_BASE_URL")
fi
if [[ -n "$REQUIRED_KEYWORD" ]]; then
  report_args+=(--required-keyword "$REQUIRED_KEYWORD")
fi

report_rc=0
python3 "${report_args[@]}" \
  > "$OUTPUT_DIR/${RUN_ID}-daily-report-command.json" \
  2>> "$LOG_FILE" || report_rc=$?

report_provider_call="$(
  python3 - "$OUTPUT_DIR/${RUN_ID}-daily-report-command.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("false")
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("false")
    raise SystemExit(0)
print("true" if payload.get("provider_call") else "false")
PY
)"

python3 -m reddit_voc.cli prune-artifacts \
  --path "$LOG_DIR" \
  --pattern "*.log" \
  --keep-last "$LOG_KEEP_LAST" \
  --apply \
  > "$OUTPUT_DIR/${RUN_ID}-report-log-retention-summary.json" \
  2>> "$LOG_FILE" || true

printf 'run_id=%s phase=report end=%s provider_call=%s live_send=false rc=%s\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$report_provider_call" "$report_rc" >> "$LOG_FILE"
printf '{"run_id":"%s","database":"%s","output_dir":"%s","provider_call":%s,"live_send":false,"return_code":%s}\n' \
  "$RUN_ID" "$DATABASE" "$OUTPUT_DIR" "$report_provider_call" "$report_rc" >&3
exit "$report_rc"
