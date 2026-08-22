#!/usr/bin/env bash
set -euo pipefail

ROOT="${REDDIT_VOC_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

RUN_ID="${REDDIT_VOC_RUN_ID:-local_daily_dry_run_$(date +%Y%m%d_%H%M%S)}"
DATABASE="${REDDIT_VOC_DATABASE_PATH:-data/reddit_voc.sqlite3}"
OUTPUT_DIR="${REDDIT_VOC_OUTPUT_DIR:-outputs}"
LOG_DIR="${REDDIT_VOC_LOG_DIR:-logs}"
LOG_KEEP_LAST="${REDDIT_VOC_LOG_KEEP_LAST:-30}"
LOG_FILE="$LOG_DIR/${RUN_ID}.log"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"
exec 3>&1
printf 'run_id=%s start=%s provider_call=false live_send=false\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m reddit_voc.cli init-local \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/${RUN_ID}-init-local.json" \
  2>> "$LOG_FILE"

python3 -m reddit_voc.cli run-adapter-fixture-loop \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-collector-summary.json" \
  2>> "$LOG_FILE"

python3 -m reddit_voc.cli export-run \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-export-summary.json" \
  2>> "$LOG_FILE"

python3 -m reddit_voc.cli build-dingtalk-dry-run \
  --database "$DATABASE" \
  --output-dir "$OUTPUT_DIR" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-delivery-summary.json" \
  2>> "$LOG_FILE"

report_args=(
  -m reddit_voc.cli build-daily-report
  --database "$DATABASE"
  --output-dir "$OUTPUT_DIR"
  --run-id "$RUN_ID"
  --translation-mode "${REDDIT_VOC_TRANSLATION_MODE:-dry_run}"
)
if [[ -n "${REDDIT_VOC_ARTIFACT_BASE_URL:-}" ]]; then
  report_args+=(--artifact-base-url "$REDDIT_VOC_ARTIFACT_BASE_URL")
fi
if [[ -n "${DINGTALK_REQUIRED_KEYWORD:-}" ]]; then
  report_args+=(--required-keyword "$DINGTALK_REQUIRED_KEYWORD")
fi
python3 "${report_args[@]}" \
  > "$OUTPUT_DIR/${RUN_ID}-daily-report-command.json" \
  2>> "$LOG_FILE"

python3 -m reddit_voc.cli status-summary \
  --database "$DATABASE" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-status-summary.json" \
  2>> "$LOG_FILE"

python3 -m reddit_voc.cli issue-summary \
  --database "$DATABASE" \
  --run-id "$RUN_ID" \
  > "$OUTPUT_DIR/${RUN_ID}-issue-summary.json" \
  2>> "$LOG_FILE" || true

python3 -m reddit_voc.cli prune-artifacts \
  --path "$LOG_DIR" \
  --pattern "*.log" \
  --keep-last "$LOG_KEEP_LAST" \
  --apply \
  > "$OUTPUT_DIR/${RUN_ID}-log-retention-summary.json" \
  2>> "$LOG_FILE"

printf 'run_id=%s end=%s provider_call=false live_send=false\n' "$RUN_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"

printf '{"run_id":"%s","database":"%s","output_dir":"%s","provider_call":false,"live_send":false}\n' \
  "$RUN_ID" "$DATABASE" "$OUTPUT_DIR" >&3
