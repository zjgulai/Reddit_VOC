#!/usr/bin/env python3
"""Run the repository-contained or local-artifact backend test lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any, Mapping


SCHEMA_VERSION = "reddit-voc-ci-test-lanes-v1"
CONFIG_PATH = Path("config/ci/test-lanes.json")


class TestLaneError(RuntimeError):
    """Raised when the test-lane registry is incomplete or unsafe."""


def _safe_test_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise TestLaneError("test_lane_path_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or len(path.parts) != 2
        or path.parts[0] != "tests"
        or not path.name.startswith("test_")
        or path.suffix != ".py"
    ):
        raise TestLaneError("test_lane_path_invalid")
    return path


def classify_tests(project_root: Path) -> Mapping[str, tuple[str, ...]]:
    project_root = project_root.resolve(strict=True)
    config_path = project_root / CONFIG_PATH
    try:
        config: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TestLaneError("test_lane_config_unreadable") from exc
    if not isinstance(config, Mapping) or set(config) != {
        "schema_version",
        "local_artifact_roots",
        "local_artifact_test_modules",
    }:
        raise TestLaneError("test_lane_config_invalid")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise TestLaneError("test_lane_schema_invalid")
    roots = config.get("local_artifact_roots")
    if (
        not isinstance(roots, list)
        or not roots
        or roots != sorted(set(roots))
        or any(not isinstance(root, str) or not root for root in roots)
    ):
        raise TestLaneError("local_artifact_roots_invalid")
    configured = config.get("local_artifact_test_modules")
    if not isinstance(configured, list) or configured != sorted(set(configured)):
        raise TestLaneError("local_artifact_modules_invalid")
    artifact_modules = tuple(
        path.as_posix() for path in (_safe_test_path(value) for value in configured)
    )
    discovered = tuple(
        sorted(
            path.relative_to(project_root).as_posix()
            for path in (project_root / "tests").glob("test_*.py")
            if path.is_file() and not path.is_symlink()
        )
    )
    unknown = sorted(set(artifact_modules) - set(discovered))
    if unknown:
        raise TestLaneError(f"local_artifact_module_missing:{unknown[0]}")
    repository_modules = tuple(sorted(set(discovered) - set(artifact_modules)))
    if not repository_modules:
        raise TestLaneError("repository_test_lane_empty")
    return {
        "repository": repository_modules,
        "local-artifact": artifact_modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "lane",
        choices=("repository", "local-artifact"),
        help="repository is GitHub-safe; local-artifact requires excluded frozen inputs",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--list", action="store_true")
    args, pytest_args = parser.parse_known_args()
    try:
        lanes = classify_tests(args.project_root)
    except TestLaneError as exc:
        print(f"backend_test_lane_failed:{exc}", file=sys.stderr)
        return 2
    modules = lanes[args.lane]
    print(
        json.dumps(
            {
                "lane": args.lane,
                "module_count": len(modules),
                "status": "selected",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if args.list:
        print("\n".join(modules))
        return 0
    command = [sys.executable, "-m", "pytest", "-q", *modules]
    if pytest_args:
        extra = pytest_args[1:] if pytest_args[0] == "--" else pytest_args
        command.extend(extra)
    return subprocess.run(command, cwd=args.project_root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
