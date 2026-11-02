"""Run-level build receipts: the evidence the freshness monitor reads.

`write_build_receipt` existed since L5-T02 but the pipeline never called it, so
`build-receipts/` was always missing and the freshness monitor permanently
reported `build_receipt_missing`. These tests pin the pipeline helper:

* success and failure both leave a receipt;
* a successful run writes it inside the staged generation, not the live tree;
* the receipt's release block is the pointer that was published;
* the same run id cannot be rewritten with different bytes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "run_daily_t1_pipeline", ROOT / "scripts" / "run_daily_t1_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path):
    public_root = tmp_path / "html"
    data_root = public_root / "data" / "reddit-voc"
    dataset = "demo_base"
    dataset_dir = data_root / dataset
    dataset_dir.mkdir(parents=True)
    manifest = {"dataset_version": dataset, "files": {}}
    manifest_path = dataset_dir / "manifest-public.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    release = {
        "schema_version": "reddit_voc_current_release_v2",
        "release_id": "demo-release",
        "datasets": {
            "base": {
                "dataset_version": dataset,
                "manifest_path": f"data/reddit-voc/{dataset}/manifest-public.json",
                "public_manifest_sha256": sha,
            }
        },
    }
    return public_root, data_root, release


def _receipt_doc(run_id: str, status: str = "success") -> dict:
    return {
        "run_id": run_id,
        "status": status,
        "started_at_utc": "2026-11-02T07:05:00+00:00",
        "finished_at_utc": "2026-11-02T07:16:07+00:00",
        "steps": [
            {"step": "collect", "status": "success"},
            {"step": "commit_generation", "status": "committed"},
        ],
        "errors": [],
    }


def test_success_writes_a_receipt_with_the_pointer_release(tmp_path: Path) -> None:
    pipeline = _load_pipeline()
    public_root, _, release = _fixture(tmp_path)
    receipt_doc = _receipt_doc("daily_collect_20261102_070500")

    step = pipeline._write_run_build_receipt(
        public_root=public_root,
        mode="off",
        tx=None,
        release_doc=release,
        receipt_doc=receipt_doc,
        period_end_utc="2026-11-01T23:00:00Z",
    )

    assert step["status"] == "ok"
    written = json.loads(Path(step["path"]).read_text(encoding="utf-8"))
    assert written["run_id"] == "daily_collect_20261102_070500"
    assert written["status"] == "success"
    assert written["release_id"] == "demo-release"
    assert written["datasets"]["base"]["manifest_path"] == (
        "demo_base/manifest-public.json"
    )
    assert written["period_end_utc"] == "2026-11-01T23:00:00Z"


def test_failure_also_leaves_a_receipt(tmp_path: Path) -> None:
    pipeline = _load_pipeline()
    public_root, _, release = _fixture(tmp_path)
    receipt_doc = _receipt_doc("daily_collect_20261102_070500", status="failed")
    receipt_doc["errors"] = [{"step": "recompute_derivatives", "status": "error", "error": "boom"}]

    step = pipeline._write_run_build_receipt(
        public_root=public_root,
        mode="off",
        tx=None,
        release_doc=release,
        receipt_doc=receipt_doc,
        period_end_utc="2026-11-01T23:00:00Z",
    )

    written = json.loads(Path(step["path"]).read_text(encoding="utf-8"))
    assert written["status"] == "failed"
    assert written["errors"][0]["step"] == "recompute_derivatives"


def test_symlink_mode_writes_inside_the_generation_not_the_live_tree(tmp_path: Path) -> None:
    pipeline = _load_pipeline()
    public_root, data_root, release = _fixture(tmp_path)
    generation = tmp_path / "generations" / "daily_collect_20261102_070500" / "reddit-voc"
    generation.mkdir(parents=True)
    shutil_copied = generation / "demo_base"
    shutil_copied.mkdir()
    (shutil_copied / "manifest-public.json").write_text(
        (data_root / "demo_base" / "manifest-public.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    step = pipeline._write_run_build_receipt(
        public_root=public_root,
        mode="symlink",
        tx=SimpleNamespace(root=generation),
        release_doc=release,
        receipt_doc=_receipt_doc("daily_collect_20261102_070500"),
        period_end_utc="2026-11-01T23:00:00Z",
    )

    assert step["status"] == "ok"
    assert (generation / "build-receipts" / "daily_collect_20261102_070500.json").is_file()
    assert not (data_root / "build-receipts").exists()


def test_same_run_id_cannot_be_rewritten_with_different_bytes(tmp_path: Path) -> None:
    pipeline = _load_pipeline()
    public_root, data_root, release = _fixture(tmp_path)
    run_id = "daily_collect_20261102_070500"

    first = pipeline._write_run_build_receipt(
        public_root=public_root,
        mode="off",
        tx=None,
        release_doc=release,
        receipt_doc=_receipt_doc(run_id),
        period_end_utc="2026-11-01T23:00:00Z",
    )
    original = Path(first["path"]).read_bytes()

    with pytest.raises(Exception, match="build_receipt_collision"):
        pipeline._write_run_build_receipt(
            public_root=public_root,
            mode="off",
            tx=None,
            release_doc=release,
            receipt_doc=_receipt_doc(run_id, status="failed"),
            period_end_utc="2026-11-01T23:00:00Z",
        )
    assert Path(first["path"]).read_bytes() == original