#!/usr/bin/env python3
"""Build a private, immutable Reddit VOC V3 metrics candidate."""

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
SOURCE_MANIFEST_SCHEMA_VERSION = "reddit_voc_governed_signal_snapshot_v1"
SOURCE_RECEIPT_SCHEMA_VERSION = "reddit_voc_governed_signal_validation_receipt_v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MetricsBuildError(ValueError):
    """The metrics input, upstream gate, or output target is invalid."""


def _sha(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hex(value: object, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise MetricsBuildError(f"{label} must be lowercase SHA-256")
    return value


def _input(value: object) -> dict[str, Any]:
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
        raise MetricsBuildError("metrics input fields are invalid")
    if value.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise MetricsBuildError("metrics input schema is unsupported")
    result = dict(value)
    for field in ("atomic_facts", "eligibility_rows", "observations"):
        if not isinstance(result.get(field), list) or any(
            not isinstance(row, Mapping) for row in result[field]
        ):
            raise MetricsBuildError(f"metrics input {field} is invalid")
    if not isinstance(result.get("context"), Mapping):
        raise MetricsBuildError("metrics input context is invalid")
    for field in ("period", "scope", "source_snapshot_id"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise MetricsBuildError(f"metrics input {field} is invalid")
    _hex(result.get("source_facts_manifest_sha256"), "source facts manifest SHA")
    decimal_places = result.get("decimal_places", 2)
    if type(decimal_places) is not int or not 0 <= decimal_places <= 12:
        raise MetricsBuildError("metrics decimal_places is invalid")
    result["decimal_places"] = decimal_places
    result["brand_health_period"] = result.get("brand_health_period", result["period"])
    result["brand_health_scope"] = result.get("brand_health_scope", "momcozy")
    return result


def build_metrics_documents(
    input_document: Mapping[str, object],
    *,
    registry: IndicatorRegistry,
) -> dict[str, dict[str, object]]:
    """Compute the 19+7 registry and raw/qualified brand-health documents."""

    value = _input(input_document)
    observations = value["observations"]
    atomic_facts = value["atomic_facts"]
    eligibility_rows = value["eligibility_rows"]
    context = value["context"]
    period = str(value["period"])
    scope = str(value["scope"])
    decimal_places = int(value["decimal_places"])
    results = []
    for definition in registry.indicators:
        indicator_context = context.get(definition.reddit_indicator_id, {})
        if not isinstance(indicator_context, Mapping):
            raise MetricsBuildError(
                f"indicator context is invalid:{definition.reddit_indicator_id}"
            )
        try:
            result = compute_indicator(
                definition.reddit_indicator_id,
                observations,
                registry=registry,
                comparison_side=definition.default_comparison_side,
                period=period,
                scope=scope,
                eligibility_rows=eligibility_rows,
                atomic_facts=atomic_facts,
                context=indicator_context,
                decimal_places=decimal_places,
            )
        except ValueError as exc:
            raise MetricsBuildError(
                f"indicator computation failed:{definition.reddit_indicator_id}:{exc}"
            ) from exc
        results.append(result.as_dict())
    try:
        brand_health = compute_brand_health(
            observations,
            atomic_facts=atomic_facts,
            period=str(value["brand_health_period"]),
            scope=str(value["brand_health_scope"]),
            decimal_places=decimal_places,
        ).as_dict()
    except ValueError as exc:
        raise MetricsBuildError(f"brand health computation failed:{exc}") from exc
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
        "period": period,
        "registry_version": registry.registry_version,
        "schema_version": METRICS_SCHEMA_VERSION,
        "scope": scope,
    }
    brand_health = dict(brand_health)
    brand_health["boundaries"] = dict(EXPECTED_BOUNDARIES)
    brand_health["lineage"] = lineage
    periodized_metrics = build_periodized_metrics_candidate(
        value,
        registry=registry,
    )
    periodized_metrics["lineage"] = lineage
    return {
        "brand_health": brand_health,
        "metrics": metrics,
        "periodized_metrics": periodized_metrics,
    }


def _write_exact(path: Path, payload: bytes) -> str:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise MetricsBuildError(f"metrics output collision:{path.name}")
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


def write_metrics_candidate(
    output_root: Path,
    *,
    documents: Mapping[str, Mapping[str, object]],
    input_sha256: str,
    registry_sha256: str,
    source_facts_validation_receipt_sha256: str,
) -> dict[str, object]:
    if set(documents) != {"brand_health", "metrics", "periodized_metrics"}:
        raise MetricsBuildError("metrics document set is invalid")
    input_sha256 = _hex(input_sha256, "metrics input SHA")
    registry_sha256 = _hex(registry_sha256, "registry SHA")
    receipt_sha = _hex(
        source_facts_validation_receipt_sha256,
        "source facts validation receipt SHA",
    )
    payloads = {
        "brand-health.json": canonical_json_bytes(documents["brand_health"]) + b"\n",
        "metrics.json": canonical_json_bytes(documents["metrics"]) + b"\n",
        "periodized-metrics.json": (
            canonical_json_bytes(documents["periodized_metrics"]) + b"\n"
        ),
    }
    files = {
        name: {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}
        for name, payload in sorted(payloads.items())
    }
    metrics = documents["metrics"]
    periodized = documents["periodized_metrics"]
    manifest = {
        "artifact_stage": "metrics_candidate",
        "boundaries": dict(EXPECTED_BOUNDARIES),
        "consumption_status": "candidate_pending_independent_validation",
        "core_indicator_count": metrics.get("core_indicator_count"),
        "files": files,
        "indicator_count": metrics.get("indicator_count"),
        "input_sha256": input_sha256,
        "integrity_indicator_count": metrics.get("integrity_indicator_count"),
        "period_count": periodized.get("period_count"),
        "periodized_brand_health_row_count": periodized.get(
            "brand_health_row_count"
        ),
        "periodized_brand_health_dimension_row_count": periodized.get(
            "brand_health_dimension_row_count"
        ),
        "periodized_metric_row_count": periodized.get("metric_row_count"),
        "promotable": False,
        "registry_sha256": registry_sha256,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_facts_validation_receipt_sha256": receipt_sha,
    }
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    output_root = Path(output_root)
    if output_root.is_symlink() or (output_root.exists() and not output_root.is_dir()):
        raise MetricsBuildError("metrics output root is invalid")
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    undeclared = {
        path.name for path in output_root.iterdir()
    } - {
        "brand-health.json",
        "manifest.json",
        "metrics.json",
        "periodized-metrics.json",
    }
    if undeclared:
        raise MetricsBuildError("metrics output root contains undeclared entries")
    statuses = {
        name: _write_exact(output_root / name, payload)
        for name, payload in sorted(payloads.items())
    }
    statuses["manifest.json"] = _write_exact(
        output_root / "manifest.json", manifest_payload
    )
    return {
        "manifest": manifest,
        "manifest_sha256": sha256(manifest_payload).hexdigest(),
        "write_status": statuses,
    }


def validate_upstream_binding(
    *,
    source_manifest: Mapping[str, object],
    source_manifest_sha256: str,
    source_receipt: Mapping[str, object],
) -> None:
    source_manifest_sha256 = _hex(source_manifest_sha256, "source manifest SHA")
    if not isinstance(source_manifest, Mapping):
        raise MetricsBuildError("source facts manifest is invalid")
    if not isinstance(source_receipt, Mapping):
        raise MetricsBuildError("source validation receipt is invalid")
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
        raise MetricsBuildError("blocked upstream facts cannot build formal metrics")
    if source_receipt.get("snapshot_manifest_sha256") != source_manifest_sha256:
        raise MetricsBuildError("source validation receipt manifest binding mismatch")
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
        raise MetricsBuildError("source facts manifest lifecycle is invalid")
    boundaries = source_manifest.get("boundaries")
    if boundaries != EXPECTED_BOUNDARIES or source_receipt.get("boundaries") != EXPECTED_BOUNDARIES:
        raise MetricsBuildError("source facts boundaries are invalid")


def _load_canonical_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricsBuildError(f"{label} is unreadable") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise MetricsBuildError(f"{label} is not canonical JSON")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--source-facts-manifest", type=Path, required=True)
    parser.add_argument("--source-facts-manifest-sha256", required=True)
    parser.add_argument("--source-facts-validation-receipt", type=Path, required=True)
    parser.add_argument("--source-facts-validation-receipt-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    expected_input_sha = _hex(args.input_sha256, "metrics input SHA")
    expected_registry_sha = _hex(args.registry_sha256, "registry SHA")
    expected_manifest_sha = _hex(
        args.source_facts_manifest_sha256, "source facts manifest SHA"
    )
    expected_receipt_sha = _hex(
        args.source_facts_validation_receipt_sha256,
        "source facts validation receipt SHA",
    )
    if _sha(args.input) != expected_input_sha:
        raise MetricsBuildError("metrics input SHA mismatch")
    if _sha(args.registry) != expected_registry_sha:
        raise MetricsBuildError("registry SHA mismatch")
    if _sha(args.source_facts_manifest) != expected_manifest_sha:
        raise MetricsBuildError("source facts manifest SHA mismatch")
    if _sha(args.source_facts_validation_receipt) != expected_receipt_sha:
        raise MetricsBuildError("source facts validation receipt SHA mismatch")
    input_document = _load_canonical_object(args.input, "metrics input")
    source_manifest = _load_canonical_object(
        args.source_facts_manifest, "source facts manifest"
    )
    source_receipt = _load_canonical_object(
        args.source_facts_validation_receipt,
        "source facts validation receipt",
    )
    validate_upstream_binding(
        source_manifest=source_manifest,
        source_manifest_sha256=expected_manifest_sha,
        source_receipt=source_receipt,
    )
    if input_document.get("source_facts_manifest_sha256") != expected_manifest_sha:
        raise MetricsBuildError("metrics input source facts manifest binding mismatch")
    registry = load_indicator_registry(args.registry)
    documents = build_metrics_documents(input_document, registry=registry)
    result = write_metrics_candidate(
        args.output_root,
        documents=documents,
        input_sha256=expected_input_sha,
        registry_sha256=expected_registry_sha,
        source_facts_validation_receipt_sha256=expected_receipt_sha,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
