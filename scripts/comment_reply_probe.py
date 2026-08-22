#!/usr/bin/env python3
"""Capture one documented TikHub More-child response, fail-safe."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from reddit_voc.comment_repair import parse_comment_repair_payload

ENDPOINT = "/api/v1/reddit/app/fetch_comment_replies"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError("comment_reply_probe_redirect_rejected")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.tikhub.io")
    args = parser.parse_args()
    api_key = os.environ.get("TIKHUB_API_KEY", "")
    if not api_key:
        raise SystemExit("comment_reply_probe_error=missing_tikhub_key")
    plan = json.loads(args.plan.read_bytes())
    if plan.get("schema_version") != "reddit_voc_comment_reply_plan_v1":
        raise SystemExit("comment_reply_probe_error=plan_schema_invalid")
    post_id = str(plan["post_id"])
    cursor = str(plan["cursor"])
    params = {"post_id": f"t3_{post_id}", "cursor": cursor, "sort_type": "CONFIDENCE", "need_format": "false"}
    request = Request(
        args.base_url.rstrip("/") + ENDPOINT + "?" + urlencode(params),
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": os.environ.get("TIKHUB_USER_AGENT", "Mozilla/5.0 (compatible; RedditVOC/1.0)")},
        method="GET",
    )
    with build_opener(_NoRedirect).open(request, timeout=30) as response:
        body = response.read()
        http_status = int(response.status)
    payload = None
    decode_error = None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        decode_error = type(exc).__name__
    parsed = None
    validation_error = decode_error
    if payload is not None:
        try:
            parsed = parse_comment_repair_payload(payload, expected_post_id=post_id)
            validation_error = None
        except ValueError as exc:
            validation_error = str(exc)
    result = {
        "schema_version": "reddit_voc_comment_reply_probe_v1",
        "run_id": plan["run_id"], "post_id": post_id, "cursor": cursor, "endpoint": ENDPOINT,
        "request_params": params, "http_status": http_status, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": sha256(canonical(payload) if payload is not None else body).hexdigest(),
        "response_validation": "passed" if parsed is not None else "failed",
        "validation_error": validation_error,
        "parsed_comment_count": None if parsed is None else parsed["parsed_comment_count"],
        "more_node_count": None if parsed is None else parsed["more_node_count"],
        "more_cursor_count": None if parsed is None else len(parsed["more_cursors"]),
        "payload": payload,
        "source_first_page_payload_sha256": plan.get("source_first_page_payload_sha256"),
        "provider_attempt_made": True, "live_send": False, "production_merge": False, "git_push": False, "dingtalk": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
