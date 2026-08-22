#!/usr/bin/env python3
"""HEAD-check a public periodic projection without sending any message."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from reddit_voc.report_contracts import canonical_json_bytes, sha256_hex


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--expected-public-manifest-sha256", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--allow-local-http", action="store_true")
    return parser.parse_args()


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/") + "/"
    parsed = urlsplit(base)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if not (
        parsed.scheme == "https"
        or (args.allow_local_http and local_http)
    ) or not parsed.netloc or parsed.username or parsed.password:
        raise SystemExit("publication_preflight_base_url_invalid")
    manifest_payload = args.public_manifest.read_bytes()
    if sha256_hex(manifest_payload) != args.expected_public_manifest_sha256:
        raise SystemExit("publication_preflight_manifest_sha256_mismatch")
    manifest = json.loads(manifest_payload.decode("utf-8"))
    if (
        manifest.get("schema_version")
        != "reddit-voc-periodic-report-public-manifest-v1"
        or manifest.get("data_release_id") != args.expected_release_id
        or not isinstance(manifest.get("assets"), list)
        or len(manifest["assets"]) != 3
    ):
        raise SystemExit("publication_preflight_manifest_contract_invalid")
    bundle_id = manifest["bundle_id"]
    manifest_relative = f"periodic-report-assets/{bundle_id}/manifest.json"
    checks = [
        {
            "role": "manifest",
            "grain": None,
            "url": urljoin(base, manifest_relative),
            "expected_bytes": len(manifest_payload),
        }
    ]
    for asset in manifest["assets"]:
        checks.append(
            {
                "role": "poster",
                "grain": asset["grain"],
                "url": urljoin(base, asset["relative_path"]),
                "expected_bytes": asset["bytes"],
            }
        )
    opener = build_opener(NoRedirect())
    observed = []
    for check in checks:
        request = Request(check["url"], method="HEAD", headers={"User-Agent": "reddit-voc-periodic-preflight/1"})
        try:
            with opener.open(request, timeout=10) as response:
                status = int(response.status)
                length_value = response.headers.get("Content-Length")
        except HTTPError as exc:
            raise SystemExit(f"publication_preflight_head_failed:{check['role']}:{exc.code}") from exc
        except (URLError, OSError) as exc:
            raise SystemExit(f"publication_preflight_head_failed:{check['role']}") from exc
        length = int(length_value) if length_value is not None else None
        if status != 200 or length != check["expected_bytes"]:
            raise SystemExit(f"publication_preflight_head_contract_mismatch:{check['role']}:{check['grain']}")
        observed.append({**check, "status": status, "content_length": length})
    receipt = {
        "schema_version": "reddit-voc-periodic-report-public-head-receipt-v1",
        "status": "passed_local_head" if local_http else "passed_public_https_head",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base.rstrip("/"),
        "data_release_id": args.expected_release_id,
        "public_manifest_sha256": args.expected_public_manifest_sha256,
        "checks": observed,
        "boundaries": {
            "read_only_head": True,
            "production_write": False,
            "remote_write": False,
            "schedule_change": False,
            "database_write": False,
            "live_send": False,
            "webhook_send": False,
        },
    }
    write_new(args.receipt, canonical_json_bytes(receipt))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
