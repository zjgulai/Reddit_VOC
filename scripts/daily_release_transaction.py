#!/usr/bin/env python3
"""Write a whole release generation off to the side, then swap it in atomically.

Why this exists
---------------
The 2026-10-29 07:05 run collected and merged 73 posts / 291 comments into the live
dataset tree, then died in `recompute_derivatives` on a permission error. The
pointer was correctly blocked, so the pointer still named the July generation --
but `posts-public.json` had already been overwritten in place. For the next twelve
hours the site served a base snapshot from the new run paired with reports,
aggregates and brand-health from the old one. Nothing in the system could tell the
two apart, because there was no generation boundary to compare.

This module supplies that boundary:

    tx = begin_generation(public_root, run_id="daily_collect_20261030_0700")
    tx.stage_write("reddit_voc_site_snapshot_x/posts-public.json", blob)
    tx.stage_write("reddit_voc_site_snapshot_x/manifest-public.json", manifest_blob)
    tx.commit(release)            # single atomic symlink replace
    # on any failure: nothing was published; the live tree is untouched

Layout
------
    public_root/data/reddit-voc                 -> symlink into the live generation
    public_root/data/reddit-voc-generations/<id>/reddit-voc/<full tree>

`data/reddit-voc` stays the public path every consumer already uses, so nginx, the
SPA and the validators need no change; only the directory entry becomes a symlink.

The seed is a real copy, never a hardlink: `write_text`/`open(..., 'w')` truncates
the shared inode, which would corrupt the live generation while "staging".
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping


LIVE_DIRNAME = "reddit-voc"
GENERATIONS_DIRNAME = "reddit-voc-generations"
RELEASE_FILENAME = "current-release.json"

# A generation is a full copy of the tree, so the free space needed to build one is
# roughly the tree size again plus room for the write churn while building it.
DISK_HEADROOM_FACTOR = 2.5


class ReleaseTransactionError(RuntimeError):
    """A generation could not be built, committed, restored or collected."""


@dataclass
class GenerationSeed:
    """What the generation was copied from, and the invariants commit must keep."""

    generation_id: str
    root: Path
    dataset_versions: dict[str, str] = field(default_factory=dict)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fsync_dir(path: Path) -> None:
    """Persist a directory entry. Tolerated on filesystems that refuse it."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError as exc:  # pragma: no cover - platform dependent
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF):
            raise
    finally:
        os.close(fd)


def _tree_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def tree_digest(root: Path) -> str:
    """Content digest of a tree, used by tests and by callers asserting no change.

    Includes relative paths, so a rename shows up as a change even when the bytes
    are identical.
    """
    digest = hashlib.sha256()
    entries: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                payload = path.read_bytes()
            except OSError:
                entries.append((rel, "<unreadable>"))
                continue
            entries.append((rel, hashlib.sha256(payload).hexdigest()))
    for rel, sha in entries:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _read_dataset_versions(release_path: Path) -> dict[str, str]:
    try:
        document = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    datasets = document.get("datasets")
    if not isinstance(datasets, dict):
        return {}
    versions: dict[str, str] = {}
    for key, binding in datasets.items():
        if isinstance(binding, dict) and isinstance(binding.get("dataset_version"), str):
            versions[str(key)] = binding["dataset_version"]
    return versions


class ReleaseGeneration:
    """One staged copy of the release tree, swappable in as a single operation."""

    def __init__(
        self,
        *,
        public_root: Path,
        generation_id: str,
        root: Path,
        live_root: Path,
        generations_root: Path,
        dataset_versions: Mapping[str, str],
        disk_usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
    ) -> None:
        self.public_root = public_root
        self.generation_id = generation_id
        self.root = root
        self.live_root = live_root
        self.generations_root = generations_root
        self.dataset_versions = dict(dataset_versions)
        self._disk_usage = disk_usage
        self._committed = False

    # ------------------------------------------------------------------ staging

    def _resolve_inside(self, relative: str) -> Path:
        """Resolve a dataset-relative path, refusing anything that escapes."""
        if not relative or os.path.isabs(relative) or ".." in Path(relative).parts:
            raise ReleaseTransactionError(f"generation_path_invalid:{relative!r}")
        target = (self.root / relative).resolve()
        root_resolved = self.root.resolve()
        if target != root_resolved and root_resolved not in target.parents:
            raise ReleaseTransactionError(f"generation_path_escapes_root:{relative!r}")
        return target

    def stage_write(self, relative: str, payload: bytes) -> Path:
        """Write one file into the generation: temp + fsync + atomic replace.

        Never writes in place. A crash mid-write leaves the previous staged content
        intact rather than a truncated file, and `os.replace` keeps readers of an
        already-open path from seeing a half-written document.
        """
        target = self._resolve_inside(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.staging-{os.getpid()}")
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        _fsync_dir(target.parent)
        return target

    def stage_json(self, relative: str, document: object) -> Path:
        return self.stage_write(
            relative,
            (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    def read_staged(self, relative: str) -> bytes:
        return self._resolve_inside(relative).read_bytes()

    # -------------------------------------------------------------------- safety

    def _assert_private(self) -> None:
        """The generation must be an independent tree, not a view of the live one.

        Two ways this could silently break the whole idea:
          * the generation root sits *inside* the live root, so staging still
            writes to what is being served;
          * a file is hardlinked to a live file, so truncating it while staging
            mutates the live generation (the reason the seed is a real copy).
        """
        live_resolved = self.live_root.resolve()
        root_resolved = self.root.resolve()
        if root_resolved == live_resolved or live_resolved in root_resolved.parents:
            raise ReleaseTransactionError("generation_root_inside_live_tree")
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    stat = os.lstat(path)
                except OSError as exc:
                    raise ReleaseTransactionError(f"generation_file_unreadable:{path}") from exc
                if stat.st_nlink != 1:
                    raise ReleaseTransactionError(
                        f"generation_file_shared_inode:{path.relative_to(self.root).as_posix()}"
                    )

    def _assert_disk_headroom(self) -> None:
        try:
            required = int(_tree_bytes(self.live_root) * DISK_HEADROOM_FACTOR)
        except OSError:
            required = 0
        try:
            usage = self._disk_usage(self.generations_root)
        except OSError as exc:
            raise ReleaseTransactionError(f"generation_disk_usage_unavailable:{exc}") from exc
        # shutil.disk_usage returns a named tuple with .free; a bare 3-tuple is also
        # accepted so callers can inject a fake without importing shutil.
        free = usage.free if hasattr(usage, "free") else usage[2]
        if free < required:
            raise ReleaseTransactionError(
                f"generation_insufficient_disk:free={free},required={required}"
            )

    # ------------------------------------------------------------------- commit

    def commit(self, release: Mapping[str, object]) -> str:
        """Publish this generation by replacing the `data/reddit-voc` directory entry.

        Order matters and is the whole point:
          1. the complete release document is written *inside* the generation and
             fsynced, so a reader can never see new content with an old pointer;
          2. the pointer (symlink) is replaced with a single `os.replace`, which is
             atomic on POSIX. Either the old generation or the new one is live; there
             is no window where the path is missing or half-updated.
        """
        if self.live_root.exists() and not self.live_root.is_symlink():
            raise ReleaseTransactionError("generation_live_root_not_symlink")

        self._assert_disk_headroom()
        self._assert_version_stability(release)

        self.stage_json(RELEASE_FILENAME, release)
        _fsync_dir(self.root)
        self._assert_private()

        tmp_link = self.live_root.with_name(f".{LIVE_DIRNAME}.linking-{os.getpid()}")
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        os.symlink(self.root, tmp_link)
        os.replace(tmp_link, self.live_root)
        _fsync_dir(self.live_root.parent)

        self._committed = True
        self.dataset_versions = _read_dataset_versions(self.root / RELEASE_FILENAME)
        return str(self.root)

    def _assert_version_stability(self, release: Mapping[str, object]) -> None:
        """A daily run may rewrite content, never rename a frozen dataset.

        `personas` and `insights` are built by out-of-band attested chains; a daily
        swap that also moved their `dataset_version` would silently repoint the
        frontend at a directory the pipeline never produced.
        """
        datasets = release.get("datasets")
        if not isinstance(datasets, Mapping):
            return
        for key, binding in datasets.items():
            if not isinstance(binding, Mapping):
                continue
            version = binding.get("dataset_version")
            previous = self.dataset_versions.get(str(key))
            if previous is not None and version != previous:
                raise ReleaseTransactionError(f"generation_dataset_version_changed:{key}")


def begin_generation(
    public_root: Path,
    *,
    run_id: str | None = None,
    disk_usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
) -> ReleaseGeneration:
    """Copy the live tree into a fresh generation and return it for staging.

    The copy is deliberately shallow in intent but real on disk: every file is
    materialized so that staging writes cannot reach the live inode.
    """
    public_root = Path(public_root)
    live_root = public_root / "data" / LIVE_DIRNAME
    generations_root = public_root / "data" / GENERATIONS_DIRNAME
    if not live_root.is_dir():
        raise ReleaseTransactionError(f"generation_live_tree_missing:{live_root}")

    suffix = run_id or _utc_stamp()
    generation_id = suffix
    generations_root.mkdir(parents=True, exist_ok=True)
    root = generations_root / generation_id / LIVE_DIRNAME
    index = 1
    while root.exists():
        index += 1
        generation_id = f"{suffix}-{index}"
        root = generations_root / generation_id / LIVE_DIRNAME

    root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(live_root, root, symlinks=False, copy_function=shutil.copy2)
    _fsync_dir(root.parent)

    return ReleaseGeneration(
        public_root=public_root,
        generation_id=generation_id,
        root=root,
        live_root=live_root,
        generations_root=generations_root,
        dataset_versions=_read_dataset_versions(root / RELEASE_FILENAME),
        disk_usage=disk_usage,
    )


def list_generations(public_root: Path) -> list[Path]:
    """Generation directories, oldest first (by directory mtime then name)."""
    generations_root = Path(public_root) / "data" / GENERATIONS_DIRNAME
    if not generations_root.is_dir():
        return []
    items = [p for p in generations_root.iterdir() if p.is_dir()]
    return sorted(items, key=lambda p: (p.stat().st_mtime, p.name))


def _live_target(public_root: Path) -> Path | None:
    live_root = Path(public_root) / "data" / LIVE_DIRNAME
    if not live_root.is_symlink():
        return None
    try:
        return Path(os.readlink(live_root)).resolve()
    except OSError:
        return None


def _live_generation_dir(public_root: Path) -> Path | None:
    """The generation *directory* containing the live tree.

    The symlink points at `<generation>/reddit-voc`, while `list_generations`
    returns `<generation>`. Comparing the two directly never matches, which would
    leave the live generation unprotected from gc and make restore pick the
    generation it is supposed to roll back from.
    """
    target = _live_target(public_root)
    if target is None:
        return None
    generations_root = Path(public_root) / "data" / GENERATIONS_DIRNAME
    try:
        generations_root = generations_root.resolve()
    except OSError:
        return None
    candidate = target.parent
    if candidate == generations_root or generations_root not in candidate.parents:
        return None
    return candidate


def restore(public_root: Path, generation_id: str | None = None) -> str:
    """Point the live symlink back at a previous generation.

    Default is the generation immediately preceding the live one. The generation
    being rolled back *from* is left on disk untouched, so a bad restore is itself
    reversible.
    """
    public_root = Path(public_root)
    live_root = public_root / "data" / LIVE_DIRNAME
    current_generation = _live_generation_dir(public_root)

    if generation_id is None:
        candidates = list_generations(public_root)
        previous = [
            g for g in candidates
            if current_generation is None or g.resolve() != current_generation
        ]
        if not previous:
            raise ReleaseTransactionError("generation_restore_no_previous_generation")
        target = previous[-1] / LIVE_DIRNAME
    else:
        target = Path(public_root) / "data" / GENERATIONS_DIRNAME / generation_id / LIVE_DIRNAME

    if not target.is_dir():
        raise ReleaseTransactionError(f"generation_restore_target_missing:{target}")

    tmp_link = live_root.with_name(f".{LIVE_DIRNAME}.restoring-{os.getpid()}")
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    os.symlink(target.resolve(), tmp_link)
    os.replace(tmp_link, live_root)
    _fsync_dir(live_root.parent)
    return str(target.resolve())


def gc(public_root: Path, keep: int = 2) -> list[str]:
    """Delete old generations, never the live one and never the `keep` newest.

    Returns the generation ids removed. A generation is only removed when it is a
    complete directory under the generations root, so a partially built generation
    from a crashed run is collected too.
    """
    if keep < 1:
        raise ReleaseTransactionError("generation_gc_keep_must_be_positive")
    public_root = Path(public_root)
    # Protect the generation directory, not the inner `reddit-voc` the symlink names:
    # list_generations() yields generation dirs, so comparing against the symlink
    # target would never match and the live generation could be deleted.
    current_generation = _live_generation_dir(public_root)
    generations = list_generations(public_root)

    protected: set[Path] = {g.resolve() for g in generations[-keep:]}
    if current_generation is not None:
        protected.add(current_generation)

    removed: list[str] = []
    for generation in generations:
        if generation.resolve() in protected:
            continue
        shutil.rmtree(generation, ignore_errors=False)
        removed.append(generation.name)
    return removed


__all__ = [
    "DISK_HEADROOM_FACTOR",
    "GENERATIONS_DIRNAME",
    "LIVE_DIRNAME",
    "RELEASE_FILENAME",
    "GenerationSeed",
    "ReleaseGeneration",
    "ReleaseTransactionError",
    "begin_generation",
    "gc",
    "list_generations",
    "restore",
    "tree_digest",
]
