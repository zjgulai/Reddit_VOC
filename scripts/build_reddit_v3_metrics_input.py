#!/usr/bin/env python3
"""Build the immutable, source-bound formal Reddit VOC V3 metrics input."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit_voc.v3_governed_signal_inputs import (  # noqa: E402
    EXPECTED_BOUNDARIES,
    load_formal_governed_signal_inputs,
)
from reddit_voc.v3_indicators import load_indicator_registry  # noqa: E402
from reddit_voc.v3_metrics_input import (  # noqa: E402
    MetricsInputError,
    canonical_json_bytes,
    materialize_metrics_input,
    metrics_input_manifest,
)
from reddit_voc.v3_periodized_metrics import (  # noqa: E402
    build_periodized_metrics_input,
    latest_acceleration_context,
)


GOVERNED_MANIFEST_SCHEMA = "reddit_voc_governed_signal_snapshot_v1"
GOVERNED_RECEIPT_SCHEMA = "reddit_voc_governed_signal_validation_receipt_v1"
FACTS_MANIFEST_SCHEMA = "reddit_voc_voc_facts_manifest_v2"
FACTS_RECEIPT_SCHEMA = "reddit_voc_voc_facts_validation_receipt_v2"
CANONICAL_MANIFEST_SCHEMA = "reddit_voc_canonical_snapshot_manifest_v1"
CANONICAL_RECEIPT_SCHEMA = "reddit_voc_canonical_snapshot_validation_receipt_v1"
CANONICAL_MANIFEST_SCHEMA_V2 = "reddit_voc_canonical_snapshot_manifest_v2"
CANONICAL_RECEIPT_SCHEMA_V2 = "reddit_voc_canonical_snapshot_validation_receipt_v2"
FACT_TABLES = (
    "commercial-relation-facts.jsonl",
    "community-governance-facts.jsonl",
    "entity-brand-facts.jsonl",
    "entity-problem-facts.jsonl",
    "entity-product-facts.jsonl",
    "entity-sentiment-facts.jsonl",
    "entity-tag-facts.jsonl",
    "integrity-signal-facts.jsonl",
)


class MetricsInputBuildError(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise MetricsInputBuildError(f"{label} must be a regular file")
    return path


def _bound_object(path: Path, expected_sha: str, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != expected_sha:
        raise MetricsInputBuildError(f"{label} SHA mismatch")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricsInputBuildError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise MetricsInputBuildError(f"{label} is not canonical JSON")
    return value


def _file_contract(root: Path, manifest: Mapping[str, object], name: str) -> Path:
    path = _regular(root / name, name)
    files = manifest.get("files")
    contract = files.get(name) if isinstance(files, Mapping) else None
    if (
        not isinstance(contract, Mapping)
        or set(contract) != {"bytes", "rows", "sha256"}
        or contract.get("bytes") != path.stat().st_size
        or contract.get("sha256") != _sha(path)
        or type(contract.get("rows")) is not int
        or int(contract["rows"]) < 0
    ):
        raise MetricsInputBuildError(f"{name} file contract mismatch")
    return path


def _jsonl(path: Path, expected_rows: int, label: str) -> Iterator[dict[str, Any]]:
    count = 0
    with _regular(path, label).open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith(b"\n") or line == b"\n":
                raise MetricsInputBuildError(f"{label} row framing is invalid")
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MetricsInputBuildError(
                    f"{label} row {line_number} is invalid"
                ) from exc
            if not isinstance(value, dict) or line != canonical_json_bytes(value) + b"\n":
                raise MetricsInputBuildError(
                    f"{label} row {line_number} is not canonical"
                )
            count += 1
            yield value
    if count != expected_rows:
        raise MetricsInputBuildError(f"{label} row count mismatch")


def _rows_for(root: Path, manifest: Mapping[str, object], name: str) -> Iterator[dict[str, Any]]:
    path = _file_contract(root, manifest, name)
    files = manifest["files"]
    assert isinstance(files, Mapping)
    contract = files[name]
    assert isinstance(contract, Mapping)
    return _jsonl(path, int(contract["rows"]), name)


def _validate_lifecycle(
    *,
    facts_manifest: Mapping[str, object],
    facts_receipt: Mapping[str, object],
    facts_manifest_sha: str,
    governed_manifest: Mapping[str, object],
    governed_receipt: Mapping[str, object],
    governed_manifest_sha: str,
    canonical_manifest: Mapping[str, object],
    canonical_receipt: Mapping[str, object],
    canonical_manifest_sha: str,
) -> None:
    if (
        facts_manifest.get("schema_version") != FACTS_MANIFEST_SCHEMA
        or facts_manifest.get("status") != "candidate_built"
        or facts_manifest.get("boundaries") != EXPECTED_BOUNDARIES
        or facts_receipt.get("schema_version") != FACTS_RECEIPT_SCHEMA
        or facts_receipt.get("status") != "passed"
        or facts_receipt.get("bundle_manifest_sha256") != facts_manifest_sha
        or facts_receipt.get("unaccounted_vocs") != 0
        or facts_receipt.get("unaccounted_eligibility_members") != 0
        or facts_receipt.get("boundaries") != EXPECTED_BOUNDARIES
    ):
        raise MetricsInputBuildError("Task4 facts lifecycle is invalid")
    governed_inputs = governed_manifest.get("inputs")
    if (
        governed_manifest.get("schema_version") != GOVERNED_MANIFEST_SCHEMA
        or governed_manifest.get("status") != "candidate_built"
        or governed_manifest.get("boundaries") != EXPECTED_BOUNDARIES
        or governed_receipt.get("schema_version") != GOVERNED_RECEIPT_SCHEMA
        or governed_receipt.get("status") != "passed"
        or governed_receipt.get("consumption_status")
        != "eligible_for_downstream_consumption"
        or governed_receipt.get("promotable") is not True
        or governed_receipt.get("snapshot_manifest_sha256") != governed_manifest_sha
        or governed_receipt.get("unaccounted_facts") != 0
        or governed_receipt.get("unaccounted_vocs") != 0
        or governed_receipt.get("boundaries") != EXPECTED_BOUNDARIES
        or not isinstance(governed_inputs, Mapping)
        or governed_inputs.get("facts_manifest_sha256") != facts_manifest_sha
    ):
        raise MetricsInputBuildError("Task5 governed lifecycle is invalid")
    if (
        canonical_manifest.get("schema_version") not in {
            CANONICAL_MANIFEST_SCHEMA,
            CANONICAL_MANIFEST_SCHEMA_V2,
        }
        or canonical_manifest.get("status") != "candidate_built"
        or canonical_manifest.get("boundaries") != EXPECTED_BOUNDARIES
        or canonical_receipt.get("schema_version")
        != (
            CANONICAL_RECEIPT_SCHEMA_V2
            if canonical_manifest.get("schema_version") == CANONICAL_MANIFEST_SCHEMA_V2
            else CANONICAL_RECEIPT_SCHEMA
        )
        or canonical_receipt.get("status") != "passed"
        or canonical_receipt.get("bundle_manifest_sha256") != canonical_manifest_sha
        or canonical_receipt.get("unaccounted_canonical_identities") != 0
        or canonical_receipt.get("unaccounted_foreign_keys") != 0
        or canonical_receipt.get("boundaries") != EXPECTED_BOUNDARIES
        or facts_manifest.get("inputs", {}).get("canonical_manifest_sha256")
        != canonical_manifest_sha
    ):
        raise MetricsInputBuildError("canonical snapshot lifecycle is invalid")


def build_formal_metrics_input(
    *,
    facts_root: Path,
    facts_manifest_sha256: str,
    facts_receipt_path: Path,
    facts_receipt_sha256: str,
    governed_root: Path,
    governed_manifest_sha256: str,
    governed_receipt_path: Path,
    governed_receipt_sha256: str,
    canonical_root: Path,
    canonical_manifest_sha256: str,
    canonical_receipt_path: Path,
    canonical_receipt_sha256: str,
    dim_tag_path: Path,
    product_entity_ledger_path: Path,
    closed_set_registry_path: Path,
    indicator_registry_path: Path,
    indicator_registry_sha256: str,
    period: str,
    scope: str,
    coverage_attestation_path: Path | None = None,
    coverage_attestation_sha256: str | None = None,
) -> tuple[dict[str, object], dict[str, int], dict[str, str]]:
    facts_root = Path(facts_root)
    governed_root = Path(governed_root)
    canonical_root = Path(canonical_root)
    facts_manifest = _bound_object(
        facts_root / "manifest.json", facts_manifest_sha256, "Task4 facts manifest"
    )
    facts_receipt = _bound_object(
        facts_receipt_path, facts_receipt_sha256, "Task4 facts receipt"
    )
    governed_manifest = _bound_object(
        governed_root / "manifest.json",
        governed_manifest_sha256,
        "Task5 governed manifest",
    )
    governed_receipt = _bound_object(
        governed_receipt_path,
        governed_receipt_sha256,
        "Task5 governed receipt",
    )
    canonical_manifest = _bound_object(
        canonical_root / "manifest.json",
        canonical_manifest_sha256,
        "canonical manifest",
    )
    canonical_receipt = _bound_object(
        canonical_receipt_path,
        canonical_receipt_sha256,
        "canonical receipt",
    )
    if (coverage_attestation_path is None) != (
        coverage_attestation_sha256 is None
    ):
        raise MetricsInputBuildError(
            "coverage attestation path and SHA must be paired"
        )
    coverage_attestation = (
        _bound_object(
            coverage_attestation_path,
            str(coverage_attestation_sha256),
            "coverage attestation",
        )
        if coverage_attestation_path is not None
        else None
    )
    _validate_lifecycle(
        facts_manifest=facts_manifest,
        facts_receipt=facts_receipt,
        facts_manifest_sha=facts_manifest_sha256,
        governed_manifest=governed_manifest,
        governed_receipt=governed_receipt,
        governed_manifest_sha=governed_manifest_sha256,
        canonical_manifest=canonical_manifest,
        canonical_receipt=canonical_receipt,
        canonical_manifest_sha=canonical_manifest_sha256,
    )
    formal = load_formal_governed_signal_inputs(
        facts_root=facts_root,
        facts_receipt_path=facts_receipt_path,
        dim_tag_path=dim_tag_path,
        product_entity_ledger_path=product_entity_ledger_path,
        registry_path=closed_set_registry_path,
        facts_manifest_sha256=facts_manifest_sha256,
        facts_receipt_sha256=facts_receipt_sha256,
    )
    if _sha(indicator_registry_path) != indicator_registry_sha256:
        raise MetricsInputBuildError("indicator registry SHA mismatch")
    indicator_registry = load_indicator_registry(indicator_registry_path)

    fact_iterators = [
        _rows_for(governed_root, governed_manifest, name) for name in FACT_TABLES
    ]

    def governed_facts() -> Iterator[dict[str, Any]]:
        for rows in fact_iterators:
            yield from rows

    automation_rows = _rows_for(
        facts_root, facts_manifest, "automation-classifications.jsonl"
    )
    eligibility_rows = _rows_for(
        facts_root, facts_manifest, "metric-eligibility.jsonl"
    )
    canonical_posts = _rows_for(canonical_root, canonical_manifest, "posts.jsonl")
    canonical_comments = _rows_for(
        canonical_root, canonical_manifest, "comments.jsonl"
    )
    quarantine = _rows_for(
        canonical_root, canonical_manifest, "quarantine.jsonl"
    )
    result = materialize_metrics_input(
        vocs=formal.vocs,
        automation_voc_ids=formal.automation_voc_ids,
        automation_classifications=automation_rows,
        governed_facts=governed_facts(),
        source_eligibility_rows=eligibility_rows,
        canonical_posts=canonical_posts,
        canonical_comments=canonical_comments,
        quarantine_comments=quarantine,
        registry=indicator_registry,
        source_snapshot_id=formal.source_snapshot_id,
        source_facts_manifest_sha256=governed_manifest_sha256,
        period=period,
        scope=scope,
        expected_source_eligibility_rows=int(
            facts_manifest.get("counts", {}).get("eligibility_rows", -1)
        ),
        recommendation_closed_set_complete=True,
    )
    if (
        result.counts.get("source_fact_rows")
        != governed_manifest.get("counts", {}).get("fact_rows")
        or result.counts.get("promoted_source_facts")
        != governed_manifest.get("counts", {}).get("promoted_facts")
        or result.counts.get("held_source_facts")
        != governed_manifest.get("counts", {}).get("held_facts")
        or result.counts.get("rejected_source_facts")
        != governed_manifest.get("counts", {}).get("rejected_facts")
        or result.counts.get("organic_observations")
        != governed_receipt.get("counts", {}).get("organic_vocs")
        or result.counts.get("automation_excluded_vocs")
        != governed_receipt.get("counts", {}).get("automation_excluded_vocs")
        or {
            key: result.counts[key]
            for key in (
                "comments_jsonl",
                "linked_comments",
                "posts",
                "quarantined_comments",
                "stored_comments",
                "unresolved_parent_comments",
            )
        }
        != canonical_receipt.get("canonical_counts")
    ):
        raise MetricsInputBuildError("formal metrics input conservation mismatch")
    inputs = governed_manifest.get("inputs")
    assert isinstance(inputs, Mapping)
    files = facts_manifest.get("files")
    assert isinstance(files, Mapping)
    eligibility_contract = files.get("metric-eligibility.jsonl")
    assert isinstance(eligibility_contract, Mapping)
    bindings = {
        "automation_classifications_sha256": str(
            inputs["automation_classifications_sha256"]
        ),
        "canonical_manifest_sha256": canonical_manifest_sha256,
        "canonical_receipt_sha256": canonical_receipt_sha256,
        "facts_manifest_sha256": facts_manifest_sha256,
        "facts_receipt_sha256": facts_receipt_sha256,
        "governed_manifest_sha256": governed_manifest_sha256,
        "governed_receipt_sha256": governed_receipt_sha256,
        "indicator_registry_sha256": indicator_registry_sha256,
        "metric_eligibility_sha256": str(eligibility_contract["sha256"]),
        "vocs_sha256": str(inputs["vocs_sha256"]),
    }
    if coverage_attestation_sha256 is not None:
        bindings["data_owner_coverage_attestation_sha256"] = (
            coverage_attestation_sha256
        )
    periodized = build_periodized_metrics_input(
        observations=result.document["observations"],
        input_bindings=bindings,
        coverage_attestation=coverage_attestation,
        coverage_attestation_sha256=coverage_attestation_sha256,
        dataset_id=formal.source_snapshot_id,
        metric_policy_version=indicator_registry.registry_version,
        scope=scope,
        source_snapshot_id=formal.source_snapshot_id,
    )
    document = dict(result.document)
    context = {
        str(key): dict(value)
        for key, value in document["context"].items()
        if isinstance(value, Mapping)
    }
    context["RV-IN-05"] = latest_acceleration_context(periodized)
    document["context"] = context
    document["periodized_metrics_input"] = periodized
    counts = dict(result.counts)
    counts["periodized_periods"] = len(periodized["periods"])
    counts["periodized_complete_periods"] = sum(
        row["coverage_complete"] is True for row in periodized["periods"]
    )
    counts["periodized_empty_periods"] = sum(
        not row["member_ids"] for row in periodized["periods"]
    )
    return document, counts, bindings


def write_bundle(
    *,
    output_root: Path,
    document: Mapping[str, object],
    counts: Mapping[str, int],
    bindings: Mapping[str, str],
) -> dict[str, object]:
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise MetricsInputBuildError("metrics input output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.parent / f".{output_root.name}.building"
    if staging.exists() or staging.is_symlink():
        raise MetricsInputBuildError("metrics input staging root already exists")
    payload = canonical_json_bytes(document) + b"\n"
    manifest = metrics_input_manifest(
        document_payload=payload,
        counts=counts,
        input_bindings=bindings,
        source_snapshot_id=str(document["source_snapshot_id"]),
    )
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    staging.mkdir(mode=0o700)
    try:
        (staging / "metrics-input.json").write_bytes(payload)
        (staging / "manifest.json").write_bytes(manifest_payload)
        staging.rename(output_root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "counts": dict(counts),
        "input_sha256": sha256(payload).hexdigest(),
        "manifest_sha256": sha256(manifest_payload).hexdigest(),
        "status": "candidate_built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-root", type=Path, required=True)
    parser.add_argument("--facts-manifest-sha256", required=True)
    parser.add_argument("--facts-receipt", type=Path, required=True)
    parser.add_argument("--facts-receipt-sha256", required=True)
    parser.add_argument("--governed-root", type=Path, required=True)
    parser.add_argument("--governed-manifest-sha256", required=True)
    parser.add_argument("--governed-receipt", type=Path, required=True)
    parser.add_argument("--governed-receipt-sha256", required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--canonical-manifest-sha256", required=True)
    parser.add_argument("--canonical-receipt", type=Path, required=True)
    parser.add_argument("--canonical-receipt-sha256", required=True)
    parser.add_argument("--dim-tag", type=Path, required=True)
    parser.add_argument("--product-entity-ledger", type=Path, required=True)
    parser.add_argument("--closed-set-registry", type=Path, required=True)
    parser.add_argument("--indicator-registry", type=Path, required=True)
    parser.add_argument("--indicator-registry-sha256", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--coverage-attestation", type=Path)
    parser.add_argument("--coverage-attestation-sha256")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    document, counts, bindings = build_formal_metrics_input(
        facts_root=args.facts_root,
        facts_manifest_sha256=args.facts_manifest_sha256,
        facts_receipt_path=args.facts_receipt,
        facts_receipt_sha256=args.facts_receipt_sha256,
        governed_root=args.governed_root,
        governed_manifest_sha256=args.governed_manifest_sha256,
        governed_receipt_path=args.governed_receipt,
        governed_receipt_sha256=args.governed_receipt_sha256,
        canonical_root=args.canonical_root,
        canonical_manifest_sha256=args.canonical_manifest_sha256,
        canonical_receipt_path=args.canonical_receipt,
        canonical_receipt_sha256=args.canonical_receipt_sha256,
        dim_tag_path=args.dim_tag,
        product_entity_ledger_path=args.product_entity_ledger,
        closed_set_registry_path=args.closed_set_registry,
        indicator_registry_path=args.indicator_registry,
        indicator_registry_sha256=args.indicator_registry_sha256,
        period=args.period,
        scope=args.scope,
        coverage_attestation_path=args.coverage_attestation,
        coverage_attestation_sha256=args.coverage_attestation_sha256,
    )
    result = write_bundle(
        output_root=args.output_root,
        document=document,
        counts=counts,
        bindings=bindings,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
