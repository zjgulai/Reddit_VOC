"""The workbench lock must describe the current release, not the retired stack."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "verify_workbench_lock", ROOT / "scripts" / "verify_workbench_lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lock():
    return {
        "schema_version": "echo_agent_workbench_release_lock_v1",
        "production_host": "43.163.92.244",
        "public_url": "https://radar.luteos.com",
        "data_path": "/opt/voc-report/html/data/reddit-voc",
        "observed_at": "2026-11-03T10:52:02Z",
        "release_id": "reddit_voc_release_20260723_daily_v2",
        "run_id": "daily_collect_20261103_070500",
        "pointer_sha256": "a" * 64,
        "generated_at_utc": "2026-11-02T23:14:00Z",
        "data_as_of_utc": "2026-11-02T23:00:00Z",
        "window_start_utc": "2026-11-01T23:00:00Z",
        "window_end_utc": "2026-11-02T23:00:00Z",
        "datasets": {
            key: {"dataset_version": f"v-{key}", "public_manifest_sha256": "b" * 64}
            for key in (
                "base",
                "insights",
                "reports",
                "personas",
                "brand_health",
                "quarter_insights",
                "casebook",
            )
        },
    }


def test_current_shape_is_valid() -> None:
    module = _load()
    assert module.validate_lock(_lock()) == []


def test_missing_dataset_is_rejected() -> None:
    module = _load()
    lock = copy.deepcopy(_lock())
    lock["datasets"].pop("casebook")
    assert "datasets_keys" in module.validate_lock(lock)


def test_bad_sha_is_rejected() -> None:
    module = _load()
    lock = copy.deepcopy(_lock())
    lock["datasets"]["base"]["public_manifest_sha256"] = "not-a-sha"
    assert "dataset_sha:base" in module.validate_lock(lock)


def test_public_compare_detects_release_mismatch() -> None:
    module = _load()
    lock = _lock()
    pointer = {
        "release_id": "other-release",
        "generated_at_utc": lock["generated_at_utc"],
        "freshness": {
            "collector_run_id": lock["run_id"],
            "data_as_of_utc": lock["data_as_of_utc"],
        },
    }
    errors = module.compare_public(lock, pointer, lock["pointer_sha256"])
    assert errors == ["release_id_mismatch"]


def test_public_compare_matches() -> None:
    module = _load()
    lock = _lock()
    pointer = {
        "release_id": lock["release_id"],
        "generated_at_utc": lock["generated_at_utc"],
        "freshness": {
            "collector_run_id": lock["run_id"],
            "data_as_of_utc": lock["data_as_of_utc"],
        },
    }
    assert module.compare_public(lock, pointer, lock["pointer_sha256"]) == []