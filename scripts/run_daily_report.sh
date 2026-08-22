#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="${REDDIT_VOC_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CLI_PYTHON="${REDDIT_VOC_CLI_PYTHON_BIN:-python3}"
SYSTEM_PYTHON="${REDDIT_VOC_SYSTEM_PYTHON_BIN:-python3}"
REPORT_ENV_FILE="${REDDIT_VOC_REPORT_ENV_FILE:-/run/secrets/reddit_voc_report.env}"

fail() {
  printf 'report_wrapper=blocked\nreason=%s\nprovider_call=false\ntranslation_provider_attempt_made=false\nlive_send=false\n' "$1" >&2
  exit 1
}

safe_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]
}

sha256_value() {
  [[ "$1" =~ ^[0-9a-f]{64}$ ]]
}

version_id() {
  [[ "$1" =~ ^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$ ]]
}

report_value() {
  local variable="REPORT_VALUE_$1"
  printf '%s' "${!variable-}"
}

load_report_env() {
  local report_env_fd=8
  if ! exec 8<"$REPORT_ENV_FILE"; then
    fail "report_env_missing"
  fi
  "$SYSTEM_PYTHON" - "$report_env_fd" "$REPORT_ENV_FILE" <<'PY' || {
import os
import re
import stat
import sys

allowed = {
    "REDDIT_VOC_DATABASE_PATH",
    "REDDIT_VOC_RUN_ID",
    "REDDIT_VOC_ATTEMPT_ID",
    "REDDIT_VOC_ARTIFACT_VERSION_ID",
    "REDDIT_VOC_REPORT_PUBLIC_ROOT",
    "REDDIT_VOC_REPORT_PRIVATE_ROOT",
    "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT",
    "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT",
    "REDDIT_VOC_REPORT_STATE_ROOT",
    "REDDIT_VOC_REPORT_BLOCKED_ROOT",
    "REDDIT_VOC_REPORT_HANDOFF_ROOT",
    "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT",
    "REDDIT_VOC_CONFIG_ROOT",
    "REDDIT_VOC_ARTIFACT_BASE_URL",
    "DINGTALK_REQUIRED_KEYWORD",
    "REDDIT_VOC_DINGTALK_MAX_BYTES",
    "REDDIT_VOC_DINGTALK_MAX_PARTS",
    "REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID",
    "REDDIT_VOC_DINGTALK_DESTINATION_ALIAS",
    "REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID",
    "REDDIT_VOC_DINGTALK_DESTINATION_SET_ID",
    "REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS",
    "REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS",
    "REDDIT_VOC_TRANSLATION_MODE",
    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION",
    "REDDIT_VOC_DINGTALK_MODE",
    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND",
    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT",
    "DINGTALK_WEBHOOK_URL",
    "DINGTALK_WEBHOOK_SECRET",
    "DINGTALK_WEBHOOK_URL_2",
    "DINGTALK_WEBHOOK_SECRET_2",
}
try:
    descriptor = int(sys.argv[1])
    path = sys.argv[2]
    path_metadata = os.lstat(path)
    descriptor_metadata = os.fstat(descriptor)
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISREG(path_metadata.st_mode)
        or not stat.S_ISREG(descriptor_metadata.st_mode)
        or path_metadata.st_dev != descriptor_metadata.st_dev
        or path_metadata.st_ino != descriptor_metadata.st_ino
    ):
        raise ValueError("report_env_not_regular")
    if descriptor_metadata.st_uid != os.getuid():
        raise ValueError("report_env_owner_invalid")
    if stat.S_IMODE(descriptor_metadata.st_mode) != 0o600:
        raise ValueError("report_env_mode_invalid")
    chunks = []
    total = 0
    while True:
        chunk = os.read(descriptor, 65_536)
        if not chunk:
            break
        total += len(chunk)
        if total > 4 * 1024 * 1024:
            raise ValueError("report_env_too_large")
        chunks.append(chunk)
    payload = b"".join(chunks)
    if b"\x00" in payload or b"\r" in payload:
        raise ValueError("report_env_control_character")
    text = payload.decode("utf-8")
    seen = set()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("report_env_assignment_invalid")
        key, _value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("report_env_key_invalid")
        if key not in allowed:
            raise ValueError("report_env_unknown_key")
        if key in seen:
            raise ValueError("report_env_duplicate_key")
        seen.add(key)
    os.lseek(descriptor, 0, os.SEEK_SET)
except (OSError, UnicodeError, ValueError) as exc:
    reason = str(exc) if str(exc).startswith("report_env_") else "report_env_invalid"
    print(f"report_wrapper=blocked\nreason={reason}", file=sys.stderr)
    raise SystemExit(1)
PY
    exec 8<&-
    exit 1
  }

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    printf -v "REPORT_VALUE_$key" '%s' "$value"
  done <&8
  exec 8<&-
}

require_env_names() {
  local key
  for key in "$@"; do
    [[ -n "$(report_value "$key")" ]] || fail "report_env_required_value_missing"
  done
}

phase="${1:-}"
[[ -n "$phase" ]] || fail "phase_required"
shift

if [[ "$phase" == "smoke" ]]; then
  config_root=""
  work_root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config-root)
        [[ $# -ge 2 ]] || fail "smoke_argument_missing"
        config_root="$2"
        shift 2
        ;;
      --work-root)
        [[ $# -ge 2 ]] || fail "smoke_argument_missing"
        work_root="$2"
        shift 2
        ;;
      *) fail "smoke_argument_invalid" ;;
    esac
  done
  [[ -n "$config_root" && -n "$work_root" ]] || fail "smoke_argument_missing"
  REDDIT_VOC_TRANSLATION_MODE=dry_run \
  REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0 \
  REDDIT_VOC_DINGTALK_MODE=dry_run \
  REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0 \
  REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0 \
  PYTHONPATH="$ROOT/src" \
    "$CLI_PYTHON" "$ROOT/scripts/report_runtime_smoke.py" \
      --config-root "$config_root" --work-root "$work_root"
  exit $?
fi

load_report_env

DATABASE_PATH="$(report_value REDDIT_VOC_DATABASE_PATH)"
RUN_ID="$(report_value REDDIT_VOC_RUN_ID)"
ATTEMPT_ID="$(report_value REDDIT_VOC_ATTEMPT_ID)"
ARTIFACT_VERSION_ID="$(report_value REDDIT_VOC_ARTIFACT_VERSION_ID)"
PUBLIC_ROOT="$(report_value REDDIT_VOC_REPORT_PUBLIC_ROOT)"
PRIVATE_ROOT="$(report_value REDDIT_VOC_REPORT_PRIVATE_ROOT)"
PUBLIC_STAGING_ROOT="$(report_value REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT)"
PRIVATE_STAGING_ROOT="$(report_value REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT)"
STATE_ROOT="$(report_value REDDIT_VOC_REPORT_STATE_ROOT)"
BLOCKED_ROOT="$(report_value REDDIT_VOC_REPORT_BLOCKED_ROOT)"
HANDOFF_ROOT="$(report_value REDDIT_VOC_REPORT_HANDOFF_ROOT)"
PROVIDER_ATTEMPT_ROOT="$(report_value REDDIT_VOC_PROVIDER_ATTEMPT_ROOT)"
CONFIG_ROOT="$(report_value REDDIT_VOC_CONFIG_ROOT)"
ARTIFACT_BASE_URL="$(report_value REDDIT_VOC_ARTIFACT_BASE_URL)"
REQUIRED_KEYWORD="$(report_value DINGTALK_REQUIRED_KEYWORD)"
DINGTALK_MAX_BYTES="$(report_value REDDIT_VOC_DINGTALK_MAX_BYTES)"
DINGTALK_MAX_PARTS="$(report_value REDDIT_VOC_DINGTALK_MAX_PARTS)"
CREDENTIAL_EPOCH_ID="$(report_value REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID)"
DESTINATION_ALIAS="$(report_value REDDIT_VOC_DINGTALK_DESTINATION_ALIAS)"
CREDENTIAL_SET_EPOCH_ID="$(report_value REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID)"
DESTINATION_SET_ID="$(report_value REDDIT_VOC_DINGTALK_DESTINATION_SET_ID)"
PRIMARY_DESTINATION_ALIAS="$(report_value REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS)"
SECONDARY_DESTINATION_ALIAS="$(report_value REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS)"
TRANSLATION_MODE="$(report_value REDDIT_VOC_TRANSLATION_MODE)"
ENABLE_DEEPSEEK="$(report_value REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION)"
DINGTALK_MODE="$(report_value REDDIT_VOC_DINGTALK_MODE)"
ENABLE_DINGTALK="$(report_value REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND)"
ENABLE_FAILURE_ALERT="$(report_value REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT)"
WEBHOOK_URL="$(report_value DINGTALK_WEBHOOK_URL)"
WEBHOOK_SECRET="$(report_value DINGTALK_WEBHOOK_SECRET)"
WEBHOOK_URL_2="$(report_value DINGTALK_WEBHOOK_URL_2)"
WEBHOOK_SECRET_2="$(report_value DINGTALK_WEBHOOK_SECRET_2)"

common_names=(
  REDDIT_VOC_DATABASE_PATH
  REDDIT_VOC_RUN_ID
  REDDIT_VOC_REPORT_PUBLIC_ROOT
  REDDIT_VOC_REPORT_PRIVATE_ROOT
  REDDIT_VOC_REPORT_STATE_ROOT
  REDDIT_VOC_CONFIG_ROOT
)
require_env_names "${common_names[@]}"

case "$phase" in
  prepare)
    prepare_action_id=""
    provider_id=""
    authorize_failure_alert=0
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --prepare-action-authorization-id)
          [[ $# -ge 2 ]] || fail "prepare_action_id_missing"
          prepare_action_id="$2"
          shift 2
          ;;
        --provider-authorization-id)
          [[ $# -ge 2 ]] || fail "provider_authorization_id_missing"
          provider_id="$2"
          shift 2
          ;;
        --authorize-failure-alert)
          authorize_failure_alert=1
          shift
          ;;
        *) fail "prepare_argument_invalid" ;;
      esac
    done
    safe_id "$prepare_action_id" || fail "prepare_action_authorization_id_invalid"
    require_env_names \
      REDDIT_VOC_ATTEMPT_ID \
      REDDIT_VOC_ARTIFACT_VERSION_ID \
      REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT \
      REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT \
      REDDIT_VOC_REPORT_BLOCKED_ROOT \
      REDDIT_VOC_REPORT_HANDOFF_ROOT \
      REDDIT_VOC_PROVIDER_ATTEMPT_ROOT \
      REDDIT_VOC_ARTIFACT_BASE_URL \
      DINGTALK_REQUIRED_KEYWORD \
      REDDIT_VOC_DINGTALK_MAX_BYTES \
      REDDIT_VOC_DINGTALK_MAX_PARTS
    safe_id "$RUN_ID" || fail "run_id_invalid"
    safe_id "$ATTEMPT_ID" || fail "attempt_id_invalid"
    version_id "$ARTIFACT_VERSION_ID" || fail "artifact_version_id_invalid"
    prepare_args=(
      -m reddit_voc.cli prepare-daily-report
      --database "$DATABASE_PATH"
      --run-id "$RUN_ID"
      --attempt-id "$ATTEMPT_ID"
      --artifact-version-id "$ARTIFACT_VERSION_ID"
      --public-root "$PUBLIC_ROOT"
      --private-root "$PRIVATE_ROOT"
      --public-staging-root "$PUBLIC_STAGING_ROOT"
      --private-staging-root "$PRIVATE_STAGING_ROOT"
      --state-root "$STATE_ROOT"
      --blocked-root "$BLOCKED_ROOT"
      --handoff-root "$HANDOFF_ROOT"
      --provider-attempt-root "$PROVIDER_ATTEMPT_ROOT"
      --config-root "$CONFIG_ROOT"
      --artifact-base-url "$ARTIFACT_BASE_URL"
      --dingtalk-required-keyword "$REQUIRED_KEYWORD"
      --dingtalk-max-bytes "$DINGTALK_MAX_BYTES"
      --dingtalk-max-parts "$DINGTALK_MAX_PARTS"
      --prepare-action-authorization-id "$prepare_action_id"
      --defer-host-commit
    )
    if [[ "${TRANSLATION_MODE:-dry_run}" == "deepseek" && "${ENABLE_DEEPSEEK:-0}" == "1" ]]; then
      safe_id "$provider_id" || fail "provider_authorization_id_invalid"
      prepare_args+=(--authorize-provider-call --provider-authorization-id "$provider_id")
    elif [[ -n "$provider_id" ]]; then
      fail "provider_authorization_without_live_gates"
    fi
    prepare_webhook_url=""
    prepare_webhook_secret=""
    if [[ "${ENABLE_FAILURE_ALERT:-0}" == "1" && "$authorize_failure_alert" == "1" ]]; then
      prepare_args+=(--authorize-failure-alert)
      prepare_webhook_url="$WEBHOOK_URL"
      prepare_webhook_secret="$WEBHOOK_SECRET"
    elif [[ "$authorize_failure_alert" == "1" ]]; then
      fail "failure_alert_authorization_without_gate"
    fi
    REDDIT_VOC_TRANSLATION_MODE="${TRANSLATION_MODE:-dry_run}" \
    REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION="${ENABLE_DEEPSEEK:-0}" \
    REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT="${ENABLE_FAILURE_ALERT:-0}" \
    DINGTALK_WEBHOOK_URL="$prepare_webhook_url" \
    DINGTALK_WEBHOOK_SECRET="$prepare_webhook_secret" \
    PYTHONPATH="$ROOT/src" \
      "$CLI_PYTHON" "${prepare_args[@]}"
    ;;
  send|send-dual)
    send_command="send-prepared-daily-report"
    if [[ "$phase" == "send-dual" ]]; then
      send_command="send-prepared-daily-report-dual"
    fi
    expected_version=""
    expected_bundle=""
    expected_outbox=""
    authorization_id=""
    authorize_resend=0
    resend_parts=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --expected-artifact-version-id)
          [[ $# -ge 2 ]] || fail "send_tuple_missing"
          expected_version="$2"
          shift 2
          ;;
        --expected-bundle-sha256)
          [[ $# -ge 2 ]] || fail "send_tuple_missing"
          expected_bundle="$2"
          shift 2
          ;;
        --expected-outbox-sha256)
          [[ $# -ge 2 ]] || fail "send_tuple_missing"
          expected_outbox="$2"
          shift 2
          ;;
        --authorization-id)
          [[ $# -ge 2 ]] || fail "send_authorization_id_missing"
          authorization_id="$2"
          shift 2
          ;;
        --authorize-resend)
          authorize_resend=1
          shift
          ;;
        --resend-part-index)
          [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] || fail "resend_part_index_invalid"
          resend_parts+=("$2")
          shift 2
          ;;
        *) fail "send_argument_invalid" ;;
      esac
    done
    version_id "$expected_version" || fail "artifact_version_id_invalid"
    sha256_value "$expected_bundle" || fail "bundle_sha256_invalid"
    sha256_value "$expected_outbox" || fail "outbox_sha256_invalid"
    safe_id "$authorization_id" || fail "authorization_id_invalid"
    [[ "${TRANSLATION_MODE:-dry_run}" == "dry_run" \
        && "${ENABLE_DEEPSEEK:-0}" == "0" \
        && "${ENABLE_FAILURE_ALERT:-0}" == "0" ]] \
      || fail "send_runtime_scope_invalid"
    for forbidden_runtime_name in \
      REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT \
      REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT \
      REDDIT_VOC_REPORT_BLOCKED_ROOT \
      REDDIT_VOC_REPORT_HANDOFF_ROOT \
      REDDIT_VOC_PROVIDER_ATTEMPT_ROOT; do
      [[ -z "$(report_value "$forbidden_runtime_name")" ]] \
        || fail "send_runtime_scope_invalid"
    done
    [[ "${DINGTALK_MODE:-dry_run}" == "live" ]] || fail "dingtalk_mode_not_live"
    [[ "${ENABLE_DINGTALK:-0}" == "1" ]] || fail "dingtalk_live_send_not_enabled"
    [[ -n "$WEBHOOK_URL" ]] || fail "dingtalk_webhook_missing"
    if [[ "$phase" == "send-dual" ]]; then
      safe_id "$CREDENTIAL_SET_EPOCH_ID" \
        || fail "credential_set_epoch_id_invalid"
      [[ "$DESTINATION_SET_ID" == "HighValueAssetDual" ]] \
        || fail "destination_set_id_invalid"
      [[ "$PRIMARY_DESTINATION_ALIAS" == "HighValueAsset" \
          && "$SECONDARY_DESTINATION_ALIAS" == "HighValueAssetSecondary" ]] \
        || fail "destination_alias_invalid"
      [[ -n "$WEBHOOK_URL_2" ]] || fail "dingtalk_secondary_webhook_missing"
      [[ "$WEBHOOK_URL" != "$WEBHOOK_URL_2" ]] \
        || fail "dingtalk_destination_duplicate"
    else
      safe_id "$CREDENTIAL_EPOCH_ID" || fail "credential_epoch_id_invalid"
      [[ "$DESTINATION_ALIAS" == "HighValueAsset" ]] \
        || fail "destination_alias_invalid"
      if [[ -n "$WEBHOOK_URL_2" || -n "$WEBHOOK_SECRET_2" ]]; then
        fail "dingtalk_secondary_not_authorized"
      fi
    fi
    send_args=(
      -m reddit_voc.cli "$send_command"
      --database "$DATABASE_PATH"
      --run-id "$RUN_ID"
      --expected-artifact-version-id "$expected_version"
      --expected-bundle-sha256 "$expected_bundle"
      --expected-outbox-sha256 "$expected_outbox"
      --authorization-id "$authorization_id"
      --public-root "$PUBLIC_ROOT"
      --private-root "$PRIVATE_ROOT"
      --state-root "$STATE_ROOT"
      --config-root "$CONFIG_ROOT"
      --timeout-seconds 10
      --authorize-live-send
    )
    if [[ "$authorize_resend" == "1" ]]; then
      [[ ${#resend_parts[@]} -gt 0 ]] || fail "resend_part_index_required"
      send_args+=(--authorize-resend)
      for part in "${resend_parts[@]}"; do
        send_args+=(--resend-part-index "$part")
      done
    elif [[ ${#resend_parts[@]} -gt 0 ]]; then
      fail "resend_not_authorized"
    fi
    REDDIT_VOC_DINGTALK_MODE=live \
    REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1 \
    PYTHONPATH="$ROOT/src" \
      "$CLI_PYTHON" "${send_args[@]}"
    ;;
  *) fail "phase_invalid" ;;
esac
