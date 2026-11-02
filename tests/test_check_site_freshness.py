"""Can the served site prove it contains this morning's data?

On 2026-10-31 `data/reddit-voc` became a symlink whose target was unreachable
from the nginx container. Every `/data/` request 404'd and
`curl https://report.luteos.com/` still returned 200 from the SPA fallback.
Nothing contradicted that and nothing alerted; it was found by hand.

The monitor answers three separate questions from three separate artifacts:
pointer freshness, per-dataset self-proof (build.json), and agreement with the
run receipt. These tests make sure no one of them can answer for another.

Times are fixed by constructor (`now_utc` / `--now`), never by wall clock, so a
failing assertion names a cadence bug rather than a slow test run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_receipt as br  # noqa: E402
import check_site_freshness as mon  # noqa: E402

# 2026-10-31T12:00Z -> latest closed Shanghai 07:00 boundary is 2026-10-30T23:00Z.
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
CURRENT_PERIOD = "2026-10-30T23:00:00Z"
STALE_PERIOD = "2026-10-29T23:00:00Z"
RUN_ID = "daily_collect_20261031_0700"

DATASETS = {
    "base": "reddit_voc_site_snapshot_demo_v1",
    "quarter_insights": "quarter_insights_demo_v1",
    "brand_health": "brand_health_demo_v1",
    "reports": "reports_demo_v1",
    "personas": "personas_demo_v1",
    "insights": "insights_demo_v1",
    "casebook": "casebook_demo_v1",
}
MANIFEST_TAIL = {"reports": "public/manifest.json"}


def _manifest_rel(key: str, version: str) -> str:
    return f"data/reddit-voc/{version}/{MANIFEST_TAIL.get(key, 'manifest.json')}"


def make_site(tmp_path: Path, *, data_as_of: str = CURRENT_PERIOD,
              freshness_status: str = "full", with_stamps: bool = True,
              with_receipt: bool = True) -> dict:
    public_root = tmp_path / "html"
    data_root = public_root / "data" / "reddit-voc"
    data_root.mkdir(parents=True, exist_ok=True)

    datasets: dict[str, dict] = {}
    for key, version in DATASETS.items():
        manifest_abs = public_root / _manifest_rel(key, version)
        manifest_abs.parent.mkdir(parents=True, exist_ok=True)
        manifest_abs.write_text(
            json.dumps({"dataset_version": version, "files": {}}, sort_keys=True),
            encoding="utf-8",
        )
        import hashlib

        datasets[key] = {
            "dataset_version": version,
            "manifest_path": _manifest_rel(key, version),
            "public_manifest_sha256": hashlib.sha256(manifest_abs.read_bytes()).hexdigest(),
        }

    release = {
        "schema_version": mon.POINTER_SCHEMA,
        "release_id": "demo_release",
        "generated_at_utc": "2026-10-31T09:00:00Z",
        "freshness": {
            "status": freshness_status,
            "timezone": "Asia/Shanghai",
            "data_as_of_utc": data_as_of,
            "collector_run_id": RUN_ID,
        },
        "datasets": datasets,
    }
    (data_root / "current-release.json").write_text(json.dumps(release, indent=2), encoding="utf-8")

    if with_stamps:
        br.collect_dataset_stamps(
            data_root, release,
            run_id=RUN_ID,
            period_end_utc=CURRENT_PERIOD,
            generated_at_utc="2026-10-31T09:00:00Z",
        )
    if with_receipt:
        br.write_build_receipt(
            data_root, RUN_ID,
            release=release, status="success", period_end_utc=CURRENT_PERIOD,
        )

    return {"public_root": public_root, "data_root": data_root, "release": release}


def test_missing_build_receipt_after_deadline_is_stalled(tmp_path: Path) -> None:
    """No run receipt and a pointer older than the deadline: nobody can explain it."""
    site = make_site(tmp_path, data_as_of=STALE_PERIOD, with_receipt=False)
    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert doc["state"] == "stalled", doc["state"]
    assert "build_receipt_missing" in doc["failures"]
    assert doc["healthy"] is False


def test_fresh_release_with_matching_receipt_is_fresh(tmp_path: Path) -> None:
    """The happy path: pointer, stamps and receipt all agree on one run."""
    site = make_site(tmp_path)
    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert doc["state"] == "fresh", (doc["state"], doc["failures"])
    assert doc["failures"] == []
    assert doc["healthy"] is True
    assert doc["data_as_of_utc"] == CURRENT_PERIOD
    assert doc["run_id"] == RUN_ID
    # Every dataset proved itself.
    assert all(v["ok"] for v in doc["datasets"].values()), doc["datasets"]


def test_missing_build_stamp_is_failed_not_fresh(tmp_path: Path) -> None:
    """A dataset with no stamp cannot prove its own provenance."""
    site = make_site(tmp_path)
    (site["data_root"] / DATASETS["brand_health"] / "build.json").unlink()

    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert doc["state"] == "failed", doc["state"]
    assert "build_stamp_missing:brand_health" in doc["failures"]
    assert doc["healthy"] is False


def test_manifest_sha_mismatch_is_failed_not_fresh(tmp_path: Path) -> None:
    """Change the manifest bytes: the binding no longer describes what is served."""
    site = make_site(tmp_path)
    manifest = site["data_root"] / DATASETS["base"] / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")

    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert doc["state"] == "failed", doc["state"]
    # Both the binding comparison and the stamp comparison must notice.
    assert "release_manifest_sha_mismatch:base" in doc["failures"]
    assert "build_stamp_manifest_sha_mismatch:base" in doc["failures"]


def test_partial_build_status_is_not_fresh(tmp_path: Path) -> None:
    """`partial` means the window is current but the run did not fully succeed."""
    site = make_site(tmp_path, freshness_status="partial")
    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert doc["state"] == "partial"
    assert doc["state"] != "fresh"
    # Still publishable: partial is a warning, not a breach.
    assert doc["healthy"] is True


def test_feishu_card_header_is_red_for_stalled(tmp_path: Path) -> None:
    """A stalled site must not render as a healthy green card."""
    site = make_site(tmp_path, data_as_of=STALE_PERIOD, with_receipt=False)

    stalled = mon.observe_site(site["public_root"], now_utc=NOW)
    assert mon.build_alert_card(stalled)["header"]["template"] == "red"

    fresh = mon.observe_site(make_site(tmp_path / "ok")["public_root"], now_utc=NOW)
    assert mon.build_alert_card(fresh, heartbeat=True)["header"]["template"] == "green"


def test_alert_is_deduped_per_state_transition(tmp_path: Path) -> None:
    """A monitor that alerts every run gets muted; muted equals absent."""
    site = make_site(tmp_path, data_as_of=STALE_PERIOD, with_receipt=False)
    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    state: dict = {}
    first, reason = mon.should_notify(doc, state, now_utc=NOW, heartbeat=False)
    assert first is True and reason == "state_changed"

    # Same state and same failure codes: silence.
    state = {"last_state": doc["state"], "last_failure_codes": doc["failures"]}
    again, _ = mon.should_notify(doc, state, now_utc=NOW, heartbeat=False)
    assert again is False

    # A different state speaks immediately.
    changed = dict(doc, state="fresh")
    moved, reason = mon.should_notify(changed, state, now_utc=NOW, heartbeat=False)
    assert moved is True and reason == "state_changed"


def test_failure_code_change_speaks_with_a_stable_state(tmp_path: Path) -> None:
    """`failed A -> failed B` is a new incident, not a duplicate."""
    doc = {
        "state": "failed",
        "failures": ["build_receipt_missing"],
        "healthy": False,
    }
    state = {
        "last_state": "failed",
        "last_failure_codes": ["release_manifest_sha_mismatch:base"],
    }
    send, reason = mon.should_notify(doc, state, now_utc=NOW, heartbeat=False)
    assert send is True
    assert reason == "failure_codes_changed"

    same = {
        "last_state": "failed",
        "last_failure_codes": ["build_receipt_missing"],
    }
    send, reason = mon.should_notify(doc, same, now_utc=NOW, heartbeat=False)
    assert send is False
    assert reason == "unchanged"


def test_heartbeat_is_sent_once_per_shanghai_day(tmp_path: Path) -> None:
    """A green heartbeat proves the monitor is alive, at most once a day."""
    site = make_site(tmp_path)
    doc = mon.observe_site(site["public_root"], now_utc=NOW)
    state = {"last_state": doc["state"], "last_failure_codes": doc["failures"]}

    # First heartbeat today: send.
    send, reason = mon.should_notify(doc, state, now_utc=NOW, heartbeat=True)
    assert send is True and reason == "heartbeat"

    # Second call the same Shanghai day: quiet.
    state = {
        "last_state": doc["state"],
        "last_failure_codes": doc["failures"],
        "last_heartbeat_date": "2026-10-31",
    }
    same_day = NOW.replace(hour=15)  # still 2026-10-31 in Shanghai
    send, _ = mon.should_notify(doc, state, now_utc=same_day, heartbeat=True)
    assert send is False

    # Next Shanghai day: send again.
    next_day = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    send, reason = mon.should_notify(doc, state, now_utc=next_day, heartbeat=True)
    assert send is True and reason == "heartbeat"


def test_unreadable_pointer_is_unevaluable_not_healthy(tmp_path: Path) -> None:
    """A missing pointer must never read as 'all good'."""
    public_root = tmp_path / "html"
    (public_root / "data" / "reddit-voc").mkdir(parents=True)

    with pytest.raises(mon.FreshnessError) as excinfo:
        mon.observe_site(public_root, now_utc=NOW)
    assert "pointer_missing_or_unreadable" in str(excinfo.value)


def test_wrong_release_id_in_receipt_is_a_failure(tmp_path: Path) -> None:
    """A receipt for a different release cannot certify this one."""
    site = make_site(tmp_path)
    receipts_dir = site["data_root"] / br.RECEIPTS_DIRNAME
    path = receipts_dir / f"{RUN_ID}.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["release_id"] = "some_other_release"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert "receipt_release_mismatch" in doc["failures"]
    assert doc["healthy"] is False


def test_stamp_from_a_different_run_is_a_failure(tmp_path: Path) -> None:
    """Mixed generations: a dataset stamped by another run is the 10-29 incident."""
    site = make_site(tmp_path)
    stamp_path = site["data_root"] / DATASETS["reports"] / "public" / "build.json"
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    stamp["run_id"] = "daily_collect_20261030_0700"
    stamp_path.write_text(json.dumps(stamp), encoding="utf-8")

    doc = mon.observe_site(site["public_root"], now_utc=NOW)

    assert "build_stamp_run_mismatch:reports" in doc["failures"]
    assert doc["healthy"] is False
