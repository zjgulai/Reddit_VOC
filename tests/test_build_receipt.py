"""Each dataset must be able to prove which run produced it.

Nothing in the published tree linked "the pipeline ran" to "these are the bytes
this run wrote". On 2026-10-31 `data/reddit-voc` became a dangling symlink: every
`/data/` request 404'd, while `curl https://report.luteos.com/` returned 200 from
the SPA fallback. No artifact contradicted that, so nothing could have alerted.

A build stamp closes that gap by making three values agree:

    pointer binding.public_manifest_sha256
        == sha256(<dataset>/manifest.json bytes)
        == <dataset>/build.json manifest_sha256

These tests pin the stamp, the per-run receipt, and the refusal paths — a stamp
that records a disagreement would be worse than no stamp at all.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_receipt as br  # noqa: E402

DATASETS = {
    "base": "reddit_voc_site_snapshot_demo_v1",
    "quarter_insights": "quarter_insights_demo_v1",
    "brand_health": "brand_health_demo_v1",
    "reports": "reports_demo_v1",
    "personas": "personas_demo_v1",
    "insights": "insights_demo_v1",
    "casebook": "casebook_demo_v1",
}

# reports puts its manifest under public/; the others are flat.
MANIFEST_TAIL = {"reports": "public/manifest.json"}


def _manifest_rel(key: str, version: str) -> str:
    tail = MANIFEST_TAIL.get(key, "manifest.json")
    return f"data/reddit-voc/{version}/{tail}"


def make_site(tmp_path: Path) -> dict:
    """A public root with seven dataset manifests and a pointer naming them."""
    data_root = tmp_path / "html" / "data" / "reddit-voc"
    data_root.mkdir(parents=True, exist_ok=True)

    datasets: dict[str, dict] = {}
    for key, version in DATASETS.items():
        rel = _manifest_rel(key, version)
        manifest_abs = tmp_path / "html" / rel
        manifest_abs.parent.mkdir(parents=True, exist_ok=True)
        manifest_abs.write_text(
            json.dumps({"dataset_version": version, "files": {}}, sort_keys=True),
            encoding="utf-8",
        )
        datasets[key] = {
            "dataset_version": version,
            "manifest_path": rel,
            "public_manifest_sha256": hashlib.sha256(
                manifest_abs.read_bytes()
            ).hexdigest(),
        }

    release = {
        "schema_version": "reddit_voc_current_release_v2",
        "release_id": "demo_release",
        "generated_at_utc": "2026-10-31T00:00:00Z",
        "datasets": datasets,
    }
    (data_root / "current-release.json").write_text(
        json.dumps(release, indent=2), encoding="utf-8"
    )
    return {
        "public_root": tmp_path / "html",
        "data_root": data_root,
        "release": release,
    }


def stamp_all(site: dict, **kwargs) -> dict:
    defaults = dict(
        run_id="daily_collect_20261031_0700",
        period_end_utc="2026-10-30T23:00:00Z",
        generated_at_utc="2026-10-31T08:00:00Z",
    )
    defaults.update(kwargs)
    return br.collect_dataset_stamps(site["data_root"], site["release"], **defaults)


def test_stamp_manifest_sha_matches_manifest_bytes(tmp_path: Path) -> None:
    """The stamp's hash must be the bytes on disk, not the pointer's claim."""
    site = make_site(tmp_path)
    written = stamp_all(site)

    assert set(written) == set(DATASETS)
    for key, path in written.items():
        stamp = json.loads(path.read_text(encoding="utf-8"))
        binding = site["release"]["datasets"][key]
        manifest_abs = site["public_root"] / binding["manifest_path"]

        assert stamp["schema_version"] == br.STAMP_SCHEMA
        assert stamp["manifest_sha256"] == hashlib.sha256(
            manifest_abs.read_bytes()
        ).hexdigest()
        assert stamp["manifest_sha256"] == binding["public_manifest_sha256"]
        assert stamp["dataset_key"] == key
        assert stamp["dataset_version"] == binding["dataset_version"]


def test_receipt_lists_every_release_dataset(tmp_path: Path) -> None:
    """A receipt that silently omits a dataset cannot prove that dataset."""
    site = make_site(tmp_path)
    stamp_all(site)

    path = br.write_build_receipt(
        site["data_root"],
        "daily_collect_20261031_0700",
        release=site["release"],
        status="success",
        period_end_utc="2026-10-30T23:00:00Z",
        steps=[{"step": "collect", "status": "ok", "traceback": "drop me"}],
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert receipt["schema_version"] == br.RECEIPT_SCHEMA
    assert set(receipt["datasets"]) == set(site["release"]["datasets"])
    for key, entry in receipt["datasets"].items():
        assert entry["manifest_sha256"] == site["release"]["datasets"][key][
            "public_manifest_sha256"
        ]
        assert entry["build_stamp_present"] is True
        assert entry["build_stamp_manifest_sha256"] == entry["manifest_sha256"]

    # Steps keep only step/status/error -- a traceback would bloat the receipt
    # and leak paths.
    assert receipt["steps"] == [{"step": "collect", "status": "ok"}]
    # Internal artifact, not something to serve.
    assert path.parent.name == br.RECEIPTS_DIRNAME


def test_receipt_write_is_immutable_on_conflict(tmp_path: Path) -> None:
    """A run id names one run; rewriting it with new bytes erases the evidence."""
    site = make_site(tmp_path)
    stamp_all(site)
    run_id = "daily_collect_20261031_0700"

    first = br.write_build_receipt(
        site["data_root"], run_id, release=site["release"],
        status="success", period_end_utc="2026-10-30T23:00:00Z",
    )
    before = first.read_bytes()

    # Identical rewrite is a no-op, not a collision: a retried identical run.
    again = br.write_build_receipt(
        site["data_root"], run_id, release=site["release"],
        status="success", period_end_utc="2026-10-30T23:00:00Z",
    )
    assert again.read_bytes() == before

    # Different bytes for the same id must raise and leave the original alone.
    with pytest.raises(br.BuildReceiptCollision) as excinfo:
        br.write_build_receipt(
            site["data_root"], run_id, release=site["release"],
            status="failed", period_end_utc="2026-10-30T23:00:00Z",
        )
    assert "build_receipt_collision" in str(excinfo.value)
    assert first.read_bytes() == before


def test_run_id_must_match_client_safe_pattern(tmp_path: Path) -> None:
    """The run id reaches a filename and a URL-visible field."""
    site = make_site(tmp_path)

    for bad in ("Daily Collect", "", "daily/collect", "-leading", "a" * 200, "有中文"):
        with pytest.raises(ValueError):
            br.write_build_receipt(
                site["data_root"], bad, release=site["release"],
                status="success", period_end_utc=None,
            )

    ok = br.write_build_receipt(
        site["data_root"], "daily_collect_20261029_190142_manual",
        release=site["release"], status="success", period_end_utc=None,
    )
    assert ok.exists()


def test_frozen_dataset_stamp_allows_null_generated_at(tmp_path: Path) -> None:
    """personas/insights are built out of band; null time is honest, silence is not."""
    site = make_site(tmp_path)
    written = stamp_all(site)

    frozen = {"personas", "insights", "casebook"}
    for key in frozen:
        stamp = json.loads(written[key].read_text(encoding="utf-8"))
        assert stamp["build_basis"] == "external_manual_build"
        assert stamp["generated_at_utc"] is None
        # ...and it must say WHY, or a reader cannot tell unknown from forgotten.
        assert stamp["source_unavailable_reason"]

    for key in {"base", "quarter_insights", "brand_health", "reports"}:
        stamp = json.loads(written[key].read_text(encoding="utf-8"))
        assert stamp["build_basis"] == "pipeline"
        assert stamp["generated_at_utc"] == "2026-10-31T08:00:00Z"
        assert "source_unavailable_reason" not in stamp


def test_stamp_refuses_when_pointer_and_tree_disagree(tmp_path: Path) -> None:
    """A stamp must never launder a disagreement into a clean record."""
    site = make_site(tmp_path)
    # Change the manifest bytes without updating the binding.
    binding = site["release"]["datasets"]["base"]
    manifest_abs = site["public_root"] / binding["manifest_path"]
    manifest_abs.write_bytes(manifest_abs.read_bytes() + b"\n")

    with pytest.raises(br.BuildReceiptError) as excinfo:
        br.write_dataset_stamp(
            site["data_root"], "base", binding,
            run_id="daily_collect_20261031_0700",
            build_basis="pipeline",
            period_end_utc="2026-10-30T23:00:00Z",
            generated_at_utc="2026-10-31T08:00:00Z",
        )
    assert "manifest_sha_mismatch" in str(excinfo.value)
    # And nothing was written.
    assert not (manifest_abs.parent / "build.json").exists()


def test_stamp_refuses_null_timestamp_without_a_reason(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    with pytest.raises(br.BuildReceiptError) as excinfo:
        br.write_dataset_stamp(
            site["data_root"], "personas", site["release"]["datasets"]["personas"],
            run_id="daily_collect_20261031_0700",
            build_basis="external_manual_build",
            period_end_utc=None,
            generated_at_utc=None,
        )
    assert "generated_at_missing_without_reason" in str(excinfo.value)


def test_stamp_rejects_unknown_build_basis(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    with pytest.raises(ValueError):
        br.write_dataset_stamp(
            site["data_root"], "base", site["release"]["datasets"]["base"],
            run_id="daily_collect_20261031_0700",
            build_basis="made_up",
            period_end_utc=None,
        )
