#!/usr/bin/env bash
set -euo pipefail

POLICY_FILE="${REDDIT_VOC_DAILY_LIVE_POLICY_FILE:-/home/ubuntu/.reddit-voc/report-control/task32aa-daily-live-policy.json}"
ENV_FILE="${REDDIT_VOC_ENV_FILE:-/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env}"

python3 - "$POLICY_FILE" "$ENV_FILE" <<'PY'
import hashlib
import json
import shlex
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


def regular_file(path: Path, label: str) -> bytes:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"{label}_unsafe")
    return path.read_bytes()


policy_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
policy = json.loads(regular_file(policy_path, "policy").decode("utf-8"))
expected_keys = {
    "schema_version",
    "policy_id",
    "cadence",
    "starts_at_utc",
    "expires_at_utc",
    "max_scheduled_runs",
    "destination_fingerprint",
    "required_keyword",
}
if set(policy) != expected_keys or policy.get("schema_version") != "reddit-voc-bounded-daily-live-policy-v1":
    raise SystemExit("daily_live_policy_invalid")
if policy.get("cadence") != "daily" or policy.get("max_scheduled_runs") != 30:
    raise SystemExit("daily_live_policy_scope_invalid")
try:
    starts = datetime.fromisoformat(str(policy["starts_at_utc"]))
    expires = datetime.fromisoformat(str(policy["expires_at_utc"]))
except ValueError as exc:
    raise SystemExit("daily_live_policy_time_invalid") from exc
now = datetime.now(timezone.utc)
if starts.tzinfo is None or expires.tzinfo is None or not starts <= now < expires:
    raise SystemExit("daily_live_policy_inactive")

values: dict[str, str] = {}
for raw in regular_file(env_path, "runtime_env").decode("utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    parsed = shlex.split(value)
    values[key.strip()] = parsed[0] if len(parsed) == 1 else value.strip()
webhook = values.get("DINGTALK_WEBHOOK_URL", "")
checks = {
    "mode": values.get("REDDIT_VOC_DINGTALK_MODE") == "live",
    "enable": values.get("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND") == "1",
    "keyword": values.get("DINGTALK_REQUIRED_KEYWORD") == policy["required_keyword"],
    "destination": hashlib.sha256(webhook.encode("utf-8")).hexdigest()
    == policy["destination_fingerprint"],
}
result = {
    "schema_version": "reddit-voc-bounded-daily-live-admission-v1",
    "policy_id": policy["policy_id"],
    "status": "passed" if all(checks.values()) else "blocked",
    "checks": checks,
    "expires_at_utc": policy["expires_at_utc"],
    "webhook_output": False,
    "external_attempt_made": False,
}
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
if not all(checks.values()):
    raise SystemExit(4)
PY

if [[ "${REDDIT_VOC_POLICY_CHECK_ONLY:-0}" == "1" ]]; then
  exit 0
fi

exec /opt/reddit-voc-site/scripts/server_daily_report.sh
