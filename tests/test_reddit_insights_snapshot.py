import json
from pathlib import Path

import pytest

from scripts.build_reddit_insights_snapshot import build, write_snapshot
from scripts.validate_reddit_insights_snapshot import validate


ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT = ROOT / "data/processed/reddit_voc_site_snapshot_20260714"
REVIEW_SAMPLE = (
    ROOT
    / "docs/analysis/reddit-tag-semantic-audit-20260714/review-sample.json"
)
REVIEW_DECISIONS = (
    ROOT
    / "docs/analysis/reddit-tag-semantic-audit-20260714/review-decisions.json"
)


def build_fixture():
    return build(BASE_SNAPSHOT, REVIEW_SAMPLE, REVIEW_DECISIONS)


def test_builds_fail_closed_insights_overlay_and_validates_it(tmp_path: Path) -> None:
    audit, insights, manifest = build_fixture()

    assert audit["summary"]["reviewed_assignments"] == 100
    assert set(audit["summary"]["promoted_tag_ids"]) == {
        "L0-GEN-075",
        "L0-GEN-103",
    }
    assert audit["summary"]["held_tags"] == 8
    assert {signal["tag_id"] for signal in insights["signals"]} == {
        "L0-GEN-075",
        "L0-GEN-103",
    }
    assert insights["interpretation_boundaries"][
        "consumer_card_is_reference_not_persona_id"
    ] is True
    assert insights["interpretation_boundaries"]["persona_tags_generated"] is False
    assert set(insights["reference_dimensions"]) == {
        "consumer_card",
        "aipl_node",
        "story_lines",
        "intent_type",
        "problem_type",
    }

    output_dir = tmp_path / "overlay"
    write_snapshot(output_dir, audit, insights, manifest)
    receipt = validate(output_dir, BASE_SNAPSHOT)

    assert receipt["status"] == "passed"
    assert all(receipt["checks"].values())
    assert receipt["production_unchanged"] is True
    assert receipt["provider_call"] is False
    assert receipt["database_write"] is False
    assert receipt["live_send"] is False


def test_holds_source_incompatible_tag_even_with_perfect_label_precision() -> None:
    audit, insights, _ = build_fixture()
    customer_service = next(
        tag for tag in audit["tags"] if tag["tag_id"] == "L0-SVC-010"
    )

    assert customer_service["review_metrics"]["label_precision"] == 1.0
    assert customer_service["review_metrics"]["taxonomy_fit_rate"] == 0.0
    assert customer_service["promotion_status"] == "held"
    assert customer_service["gate_checks"]["taxonomy_fit_rate"] is False
    assert customer_service["gate_checks"]["governance_fit"] is False
    assert any(
        tag["tag_id"] == "L0-SVC-010" for tag in insights["held_tags"]
    )


def test_rejects_review_decisions_not_bound_to_exact_sample(tmp_path: Path) -> None:
    tampered_sample = json.loads(REVIEW_SAMPLE.read_text(encoding="utf-8"))
    tampered_sample["tags"][0]["definition"] += " tampered"
    tampered_path = tmp_path / "review-sample.json"
    tampered_path.write_text(
        json.dumps(tampered_sample, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="review decisions are not bound to the current sample"
    ):
        build(BASE_SNAPSHOT, tampered_path, REVIEW_DECISIONS)
