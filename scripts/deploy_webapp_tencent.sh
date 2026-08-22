#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_KEY="${SSH_KEY:-${PROJECT_ROOT}/ai_video.pem}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
REMOTE_DIR="${REMOTE_DIR:-/opt/reddit-voc-site}"
DOMAIN="${DOMAIN:-reddit.brand.lute-tlz-dddd.top}"
TLS_CERT_NAME="${TLS_CERT_NAME:-${DOMAIN}}"
LOCAL_PORT="${LOCAL_PORT:-18337}"
NGINX_CONTAINER="${NGINX_CONTAINER:-ai_video_nginx}"
NGINX_CONF="${NGINX_CONF:-/opt/ai-video/deploy/lighthouse/nginx.conf}"
NETWORK_NAME="${NETWORK_NAME:-lighthouse_ai_video_net}"
DEPLOY_TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="/tmp/reddit-voc-site-${DEPLOY_TS}.tgz"

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "SSH key not found: ${SSH_KEY}" >&2
  exit 1
fi

chmod 600 "${SSH_KEY}"

cd "${PROJECT_ROOT}"
COPYFILE_DISABLE=1 tar \
  --exclude='./ai_video.pem' \
  --exclude='./*.pem' \
  --exclude='._*' \
  --exclude='*/._*' \
  --exclude='./.env' \
  --exclude='./logs' \
  --exclude='./tmp' \
  --exclude='./.git' \
  --exclude='./.codegraph' \
  --exclude='./.codex' \
  --exclude='./.kiro' \
  -czf "${ARCHIVE}" \
  webapp src scripts config docs .env.example README.md pyproject.toml .dockerignore

scp -i "${SSH_KEY}" -o StrictHostKeyChecking=accept-new "${ARCHIVE}" "${REMOTE}:/tmp/$(basename "${ARCHIVE}")"

ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=accept-new "${REMOTE}" \
  "REMOTE_DIR='${REMOTE_DIR}' ARCHIVE='/tmp/$(basename "${ARCHIVE}")' DOMAIN='${DOMAIN}' TLS_CERT_NAME='${TLS_CERT_NAME}' LOCAL_PORT='${LOCAL_PORT}' NGINX_CONTAINER='${NGINX_CONTAINER}' NGINX_CONF='${NGINX_CONF}' NETWORK_NAME='${NETWORK_NAME}' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

sudo mkdir -p "${REMOTE_DIR}"
sudo chown "$(id -un):$(id -gn)" "${REMOTE_DIR}"
rm -rf \
  "${REMOTE_DIR}/webapp" \
  "${REMOTE_DIR}/src" \
  "${REMOTE_DIR}/scripts" \
  "${REMOTE_DIR}/config" \
  "${REMOTE_DIR}/docs" \
  "${REMOTE_DIR}/.env.example" \
  "${REMOTE_DIR}/README.md" \
  "${REMOTE_DIR}/pyproject.toml" \
  "${REMOTE_DIR}/.dockerignore"
tar -xzf "${ARCHIVE}" -C "${REMOTE_DIR}"
find "${REMOTE_DIR}" -name '._*' -delete
    chmod +x "${REMOTE_DIR}/scripts/server_daily_collect.sh" "${REMOTE_DIR}/scripts/server_daily_report.sh" "${REMOTE_DIR}/scripts/server_daily_cycle.sh"
mkdir -p "${REMOTE_DIR}/data" "${REMOTE_DIR}/outputs" "${REMOTE_DIR}/logs"
cd "${REMOTE_DIR}"

docker network inspect "${NETWORK_NAME}" >/dev/null
docker compose -p reddit_voc_site -f webapp/docker-compose.yml build
docker compose -p reddit_voc_site -f webapp/docker-compose.yml up -d
docker compose -p reddit_voc_translation -f webapp/docker-compose.translation.yml up -d
health_ok=0
for attempt in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${LOCAL_PORT}/api/health" >/tmp/reddit-voc-site-health.json; then
    health_ok=1
    break
  fi
  sleep 1
done
if [[ "${health_ok}" != "1" ]]; then
  docker logs --tail 120 reddit_voc_site_app >&2 || true
  exit 1
fi

BACKUP_DIR="/opt/ai-video-backups/reddit-voc-site-$(date +%Y%m%d-%H%M%S)"
sudo mkdir -p "${BACKUP_DIR}"
sudo cp "${NGINX_CONF}" "${BACKUP_DIR}/nginx.conf"

if ! sudo test -f "/etc/letsencrypt/live/${TLS_CERT_NAME}/fullchain.pem"; then
  sudo certbot certonly \
    --webroot \
    -w /var/www/certbot \
    --cert-name "${TLS_CERT_NAME}" \
    --non-interactive \
    --agree-tos \
    --no-eff-email \
    --register-unsafely-without-email \
    -d "${DOMAIN}"
fi

sudo env NGINX_CONF="${NGINX_CONF}" DOMAIN="${DOMAIN}" TLS_CERT_NAME="${TLS_CERT_NAME}" python3 - <<'PY'
from pathlib import Path
import os

conf_path = Path(os.environ["NGINX_CONF"])
domain = os.environ["DOMAIN"]
tls_cert_name = os.environ["TLS_CERT_NAME"]
marker_start = "# BEGIN reddit-voc-site"
marker_end = "# END reddit-voc-site"
block = f"""
    {marker_start}
    upstream reddit_voc_site_app_upstream {{
        server reddit_voc_site_app:8080;
    }}

    server {{
        listen 80;
        server_name {domain};

        location /.well-known/acme-challenge/ {{
            root /var/www/certbot;
            default_type "text/plain";
            try_files $uri =404;
        }}

        location / {{
            return 301 https://$host$request_uri;
        }}
    }}

    server {{
        listen 443 ssl;
        http2 on;
        server_name {domain};

        ssl_certificate /etc/letsencrypt/live/{tls_cert_name}/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/{tls_cert_name}/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        location /artifacts/ {{
            auth_request off;
            auth_basic off;
            proxy_pass http://reddit_voc_site_app_upstream;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }}

        location / {{
            proxy_pass http://reddit_voc_site_app_upstream;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }}
    }}
    {marker_end}
"""
text = conf_path.read_text()
if marker_start in text and marker_end in text:
    before, rest = text.split(marker_start, 1)
    _, after = rest.split(marker_end, 1)
    text = before + block.strip("\n") + after
else:
    insert_at = text.rfind("\n}")
    if insert_at == -1:
        raise SystemExit("nginx.conf does not look like a single http{} config")
    text = text[:insert_at] + "\n" + block.rstrip() + text[insert_at:]
conf_path.write_text(text)
PY

docker exec "${NGINX_CONTAINER}" nginx -t
docker exec "${NGINX_CONTAINER}" nginx -s reload
curl -fsS "http://127.0.0.1:${LOCAL_PORT}/api/health"

sudo tee /etc/cron.d/reddit-voc-site >/dev/null <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=Asia/Shanghai
0 7 * * * ubuntu ${REMOTE_DIR}/scripts/server_daily_collect.sh >> ${REMOTE_DIR}/logs/cron-collect.log 2>&1
0 8 * * * ubuntu ${REMOTE_DIR}/scripts/server_daily_report.sh >> ${REMOTE_DIR}/logs/cron-report.log 2>&1
EOF
sudo chmod 0644 /etc/cron.d/reddit-voc-site
sudo systemctl reload cron 2>/dev/null || sudo service cron reload 2>/dev/null || true
REMOTE_SCRIPT

rm -f "${ARCHIVE}"
