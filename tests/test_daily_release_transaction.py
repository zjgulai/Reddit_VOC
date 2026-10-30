"""A failed publish must leave the live tree byte-identical.

On 2026-10-29 the 07:05 run merged into the live dataset tree and then died in
recompute. The pointer was correctly blocked, but `posts-public.json` had already
been overwritten, so the site served a new base snapshot with twelve-hour-old
reports and brand-health. There was no generation boundary, so nothing could tell
the two apart.

These tests pin the contract that makes that impossible: staging never touches the
live tree, and publishing is a single atomic symlink replace.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import daily_release_transaction as tx  # noqa: E402


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def make_live_site(tmp_path: Path) -> dict:
    """A site in the post-migration shape: `data/reddit-voc` is a symlink.

    The one-time adoption of a real directory into a symlink is deliberately NOT
    something `commit()` will do (see test_commit_refuses_to_replace_real_directory),
    so the fixture starts from the shape the transaction maintains.
    """
    public_root = tmp_path / "html"
    generations = public_root / "data" / tx.GENERATIONS_DIRNAME
    live_gen = generations / "gen-000" / tx.LIVE_DIRNAME
    live_gen.mkdir(parents=True, exist_ok=True)

    dataset = live_gen / "reddit_voc_site_snapshot_demo_v1"
    _write(dataset / "posts-public.json", b'[{"post_id": "p1"}]\n')
    _write(dataset / "comments-public.json", b"[]\n")
    _write(dataset / "manifest-public.json", b'{"dataset_version": "demo_v1"}\n')
    _write(
        live_gen / tx.RELEASE_FILENAME,
        json.dumps(
            {
                "release_id": "demo_release",
                "generated_at_utc": "2026-10-29T00:00:00Z",
                "datasets": {
                    "base": {
                        "dataset_version": "reddit_voc_site_snapshot_demo_v1",
                        "manifest_path": "data/reddit-voc/reddit_voc_site_snapshot_demo_v1/manifest-public.json",
                        "public_manifest_sha256": "0" * 64,
                        "lineage_manifest_sha256": "0" * 64,
                    }
                },
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    )

    link = public_root / "data" / tx.LIVE_DIRNAME
    os.symlink(live_gen, link)

    return {
        "public_root": public_root,
        "live_gen": live_gen,
        "link": link,
        "dataset": "reddit_voc_site_snapshot_demo_v1",
    }


def _release_for(site: dict, *, base_version: str | None = None) -> dict:
    return {
        "release_id": "demo_release_next",
        "generated_at_utc": "2026-10-30T00:00:00Z",
        "datasets": {
            "base": {
                "dataset_version": base_version or f"reddit_voc_site_snapshot_demo_v1",
                "manifest_path": "data/reddit-voc/reddit_voc_site_snapshot_demo_v1/manifest-public.json",
                "public_manifest_sha256": "1" * 64,
                "lineage_manifest_sha256": "1" * 64,
            }
        },
    }


def test_commit_switches_symlink_atomically(tmp_path: Path) -> None:
    site = make_live_site(tmp_path)
    before = os.readlink(site["link"])

    generation = tx.begin_generation(site["public_root"], run_id="gen-001")
    generation.stage_write(f"{site['dataset']}/posts-public.json", b'[{"post_id": "p1"}, {"post_id": "p2"}]\n')
    generation.commit(_release_for(site))

    after = os.readlink(site["link"])
    assert after != before, "commit must repoint the live symlink"
    assert Path(after).resolve() == generation.root.resolve()

    # The served content is the staged generation, not a mix of both.
    served = json.loads((site["link"] / site["dataset"] / "posts-public.json").read_text())
    assert len(served) == 2

    # The pointer inside the live tree names the same generation it was written with.
    live_release = json.loads((site["link"] / tx.RELEASE_FILENAME).read_text())
    assert live_release["release_id"] == "demo_release_next"

    # The previous generation is still complete and reachable, so a rollback target exists.
    assert (site["live_gen"] / site["dataset"] / "posts-public.json").exists()
    assert before


def test_failed_build_leaves_live_tree_byte_identical(tmp_path: Path) -> None:
    """Throw after the first staged write and never call commit: nothing moved."""
    site = make_live_site(tmp_path)
    live_before = tx.tree_digest(site["live_gen"])
    link_before = os.readlink(site["link"])

    generation = tx.begin_generation(site["public_root"], run_id="gen-fail")
    generation.stage_write(f"{site['dataset']}/posts-public.json", b'[{"post_id": "CORRUPT"}]\n')
    with pytest.raises(RuntimeError):
        raise RuntimeError("recompute died mid-run")

    assert tx.tree_digest(site["live_gen"]) == live_before
    assert os.readlink(site["link"]) == link_before
    # And what a reader sees is still the old bytes.
    served = json.loads((site["link"] / site["dataset"] / "posts-public.json").read_text())
    assert served == [{"post_id": "p1"}]


def test_stage_write_does_not_inherit_live_inode(tmp_path: Path) -> None:
    """The seed must be a real copy: hardlinks would let staging truncate live data."""
    site = make_live_site(tmp_path)
    live_file = site["live_gen"] / site["dataset"] / "posts-public.json"
    live_inode = os.stat(live_file).st_ino
    live_bytes = live_file.read_bytes()

    generation = tx.begin_generation(site["public_root"], run_id="gen-inode")
    staged_file = generation.root / site["dataset"] / "posts-public.json"

    assert os.stat(staged_file).st_ino != live_inode, "staged file shares an inode with live"
    assert os.stat(staged_file).st_nlink == 1

    # Overwriting the staged file must not disturb the live bytes.
    generation.stage_write(f"{site['dataset']}/posts-public.json", b"[TRUNCATED]\n")
    assert live_file.read_bytes() == live_bytes


def test_commit_refuses_to_replace_real_directory(tmp_path: Path) -> None:
    """Adopting the very first generation is an explicit ops step, not a silent rmtree."""
    public_root = tmp_path / "html"
    live = public_root / "data" / tx.LIVE_DIRNAME
    _write(live / "current-release.json", b'{"release_id": "demo_release"}\n')

    generation = tx.begin_generation(public_root, run_id="gen-adopt")
    generation.stage_write("current-release.json", b'{"release_id": "next"}\n')

    with pytest.raises(tx.ReleaseTransactionError) as excinfo:
        generation.commit({"release_id": "next", "datasets": {}})
    assert "generation_live_root_not_symlink" in str(excinfo.value)

    # Crucially the real directory is intact, not deleted.
    assert live.is_dir() and not live.is_symlink()
    assert (live / "current-release.json").read_bytes() == b'{"release_id": "demo_release"}\n'


def test_commit_rejects_dataset_version_change(tmp_path: Path) -> None:
    """personas/insights are attested out-of-band; a daily swap may not repoint them."""
    site = make_live_site(tmp_path)
    generation = tx.begin_generation(site["public_root"], run_id="gen-version")

    with pytest.raises(tx.ReleaseTransactionError) as excinfo:
        generation.commit(_release_for(site, base_version="reddit_voc_site_snapshot_demo_v2"))
    assert "generation_dataset_version_changed:base" in str(excinfo.value)

    # The refused commit must not have moved the live symlink.
    assert Path(os.readlink(site["link"])).resolve() == site["live_gen"].resolve()


def test_gc_keeps_current_and_previous(tmp_path: Path) -> None:
    site = make_live_site(tmp_path)
    ids = []
    for index in range(1, 4):
        generation = tx.begin_generation(site["public_root"], run_id=f"gen-{index:03d}")
        generation.commit(_release_for(site))
        ids.append(generation.generation_id)

    live_target = Path(os.readlink(site["link"])).resolve()
    live_generation = live_target.parent.name
    removed = tx.gc(site["public_root"], keep=2)

    remaining = [g.name for g in tx.list_generations(site["public_root"])]
    assert "gen-000" in removed, f"oldest must be collected, removed={removed}"
    assert live_generation in remaining, (
        f"gc must never delete the live generation {live_generation}; remaining={remaining}"
    )
    assert "gen-003" in remaining and "gen-002" in remaining
    for name in removed:
        assert name not in remaining


def test_restore_returns_previous_generation(tmp_path: Path) -> None:
    site = make_live_site(tmp_path)
    first = site["live_gen"].resolve()

    generation = tx.begin_generation(site["public_root"], run_id="gen-next")
    generation.stage_write(f"{site['dataset']}/posts-public.json", b'[{"post_id": "NEW"}]\n')
    generation.commit(_release_for(site))
    assert Path(os.readlink(site["link"])).resolve() == generation.root.resolve()

    restored = tx.restore(site["public_root"])
    assert Path(restored).resolve() == first
    assert Path(os.readlink(site["link"])).resolve() == first

    # The generation we rolled back FROM is untouched, so the restore is reversible.
    assert (generation.root / site["dataset"] / "posts-public.json").read_bytes() == b'[{"post_id": "NEW"}]\n'
    served = json.loads((site["link"] / site["dataset"] / "posts-public.json").read_text())
    assert served == [{"post_id": "p1"}]


def test_insufficient_disk_raises(tmp_path: Path) -> None:
    site = make_live_site(tmp_path)
    generation = tx.begin_generation(
        site["public_root"],
        run_id="gen-disk",
        disk_usage=lambda _path: (0, 0, 1),
    )
    with pytest.raises(tx.ReleaseTransactionError) as excinfo:
        generation.commit(_release_for(site))
    assert "generation_insufficient_disk" in str(excinfo.value)


def test_stage_write_rejects_path_escape(tmp_path: Path) -> None:
    site = make_live_site(tmp_path)
    generation = tx.begin_generation(site["public_root"], run_id="gen-escape")
    with pytest.raises(tx.ReleaseTransactionError):
        generation.stage_write("../escaped.json", b"{}")
    with pytest.raises(tx.ReleaseTransactionError):
        generation.stage_write("/etc/passwd", b"{}")
