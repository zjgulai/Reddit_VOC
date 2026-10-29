#!/usr/bin/env bash
# Echo-Agent Workbench one-command deploy.
# Builds the frontend locally, ships it to 43.163.92.244 via stdin pipes (AppleDouble-safe),
# and syncs into the canonical nginx static root /opt/voc-report/html while
# PRESERVING the pipeline-fed data/ directory in place.
set -euo pipefail

HOST="43.163.92.244"
USER="ubuntu"
KEY="zhoujian_pachong.pem"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/ref/UI/momcozy-reddit-workbench"
REMOTE_ROOT="/opt/voc-report/html"
REMOTE_STAGING="/opt/reddit-voc-workbench-dist"

echo "==> [1/4] Building frontend (tsc + vite)..."
(cd "$LOCAL_DIR" && npm run build >/dev/null)
echo "    build OK: $(ls "$LOCAL_DIR/dist/assets" | wc -l | tr -d ' ') asset files"

echo "==> [2/4] Shipping bundle via stdin pipes..."
ssh -i "$KEY" -o StrictHostKeyChecking=no "$USER@$HOST" "find $REMOTE_STAGING -mindepth 1 -delete && mkdir -p $REMOTE_STAGING"
(cd "$LOCAL_DIR/dist" && tar cf - --exclude='._*' .) | \
  ssh -i "$KEY" -o StrictHostKeyChecking=no "$USER@$HOST" "tar xf - -C $REMOTE_STAGING"
echo "    shipped OK"

echo "==> [3/4] Syncing into canonical root (preserving data/)..."
ssh -i "$KEY" -o StrictHostKeyChecking=no "$USER@$HOST" "
  sudo cp -r $REMOTE_STAGING/assets $REMOTE_ROOT/ && \
  sudo cp $REMOTE_STAGING/favicon.svg $REMOTE_STAGING/icons.svg $REMOTE_STAGING/index.html $REMOTE_STAGING/robots.txt $REMOTE_ROOT/ && \
  sudo cp -rn $REMOTE_STAGING/data/cases $REMOTE_ROOT/data/ 2>/dev/null || true
"
echo "    synced OK"

echo "==> [4/4] Verifying served bundle..."
REMOTE_JS=$(curl -sk "https://$HOST/" -H "Host: reddit.luteos.com" | grep -oE 'index-[A-Za-z0-9_-]+\.js' | head -n 1)
LOCAL_JS=$(ls "$LOCAL_DIR/dist/assets" | grep -E '^index-.*\.js$' | head -n 1)
if [ "$REMOTE_JS" = "$LOCAL_JS" ]; then
  echo "    verified: $REMOTE_JS is live"
else
  echo "    MISMATCH: remote=$REMOTE_JS local=$LOCAL_JS"; exit 1
fi
echo "==> Deploy complete."
