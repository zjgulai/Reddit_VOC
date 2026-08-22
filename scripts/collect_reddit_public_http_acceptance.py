#!/usr/bin/env python3
"""Collect exact read-only public HTTP evidence for one Reddit VOC release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import ssl
import tempfile
from urllib.parse import urlsplit


ROUTES = (
    "/",
    "/dashboard",
    "/dashboard/reports",
    "/dashboard/analytics",
    "/dashboard/insights",
    "/dashboard/search",
    "/dashboard/ugc-showcase",
    "/dashboard/messages",
    "/dashboard/settings",
    "/features",
    "/how-it-works",
    "/faq",
    "/cases",
)


def _get(*, host: str, path: str, context: ssl.SSLContext) -> tuple[int, bytes]:
    connection = http.client.HTTPSConnection(host, timeout=30, context=context)
    try:
        connection.request(
            "GET",
            path,
            headers={"Accept": "application/json,text/plain,text/html;q=0.9"},
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _require_statuses(
    *, host: str, paths: tuple[str, ...], expected: int, context: ssl.SSLContext
) -> list[dict[str, object]]:
    observations = []
    for path in paths:
        status, _ = _get(host=host, path=path, context=context)
        if status != expected:
            raise SystemExit(f"unexpected HTTP status for {path}: {status}, expected {expected}")
        observations.append({"path": path, "status": status})
    return observations


def _write_immutable(path: Path, value: dict[str, object]) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise SystemExit("public HTTP observation immutable collision")
        os.chmod(path, 0o600)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--expected-data-release-id", required=True)
    parser.add_argument("--expected-data-pointer-sha256", required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--insights-version", required=True)
    parser.add_argument("--reports-version", required=True)
    parser.add_argument("--personas-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        len(args.expected_data_pointer_sha256) != 64
        or any(character not in "0123456789abcdef" for character in args.expected_data_pointer_sha256)
    ):
        raise SystemExit("expected data pointer SHA-256 is invalid")

    parsed = urlsplit(args.base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("base URL must be one canonical HTTPS origin")
    host = parsed.hostname
    context = ssl.create_default_context()

    current_release_path = "/data/reddit-voc/current-release.json"
    base_manifest_path = (
        f"/data/reddit-voc/{args.base_version}/manifest-public.json"
    )
    insights_manifest_path = (
        f"/data/reddit-voc/{args.insights_version}/public/manifest.json"
    )
    reports_manifest_path = (
        f"/data/reddit-voc/{args.reports_version}/public/manifest.json"
    )
    personas_manifest_path = (
        f"/data/reddit-voc/{args.personas_version}/manifest.json"
    )
    public_paths = (
        "/release.json",
        current_release_path,
        base_manifest_path,
        insights_manifest_path,
        reports_manifest_path,
        personas_manifest_path,
        "/data/cases/manifest.v1.json",
        "/data/cases/case-index.v1.json",
    )
    forbidden_paths = (
        "/.env",
        "/.env.local",
        "/frontend-source-manifest.json",
        "/candidate-ui-source-validation-receipt.json",
        "/candidate-ui-validation-receipt.json",
        "/release-manifest.json",
        f"/data/reddit-voc/{args.base_version}/manifest.json",
        f"/data/reddit-voc/{args.base_version}/aggregates.json",
        f"/data/reddit-voc/{args.base_version}/posts.json",
        f"/data/reddit-voc/{args.base_version}/comments.json",
        f"/data/reddit-voc/{args.base_version}/quarantine.json",
        f"/data/reddit-voc/{args.base_version}/tag-dictionary.json",
        f"/data/reddit-voc/{args.insights_version}/manifest.json",
        f"/data/reddit-voc/{args.insights_version}/insights.json",
        f"/data/reddit-voc/{args.insights_version}/semantic-audit.json",
        f"/data/reddit-voc/{args.reports_version}/manifest.json",
        f"/data/reddit-voc/{args.reports_version}/report-index.json",
        f"/data/reddit-voc/{args.reports_version}/current/daily.json",
        f"/data/reddit-voc/{args.reports_version}/archive/daily.json",
        f"/data/reddit-voc/{args.personas_version}/imports/private.json",
    )

    health_status, health_body = _get(host=host, path="/healthz", context=context)
    if health_status != 200 or health_body.strip() != b"ok":
        raise SystemExit("public health contract failed")

    release_status, release_body = _get(
        host=host, path="/release.json", context=context
    )
    if release_status != 200:
        raise SystemExit("public release marker failed")
    release_marker = json.loads(release_body)
    if release_marker != {"release_sha256": args.expected_release_sha256}:
        raise SystemExit("public release marker identity mismatch")

    pointer_status, pointer_body = _get(
        host=host, path=current_release_path, context=context
    )
    if pointer_status != 200:
        raise SystemExit("public data release pointer failed")
    data_pointer = json.loads(pointer_body)
    pointer_sha256 = sha256(pointer_body).hexdigest()
    if (
        data_pointer.get("release_id") != args.expected_data_release_id
        or pointer_sha256 != args.expected_data_pointer_sha256
    ):
        raise SystemExit("public data release pointer identity mismatch")

    route_observations = _require_statuses(
        host=host, paths=ROUTES, expected=200, context=context
    )
    public_observations = _require_statuses(
        host=host, paths=public_paths, expected=200, context=context
    )
    security_observations = _require_statuses(
        host=host, paths=forbidden_paths, expected=404, context=context
    )
    if (len(route_observations), len(public_observations), len(security_observations)) != (
        13,
        8,
        20,
    ):
        raise SystemExit("public HTTP exact-count contract failed")

    receipt: dict[str, object] = {
        "schema_version": "reddit_voc_public_http_acceptance_observation_v1",
        "status": "passed_public_http_acceptance",
        "evidence_grade": "L3-public-read-only",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_url": f"https://{host}",
        "expected_release_sha256": args.expected_release_sha256,
        "expected_data_release_id": args.expected_data_release_id,
        "expected_data_pointer_sha256": args.expected_data_pointer_sha256,
        "tls_verified": True,
        "health": {"path": "/healthz", "status": 200, "body": "ok"},
        "release_marker": release_marker,
        "data_pointer": {
            "path": current_release_path,
            "release_id": data_pointer["release_id"],
            "sha256": pointer_sha256,
        },
        "routes": route_observations,
        "public_artifacts": public_observations,
        "security_paths": security_observations,
        "counts": {
            "route_200_count": len(route_observations),
            "public_artifact_200_count": len(public_observations),
            "security_404_count": len(security_observations),
        },
        "remote_write": False,
    }
    _write_immutable(args.output.resolve(), receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
