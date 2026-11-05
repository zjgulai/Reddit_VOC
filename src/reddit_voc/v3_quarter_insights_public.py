"""Build and independently validate the privacy-safe rolling-quarter insight projection.

The projection deliberately consumes governed V3 facts rather than attempting to
reconstruct Momcozy scope from the broader lexical fields in the public base.
Only aggregate counts, public-safe Reddit evidence IDs, persona assignment hashes,
method boundaries, and source lineage hashes leave this module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from reddit_voc.analyzer import analyze_text
from reddit_voc.rates import half_up_percent
from reddit_voc.v3_integrity_snapshot import canonical_json_document, sha256_bytes


PUBLIC_DATA_SCHEMA = "reddit_voc_quarter_insights_public_v1"
PUBLIC_MANIFEST_SCHEMA = "reddit_voc_quarter_insights_public_manifest_v1"
PUBLIC_FILES = ("quarter-insights.json",)
REPORTING_TIMEZONE = "Asia/Shanghai"
ROLLING_QUARTER_DAYS = 90
GENERATED_AT_UTC = "2026-07-16T00:00:00+00:00"
EXPECTED_DATASET_VERSION = "reddit_voc_quarter_insights_20260716_public_a1"
DATASET_VERSION_RE = re.compile(r"reddit_voc_quarter_insights_[a-z0-9_]+")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
POST_ID_RE = re.compile(r"[a-z0-9]+")
COMMENT_ID_RE = re.compile(r"t1_[a-z0-9]+")

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
    "author_fields_excluded": True,
    "automation_comment_count_corrected_from_utc_boundary_undercount": True,
    "automation_comments_are_not_brand_attribution": True,
    "brand_bot_attribution_confirmed": False,
    "case_references_are_method_only": True,
    "counts_are_content_entities_not_users": True,
    "market_share_supported": False,
    "population_share_supported": False,
    "private_paths_excluded": True,
    "quarter_moderation_claim_evidence_is_allowlisted_not_total": True,
    "rankings_are_non_exclusive": True,
    "source_text_excluded": True,
}

PAIN_LABELS = {
    "operations": "操作与可靠性",
    "fit_comfort": "适配与舒适度",
    "output_supply": "泌乳输出与供给",
    "family_scenario": "家庭使用场景",
    "support": "售后支持",
    "work_scenario": "工作使用场景",
    "leakage": "泄漏",
    "insurance": "保险与支付",
    "health": "健康相关",
}
CATEGORY_LABELS = {
    "breast_pump": "吸奶器",
    "bottle_washer": "奶瓶清洗消毒器",
}
FAMILY_LABELS = {
    "m5-smart": "M5 Smart 产品家族",
    "m6-mobile-style": "M6 Mobile Style 产品家族",
    "s9-pro": "S9 Pro 产品家族",
    "s12-pro-quick": "S12 Pro Quick 产品家族",
    "v2-pro": "V2 Pro 产品家族",
    "m9-mobile-flow": "M9 Mobile Flow 产品家族",
    "kleanpal-pro": "KleanPal Pro 产品家族",
    "v1-pro": "V1 Pro 产品家族",
    "air-1": "Air 1 产品家族",
}
BRAND_LABELS = {
    "spectra": "Spectra",
    "medela": "Medela",
    "philips avent": "Philips Avent",
    "babybjorn": "BabyBjorn",
    "baby bjorn": "BabyBjorn",
    "avent": "Avent",
    "dr browns": "Dr. Brown's",
    "lansinoh": "Lansinoh",
}
COHORT_ORDER = (
    "scenario_adapter",
    "product_evaluator",
    "purchase_decision",
    "competitor_comparer",
    "recommendation_expression",
    "service_support_seeker",
    "operations_troubleshooter",
    "fit_output_optimizer",
)
EVIDENCE: dict[str, tuple[dict[str, str | None], ...]] = {
    "pain": (
        {"post_id": "1u9zf0q", "comment_id": None, "reason": "安全与售后问题证据"},
        {"post_id": "1usqihm", "comment_id": None, "reason": "设备故障与更换延迟证据"},
        {"post_id": "1uq90k8", "comment_id": None, "reason": "耐用性与售后争议证据"},
        {"post_id": "1um4njp", "comment_id": None, "reason": "吸力故障排查证据"},
        {"post_id": "1ut5fgi", "comment_id": None, "reason": "M5 泄漏证据"},
    ),
    "reputation": (
        {
            "post_id": "1uubl6f",
            "comment_id": "t1_ox33k0h",
            "reason": "社区管理员自动移除规则信号；不构成品牌机器人归因",
        },
        {"post_id": "1u9zf0q", "comment_id": None, "reason": "高互动安全与售后风险证据"},
        {"post_id": "1usqihm", "comment_id": None, "reason": "更换延迟风险证据"},
        {"post_id": "1uq90k8", "comment_id": None, "reason": "耐用性争议证据"},
        {"post_id": "1um4njp", "comment_id": None, "reason": "产品故障与用户自助排障证据"},
    ),
    "new_product": (
        {"post_id": "1umqmwp", "comment_id": None, "reason": "洗瓶机社区偏好与决策问题"},
        {"post_id": "1uc6pmz", "comment_id": None, "reason": "洗瓶机使用讨论"},
        {"post_id": "1uemhla", "comment_id": None, "reason": "M5 与竞品选择讨论"},
        {"post_id": "1uemi64", "comment_id": None, "reason": "背带尺寸适配问题"},
        {"post_id": "1ucv06p", "comment_id": None, "reason": "新生儿背带适配问题"},
    ),
    "geo": (
        {"post_id": "1umqmwp", "comment_id": None, "reason": "洗瓶机社区偏好问题"},
        {"post_id": "1uemhla", "comment_id": None, "reason": "Eufy E20 与 M5 比较问题"},
        {"post_id": "1u9u8q2", "comment_id": None, "reason": "M5 与 Spectra S1 供给影响问题"},
        {"post_id": "1uc8iy2", "comment_id": None, "reason": "Tushbaby 与 Momcozy 比较问题"},
        {"post_id": "1ursya6", "comment_id": None, "reason": "婴儿背带推荐问题"},
    ),
}

FORBIDDEN_KEYS = {
    "author",
    "authors",
    "body",
    "content",
    "entity_id",
    "permalink",
    "source_path",
    "source_text",
    "text",
    "title",
    "url",
    "username",
}


class QuarterInsightsPublicProjectionError(ValueError):
    """A source or public quarter projection violates the fixed contract."""


def _read_json(path: Path, label: str, *, canonical: bool = False) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise QuarterInsightsPublicProjectionError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuarterInsightsPublicProjectionError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise QuarterInsightsPublicProjectionError(f"{label} must be an object")
    if canonical and canonical_json_document(value) != payload:
        raise QuarterInsightsPublicProjectionError(f"{label} is not canonical JSON")
    return value, payload


def _read_jsonl(path: Path, label: str) -> Iterable[dict[str, Any]]:
    try:
        if path.is_symlink() or not path.is_file():
            raise QuarterInsightsPublicProjectionError(f"{label} must be a regular file")
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise QuarterInsightsPublicProjectionError(f"{label} is unreadable") from exc
    with handle:
        for ordinal, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise QuarterInsightsPublicProjectionError(
                    f"{label} row {ordinal} is invalid"
                ) from exc
            if not isinstance(value, dict):
                raise QuarterInsightsPublicProjectionError(
                    f"{label} row {ordinal} must be an object"
                )
            yield value


def _require_sha(value: str, label: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise QuarterInsightsPublicProjectionError(f"{label} SHA-256 is invalid")


def _file_contract(payload: bytes) -> dict[str, Any]:
    return {
        "bytes": len(payload),
        "media_type": "application/json",
        "sha256": sha256_bytes(payload),
    }


def _validate_declared_file(root: Path, manifest: Mapping[str, Any], name: str) -> None:
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise QuarterInsightsPublicProjectionError(f"source file is missing: {name}")
    payload = path.read_bytes()
    contract = manifest.get("files", {}).get(name)
    if (
        not isinstance(contract, Mapping)
        or contract.get("bytes") != len(payload)
        or contract.get("sha256") != sha256_bytes(payload)
        or contract.get("rows") != len(payload.splitlines())
    ):
        raise QuarterInsightsPublicProjectionError(f"source file contract mismatch: {name}")


def _load_pinned_source(
    *,
    root: Path,
    receipt_path: Path,
    expected_manifest_sha256: str,
    expected_receipt_sha256: str,
    manifest_schema: str | tuple[str, ...],
    receipt_schema: str | tuple[str, ...],
    receipt_manifest_field: str,
    required_files: tuple[str, ...],
    receipt_promotable: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_sha(expected_manifest_sha256, "expected source manifest")
    _require_sha(expected_receipt_sha256, "expected source receipt")
    if root.is_symlink() or not root.is_dir():
        raise QuarterInsightsPublicProjectionError("source root must be a directory")
    manifest, manifest_payload = _read_json(root / "manifest.json", "source manifest")
    receipt, receipt_payload = _read_json(receipt_path, "source validation receipt")
    if sha256_bytes(manifest_payload) != expected_manifest_sha256:
        raise QuarterInsightsPublicProjectionError("source manifest SHA-256 mismatch")
    if sha256_bytes(receipt_payload) != expected_receipt_sha256:
        raise QuarterInsightsPublicProjectionError("source receipt SHA-256 mismatch")
    manifest_schemas = (manifest_schema,) if isinstance(manifest_schema, str) else manifest_schema
    receipt_schemas = (receipt_schema,) if isinstance(receipt_schema, str) else receipt_schema
    if manifest.get("schema_version") not in manifest_schemas or manifest.get("status") != "candidate_built":
        raise QuarterInsightsPublicProjectionError("source manifest semantics are invalid")
    if (
        receipt.get("schema_version") not in receipt_schemas
        or receipt.get("status") != "passed"
        or receipt.get("promotable") is not receipt_promotable
        or receipt.get(receipt_manifest_field) != expected_manifest_sha256
    ):
        raise QuarterInsightsPublicProjectionError("source validation receipt semantics are invalid")
    boundaries = manifest.get("boundaries")
    if (
        not isinstance(boundaries, Mapping)
        or any(boundaries.get(key) is not value for key, value in SOURCE_BOUNDARIES.items())
    ):
        raise QuarterInsightsPublicProjectionError("source side-effect boundaries are invalid")
    for name in required_files:
        _validate_declared_file(root, manifest, name)
    return manifest, receipt


def _source_component(
    source_root: Path,
    current_name: str,
    legacy_name: str,
    alternate_name: str | None = None,
) -> Path:
    """Resolve the current orchestration layout while retaining legacy replay support."""
    current = source_root / current_name
    if current.exists():
        return current
    if alternate_name is not None:
        alternate = source_root / alternate_name
        if alternate.exists():
            return alternate
    return source_root / legacy_name


def _calendar_date(row: Mapping[str, Any]) -> date:
    precision = row.get("event_time_precision")
    if precision == "day":
        value = row.get("source_calendar_date")
        if not isinstance(value, str):
            raise QuarterInsightsPublicProjectionError("day-precision source date is missing")
        return date.fromisoformat(value)
    value = row.get("event_created_at_utc") or row.get("created_at_utc")
    if not isinstance(value, str):
        raise QuarterInsightsPublicProjectionError("event timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise QuarterInsightsPublicProjectionError("event timestamp lacks timezone")
    return parsed.astimezone(ZoneInfo(REPORTING_TIMEZONE)).date()


def _record_calendar_date(record: Mapping[str, Any]) -> date | None:
    if record.get("event_time_precision") == "day":
        value = record.get("source_calendar_date")
        return date.fromisoformat(value) if isinstance(value, str) else None
    value = record.get("event_created_at_utc") or record.get("created_at_utc")
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(ZoneInfo(REPORTING_TIMEZONE)).date()
    value = record.get("source_calendar_date")
    return date.fromisoformat(value) if isinstance(value, str) else None


def _ranking(counts: Mapping[str, int], labels: Mapping[str, str], limit: int | None = None) -> list[dict[str, Any]]:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        ordered = ordered[:limit]
    return [
        {"id": key, "label": labels.get(key, key), "count": value}
        for key, value in ordered
    ]


def _sentiment(counter: Mapping[str, int]) -> dict[str, Any]:
    positive = int(counter.get("positive", 0))
    neutral = int(counter.get("neutral", 0))
    negative = int(counter.get("negative", 0))
    missing = int(counter.get("missing", 0))
    classified = positive + neutral + negative
    return {
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
        "missing": missing,
        "classified": classified,
        "negative_rate": half_up_percent(negative, classified),
        "negative_rate_denominator": "classified",
        "negative_rate_unit": "percent",
    }


def _analysis_for_record(record: Mapping[str, Any], entity_type: str) -> dict[str, Any]:
    """Return a usable sentiment analysis without calling an external provider.

    Incremental canonical rows can legitimately arrive before the optional NLP
    enrichment stage.  The public base projection already falls back to the
    deterministic local analyzer for those rows; the quarter projection must do
    the same so a fresh day is not silently rendered as a missing trend point.
    Existing classified analysis always remains authoritative.
    """
    existing = record.get("analysis")
    if isinstance(existing, Mapping) and existing.get("sentiment_label") in {
        "positive", "neutral", "negative"
    }:
        return dict(existing)

    if entity_type == "post":
        parts = (record.get("title"), record.get("content"))
    else:
        parts = (record.get("body"),)
    text = "\n".join(str(value).strip() for value in parts if isinstance(value, str) and value.strip())
    if not text:
        for fallback_key in ("source_text", "source_summary"):
            fallback = record.get(fallback_key)
            if isinstance(fallback, str) and fallback.strip():
                text = fallback.strip()
                break

    analysis = analyze_text(text)
    return {
        "analysis_version": "local_rules_v1",
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": analysis.sentiment_score,
        "topic": analysis.topic,
        "severity": analysis.severity,
        "confidence": analysis.confidence,
        "pain_points": analysis.pain_points,
        "provider_call": False,
    }


def _window_projection(
    *,
    window_id: str,
    days: int,
    anchor: date,
    vocs: Mapping[str, Mapping[str, Any]],
    voc_dates: Mapping[str, date],
    brand_vocs: Mapping[str, set[str]],
    analyses: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    start = anchor - timedelta(days=days - 1)
    momcozy = {
        voc_id for voc_id in brand_vocs.get("momcozy", set())
        if start <= voc_dates.get(voc_id, date.min) <= anchor
    }
    type_counts = Counter(str(vocs[voc_id].get("voc_type")) for voc_id in momcozy)
    sentiments = Counter(
        str(analyses.get(str(vocs[voc_id].get("canonical_entity_id")), {}).get("sentiment_label") or "missing")
        for voc_id in momcozy
    )
    competitors: list[tuple[int, str]] = []
    for brand_id, member_ids in brand_vocs.items():
        if brand_id == "momcozy":
            continue
        count = sum(start <= voc_dates.get(voc_id, date.min) <= anchor for voc_id in member_ids)
        if count:
            competitors.append((count, brand_id))
    competitors.sort(key=lambda item: (-item[0], item[1]))
    top_count, top_id = competitors[0]
    grain = "month" if days == 183 else "day"
    buckets: dict[str, set[str]] = defaultdict(set)
    for voc_id in momcozy:
        value = voc_dates[voc_id]
        bucket = value.strftime("%Y-%m") if grain == "month" else value.isoformat()
        buckets[bucket].add(voc_id)
    bucket_rows: list[dict[str, Any]] = []
    for bucket, members in sorted(buckets.items()):
        bucket_types = Counter(str(vocs[voc_id].get("voc_type")) for voc_id in members)
        bucket_sentiments = Counter(
            str(analyses.get(str(vocs[voc_id].get("canonical_entity_id")), {}).get("sentiment_label") or "missing")
            for voc_id in members
        )
        sentiment = _sentiment(bucket_sentiments)
        bucket_rows.append({
            "bucket": bucket,
            "post_vocs": bucket_types["post_voc"],
            "comment_context_vocs": bucket_types["comment_context_voc"],
            "total_vocs": len(members),
            "negative_vocs": sentiment["negative"],
            "classified_vocs": sentiment["classified"],
            "negative_rate": sentiment["negative_rate"],
        })
    sentiment = _sentiment(sentiments)
    return {
        "id": window_id,
        "start_date": start.isoformat(),
        "end_date": anchor.isoformat(),
        "days": days,
        "bucket_grain": grain,
        "momcozy": {
            "post_vocs": type_counts["post_voc"],
            "comment_context_vocs": type_counts["comment_context_voc"],
            "total_vocs": len(momcozy),
            "negative_vocs": sentiment["negative"],
            "classified_vocs": sentiment["classified"],
            "negative_rate": sentiment["negative_rate"],
        },
        "top_competitor": {
            "id": top_id,
            "label": BRAND_LABELS.get(top_id, top_id.title()),
            "voc_count": top_count,
        },
        "buckets": bucket_rows,
    }


def _validate_source_lineage(
    *,
    source_root: Path,
    casebook_public_root: Path,
    product_ledger_path: Path,
    expected_hashes: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    required = {
        "canonical_manifest", "canonical_receipt", "voc_manifest", "voc_receipt",
        "governed_manifest", "governed_receipt", "persona_manifest", "persona_receipt",
        "casebook_public_manifest", "product_ledger",
    }
    if set(expected_hashes) != required:
        raise QuarterInsightsPublicProjectionError("expected source hashes are incomplete")
    canonical_root = _source_component(source_root, "canonical", "canonical-candidate-a1")
    canonical_receipt = _source_component(
        source_root,
        "canonical-validation/receipt.json",
        "canonical-validation-a1/receipt.json",
        "receipts/canonical-validation.json",
    )
    voc_root = _source_component(source_root, "voc-facts", "voc-facts-candidate-a2")
    voc_receipt = _source_component(
        source_root,
        "voc-facts-validation/receipt.json",
        "voc-facts-validation-a2/receipt.json",
        "receipts/voc-facts-validation.json",
    )
    governed_root = _source_component(
        source_root, "governed-signals", "governed-signals-candidate-a1"
    )
    governed_receipt = _source_component(
        source_root,
        "governed-signals-validation/receipt.json",
        "governed-signals-validation-a1/receipt.json",
    )
    persona_root = _source_component(source_root, "personas", "personas-candidate-a4")
    persona_receipt = _source_component(
        source_root,
        "personas-validation/receipt.json",
        "personas-validation-a4/receipt.json",
        "receipts/personas-validation.json",
    )
    canonical_manifest, _ = _load_pinned_source(
        root=canonical_root,
        receipt_path=canonical_receipt,
        expected_manifest_sha256=expected_hashes["canonical_manifest"],
        expected_receipt_sha256=expected_hashes["canonical_receipt"],
        manifest_schema=(
            "reddit_voc_canonical_snapshot_manifest_v1",
            "reddit_voc_canonical_snapshot_manifest_v2",
        ),
        receipt_schema=(
            "reddit_voc_canonical_snapshot_validation_receipt_v1",
            "reddit_voc_canonical_snapshot_validation_receipt_v2",
        ),
        receipt_manifest_field="bundle_manifest_sha256",
        required_files=("posts.jsonl", "comments.jsonl"),
        receipt_promotable=False,
    )
    voc_manifest, _ = _load_pinned_source(
        root=voc_root,
        receipt_path=voc_receipt,
        expected_manifest_sha256=expected_hashes["voc_manifest"],
        expected_receipt_sha256=expected_hashes["voc_receipt"],
        manifest_schema="reddit_voc_voc_facts_manifest_v2",
        receipt_schema="reddit_voc_voc_facts_validation_receipt_v2",
        receipt_manifest_field="bundle_manifest_sha256",
        required_files=("vocs.jsonl", "automation-classifications.jsonl"),
        receipt_promotable=False,
    )
    governed_manifest, _ = _load_pinned_source(
        root=governed_root,
        receipt_path=governed_receipt,
        expected_manifest_sha256=expected_hashes["governed_manifest"],
        expected_receipt_sha256=expected_hashes["governed_receipt"],
        manifest_schema="reddit_voc_governed_signal_snapshot_v1",
        receipt_schema="reddit_voc_governed_signal_validation_receipt_v1",
        receipt_manifest_field="snapshot_manifest_sha256",
        required_files=("entity-brand-facts.jsonl", "entity-product-facts.jsonl"),
        receipt_promotable=True,
    )
    persona_manifest, _ = _load_pinned_source(
        root=persona_root,
        receipt_path=persona_receipt,
        expected_manifest_sha256=expected_hashes["persona_manifest"],
        expected_receipt_sha256=expected_hashes["persona_receipt"],
        manifest_schema="reddit_voc_personas_manifest_v3",
        receipt_schema="reddit_voc_personas_validation_v3",
        receipt_manifest_field="manifest_sha256",
        required_files=("persona-tags.json",),
        receipt_promotable=True,
    )
    casebook_manifest, casebook_payload = _read_json(
        casebook_public_root / "manifest.json", "public casebook manifest", canonical=True
    )
    if (
        sha256_bytes(casebook_payload) != expected_hashes["casebook_public_manifest"]
        or casebook_manifest.get("schema_version") != "reddit_voc_governance_casebook_public_manifest_v1"
        or casebook_manifest.get("status") != "ready"
    ):
        raise QuarterInsightsPublicProjectionError("public casebook manifest is ineligible")
    casebook, casebook_data_payload = _read_json(
        casebook_public_root / "casebook.json", "public casebook", canonical=True
    )
    if casebook_manifest.get("files", {}).get("casebook.json") != _file_contract(casebook_data_payload):
        raise QuarterInsightsPublicProjectionError("public casebook file contract mismatch")
    product_ledger, product_payload = _read_json(product_ledger_path, "product entity ledger")
    if sha256_bytes(product_payload) != expected_hashes["product_ledger"]:
        raise QuarterInsightsPublicProjectionError("product ledger SHA-256 mismatch")
    if (
        voc_manifest.get("inputs", {}).get("canonical_manifest_sha256") != expected_hashes["canonical_manifest"]
        or governed_manifest.get("inputs", {}).get("facts_manifest_sha256") != expected_hashes["voc_manifest"]
        or persona_manifest.get("governed_signal_manifest_sha256") != expected_hashes["governed_manifest"]
        or persona_manifest.get("source_facts_manifest_sha256") != expected_hashes["voc_manifest"]
        or governed_manifest.get("inputs", {}).get("product_entity_ledger_sha256") != expected_hashes["product_ledger"]
    ):
        raise QuarterInsightsPublicProjectionError("source lineage is inconsistent")
    return canonical_manifest, voc_manifest, governed_manifest, persona_manifest, {"manifest": casebook_manifest, "data": casebook, "ledger": product_ledger}


def build_public_projection(
    *,
    source_root: Path,
    casebook_public_root: Path,
    product_ledger_path: Path,
    expected_hashes: Mapping[str, str],
    output_root: Path,
    dataset_version: str = EXPECTED_DATASET_VERSION,
    generated_at_utc: str = GENERATED_AT_UTC,
) -> dict[str, Any]:
    """Build the pinned rolling-quarter and dashboard-window public projection."""
    if DATASET_VERSION_RE.fullmatch(dataset_version) is None:
        raise QuarterInsightsPublicProjectionError("dataset_version is invalid")
    try:
        generated_at = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QuarterInsightsPublicProjectionError("generated_at_utc is invalid") from exc
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise QuarterInsightsPublicProjectionError("generated_at_utc must be UTC")
    source_root = Path(source_root)
    canonical_manifest, voc_manifest, governed_manifest, persona_manifest, auxiliaries = _validate_source_lineage(
        source_root=source_root,
        casebook_public_root=Path(casebook_public_root),
        product_ledger_path=Path(product_ledger_path),
        expected_hashes=expected_hashes,
    )

    vocs: dict[str, dict[str, Any]] = {}
    voc_dates: dict[str, date] = {}
    canonical_root = _source_component(source_root, "canonical", "canonical-candidate-a1")
    voc_root = _source_component(source_root, "voc-facts", "voc-facts-candidate-a2")
    governed_root = _source_component(
        source_root, "governed-signals", "governed-signals-candidate-a1"
    )
    persona_root = _source_component(source_root, "personas", "personas-candidate-a4")
    for row in _read_jsonl(voc_root / "vocs.jsonl", "VOCs"):
        voc_id = row.get("voc_id")
        if not isinstance(voc_id, str) or voc_id in vocs:
            raise QuarterInsightsPublicProjectionError("VOCs contain an invalid or duplicate id")
        vocs[voc_id] = row
        voc_dates[voc_id] = _calendar_date(row)
    anchor = max(voc_dates.values())
    start = anchor - timedelta(days=ROLLING_QUARTER_DAYS - 1)
    quarter_vocs = {voc_id: row for voc_id, row in vocs.items() if start <= voc_dates[voc_id] <= anchor}

    analyses: dict[str, dict[str, Any]] = {}
    canonical_posts = 0
    periodic_comments = 0
    unresolved_comments = 0
    quarter_post_ids: set[str] = set()
    quarter_comments: dict[str, dict[str, Any]] = {}
    for filename, entity_type in (("posts.jsonl", "post"), ("comments.jsonl", "comment")):
        for row in _read_jsonl(canonical_root / filename, f"canonical {entity_type}s"):
            entity_id = row.get("canonical_reddit_id")
            record = row.get("record")
            if not isinstance(entity_id, str) or not isinstance(record, Mapping):
                raise QuarterInsightsPublicProjectionError(f"canonical {entity_type} is invalid")
            analyses[entity_id] = _analysis_for_record(record, entity_type)
            observed = _record_calendar_date(record)
            if observed is None or not start <= observed <= anchor:
                continue
            if entity_type == "post":
                canonical_posts += 1
                post_id = row.get("post_id")
                if isinstance(post_id, str):
                    quarter_post_ids.add(post_id)
            else:
                periodic_comments += 1
                quarter_comments[entity_id] = row
                if row.get("comment_state") == "unresolved_parent":
                    unresolved_comments += 1

    brand_vocs: dict[str, set[str]] = defaultdict(set)
    competitor_union: set[str] = set()
    for fact in _read_jsonl(
        governed_root / "entity-brand-facts.jsonl",
        "governed brand facts",
    ):
        voc_id = fact.get("voc_id")
        attributes = fact.get("attributes")
        if voc_id not in vocs or fact.get("decision_status") != "promoted" or not isinstance(attributes, Mapping):
            continue
        brand_id = attributes.get("brand_id")
        if not isinstance(brand_id, str):
            continue
        brand_vocs[brand_id].add(voc_id)
        if attributes.get("brand_role") == "competitor":
            competitor_union.add(voc_id)
    momcozy_vocs = brand_vocs.get("momcozy", set()) & set(quarter_vocs)
    competitor_quarter = competitor_union & set(quarter_vocs)

    momcozy_types = Counter(str(quarter_vocs[voc_id].get("voc_type")) for voc_id in momcozy_vocs)
    sentiment_counts = Counter()
    pain_counts = Counter()
    severity_counts = Counter()
    geo_topics = Counter()
    for voc_id in momcozy_vocs:
        entity_id = str(quarter_vocs[voc_id].get("canonical_entity_id"))
        analysis = analyses.get(entity_id, {})
        sentiment_counts[str(analysis.get("sentiment_label") or "missing")] += 1
        pain_points = analysis.get("pain_points")
        if isinstance(pain_points, list):
            pain_counts.update(str(value) for value in pain_points)
        severity_counts[str(analysis.get("severity") or "missing")] += 1
        if quarter_vocs[voc_id].get("voc_type") == "post_voc":
            topic = str(analysis.get("topic") or "missing")
            if topic in {"competitor_comparison", "purchase_decision"}:
                geo_topics[topic] += 1

    product_categories: dict[str, set[str]] = defaultdict(set)
    product_families: dict[str, set[str]] = defaultdict(set)
    exact_status_by_family: dict[str, str] = {}
    for fact in _read_jsonl(
        governed_root / "entity-product-facts.jsonl",
        "governed product facts",
    ):
        voc_id = fact.get("voc_id")
        attributes = fact.get("attributes")
        if voc_id not in momcozy_vocs or fact.get("decision_status") != "promoted" or not isinstance(attributes, Mapping):
            continue
        category_id = attributes.get("category_id")
        family_id = attributes.get("family_id")
        if isinstance(category_id, str):
            product_categories[category_id].add(voc_id)
        if isinstance(family_id, str):
            product_families[family_id].add(voc_id)
            status = attributes.get("exact_spu_mapping_status")
            if isinstance(status, str):
                exact_status_by_family[family_id] = status

    exact_spu_rows: list[dict[str, Any]] = []
    exact_ledger = auxiliaries["ledger"].get("exact_spu_ledger")
    if not isinstance(exact_ledger, list):
        raise QuarterInsightsPublicProjectionError("exact SPU ledger is missing")
    for item in exact_ledger:
        if not isinstance(item, Mapping) or item.get("publish_exact_spu") is not True:
            continue
        family_id = item.get("family_id")
        spu_id = item.get("spu_id")
        spu_name = item.get("spu_name")
        if not all(isinstance(value, str) for value in (family_id, spu_id, spu_name)):
            raise QuarterInsightsPublicProjectionError("exact SPU ledger row is invalid")
        if exact_status_by_family.get(str(family_id)) != "approved_for_publication":
            continue
        exact_spu_rows.append({
            "id": str(spu_id),
            "label": str(spu_name),
            "count": len(product_families.get(str(family_id), set())),
        })
    exact_spu_rows.sort(key=lambda item: (-int(item["count"]), str(item["id"])))

    automation_comments = 0
    moderation_evidence_verified = False
    quarter_comment_entity_ids = {
        str(row.get("canonical_entity_id"))
        for row in quarter_vocs.values()
        if row.get("voc_type") == "comment_context_voc"
    }
    for classification in _read_jsonl(
        voc_root / "automation-classifications.jsonl",
        "automation classifications",
    ):
        entity_id = classification.get("canonical_entity_id")
        if (
            entity_id not in quarter_comment_entity_ids
            or entity_id not in quarter_comments
            or classification.get("automation_determined") is not True
        ):
            continue
        automation_comments += 1
        record = quarter_comments[str(entity_id)].get("record")
        body = str(record.get("body") or record.get("source_text") or "") if isinstance(record, Mapping) else ""
        if (
            entity_id == "t1_ox33k0h"
            and quarter_comments[str(entity_id)].get("post_id") == "1uubl6f"
            and "rampant use of bots momcozy uses" in body.lower()
        ):
            moderation_evidence_verified = True

    persona_tags, _ = _read_json(
        persona_root / "persona-tags.json", "persona tags"
    )
    assignments = persona_tags.get("assignments")
    if not isinstance(assignments, list):
        raise QuarterInsightsPublicProjectionError("persona assignments are missing")
    main_assignments: list[Mapping[str, Any]] = []
    category_assignments: list[Mapping[str, Any]] = []
    for assignment in assignments:
        if not isinstance(assignment, Mapping) or assignment.get("voc_id") not in quarter_vocs:
            continue
        if assignment.get("scope") in {"momcozy_direct", "momcozy_multi"}:
            main_assignments.append(assignment)
        elif assignment.get("scope") == "category_context":
            category_assignments.append(assignment)
    main_assignment_ids = sorted(str(item.get("assignment_id")) for item in main_assignments)
    if any(SHA256_RE.fullmatch(value) is None for value in main_assignment_ids):
        raise QuarterInsightsPublicProjectionError("persona assignment id is invalid")
    main_cohorts = Counter(str(item.get("cohort_id")) for item in main_assignments)

    casebook_data = auxiliaries["data"]
    dossiers = casebook_data.get("dossiers")
    dossier = dossiers[0] if isinstance(dossiers, list) and len(dossiers) == 1 else None
    if not isinstance(dossier, Mapping) or not isinstance(dossier.get("case_id"), str):
        raise QuarterInsightsPublicProjectionError("public casebook has no eligible case")
    case_id = str(dossier["case_id"])

    source = {
        "source_snapshot_id": governed_manifest["source_snapshot_id"],
        "canonical_dataset_id": canonical_manifest["dataset_id"],
        "canonical_manifest_sha256": expected_hashes["canonical_manifest"],
        "canonical_validation_receipt_sha256": expected_hashes["canonical_receipt"],
        "voc_dataset_id": voc_manifest["dataset_id"],
        "voc_manifest_sha256": expected_hashes["voc_manifest"],
        "voc_validation_receipt_sha256": expected_hashes["voc_receipt"],
        "governed_signal_snapshot_id": governed_manifest["snapshot_id"],
        "governed_signal_manifest_sha256": expected_hashes["governed_manifest"],
        "governed_signal_validation_receipt_sha256": expected_hashes["governed_receipt"],
        "persona_snapshot_id": persona_manifest["snapshot_id"],
        "persona_manifest_sha256": expected_hashes["persona_manifest"],
        "persona_validation_receipt_sha256": expected_hashes["persona_receipt"],
        "casebook_public_projection_id": auxiliaries["manifest"]["projection_id"],
        "casebook_public_manifest_sha256": expected_hashes["casebook_public_manifest"],
        "product_ledger_sha256": expected_hashes["product_ledger"],
    }
    data = {
        "schema_version": PUBLIC_DATA_SCHEMA,
        "dataset_version": dataset_version,
        "generated_at_utc": generated_at_utc,
        "period": {
            "timezone": REPORTING_TIMEZONE,
            "anchor_date": anchor.isoformat(),
            "start_date": start.isoformat(),
            "end_date": anchor.isoformat(),
            "days": ROLLING_QUARTER_DAYS,
            "inclusive": True,
        },
        "counts": {
            "canonical_posts": canonical_posts,
            "periodic_comments": periodic_comments,
            "linked_comment_context_vocs": sum(row.get("voc_type") == "comment_context_voc" for row in quarter_vocs.values()),
            "unresolved_parent_comments": unresolved_comments,
            "analysis_post_vocs": sum(row.get("voc_type") == "post_voc" for row in quarter_vocs.values()),
            "analysis_comment_context_vocs": sum(row.get("voc_type") == "comment_context_voc" for row in quarter_vocs.values()),
            "momcozy": {
                "post_vocs": momcozy_types["post_voc"],
                "comment_context_vocs": momcozy_types["comment_context_voc"],
                "total_vocs": len(momcozy_vocs),
                "sentiment": _sentiment(sentiment_counts),
            },
            "competitor_union_vocs": len(competitor_quarter),
            "momcozy_competitor_overlap_vocs": len(momcozy_vocs & competitor_quarter),
        },
        "personas": {
            "main_scope": ["momcozy_direct", "momcozy_multi"],
            "date_basis": "content_entity_event_date",
            "main_assignment_ids": main_assignment_ids,
            "main_assignment_count": len(main_assignments),
            "main_unique_entities": len({str(item.get("entity_id")) for item in main_assignments}),
            "category_context_assignment_count": len(category_assignments),
            "category_context_unique_entities": len({str(item.get("entity_id")) for item in category_assignments}),
            "cohorts": [
                {"cohort_id": cohort_id, "assignment_count": main_cohorts[cohort_id]}
                for cohort_id in COHORT_ORDER
            ],
        },
        "themes": {
            "pain": {
                "method": "canonical_analysis_local_rules_v1_multilabel",
                "rankings": _ranking(pain_counts, PAIN_LABELS, 5),
                "evidence": list(EVIDENCE["pain"]),
            },
            "reputation": {
                "method": "local_rules_v1_plus_explicit_automation_disclosure",
                "negative_vocs": sentiment_counts["negative"],
                "high_severity_vocs": severity_counts["high"],
                "automation_comments": automation_comments,
                "quarter_moderation_claim_evidence_count": int(moderation_evidence_verified),
                "rankings": _ranking(
                    {
                        "negative_vocs": sentiment_counts["negative"],
                        "high_severity_vocs": severity_counts["high"],
                        "automation_comments": automation_comments,
                        "quarter_moderation_claim_evidence_count": int(moderation_evidence_verified),
                    },
                    {
                        "negative_vocs": "Momcozy 负向 VOC",
                        "high_severity_vocs": "Momcozy 高严重度 VOC",
                        "automation_comments": "自动化评论",
                        "quarter_moderation_claim_evidence_count": "季度版主管理主张证据",
                    },
                ),
                "evidence": list(EVIDENCE["reputation"]),
            },
            "new_product": {
                "method": "promoted_governed_product_facts_distinct_voc",
                "category_rankings": _ranking(
                    {key: len(value) for key, value in product_categories.items()}, CATEGORY_LABELS
                ),
                "family_rankings": _ranking(
                    {key: len(value) for key, value in product_families.items()}, FAMILY_LABELS, 5
                ),
                "product_rankings": _ranking(
                    {key: len(value) for key, value in product_families.items()}, FAMILY_LABELS, 5
                ),
                "exact_spu_rankings": exact_spu_rows,
                "family_only_ids": sorted(
                    family_id for family_id, status in exact_status_by_family.items()
                    if status != "approved_for_publication" and family_id in product_families
                ),
                "evidence": list(EVIDENCE["new_product"]),
            },
            "geo": {
                "method": "momcozy_post_local_rules_v1_decision_topics",
                "comparison_decision_posts": sum(geo_topics.values()),
                "rankings": _ranking(
                    geo_topics,
                    {
                        "competitor_comparison": "竞品比较问题",
                        "purchase_decision": "购买决策问题",
                    },
                ),
                "evidence": list(EVIDENCE["geo"]),
            },
        },
        "case_references": {
            "pain": {"id": None, "role": "no_approved_local_case"},
            "reputation": {"id": case_id, "role": "historical_governance_method_reference"},
            "new_product": {"id": None, "role": "no_approved_local_case"},
            "geo": {"id": None, "role": "no_approved_local_case"},
        },
        "dashboard_windows": [
            _window_projection(
                window_id=window_id,
                days=days,
                anchor=anchor,
                vocs=vocs,
                voc_dates=voc_dates,
                brand_vocs=brand_vocs,
                analyses=analyses,
            )
            for window_id, days in (
                ("rolling_7_days", 7),
                ("rolling_30_days", 30),
                ("rolling_183_days", 183),
            )
        ],
        "boundaries": dict(PUBLIC_BOUNDARIES),
        "source": source,
    }
    if not moderation_evidence_verified:
        raise QuarterInsightsPublicProjectionError("quarter moderation evidence changed")
    _validate_data_semantics(data)
    _walk_forbidden(data)
    data_payload = canonical_json_document(data)
    manifest = {
        "schema_version": PUBLIC_MANIFEST_SCHEMA,
        "dataset_version": dataset_version,
        "generated_at_utc": generated_at_utc,
        "status": "ready",
        "period": dict(data["period"]),
        "boundaries": dict(PUBLIC_BOUNDARIES),
        "source": source,
        "files": {"quarter-insights.json": _file_contract(data_payload)},
    }
    manifest_payload = canonical_json_document(manifest)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    declared = {"manifest.json", *PUBLIC_FILES}
    extras = {entry.name for entry in output.iterdir()} - declared
    if extras:
        raise QuarterInsightsPublicProjectionError("public output contains undeclared entries")
    (output / "quarter-insights.json").write_bytes(data_payload)
    (output / "manifest.json").write_bytes(manifest_payload)
    return {
        "dataset_version": dataset_version,
        "data_sha256": sha256_bytes(data_payload),
        "manifest_sha256": sha256_bytes(manifest_payload),
        "status": "built",
    }


def _walk_forbidden(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in FORBIDDEN_KEYS:
                raise QuarterInsightsPublicProjectionError(f"public data contains forbidden field: {key}")
            _walk_forbidden(nested)
    elif isinstance(value, list):
        for item in value:
            _walk_forbidden(item)
    elif isinstance(value, str):
        if "http://" in value or "https://" in value or "/Users/" in value or "tmp/" in value:
            raise QuarterInsightsPublicProjectionError("public data contains a URL or private path")


def _mapping_counts(rows: Any, id_key: str = "id", count_key: str = "count") -> dict[str, int]:
    if not isinstance(rows, list):
        raise QuarterInsightsPublicProjectionError("ranking rows must be a list")
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {id_key, "label", count_key}:
            raise QuarterInsightsPublicProjectionError("ranking row fields are invalid")
        key = row.get(id_key)
        count = row.get(count_key)
        if not isinstance(key, str) or not isinstance(row.get("label"), str) or not isinstance(count, int) or count < 0:
            raise QuarterInsightsPublicProjectionError("ranking row is invalid")
        if key in result:
            raise QuarterInsightsPublicProjectionError("ranking ids must be unique")
        result[key] = count
    return result


def _validate_evidence(rows: Any, expected: tuple[dict[str, str | None], ...]) -> None:
    if rows != list(expected):
        raise QuarterInsightsPublicProjectionError("public evidence allowlist changed")
    for row in rows:
        if set(row) != {"post_id", "comment_id", "reason"}:
            raise QuarterInsightsPublicProjectionError("public evidence fields are invalid")
        if POST_ID_RE.fullmatch(str(row["post_id"])) is None or not isinstance(row["reason"], str) or not row["reason"]:
            raise QuarterInsightsPublicProjectionError("public evidence is invalid")
        if row["comment_id"] is not None and COMMENT_ID_RE.fullmatch(str(row["comment_id"])) is None:
            raise QuarterInsightsPublicProjectionError("public comment evidence id is invalid")


def _validate_window(window: Any, *, expected_id: str, expected_days: int, anchor: date) -> None:
    if not isinstance(window, Mapping):
        raise QuarterInsightsPublicProjectionError("dashboard window is invalid")
    required = {
        "id", "start_date", "end_date", "days", "bucket_grain", "momcozy",
        "top_competitor", "buckets",
    }
    if set(window) != required or window.get("id") != expected_id or window.get("days") != expected_days:
        raise QuarterInsightsPublicProjectionError("dashboard window contract is invalid")
    expected_start = anchor - timedelta(days=expected_days - 1)
    expected_grain = "month" if expected_days == 183 else "day"
    if (
        window.get("start_date") != expected_start.isoformat()
        or window.get("end_date") != anchor.isoformat()
        or window.get("bucket_grain") != expected_grain
    ):
        raise QuarterInsightsPublicProjectionError("dashboard window period is invalid")
    momcozy = window.get("momcozy")
    if not isinstance(momcozy, Mapping) or set(momcozy) != {
        "post_vocs", "comment_context_vocs", "total_vocs", "negative_vocs",
        "classified_vocs", "negative_rate",
    }:
        raise QuarterInsightsPublicProjectionError("dashboard Momcozy summary is invalid")
    if momcozy["post_vocs"] + momcozy["comment_context_vocs"] != momcozy["total_vocs"]:
        raise QuarterInsightsPublicProjectionError("dashboard Momcozy VOC counts do not reconcile")
    expected_rate = half_up_percent(momcozy["negative_vocs"], momcozy["classified_vocs"])
    if momcozy["negative_rate"] != expected_rate:
        raise QuarterInsightsPublicProjectionError("dashboard negative rate is invalid")
    top = window.get("top_competitor")
    if (
        not isinstance(top, Mapping)
        or set(top) != {"id", "label", "voc_count"}
        or not isinstance(top.get("id"), str)
        or not top.get("id")
        or not isinstance(top.get("label"), str)
        or not top.get("label")
        or not isinstance(top.get("voc_count"), int)
        or top.get("voc_count", 0) <= 0
    ):
        raise QuarterInsightsPublicProjectionError("dashboard top competitor is invalid")
    buckets = window.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        raise QuarterInsightsPublicProjectionError("dashboard buckets are missing")
    total = 0
    observed_buckets: list[str] = []
    for bucket in buckets:
        if not isinstance(bucket, Mapping) or set(bucket) != {
            "bucket", "post_vocs", "comment_context_vocs", "total_vocs",
            "negative_vocs", "classified_vocs", "negative_rate",
        }:
            raise QuarterInsightsPublicProjectionError("dashboard bucket fields are invalid")
        if bucket["post_vocs"] + bucket["comment_context_vocs"] != bucket["total_vocs"]:
            raise QuarterInsightsPublicProjectionError("dashboard bucket VOC counts do not reconcile")
        rate = half_up_percent(bucket["negative_vocs"], bucket["classified_vocs"])
        if bucket["negative_rate"] != rate:
            raise QuarterInsightsPublicProjectionError("dashboard bucket negative rate is invalid")
        bucket_id = bucket.get("bucket")
        if not isinstance(bucket_id, str) or not bucket_id:
            raise QuarterInsightsPublicProjectionError("dashboard bucket id is invalid")
        observed_buckets.append(bucket_id)
        total += bucket["total_vocs"]
    if observed_buckets != sorted(set(observed_buckets)) or total != momcozy["total_vocs"]:
        raise QuarterInsightsPublicProjectionError("dashboard buckets do not reconcile to the window")


def _validate_data_semantics(data: Mapping[str, Any]) -> None:
    expected_top = {
        "schema_version", "dataset_version", "generated_at_utc", "period", "counts",
        "personas", "themes", "case_references", "dashboard_windows", "boundaries", "source",
    }
    if set(data) != expected_top:
        raise QuarterInsightsPublicProjectionError("public data fields do not match the contract")
    dataset_version = data.get("dataset_version")
    generated_at_utc = data.get("generated_at_utc")
    if (
        data.get("schema_version") != PUBLIC_DATA_SCHEMA
        or not isinstance(dataset_version, str)
        or DATASET_VERSION_RE.fullmatch(dataset_version) is None
        or not isinstance(generated_at_utc, str)
        or data.get("boundaries") != PUBLIC_BOUNDARIES
    ):
        raise QuarterInsightsPublicProjectionError("public data identity or boundaries are invalid")
    try:
        generated_at = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QuarterInsightsPublicProjectionError("public generated timestamp is invalid") from exc
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise QuarterInsightsPublicProjectionError("public generated timestamp must be UTC")
    period = data.get("period")
    if not isinstance(period, Mapping) or set(period) != {
        "timezone", "anchor_date", "start_date", "end_date", "days", "inclusive"
    }:
        raise QuarterInsightsPublicProjectionError("public quarter period is invalid")
    try:
        anchor = date.fromisoformat(str(period.get("anchor_date")))
        start = date.fromisoformat(str(period.get("start_date")))
        end = date.fromisoformat(str(period.get("end_date")))
    except ValueError as exc:
        raise QuarterInsightsPublicProjectionError("public quarter dates are invalid") from exc
    if (
        period.get("timezone") != REPORTING_TIMEZONE
        or period.get("days") != ROLLING_QUARTER_DAYS
        or period.get("inclusive") is not True
        or end != anchor
        or start != anchor - timedelta(days=ROLLING_QUARTER_DAYS - 1)
    ):
        raise QuarterInsightsPublicProjectionError("public quarter period is invalid")
    counts = data.get("counts")
    count_keys = {
        "canonical_posts", "periodic_comments", "linked_comment_context_vocs",
        "unresolved_parent_comments", "analysis_post_vocs",
        "analysis_comment_context_vocs", "momcozy", "competitor_union_vocs",
        "momcozy_competitor_overlap_vocs",
    }
    if not isinstance(counts, Mapping) or set(counts) != count_keys:
        raise QuarterInsightsPublicProjectionError("public counts are missing")
    scalar_count_keys = count_keys - {"momcozy"}
    if any(not isinstance(counts.get(key), int) or counts.get(key, -1) < 0 for key in scalar_count_keys):
        raise QuarterInsightsPublicProjectionError("public scalar counts are invalid")
    if (
        counts["periodic_comments"]
        != counts["linked_comment_context_vocs"] + counts["unresolved_parent_comments"]
        or counts["analysis_comment_context_vocs"] != counts["linked_comment_context_vocs"]
        or counts["analysis_post_vocs"] > counts["canonical_posts"]
    ):
        raise QuarterInsightsPublicProjectionError("period comment counts do not reconcile")
    momcozy = counts.get("momcozy")
    if not isinstance(momcozy, Mapping) or set(momcozy) != {
        "post_vocs", "comment_context_vocs", "total_vocs", "sentiment"
    }:
        raise QuarterInsightsPublicProjectionError("Momcozy quarter counts are invalid")
    if any(not isinstance(momcozy.get(key), int) or momcozy.get(key, -1) < 0 for key in (
        "post_vocs", "comment_context_vocs", "total_vocs"
    )):
        raise QuarterInsightsPublicProjectionError("Momcozy quarter counts are invalid")
    if (
        momcozy["post_vocs"] + momcozy["comment_context_vocs"] != momcozy["total_vocs"]
        or momcozy["post_vocs"] > counts["analysis_post_vocs"]
        or momcozy["comment_context_vocs"] > counts["analysis_comment_context_vocs"]
        or counts["momcozy_competitor_overlap_vocs"]
        > min(momcozy["total_vocs"], counts["competitor_union_vocs"])
    ):
        raise QuarterInsightsPublicProjectionError("Momcozy quarter counts do not reconcile")
    sentiment = momcozy.get("sentiment")
    if not isinstance(sentiment, Mapping) or set(sentiment) != {
        "positive", "neutral", "negative", "missing", "classified", "negative_rate",
        "negative_rate_denominator", "negative_rate_unit",
    }:
        raise QuarterInsightsPublicProjectionError("Momcozy sentiment is invalid")
    if any(not isinstance(sentiment.get(key), int) or sentiment.get(key, -1) < 0 for key in (
        "positive", "neutral", "negative", "missing", "classified"
    )):
        raise QuarterInsightsPublicProjectionError("Momcozy sentiment counts are invalid")
    classified = sentiment["positive"] + sentiment["neutral"] + sentiment["negative"]
    expected_rate = half_up_percent(sentiment["negative"], classified)
    if (
        sentiment["classified"] != classified
        or classified + sentiment["missing"] != momcozy["total_vocs"]
        or sentiment["negative_rate"] != expected_rate
        or sentiment["negative_rate_denominator"] != "classified"
        or sentiment["negative_rate_unit"] != "percent"
    ):
        raise QuarterInsightsPublicProjectionError("Momcozy sentiment counts do not reconcile")

    personas = data.get("personas")
    if not isinstance(personas, Mapping):
        raise QuarterInsightsPublicProjectionError("public personas are missing")
    if personas.get("main_scope") != ["momcozy_direct", "momcozy_multi"] or personas.get("date_basis") != "content_entity_event_date":
        raise QuarterInsightsPublicProjectionError("persona scope or date basis is invalid")
    persona_count_keys = (
        "main_assignment_count", "main_unique_entities",
        "category_context_assignment_count", "category_context_unique_entities",
    )
    if any(not isinstance(personas.get(key), int) or personas.get(key, -1) < 0 for key in persona_count_keys):
        raise QuarterInsightsPublicProjectionError("persona counts are invalid")
    if (
        personas["main_unique_entities"] > personas["main_assignment_count"]
        or personas["category_context_unique_entities"] > personas["category_context_assignment_count"]
    ):
        raise QuarterInsightsPublicProjectionError("persona counts do not reconcile")
    assignment_ids = personas.get("main_assignment_ids")
    if (
        not isinstance(assignment_ids, list)
        or len(assignment_ids) != personas["main_assignment_count"]
        or assignment_ids != sorted(set(assignment_ids))
        or any(SHA256_RE.fullmatch(str(value)) is None for value in assignment_ids)
    ):
        raise QuarterInsightsPublicProjectionError("persona assignment allowlist is invalid")
    cohorts = personas.get("cohorts")
    if not isinstance(cohorts, list) or [row.get("cohort_id") for row in cohorts if isinstance(row, Mapping)] != list(COHORT_ORDER):
        raise QuarterInsightsPublicProjectionError("persona cohort order is invalid")
    observed_cohorts = {
        str(row.get("cohort_id")): row.get("assignment_count")
        for row in cohorts if isinstance(row, Mapping)
    }
    if (
        set(observed_cohorts) != set(COHORT_ORDER)
        or any(not isinstance(value, int) or value < 0 for value in observed_cohorts.values())
        or sum(observed_cohorts.values()) != personas["main_assignment_count"]
    ):
        raise QuarterInsightsPublicProjectionError("persona cohort counts do not reconcile")

    themes = data.get("themes")
    if not isinstance(themes, Mapping) or set(themes) != set(EVIDENCE):
        raise QuarterInsightsPublicProjectionError("public themes are incomplete")
    pain = themes["pain"]
    pain_counts = _mapping_counts(pain.get("rankings"))
    if not pain_counts or any(value <= 0 for value in pain_counts.values()):
        raise QuarterInsightsPublicProjectionError("pain rankings are invalid")
    _validate_evidence(pain.get("evidence"), EVIDENCE["pain"])
    reputation = themes["reputation"]
    reputation_counts = {
        key: reputation.get(key)
        for key in (
            "automation_comments", "negative_vocs", "high_severity_vocs",
            "quarter_moderation_claim_evidence_count",
        )
    }
    if (
        any(not isinstance(value, int) or value < 0 for value in reputation_counts.values())
        or reputation_counts["quarter_moderation_claim_evidence_count"] != 1
        or _mapping_counts(reputation.get("rankings")) != reputation_counts
    ):
        raise QuarterInsightsPublicProjectionError("reputation counts do not reconcile")
    _validate_evidence(reputation.get("evidence"), EVIDENCE["reputation"])
    new_product = themes["new_product"]
    category_counts = _mapping_counts(new_product.get("category_rankings"))
    family_counts = _mapping_counts(new_product.get("family_rankings"))
    product_counts = _mapping_counts(new_product.get("product_rankings"))
    exact_spu_counts = _mapping_counts(new_product.get("exact_spu_rankings"))
    if (
        not category_counts
        or not family_counts
        or product_counts != family_counts
        or any(value <= 0 for value in (*category_counts.values(), *family_counts.values(), *exact_spu_counts.values()))
    ):
        raise QuarterInsightsPublicProjectionError("product rankings are invalid")
    family_only = new_product.get("family_only_ids")
    if (
        not isinstance(family_only, list)
        or family_only != sorted(set(family_only))
        or any(not isinstance(value, str) or not value for value in family_only)
    ):
        raise QuarterInsightsPublicProjectionError("family-only product boundary is invalid")
    _validate_evidence(new_product.get("evidence"), EVIDENCE["new_product"])
    geo = themes["geo"]
    geo_counts = _mapping_counts(geo.get("rankings"))
    if geo.get("comparison_decision_posts") != sum(geo_counts.values()):
        raise QuarterInsightsPublicProjectionError("GEO decision counts do not reconcile")
    _validate_evidence(geo.get("evidence"), EVIDENCE["geo"])

    case_references = data.get("case_references")
    if not isinstance(case_references, Mapping) or set(case_references) != set(EVIDENCE):
        raise QuarterInsightsPublicProjectionError("case references are incomplete")
    for theme_id, reference in case_references.items():
        if not isinstance(reference, Mapping) or set(reference) != {"id", "role"}:
            raise QuarterInsightsPublicProjectionError("case reference fields are invalid")
        if theme_id == "reputation":
            if (
                reference.get("role") != "historical_governance_method_reference"
                or SHA256_RE.fullmatch(str(reference.get("id"))) is None
            ):
                raise QuarterInsightsPublicProjectionError("reputation case reference is invalid")
        elif reference != {"id": None, "role": "no_approved_local_case"}:
            raise QuarterInsightsPublicProjectionError("unapproved case reference must stay empty")

    windows = data.get("dashboard_windows")
    if not isinstance(windows, list) or len(windows) != 3:
        raise QuarterInsightsPublicProjectionError("dashboard windows are incomplete")
    for window, (window_id, days) in zip(
        windows,
        (("rolling_7_days", 7), ("rolling_30_days", 30), ("rolling_183_days", 183)),
        strict=True,
    ):
        _validate_window(window, expected_id=window_id, expected_days=days, anchor=anchor)
    source = data.get("source")
    source_keys = {
        "source_snapshot_id", "canonical_dataset_id", "canonical_manifest_sha256",
        "canonical_validation_receipt_sha256", "voc_dataset_id", "voc_manifest_sha256",
        "voc_validation_receipt_sha256", "governed_signal_snapshot_id",
        "governed_signal_manifest_sha256", "governed_signal_validation_receipt_sha256",
        "persona_snapshot_id", "persona_manifest_sha256",
        "persona_validation_receipt_sha256", "casebook_public_projection_id",
        "casebook_public_manifest_sha256", "product_ledger_sha256",
    }
    if not isinstance(source, Mapping) or set(source) != source_keys:
        raise QuarterInsightsPublicProjectionError("public source lineage is invalid")
    for key, value in source.items():
        if key.endswith("sha256"):
            _require_sha(str(value), key)
        elif not isinstance(value, str) or not value:
            raise QuarterInsightsPublicProjectionError("public source identity is invalid")


def validate_public_projection(*, output_root: Path, expected_manifest_sha256: str) -> dict[str, Any]:
    """Independently validate a materialized projection without reading private inputs."""
    _require_sha(expected_manifest_sha256, "expected public manifest")
    root = Path(output_root)
    if root.is_symlink() or not root.is_dir() or {entry.name for entry in root.iterdir()} != {"manifest.json", *PUBLIC_FILES}:
        raise QuarterInsightsPublicProjectionError("public output entries do not match the contract")
    manifest, manifest_payload = _read_json(root / "manifest.json", "public manifest", canonical=True)
    data, data_payload = _read_json(root / "quarter-insights.json", "public quarter insights", canonical=True)
    if sha256_bytes(manifest_payload) != expected_manifest_sha256:
        raise QuarterInsightsPublicProjectionError("public manifest SHA-256 mismatch")
    expected_manifest_keys = {
        "schema_version", "dataset_version", "generated_at_utc", "status", "period",
        "boundaries", "source", "files",
    }
    if set(manifest) != expected_manifest_keys:
        raise QuarterInsightsPublicProjectionError("public manifest fields do not match the contract")
    if (
        manifest.get("schema_version") != PUBLIC_MANIFEST_SCHEMA
        or manifest.get("dataset_version") != data.get("dataset_version")
        or manifest.get("generated_at_utc") != data.get("generated_at_utc")
        or manifest.get("status") != "ready"
        or manifest.get("period") != data.get("period")
        or manifest.get("boundaries") != PUBLIC_BOUNDARIES
        or manifest.get("source") != data.get("source")
        or manifest.get("files", {}).get("quarter-insights.json") != _file_contract(data_payload)
    ):
        raise QuarterInsightsPublicProjectionError("public manifest contract mismatch")
    _validate_data_semantics(data)
    _walk_forbidden(data)
    return {
        "data_sha256": sha256_bytes(data_payload),
        "dataset_version": data["dataset_version"],
        "manifest_sha256": sha256_bytes(manifest_payload),
        "status": "passed",
    }
