#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${REDDIT_VOC_BACKFILL_PYTHON:-python3}"
PHASE="${REDDIT_VOC_BACKFILL_PHASE:-}"

fail() {
  printf 'backfill_wrapper_error=%s\n' "$1" >&2
  exit 64
}

require_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "missing_required_value:${name}"
}

append_required() {
  local flag="$1"
  local name="$2"
  require_env "$name"
  args+=("$flag" "${!name}")
}

[[ -n "$PHASE" ]] || fail "missing_phase"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src:$ROOT"

args=(-m reddit_voc.backfill_cli "$PHASE")

case "$PHASE" in
  seed)
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --database REDDIT_VOC_BACKFILL_DATABASE_PATH
    append_required --source-dir REDDIT_VOC_BACKFILL_SOURCE_DIR
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    append_required --report-dir REDDIT_VOC_BACKFILL_REPORT_DIR
    append_required --window-start-utc REDDIT_VOC_BACKFILL_WINDOW_START_UTC
    append_required --requested-window-end-utc REDDIT_VOC_BACKFILL_REQUESTED_WINDOW_END_UTC
    append_required --effective-window-end-utc REDDIT_VOC_BACKFILL_EFFECTIVE_WINDOW_END_UTC
    ;;
  probe)
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --database REDDIT_VOC_BACKFILL_DATABASE_PATH
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    append_required --report-dir REDDIT_VOC_BACKFILL_REPORT_DIR
    append_required --release-manifest REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    if [[ "${REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL:-}" == "1" ]]; then
      args+=(--authorize-provider-call)
    fi
    ;;
  collect)
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --database REDDIT_VOC_BACKFILL_DATABASE_PATH
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    append_required --report-dir REDDIT_VOC_BACKFILL_REPORT_DIR
    append_required --probe-report REDDIT_VOC_BACKFILL_PROBE_REPORT
    append_required --expected-probe-sha256 REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256
    append_required --release-manifest REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    append_required --expected-release-manifest-sha256 REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    append_required --comment-cursor-contract REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT
    append_required --max-provider-requests-total REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL
    append_required --include-subreddit-sweep REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP
    if [[ -n "${REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION:-}" \
      || -n "${REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256:-}" ]]; then
      append_required --budget-extension-authorization REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION
      append_required --expected-budget-extension-authorization-sha256 REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256
    fi
    if [[ -n "${REDDIT_VOC_BACKFILL_EXISTING_BUDGET_RESUME_AUTHORIZATION:-}" \
      || -n "${REDDIT_VOC_BACKFILL_EXPECTED_EXISTING_BUDGET_RESUME_AUTHORIZATION_SHA256:-}" ]]; then
      append_required --existing-budget-resume-authorization REDDIT_VOC_BACKFILL_EXISTING_BUDGET_RESUME_AUTHORIZATION
      append_required --expected-existing-budget-resume-authorization-sha256 REDDIT_VOC_BACKFILL_EXPECTED_EXISTING_BUDGET_RESUME_AUTHORIZATION_SHA256
    fi
    if [[ "${REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL:-}" == "1" ]]; then
      args+=(--authorize-provider-call)
    fi
    ;;
  replay)
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --source-database REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
    append_required --replay-database REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    ;;
  reindex-discovery)
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --source-database REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    append_required --reindexed-database REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH
    append_required --expected-source-database-sha256 REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256
    append_required --release-manifest REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    append_required --expected-release-manifest-sha256 REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    append_required --report REDDIT_VOC_BACKFILL_REPORT
    ;;
  recover-collection)
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --source-database REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    append_required --recovered-database REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH
    append_required --expected-source-database-sha256 REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256
    append_required --recovered-at-utc REDDIT_VOC_BACKFILL_RECOVERED_AT_UTC
    append_required --release-manifest REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    append_required --expected-release-manifest-sha256 REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    append_required --report REDDIT_VOC_BACKFILL_REPORT
    ;;
  validate)
    append_required --scope REDDIT_VOC_BACKFILL_SCOPE
    case "${REDDIT_VOC_BACKFILL_SCOPE}" in
      seed|full) ;;
      *) fail "invalid_validation_scope" ;;
    esac
    append_required --run-id REDDIT_VOC_BACKFILL_RUN_ID
    append_required --database REDDIT_VOC_BACKFILL_DATABASE_PATH
    append_required --raw-archive-dir REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    append_required --seed-baseline REDDIT_VOC_BACKFILL_SEED_BASELINE
    append_required --release-manifest REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    append_required --report REDDIT_VOC_BACKFILL_REPORT
    if [[ "${REDDIT_VOC_BACKFILL_SCOPE}" == "full" ]]; then
      append_required --replay-database REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH
      append_required --run-root REDDIT_VOC_BACKFILL_RUN_ROOT
      append_required --expected-release-manifest-sha256 REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    fi
    ;;
  *)
    fail "unsupported_phase"
    ;;
esac

exec "$PYTHON" "${args[@]}"
