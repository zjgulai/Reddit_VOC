#!/usr/bin/env python3
"""Run and validate the four read-only Reddit VOC report downloads.

The browser callback is rendered from a reviewed template so the local output
directory is explicit.  No browser-side access to ``process.env`` is assumed.
The command downloads files locally and never writes to the website.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import zipfile

from scripts.run_insights_e2e import (
    default_runner,
    file_sha256,
    run_browser_callback,
    runner_prefix,
    write_immutable,
)


SCHEMA_VERSION = "reddit_voc_insights_export_validation_receipt_v1"
TEMPLATE_TOKEN = "__REDDIT_VOC_EXPORT_OUTPUT_DIR__"
SHA_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
EXPECTED_FILES = {
    "csv": "report-latest-complete-daily.csv",
    "pdf": "report-latest-complete-daily.pdf",
    "pptx": "report-latest-complete-daily.pptx",
    "docx": "report-latest-complete-daily.docx",
}


class InsightsExportsError(ValueError):
    """A production export acceptance invariant failed."""


def _regular_file(path: Path, *, label: str) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise InsightsExportsError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InsightsExportsError(f"{label}_unsafe")
    return metadata


def _safe_empty_output_root(path: Path) -> None:
    if path.exists() or path.is_symlink():
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InsightsExportsError("output_root_unsafe")
        if any(path.iterdir()):
            raise InsightsExportsError("output_root_not_empty")
    else:
        path.mkdir(parents=True, mode=0o700)
    os.chmod(path, 0o700)


def _require_sha(value: str, *, label: str) -> str:
    if SHA_RE.fullmatch(value) is None:
        raise InsightsExportsError(f"{label}_sha256_invalid")
    return value


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InsightsExportsError("base_url_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise InsightsExportsError("base_url_invalid")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise InsightsExportsError("base_url_https_required")
    if parsed.path not in {"", "/"}:
        raise InsightsExportsError("base_url_path_invalid")
    return value.rstrip("/")


def evidence_contract_for_url(value: str) -> tuple[str, str]:
    """Classify export evidence without promoting loopback checks to public L3."""
    site_url = _validate_base_url(value)
    hostname = urlsplit(site_url).hostname
    if hostname in {"127.0.0.1", "localhost"}:
        return "local_loopback", "L2_local_container_readonly_browser_download_acceptance"
    return "public_https", "L3_public_readonly_browser_download_acceptance"


def render_callback_template(source_path: Path, output_path: Path, output_root: Path) -> str:
    _regular_file(source_path, label="callback_template")
    source = source_path.read_text(encoding="utf-8")
    if source.count(TEMPLATE_TOKEN) != 1 or "process.env" in source:
        raise InsightsExportsError("callback_template_contract_invalid")
    rendered = source.replace(TEMPLATE_TOKEN, json.dumps(str(output_root), ensure_ascii=False))
    output_path.write_text(rendered, encoding="utf-8")
    os.chmod(output_path, 0o600)
    return file_sha256(output_path)


def _validate_csv(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        raise InsightsExportsError("csv_utf8_bom_missing")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeError, csv.Error) as exc:
        raise InsightsExportsError("csv_parse_failed") from exc
    expected_header = ["指标ID", "指标", "当前值", "环比", "同比", "趋势"]
    if len(rows) < 2 or rows[0] != expected_header or any(len(row) != len(expected_header) for row in rows):
        raise InsightsExportsError("csv_contract_invalid")
    return {"header": rows[0], "data_row_count": len(rows) - 1}


def _validate_pdf(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) < 1_000 or not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-4_096:]:
        raise InsightsExportsError("pdf_contract_invalid")
    page_markers = raw.count(b"/Type /Page")
    if page_markers < 1:
        raise InsightsExportsError("pdf_page_missing")
    return {"page_marker_count": page_markers}


def _validate_office_zip(path: Path, *, kind: str) -> dict[str, Any]:
    if not zipfile.is_zipfile(path):
        raise InsightsExportsError(f"{kind}_zip_invalid")
    required = {
        "pptx": {"[Content_Types].xml", "ppt/presentation.xml"},
        "docx": {"[Content_Types].xml", "word/document.xml"},
    }[kind]
    prefix = "ppt/slides/" if kind == "pptx" else "word/"
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if not required <= names or not any(name.startswith(prefix) and name.endswith(".xml") for name in names):
            raise InsightsExportsError(f"{kind}_package_contract_invalid")
        xml = b"\n".join(
            archive.read(name)
            for name in sorted(names)
            if name.startswith(prefix) and name.endswith(".xml")
        )
    if b"Reddit VOC" not in xml or "指标".encode("utf-8") not in xml:
        raise InsightsExportsError(f"{kind}_business_content_missing")
    return {"package_member_count": len(names), "business_content_verified": True}


def validate_downloads(output_root: Path) -> dict[str, dict[str, Any]]:
    actual_names = {path.name for path in output_root.iterdir()}
    expected_names = set(EXPECTED_FILES.values())
    if actual_names != expected_names:
        raise InsightsExportsError("download_file_set_invalid")
    result: dict[str, dict[str, Any]] = {}
    for kind, filename in EXPECTED_FILES.items():
        path = output_root / filename
        metadata = _regular_file(path, label=f"download_{kind}")
        if metadata.st_size <= 0:
            raise InsightsExportsError(f"download_{kind}_empty")
        if kind == "csv":
            detail = _validate_csv(path)
        elif kind == "pdf":
            detail = _validate_pdf(path)
        else:
            detail = _validate_office_zip(path, kind=kind)
        result[kind] = {
            "path": filename,
            "bytes": metadata.st_size,
            "sha256": file_sha256(path),
            **detail,
        }
    return result


def validate_callback(
    callback: Mapping[str, Any], *, expected_release_sha256: str, expected_release_id: str
) -> None:
    if (
        callback.get("status") != "passed"
        or callback.get("route") != "/dashboard/reports"
        or callback.get("releaseSha256") != expected_release_sha256
        or callback.get("releaseId") != expected_release_id
        or callback.get("reportCollection") != "最新完整周期"
        or callback.get("reportPeriod") != "日报"
        or callback.get("browserErrors") != []
        or callback.get("sameOriginHttpFailures") != []
        or callback.get("externalRequests") != []
    ):
        raise InsightsExportsError("browser_callback_contract_invalid")
    downloads = callback.get("downloads")
    if not isinstance(downloads, dict) or set(downloads) != set(EXPECTED_FILES):
        raise InsightsExportsError("browser_download_contract_invalid")
    for kind, filename in EXPECTED_FILES.items():
        row = downloads.get(kind)
        if not isinstance(row, dict) or row.get("savedFilename") != filename:
            raise InsightsExportsError(f"browser_download_{kind}_invalid")
        suggested = row.get("suggestedFilename")
        if not isinstance(suggested, str) or not suggested.casefold().endswith(f".{kind}"):
            raise InsightsExportsError(f"browser_download_{kind}_suggested_name_invalid")


def execute_export_acceptance(
    *,
    base_url: str,
    expected_release_sha256: str,
    expected_release_id: str,
    callback_template_path: Path,
    expected_callback_template_sha256: str,
    output_root: Path,
    output_receipt_path: Path,
    runner_executable: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    site_url = _validate_base_url(base_url)
    site_scope, evidence_grade = evidence_contract_for_url(site_url)
    release_sha = _require_sha(expected_release_sha256, label="release")
    template_sha = _require_sha(expected_callback_template_sha256, label="callback_template")
    _regular_file(callback_template_path, label="callback_template")
    if file_sha256(callback_template_path) != template_sha:
        raise InsightsExportsError("callback_template_sha256_mismatch")
    _safe_empty_output_root(output_root)
    if output_receipt_path == output_root or output_receipt_path.parent != output_root:
        raise InsightsExportsError("receipt_path_must_be_inside_output_root")

    with tempfile.TemporaryDirectory(prefix="reddit-voc-exports-") as temporary:
        temporary_root = Path(temporary)
        callback_path = temporary_root / "callback.js"
        rendered_sha = render_callback_template(
            callback_template_path, callback_path, output_root.resolve()
        )
        env = dict(os.environ)
        env.update(
            {
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                "PWTEST_CLI_GLOBAL_CONFIG": str(temporary_root / "playwright-config"),
            }
        )
        callback, runner_version = run_browser_callback(
            base_url=site_url,
            script_path=callback_path,
            release_sha256=release_sha,
            runner=default_runner,
            prefix=runner_prefix(runner_executable),
            env=env,
        )

    validate_callback(
        callback,
        expected_release_sha256=release_sha,
        expected_release_id=expected_release_id,
    )
    files = validate_downloads(output_root)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "passed_local_readonly_export_acceptance"
            if site_scope == "local_loopback"
            else "passed_public_readonly_export_acceptance"
        ),
        "evidence_grade": evidence_grade,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "site_url": site_url,
        "site_scope": site_scope,
        "release": {
            "release_sha256": release_sha,
            "release_id": expected_release_id,
            "pointer_sha256": callback.get("releasePointerSha256"),
            "reports_dataset_version": callback.get("reportsDatasetVersion"),
            "report_manifest_sha256": callback.get("reportManifestSha256"),
            "report_index_sha256": callback.get("reportIndexSha256"),
            "report_document_sha256": callback.get("reportDocumentSha256"),
            "report_id": callback.get("reportId"),
        },
        "browser": {
            "runner": "playwright-cli",
            "version": runner_version,
            "callback_template_sha256": template_sha,
            "rendered_callback_sha256": rendered_sha,
            "browser_errors": [],
            "same_origin_http_failures": [],
            "external_requests": [],
        },
        "downloads": files,
        "checks": {
            "download_count": 4,
            "csv_content_verified": True,
            "pdf_structure_verified": True,
            "pptx_structure_and_content_verified": True,
            "docx_structure_and_content_verified": True,
            "release_and_report_binding_verified": True,
        },
        "boundaries": {
            "production_unchanged": True,
            "remote_write": False,
            "deploy": False,
            "schedule_change": False,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
        },
    }
    state, digest = write_immutable(output_receipt_path, receipt)
    return state, digest, receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--callback-template", required=True)
    parser.add_argument("--expected-callback-template-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output-receipt", required=True)
    parser.add_argument("--runner-executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        state, digest, receipt = execute_export_acceptance(
            base_url=args.base_url,
            expected_release_sha256=args.expected_release_sha256,
            expected_release_id=args.expected_release_id,
            callback_template_path=Path(args.callback_template),
            expected_callback_template_sha256=args.expected_callback_template_sha256,
            output_root=Path(args.output_root),
            output_receipt_path=Path(args.output_receipt),
            runner_executable=args.runner_executable,
        )
    except (InsightsExportsError, OSError, ValueError) as exc:
        print(f"status=failed reason={exc}", file=__import__("sys").stderr)
        return 1
    print(f"state={state}")
    print(f"receipt_sha256={digest}")
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
