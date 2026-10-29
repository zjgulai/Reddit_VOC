#!/usr/bin/env bash
# Deploy one local file to the production server with integrity verification.
#
# Why not scp: during the 10-28 deploy, scp produced a binary-garbage file on the
# server whose SHA read back as matching (transcript byte counts are unreliable),
# and production imported garbage. The reliable channel: embed SHA + byte length
# in the payload header, verify both server-side BEFORE writing the target, and
# refuse on any mismatch. The target file is only replaced by an atomic mv.
#
# Usage: deploy_file_to_server.sh <local-path> <remote-path>
set -euo pipefail

LOCAL="$1"
REMOTE="$2"
KEY="/Users/lute/Project/Echo-Agent/zhoujian_pachong.pem"
USERHOST="ubuntu@43.163.92.244"
ssh_base() {
  ssh -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no "$@"
}

SHA=$(shasum -a 256 "$LOCAL" | awk '{print $1}')
LEN=$(wc -c < "$LOCAL" | tr -d ' ')

PAYLOAD="/tmp/deploy_payload_$$.b64"
{
  echo "#SHA=$SHA"
  echo "#LEN=$LEN"
  base64 -i "$LOCAL"
} > "$PAYLOAD"

cleanup() { rm -f "$PAYLOAD"; }
trap cleanup EXIT

ssh_base "$USERHOST" "mkdir -p \"\$(dirname '$REMOTE')\" && cat > '$REMOTE.b64'" < "$PAYLOAD"

ssh_base "$USERHOST" bash -s "$REMOTE.b64" "$REMOTE" <<'REMOTE_SCRIPT'
set -euo pipefail
B64="$1"; TARGET="$2"
HEAD_SHA=$(sed -n '1p' "$B64")
HEAD_LEN=$(sed -n '2p' "$B64")
PAYLOAD_SHA="${HEAD_SHA#\#SHA=}"
PAYLOAD_LEN="${HEAD_LEN#\#LEN=}"
if ! tail -n +3 "$B64" | base64 -d > "$TARGET.tmp"; then
  echo "DECODE FAILED" >&2
  rm -f "$TARGET.tmp"
  exit 2
fi
ACTUAL_LEN=$(wc -c < "$TARGET.tmp" | tr -d ' ')
if [ "$ACTUAL_LEN" != "$PAYLOAD_LEN" ]; then
  echo "LEN MISMATCH: expected=$PAYLOAD_LEN actual=$ACTUAL_LEN" >&2
  rm -f "$TARGET.tmp"
  exit 3
fi
ACTUAL_SHA=$(sha256sum "$TARGET.tmp" | awk '{print $1}')
if [ "$ACTUAL_SHA" != "$PAYLOAD_SHA" ]; then
  echo "SHA MISMATCH: expected=$PAYLOAD_SHA actual=$ACTUAL_SHA" >&2
  rm -f "$TARGET.tmp"
  exit 4
fi
chmod 644 "$TARGET.tmp" 2>/dev/null || true
[ -f "$TARGET" ] && chmod --reference="$TARGET" "$TARGET.tmp" || true
mv -f "$TARGET.tmp" "$TARGET"
echo "OK $TARGET sha=$ACTUAL_SHA len=$ACTUAL_LEN"
REMOTE_SCRIPT
