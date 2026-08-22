#!/usr/bin/env python3
"""Perform one explicitly authorised comment first-page probe.

The probe writes only a private raw response artifact.  It does not mutate
the source SQLite, production data, or any delivery channel.
"""

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


ENDPOINT = "/api/v1/reddit/app/fetch_post_comments"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError("comment_repair_probe_redirect_rejected")


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.tikhub.io")
    args = parser.parse_args()
    api_key = os.environ.get("TIKHUB_API_KEY", "")
    if not api_key:
        raise SystemExit("comment_repair_probe_error=missing_tikhub_key")
    plan = json.loads(args.plan.read_bytes())
    if plan.get("schema_version") != "reddit_voc_comment_repair_plan_v1":
        raise SystemExit("comment_repair_probe_error=plan_schema_invalid")
    if int(plan.get("selected_candidate_count", 0)) < 1:
        raise SystemExit("comment_repair_probe_error=no_selected_candidate")
    candidate = plan["candidates"][0]
    post_id = str(candidate["post_id"])
    params = {
        "post_id": f"t3_{post_id}",
        "sort_type": "CONFIDENCE",
        "after": "",
        "need_format": "false",
    }
    query = urlencode(params)
    request = Request(
        args.base_url.rstrip("/") + ENDPOINT + "?" + query,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": os.environ.get(
                "TIKHUB_USER_AGENT",
                "Mozilla/5.0 (compatible; RedditVOC/1.0)",
            ),
        },
        method="GET",
    )
    with build_opener(_NoRedirect).open(request, timeout=30) as response:
        body = response.read()
        http_status = int(response.status)
    payload_bytes = None
    decode_error = None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        payload = None
        decode_error = type(exc).__name__
    if payload is not None:
        payload_bytes = canonical(payload)
    validation_error = None
    parsed = None
    if payload is not None:
        try:
            parsed = parse_comment_repair_payload(payload, expected_post_id=post_id)
        except ValueError as exc:
            validation_error = str(exc)
    result = {
        "schema_version": "reddit_voc_comment_repair_probe_v1",
        "run_id": plan["run_id"],
        "post_id": post_id,
        "endpoint": ENDPOINT,
        "request_params": params,
        "http_status": http_status,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": sha256(payload_bytes or body).hexdigest(),
        "response_validation": "passed" if parsed is not None else "failed",
        "parsed_comment_count": None if parsed is None else parsed["parsed_comment_count"],
        "more_node_count": None if parsed is None else parsed["more_node_count"],
        "more_cursor_count": None if parsed is None else len(parsed["more_cursors"]),
        "reported_comment_count": None if parsed is None else parsed["reported_comment_count"],
        "has_next_page": None if parsed is None else parsed["has_next_page"],
        "validation_error": validation_error or decode_error,
        "payload": payload,
        "provider_attempt_made": True,
        "live_send": False,
        "production_merge": False,
        "git_push": False,
        "dingtalk": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
