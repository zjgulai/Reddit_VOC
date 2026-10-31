#!/usr/bin/env python3
"""Path resolution for release bindings, rooted at a data directory.

Both the pipeline and the recompute engine resolve `current-release.json`
binding strings such as `data/reddit-voc/<version>/manifest-public.json`. They
must do it against a *data root* -- the live `data/reddit-voc` directory, or a
staged generation -- and never against the site root, because in staging mode
`<site>/data/reddit-voc` is a symlink whose target is what is being served.

Joining a binding onto the site root therefore writes the live tree. That is
the 2026-10-29 incident: the pointer was correctly blocked, but posts-public.json,
the base manifest and current-release.json had already been overwritten live.

Stdlib only and no imports from the rest of the tree, so both callers can depend
on it without a cycle.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

# The two components every binding path starts with.
PREFIX = PurePosixPath("data", "reddit-voc")

# Binding strings are POSIX and are produced and consumed on Linux. Parsing them
# with PurePosixPath keeps the components identical on a macOS dev box, where a
# backslash is a legal filename character rather than a separator.


class ReleasePathError(ValueError):
    """A binding path is unusable, so the caller must fail closed."""


def _raw(path_or_binding: Any) -> Any:
    if isinstance(path_or_binding, Mapping):
        return path_or_binding.get("manifest_path")
    return path_or_binding


def relocate_manifest_path(path_or_binding: Any) -> PurePosixPath:
    """Return a binding path relative to the data root.

    Accepts the raw string or the binding mapping carrying it.
    `data/reddit-voc/<version>/...` becomes `<version>/...`; a value that is
    already data-root-relative passes through, so applying this twice cannot
    double-prefix.

    Empty, absolute and `..`-escaping values raise. Plain path joining used to
    let them escape the site root silently; a malformed release document must
    stop the run instead of publishing from an unintended directory.
    """
    raw = _raw(path_or_binding)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ReleasePathError("release_path_invalid: binding has no manifest_path")
    if not isinstance(raw, str):
        raise ReleasePathError(f"release_path_invalid: manifest_path is {type(raw).__name__}")

    raw = raw.strip()
    if "\\" in raw:
        # On POSIX this would be a single filename component, never a directory.
        raise ReleasePathError(f"release_path_invalid: backslash in {raw!r}")

    pure = PurePosixPath(raw)
    if pure.is_absolute():
        raise ReleasePathError(f"release_path_escapes_root: absolute path {raw!r}")
    parts = pure.parts
    if ".." in parts:
        raise ReleasePathError(f"release_path_escapes_root: parent traversal in {raw!r}")

    if tuple(parts[: len(PREFIX.parts)]) == PREFIX.parts:
        parts = parts[len(PREFIX.parts):]
    if not parts:
        raise ReleasePathError(f"release_path_invalid: {raw!r} names the data root itself")
    return PurePosixPath(*parts)


def manifest_path(data_root: Path, path_or_binding: Any) -> Path:
    """Absolute path to a dataset manifest inside `data_root`.

    Deliberately not `.resolve()`d: `data_root` may be a staged generation, and
    resolving would follow a symlink back to the live tree.
    """
    return Path(data_root) / relocate_manifest_path(path_or_binding)


def dataset_dir(data_root: Path, path_or_binding: Any) -> Path:
    """The directory holding a dataset's files (the manifest's parent)."""
    return manifest_path(data_root, path_or_binding).parent


def load_release(data_root: Path) -> dict:
    """Read and parse `current-release.json` from `data_root`."""
    return json.loads((Path(data_root) / "current-release.json").read_text(encoding="utf-8"))
