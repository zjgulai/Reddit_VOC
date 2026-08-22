#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${REDDIT_VOC_ENV_FILE:-/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env}"

print_redacted() {
  if [[ ! -f "$ENV_FILE" ]]; then
    printf 'status=missing env_file=%s\n' "$ENV_FILE"
    return 0
  fi
  printf 'status=present env_file=%s mode=%s\n' "$ENV_FILE" "$(stat -c '%a' "$ENV_FILE" 2>/dev/null || printf 'unknown')"
  grep -E '^(export )?(DINGTALK_WEBHOOK_URL|DINGTALK_REQUIRED_KEYWORD)=' "$ENV_FILE" \
    | sed -E "s#(DINGTALK_WEBHOOK_URL=).*#\\1'***'#; s#(DINGTALK_REQUIRED_KEYWORD=).*#\\1'***'#"
}

if [[ "${1:-}" == "--check" ]]; then
  print_redacted
  exit 0
fi

mkdir -p "$(dirname "$ENV_FILE")"
umask 077
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

backup="${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
cp "$ENV_FILE" "$backup"
chmod 600 "$backup"

printf 'New DingTalk webhook URL: '
IFS= read -rs new_webhook
printf '\n'
printf 'New DingTalk required keyword: '
IFS= read -r new_keyword

if [[ -z "$new_webhook" || -z "$new_keyword" ]]; then
  printf 'status=blocked reason=empty_webhook_or_keyword backup=%s\n' "$backup" >&2
  exit 2
fi

python3 - "$ENV_FILE" "$new_webhook" "$new_keyword" <<'PY'
from __future__ import annotations

import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
new_webhook = sys.argv[2]
new_keyword = sys.argv[3]

replacements = {
    "DINGTALK_WEBHOOK_URL": f"export DINGTALK_WEBHOOK_URL={shlex.quote(new_webhook)}",
    "DINGTALK_REQUIRED_KEYWORD": f"export DINGTALK_REQUIRED_KEYWORD={shlex.quote(new_keyword)}",
}

lines = path.read_text(encoding="utf-8").splitlines()
seen: set[str] = set()
out: list[str] = []
for line in lines:
    stripped = line.strip()
    key = ""
    if stripped.startswith("export ") and "=" in stripped:
        key = stripped.removeprefix("export ").split("=", 1)[0]
    elif "=" in stripped and not stripped.startswith("#"):
        key = stripped.split("=", 1)[0]
    if key in replacements:
        out.append(replacements[key])
        seen.add(key)
    else:
        out.append(line)

for key, value in replacements.items():
    if key not in seen:
        out.append(value)

path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
path.chmod(0o600)
PY

printf 'status=updated env_file=%s backup=%s\n' "$ENV_FILE" "$backup"
print_redacted
