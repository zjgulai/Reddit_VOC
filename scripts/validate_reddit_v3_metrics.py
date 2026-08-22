#!/usr/bin/env python3
"""Independently recompute and validate a Reddit VOC V3 metrics candidate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_brand_health import compute_brand_health  # noqa: E402
from reddit_voc.v3_indicators import (  # noqa: E402
    EXPECTED_BOUNDARIES,
    IndicatorRegistry,
    canonical_json_bytes,
    compute_indicator,
    load_indicator_registry,
)
from reddit_voc.v3_periodized_metrics import (  # noqa: E402
    build_periodized_metrics_candidate,
)


INPUT_SCHEMA_VERSION = "reddit_voc_metrics_input_v1"
METRICS_SCHEMA_VERSION = "reddit_voc_metrics_snapshot_v1"
MANIFEST_SCHEMA_VERSION = "reddit_voc_metrics_candidate_manifest_v1"
RECEIPT_SCHEMA_VERSION = "reddit_voc_metrics_validation_receipt_v1"
SOURCE_MANIFEST_SCHEMA_VERSION = "reddit_voc_governed_signal_snapshot_v1"
SOURCE_RECEIPT_SCHEMA_VERSION = "reddit_voc_governed_signal_validation_receipt_v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MetricsValidationError(ValueError):
    """The candidate fails byte, lineage, semantic, or recomputation checks."""


def _sha(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hex(value: object, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise MetricsValidationError(f"{label} must be lowercase SHA-256")
    return value


def _canonical_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricsValidationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise MetricsValidationError(f"{label} is not canonical JSON")
    return value


def _normalize_input(value: object) -> dict[str, Any]:
    required = {
        "atomic_facts",
        "context",
        "eligibility_rows",
        "observations",
        "period",
        "periodized_metrics_input",
        "schema_version",
        "scope",
        "source_facts_manifest_sha256",
        "source_snapshot_id",
    }
    optional = {"brand_health_period", "brand_health_scope", "decimal_places"}
    if not isinstance(value, Mapping) or not required <= set(value) or set(value) - required - optional:
        raise MetricsValidationError("metrics input fields are invalid")
    if value.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise MetricsValidationError("metrics input schema is unsupported")
    result = dict(value)
    for field in ("atomic_facts", "eligibility_rows", "observations"):
        if not isinstance(result.get(field), list) or any(
            not isinstance(row, Mapping) for row in result[field]
        ):
            raise MetricsValidationError(f"metrics input {field} is invalid")
    if not isinstance(result.get("context"), Mapping):
        raise MetricsValidationError("metrics input context is invalid")
    for field in ("period", "scope", "source_snapshot_id"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise MetricsValidationError(f"metrics input {field} is invalid")
    _hex(result.get("source_facts_manifest_sha256"), "source facts manifest SHA")
    decimal_places = result.get("decimal_places", 2)
    if type(decimal_places) is not int or not 0 <= decimal_places <= 12:
        raise MetricsValidationError("metrics decimal_places is invalid")
    result["decimal_places"] = decimal_places
    result["brand_health_period"] = result.get("brand_health_period", result["period"])
    result["brand_health_scope"] = result.get("brand_health_scope", "momcozy")
    return result


def _independent_documents(
    input_document: Mapping[str, object], registry: IndicatorRegistry
) -> dict[str, dict[str, object]]:
    """Replay domain formulas without importing or calling the build script."""

    value = _normalize_input(input_document)
    results: list[dict[str, object]] = []
    context = value["context"]
    assert isinstance(context, Mapping)
    for definition in registry.indicators:
        indicator_context = context.get(definition.reddit_indicator_id, {})
        if not isinstance(indicator_context, Mapping):
            raise MetricsValidationError(
                f"indicator context is invalid:{definition.reddit_indicator_id}"
            )
        try:
            result = compute_indicator(
                definition.reddit_indicator_id,
                value["observations"],
                registry=registry,
                comparison_side=definition.default_comparison_side,
                period=str(value["period"]),
                scope=str(value["scope"]),
                eligibility_rows=value["eligibility_rows"],
                atomic_facts=value["atomic_facts"],
                context=indicator_context,
                decimal_places=int(value["decimal_places"]),
            )
        except ValueError as exc:
            raise MetricsValidationError(
                f"independent indicator recompute failed:{definition.reddit_indicator_id}:{exc}"
            ) from exc
        results.append(result.as_dict())
    try:
        brand_health = compute_brand_health(
            value["observations"],
            atomic_facts=value["atomic_facts"],
            period=str(value["brand_health_period"]),
            scope=str(value["brand_health_scope"]),
            decimal_places=int(value["decimal_places"]),
        ).as_dict()
    except ValueError as exc:
        raise MetricsValidationError(
            f"independent brand health recompute failed:{exc}"
        ) from exc
    lineage = {
        "source_facts_manifest_sha256": value["source_facts_manifest_sha256"],
        "source_snapshot_id": value["source_snapshot_id"],
    }
    metrics = {
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "core_indicator_count": registry.core_indicator_count,
        "indicator_count": len(results),
        "indicators": results,
        "integrity_indicator_count": registry.integrity_indicator_count,
        "lineage": lineage,
        "period": value["period"],
        "registry_version": registry.registry_version,
        "schema_version": METRICS_SCHEMA_VERSION,
        "scope": value["scope"],
    }
    brand_health = dict(brand_health)
    brand_health["boundaries"] = dict(EXPECTED_BOUNDARIES)
    brand_health["lineage"] = lineage
    periodized = build_periodized_metrics_candidate(value, registry=registry)
    periodized["lineage"] = lineage
    return {
        "brand-health.json": brand_health,
        "metrics.json": metrics,
        "periodized-metrics.json": periodized,
    }


def _validate_manifest(
    manifest: Mapping[str, object],
    *,
    expected_input_sha256: str,
    expected_registry_sha256: str,
    expected_source_facts_validation_receipt_sha256: str,
) -> None:
    if set(manifest) != {
        "artifact_stage",
        "boundaries",
        "consumption_status",
        "core_indicator_count",
        "files",
        "indicator_count",
        "input_sha256",
        "integrity_indicator_count",
        "period_count",
        "periodized_brand_health_row_count",
        "periodized_brand_health_dimension_row_count",
        "periodized_metric_row_count",
        "promotable",
        "registry_sha256",
        "schema_version",
        "source_facts_validation_receipt_sha256",
    }:
        raise MetricsValidationError("metrics manifest fields are invalid")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise MetricsValidationError("metrics manifest schema is unsupported")
    if (
        manifest.get("artifact_stage") != "metrics_candidate"
        or manifest.get("consumption_status")
        != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != EXPECTED_BOUNDARIES
    ):
        raise MetricsValidationError("metrics manifest candidate state is invalid")
    if manifest.get("input_sha256") != expected_input_sha256:
        raise MetricsValidationError("metrics input SHA binding mismatch")
    if manifest.get("registry_sha256") != expected_registry_sha256:
        raise MetricsValidationError("metrics registry SHA binding mismatch")
    if (
        manifest.get("source_facts_validation_receipt_sha256")
        != expected_source_facts_validation_receipt_sha256
    ):
        raise MetricsValidationError("source facts validation receipt binding mismatch")
    if (
        manifest.get("indicator_count") != 26
        or manifest.get("core_indicator_count") != 19
        or manifest.get("integrity_indicator_count") != 7
        or type(manifest.get("period_count")) is not int
        or int(manifest["period_count"]) < 3
        or manifest.get("periodized_metric_row_count")
        != int(manifest["period_count"]) * 26
        or manifest.get("periodized_brand_health_row_count")
        != int(manifest["period_count"]) * 2
        or manifest.get("periodized_brand_health_dimension_row_count")
        != int(manifest["period_count"]) * 8
    ):
        raise MetricsValidationError("metrics manifest indicator counts are invalid")


def validate_metrics_candidate(
    bundle_root: Path,
    *,
    input_document: Mapping[str, object],
    registry: IndicatorRegistry,
    expected_input_sha256: str,
    expected_registry_sha256: str,
    expected_source_facts_validation_receipt_sha256: str,
) -> dict[str, object]:
    expected_input_sha256 = _hex(expected_input_sha256, "metrics input SHA")
    expected_registry_sha256 = _hex(expected_registry_sha256, "registry SHA")
    expected_receipt_sha = _hex(
        expected_source_facts_validation_receipt_sha256,
        "source facts validation receipt SHA",
    )
    normalized_input = _normalize_input(input_document)
    bundle_root = Path(bundle_root)
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise MetricsValidationError("metrics candidate root is invalid")
    actual_names = {path.name for path in bundle_root.iterdir()}
    expected_names = {
        "brand-health.json",
        "manifest.json",
        "metrics.json",
        "periodized-metrics.json",
    }
    if actual_names != expected_names or any(
        path.is_symlink() or not path.is_file() for path in bundle_root.iterdir()
    ):
        raise MetricsValidationError("metrics candidate file set is invalid")
    manifest = _canonical_object(bundle_root / "manifest.json", "metrics manifest")
    _validate_manifest(
        manifest,
        expected_input_sha256=expected_input_sha256,
        expected_registry_sha256=expected_registry_sha256,
        expected_source_facts_validation_receipt_sha256=expected_receipt_sha,
    )
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != {
        "brand-health.json",
        "metrics.json",
        "periodized-metrics.json",
    }:
        raise MetricsValidationError("metrics manifest files are invalid")
    actual_documents: dict[str, dict[str, object]] = {}
    for name in sorted(files):
        record = files[name]
        path = bundle_root / name
        if not isinstance(record, Mapping) or set(record) != {"bytes", "sha256"}:
            raise MetricsValidationError("metrics file record is invalid")
        if record.get("bytes") != path.stat().st_size or record.get("sha256") != _sha(path):
            raise MetricsValidationError("metrics file integrity mismatch")
        actual_documents[name] = _canonical_object(path, name)
    expected_documents = _independent_documents(normalized_input, registry)
    for name in sorted(expected_documents):
        expected_payload = canonical_json_bytes(expected_documents[name]) + b"\n"
        if (bundle_root / name).read_bytes() != expected_payload:
            raise MetricsValidationError(
                f"independent recompute mismatch:{name}"
            )
    metrics = actual_documents["metrics.json"]
    indicators = metrics.get("indicators")
    if not isinstance(indicators, list) or len(indicators) != 26:
        raise MetricsValidationError("metrics indicator result closed set is invalid")
    ids = [row.get("reddit_indicator_id") for row in indicators if isinstance(row, Mapping)]
    if ids != [definition.reddit_indicator_id for definition in registry.indicators]:
        raise MetricsValidationError("metrics indicator result order is invalid")
    snapshot_id = str(normalized_input["source_snapshot_id"])
    fixture_only = snapshot_id.startswith("fixture")
    return {
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "brand_health_recomputed": True,
        "bundle_manifest_sha256": _sha(bundle_root / "manifest.json"),
        "deterministic_full_byte_replay": True,
        "indicator_count": 26,
        "input_sha256": expected_input_sha256,
        "periodized_metrics_recomputed": True,
        "promotable": False if fixture_only else True,
        "registry_sha256": expected_registry_sha256,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source_facts_validation_receipt_sha256": expected_receipt_sha,
        "status": "passed_fixture_only" if fixture_only else "passed_candidate_only",
    }


def _validate_upstream_binding(
    source_manifest: Mapping[str, object],
    source_manifest_sha256: str,
    source_receipt: Mapping[str, object],
) -> None:
    if (
        source_receipt.get("schema_version") != SOURCE_RECEIPT_SCHEMA_VERSION
        or source_receipt.get("status") != "passed"
        or source_receipt.get("consumption_status")
        != "eligible_for_downstream_consumption"
        or source_receipt.get("promotable") is not True
        or source_receipt.get("validated_tables") != 8
        or type(source_receipt.get("unaccounted_facts")) is not int
        or source_receipt.get("unaccounted_facts") != 0
        or type(source_receipt.get("unaccounted_vocs")) is not int
        or source_receipt.get("unaccounted_vocs") != 0
    ):
        raise MetricsValidationError("blocked upstream facts cannot validate formal metrics")
    if source_receipt.get("snapshot_manifest_sha256") != source_manifest_sha256:
        raise MetricsValidationError("source facts receipt manifest binding mismatch")
    if (
        source_manifest.get("schema_version") != SOURCE_MANIFEST_SCHEMA_VERSION
        or source_manifest.get("status") != "candidate_built"
        or source_manifest.get("consumption_status")
        != "blocked_pending_independent_validation"
        or source_manifest.get("independent_validation_status") != "pending"
        or source_manifest.get("promotable") is not False
        or source_receipt.get("snapshot_id") != source_manifest.get("snapshot_id")
        or source_receipt.get("source_snapshot_id")
        != source_manifest.get("source_snapshot_id")
    ):
        raise MetricsValidationError("source facts manifest lifecycle is invalid")
    boundaries = source_manifest.get("boundaries")
    if boundaries != EXPECTED_BOUNDARIES or source_receipt.get("boundaries") != EXPECTED_BOUNDARIES:
        raise MetricsValidationError("source facts boundaries are invalid")


def _write_receipt(path: Path, result: Mapping[str, object]) -> str:
    payload = canonical_json_bytes(result) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise MetricsValidationError("metrics validation receipt collision")
        return "no_change"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.write(descriptor, payload)
        os.close(descriptor)
        descriptor = -1
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--source-facts-manifest", type=Path, required=True)
    parser.add_argument("--source-facts-manifest-sha256", required=True)
    parser.add_argument("--source-facts-validation-receipt", type=Path, required=True)
    parser.add_argument("--source-facts-validation-receipt-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    input_sha = _hex(args.input_sha256, "metrics input SHA")
    registry_sha = _hex(args.registry_sha256, "registry SHA")
    source_manifest_sha = _hex(
        args.source_facts_manifest_sha256, "source facts manifest SHA"
    )
    source_receipt_sha = _hex(
        args.source_facts_validation_receipt_sha256,
        "source facts validation receipt SHA",
    )
    for path, expected, label in (
        (args.input, input_sha, "metrics input"),
        (args.registry, registry_sha, "indicator registry"),
        (args.source_facts_manifest, source_manifest_sha, "source facts manifest"),
        (
            args.source_facts_validation_receipt,
            source_receipt_sha,
            "source facts validation receipt",
        ),
    ):
        if _sha(path) != expected:
            raise MetricsValidationError(f"{label} SHA mismatch")
    input_document = _canonical_object(args.input, "metrics input")
    source_manifest = _canonical_object(
        args.source_facts_manifest, "source facts manifest"
    )
    source_receipt = _canonical_object(
        args.source_facts_validation_receipt,
        "source facts validation receipt",
    )
    _validate_upstream_binding(source_manifest, source_manifest_sha, source_receipt)
    if input_document.get("source_facts_manifest_sha256") != source_manifest_sha:
        raise MetricsValidationError("metrics input source facts binding mismatch")
    registry = load_indicator_registry(args.registry)
    result = validate_metrics_candidate(
        args.candidate_root,
        input_document=input_document,
        registry=registry,
        expected_input_sha256=input_sha,
        expected_registry_sha256=registry_sha,
        expected_source_facts_validation_receipt_sha256=source_receipt_sha,
    )
    result["receipt_write_status"] = _write_receipt(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
