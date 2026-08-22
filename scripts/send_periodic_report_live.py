#!/usr/bin/env python3
"""Send exactly one authorization-bound periodic report canary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from reddit_voc.dingtalk import send_payload_bytes
from reddit_voc.periodic_report_delivery import send_periodic_live_canary


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_authorization(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("periodic_live_authorization_file_invalid")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("periodic_live_authorization_file_invalid")
    return value


def head_checker(timeout_seconds: int):
    opener = build_opener(NoRedirect())

    def check(url: str) -> dict[str, object]:
        request = Request(url, method="HEAD")
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", None)
                raw_length = response.headers.get("Content-Length")
        except HTTPError as exc:
            return {"status": exc.code, "content_length": None}
        return {
            "status": status,
            "content_length": int(raw_length) if raw_length is not None else None,
        }

    return check


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--bundle-root", required=True, type=Path)
    result.add_argument("--state-root", required=True, type=Path)
    result.add_argument("--authorization-contract", required=True, type=Path)
    result.add_argument("--expected-release-id", required=True)
    result.add_argument("--expected-destination-fingerprint", required=True)
    result.add_argument("--expected-manifest-sha256", required=True)
    result.add_argument("--expected-outbox-sha256", required=True)
    result.add_argument("--grain", required=True, choices=("daily", "weekly", "monthly"))
    result.add_argument("--group-alias", required=True)
    result.add_argument("--authorize-live-send", action="store_true")
    result.add_argument("--timeout-seconds", type=int, default=10)
    return result


def main() -> int:
    args = parser().parse_args()
    authorization = load_authorization(args.authorization_contract)
    summary = send_periodic_live_canary(
        bundle_root=args.bundle_root,
        expected_release_id=args.expected_release_id,
        expected_destination_fingerprint=args.expected_destination_fingerprint,
        expected_manifest_sha256=args.expected_manifest_sha256,
        expected_outbox_sha256=args.expected_outbox_sha256,
        expected_grain=args.grain,
        expected_group_alias=args.group_alias,
        required_keyword=os.environ.get("DINGTALK_REQUIRED_KEYWORD", ""),
        state_root=args.state_root,
        authorization=authorization,
        authorize_live_send=args.authorize_live_send,
        dingtalk_mode=os.environ.get("REDDIT_VOC_DINGTALK_MODE", "dry_run"),
        enable_live_send=os.environ.get("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND", "0"),
        webhook_url=os.environ.get("DINGTALK_WEBHOOK_URL", ""),
        webhook_secret=os.environ.get("DINGTALK_WEBHOOK_SECRET") or None,
        timeout_seconds=args.timeout_seconds,
        head_checker=head_checker(args.timeout_seconds),
        transport=send_payload_bytes,
    )
    receipt = {
        "schema_version": "reddit-voc-periodic-live-canary-execution-v1",
        "authorization_id": authorization.get("authorization_id"),
        "release_id": args.expected_release_id,
        "destination_fingerprint": args.expected_destination_fingerprint,
        "bundle_manifest_sha256": args.expected_manifest_sha256,
        "outbox_sha256": args.expected_outbox_sha256,
        "summary": summary.as_dict(),
        "boundaries": {
            "provider_call": False,
            "database_write": False,
            "schedule_change": False,
            "cron_enable": False,
            "webhook_value_output": False,
            "live_send": summary.live_send,
        },
    }
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if summary.status == "sent" and summary.live_send else 1


if __name__ == "__main__":
    raise SystemExit(main())
