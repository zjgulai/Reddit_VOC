#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: remote_configure_insights_edge.sh <http|https> <patch-script>" >&2
  exit 1
fi

MODE="$1"
PATCH_SCRIPT="$2"
DOMAIN="reddit.lute-tlz-dddd.top"
CERT_NAME="reddit.lute-tlz-dddd.top"
SERVER_IP="101.34.52.232"
UPSTREAM="172.20.0.1:18338"
NGINX_CONTAINER="ai_video_nginx"
NGINX_CONF="/opt/ai-video/deploy/lighthouse/nginx.conf"
CRON_FILE="/etc/cron.d/reddit-voc-site"
DEPLOY_ROOT="/opt/reddit-voc-insights-site"
LOCK_FILE="${DEPLOY_ROOT}/.deploy.lock"
COLLECTOR_PUBLIC_URL="https://reddit.brand.lute-tlz-dddd.top/api/health"

if [[ "${MODE}" != "http" && "${MODE}" != "https" ]]; then
  echo "mode must be http or https" >&2
  exit 1
fi
if [[ ! -f "${PATCH_SCRIPT}" || -L "${PATCH_SCRIPT}" ]]; then
  echo "Nginx patch script is missing or is a symlink" >&2
  exit 1
fi

for command in curl docker flock python3 seq sha256sum; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "required command is missing: ${command}" >&2
    exit 1
  fi
done
sudo -n true

assert_safe_window() {
  local hhmm hhmm_number
  hhmm="$(TZ=Asia/Shanghai date +%H%M)"
  hhmm_number=$((10#${hhmm}))
  if (( hhmm_number >= 630 && hhmm_number <= 830 )); then
    echo "edge change blocked during the 06:30-08:30 collection/report window" >&2
    return 1
  fi
}
assert_safe_window

if [[ ! -d "${DEPLOY_ROOT}" || -L "${DEPLOY_ROOT}" ]]; then
  echo "insights deployment root is missing or unsafe" >&2
  exit 1
fi
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "another Reddit VOC insights deployment is already running" >&2
  exit 1
fi

curl -fsS http://172.20.0.1:18338/healthz >/dev/null
curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null
curl -fsS http://127.0.0.1:18337/api/health >/dev/null

collector_id="$(docker inspect -f '{{.Id}}' reddit_voc_site_app)"
collector_restart="$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)"
translation_id="$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)"
translation_restart="$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)"
nginx_id="$(docker inspect -f '{{.Id}}' "${NGINX_CONTAINER}")"
nginx_restart="$(docker inspect -f '{{.RestartCount}}' "${NGINX_CONTAINER}")"
cron_sha="$(sudo sha256sum "${CRON_FILE}" | awk '{print $1}')"
nginx_before_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')"
nginx_before_inode="$(stat -c '%i' "${NGINX_CONF}")"

if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-'; then
  echo "edge change blocked because a collector one-shot container is running" >&2
  exit 1
fi

nginx_conf_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/nginx/nginx.conf"}}{{.Type}}|{{.Source}}{{end}}{{end}}' "${NGINX_CONTAINER}")"
if [[ "${nginx_conf_mount}" != "bind|${NGINX_CONF}" ]]; then
  echo "shared Nginx config is not the expected single-file bind mount" >&2
  exit 1
fi
nginx_container_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
if [[ "${nginx_container_sha}" != "${nginx_before_sha}" ]]; then
  echo "host and container Nginx configuration are not the same bind-mounted content" >&2
  exit 1
fi

if docker exec "${NGINX_CONTAINER}" sh -c 'command -v wget >/dev/null 2>&1'; then
  docker exec "${NGINX_CONTAINER}" wget -q -O /dev/null "http://${UPSTREAM}/healthz"
elif docker exec "${NGINX_CONTAINER}" sh -c 'command -v curl >/dev/null 2>&1'; then
  docker exec "${NGINX_CONTAINER}" curl -fsS "http://${UPSTREAM}/healthz" >/dev/null
else
  echo "shared Nginx container has no HTTP client for upstream reachability proof" >&2
  exit 1
fi

certbot_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/www/certbot"}}{{.Source}}{{end}}{{end}}' "${NGINX_CONTAINER}")"
letsencrypt_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/letsencrypt"}}{{.Source}}{{end}}{{end}}' "${NGINX_CONTAINER}")"
if [[ -z "${certbot_mount}" || -z "${letsencrypt_mount}" || ! -d "${certbot_mount}" || ! -d "${letsencrypt_mount}" ]]; then
  echo "shared Nginx does not expose usable ACME/certificate mounts" >&2
  exit 1
fi

certbot_invoked=false
acme_provider_call=false
dns_system_a=not_checked
dns_public_a=not_checked
dns_system_aaaa=not_checked
dns_public_aaaa=not_checked

assert_dns_contract() {
  dns_system_a="$(dig +short A "${DOMAIN}" | sort -u | paste -sd, -)"
  dns_public_a="$(dig @1.1.1.1 +short A "${DOMAIN}" | sort -u | paste -sd, -)"
  dns_system_aaaa="$(dig +short AAAA "${DOMAIN}" | sort -u | paste -sd, -)"
  dns_public_aaaa="$(dig @1.1.1.1 +short AAAA "${DOMAIN}" | sort -u | paste -sd, -)"
  if [[ "${dns_system_a}" != "${SERVER_IP}" || "${dns_public_a}" != "${SERVER_IP}" ]]; then
    echo "TLS configuration blocked: DNS A records must equal only ${SERVER_IP} (system=${dns_system_a:-empty}, public=${dns_public_a:-empty})" >&2
    return 1
  fi
  if [[ -n "${dns_system_aaaa}" || -n "${dns_public_aaaa}" ]]; then
    echo "TLS configuration blocked: IPv4-only deployment requires empty AAAA records (system=${dns_system_aaaa:-empty}, public=${dns_public_aaaa:-empty})" >&2
    return 1
  fi
}

if [[ "${MODE}" == "https" ]]; then
  for command in certbot dig openssl; do
    if ! command -v "${command}" >/dev/null 2>&1; then
      echo "required TLS command is missing: ${command}" >&2
      exit 1
    fi
  done
  if ! grep -Fq '# BEGIN reddit-voc-insights-site' "${NGINX_CONF}"; then
    echo "HTTPS mode requires the reviewed HTTP edge stage first" >&2
    exit 1
  fi
  assert_dns_contract
  curl -fsS "http://${DOMAIN}/healthz" >/dev/null

  host_cert_dir="${letsencrypt_mount}/live/${CERT_NAME}"
  certificate_needs_issue=false
  if [[ ! -f "${host_cert_dir}/fullchain.pem" || ! -f "${host_cert_dir}/privkey.pem" ]] || ! sudo openssl x509 -checkend 604800 -noout -in "${host_cert_dir}/fullchain.pem" >/dev/null 2>&1; then
    certificate_needs_issue=true
  fi
  if [[ "${certificate_needs_issue}" == "true" ]]; then
    certbot_invoked=true
    acme_provider_call=true
    sudo certbot certonly \
      --webroot \
      --webroot-path "${certbot_mount}" \
      --config-dir "${letsencrypt_mount}" \
      --cert-name "${CERT_NAME}" \
      --non-interactive \
      --agree-tos \
      --no-eff-email \
      -d "${DOMAIN}"
  fi
  sudo test -f "${host_cert_dir}/fullchain.pem"
  sudo test -f "${host_cert_dir}/privkey.pem"
  sudo openssl x509 -checkend 604800 -noout -in "${host_cert_dir}/fullchain.pem"
  if ! sudo openssl x509 -noout -ext subjectAltName -in "${host_cert_dir}/fullchain.pem" | grep -Fq "DNS:${DOMAIN}"; then
    echo "certificate SAN does not include ${DOMAIN}" >&2
    exit 1
  fi
  cert_public_key="$(sudo openssl x509 -pubkey -noout -in "${host_cert_dir}/fullchain.pem" | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
  private_public_key="$(sudo openssl pkey -in "${host_cert_dir}/privkey.pem" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
  if [[ -z "${cert_public_key}" || "${cert_public_key}" != "${private_public_key}" ]]; then
    echo "certificate and private key do not match" >&2
    exit 1
  fi
fi

assert_safe_window
if [[ "${MODE}" == "https" ]]; then
  assert_dns_contract
fi
if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-' || \
   [[ "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" != "${collector_id}" ]] || \
   [[ "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" != "${collector_restart}" ]] || \
   [[ "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" != "${translation_id}" ]] || \
   [[ "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" != "${translation_restart}" ]] || \
   [[ "$(sudo sha256sum "${CRON_FILE}" | awk '{print $1}')" != "${cron_sha}" ]]; then
  echo "production baseline changed before shared Nginx mutation" >&2
  exit 1
fi
docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null
if [[ "$(sha256sum "${NGINX_CONF}" | awk '{print $1}')" != "${nginx_before_sha}" || \
      "$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')" != "${nginx_before_sha}" || \
      "$(docker inspect -f '{{.Id}}' "${NGINX_CONTAINER}")" != "${nginx_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' "${NGINX_CONTAINER}")" != "${nginx_restart}" ]]; then
  echo "shared Nginx baseline changed during edge preflight" >&2
  exit 1
fi

backup_dir="/opt/ai-video-backups/reddit-voc-insights-$(date -u +%Y%m%dT%H%M%SZ)"
sudo mkdir -p "${backup_dir}"
sudo cp "${NGINX_CONF}" "${backup_dir}/nginx.conf"
backup_sha="$(sudo sha256sum "${backup_dir}/nginx.conf" | awk '{print $1}')"
if [[ "${backup_sha}" != "${nginx_before_sha}" ]]; then
  echo "shared Nginx backup checksum mismatch" >&2
  exit 1
fi
edge_succeeded=0

restore_nginx() {
  sudo cp "${backup_dir}/nginx.conf" "${NGINX_CONF}"
  restored_inode="$(stat -c '%i' "${NGINX_CONF}")"
  restored_host_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')"
  restored_container_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
  if [[ "${restored_inode}" != "${nginx_before_inode}" || "${restored_host_sha}" != "${nginx_before_sha}" || "${restored_container_sha}" != "${nginx_before_sha}" ]]; then
    echo "CRITICAL: Nginx rollback content or inode verification failed" >&2
    return 1
  fi
  docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null
  docker exec "${NGINX_CONTAINER}" nginx -s reload
  curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null
  curl -fsS http://127.0.0.1:18337/api/health >/dev/null
}

on_exit() {
  local status="$1"
  trap - EXIT
  set +e
  if [[ "${status}" != "0" && "${edge_succeeded}" != "1" ]]; then
    if ! restore_nginx; then
      echo "CRITICAL: shared Nginx automatic rollback did not complete" >&2
    fi
  fi
  exit "${status}"
}
trap 'on_exit $?' EXIT

sudo python3 "${PATCH_SCRIPT}" \
  --conf "${NGINX_CONF}" \
  --mode "${MODE}" \
  --domain "${DOMAIN}" \
  --cert-name "${CERT_NAME}" \
  --upstream "${UPSTREAM}"

nginx_after_inode="$(stat -c '%i' "${NGINX_CONF}")"
nginx_after_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')"
nginx_container_after_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
if [[ "${nginx_after_inode}" != "${nginx_before_inode}" || "${nginx_after_sha}" != "${nginx_container_after_sha}" ]]; then
  echo "Nginx bind-mounted config did not preserve inode/content identity" >&2
  exit 1
fi

docker exec "${NGINX_CONTAINER}" nginx -t
docker exec "${NGINX_CONTAINER}" nginx -s reload

release_sha="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' reddit_voc_insights_web)"
edge_marker_verified=false
release_http=""
for _ in $(seq 1 30); do
  if [[ "${MODE}" == "http" ]]; then
    if curl -fsS -H "Host: ${DOMAIN}" http://127.0.0.1/healthz >/dev/null 2>&1; then
      release_http="$(curl -fsS -H "Host: ${DOMAIN}" http://127.0.0.1/release.json 2>/dev/null || true)"
    fi
  else
    if curl -fsS "https://${DOMAIN}/healthz" >/dev/null 2>&1; then
      release_http="$(curl -fsS "https://${DOMAIN}/release.json" 2>/dev/null || true)"
    fi
  fi
  observed_release="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["release_sha256"])' "${release_http}" 2>/dev/null || true)"
  if [[ "${observed_release}" == "${release_sha}" ]]; then
    edge_marker_verified=true
    break
  fi
  sleep 1
done
if [[ "${edge_marker_verified}" != "true" ]]; then
  echo "edge release marker mismatch" >&2
  exit 1
fi

curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null
curl -fsS http://127.0.0.1:18337/api/health >/dev/null
if [[ "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" != "${collector_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" != "${collector_restart}" || \
      "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" != "${translation_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" != "${translation_restart}" || \
      "$(docker inspect -f '{{.Id}}' "${NGINX_CONTAINER}")" != "${nginx_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' "${NGINX_CONTAINER}")" != "${nginx_restart}" || \
      "$(sudo sha256sum "${CRON_FILE}" | awk '{print $1}')" != "${cron_sha}" ]]; then
  echo "existing production baseline changed during edge configuration" >&2
  exit 1
fi

evidence_dir="${DEPLOY_ROOT}/evidence"
evidence_file="${evidence_dir}/edge-${MODE}-$(date -u +%Y%m%dT%H%M%SZ)-${release_sha}.txt"
{
  echo "evidence_grade=L4-authorized-live"
  echo "mode=${MODE}"
  echo "domain=${DOMAIN}"
  echo "release_sha=${release_sha}"
  echo "release_marker_verified=true"
  echo "nginx_before_sha=${nginx_before_sha}"
  echo "nginx_after_sha=${nginx_after_sha}"
  echo "nginx_backup_dir=${backup_dir}"
  echo "nginx_backup_sha=${backup_sha}"
  echo "nginx_inode_preserved=true"
  echo "nginx_container_sha_aligned=true"
  echo "nginx_reload=true"
  echo "collector_public_smoke=true"
  echo "collector_id_unchanged=true"
  echo "collector_restart_count=${collector_restart}"
  echo "translation_restart_count=${translation_restart}"
  echo "cron_unchanged=true"
  echo "provider_call=${acme_provider_call}"
  echo "certbot_invoked=${certbot_invoked}"
  echo "acme_provider_call=${acme_provider_call}"
  echo "dns_system_a=${dns_system_a}"
  echo "dns_public_a=${dns_public_a}"
  echo "dns_system_aaaa=${dns_system_aaaa:-absent}"
  echo "dns_public_aaaa=${dns_public_aaaa:-absent}"
  echo "database_write=false"
  echo "live_send=false"
  echo "webhook_send=false"
} > "${evidence_file}"

edge_succeeded=1
trap - EXIT
printf '%s\n' "mode=${MODE}" "release_sha=${release_sha}" "nginx_sha=${nginx_after_sha}" "evidence=${evidence_file}" "backend_health_preserved=true"
