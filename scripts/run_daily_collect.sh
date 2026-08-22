#!/usr/bin/env bash
set -euo pipefail

ROOT="${REDDIT_VOC_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"
. "$ROOT/scripts/load_runtime_env.sh"

LOCAL_TZ="${REDDIT_VOC_TIMEZONE:-Asia/Shanghai}"
RUN_DATE="${REDDIT_VOC_RUN_DATE:-$(TZ="$LOCAL_TZ" date +%Y%m%d)}"
RUN_HOUR="${REDDIT_VOC_RUN_HOUR:-7}"
RUN_ID="${REDDIT_VOC_RUN_ID:-daily_collect_${RUN_DATE}_0700}"
DATABASE="${REDDIT_VOC_DATABASE_PATH:-data/reddit_voc.sqlite3}"
OUTPUT_DIR="${REDDIT_VOC_OUTPUT_DIR:-outputs}"
LOG_DIR="${REDDIT_VOC_LOG_DIR:-logs}"
LOG_KEEP_LAST="${REDDIT_VOC_LOG_KEEP_LAST:-30}"
LISTING_LIMIT="${REDDIT_VOC_LISTING_LIMIT:-100}"
MAX_DETAIL_POSTS="${REDDIT_VOC_MAX_DETAIL_POSTS:-50}"
COLLECTION_PROVIDER="${REDDIT_VOC_COLLECTION_PROVIDER:-tikhub}"
LOG_FILE="$LOG_DIR/${RUN_ID}-collect.log"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"
exec 3>&1
printf 'run_id=%s phase=collect start=%s provider_call=false live_send=false\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m reddit_voc.cli init-local \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/${RUN_ID}-init-local.json" \
  2>> "$LOG_FILE"

collect_args=(
  -m reddit_voc.cli
)

if [[ "$COLLECTION_PROVIDER" == "tikhub" ]]; then
  collect_args+=(run-tikhub-collector --authorize-provider-call)
else
  collect_args+=(run-daily-collector)
fi

collect_args+=(
  --database "$DATABASE"
  --output-dir "$OUTPUT_DIR"
  --run-id "$RUN_ID"
  --run-hour "$RUN_HOUR"
  --listing-limit "$LISTING_LIMIT"
  --max-detail-posts "$MAX_DETAIL_POSTS"
)

if [[ -n "${REDDIT_VOC_ANCHOR_UTC:-}" ]]; then
  collect_args+=(--anchor-utc "$REDDIT_VOC_ANCHOR_UTC")
fi
if [[ -n "${REDDIT_VOC_WINDOW_END_UTC:-}" ]]; then
  collect_args+=(--window-end-utc "$REDDIT_VOC_WINDOW_END_UTC")
fi
if [[ -n "${REDDIT_VOC_ROLLING_WINDOW_HOURS:-}" ]]; then
  collect_args+=(--rolling-window-hours "$REDDIT_VOC_ROLLING_WINDOW_HOURS")
fi
if [[ -n "${REDDIT_VOC_BROWSER_CDP_URL:-}" ]]; then
  collect_args+=(--browser-cdp-url "$REDDIT_VOC_BROWSER_CDP_URL")
fi
if [[ -n "${REDDIT_VOC_BROWSER_DAEMON_NAME:-}" ]]; then
  collect_args+=(--browser-daemon-name "$REDDIT_VOC_BROWSER_DAEMON_NAME")
fi
if [[ -n "${REDDIT_VOC_SUBREDDITS:-}" ]]; then
  IFS=',' read -r -a subreddit_items <<< "$REDDIT_VOC_SUBREDDITS"
  for subreddit in "${subreddit_items[@]}"; do
    subreddit="${subreddit//[[:space:]]/}"
    if [[ -n "$subreddit" ]]; then
      collect_args+=(--subreddit "$subreddit")
    fi
  done
fi
if [[ "$COLLECTION_PROVIDER" == "tikhub" && -n "${REDDIT_VOC_SEARCH_TERMS:-}" ]]; then
  IFS=',' read -r -a search_items <<< "$REDDIT_VOC_SEARCH_TERMS"
  for term in "${search_items[@]}"; do
    term="${term#"${term%%[![:space:]]*}"}"
    term="${term%"${term##*[![:space:]]}"}"
    if [[ -n "$term" ]]; then
      collect_args+=(--search-term "$term")
    fi
  done
fi

collect_rc=0
python3 "${collect_args[@]}" \
  > "$OUTPUT_DIR/${RUN_ID}-collector-summary.json" \
  2>> "$LOG_FILE" || collect_rc=$?

python3 -m reddit_voc.cli export-run \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-export-summary.json" \
  2>> "$LOG_FILE" || true

python3 -m reddit_voc.cli status-summary \
  --database "$DATABASE" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-status-summary.json" \
  2>> "$LOG_FILE" || true

python3 -m reddit_voc.cli issue-summary \
  --database "$DATABASE" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-issue-summary.json" \
  2>> "$LOG_FILE" || true

source_batch_rc=0
python3 -m reddit_voc.cli build-daily-source-batch \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  --run-id "$RUN_ID" \
  --query-profile "$ROOT/config/source-batch/momcozy-query-v2.json" \
  --coverage-profile "$ROOT/config/source-batch/momcozy-coverage-v2.json" \
  > "$OUTPUT_DIR/${RUN_ID}-source-batch-summary.json" \
  2>> "$LOG_FILE" || source_batch_rc=$?

python3 -m reddit_voc.cli prune-artifacts \
  --path "$LOG_DIR" \
  --pattern "*.log" \
  --keep-last "$LOG_KEEP_LAST" \
  --apply \
  > "$OUTPUT_DIR/${RUN_ID}-collect-log-retention-summary.json" \
  2>> "$LOG_FILE" || true

collector_provider_call="$(
  python3 - "$OUTPUT_DIR/${RUN_ID}-collector-summary.json" <<'PY'
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

printf 'run_id=%s phase=collect end=%s provider_call=%s live_send=false rc=%s source_batch_rc=%s\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$collector_provider_call" "$collect_rc" "$source_batch_rc" >> "$LOG_FILE"
printf '{"run_id":"%s","database":"%s","output_dir":"%s","provider_call":%s,"live_send":false,"return_code":%s,"source_batch_return_code":%s}\n' \
  "$RUN_ID" "$DATABASE" "$OUTPUT_DIR" "$collector_provider_call" "$collect_rc" "$source_batch_rc" >&3
if [[ "$collect_rc" -ne 0 ]]; then
  exit "$collect_rc"
fi
exit "$source_batch_rc"
