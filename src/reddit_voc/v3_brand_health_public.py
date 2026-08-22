"""Build and validate the privacy-safe public V3 brand-health projection."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from reddit_voc.v3_integrity_snapshot import canonical_json_document, sha256_bytes


PUBLIC_MANIFEST_SCHEMA = "reddit_voc_brand_health_public_manifest_v1"
PUBLIC_DATA_SCHEMA = "reddit_voc_brand_health_public_v1"
PUBLIC_FILES = ("brand-health.json",)
SOURCE_MANIFEST_SCHEMA = "reddit_voc_metrics_candidate_manifest_v1"
SOURCE_RECEIPT_SCHEMA = "reddit_voc_metrics_validation_receipt_v1"
SOURCE_DATA_SCHEMA = "reddit_voc_brand_health_index_v2"
COMPARISON_SIDE = "qualified_organic"
DIMENSIONS = (
    ("reputation", "口碑健康"),
    ("product_experience", "产品体验"),
    ("recommendation_trust", "推荐信任"),
    ("risk_resilience", "风险韧性"),
)
SOURCE_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
PUBLIC_BOUNDARIES = {
    **SOURCE_BOUNDARIES,
    "contains_authors": False,
    "contains_entity_ids": False,
    "contains_source_text": False,
    "overall_score_derived_from_axes": False,
    "pii_removed": True,
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FORBIDDEN_KEYS = {
    "author",
    "authors",
    "denominator_member_ids",
    "excluded_entity_ids",
    "included_entity_ids",
    "numerator_member_ids",
    "text",
    "title",
    "url",
    "username",
}


class BrandHealthPublicProjectionError(ValueError):
    """A source or public artifact violates the fixed projection contract."""


def _read_json(path: Path, label: str, *, canonical: bool = False) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise BrandHealthPublicProjectionError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrandHealthPublicProjectionError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise BrandHealthPublicProjectionError(f"{label} must be an object")
    if canonical and canonical_json_document(value) != payload:
        raise BrandHealthPublicProjectionError(f"{label} is not canonical JSON")
    return value, payload


def _require_sha(value: str, label: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise BrandHealthPublicProjectionError(f"{label} SHA-256 is invalid")


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise BrandHealthPublicProjectionError(f"{label} fields do not match the contract")


def _validate_source(
    *,
    metrics_root: Path,
    expected_metrics_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _require_sha(expected_metrics_manifest_sha256, "expected metrics manifest")
    _require_sha(expected_receipt_sha256, "expected validation receipt")
    root = Path(metrics_root)
    if root.is_symlink() or not root.is_dir():
        raise BrandHealthPublicProjectionError("metrics root must be a directory")
    manifest, manifest_payload = _read_json(root / "manifest.json", "metrics manifest", canonical=True)
    receipt, receipt_payload = _read_json(Path(receipt_path), "metrics validation receipt", canonical=True)
    brand_health, brand_payload = _read_json(root / "brand-health.json", "brand health", canonical=True)
    if sha256_bytes(manifest_payload) != expected_metrics_manifest_sha256:
        raise BrandHealthPublicProjectionError("metrics manifest SHA-256 mismatch")
    if sha256_bytes(receipt_payload) != expected_receipt_sha256:
        raise BrandHealthPublicProjectionError("validation receipt SHA-256 mismatch")
    if (
        manifest.get("schema_version") != SOURCE_MANIFEST_SCHEMA
        or manifest.get("artifact_stage") != "metrics_candidate"
        or manifest.get("consumption_status") != "candidate_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("boundaries") != SOURCE_BOUNDARIES
    ):
        raise BrandHealthPublicProjectionError("metrics manifest is not an eligible validated candidate")
    files = manifest.get("files")
    brand_contract = files.get("brand-health.json") if isinstance(files, Mapping) else None
    if (
        not isinstance(brand_contract, Mapping)
        or brand_contract.get("bytes") != len(brand_payload)
        or brand_contract.get("sha256") != sha256_bytes(brand_payload)
    ):
        raise BrandHealthPublicProjectionError("brand-health source file contract mismatch")
    if (
        receipt.get("schema_version") != SOURCE_RECEIPT_SCHEMA
        or receipt.get("status") != "passed_candidate_only"
        or receipt.get("promotable") is not True
        or receipt.get("brand_health_recomputed") is not True
        or receipt.get("deterministic_full_byte_replay") is not True
        or receipt.get("bundle_manifest_sha256") != expected_metrics_manifest_sha256
        or receipt.get("boundaries") != SOURCE_BOUNDARIES
    ):
        raise BrandHealthPublicProjectionError("metrics validation receipt is not eligible")
    _require_exact_keys(
        brand_health,
        {
            "boundaries", "decimal_places", "index_version", "lineage", "period",
            "qualified_organic", "raw_observed", "schema_version", "scope",
            "sensitivity_difference",
        },
        "brand health",
    )
    lineage = brand_health.get("lineage")
    if (
        brand_health.get("schema_version") != SOURCE_DATA_SCHEMA
        or brand_health.get("index_version") != "brand_health_index_v2"
        or brand_health.get("scope") != "momcozy"
        or brand_health.get("period") != "all_observed_history"
        or brand_health.get("decimal_places") != 2
        or brand_health.get("boundaries") != SOURCE_BOUNDARIES
        or not isinstance(lineage, Mapping)
        or not isinstance(lineage.get("source_snapshot_id"), str)
        or SHA256_RE.fullmatch(str(lineage.get("source_facts_manifest_sha256"))) is None
    ):
        raise BrandHealthPublicProjectionError("brand health source semantics are invalid")
    side = brand_health.get(COMPARISON_SIDE)
    if not isinstance(side, Mapping) or side.get("comparison_side") != COMPARISON_SIDE:
        raise BrandHealthPublicProjectionError("qualified organic comparison side is missing")
    dimensions = side.get("dimensions")
    if not isinstance(dimensions, Mapping) or set(dimensions) != {item[0] for item in DIMENSIONS}:
        raise BrandHealthPublicProjectionError("brand health dimensions are incomplete")
    return manifest, receipt, brand_health


def _score(value: Any, status: Any, label: str) -> float | None:
    if status == "unavailable":
        if value is not None:
            raise BrandHealthPublicProjectionError(f"{label} unavailable score must be null")
        return None
    if status not in {"available", "provisional"}:
        raise BrandHealthPublicProjectionError(f"{label} status is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BrandHealthPublicProjectionError(f"{label} score is invalid") from exc
    if not 0 <= result <= 100:
        raise BrandHealthPublicProjectionError(f"{label} score is outside 0..100")
    return result


def _reason_codes(value: Any, status: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise BrandHealthPublicProjectionError(f"{label} reason codes are invalid")
    if status == "unavailable" and not value:
        raise BrandHealthPublicProjectionError(f"{label} unavailable state needs a reason")
    return list(value)


def _project_data(
    *,
    brand_health: Mapping[str, Any],
    projection_id: str,
    source_manifest_sha256: str,
    source_receipt_sha256: str,
    source_brand_health_sha256: str,
) -> dict[str, Any]:
    side = brand_health[COMPARISON_SIDE]
    dimensions_source = side["dimensions"]
    dimensions: list[dict[str, Any]] = []
    for dimension_id, label in DIMENSIONS:
        source = dimensions_source[dimension_id]
        if not isinstance(source, Mapping) or source.get("dimension_id") != dimension_id:
            raise BrandHealthPublicProjectionError(f"{dimension_id} source is invalid")
        status = source.get("status")
        dimensions.append(
            {
                "dimension_id": dimension_id,
                "label": label,
                "reason_codes": _reason_codes(source.get("reason_codes"), status, dimension_id),
                "score": _score(source.get("value"), status, dimension_id),
                "status": status,
            }
        )
    total = side.get("total")
    if not isinstance(total, Mapping):
        raise BrandHealthPublicProjectionError("brand health total is missing")
    total_status = total.get("status")
    overall = {
        "reason_codes": _reason_codes(total.get("reason_codes"), total_status, "overall"),
        "score": _score(total.get("value"), total_status, "overall"),
        "status": total_status,
    }
    lineage = brand_health["lineage"]
    return {
        "boundaries": dict(PUBLIC_BOUNDARIES),
        "brand_name": "Momcozy",
        "comparison_side": COMPARISON_SIDE,
        "dimensions": dimensions,
        "overall": overall,
        "period": "all_observed_history",
        "projection_id": projection_id,
        "schema_version": PUBLIC_DATA_SCHEMA,
        "source": {
            "brand_health_sha256": source_brand_health_sha256,
            "facts_manifest_sha256": lineage["source_facts_manifest_sha256"],
            "metrics_manifest_sha256": source_manifest_sha256,
            "metrics_validation_receipt_sha256": source_receipt_sha256,
            "snapshot_id": lineage["source_snapshot_id"],
        },
    }


def _file_contract(payload: bytes) -> dict[str, Any]:
    return {"bytes": len(payload), "media_type": "application/json", "sha256": sha256_bytes(payload)}


def _walk_forbidden(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in FORBIDDEN_KEYS:
                raise BrandHealthPublicProjectionError(f"public data contains forbidden field: {key}")
            _walk_forbidden(nested)
    elif isinstance(value, list):
        for nested in value:
            _walk_forbidden(nested)


def build_public_projection(
    *,
    metrics_root: Path,
    expected_metrics_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    output_root: Path,
    projection_id: str,
) -> dict[str, Any]:
    if not projection_id.strip():
        raise BrandHealthPublicProjectionError("projection_id is required")
    _, _, brand_health = _validate_source(
        metrics_root=metrics_root,
        expected_metrics_manifest_sha256=expected_metrics_manifest_sha256,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
    )
    brand_payload = (Path(metrics_root) / "brand-health.json").read_bytes()
    data = _project_data(
        brand_health=brand_health,
        projection_id=projection_id,
        source_manifest_sha256=expected_metrics_manifest_sha256,
        source_receipt_sha256=expected_receipt_sha256,
        source_brand_health_sha256=sha256_bytes(brand_payload),
    )
    _walk_forbidden(data)
    data_payload = canonical_json_document(data)
    manifest = {
        "boundaries": dict(PUBLIC_BOUNDARIES),
        "comparison_side": COMPARISON_SIDE,
        "files": {"brand-health.json": _file_contract(data_payload)},
        "projection_id": projection_id,
        "schema_version": PUBLIC_MANIFEST_SCHEMA,
        "source_brand_health_sha256": sha256_bytes(brand_payload),
        "source_metrics_manifest_sha256": expected_metrics_manifest_sha256,
        "source_metrics_validation_receipt_sha256": expected_receipt_sha256,
        "source_snapshot_id": brand_health["lineage"]["source_snapshot_id"],
        "status": "ready",
    }
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    extras = {entry.name for entry in output.iterdir()} - {"manifest.json", *PUBLIC_FILES}
    if extras:
        raise BrandHealthPublicProjectionError("public output contains undeclared entries")
    (output / "brand-health.json").write_bytes(data_payload)
    manifest_payload = canonical_json_document(manifest)
    (output / "manifest.json").write_bytes(manifest_payload)
    return {
        "data_sha256": sha256_bytes(data_payload),
        "manifest_sha256": sha256_bytes(manifest_payload),
        "projection_id": projection_id,
    }


def validate_public_projection(*, output_root: Path, expected_manifest_sha256: str) -> dict[str, Any]:
    _require_sha(expected_manifest_sha256, "expected public manifest")
    output = Path(output_root)
    if output.is_symlink() or not output.is_dir():
        raise BrandHealthPublicProjectionError("public output must be a directory")
    if {entry.name for entry in output.iterdir()} != {"manifest.json", *PUBLIC_FILES}:
        raise BrandHealthPublicProjectionError("public output entries do not match the contract")
    manifest, manifest_payload = _read_json(output / "manifest.json", "public manifest", canonical=True)
    data, data_payload = _read_json(output / "brand-health.json", "public data", canonical=True)
    if sha256_bytes(manifest_payload) != expected_manifest_sha256:
        raise BrandHealthPublicProjectionError("public manifest SHA-256 mismatch")
    _require_exact_keys(
        manifest,
        {
            "boundaries", "comparison_side", "files", "projection_id", "schema_version",
            "source_brand_health_sha256", "source_metrics_manifest_sha256",
            "source_metrics_validation_receipt_sha256", "source_snapshot_id", "status",
        },
        "public manifest",
    )
    if (
        manifest.get("schema_version") != PUBLIC_MANIFEST_SCHEMA
        or manifest.get("status") != "ready"
        or manifest.get("comparison_side") != COMPARISON_SIDE
        or manifest.get("boundaries") != PUBLIC_BOUNDARIES
    ):
        raise BrandHealthPublicProjectionError("public manifest semantics are invalid")
    for key in (
        "source_brand_health_sha256",
        "source_metrics_manifest_sha256",
        "source_metrics_validation_receipt_sha256",
    ):
        _require_sha(str(manifest.get(key)), key)
    files = manifest.get("files")
    contract = files.get("brand-health.json") if isinstance(files, Mapping) else None
    if (
        not isinstance(contract, Mapping)
        or set(contract) != {"bytes", "media_type", "sha256"}
        or contract.get("media_type") != "application/json"
        or contract.get("bytes") != len(data_payload)
        or contract.get("sha256") != sha256_bytes(data_payload)
    ):
        raise BrandHealthPublicProjectionError("public data file contract mismatch")
    _require_exact_keys(
        data,
        {
            "boundaries", "brand_name", "comparison_side", "dimensions", "overall",
            "period", "projection_id", "schema_version", "source",
        },
        "public data",
    )
    if (
        data.get("schema_version") != PUBLIC_DATA_SCHEMA
        or data.get("brand_name") != "Momcozy"
        or data.get("comparison_side") != COMPARISON_SIDE
        or data.get("period") != "all_observed_history"
        or data.get("boundaries") != PUBLIC_BOUNDARIES
        or data.get("projection_id") != manifest.get("projection_id")
    ):
        raise BrandHealthPublicProjectionError("public data semantics are invalid")
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, list) or len(dimensions) != len(DIMENSIONS):
        raise BrandHealthPublicProjectionError("public dimensions are incomplete")
    for item, (dimension_id, label) in zip(dimensions, DIMENSIONS, strict=True):
        if not isinstance(item, Mapping):
            raise BrandHealthPublicProjectionError("public dimension must be an object")
        _require_exact_keys(item, {"dimension_id", "label", "reason_codes", "score", "status"}, dimension_id)
        if item.get("dimension_id") != dimension_id or item.get("label") != label:
            raise BrandHealthPublicProjectionError("public dimension order is invalid")
        _score(item.get("score"), item.get("status"), dimension_id)
        _reason_codes(item.get("reason_codes"), item.get("status"), dimension_id)
    overall = data.get("overall")
    if not isinstance(overall, Mapping):
        raise BrandHealthPublicProjectionError("public overall is missing")
    _require_exact_keys(overall, {"reason_codes", "score", "status"}, "public overall")
    _score(overall.get("score"), overall.get("status"), "public overall")
    _reason_codes(overall.get("reason_codes"), overall.get("status"), "public overall")
    dimension_scores = [item.get("score") for item in dimensions]
    if any(score is None for score in dimension_scores):
        if overall.get("status") != "unavailable" or overall.get("score") is not None:
            raise BrandHealthPublicProjectionError(
                "public overall must be unavailable while any dimension is unavailable"
            )
    elif overall.get("status") == "unavailable" or overall.get("score") is None:
        raise BrandHealthPublicProjectionError(
            "public overall must be present when every dimension is computable"
        )
    source = data.get("source")
    if not isinstance(source, Mapping) or set(source) != {
        "brand_health_sha256", "facts_manifest_sha256", "metrics_manifest_sha256",
        "metrics_validation_receipt_sha256", "snapshot_id",
    }:
        raise BrandHealthPublicProjectionError("public source lineage is invalid")
    if (
        source.get("brand_health_sha256") != manifest.get("source_brand_health_sha256")
        or source.get("metrics_manifest_sha256") != manifest.get("source_metrics_manifest_sha256")
        or source.get("metrics_validation_receipt_sha256") != manifest.get("source_metrics_validation_receipt_sha256")
        or source.get("snapshot_id") != manifest.get("source_snapshot_id")
    ):
        raise BrandHealthPublicProjectionError("public source lineage mismatch")
    _walk_forbidden(data)
    return {
        "data_sha256": sha256_bytes(data_payload),
        "manifest_sha256": expected_manifest_sha256,
        "projection_id": manifest["projection_id"],
        "status": "passed",
    }
