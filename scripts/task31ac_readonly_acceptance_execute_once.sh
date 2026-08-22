#!/usr/bin/env bash
set -euo pipefail

BASE='/opt/reddit-voc-staging/task28-5b0ff5afc5bac1df7907bcd8fd2fa2a3d335918f97471c378d4d405db194cd63/backfill_momcozy_20250101_20260711'
SOURCE="$BASE/reddit_voc_backfill.sqlite3"
RAW="$BASE/private-raw"
TARGET_ROOT="$BASE/task31y-comment-scope-recovery-20260729"
TARGET="$TARGET_ROOT/reddit_voc_backfill_recovered.sqlite3"
REPORT="$TARGET_ROOT/recovery-report.json"
ROOT="$BASE/task31ac-comments-only-acceptance-20260731"
TASK31='/opt/reddit-voc-staging/task31-comments-schema-recovery-20260727'
TASK31R='/opt/reddit-voc-staging/task31r-comments-schema-recovery-20260727'
TASK31S='/opt/reddit-voc-staging/task31s-comments-schema-recovery-20260727'
TASK31T="$BASE/task31t-comments-schema-recovery-20260727"
TASK31U="$BASE/task31u-comments-only-recovery-20260728"
TASK31W="$BASE/task31w-owner-batch-recovery-20260728"
TASK31X="$BASE/task31x-owner-batch-recovery-20260729"
TASK31AA="$BASE/task31aa-committed-target-acceptance-20260730"
TASK31AB="$BASE/task31ab-comments-only-acceptance-20260730"
VERIFIER="$ROOT/bundle-content/scripts/task31z_committed_target_acceptance.py"
OUTER_BUNDLE="$ROOT/task31ac-bundle.tgz"
OUTER_ADMISSION="$ROOT/task31ac-readonly-admission-receipt.json"
TASK31Y_ADMISSION="$TARGET_ROOT/evidence/remote-readonly-fresh-root-admission-v2-receipt.json"

EXPECTED_SOURCE_SHA256='8baa66135aa58e34c83c7b1d7fd3170adf05f7fdeb342363f3cac13459c29f2f'
EXPECTED_TARGET_SHA256='244bd4096de3ed37c7aa680dff50d2a52c5956ae6d180095cb8aaf7f67022749'
EXPECTED_VERIFIER_SHA256='0bc0825c237d0b7dda056cf3e2c3213647a60f9084264f27f55828f0aac1a4f5'
EXPECTED_TASK31Y_ADMISSION_SHA256='b179c80fa2a2fc068ecfe0b78a48976911759d8b28c3603b4e2d8f5198905d2d'
EXPECTED_TASK31Z_EXECUTION_SHA256='36d76a7dca8aa287a3cee0881069b548b5bd4375aea459d7ff22ae4af58191c7'
EXPECTED_RAW_INVENTORY_SHA256='714000881904b88ef021b709c8b581459d1722132f17c517de151f895afe4caf'
RECOVERED_AT_UTC='2026-07-27T11:42:19+00:00'
RUN_ID='backfill_momcozy_20250101_20260711'

fail_closed() {
  printf 'FAIL_CLOSED:%s\n' "$1" >&2
  exit 70
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

require_sha256() {
  local label="$1"
  local file="$2"
  local expected="$3"
  [ -f "$file" ] && [ ! -L "$file" ] || fail_closed "${label}_not_regular"
  [ "$(sha256_file "$file")" = "$expected" ] || fail_closed "${label}_sha256_mismatch"
  printf 'BINDING_GATE=passed label=%s\n' "$label" >&2
}

find_execution_receipt() {
  local search_root="$1"
  local expected="$2"
  local candidate
  local -a matches=()

  while IFS= read -r -d '' candidate; do
    if [ "$(sha256_file "$candidate")" = "$expected" ]; then
      matches+=("$candidate")
    fi
  done < <(find "$search_root" -xdev -type f -print0)

  [ "${#matches[@]}" -eq 1 ] || fail_closed "task31z_execution_receipt_match_count_${#matches[@]}"
  printf '%s\n' "${matches[0]}"
}

validate_network_none() {
  local net_dev_file="$1"
  local route_file="$2"
  local route_count
  local -a interfaces=()

  while IFS= read -r interface_name; do
    interfaces+=("$interface_name")
  done < <(
    awk -F: 'NR > 2 {
      name=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name != "") print name
    }' "$net_dev_file" | LC_ALL=C sort
  )
  if [ "${#interfaces[@]}" -ne 1 ] || [ "${interfaces[0]}" != 'lo' ]; then
    fail_closed "network_interfaces_invalid_${interfaces[*]:-none}"
  fi

  route_count="$(awk 'NR > 1 { count++ } END { print count + 0 }' "$route_file")"
  [ "$route_count" -eq 0 ] || fail_closed "network_routes_nonzero_${route_count}"
  printf 'NETWORK_NONE_GATE=passed interfaces=lo routes=0\n' >&2
}

readonly_bind() {
  local label="$1"
  local target="$2"
  local options

  mount --bind "$target" "$target" || fail_closed "bind_failed_${label}"
  mount -o remount,bind,ro "$target" || fail_closed "remount_readonly_failed_${label}"
  options="$(findmnt -n -o OPTIONS -T "$target")"
  case ",$options," in
    *,ro,*) ;;
    *) fail_closed "mount_not_readonly_${label}" ;;
  esac
  printf 'READONLY_MOUNT_GATE=passed label=%s\n' "$label" >&2
}

self_test_network_gate() {
  [ "$#" -eq 2 ] || fail_closed 'self_test_network_gate_argument_count'
  validate_network_none "$1" "$2"
}

self_test_receipt_loop() {
  [ "$#" -eq 2 ] || fail_closed 'self_test_receipt_loop_argument_count'
  find_execution_receipt "$1" "$2"
}

namespace_child() {
  [ "${TASK31Z_EXEC_RECEIPT:-}" != '' ] || fail_closed 'task31z_execution_receipt_env_missing'

  mount --make-rprivate / || fail_closed 'make_rprivate_failed'
  readonly_bind source "$SOURCE"
  readonly_bind raw "$RAW"
  readonly_bind target_root "$TARGET_ROOT"
  readonly_bind Task31 "$TASK31"
  readonly_bind Task31R "$TASK31R"
  readonly_bind Task31S "$TASK31S"
  readonly_bind Task31T "$TASK31T"
  readonly_bind Task31U "$TASK31U"
  readonly_bind Task31W "$TASK31W"
  readonly_bind Task31X "$TASK31X"
  readonly_bind Task31AA "$TASK31AA"
  readonly_bind Task31AB "$TASK31AB"
  readonly_bind Task31AC "$ROOT"
  validate_network_none /proc/net/dev /proc/net/route

  exec python3 "$VERIFIER" \
    --source-database "$SOURCE" \
    --raw-archive-dir "$RAW" \
    --target-database "$TARGET" \
    --report "$REPORT" \
    --admission-receipt "$TASK31Y_ADMISSION" \
    --execution-receipt "$TASK31Z_EXEC_RECEIPT" \
    --run-id "$RUN_ID" \
    --recovered-at-utc "$RECOVERED_AT_UTC" \
    --expected-source-sha256 "$EXPECTED_SOURCE_SHA256" \
    --expected-target-sha256 "$EXPECTED_TARGET_SHA256" \
    --expected-admission-sha256 "$EXPECTED_TASK31Y_ADMISSION_SHA256" \
    --expected-execution-sha256 "$EXPECTED_TASK31Z_EXECUTION_SHA256" \
    --expected-raw-inventory-sha256 "$EXPECTED_RAW_INVENTORY_SHA256" \
    --old-root "Task31=$TASK31" \
    --expected-old-root-sha256 'Task31=f11f9491b57a93ba399284310025ff441709aa4c8e59e809347d2d4dd9ef91bb' \
    --old-root "Task31R=$TASK31R" \
    --expected-old-root-sha256 'Task31R=987565f5c9a21e1d7a952983baa6cab143cef9157388ce9de55ea677ebc91a34' \
    --old-root "Task31S=$TASK31S" \
    --expected-old-root-sha256 'Task31S=7b3480bd9521cb5c420e66b4f60f5091b3a9c1ecefdff36b810758b15b2e80cf' \
    --old-root "Task31T=$TASK31T" \
    --expected-old-root-sha256 'Task31T=683faae5e1c5e223b0cc175d9e139ca3ac4fb7c4803907a8b1cb267be9755d4b' \
    --old-root "Task31U=$TASK31U" \
    --expected-old-root-sha256 'Task31U=3fe7386df6dfa446174f5352d8ab4ddf732377f74ec27ff0db31c713c9c4d30f' \
    --old-root "Task31W=$TASK31W" \
    --expected-old-root-sha256 'Task31W=a4e66bbcea8a1e4ee61fe6ea09386113575af9a59bd512f80adba6acb50c7e2a' \
    --old-root "Task31X=$TASK31X" \
    --expected-old-root-sha256 'Task31X=70811b98067355685f753a18311d77333418b5c42b342546813f377cd36e555a'
}

execute_parent() {
  [ "${TASK31AC_BUNDLE_SHA256:-}" != '' ] || fail_closed 'task31ac_bundle_sha256_env_missing'
  [ "${TASK31AC_OUTER_ADMISSION_SHA256:-}" != '' ] || fail_closed 'task31ac_outer_admission_sha256_env_missing'

  require_sha256 source "$SOURCE" "$EXPECTED_SOURCE_SHA256"
  require_sha256 target "$TARGET" "$EXPECTED_TARGET_SHA256"
  require_sha256 verifier "$VERIFIER" "$EXPECTED_VERIFIER_SHA256"
  require_sha256 task31y_admission "$TASK31Y_ADMISSION" "$EXPECTED_TASK31Y_ADMISSION_SHA256"
  require_sha256 task31ac_bundle "$OUTER_BUNDLE" "$TASK31AC_BUNDLE_SHA256"
  require_sha256 task31ac_outer_admission "$OUTER_ADMISSION" "$TASK31AC_OUTER_ADMISSION_SHA256"
  [ ! -e "$REPORT" ] && [ ! -L "$REPORT" ] || fail_closed 'original_recovery_report_present'

  TASK31Z_EXEC_RECEIPT="$(find_execution_receipt "$TASK31AA" "$EXPECTED_TASK31Z_EXECUTION_SHA256")"
  export TASK31Z_EXEC_RECEIPT
  require_sha256 task31z_execution "$TASK31Z_EXEC_RECEIPT" "$EXPECTED_TASK31Z_EXECUTION_SHA256"

  exec unshare -m -n -- bash "$0" --namespace-child
}

case "${1:-}" in
  --self-test-network-gate)
    shift
    self_test_network_gate "$@"
    ;;
  --self-test-receipt-loop)
    shift
    self_test_receipt_loop "$@"
    ;;
  --namespace-child)
    shift
    [ "$#" -eq 0 ] || fail_closed 'namespace_child_argument_count'
    namespace_child
    ;;
  '')
    execute_parent
    ;;
  *)
    fail_closed "unknown_mode_$1"
    ;;
esac
