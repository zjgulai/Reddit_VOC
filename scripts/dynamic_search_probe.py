#!/usr/bin/env python3
"""Capture one exact V2 dynamic-search lane response.

The probe performs one GET request, preserves the raw JSON in isolated
staging, and emits only deterministic lane/post accounting alongside it.
It never writes SQLite, production data, or delivery channels.
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


ENDPOINT = "/api/v1/reddit/app/fetch_dynamic_search"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError("dynamic_search_probe_redirect_rejected")


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _post_id(node: dict[str, object]) -> str | None:
    for key in ("id", "post_id", "name"):
        value = node.get(key)
        if isinstance(value, str) and value:
            value = value.removeprefix("t3_")
            if key == "name" and not value.startswith("t3_"):
                continue
            return value
    return None


def _created_at(node: dict[str, object]) -> str | None:
    for key in ("created_at", "created_at_utc", "created_utc", "timestamp"):
        value = node.get(key)
        if isinstance(value, (str, int, float)):
            return str(value)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.tikhub.io")
    args = parser.parse_args()
    api_key = os.environ.get("TIKHUB_API_KEY", "")
    if not api_key:
        raise SystemExit("dynamic_search_probe_error=missing_tikhub_key")
    plan = json.loads(args.plan.read_bytes())
    if plan.get("schema_version") != "reddit_voc_search_lane_plan_v1":
        raise SystemExit("dynamic_search_probe_error=plan_schema_invalid")
    term = str(plan["term"])
    params = {"query": term, "sort": "new", "limit": 100}
    request = Request(
        args.base_url.rstrip("/") + ENDPOINT + "?" + urlencode(params),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": os.environ.get(
                "TIKHUB_USER_AGENT", "Mozilla/5.0 (compatible; RedditVOC/1.0)"
            ),
        },
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
    nodes = list(_walk(payload)) if payload is not None else []
    post_ids = []
    created = []
    for node in nodes:
        post_id = _post_id(node)
        if post_id and (post_id.startswith("1") or post_id.startswith("t3_")):
            post_ids.append(post_id)
            timestamp = _created_at(node)
            if timestamp is not None:
                created.append(timestamp)
    unique_ids = list(dict.fromkeys(post_ids))
    result = {
        "schema_version": "reddit_voc_search_lane_probe_v1",
        "run_id": plan["run_id"],
        "lane_index": plan["lane_index"],
        "term": term,
        "endpoint": ENDPOINT,
        "request_params": params,
        "http_status": http_status,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": sha256(canonical(payload) if payload is not None else body).hexdigest(),
        "response_validation": "passed" if payload is not None else "failed",
        "validation_error": decode_error,
        "parsed_post_count": len(post_ids),
        "unique_post_count": len(unique_ids),
        "post_ids": unique_ids,
        "created_at_values": created,
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
