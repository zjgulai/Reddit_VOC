"""The morning-brief card must never claim verification it does not have.

On 2026-10-29 the 07:05 run died in `recompute_derivatives`, yet the card that
reached the group chat still read "版本完整性已验证" because
`partial_1_step_errors` sat on a whitelist. The card is the only channel a human
reads, so a green card over a failed publish is the most expensive possible bug:
every number below it may come from the previous generation.

These tests pin the contract:
  - only an exact `success` may say 已验证
  - any other status is red and names the failed step
  - an in-memory receipt wins over disk (the writer still holds the file open)
  - a missing receipt degrades to an honest red card instead of raising
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "feishu-card" / "builders" / "build_morning_brief_v4.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("morning_brief_v4", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mb = _load_builder()

RUN_ID = "daily_collect_20261029_0700"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_site(tmp_path: Path, *, calm_business: bool = False) -> tuple[Path, Path]:
    """Minimal site tree the card builder reads, mirroring production layout.

    `calm_business` keeps the business indicators quiet (no negative-rate spike), so
    the header colour is decided by the pipeline receipt alone. Without it the
    fixture's +265.7% negative rate legitimately forces red and would mask the
    receipt contract under test.
    """
    run_dir = tmp_path / "outputs"
    public_root = tmp_path / "html"
    data_voc = public_root / "data" / "reddit-voc"

    for name in ("content-ideas", "rnd-tickets", "competitor-radar"):
        _write(run_dir / f"{RUN_ID}-daily-{name}.json", {"results": [], "total_topics": 0})

    neg_display, neg_direction = ("-3.2%", "down") if calm_business else ("+265.7%", "up")
    report_dir = data_voc / "reddit_voc_reports_demo_v1"
    _write(
        report_dir / "public" / "current" / "daily.json",
        {
            "indicators": [
                {"metric_id": "RV-BR-01", "current": {"display": "27"},
                 "comparisons": {"period_over_period": {"display": "-63.5%", "direction": "down"}}},
                {"metric_id": "RV-BR-02", "current": {"display": "14.81%"},
                 "comparisons": {"period_over_period": {"display": neg_display, "direction": neg_direction}}},
                {"metric_id": "RV-BR-04", "current": {"display": "44.44%"},
                 "comparisons": {"period_over_period": {"display": "+152.9%", "direction": "up"}}},
            ]
        },
    )

    base_dir = data_voc / "reddit_voc_site_snapshot_demo_v1"
    _write(base_dir / "aggregates-public.json",
           {"headline": {"unique_posts": 25873, "linked_comments": 100778}})
    _write(base_dir / "posts-public.json", [])

    _write(
        data_voc / "reddit_voc_quarter_insights_20260723_public_v1" / "quarter-insights.json",
        {
            "themes": {"pain": {"rankings": [
                {"label": "操作与可靠性", "count": 162},
                {"label": "适配与舒适度", "count": 123},
            ]}},
            "counts": {"momcozy": {"post_vocs": 208, "comment_context_vocs": 547}},
        },
    )

    _write(
        data_voc / "current-release.json",
        {
            "freshness": {"data_as_of_utc": "2026-10-28T23:00:00Z"},
            "datasets": {
                "reports": {
                    "dataset_version": "reports_demo_v1",
                    "manifest_path": "data/reddit-voc/reddit_voc_reports_demo_v1/public/manifest.json",
                },
                "base": {
                    "dataset_version": "demo_v1",
                    "manifest_path": "data/reddit-voc/reddit_voc_site_snapshot_demo_v1/manifest-public.json",
                },
            },
        },
    )
    return run_dir, public_root


def _partial_receipt() -> dict:
    return {
        "status": "partial_1_step_errors",
        "report_date": "2026-10-29",
        "steps": [
            {"step": "collect", "status": "success"},
            {"step": "agents", "status": "ok"},
            {"step": "merge_snapshot", "status": "ok"},
            {"step": "recompute_derivatives", "status": "error",
             "error": "[Errno 13] Permission denied: lineage/product-entity-ledger.json"},
            {"step": "advance_pointer", "status": "blocked_by_prerequisites"},
        ],
        "errors": [{"step": "recompute_derivatives", "status": "error"}],
    }


def _success_receipt() -> dict:
    receipt = _partial_receipt()
    receipt["status"] = "success"
    receipt["steps"] = [
        {"step": "collect", "status": "success"},
        {"step": "agents", "status": "ok"},
        {"step": "merge_snapshot", "status": "ok"},
        {"step": "recompute_derivatives", "status": "ok"},
        {"step": "advance_pointer", "status": "advanced"},
        {"step": "feishu_push", "status": "sent"},
    ]
    receipt["errors"] = []
    return receipt


def _card_text(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False)


def test_card_is_red_and_unverified_when_receipt_status_is_partial(tmp_path: Path) -> None:
    run_dir, public_root = make_site(tmp_path)
    card = mb.build_card(run_dir, public_root, RUN_ID, receipt=_partial_receipt())
    assert card["header"]["template"] != "green"
    assert card["header"]["template"] == "red"
    text = _card_text(card)
    assert "未验证" in text
    assert "已验证" not in text


def test_card_never_reports_verified_for_partial_1_step_errors(tmp_path: Path) -> None:
    """The exact regression: this status used to be whitelisted as verified."""
    run_dir, public_root = make_site(tmp_path)
    card = mb.build_card(run_dir, public_root, RUN_ID, receipt=_partial_receipt())
    trust = next(
        (node for node in _walk(card) if isinstance(node, str) and "版本完整性" in node), None
    )
    assert trust is not None, "card must carry a trust line"
    assert "版本完整性未验证" in trust
    assert "部分通过" not in trust


def test_card_uses_in_memory_receipt_not_disk(tmp_path: Path) -> None:
    """step5 holds the receipt before the file lands; disk must not be consulted."""
    run_dir, public_root = make_site(tmp_path, calm_business=True)
    assert not (run_dir / f"{RUN_ID}-pipeline-receipt.json").exists()
    card = mb.build_card(run_dir, public_root, RUN_ID, receipt=_success_receipt())
    assert card["header"]["template"] == "green"


def test_card_names_failed_step(tmp_path: Path) -> None:
    run_dir, public_root = make_site(tmp_path)
    card = mb.build_card(run_dir, public_root, RUN_ID, receipt=_partial_receipt())
    text = _card_text(card)
    assert "recompute_derivatives" in text, "the card must name the step that failed"
    assert "advance_pointer" in text, "blocked downstream steps must be visible too"


def test_card_is_unverified_when_receipt_missing(tmp_path: Path) -> None:
    """No receipt must render an honest red card, never raise."""
    run_dir, public_root = make_site(tmp_path)
    card = mb.build_card(run_dir, public_root, RUN_ID)
    assert card["header"]["template"] == "red"
    text = _card_text(card)
    assert "未验证" in text
    assert "已验证" not in text


def test_success_receipt_is_the_only_green_path(tmp_path: Path) -> None:
    run_dir, public_root = make_site(tmp_path, calm_business=True)
    card = mb.build_card(run_dir, public_root, RUN_ID, receipt=_success_receipt())
    assert card["header"]["template"] == "green"
    assert "版本完整性已验证" in _card_text(card)


def test_failed_pipeline_outranks_calm_business_signal(tmp_path: Path) -> None:
    """A quiet business day must not mask a failed publish: red either way."""
    run_dir, public_root = make_site(tmp_path, calm_business=True)
    card = mb.build_card(run_dir, public_root, RUN_ID, receipt=_partial_receipt())
    assert card["header"]["template"] == "red"


def _walk(node):
    """Yield every scalar inside a nested card dict."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)
    else:
        yield node
