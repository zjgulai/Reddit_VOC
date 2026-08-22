#!/usr/bin/env python3
import argparse
import ipaddress
import os
from pathlib import Path
import re


MARKER_START = "# BEGIN reddit-voc-insights-site"
MARKER_END = "# END reddit-voc-insights-site"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conf", required=True)
    parser.add_argument("--mode", required=True, choices=("http", "https", "remove"))
    parser.add_argument("--domain", default="reddit.lute-tlz-dddd.top")
    parser.add_argument("--cert-name", default="reddit.lute-tlz-dddd.top")
    parser.add_argument("--upstream", default="172.20.0.1:18338")
    return parser.parse_args()


def validate_inputs(domain: str, cert_name: str, upstream: str) -> None:
    domain_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
    if not domain_pattern.fullmatch(domain) or not domain_pattern.fullmatch(cert_name):
        raise SystemExit("invalid domain or certificate name")
    host, separator, port_text = upstream.rpartition(":")
    if not separator:
        raise SystemExit("upstream must use IP:port")
    ipaddress.ip_address(host)
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise SystemExit("invalid upstream port")


def without_managed_block(text: str) -> str:
    has_start = MARKER_START in text
    has_end = MARKER_END in text
    if has_start != has_end:
        raise SystemExit("managed Nginx marker is incomplete")
    if not has_start:
        return text
    before, rest = text.split(MARKER_START, 1)
    _, after = rest.split(MARKER_END, 1)
    return f"{before.rstrip()}\n{after.lstrip()}"


def proxy_location(upstream: str) -> str:
    return f"""        location / {{
            proxy_pass http://{upstream};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Connection \"\";
            proxy_connect_timeout 5s;
            proxy_read_timeout 60s;
        }}"""


def build_block(mode: str, domain: str, cert_name: str, upstream: str) -> str:
    http_default = proxy_location(upstream) if mode == "http" else """        location / {
            return 301 https://$host$request_uri;
        }"""
    http_server = f"""    server {{
        listen 80;
        server_name {domain};

        location /.well-known/acme-challenge/ {{
            root /var/www/certbot;
            default_type text/plain;
            try_files $uri =404;
        }}

{http_default}
    }}"""
    if mode == "http":
        return f"    {MARKER_START}\n{http_server}\n    {MARKER_END}"

    https_server = f"""    server {{
        listen 443 ssl;
        http2 on;
        server_name {domain};

        ssl_certificate /etc/letsencrypt/live/{cert_name}/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/{cert_name}/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        add_header Strict-Transport-Security \"max-age=31536000\" always;

{proxy_location(upstream)}
    }}"""
    return f"    {MARKER_START}\n{http_server}\n\n{https_server}\n    {MARKER_END}"


def insert_before_final_brace(text: str, block: str) -> str:
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise SystemExit("Nginx config does not end with an http-context brace")
    insert_at = stripped.rfind("}")
    return f"{stripped[:insert_at].rstrip()}\n\n{block}\n{stripped[insert_at:]}\n"


def in_place_write(path: Path, text: str) -> None:
    """Preserve the inode so a container's single-file bind mount sees the update."""
    original_inode = path.stat().st_ino
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    if path.stat().st_ino != original_inode:
        raise SystemExit("Nginx config inode changed during in-place write")


def main() -> None:
    args = parse_args()
    validate_inputs(args.domain, args.cert_name, args.upstream)
    path = Path(args.conf)
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Nginx config must be a regular non-symlink file")
    original = path.read_text(encoding="utf-8")
    unmanaged = without_managed_block(original)
    if re.search(rf"\bserver_name\s+{re.escape(args.domain)}\s*;", unmanaged):
        raise SystemExit("domain already exists outside the managed block")
    updated = unmanaged if args.mode == "remove" else insert_before_final_brace(
        unmanaged,
        build_block(args.mode, args.domain, args.cert_name, args.upstream),
    )
    in_place_write(path, updated)


if __name__ == "__main__":
    main()
