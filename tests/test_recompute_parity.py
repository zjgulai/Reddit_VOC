"""ADR-002 B2: recompute engine regression tests.

Runs the engine against the live served snapshot with anchor forced to the July
baseline date; asserts SELF-CONSISTENCY (schema keys, bucket day-continuity,
rate math) and the documented governance contract. Byte-parity with July is NOT
asserted — the July bucket attribution used the V2 center promotion engine which
is out of repo scope (documented deviation in ADR-002).
"""
import hashlib
import importlib.util
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recompute_derivatives", ROOT / "scripts" / "recompute_derivatives.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


@pytest.fixture(scope="module")
def snapshot():
    import urllib.request
    base = "https://radar.luteos.com/data/reddit-voc/reddit_voc_site_snapshot_20260723_v3_daily_001"

    def fetch(u):
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    return fetch(f"{base}/posts-public.json"), fetch(f"{base}/comments-public.json")


def _july_anchor():
    return datetime(2026, 7, 23, 8, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_window_buckets_match_july_contract(snapshot):
    """July baseline emits contiguous, zero-filled buckets: 7 days / 30 days / 7 months."""
    posts, comments = snapshot
    expected = {"rolling_7_days": 7, "rolling_30_days": 30, "rolling_183_days": 7}
    with patch.object(rd, "_t1_anchor", _july_anchor):
        qi = rd.recompute_quarter_insights(posts, comments, dataset_version="reddit_voc_quarter_insights_test_v1")
    for w in qi["dashboard_windows"]:
        buckets = [b["bucket"] for b in w["buckets"]]
        assert len(buckets) == expected[w["id"]], (
            f"{w['id']}: expected {expected[w['id']]} buckets, got {len(buckets)}"
        )
        # contiguity: day grain one-day steps, month grain one-month steps
        for prev, cur in zip(buckets, buckets[1:]):
            if w["bucket_grain"] == "day":
                assert (date.fromisoformat(cur) - date.fromisoformat(prev)).days == 1, cur
            else:
                py, pm = int(prev[:4]), int(prev[5:7])
                cy, cm = int(cur[:4]), int(cur[5:7])
                assert (cy - py) * 12 + (cm - pm) == 1, f"{prev} -> {cur}"
        if w["bucket_grain"] == "day":
            assert buckets[-1] == "2026-07-23", "last day bucket must be the anchor"
        else:
            assert buckets[-1] == "2026-07", "last month bucket must be the anchor month"


def test_negative_rate_math_consistent(snapshot):
    posts, comments = snapshot
    with patch.object(rd, "_t1_anchor", _july_anchor):
        qi = rd.recompute_quarter_insights(posts, comments, dataset_version="reddit_voc_quarter_insights_test_v1")
    for w in qi["dashboard_windows"]:
        m = w["momcozy"]
        if m["classified_vocs"]:
            expected = round(m["negative_vocs"] * 10_000 / m["classified_vocs"]) / 100
            assert m["negative_rate"] == expected
        else:
            assert m["negative_rate"] is None


def test_window_totals_equal_bucket_sums(snapshot):
    posts, comments = snapshot
    with patch.object(rd, "_t1_anchor", _july_anchor):
        qi = rd.recompute_quarter_insights(posts, comments, dataset_version="reddit_voc_quarter_insights_test_v1")
    for w in qi["dashboard_windows"]:
        if w["bucket_grain"] != "day":
            continue
        assert sum(b["total_vocs"] for b in w["buckets"]) == w["momcozy"]["total_vocs"]
        assert sum(b["post_vocs"] for b in w["buckets"]) == w["momcozy"]["post_vocs"]


def test_dead_report_engine_with_fake_metrics_is_gone():
    """`recompute_reports_daily` published hardcoded 100.00 / 0.00 / 0.00pp for
    RV-DH-05, RV-PS-02 and RV-PS-04 and claimed `is_complete: true`. It was never
    called in production, but the fake constants must not exist anywhere -- and no
    test may keep exercising that path instead of the real bundle builder."""
    assert not hasattr(rd, "recompute_reports_daily"), "dead report engine still present"
    source = (ROOT / "scripts" / "recompute_derivatives.py").read_text(encoding="utf-8")
    for fake in ('"RV-DH-05", "证据完整率", 100.00', '"RV-PS-02", "产品问题率", 0.00',
                 '"RV-PS-04", "产品竞品问题差", 0.00'):
        assert fake not in source, f"hardcoded fake metric still in source: {fake}"


def test_aggregates_headline_matches_inputs(snapshot):
    posts, comments = snapshot
    ag = rd.recompute_aggregates(posts, comments)
    assert ag["headline"]["analysis_covered_posts"] == len(posts)
    assert ag["headline"]["analysis_covered_comments"] == len(comments)
    assert ag["headline"]["unique_posts"] == len(posts)
    assert ag["headline"]["linked_comments"] == len(comments)
    tp = ag["time_precision"]
    assert tp["posts"]["day"] + tp["posts"]["instant"] == len(posts)
    assert tp["comments"]["day"] + tp["comments"]["instant"] == len(comments)
    assert tp["day_precision_midnight_imputed"] is False


def test_brand_health_projection_is_self_consistent(snapshot):
    """Step 3.5.4 contract: 4 dimensions in fixed order, scores in [0,100],
    overall = equal-weight mean, and manifest<->data lineage matches."""
    posts, comments = snapshot
    hashes = {
        "brand_health_sha256": "a" * 64,
        "facts_manifest_sha256": "b" * 64,
        "metrics_manifest_sha256": "c" * 64,
        "metrics_validation_receipt_sha256": "d" * 64,
    }
    data, manifest = rd.recompute_brand_health(
        posts,
        comments,
        projection_id="reddit_voc_brand_health_test_v1",
        source_hashes=hashes,
        snapshot_id="test_snapshot",
    )
    assert [d["dimension_id"] for d in data["dimensions"]] == [
        "reputation",
        "product_experience",
        "recommendation_trust",
        "risk_resilience",
    ]
    assert [d["label"] for d in data["dimensions"]] == [
        "口碑健康",
        "产品体验",
        "推荐信任",
        "风险韧性",
    ]
    scores = [d["score"] for d in data["dimensions"]]
    assert all(s is None or 0 <= s <= 100 for s in scores)
    if all(s is not None for s in scores):
        assert data["overall"]["score"] == round(sum(scores) / 4, 2)
        assert data["overall"]["status"] != "unavailable"
    # manifest lineage must mirror data.source exactly (the frontend asserts this)
    assert manifest["source_brand_health_sha256"] == data["source"]["brand_health_sha256"]
    assert manifest["source_metrics_manifest_sha256"] == data["source"]["metrics_manifest_sha256"]
    assert (
        manifest["source_metrics_validation_receipt_sha256"]
        == data["source"]["metrics_validation_receipt_sha256"]
    )
    assert manifest["source_snapshot_id"] == data["source"]["snapshot_id"]
    # the file entry must describe the exact serialized bytes
    blob = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    assert manifest["files"]["brand-health.json"]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert manifest["files"]["brand-health.json"]["bytes"] == len(blob)
    # boundaries the frontend enforces
    assert data["boundaries"]["pii_removed"] is True
    assert data["boundaries"]["contains_source_text"] is False


def test_quarter_insights_matches_frozen_schema(snapshot):
    """The v3 quarter-insights contract is frozen; any missing or renamed key makes
    the workbench refuse to render, so the shape is asserted field by field."""
    posts, comments = snapshot
    with patch.object(rd, "_t1_anchor", _july_anchor):
        qi = rd.recompute_quarter_insights(
            posts, comments, dataset_version="reddit_voc_quarter_insights_test_v1"
        )
    assert set(qi) == {
        "boundaries", "case_references", "counts", "dashboard_windows", "dataset_version",
        "generated_at_utc", "period", "personas", "schema_version", "source", "themes",
    }
    assert len(qi["boundaries"]) == 18
    assert all(isinstance(v, bool) for v in qi["boundaries"].values())
    assert set(qi["period"]) == {"anchor_date", "days", "end_date", "inclusive", "start_date", "timezone"}
    assert qi["period"]["days"] == 90
    assert qi["period"]["anchor_date"] == qi["period"]["end_date"]
    assert qi["period"]["inclusive"] is True
    assert qi["period"]["timezone"] == "Asia/Shanghai"

    counts = qi["counts"]
    assert set(counts) == {
        "analysis_comment_context_vocs", "analysis_post_vocs", "canonical_posts",
        "competitor_union_vocs", "linked_comment_context_vocs", "momcozy",
        "momcozy_competitor_overlap_vocs", "periodic_comments", "unresolved_parent_comments",
    }
    mc = counts["momcozy"]
    assert set(mc) == {"comment_context_vocs", "post_vocs", "sentiment", "total_vocs"}
    sent = mc["sentiment"]
    assert set(sent) == {
        "classified", "missing", "negative", "negative_rate", "negative_rate_denominator",
        "negative_rate_unit", "neutral", "positive",
    }
    assert mc["total_vocs"] == mc["post_vocs"] + mc["comment_context_vocs"]
    assert sent["classified"] == sent["positive"] + sent["neutral"] + sent["negative"]
    assert mc["total_vocs"] == sent["classified"] + sent["missing"]
    assert counts["analysis_comment_context_vocs"] == counts["linked_comment_context_vocs"]
    assert counts["periodic_comments"] == (
        counts["linked_comment_context_vocs"] + counts["unresolved_parent_comments"]
    )

    for window in qi["dashboard_windows"]:
        assert set(window) == {
            "bucket_grain", "buckets", "days", "end_date", "id", "momcozy", "start_date",
            "top_competitor",
        }
        assert window["top_competitor"]["id"]
        assert window["top_competitor"]["label"]
        assert sum(b["total_vocs"] for b in window["buckets"]) == window["momcozy"]["total_vocs"]
        for bucket in window["buckets"]:
            assert bucket["total_vocs"] == bucket["post_vocs"] + bucket["comment_context_vocs"]

    themes = qi["themes"]
    assert set(themes) == {"geo", "new_product", "pain", "reputation"}
    assert set(themes["pain"]) == {"evidence", "method", "rankings"}
    assert set(themes["reputation"]) == {
        "automation_comments", "evidence", "high_severity_vocs", "method",
        "negative_vocs", "quarter_moderation_claim_evidence_count", "rankings",
    }
    assert set(themes["new_product"]) == {
        "category_rankings", "evidence", "exact_spu_rankings", "family_only_ids",
        "family_rankings", "method", "product_rankings",
    }
    assert set(themes["geo"]) == {"comparison_decision_posts", "evidence", "method", "rankings"}
    for ranking in themes["pain"]["rankings"]:
        assert set(ranking) == {"count", "id", "label"}
    rep_map = {r["id"]: r["count"] for r in themes["reputation"]["rankings"]}
    for key in (
        "automation_comments",
        "high_severity_vocs",
        "negative_vocs",
        "quarter_moderation_claim_evidence_count",
    ):
        assert rep_map[key] == themes["reputation"][key]
    assert sum(r["count"] for r in themes["geo"]["rankings"]) == themes["geo"]["comparison_decision_posts"]
    for evidence in (themes["pain"]["evidence"], themes["geo"]["evidence"]):
        assert evidence
        assert all(set(e) == {"comment_id", "post_id", "reason"} for e in evidence)

    personas = qi["personas"]
    assert set(personas) == {
        "category_context_assignment_count", "category_context_unique_entities", "cohorts",
        "date_basis", "main_assignment_count", "main_assignment_ids", "main_scope",
        "main_unique_entities",
    }
    assert personas["date_basis"] == "content_entity_event_date"
    assert personas["main_scope"] == ["momcozy_direct", "momcozy_multi"]
    assert len(personas["main_assignment_ids"]) == personas["main_assignment_count"]
    assert personas["main_assignment_ids"] == sorted(set(personas["main_assignment_ids"]))
    assert [c["cohort_id"] for c in personas["cohorts"]] == rd.COHORT_ORDER
    assert sum(c["assignment_count"] for c in personas["cohorts"]) == personas["main_assignment_count"]

    assert set(qi["case_references"]) == {"geo", "new_product", "pain", "reputation"}
    for reference in qi["case_references"].values():
        assert set(reference) == {"id", "role"}


def test_brand_health_contribution_matches_js_rounding():
    """The client recomputes contribution as Math.round((value/4)*100)/100 (half-up).
    Python's round() is banker's rounding, which disagrees exactly at .xx5 values."""
    import importlib.util as _ilu
    import math as _math

    spec = _ilu.spec_from_file_location(
        "recompute_reports_bundle", ROOT / "scripts" / "recompute_reports_bundle.py"
    )
    bundle = _ilu.module_from_spec(spec)
    spec.loader.exec_module(bundle)

    def js_round(value: float) -> float:
        return _math.floor((value / 4) * 100 + 0.5) / 100

    for dimension_value in (74.5, 58.99, 95.67, 70.05, 73.13, 50.0, 62.5, 0.0, 100.0):
        data = bundle._brand_health_block(
            {"dimensions": [{"dimension_id": dim, "score": dimension_value}
                            for dim in bundle.DIMENSION_IDS],
             "overall": {"score": dimension_value}},
            {"period_id": "daily:2026-10-26:2026-10-27", "start": "2026-10-26", "end": "2026-10-27"},
            "daily",
            bundle.profile_hashes(),
        )
        for row in data["dimension_rows"]:
            assert row["contribution_points"] == js_round(dimension_value), dimension_value


def test_wider_windows_are_supersets(snapshot):
    """A wider window must never see fewer VOCs than a narrower one. Regression for
    the bug where every rolling window was capped by the 90-day quarter slice, so
    rolling_183_days silently equalled rolling_30_days."""
    posts, comments = snapshot
    with patch.object(rd, "_t1_anchor", _july_anchor):
        qi = rd.recompute_quarter_insights(posts, comments, dataset_version="reddit_voc_quarter_insights_test_v1")
    by_id = {w["id"]: w["momcozy"]["total_vocs"] for w in qi["dashboard_windows"]}
    assert by_id["rolling_7_days"] <= by_id["rolling_30_days"] <= by_id["rolling_183_days"], by_id
    month_window = next(w for w in qi["dashboard_windows"] if w["id"] == "rolling_183_days")
    assert sum(b["total_vocs"] for b in month_window["buckets"]) == month_window["momcozy"]["total_vocs"]
