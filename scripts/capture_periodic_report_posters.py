#!/usr/bin/env python3
"""Generate deterministic local daily/weekly/monthly report poster evidence.

The command serves an already-built dist on loopback, captures only the governed
poster node, validates visual and data-identity contracts, and writes an immutable
PNG bundle plus canonical manifest. It never sends a webhook or touches production.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
from typing import Any, Iterator, Sequence
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = "reddit_voc_periodic_report_poster_bundle_v1"
PLAYWRIGHT_VERSION = "0.1.17"
PERIOD_SPECS = {
    "daily": {"label": "日报", "width": 1440, "height": 1800},
    "weekly": {"label": "周报", "width": 1440, "height": 2000},
    "monthly": {"label": "月报", "width": 1440, "height": 2200},
}
RUNNER = (
    "npm",
    "exec",
    "--offline",
    "--package=@playwright/cli@0.1.17",
    "--",
    "playwright-cli",
)


class PosterCaptureError(ValueError):
    """A deterministic capture invariant failed."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SpaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        request_path = unquote(urlsplit(self.path).path)
        candidate = Path(self.directory) / request_path.lstrip("/")
        if request_path != "/" and not candidate.is_file():
            self.path = "/index.html"
        super().do_GET()


@contextmanager
def serve_dist(dist_root: Path) -> Iterator[str]:
    if not dist_root.is_dir() or dist_root.is_symlink():
        raise PosterCaptureError("dist_root_invalid")
    if not (dist_root / "index.html").is_file():
        raise PosterCaptureError("dist_index_missing")
    handler = lambda *args, **kwargs: SpaHandler(  # noqa: E731
        *args, directory=str(dist_root), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def checked(command: Sequence[str], *, env: dict[str, str], timeout: int = 90) -> str:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PosterCaptureError("playwright_execution_failed") from exc
    if completed.returncode != 0:
        diagnostic = " ".join((completed.stderr or completed.stdout).split())[:2000]
        raise PosterCaptureError(f"playwright_command_failed:{diagnostic}")
    return completed.stdout.strip()


def png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()[:24]
    if len(payload) != 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise PosterCaptureError("capture_png_invalid")
    return struct.unpack(">II", payload[16:24])


def validate_observation(
    observation: object,
    *,
    period: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    if not isinstance(observation, dict) or observation.get("status") != "observed":
        raise PosterCaptureError(f"{period}_observation_invalid")
    for field in ("browserErrors", "requestFailures", "httpFailures", "externalRequests"):
        if observation.get(field) != []:
            raise PosterCaptureError(f"{period}_{field}_not_empty")
    boxes = observation.get("stableBoxes")
    if not isinstance(boxes, list) or len(boxes) != 3 or any(box != boxes[0] for box in boxes):
        raise PosterCaptureError(f"{period}_layout_not_stable")
    if boxes[0].get("width") != width or boxes[0].get("height") != height:
        raise PosterCaptureError(f"{period}_bounding_box_mismatch")
    contract = observation.get("contract")
    if not isinstance(contract, dict):
        raise PosterCaptureError(f"{period}_contract_invalid")
    attributes = contract.get("attributes")
    root = contract.get("root")
    if not isinstance(attributes, dict) or not isinstance(root, dict):
        raise PosterCaptureError(f"{period}_identity_missing")
    if (
        attributes.get("data-report-ready") != "true"
        or attributes.get("data-report-period") != period
        or attributes.get("data-report-capture-width") != str(width)
        or attributes.get("data-report-capture-height") != str(height)
        or not attributes.get("data-report-period-id")
        or not attributes.get("data-report-release-id")
        or not attributes.get("data-report-dataset-version")
        or not attributes.get("data-report-data-as-of")
        or attributes.get("data-report-source-freshness")
        not in {"complete", "full", "partial", "empty_success", "no_change"}
        or attributes.get("data-report-coverage") != "100"
    ):
        raise PosterCaptureError(f"{period}_identity_contract_failed")
    if (
        root.get("clientWidth") != width
        or root.get("clientHeight") != height
        or root.get("scrollWidth") != width
        or root.get("scrollHeight") != height
        or root.get("rectangleWidth") != width
        or root.get("rectangleHeight") != height
    ):
        raise PosterCaptureError(
            f"{period}_capture_overflow:{json.dumps(root, sort_keys=True)}"
        )
    if (
        contract.get("footerOverlap") is not False
        or contract.get("fontsStatus") != "loaded"
        or contract.get("visibleTooltips") != 0
        or contract.get("hasLoadingText") is not False
        or contract.get("hasCaptureError") is not False
        or not isinstance(contract.get("textLength"), int)
        or contract["textLength"] < 500
        or not isinstance(contract.get("chineseCharacterCount"), int)
        or contract["chineseCharacterCount"] < 100
        or not isinstance(contract.get("maxTextBlockLength"), int)
        or contract["maxTextBlockLength"] < 50
        or not isinstance(contract.get("cardCount"), int)
        or contract["cardCount"] < 10
    ):
        raise PosterCaptureError(
            f"{period}_visual_quality_failed:{json.dumps(contract, ensure_ascii=False, sort_keys=True)}"
        )
    if period != "daily" and contract.get("chartCount", 0) < 1:
        raise PosterCaptureError(f"{period}_trend_chart_missing")
    if period == "monthly" and contract.get("containsExtremePercent") is not True:
        raise PosterCaptureError("monthly_extreme_value_layout_not_exercised")
    return observation


def load_golden(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, None
    if not path.is_file() or path.is_symlink():
        raise PosterCaptureError("golden_contract_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PosterCaptureError("golden_contract_json_invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version")
        != "reddit_voc_periodic_report_poster_golden_v1"
        or not isinstance(value.get("baseline"), dict)
        or not isinstance(value.get("invariants"), dict)
    ):
        raise PosterCaptureError("golden_contract_schema_invalid")
    dimensions = value["invariants"].get("dimensions")
    expected = {
        period: [spec["width"], spec["height"]]
        for period, spec in PERIOD_SPECS.items()
    }
    if dimensions != expected:
        raise PosterCaptureError("golden_contract_dimensions_invalid")
    return value, file_sha256(path)


def evaluate_golden(
    *,
    golden: dict[str, Any] | None,
    golden_sha256: str | None,
    captures: list[dict[str, Any]],
    validator_sha256: str,
) -> dict[str, Any]:
    if golden is None:
        return {
            "status": "not_requested",
            "contract_sha256": None,
            "manual_visual_review_required": True,
        }
    baseline = golden["baseline"]
    capture_by_period = {row["period"]: row for row in captures}
    baseline_captures = baseline.get("captures")
    if not isinstance(baseline_captures, dict) or set(baseline_captures) != set(PERIOD_SPECS):
        raise PosterCaptureError("golden_baseline_capture_set_invalid")
    current_release_ids = {row["release_id"] for row in captures}
    current_dataset_versions = {row["dataset_version"] for row in captures}
    same_identity = (
        current_release_ids == {baseline.get("release_id")}
        and current_dataset_versions == {baseline.get("dataset_version")}
        and validator_sha256 == baseline.get("validator_script_sha256")
        and all(
            capture_by_period[period]["period_id"]
            == baseline_captures[period].get("period_id")
            for period in PERIOD_SPECS
        )
    )
    if same_identity:
        mismatches = [
            period
            for period in PERIOD_SPECS
            if capture_by_period[period]["sha256"]
            != baseline_captures[period].get("sha256")
        ]
        if mismatches:
            raise PosterCaptureError(
                f"golden_exact_image_mismatch:{','.join(mismatches)}"
            )
        return {
            "status": "passed_exact_pixel_baseline",
            "contract_sha256": golden_sha256,
            "manual_visual_review_required": False,
            "matched_periods": list(PERIOD_SPECS),
        }
    return {
        "status": "passed_structural_new_identity",
        "contract_sha256": golden_sha256,
        "manual_visual_review_required": True,
        "reason": "release_dataset_period_or_validator_changed",
    }


def execute(
    *,
    dist_root: Path,
    validator_script: Path,
    output_root: Path,
    golden_contract: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    if output_root.exists() or output_root.is_symlink():
        raise PosterCaptureError("output_root_already_exists")
    if not validator_script.is_file() or validator_script.is_symlink():
        raise PosterCaptureError("validator_script_invalid")

    golden, golden_sha256 = load_golden(golden_contract)
    parent = output_root.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=parent))
    os.chmod(temporary_root, 0o700)
    env = dict(os.environ)
    session = f"reddit-voc-posters-{os.getpid()}"
    opened = False
    captures: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="reddit-voc-pw-config-") as config_root:
            env.update(
                {
                    "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                    "PWTEST_CLI_GLOBAL_CONFIG": config_root,
                }
            )
            version_output = checked([*RUNNER, "--version"], env=env, timeout=30)
            if PLAYWRIGHT_VERSION not in version_output:
                raise PosterCaptureError("playwright_version_mismatch")
            with serve_dist(dist_root) as base_url:
                checked([*RUNNER, f"-s={session}", "open", base_url], env=env)
                opened = True
                for period, spec in PERIOD_SPECS.items():
                    width = int(spec["width"])
                    height = int(spec["height"])
                    checked([*RUNNER, f"-s={session}", "resize", str(width), str(height)], env=env)
                    capture_url = f"{base_url}/dashboard/reports?period={period}&capture=poster"
                    checked([*RUNNER, f"-s={session}", "goto", capture_url], env=env)
                    raw = checked(
                        [
                            *RUNNER,
                            "--raw",
                            f"-s={session}",
                            "run-code",
                            f"--filename={validator_script}",
                        ],
                        env=env,
                        timeout=120,
                    )
                    try:
                        observation = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        diagnostic = " ".join(raw.split())[:1200]
                        raise PosterCaptureError(
                            f"{period}_observation_json_invalid:{diagnostic}"
                        ) from exc
                    validated = validate_observation(
                        observation, period=period, width=width, height=height
                    )
                    png_path = temporary_root / f"reddit-voc-{period}.png"
                    checked(
                        [
                            *RUNNER,
                            f"-s={session}",
                            "screenshot",
                            "[data-report-capture-root]",
                            f"--filename={png_path}",
                        ],
                        env=env,
                        timeout=120,
                    )
                    actual_width, actual_height = png_dimensions(png_path)
                    if (actual_width, actual_height) != (width, height):
                        raise PosterCaptureError(f"{period}_png_dimensions_mismatch")
                    if png_path.stat().st_size < 100_000:
                        raise PosterCaptureError(f"{period}_png_too_small")
                    attributes = validated["contract"]["attributes"]
                    captures.append(
                        {
                            "period": period,
                            "label": spec["label"],
                            "file": png_path.name,
                            "bytes": png_path.stat().st_size,
                            "sha256": file_sha256(png_path),
                            "width": actual_width,
                            "height": actual_height,
                            "period_id": attributes["data-report-period-id"],
                            "release_id": attributes["data-report-release-id"],
                            "dataset_version": attributes["data-report-dataset-version"],
                            "coverage_percent": int(attributes["data-report-coverage"]),
                            "data_as_of": attributes["data-report-data-as-of"],
                            "source_freshness_status": attributes[
                                "data-report-source-freshness"
                            ],
                            "quality": {
                                "stable_layout": True,
                                "fonts_loaded": True,
                                "no_tooltip": True,
                                "no_loading_state": True,
                                "no_overflow_or_footer_overlap": True,
                                "card_count": validated["contract"]["cardCount"],
                                "chart_count": validated["contract"]["chartCount"],
                                "text_length": validated["contract"]["textLength"],
                                "chinese_character_count": validated["contract"][
                                    "chineseCharacterCount"
                                ],
                                "max_text_block_length": validated["contract"][
                                    "maxTextBlockLength"
                                ],
                                "contains_extreme_percent": validated["contract"][
                                    "containsExtremePercent"
                                ],
                            },
                        }
                    )
        release_ids = {row["release_id"] for row in captures}
        dataset_versions = {row["dataset_version"] for row in captures}
        data_as_of_values = {row["data_as_of"] for row in captures}
        if len(release_ids) != 1 or len(dataset_versions) != 1 or len(data_as_of_values) != 1:
            raise PosterCaptureError("cross_period_identity_mismatch")
        validator_sha256 = file_sha256(validator_script)
        golden_evaluation = evaluate_golden(
            golden=golden,
            golden_sha256=golden_sha256,
            captures=captures,
            validator_sha256=validator_sha256,
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "passed_local_poster_capture",
            "release_id": next(iter(release_ids)),
            "dataset_version": next(iter(dataset_versions)),
            "data_as_of": next(iter(data_as_of_values)),
            "captures": captures,
            "runner": {
                "name": "playwright-cli",
                "version": PLAYWRIGHT_VERSION,
                "validator_script_sha256": validator_sha256,
                "node_capture_only": True,
                "full_page": False,
                "fallback_image": False,
            },
            "golden_evaluation": golden_evaluation,
            "boundaries": {
                "production_unchanged": True,
                "deploy": False,
                "remote_write": False,
                "schedule_change": False,
                "database_write": False,
                "provider_call": False,
                "live_send": False,
                "webhook_send": False,
            },
        }
        manifest_path = temporary_root / "manifest.json"
        manifest_path.write_bytes(canonical_bytes(manifest))
        os.chmod(manifest_path, 0o600)
        os.replace(temporary_root, output_root)
        return file_sha256(output_root / "manifest.json"), manifest
    finally:
        if opened:
            try:
                checked([*RUNNER, f"-s={session}", "close"], env=env, timeout=30)
            except PosterCaptureError:
                pass
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dist-root", required=True)
    result.add_argument("--validator-script", required=True)
    result.add_argument("--output-root", required=True)
    result.add_argument("--golden-contract")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        digest, manifest = execute(
            dist_root=Path(args.dist_root).resolve(),
            validator_script=Path(args.validator_script).resolve(),
            output_root=Path(args.output_root).resolve(),
            golden_contract=(
                Path(args.golden_contract).resolve() if args.golden_contract else None
            ),
        )
    except PosterCaptureError as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "manifest_sha256": digest,
                "output_root": str(Path(args.output_root).resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
