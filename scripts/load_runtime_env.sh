#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${REDDIT_VOC_ENV_FILE:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi

if [[ ! -f "$REDDIT_VOC_ENV_FILE" ]]; then
  printf 'runtime_env_file_missing=%s\n' "$REDDIT_VOC_ENV_FILE" >&2
  return 2 2>/dev/null || exit 2
fi

case "$REDDIT_VOC_ENV_FILE" in
  "$PWD"|"$PWD"/*)
    printf 'runtime_env_file_inside_project_blocked=%s\n' "$REDDIT_VOC_ENV_FILE" >&2
    return 2 2>/dev/null || exit 2
    ;;
esac

if command -v stat >/dev/null 2>&1; then
  mode="$(stat -f '%Lp' "$REDDIT_VOC_ENV_FILE" 2>/dev/null || stat -c '%a' "$REDDIT_VOC_ENV_FILE" 2>/dev/null || true)"
  if [[ -n "$mode" ]]; then
    # Reject group/other readable or writable files. Decimal modes such as 600 are expected.
    tail="${mode: -2}"
    if [[ "$tail" != "00" ]]; then
      printf 'runtime_env_file_permissions_blocked=%s mode=%s\n' "$REDDIT_VOC_ENV_FILE" "$mode" >&2
      return 2 2>/dev/null || exit 2
    fi
  fi
fi

set -a
# shellcheck source=/dev/null
. "$REDDIT_VOC_ENV_FILE"
set +a
