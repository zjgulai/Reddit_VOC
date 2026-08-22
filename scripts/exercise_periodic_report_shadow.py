#!/usr/bin/env python3
"""Exercise a periodic bundle through the durable sender without network I/O."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from reddit_voc.dingtalk import DingTalkSendResult
from reddit_voc.periodic_report_delivery import exercise_periodic_shadow_delivery
from reddit_voc.report_contracts import canonical_json_bytes


class LocalSyntheticTransport:
    transport_kind = "synthetic"

    def __init__(self) -> None:
        self.call_count = 0

    def __call__(
        self,
        *,
        webhook_url,
        body_bytes,
        secret,
        timeout_seconds,
        request_start_sink,
    ) -> DingTalkSendResult:
        if request_start_sink is not None or secret is not None:
            raise RuntimeError("shadow_transport_boundary_invalid")
        json.loads(body_bytes.decode("utf-8"))
        self.call_count += 1
        return DingTalkSendResult(
            status="sent",
            http_status=200,
            response_hash="sha256:" + "0" * 64,
            response_text="local-shadow-only",
            live_send=False,
            external_attempt_made=False,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--expected-destination-fingerprint", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--authorization-id", required=True)
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
    manifest = json.loads((args.bundle_root / "manifest.json").read_text(encoding="utf-8"))
    poster_sizes = {
        row["poster"]["public_url"]: row["poster"]["bytes"]
        for row in manifest["captures"]
    }

    def local_head(url: str) -> dict[str, object]:
        return {"status": 200, "content_length": poster_sizes.get(url)}

    transport = LocalSyntheticTransport()
    summary = exercise_periodic_shadow_delivery(
        bundle_root=args.bundle_root,
        expected_release_id=args.expected_release_id,
        expected_destination_fingerprint=args.expected_destination_fingerprint,
        expected_manifest_sha256=args.expected_manifest_sha256,
        state_root=args.state_root,
        authorization_id=args.authorization_id,
        authorize_shadow_delivery=True,
        head_checker=local_head,
        transport=transport,
    )
    receipt = {
        "schema_version": "reddit-voc-periodic-shadow-exercise-receipt-v1",
        "status": "passed_local_shadow_exercise" if summary.status == "sent" else "blocked",
        "bundle_manifest_sha256": args.expected_manifest_sha256,
        "data_release_id": args.expected_release_id,
        "destination_fingerprint": args.expected_destination_fingerprint,
        "summary": summary.as_dict(),
        "synthetic_transport_call_count": transport.call_count,
        "boundaries": {
            "production_unchanged": True,
            "deploy": False,
            "remote_write": False,
            "schedule_change": False,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "webhook_send": False,
        },
    }
    write_new(args.receipt, canonical_json_bytes(receipt))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if summary.status == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
