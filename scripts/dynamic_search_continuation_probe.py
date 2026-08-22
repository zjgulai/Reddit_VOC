#!/usr/bin/env python3
"""Capture one bounded continuation page for a V2 dynamic-search lane."""

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
        raise RuntimeError("dynamic_search_continuation_probe_redirect_rejected")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def _page_info(payload: object) -> dict[str, object] | None:
    matches = []
    for node in _walk(payload):
        if isinstance(node, dict) and isinstance(node.get("pageInfo"), dict):
            matches.append(node["pageInfo"])
    if len(matches) != 1:
        return None
    page = matches[0]
    if not isinstance(page.get("endCursor"), (str, type(None))) or not isinstance(page.get("hasNextPage"), bool):
        return None
    return page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.tikhub.io")
    args = parser.parse_args()
    api_key = os.environ.get("TIKHUB_API_KEY", "")
    if not api_key:
        raise SystemExit("dynamic_search_continuation_probe_error=missing_tikhub_key")
    plan = json.loads(args.plan.read_bytes())
    if plan.get("schema_version") != "reddit_voc_search_continuation_plan_v1":
        raise SystemExit("dynamic_search_continuation_probe_error=plan_schema_invalid")
    cursor = str(plan["after_cursor"])
    params = {
        "query": str(plan["term"]),
        "search_type": "post",
        "sort": "NEW",
        "time_range": "all",
        "after": cursor,
        "need_format": "false",
    }
    request = Request(
        args.base_url.rstrip("/") + ENDPOINT + "?" + urlencode(params),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": os.environ.get("TIKHUB_USER_AGENT", "Mozilla/5.0 (compatible; RedditVOC/1.0)"),
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
    page = _page_info(payload) if payload is not None else None
    post_ids = []
    if payload is not None:
        for node in _walk(payload):
            post_id = _post_id(node)
            if post_id and (post_id.startswith("1") or post_id.startswith("t3_")):
                post_ids.append(post_id)
    unique_ids = list(dict.fromkeys(post_ids))
    result = {
        "schema_version": "reddit_voc_search_continuation_probe_v1",
        "run_id": plan["run_id"],
        "lane_index": plan["lane_index"],
        "term": plan["term"],
        "endpoint": ENDPOINT,
        "request_params": {k: ("<cursor>" if k == "after" else v) for k, v in params.items()},
        "continuation_depth": plan["continuation_depth"],
        "source_previous_page_payload_sha256": plan["source_previous_page_payload_sha256"],
        "after_cursor_sha256": plan["after_cursor_sha256"],
        "http_status": http_status,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": sha256(canonical(payload) if payload is not None else body).hexdigest(),
        "response_validation": "passed" if payload is not None and page is not None else "failed",
        "validation_error": decode_error if payload is None else ("page_info_shape_invalid" if page is None else None),
        "parsed_post_count": len(post_ids),
        "unique_post_count": len(unique_ids),
        "post_ids": unique_ids,
        "has_next_page": page.get("hasNextPage") if page else None,
        "end_cursor_present": bool(page and page.get("endCursor")),
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
