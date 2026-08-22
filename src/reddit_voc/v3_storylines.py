"""Evidence-bound six-part Reddit VOC V3 storyline records."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Mapping, Sequence


class StorylineError(ValueError):
    """A storyline would exceed the supported evidence contract."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise StorylineError(f"{label} is invalid")
    return value


def build_storyline(
    *,
    metric: Mapping[str, object],
    direction: str | None,
    root_cause_evidence_ids: Sequence[str],
    evidence_registry: Mapping[str, Mapping[str, object]],
    snapshot_id: str,
    comparison: Mapping[str, object],
    impact: str,
    action: Mapping[str, object],
    monitoring: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(metric, Mapping) or not isinstance(comparison, Mapping):
        raise StorylineError("storyline metric contract is invalid")
    snapshot_id = _text(snapshot_id, "snapshot ID")
    metric_id = _text(metric.get("metric_id"), "metric ID")
    period_id = _text(metric.get("period_id"), "period ID")
    scope = _text(metric.get("scope"), "metric scope")
    voc_type = _text(metric.get("voc_type"), "VOC type")
    unit = _text(metric.get("unit"), "metric unit")
    status = metric.get("status")
    if status not in {"available", "provisional", "unavailable"}:
        raise StorylineError("metric status is invalid")
    if direction not in {None, "up", "down", "flat"}:
        raise StorylineError("storyline direction is invalid")
    if status == "unavailable" and direction is not None:
        raise StorylineError("unavailable metric cannot produce a direction claim")
    if status != "unavailable" and metric.get("value") is None:
        raise StorylineError("available metric lacks a value")

    evidence_ids = list(root_cause_evidence_ids)
    if (
        any(not isinstance(value, str) or not value for value in evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
    ):
        raise StorylineError("root-cause evidence IDs are invalid")
    for evidence_id in evidence_ids:
        evidence = evidence_registry.get(evidence_id)
        if not isinstance(evidence, Mapping):
            raise StorylineError("root-cause evidence is missing")
        if evidence.get("snapshot_id") != snapshot_id:
            raise StorylineError("root-cause evidence snapshot mismatch")

    impact = _text(impact, "impact")
    if re.search(
        r"必然导致(?:销售额|销量|收入)|(?:cause|causes|caused|guarantee).{0,20}(?:sales|revenue)",
        impact,
        flags=re.IGNORECASE,
    ):
        raise StorylineError("unsupported sales causality claim")

    required_action = ("owner_role", "priority", "approval_status")
    required_monitoring = ("metric_id", "cadence", "review_date")
    if any(not isinstance(action.get(key), str) or not action.get(key) for key in required_action):
        raise StorylineError("storyline action is invalid")
    if any(
        not isinstance(monitoring.get(key), str) or not monitoring.get(key)
        for key in required_monitoring
    ):
        raise StorylineError("storyline monitoring is invalid")
    if action.get("approval_status") not in {"proposed", "review_required", "approved"}:
        raise StorylineError("storyline action approval status is invalid")
    if monitoring.get("metric_id") != metric_id:
        raise StorylineError("storyline monitoring metric mismatch")

    comparison_supported = comparison.get("status") in {"available", "provisional"}
    comparison_display = comparison.get("display")
    if comparison_supported and (
        not isinstance(comparison_display, str) or comparison_display == "—"
    ):
        raise StorylineError("storyline comparison value is invalid")
    counter_reason_codes = comparison.get("reason_codes", [])
    if not comparison_supported and (
        not isinstance(counter_reason_codes, list)
        or any(not isinstance(value, str) or not value for value in counter_reason_codes)
    ):
        raise StorylineError("storyline comparison reasons are invalid")

    sections: dict[str, object] = {
        "signal": {
            "metric_id": metric_id,
            "period_id": period_id,
            "scope": scope,
            "status": status,
            "unit": unit,
            "value": metric.get("value"),
            "voc_type": voc_type,
            "direction": direction,
        },
        "root_cause": {
            "statement": (
                f"由 {len(evidence_ids)} 条受治理内容证据支持"
                if evidence_ids
                else "根因未确认"
            ),
            "evidence_ids": evidence_ids,
            "supported": bool(evidence_ids),
        },
        "counter_intuitive": {
            "supported": comparison_supported,
            "statement": (
                f"可比基期差异 {comparison_display}"
                if comparison_supported
                else "基期不可比，不发布反直觉方向结论"
            ),
            "reason_codes": [] if comparison_supported else list(counter_reason_codes),
        },
        "impact": {
            "statement": impact,
            "sales_causality_supported": False,
        },
        "action": dict(action),
        "monitoring": dict(monitoring),
    }
    payload = {
        "direction_claim_supported": status in {"available", "provisional"} and direction is not None,
        "metric_id": metric_id,
        "period_id": period_id,
        "schema_version": "reddit_voc_storyline_v3",
        "sections": sections,
        "snapshot_id": snapshot_id,
    }
    payload["storyline_id"] = sha256(_canonical(payload)).hexdigest()
    return payload
