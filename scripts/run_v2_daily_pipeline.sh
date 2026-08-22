#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 8 ]]; then
  echo "usage: $0 DAILY_MANIFEST DAILY_RECEIPT CENTER_DB V2_OUTPUT_ROOT REFRESH_RUN_ID WINDOW_START_UTC WINDOW_END_UTC CUTOFF_UTC" >&2
  exit 64
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAILY_MANIFEST="$1"
DAILY_RECEIPT="$2"
CENTER_DB="$3"
V2_OUTPUT_ROOT="$4"
REFRESH_RUN_ID="$5"
WINDOW_START_UTC="$6"
WINDOW_END_UTC="$7"
CUTOFF_UTC="$8"
REFRESH_ROOT="$V2_OUTPUT_ROOT/source-batches/comment-refresh"
REFRESH_MANIFEST="$REFRESH_ROOT/$REFRESH_RUN_ID/source-batch-manifest.json"
REFRESH_RECEIPT="$V2_OUTPUT_ROOT/validation-receipts/$REFRESH_RUN_ID.json"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m reddit_voc.cli run-comment-refresh \
  --center-database "$CENTER_DB" \
  --source-batch-root "$REFRESH_ROOT" \
  --run-id "$REFRESH_RUN_ID" \
  --window-start-utc "$WINDOW_START_UTC" \
  --window-end-utc "$WINDOW_END_UTC" \
  --query-profile "$ROOT/config/source-batch/momcozy-query-v2.json" \
  --coverage-profile "$ROOT/config/source-batch/momcozy-coverage-v2.json" \
  --authorize-provider-call

VALIDATION_OBSERVED_AT_UTC="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))')"
python3 "$ROOT/scripts/validate_reddit_source_batch.py" \
  --manifest "$REFRESH_MANIFEST" \
  --batch-root "$(dirname "$REFRESH_MANIFEST")" \
  --observed-at-utc "$VALIDATION_OBSERVED_AT_UTC" \
  --require-consumable \
  --output "$REFRESH_RECEIPT"

QUIESCENCE_SECONDS="${V2_QUIESCENCE_SECONDS:-60}"
if [[ ! "$QUIESCENCE_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "V2_QUIESCENCE_SECONDS must be a positive integer" >&2
  exit 64
fi
sleep "$QUIESCENCE_SECONDS"
ORCHESTRATION_OBSERVED_AT_UTC="$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))')"

python3 "$ROOT/scripts/orchestrate_reddit_v2_candidate.py" \
  --center-database "$CENTER_DB" \
  --source-batch-manifest "$DAILY_MANIFEST" \
  --source-batch-validation-receipt "$DAILY_RECEIPT" \
  --source-batch-manifest "$REFRESH_MANIFEST" \
  --source-batch-validation-receipt "$REFRESH_RECEIPT" \
  --output-root "$V2_OUTPUT_ROOT" \
  --cutoff-utc "$CUTOFF_UTC" \
  --observed-at-utc "$ORCHESTRATION_OBSERVED_AT_UTC" \
  --quiescence-seconds "$QUIESCENCE_SECONDS" \
  --receipt "$V2_OUTPUT_ROOT/orchestration-receipts/$REFRESH_RUN_ID.json" \
  --attempt-receipt "$V2_OUTPUT_ROOT/orchestration-attempts/$REFRESH_RUN_ID.json"
