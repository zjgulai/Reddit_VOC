from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Callable, Mapping
from urllib.parse import urlencode, urlsplit

from .report_contracts import canonical_json_bytes, sha256_hex


SCHEMA_VERSION = "reddit-voc-periodic-report-bundle-v1"
PREFLIGHT_SCHEMA_VERSION = "reddit-voc-periodic-report-preflight-v1"
PERIODS = ("daily", "weekly", "monthly")
PERIOD_LABELS = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
PERIOD_DIMENSIONS = {
    "daily": (1440, 1800),
    "weekly": (1440, 2000),
    "monthly": (1440, 2200),
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_RELEASE_RE = re.compile(r"^reddit_voc_release_[A-Za-z0-9._-]+$")
SOURCE_FRESHNESS = {"complete", "full", "partial", "empty_success", "no_change"}


class PeriodicBundleError(ValueError):
    """A periodic report bundle invariant failed."""


def _regular_file(path: Path, *, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise PeriodicBundleError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PeriodicBundleError(f"{label}_unsafe")
    return metadata


def _load_json(path: Path, *, label: str, canonical: bool = False) -> Mapping[str, object]:
    _regular_file(path, label=label)
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PeriodicBundleError(f"{label}_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise PeriodicBundleError(f"{label}_object_invalid")
    canonical_payload = canonical_json_bytes(value)
    if canonical and payload not in {canonical_payload, canonical_payload + b"\n"}:
        raise PeriodicBundleError(f"{label}_noncanonical")
    return value


def _https_url(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\t"):
        raise PeriodicBundleError(f"{label}_invalid")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PeriodicBundleError(f"{label}_invalid")
    if parsed.fragment:
        raise PeriodicBundleError(f"{label}_invalid")
    return value.rstrip("/")


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise PeriodicBundleError(f"{label}_invalid")
    return value


def _coverage_message(status: str) -> str:
    if status == "partial":
        return "数据源存在明确的部分分页覆盖；报告历史完整性按数据所有者确认100%执行，两者不可混同。"
    if status == "empty_success":
        return "本周期采集成功但没有净新增，继续展示最近完整闭合期，不伪造新增数据。"
    if status == "no_change":
        return "本周期数据版本未变化；相同周期与版本由幂等键阻止重复发送。"
    return "本周期数据源闭合，报告按已校验口径生成。"


def _poster_rows(manifest_path: Path) -> tuple[Mapping[str, object], ...]:
    manifest = _load_json(manifest_path, label="poster_manifest", canonical=True)
    golden = manifest.get("golden_evaluation")
    if (
        manifest.get("schema_version") != "reddit_voc_periodic_report_poster_bundle_v1"
        or manifest.get("status") != "passed_local_poster_capture"
        or not isinstance(manifest.get("captures"), list)
        or not isinstance(golden, Mapping)
        or golden.get("status") != "passed_exact_pixel_baseline"
        or golden.get("manual_visual_review_required") is not False
    ):
        raise PeriodicBundleError("poster_manifest_contract_invalid")
    captures = manifest["captures"]
    if len(captures) != 3 or {
        row.get("period") for row in captures if isinstance(row, Mapping)
    } != set(PERIODS):
        raise PeriodicBundleError("poster_capture_set_invalid")
    rows: list[Mapping[str, object]] = []
    for period in PERIODS:
        raw = next(
            row for row in captures
            if isinstance(row, Mapping) and row.get("period") == period
        )
        width, height = PERIOD_DIMENSIONS[period]
        filename = raw.get("file")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or raw.get("width") != width
            or raw.get("height") != height
            or raw.get("coverage_percent") != 100
            or not isinstance(raw.get("bytes"), int)
            or isinstance(raw.get("bytes"), bool)
            or int(raw["bytes"]) < 100_000
            or not isinstance(raw.get("period_id"), str)
            or not raw.get("period_id")
            or not isinstance(raw.get("data_as_of"), str)
            or raw.get("source_freshness_status") not in SOURCE_FRESHNESS
        ):
            raise PeriodicBundleError(f"poster_{period}_contract_invalid")
        _sha(raw.get("sha256"), label=f"poster_{period}_sha256")
        rows.append(raw)
    return tuple(rows)


def build_periodic_report_bundle(
    *,
    poster_manifest_path: Path,
    output_root: Path,
    artifact_base_url: str,
    dashboard_base_url: str,
    destination_fingerprint: str,
    expected_release_id: str,
    expected_dataset_version: str,
    required_keyword: str = "",
) -> tuple[str, Mapping[str, object]]:
    artifact_base = _https_url(artifact_base_url, label="artifact_base_url")
    dashboard_base = _https_url(dashboard_base_url, label="dashboard_base_url")
    destination = _sha(destination_fingerprint, label="destination_fingerprint")
    if SAFE_RELEASE_RE.fullmatch(expected_release_id) is None:
        raise PeriodicBundleError("expected_release_id_invalid")
    if not isinstance(expected_dataset_version, str) or not expected_dataset_version:
        raise PeriodicBundleError("expected_dataset_version_invalid")
    keyword = _required_keyword(required_keyword)
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise PeriodicBundleError("output_root_exists")
    poster_manifest_path = Path(poster_manifest_path)
    rows = _poster_rows(poster_manifest_path)
    if (
        {row.get("release_id") for row in rows} != {expected_release_id}
        or {row.get("dataset_version") for row in rows}
        != {expected_dataset_version}
        or len({row.get("data_as_of") for row in rows}) != 1
    ):
        raise PeriodicBundleError("poster_identity_mismatch")

    identity = {
        "schema_version": "periodic-report-bundle-identity-v1",
        "data_release_id": expected_release_id,
        "dataset_version": expected_dataset_version,
        "periods": [
            {"grain": row["period"], "period_id": row["period_id"]}
            for row in rows
        ],
        "destination_fingerprint": destination,
        "required_keyword": keyword,
    }
    bundle_id = "periodic_" + sha256_hex(canonical_json_bytes(identity))[:32]
    public_base = f"{artifact_base}/{bundle_id}/public"
    temporary_parent = output_root.parent.resolve()
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=temporary_parent))
    os.chmod(temporary, 0o700)
    captures_by_period: list[Mapping[str, object]] = []
    try:
        public_root = temporary / "public"
        private_root = temporary / "private"
        outbox_root = private_root / "outbox"
        for directory in (public_root, private_root, outbox_root):
            directory.mkdir(mode=0o700)
        outbox_records: list[Mapping[str, object]] = []
        for row in rows:
            period = str(row["period"])
            source_path = poster_manifest_path.parent / str(row["file"])
            metadata = _regular_file(source_path, label=f"poster_{period}")
            payload = source_path.read_bytes()
            if metadata.st_size != row["bytes"] or sha256_hex(payload) != row["sha256"]:
                raise PeriodicBundleError(f"poster_{period}_bytes_mismatch")
            period_root = public_root / period
            period_root.mkdir(mode=0o700)
            poster_path = period_root / "poster.png"
            poster_path.write_bytes(payload)
            os.chmod(poster_path, 0o644)

            query = urlencode({"period": period, "period_id": row["period_id"]})
            report_url = f"{dashboard_base}/dashboard/reports?{query}"
            export_url = f"{report_url}#export"
            image_url = f"{public_base}/{period}/poster.png"
            idempotency_document = {
                "grain": period,
                "period_id": row["period_id"],
                "data_release_id": expected_release_id,
                "destination_fingerprint": destination,
            }
            idempotency_key = sha256_hex(canonical_json_bytes(idempotency_document))
            title = f"Momcozy Reddit VOC {PERIOD_LABELS[period]}"
            markdown_lines = [
                    f"## {title}",
                    f"> 周期：`{row['period_id']}`  ",
                    f"> 数据截止：`{row['data_as_of']}`  ",
                    f"> 数据发布：`{expected_release_id}`",
            ]
            if keyword:
                markdown_lines.append(f"> 推送校验：`{keyword}`")
            markdown_lines.extend(
                [
                    "",
                    _coverage_message(str(row["source_freshness_status"])),
                    "",
                    f"![{title}]({image_url})",
                    "",
                    f"[查看完整报告]({report_url}) ｜ [打开导出入口]({export_url})",
                ]
            )
            markdown = "\n".join(markdown_lines)
            body = {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": markdown},
            }
            body_bytes = canonical_json_bytes(body)
            outbox_path = outbox_root / f"{period}.json"
            outbox_path.write_bytes(body_bytes)
            os.chmod(outbox_path, 0o600)
            outbox_records.append(
                {
                    "grain": period,
                    "relative_path": f"private/outbox/{period}.json",
                    "bytes": len(body_bytes),
                    "sha256": sha256_hex(body_bytes),
                    "idempotency_key": idempotency_key,
                }
            )
            captures_by_period.append(
                {
                    "grain": period,
                    "period_id": row["period_id"],
                    "source_freshness_status": row["source_freshness_status"],
                    "coverage_percent": 100,
                    "data_as_of": row["data_as_of"],
                    "poster": {
                        "relative_path": f"public/{period}/poster.png",
                        "public_url": image_url,
                        "bytes": len(payload),
                        "sha256": sha256_hex(payload),
                        "width": row["width"],
                        "height": row["height"],
                    },
                    "report_url": report_url,
                    "export_url": export_url,
                    "idempotency_key": idempotency_key,
                }
            )
        aggregate_outbox_sha = sha256_hex(canonical_json_bytes(outbox_records))
        manifest: Mapping[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": "shadow_candidate",
            "bundle_id": bundle_id,
            "identity": identity,
            "data_as_of": rows[0]["data_as_of"],
            "captures": captures_by_period,
            "outbox": {
                "parts": outbox_records,
                "aggregate_sha256": aggregate_outbox_sha,
                "frozen_bytes": True,
            },
            "source_poster_manifest": {
                "sha256": sha256_hex(poster_manifest_path.read_bytes()),
                "schema_version": "reddit_voc_periodic_report_poster_bundle_v1",
            },
            "delivery": {
                "eligible": False,
                "reason": "shadow_preflight_required",
                "authoritative_sender": False,
            },
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
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        os.chmod(manifest_path, 0o600)
        os.replace(temporary, output_root)
        return sha256_hex((output_root / "manifest.json").read_bytes()), manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify_periodic_report_bundle(
    bundle_root: Path,
    *,
    expected_release_id: str,
    expected_destination_fingerprint: str,
) -> Mapping[str, object]:
    root = Path(bundle_root)
    if not root.is_dir() or root.is_symlink():
        raise PeriodicBundleError("bundle_root_invalid")
    manifest = _load_json(root / "manifest.json", label="bundle_manifest", canonical=True)
    identity = manifest.get("identity")
    captures = manifest.get("captures")
    outbox = manifest.get("outbox")
    boundaries = manifest.get("boundaries")
    delivery = manifest.get("delivery")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "shadow_candidate"
        or not isinstance(identity, Mapping)
        or identity.get("data_release_id") != expected_release_id
        or identity.get("destination_fingerprint")
        != _sha(expected_destination_fingerprint, label="destination_fingerprint")
        or not isinstance(captures, list)
        or len(captures) != 3
        or not isinstance(outbox, Mapping)
        or outbox.get("frozen_bytes") is not True
        or not isinstance(boundaries, Mapping)
        or any(boundaries.get(key) is not False for key in (
            "deploy",
            "remote_write",
            "schedule_change",
            "provider_call",
            "database_write",
            "live_send",
            "webhook_send",
        ))
        or boundaries.get("production_unchanged") is not True
        or not isinstance(delivery, Mapping)
        or delivery.get("eligible") is not False
        or delivery.get("authoritative_sender") is not False
    ):
        raise PeriodicBundleError("bundle_manifest_contract_invalid")
    identity_periods = identity.get("periods")
    if (
        identity.get("schema_version") != "periodic-report-bundle-identity-v1"
        or not isinstance(identity.get("dataset_version"), str)
        or not identity.get("dataset_version")
        or _required_keyword(identity.get("required_keyword", ""))
        != identity.get("required_keyword", "")
        or not isinstance(identity_periods, list)
        or len(identity_periods) != 3
        or {row.get("grain") for row in identity_periods if isinstance(row, Mapping)}
        != set(PERIODS)
    ):
        raise PeriodicBundleError("bundle_identity_invalid")
    expected_bundle_id = "periodic_" + sha256_hex(canonical_json_bytes(identity))[:32]
    if manifest.get("bundle_id") != expected_bundle_id:
        raise PeriodicBundleError("bundle_identity_invalid")
    records = outbox.get("parts")
    if (
        not isinstance(records, list)
        or len(records) != 3
        or {record.get("grain") for record in records if isinstance(record, Mapping)}
        != set(PERIODS)
        or {capture.get("grain") for capture in captures if isinstance(capture, Mapping)}
        != set(PERIODS)
    ):
        raise PeriodicBundleError("bundle_outbox_invalid")
    record_by_grain = {
        str(record["grain"]): record for record in records if isinstance(record, Mapping)
    }
    verified_outbox: list[Mapping[str, object]] = []
    for capture in captures:
        if not isinstance(capture, Mapping) or capture.get("grain") not in PERIODS:
            raise PeriodicBundleError("bundle_capture_invalid")
        grain = str(capture["grain"])
        period_id = capture.get("period_id")
        freshness = capture.get("source_freshness_status")
        identity_period = next(
            row for row in identity_periods
            if isinstance(row, Mapping) and row.get("grain") == grain
        )
        if (
            not isinstance(period_id, str)
            or not period_id
            or identity_period.get("period_id") != period_id
            or freshness not in SOURCE_FRESHNESS
            or capture.get("coverage_percent") != 100
        ):
            raise PeriodicBundleError("bundle_capture_invalid")
        poster = capture.get("poster")
        if not isinstance(poster, Mapping):
            raise PeriodicBundleError("bundle_capture_invalid")
        relative = poster.get("relative_path")
        expected_relative = f"public/{grain}/poster.png"
        if (
            relative != expected_relative
            or poster.get("width") != PERIOD_DIMENSIONS[grain][0]
            or poster.get("height") != PERIOD_DIMENSIONS[grain][1]
            or not isinstance(poster.get("bytes"), int)
            or isinstance(poster.get("bytes"), bool)
            or int(poster["bytes"]) < 100_000
        ):
            raise PeriodicBundleError("bundle_capture_invalid")
        _sha(poster.get("sha256"), label="bundle_poster_sha256")
        path = root / expected_relative
        metadata = _regular_file(path, label="bundle_poster")
        if metadata.st_size != poster.get("bytes") or sha256_hex(path.read_bytes()) != poster.get("sha256"):
            raise PeriodicBundleError("bundle_poster_mismatch")
        public_url = _https_url(str(poster.get("public_url", "")), label="poster_public_url")
        report_url = _https_url(str(capture.get("report_url", "")), label="report_url")
        export_url = str(capture.get("export_url", ""))
        if (
            not public_url.endswith(expected_relative)
            or f"period={grain}" not in report_url
            or f"period_id={period_id.replace(':', '%3A')}" not in report_url
            or export_url != f"{report_url}#export"
        ):
            raise PeriodicBundleError("bundle_capture_url_invalid")
        expected_idempotency = sha256_hex(
            canonical_json_bytes(
                {
                    "grain": grain,
                    "period_id": period_id,
                    "data_release_id": expected_release_id,
                    "destination_fingerprint": expected_destination_fingerprint,
                }
            )
        )
        if (
            capture.get("idempotency_key") != expected_idempotency
            or record_by_grain[grain].get("idempotency_key") != expected_idempotency
        ):
            raise PeriodicBundleError("bundle_idempotency_key_invalid")
    for record in records:
        if not isinstance(record, Mapping) or record.get("grain") not in PERIODS:
            raise PeriodicBundleError("bundle_outbox_invalid")
        grain = str(record["grain"])
        relative = record.get("relative_path")
        if relative != f"private/outbox/{grain}.json":
            raise PeriodicBundleError("bundle_outbox_invalid")
        path = root / str(relative)
        metadata = _regular_file(path, label="bundle_outbox")
        payload = path.read_bytes()
        if metadata.st_size != record.get("bytes") or sha256_hex(payload) != record.get("sha256"):
            raise PeriodicBundleError("bundle_outbox_mismatch")
        body = _load_json(path, label="bundle_outbox", canonical=True)
        markdown = body.get("markdown")
        capture = next(
            row for row in captures
            if isinstance(row, Mapping) and row.get("grain") == grain
        )
        poster = capture["poster"]
        assert isinstance(poster, Mapping)
        if (
            body.get("msgtype") != "markdown"
            or not isinstance(markdown, Mapping)
            or not isinstance(markdown.get("text"), str)
            or str(poster["public_url"]) not in str(markdown["text"])
            or str(capture["report_url"]) not in str(markdown["text"])
            or str(capture["export_url"]) not in str(markdown["text"])
            or str(capture["period_id"]) not in str(markdown["text"])
            or expected_release_id not in str(markdown["text"])
            or "webhook" in str(markdown).lower()
            or "secret" in str(markdown).lower()
        ):
            raise PeriodicBundleError("bundle_outbox_invalid")
        verified_outbox.append(record)
    if sha256_hex(canonical_json_bytes(verified_outbox)) != outbox.get("aggregate_sha256"):
        raise PeriodicBundleError("bundle_outbox_aggregate_mismatch")
    return manifest


def _required_keyword(value: object) -> str:
    if not isinstance(value, str):
        raise PeriodicBundleError("required_keyword_invalid")
    keyword = value.strip()
    if keyword != value or len(keyword) > 32 or any(char in keyword for char in "\r\n\t"):
        raise PeriodicBundleError("required_keyword_invalid")
    return keyword


def preflight_periodic_report_bundle(
    bundle_root: Path,
    *,
    expected_release_id: str,
    expected_destination_fingerprint: str,
    head_checker: Callable[[str], Mapping[str, object]],
) -> Mapping[str, object]:
    manifest = verify_periodic_report_bundle(
        bundle_root,
        expected_release_id=expected_release_id,
        expected_destination_fingerprint=expected_destination_fingerprint,
    )
    checks: list[Mapping[str, object]] = []
    for capture in manifest["captures"]:
        assert isinstance(capture, Mapping)
        poster = capture["poster"]
        assert isinstance(poster, Mapping)
        urls = (
            ("poster", str(poster["public_url"]), int(poster["bytes"])),
            ("report", str(capture["report_url"]), None),
            ("export", str(capture["export_url"]), None),
        )
        for role, url, expected_bytes in urls:
            observed = head_checker(url)
            if not isinstance(observed, Mapping) or observed.get("status") != 200:
                raise PeriodicBundleError(f"head_{capture['grain']}_{role}_failed")
            content_length = observed.get("content_length")
            if role == "poster" and content_length != expected_bytes:
                raise PeriodicBundleError(f"head_{capture['grain']}_poster_bytes_mismatch")
            checks.append(
                {
                    "grain": capture["grain"],
                    "role": role,
                    "url": url,
                    "status": 200,
                    "content_length": content_length,
                }
            )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "status": "passed_shadow_preflight",
        "bundle_id": manifest["bundle_id"],
        "data_release_id": expected_release_id,
        "destination_fingerprint": expected_destination_fingerprint,
        "checks": checks,
        "delivery_eligible": False,
        "reason": "shadow_only_live_send_not_authorized",
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
