#!/usr/bin/env python3
"""Run the repository-contained or local-artifact backend test lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any, Mapping
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "reddit-voc-ci-test-lanes-v1"
CONFIG_PATH = Path("config/ci/test-lanes.json")
KNOWN_FAILURES_SCHEMA = "reddit-voc-known-failures-v1"
KNOWN_FAILURES_PATH = Path("config/ci/known-failures.json")


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


def load_known_failures(
    project_root: Path, path: Path | None = None
) -> tuple[set[str], set[str]]:
    """Return (genuine_preexisting, lane_isolation) node ids.

    The file is a freeze of failures that predate the current program. CI may
    treat only these as baseline; anything else is a regression. The schema is
    checked so a malformed baseline cannot silently disable the gate.
    """
    target = Path(path) if path is not None else KNOWN_FAILURES_PATH
    if not target.is_absolute():
        target = project_root / target
    try:
        data: Any = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TestLaneError("known_failures_unreadable") from exc
    if not isinstance(data, Mapping) or data.get("schema_version") != KNOWN_FAILURES_SCHEMA:
        raise TestLaneError("known_failures_schema_invalid")

    def nodes(section: str) -> set[str]:
        block = data.get(section)
        if not isinstance(block, Mapping) or not isinstance(block.get("nodes"), list):
            raise TestLaneError(f"known_failures_{section}_invalid")
        values = block["nodes"]
        if any(not isinstance(value, str) or not value.startswith("tests/") for value in values):
            raise TestLaneError(f"known_failures_{section}_node_invalid")
        return set(values)

    genuine = nodes("genuine_preexisting")
    lane = nodes("lane_isolation")
    if len(lane) != data["lane_isolation"].get("count", len(lane)):
        raise TestLaneError("known_failures_lane_count_mismatch")
    return genuine, lane


def parse_junit_failures(path: Path) -> set[str]:
    """Map pytest's JUnit testcases with failure/error to pytest node ids."""
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise TestLaneError("junit_report_unreadable") from exc
    failures: set[str] = set()
    for testcase in tree.iter("testcase"):
        if testcase.find("failure") is None and testcase.find("error") is None:
            continue
        classname = testcase.get("classname") or ""
        name = testcase.get("name") or ""
        parts = classname.split(".")
        if len(parts) < 2 or parts[0] != "tests":
            continue
        module = f"tests/{parts[1]}.py"
        classes = parts[2:]
        suffix = "::" + "::".join(classes) if classes else ""
        failures.add(f"{module}{suffix}::{name}")
    return failures


def classify_failures(
    failures: set[str], genuine: set[str], lane: set[str]
) -> tuple[set[str], set[str]]:
    known = genuine | lane
    return failures & known, failures - known


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "lane",
        choices=("repository", "local-artifact"),
        help="repository is GitHub-safe; local-artifact requires excluded frozen inputs",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--enforce-known-failures",
        action="store_true",
        help="fail only on failures not listed in config/ci/known-failures.json",
    )
    parser.add_argument(
        "--known-failures",
        type=Path,
        default=None,
        help="override the known-failures path (default: config/ci/known-failures.json)",
    )
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
    if not args.enforce_known_failures:
        command = [sys.executable, "-m", "pytest", "-q", *modules]
        if pytest_args:
            extra = pytest_args[1:] if pytest_args[0] == "--" else pytest_args
            command.extend(extra)
        return subprocess.run(command, cwd=args.project_root, check=False).returncode

    try:
        genuine, lane_isolation = load_known_failures(
            args.project_root, args.known_failures
        )
    except TestLaneError as exc:
        print(f"backend_test_lane_failed:{exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as temporary:
        report = Path(temporary) / "junit.xml"
        command = [
            sys.executable, "-m", "pytest", "-q",
            f"--junitxml={report}", *modules,
        ]
        if pytest_args:
            extra = pytest_args[1:] if pytest_args[0] == "--" else pytest_args
            command.extend(
                value for value in extra if not value.startswith("--junitxml")
            )
        completed = subprocess.run(command, cwd=args.project_root, check=False)
        try:
            failures = parse_junit_failures(report)
        except TestLaneError as exc:
            print(f"backend_test_lane_failed:{exc}", file=sys.stderr)
            return completed.returncode or 2
        known, unknown = classify_failures(
            failures, genuine, lane_isolation
        )
        print(
            json.dumps(
                {
                    "lane": args.lane,
                    "pytest_returncode": completed.returncode,
                    "failure_count": len(failures),
                    "known_failures": sorted(known),
                    "unknown_failures": sorted(unknown),
                    "status": (
                        "new_regression"
                        if unknown
                        else "known_baseline"
                        if failures
                        else "clean"
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        if unknown:
            return 1
        if failures:
            # Every failure is frozen in known-failures.json (genuine or
            # lane-isolation). CI is allowed to pass, but the summary names them.
            return 0
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
