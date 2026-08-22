#!/usr/bin/env python3
"""Compose an isolated UI dist with a staged Reddit VOC public data tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-dist", type=Path, required=True)
    parser.add_argument("--staged-public", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.ui_dist
    public = args.staged_public
    output = args.output
    if (
        source.is_symlink()
        or not source.is_dir()
        or public.is_symlink()
        or not public.is_dir()
        or output.exists()
        or output.is_symlink()
    ):
        raise SystemExit("isolated dist inputs or destination are unsafe")
    shutil.copytree(source, output, symlinks=False)
    candidate_data = output / "data"
    if candidate_data.exists():
        shutil.rmtree(candidate_data)
    shutil.copytree(public / "data", candidate_data, symlinks=False)
    for name in ("favicon.svg", "icons.svg", "robots.txt"):
        shutil.copy2(public / name, output / name)
    result = {
        "data_root": candidate_data.as_posix(),
        "output": output.as_posix(),
        "production_unchanged": True,
        "schema_version": "reddit_voc_isolated_dist_composition_v1",
        "status": "composed_candidate_only",
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
