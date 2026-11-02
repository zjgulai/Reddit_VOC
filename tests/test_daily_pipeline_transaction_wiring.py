"""L6-T08: the pipeline must write a private generation, then publish it once.

Before this wiring, every data write in a daily run landed in
`public_root/data/reddit-voc` directly. On 2026-10-29 the run merged
posts-public.json, rewrote the base manifest, failed in recompute, and left the
site serving new base content with old derivatives. The pointer gate was
correct; there was simply no boundary between "wrote" and "published".

These tests pin the contract for the transaction wiring:
  * merge and recompute write only inside the staged generation;
  * the live pointer is replaced exactly once per successful run;
  * every published binding SHA matches the bytes actually committed;
  * a failure at any write point leaves the live tree byte-identical and
    records status=failed;
  * `PIPELINE_GENERATION_MODE=off` is byte-for-byte the old behaviour, so the
    flag can be shipped before it is switched on;
  * agent-studio is written into the generation and AGENT_PUBLIC_ROOT is not
    read in symlink mode.

The fixture builds a real migrated SQLite store and a real symlinked site. Fakes
that close over the fixture paths would hide exactly the joins these tests exist
to catch.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import daily_release_transaction as tx  # noqa: E402
import run_daily_t1_pipeline as pipeline  # noqa: E402
from reddit_voc.models import RedditThread  # noqa: E402
from reddit_voc.storage import VocStore  # noqa: E402

DATASET = "reddit_voc_site_snapshot_20260723_v3_daily_001"
QI_VERSION = "quarter_insights_demo_v1"
REPORTS_VERSION = "reports_demo_v1"
PERSONAS_VERSION = "personas_demo_v1"
CASEBOOK_VERSION = "casebook_demo_v1"
BRAND_HEALTH_VERSION = "brand_health_demo_v1"
INSIGHTS_VERSION = "insights_demo_v1"


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _json_bytes(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _binding(version: str, manifest_rel: str, *, sha: str = "0" * 64) -> dict:
    return {
        "dataset_version": version,
        "manifest_path": manifest_rel,
        "public_manifest_sha256": sha,
        "lineage_manifest_sha256": sha,
    }


def make_release_document() -> dict:
    """One binding per dataset the pipeline and recompute touch.

    Every path is site-root-relative, exactly as production writes it, so any
    surviving `public_root / manifest_path` join shows up as a write into the
    live tree instead of a test that merely passes.
    """
    return {
        "release_id": "demo_release_0001",
        "generated_at_utc": "2026-10-29T00:00:00Z",
        "freshness": {"status": "stale", "timezone": "Asia/Shanghai"},
        "datasets": {
            "base": _binding(
                DATASET, f"data/reddit-voc/{DATASET}/manifest-public.json"
            ),
            "quarter_insights": _binding(
                QI_VERSION, f"data/reddit-voc/{QI_VERSION}/manifest.json"
            ),
            "reports": _binding(
                REPORTS_VERSION, f"data/reddit-voc/{REPORTS_VERSION}/public/manifest.json"
            ),
            "personas": _binding(
                PERSONAS_VERSION, f"data/reddit-voc/{PERSONAS_VERSION}/manifest.json"
            ),
            "casebook": _binding(
                CASEBOOK_VERSION, f"data/reddit-voc/{CASEBOOK_VERSION}/manifest.json"
            ),
            "brand_health": _binding(
                BRAND_HEALTH_VERSION, f"data/reddit-voc/{BRAND_HEALTH_VERSION}/manifest.json"
            ),
            "insights": _binding(
                INSIGHTS_VERSION, f"data/reddit-voc/{INSIGHTS_VERSION}/manifest.json"
            ),
        },
    }


def make_site(tmp_path: Path) -> dict:
    """A site shaped like production after adoption: data/reddit-voc is a symlink."""
    public_root = tmp_path / "html"
    generations = public_root / "data" / tx.GENERATIONS_DIRNAME
    live_gen = generations / "gen-000" / tx.LIVE_DIRNAME
    live_gen.mkdir(parents=True, exist_ok=True)

    base_dir = live_gen / DATASET
    _write(base_dir / "posts-public.json", b"[]\n")
    _write(base_dir / "comments-public.json", b"[]\n")
    _write(
        base_dir / "manifest-public.json",
        _json_bytes({
            "dataset_version": DATASET,
            "canonical_counts": {"posts": 0, "linked_comments": 0},
            "projection_counts": {"public_posts": 0, "public_linked_comments": 0},
            "files": {
                "posts-public.json": {"sha256": "", "bytes": 0},
                "comments-public.json": {"sha256": "", "bytes": 0},
            },
        }),
    )
    _write(base_dir / "tag-dictionary-public.json", _json_bytes({"rules": []}))

    # A manifest per remaining binding, plus the directory its files live in.
    for version in (QI_VERSION, PERSONAS_VERSION, CASEBOOK_VERSION,
                    BRAND_HEALTH_VERSION, INSIGHTS_VERSION):
        _write(live_gen / version / "manifest.json", _json_bytes({
            "dataset_version": version,
            "files": {},
        }))
    _write(live_gen / REPORTS_VERSION / "public" / "manifest.json", _json_bytes({
        "dataset_version": REPORTS_VERSION,
        "files": {},
        "lineage_manifest_sha256": "0" * 64,
    }))
    _write(live_gen / "lineage" / "product-entity-ledger.json", _json_bytes({"entities": []}))

    _write(live_gen / tx.RELEASE_FILENAME, _json_bytes(make_release_document()))

    link = public_root / "data" / tx.LIVE_DIRNAME
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(live_gen, link)

    return {
        "public_root": public_root,
        "generations": generations,
        "live_gen": live_gen,
        "link": link,
    }


def make_store(path: Path) -> VocStore:
    """A real migrated store holding one thread inside the merge window."""
    store = VocStore(path)
    store.migrate()
    store.upsert_thread(
        RedditThread(
            post_id="p-live-1",
            run_id="daily_collect_test_0700",
            raw_capture_id="cap-1",
            subreddit="r/ExclusivelyPumping",
            title="Momcozy M5 leaking after three weeks",
            source_url="https://www.reddit.com/r/ExclusivelyPumping/comments/p-live-1/",
            created_at_utc=datetime(2026, 10, 28, 4, 0, tzinfo=timezone.utc),
            selftext="Every time I lean forward milk leaks out of the top seal of my Momcozy.",
            matched_keywords=["momcozy"],
            media_urls=[],
        )
    )
    return store


@pytest.fixture()
def site(tmp_path: Path) -> dict:
    built = make_site(tmp_path)
    built["store"] = tmp_path / "store" / "daily.sqlite3"
    built["store"].parent.mkdir(parents=True, exist_ok=True)
    make_store(built["store"]).migrate()
    built["output_dir"] = tmp_path / "outputs"
    built["output_dir"].mkdir(parents=True, exist_ok=True)
    built["sentinel"] = tmp_path / "agent-public-sentinel"
    return built


def _set_mode(monkeypatch, mode: str | None) -> None:
    if mode is None:
        monkeypatch.delenv(pipeline.PIPELINE_GENERATION_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(pipeline.PIPELINE_GENERATION_MODE_ENV, mode)


def _quiet_feishu(monkeypatch) -> None:
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_REPORT_CHAT_ID", raising=False)


def _run(site: dict, *, skip_feishu: bool = True) -> dict:
    return pipeline.run_pipeline(
        store_path=site["store"],
        public_root=site["public_root"],
        output_dir=site["output_dir"],
        skip_feishu=skip_feishu,
    )


def _stub_agents(monkeypatch) -> None:
    """Step 2 has its own suite; here it only has to be a successful receipt."""
    monkeypatch.setattr(
        pipeline, "step2_agents",
        lambda store_path, run_id, out_dir, *, data_root=None: {
            "step": "agents", "status": "ok", "run_id": run_id, "data_root": str(data_root),
        },
    )


def _stub_collect(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline, "step1_collect",
        lambda store_path, run_id: {"step": "collect", "status": "ok", "run_id": run_id},
    )


# --------------------------------------------------------------------- tests


def test_merge_and_recompute_write_only_into_generation(site, monkeypatch) -> None:
    """The decisive test: after merge, live bytes are untouched and the staged tree has the post."""
    _stub_collect(monkeypatch)
    _stub_agents(monkeypatch)
    _set_mode(monkeypatch, "symlink")

    live_digest = tx.tree_digest(site["live_gen"])
    link_before = os.readlink(site["link"])

    # Recompute is exercised by its own suite; record what root it was handed and
    # assert the generation is still the link target while it runs.
    seen: dict = {}

    def fake_recompute(public_root, *, data_root=None, dry_run=False):
        seen["data_root"] = data_root
        seen["link_while_running"] = os.readlink(site["link"])
        assert data_root is not None, "recompute must be told which tree to write"
        assert data_root != site["public_root"] / "data" / tx.LIVE_DIRNAME
        (Path(data_root) / "recompute-sentinel.json").write_text("{}", encoding="utf-8")
        return {
            "engine": "fake", "step": "recompute_derivatives", "status": "ok",
            "outputs": [], "reports_lineage_manifest_sha256": "0" * 64,
        }

    monkeypatch.setattr(
        "recompute_derivatives.run_recompute", fake_recompute, raising=False
    )

    receipt = _run(site)

    assert receipt["status"] == "success", receipt
    assert seen["data_root"] is not None
    assert Path(seen["data_root"]).name == tx.LIVE_DIRNAME
    assert seen["link_while_running"] == link_before, "live link moved before commit"

    committed = Path(receipt["release_transaction"]["root"])
    merged = json.loads((committed / DATASET / "posts-public.json").read_text(encoding="utf-8"))
    assert [p["post_id"] for p in merged] == ["p-live-1"]
    assert (committed / "recompute-sentinel.json").exists()
    # L5-T04: the published generation carries this run's evidence.
    assert (committed / "build-receipts" / f"{receipt['run_id']}.json").is_file()

    # Live generation is exactly as it was before the run.
    assert tx.tree_digest(site["live_gen"]) == live_digest


def test_pointer_written_exactly_once_per_run(site, monkeypatch) -> None:
    """Two live replaces would mean a half-published run; the contract is one."""
    _stub_collect(monkeypatch)
    _stub_agents(monkeypatch)
    _set_mode(monkeypatch, "symlink")

    monkeypatch.setattr(
        "recompute_derivatives.run_recompute",
        lambda public_root, *, data_root=None, dry_run=False: {
            "engine": "fake", "step": "recompute_derivatives", "status": "ok",
            "outputs": [], "reports_lineage_manifest_sha256": "0" * 64,
        },
        raising=False,
    )

    link_abs = os.path.abspath(site["link"])
    real_replace = os.replace
    replaced: list[str] = []

    def spy(src, dst, *args, **kwargs):
        # Compare lexically: resolving would follow the old link and miss the swap.
        if os.path.abspath(dst) == link_abs:
            replaced.append(str(dst))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)

    receipt = _run(site)

    assert receipt["status"] == "success", receipt
    assert len(replaced) == 1, f"live pointer replaced {len(replaced)} times"

    # The link now points at the committed generation, not the seed.
    assert site["link"].resolve() == Path(
        receipt["release_transaction"]["root"]
    ).resolve()

    # Every binding SHA in the published pointer is the hash of the bytes served.
    served = Path(receipt["release_transaction"]["root"])
    release = json.loads((served / tx.RELEASE_FILENAME).read_text(encoding="utf-8"))
    import hashlib

    for key, binding in release["datasets"].items():
        manifest_rel = binding["manifest_path"].replace("data/reddit-voc/", "", 1)
        manifest_abs = served / manifest_rel
        if not manifest_abs.exists():
            continue
        assert binding["public_manifest_sha256"] == hashlib.sha256(
            manifest_abs.read_bytes()
        ).hexdigest(), f"{key} binding SHA does not match its bytes"


def test_failure_at_recompute_leaves_live_tree_byte_identical(site, monkeypatch) -> None:
    """A second-write failure must not publish, and must be recorded as failed."""
    _stub_collect(monkeypatch)
    _stub_agents(monkeypatch)
    _set_mode(monkeypatch, "symlink")

    live_digest = tx.tree_digest(site["live_gen"])
    link_before = os.readlink(site["link"])
    pointer_before = (site["link"] / tx.RELEASE_FILENAME).read_bytes()

    def exploding_recompute(public_root, *, data_root=None, dry_run=False):
        target = Path(data_root)
        (target / "half-written-1.json").write_text("{}", encoding="utf-8")
        (target / "half-written-2.json").write_text("{}", encoding="utf-8")
        raise RuntimeError("recompute died on its second write")

    monkeypatch.setattr(
        "recompute_derivatives.run_recompute", exploding_recompute, raising=False
    )

    link_abs = os.path.abspath(site["link"])
    real_replace = os.replace
    replaced: list[str] = []

    def spy(src, dst, *args, **kwargs):
        if os.path.abspath(dst) == link_abs:
            replaced.append(str(dst))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)

    receipt = _run(site)

    assert receipt["status"] == "failed", receipt
    assert replaced == [], "a failed run must not touch the live pointer"
    assert tx.tree_digest(site["live_gen"]) == live_digest
    assert os.readlink(site["link"]) == link_before
    assert (site["link"] / tx.RELEASE_FILENAME).read_bytes() == pointer_before

    failed = [e for e in receipt["errors"] if e.get("step") == "recompute_derivatives"]
    assert failed, receipt["errors"]
    commit = receipt["release_transaction"]["commit"]
    assert commit["status"] == "blocked_by_prerequisites"
    # L5-T04: a failed run still leaves evidence in its private generation.
    private = Path(receipt["release_transaction"]["root"])
    run_receipt = private / "build-receipts" / f"{receipt['run_id']}.json"
    assert run_receipt.is_file(), receipt
    assert json.loads(run_receipt.read_text(encoding="utf-8"))["status"] == "failed"


def test_generation_mode_off_keeps_legacy_paths(site, monkeypatch) -> None:
    """The flag ships before it is enabled: unset and 'off' must change nothing."""
    for mode in (None, "off"):
        _set_mode(monkeypatch, mode)
        _stub_collect(monkeypatch)

        roots: list = []

        def record_root(store_path, run_id, out_dir, *, data_root=None, _roots=roots):
            _roots.append(data_root)
            return {"step": "agents", "status": "ok"}

        monkeypatch.setattr(pipeline, "step2_agents", record_root)
        monkeypatch.setattr(
            "recompute_derivatives.run_recompute",
            lambda public_root, *, data_root=None, dry_run=False: (
                roots.append(data_root) or {
                    "engine": "fake", "step": "recompute_derivatives", "status": "ok",
                    "outputs": [], "reports_lineage_manifest_sha256": "0" * 64,
                }
            ),
            raising=False,
        )

        generations_before = sorted(p.name for p in site["generations"].iterdir())
        receipt = _run(site)

        assert all(root is None for root in roots), f"off mode passed a data_root: {roots}"
        assert "release_transaction" not in receipt
        assert not receipt["status"].startswith("failed")
        assert "commit_generation" not in [s.get("step") for s in receipt["steps"]]
        assert sorted(p.name for p in site["generations"].iterdir()) == generations_before

        # Legacy in-place write happened, inside the (unchanged) live generation.
        live_release = json.loads(
            (site["live_gen"] / tx.RELEASE_FILENAME).read_text(encoding="utf-8")
        )
        assert live_release["freshness"]["status"] == "partial"


def test_agent_studio_written_into_generation(site, monkeypatch) -> None:
    """agent-studio must land in the generation; AGENT_PUBLIC_ROOT must be ignored."""
    sentinel = str(site["sentinel"])
    monkeypatch.setenv("AGENT_PUBLIC_ROOT", sentinel)

    out_dir = site["output_dir"]
    for name in ("content-ideas", "rnd-tickets", "competitor-radar"):
        (out_dir / f"daily_collect_test_0700-daily-{name}.json").write_text("[]", encoding="utf-8")

    generation_root = site["live_gen"]  # stand-in for a staged generation root

    published = pipeline._publish_agent_artifacts(
        "daily_collect_test_0700", out_dir, data_root=generation_root
    )

    assert set(published) == {"content_ideas", "rnd_tickets", "competitor_radar"}
    for name in ("latest-content-ideas.json", "latest-rnd-tickets.json",
                 "latest-competitor-radar.json"):
        assert (generation_root / "agent-studio" / name).exists()
    assert not Path(sentinel).exists(), "AGENT_PUBLIC_ROOT was read in symlink mode"

    # ...and the legacy branch still honours the env var when no data_root is given.
    published = pipeline._publish_agent_artifacts("daily_collect_test_0700", out_dir)
    assert published, published
    assert (Path(sentinel) / "data" / "reddit-voc" / "agent-studio"
            / "latest-content-ideas.json").exists()


def test_committed_run_collects_old_generations(site, monkeypatch) -> None:
    """Every run adds a full tree copy; nobody runs gc by hand.

    Production's tree is 645M. Without cleanup after a successful publish the
    disk fills in about two months, and the failure lands in the middle of a run
    rather than at a convenient moment.
    """
    _stub_collect(monkeypatch)
    _stub_agents(monkeypatch)
    _set_mode(monkeypatch, "symlink")
    monkeypatch.setattr(
        "recompute_derivatives.run_recompute",
        lambda public_root, *, data_root=None, dry_run=False: {
            "engine": "fake", "step": "recompute_derivatives", "status": "ok",
            "outputs": [], "reports_lineage_manifest_sha256": "0" * 64,
        },
        raising=False,
    )

    # Seed extra generations so gc has something to remove.
    for name in ("gen-old-1", "gen-old-2"):
        (site["generations"] / name / tx.LIVE_DIRNAME).mkdir(parents=True)
        (site["generations"] / name / tx.LIVE_DIRNAME / "stale.json").write_text("{}", encoding="utf-8")

    receipt = _run(site)

    assert receipt["status"] == "success", receipt
    steps = {s.get("step"): s for s in receipt["steps"]}
    assert "gc_generations" in steps, [s.get("step") for s in receipt["steps"]]
    assert steps["gc_generations"]["status"] == "ok"

    # keep=2 retains the live generation and the one before it, nothing more.
    assert len(list(site["generations"].iterdir())) <= 2
    # And what is served is still the generation this run committed.
    assert site["link"].resolve() == Path(receipt["release_transaction"]["root"]).resolve()


def test_failed_run_keeps_its_generation_for_diagnosis(site, monkeypatch) -> None:
    """A failed run's tree is evidence, not garbage: gc must not touch it."""
    _stub_collect(monkeypatch)
    _stub_agents(monkeypatch)
    _set_mode(monkeypatch, "symlink")
    monkeypatch.setattr(
        "recompute_derivatives.run_recompute",
        lambda public_root, *, data_root=None, dry_run=False: (_ for _ in ()).throw(
            RuntimeError("recompute died")
        ),
        raising=False,
    )

    receipt = _run(site)
    assert receipt["status"] == "failed", receipt

    steps = {s.get("step"): s for s in receipt["steps"]}
    assert "gc_generations" not in steps, "a failed run must keep its generation"
    link_before = tx.tree_digest(site["live_gen"])
    assert link_before, "the seed generation is untouched and still readable"
