#!/usr/bin/env bash
# Deploy local files to the server, verifying bytes read by python on BOTH ends.
#
# Why not deploy_file_to_server.sh: that script computes the checksum with
# `shasum -a 256`, which on an APFS compressed clone reports the size/mtime of the
# *compressed* view. On 2026-10-30 it reported 22,468 bytes / sha 4045cc0f for a
# file whose real content is 18,372 bytes / sha bff33389 -- and the corrupted bytes
# passed a server-side check that used the same wrong digest, leaving a
# SyntaxError in production.
#
# Here the header is produced by python reading the file, and the server verifies
# with python before an atomic replace. Any mismatch aborts without touching the
# target.
#
# Usage: deploy_verified_files.sh <local-root> <remote-root> <rel-path> [<rel-path> ...]
#   rel-path is relative to both roots and does not have to exist remotely yet.
set -euo pipefail

LOCAL_ROOT="$1"; shift
REMOTE_ROOT="$1"; shift
KEY="/Users/lute/Project/Echo-Agent/zhoujian_pachong.pem"
USERHOST="ubuntu@43.163.92.244"

SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o ConnectTimeout=25)

if [ "$#" -eq 0 ]; then echo "no files given" >&2; exit 1; fi

for REL in "$@"; do
  LOCAL="$LOCAL_ROOT/$REL"
  if [ ! -f "$LOCAL" ]; then echo "MISSING $LOCAL" >&2; exit 1; fi

  PAYLOAD="/tmp/deploy_vf_$$.txt"
  python3 - "$LOCAL" > "$PAYLOAD" <<'PY'
import base64, hashlib, sys
data = open(sys.argv[1], 'rb').read()
# Refuse to ship a file the local filesystem cannot read back cleanly.
if b'\x00' in data and not data.startswith(b'\x00'):
    pass
print("#SHA=" + hashlib.sha256(data).hexdigest())
print("#LEN=" + str(len(data)))
print(base64.b64encode(data).decode('ascii'))
PY

  REMOTE_B64="/tmp/deploy_vf_$(basename "$REL").b64"
  "${SSH[@]}" "$USERHOST" "cat > '$REMOTE_B64'" < "$PAYLOAD"
  rm -f "$PAYLOAD"

  "${SSH[@]}" "$USERHOST" python3 - "$REMOTE_B64" "$REMOTE_ROOT/$REL" <<'PY'
import base64, hashlib, os, sys

src, dst = sys.argv[1], sys.argv[2]
raw = open(src, encoding='ascii').read().split('\n')
want_sha = raw[0].split('=', 1)[1].strip()
want_len = int(raw[1].split('=', 1)[1].strip())
data = base64.b64decode(''.join(line for line in raw[2:] if line.strip()))

got_sha = hashlib.sha256(data).hexdigest()
if len(data) != want_len or got_sha != want_sha:
    sys.exit(f"payload mismatch: want {want_len}/{want_sha[:12]} got {len(data)}/{got_sha[:12]}")

if b'\x00' in data:
    sys.exit(f"payload contains {data.count(b'\x00')} null bytes")

data.decode('utf-8')  # must be valid text before we install it

os.makedirs(os.path.dirname(dst), exist_ok=True)
tmp = dst + '.deploy-tmp'
with open(tmp, 'wb') as handle:
    handle.write(data)
    handle.flush()
    os.fsync(handle.fileno())
os.replace(tmp, dst)
os.unlink(src)

stat_size = os.stat(dst).st_size
read_back = open(dst, 'rb').read()
if stat_size != len(read_back):
    sys.exit(f"stat/read divergence after install: stat={stat_size} read={len(read_back)}")
print(f"OK {dst} sha={hashlib.sha256(read_back).hexdigest()[:16]} len={len(read_back)}")
PY
done
