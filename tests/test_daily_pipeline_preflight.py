"""Preflight must see per-file permissions, not just directory bits.

Regression for 2026-10-29 07:05: the run passed preflight, collected and merged
73 posts / 291 comments, then died in recompute writing a root-owned 0600
`lineage/product-entity-ledger.json` that lived inside a *writable* directory.
Directory-level `os.access(W_OK)` cannot observe that, so this suite pins the
file-level contract.

The second incident that day was a root-owned 0700 `data/raw` directory blocking
the archive backfill; both are "the target looked writable from the parent".
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_daily_t1_pipeline as pipeline  # noqa: E402


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_site(tmp_path: Path, *, file_mode: int | None = None, lineage_mode: int | None = None) -> dict:
    """Build the smallest tree that exercises every branch of the target collector.

    Layout mirrors production exactly, which matters because the collector derives
    file targets from the manifest's own directory:
      base    -> <version>/manifest-public.json  + files beside it in <version>/
      reports -> <version>/public/manifest.json  + files under <version>/public/
      lineage -> <version>/lineage/               (dataset-local, the 10-29 shape)
    """
    public_root = tmp_path / "html"
    data_voc = public_root / "data" / "reddit-voc"
    data_voc.mkdir(parents=True, exist_ok=True)

    store = tmp_path / "data" / "store.sqlite3"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_bytes(b"SQLite format 3\x00")

    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- base: manifest-public.json sits IN the dataset dir, files beside it ---
    base_dir = data_voc / "reddit_voc_site_snapshot_demo_v1"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_files = {"posts-public.json": {"bytes": 2, "sha256": "0" * 64}}
    for name in base_files:
        _write(base_dir / name, [])
    base_manifest = {"dataset_version": "demo_v1", "files": base_files}
    _write(base_dir / "manifest-public.json", base_manifest)
    _write(base_dir / "manifest.json", base_manifest)

    # The 10-29 shape: a dataset-local lineage directory holding a file the run
    # must rewrite.
    for lineage in (base_dir / "lineage", data_voc / "lineage"):
        lineage.mkdir(parents=True, exist_ok=True)
        ledger = lineage / "product-entity-ledger.json"
        _write(ledger, {"ledger": []})
        if lineage_mode is not None:
            os.chmod(ledger, lineage_mode)

    # --- reports: content-addressed bundle with public/ wrapper ---
    reports_dir = data_voc / "reddit_voc_reports_demo_v1"
    reports_files = {"current/daily.json": {}, "validation-receipt.json": {}}
    for name in reports_files:
        _write(reports_dir / "public" / name, {})
    _write(reports_dir / "public" / "manifest.json", {"files": reports_files})

    release = {
        "datasets": {
            "base": {
                "dataset_version": "demo_v1",
                "manifest_path": "data/reddit-voc/reddit_voc_site_snapshot_demo_v1/manifest-public.json",
                "public_manifest_sha256": "0" * 64,
            },
            "reports": {
                "dataset_version": "reports_demo_v1",
                "manifest_path": "data/reddit-voc/reddit_voc_reports_demo_v1/public/manifest.json",
                "public_manifest_sha256": "0" * 64,
            },
        }
    }
    _write(data_voc / "current-release.json", release)

    if file_mode is not None:
        os.chmod(base_dir / "posts-public.json", file_mode)

    return {
        "public_root": public_root,
        "store": store,
        "output_dir": output_dir,
        "data_voc": data_voc,
        "base_dir": base_dir,
    }


def test_rejects_readonly_file_in_writable_dir(tmp_path: Path) -> None:
    """The exact 10-29 failure: mode 0400 inside a directory that is itself writable."""
    site = make_site(tmp_path, file_mode=0o400)
    with pytest.raises(RuntimeError) as excinfo:
        pipeline._preflight_writability(site["public_root"], site["store"], site["output_dir"])
    message = str(excinfo.value)
    assert message.startswith("pipeline_preflight_unwritable_targets:")
    payload = json.loads(message.split(":", 1)[1].strip())
    reasons = {entry["path"]: entry["reason"] for entry in payload}
    target = str(site["base_dir"] / "posts-public.json")
    assert target in reasons, f"expected {target} in {reasons}"
    assert reasons[target] == "mode_denies_write"
    entry = next(e for e in payload if e["path"] == target)
    assert entry["mode"] == oct(0o400)
    assert entry["uid"] is not None


def test_rejects_unreadable_file_in_writable_dir(tmp_path: Path) -> None:
    """A write-only file breaks the generation copy, which must read what it publishes."""
    site = make_site(tmp_path, file_mode=0o200)
    with pytest.raises(RuntimeError) as excinfo:
        pipeline._preflight_writability(site["public_root"], site["store"], site["output_dir"])
    payload = json.loads(str(excinfo.value).split(":", 1)[1].strip())
    reasons = {entry["path"]: entry["reason"] for entry in payload}
    target = str(site["base_dir"] / "posts-public.json")
    assert reasons.get(target) == "not_readable", reasons


def test_checks_base_lineage_subdir(tmp_path: Path) -> None:
    """The ledger under the dataset's OWN lineage/ was invisible to the old code.

    On 10-29 that file was root-owned 0600 and the service user was `ubuntu`, so
    for the run it had no usable write bit. A test cannot change ownership without
    root, so 0400 reproduces the same observable state: a file the pipeline must
    rewrite but may not. The point of this case is that the PATH is enumerated at
    all — the old code only derived `data/reddit-voc/lineage` and missed
    `<version>/lineage` entirely.
    """
    site = make_site(tmp_path, lineage_mode=0o400)
    with pytest.raises(RuntimeError) as excinfo:
        pipeline._preflight_writability(site["public_root"], site["store"], site["output_dir"])
    payload = json.loads(str(excinfo.value).split(":", 1)[1].strip())
    blocked_paths = {entry["path"] for entry in payload}
    dataset_ledger = str(site["base_dir"] / "lineage" / "product-entity-ledger.json")
    assert dataset_ledger in blocked_paths, (
        "dataset-local lineage must be checked; the old code only derived "
        "data/reddit-voc/lineage and missed this"
    )


def test_checks_store_sqlite_file(tmp_path: Path) -> None:
    """The store is written in place, so its own mode matters, not just its parent."""
    site = make_site(tmp_path)
    os.chmod(site["store"], 0o400)
    with pytest.raises(RuntimeError) as excinfo:
        pipeline._preflight_writability(site["public_root"], site["store"], site["output_dir"])
    payload = json.loads(str(excinfo.value).split(":", 1)[1].strip())
    reasons = {entry["path"]: entry["reason"] for entry in payload}
    assert reasons.get(str(site["store"])) == "mode_denies_write", reasons


def test_accepts_writable_tree(tmp_path: Path) -> None:
    """A healthy tree must pass and report what it actually checked."""
    site = make_site(tmp_path)
    report = pipeline._preflight_writability(site["public_root"], site["store"], site["output_dir"])
    assert report["checked"] > 0
    assert report["warnings"] == [] or all(
        w["reason"] == "foreign_owner" for w in report["warnings"]
    )


def test_run_pipeline_fails_before_step1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preflight must run before collection: zero collect calls, zero corpus writes."""
    site = make_site(tmp_path, file_mode=0o400)

    calls: list[str] = []

    def _boom(*args, **kwargs):
        calls.append("collect")
        raise AssertionError("step1_collect must not run when preflight fails")

    monkeypatch.setattr(pipeline, "step1_collect", _boom)
    monkeypatch.setattr(pipeline, "step2_agents", _boom)
    monkeypatch.setattr(pipeline, "step3_merge_snapshot", _boom)
    monkeypatch.setattr(pipeline, "step3_5_recompute_derivatives", _boom)

    with pytest.raises(RuntimeError) as excinfo:
        pipeline.run_pipeline(
            store_path=site["store"],
            public_root=site["public_root"],
            output_dir=site["output_dir"],
            skip_feishu=True,
        )
    assert str(excinfo.value).startswith("pipeline_preflight_unwritable_targets:")
    assert calls == [], f"no pipeline step may run before preflight; got {calls}"

    # The corpus must be byte-identical: nothing was rewritten.
    assert (site["base_dir"] / "posts-public.json").read_text(encoding="utf-8") == "[]"
