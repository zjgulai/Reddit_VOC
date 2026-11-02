"""Offline tests for the echo-ops daily-run verifier.

The verifier lives in `.claude/skills/echo-ops/scripts/` rather than `src/`
because it is an operator tool, not production code. These tests import it by
path so it still gets the same regression protection as the rest of the repo.

No SSH, no HTTP, no production paths: every remote fact is a fixture and the
public fetch is monkeypatched.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


VERIFIER_PATH = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "echo-ops"
    / "scripts"
    / "verify_daily_run.py"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("echo_ops_verify_daily_run", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load_verifier()


def _steps():
    statuses = {
        "collect": "success",
        "begin_generation": "ok",
        "agents": "ok",
        "merge_snapshot": "ok",
        "recompute_derivatives": "ok",
        "advance_pointer": "advanced",
        "build_stamps": "ok",
        "commit_generation": "committed",
        "gc_generations": "ok",
        "feishu_push": "sent",
    }
    return [{"step": name, "status": status} for name, status in statuses.items()]


def _healthy_data(**overrides):
    data = {
        "daily_service": {
            "Result": "success",
            "ExecMainStatus": "0",
            "ExecMainExitTimestamp": "Mon 2026-11-02 07:16:07 CST",
            "ActiveState": "inactive",
        },
        "daily_timer": {"ActiveState": "active"},
        "receipt_path": "/opt/echo-agent-bot/outputs/daily_collect_20261102_0700-pipeline-receipt.json",
        "receipt": {
            "run_id": "daily_collect_20261102_0700",
            "status": "success",
            "run_kind": "scheduled",
            "trigger": "systemd-timer",
            "steps": _steps(),
        },
        "pointer": {
            "path": "/opt/voc-report/html/data/reddit-voc",
            "is_symlink": True,
            "exists": True,
            "relative": True,
            "link_target": "reddit-voc-generations/daily_collect_20261102_0700/reddit-voc",
        },
        "generations": ["daily_collect_20261101_0700", "daily_collect_20261102_0700"],
        "pointer_sha256": "a" * 64,
        "pointer_document": {
            "freshness": {"data_as_of_utc": "2026-11-01T23:00:00Z"},
        },
        "build_receipts_exists": True,
        "freshness": {
            "state": "fresh",
            "healthy": True,
            "failures": [],
            "freshness_status": "full",
            "datasets": {"base": {"ok": True}, "reports": {"ok": True}},
        },
        "disk": {"free_percent": 44.0, "free": 216 * 1024**3},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


def _statuses(report):
    return {check["id"]: check["status"] for check in report.checks}


def test_healthy_run_is_all_pass_and_exit_zero():
    report = verify.evaluate(_healthy_data(), "https://example.invalid/pointer", public_enabled=False)
    statuses = _statuses(report)
    assert statuses["systemd"] == "PASS"
    assert statuses["steps"] == "PASS"
    assert statuses["k1_run_kind"] == "PASS"
    assert statuses["pointer"] == "PASS"
    assert statuses["freshness"] == "PASS"
    assert statuses["l5_t04_build_receipts"] == "PASS"
    assert report.exit_code() == 0


def test_missing_run_kind_is_a_finding_not_a_hard_failure():
    data = _healthy_data()
    data["receipt"].pop("run_kind")
    data["receipt"].pop("trigger")
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["k1_run_kind"] == "FIND"
    assert report.exit_code() == 2


def test_missing_build_receipts_is_a_finding():
    data = _healthy_data(build_receipts_exists=False)
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["l5_t04_build_receipts"] == "FIND"
    assert report.exit_code() == 2


def test_absolute_pointer_is_a_hard_failure():
    data = _healthy_data()
    data["pointer"]["relative"] = False
    data["pointer"]["link_target"] = "/opt/voc-report/html/data/reddit-voc-generations/g/reddit-voc"
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["pointer"] == "FAIL"
    assert report.exit_code() == 1


def test_missing_pipeline_step_is_a_hard_failure():
    data = _healthy_data()
    data["receipt"]["steps"] = [s for s in _steps() if s["step"] != "commit_generation"]
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["steps"] == "FAIL"
    assert report.exit_code() == 1


def test_freshness_failure_other_than_missing_receipt_is_a_hard_failure():
    data = _healthy_data()
    data["freshness"] = {
        "state": "failed",
        "healthy": False,
        "failures": ["release_manifest_sha_mismatch:base"],
        "freshness_status": "partial",
        "datasets": {"base": {"ok": False}},
    }
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["freshness"] == "FAIL"
    assert _statuses(report)["build_stamps"] == "FAIL"
    assert report.exit_code() == 1


def test_only_build_receipt_missing_keeps_freshness_pass_and_adds_finding():
    data = _healthy_data()
    data["freshness"] = {
        "state": "failed",
        "healthy": False,
        "failures": ["build_receipt_missing"],
        "freshness_status": "partial",
        "datasets": {"base": {"ok": True}},
    }
    data["build_receipts_exists"] = False
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["freshness"] == "PASS"
    assert _statuses(report)["l5_t04_build_receipts"] == "FIND"
    assert report.exit_code() == 2


def test_public_sha_mismatch_is_a_hard_failure(monkeypatch):
    data = _healthy_data()
    monkeypatch.setattr(
        verify,
        "_fetch_public",
        lambda url, timeout=20: {
            "status": 200,
            "content_type": "application/json",
            "sha256": "b" * 64,
            "json": {
                "generated_at_utc": "2026-11-01T23:16:05Z",
                "freshness": {
                    "collector_run_id": "daily_collect_20261102_0700",
                    "data_as_of_utc": "2026-11-01T23:00:00Z",
                },
            },
        },
    )
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=True)
    assert _statuses(report)["public_bytes"] == "FAIL"
    assert report.exit_code() == 1


def test_public_null_generated_at_is_a_hard_failure(monkeypatch):
    data = _healthy_data()
    monkeypatch.setattr(
        verify,
        "_fetch_public",
        lambda url, timeout=20: {
            "status": 200,
            "content_type": "application/json",
            "sha256": data["pointer_sha256"],
            "json": {
                "generated_at_utc": None,
                "freshness": {
                    "collector_run_id": "daily_collect_20261102_0700",
                    "data_as_of_utc": "2026-11-01T23:00:00Z",
                },
            },
        },
    )
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=True)
    assert _statuses(report)["public_generated_at"] == "FAIL"
    assert report.exit_code() == 1


def test_spa_fallback_content_type_is_a_hard_failure(monkeypatch):
    data = _healthy_data()
    monkeypatch.setattr(
        verify,
        "_fetch_public",
        lambda url, timeout=20: {
            "status": 200,
            "content_type": "text/html",
            "sha256": data["pointer_sha256"],
            "json": {
                "generated_at_utc": "2026-11-01T23:16:05Z",
                "freshness": {
                    "collector_run_id": "daily_collect_20261102_0700",
                    "data_as_of_utc": "2026-11-01T23:00:00Z",
                },
            },
        },
    )
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=True)
    assert _statuses(report)["public_content_type"] == "FAIL"
    assert report.exit_code() == 1


def test_product_counter_inconsistency_warns_without_failing():
    data = _healthy_data()
    data["receipt"]["steps"] = [
        {**step, **({"product_resolver_loaded": True, "product_bound_posts": 0,
                     "product_bound_comments": 0, "product_bindings_total": 2}
                    if step["step"] == "merge_snapshot" else {})}
        for step in _steps()
    ]
    report = verify.evaluate(data, "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["product_bindings_counter"] == "WARN"
    assert report.exit_code() == 0


def test_public_skip_is_explicit():
    report = verify.evaluate(_healthy_data(), "https://example.invalid/pointer", public_enabled=False)
    assert _statuses(report)["public"] == "SKIP"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))