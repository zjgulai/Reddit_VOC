#!/usr/bin/env python3
"""Fail closed when the deployed daily collector runtime is not ABI-complete."""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class DailyRuntimeValidationError(ValueError):
    pass


def _digest(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


def _regular(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise DailyRuntimeValidationError(f"runtime_member_missing:{relative}")
    return path


def _tree(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise DailyRuntimeValidationError(
            f"runtime_python_invalid:{path.name}"
        ) from exc


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise DailyRuntimeValidationError(f"runtime_function_missing:{name}")


def _keyword_only_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {argument.arg for argument in function.args.kwonlyargs}


def _call_keywords(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> set[str]:
    matches: list[ast.Call] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id == name:
            matches.append(node)
    if len(matches) != 1:
        raise DailyRuntimeValidationError(
            f"runtime_call_count_invalid:{name}:{len(matches)}"
        )
    return {keyword.arg for keyword in matches[0].keywords if keyword.arg is not None}


def validate_runtime(root: Path, *, require_source_receipt: bool) -> dict[str, Any]:
    root = root.resolve(strict=True)
    cli_path = _regular(root, "src/reddit_voc/cli.py")
    tikhub_path = _regular(root, "src/reddit_voc/tikhub.py")
    raw_path = _regular(root, "src/reddit_voc/raw_artifacts.py")
    runner_path = _regular(root, "scripts/run_daily_collect.sh")

    cli_tree = _tree(cli_path)
    tikhub_tree = _tree(tikhub_path)
    cli_function = _function(cli_tree, "run_tikhub_collector_command")
    collector_function = _function(tikhub_tree, "collect_daily_tikhub")
    cli_keywords = _call_keywords(cli_function, "collect_daily_tikhub")
    collector_keywords = _keyword_only_names(collector_function)

    missing_keywords = sorted(cli_keywords - collector_keywords)
    if missing_keywords:
        raise DailyRuntimeValidationError(
            "collector_cli_abi_mismatch:" + ",".join(missing_keywords)
        )
    if "raw_artifact_root" not in cli_keywords:
        raise DailyRuntimeValidationError("collector_cli_raw_artifact_binding_missing")
    if "raw_artifact_root" not in collector_keywords:
        raise DailyRuntimeValidationError("collector_raw_artifact_parameter_missing")
    raw_persist_calls = sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "persist_raw_artifact"
        for node in ast.walk(tikhub_tree)
    )
    if raw_persist_calls < 2:
        raise DailyRuntimeValidationError("collector_raw_artifact_persistence_missing")

    runner_text = runner_path.read_text(encoding="utf-8")
    source_receipt_checks: dict[str, bool] = {
        "runner_builds_daily_source_batch": "build-daily-source-batch" in runner_text,
        "daily_source_batch_module_present": (
            root / "src/reddit_voc/daily_source_batch.py"
        ).is_file(),
        "schema_migration_module_present": (
            root / "src/reddit_voc/schema_migration.py"
        ).is_file(),
        "query_profile_present": (
            root / "config/source-batch/momcozy-query-v2.json"
        ).is_file(),
        "coverage_profile_present": (
            root / "config/source-batch/momcozy-coverage-v2.json"
        ).is_file(),
    }
    if require_source_receipt:
        failed = sorted(name for name, passed in source_receipt_checks.items() if not passed)
        if failed:
            raise DailyRuntimeValidationError(
                "source_receipt_runtime_incomplete:" + ",".join(failed)
            )

    return {
        "schema_version": "reddit_voc_daily_runtime_validation_v1",
        "status": "passed",
        "root": str(root),
        "profile": (
            "collect_and_source_receipt" if require_source_receipt else "collect_only"
        ),
        "collector_cli_keywords": sorted(cli_keywords),
        "collector_function_keywords": sorted(collector_keywords),
        "raw_persist_call_count": raw_persist_calls,
        "source_receipt_checks": source_receipt_checks,
        "files": {
            "cli": _digest(cli_path),
            "tikhub": _digest(tikhub_path),
            "raw_artifacts": _digest(raw_path),
            "runner": _digest(runner_path),
        },
        "boundaries": {
            "provider_call": False,
            "database_write": False,
            "remote_write": False,
            "live_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--require-source-receipt", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_runtime(
            args.root, require_source_receipt=args.require_source_receipt
        )
    except (OSError, DailyRuntimeValidationError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "reddit_voc_daily_runtime_validation_v1",
                    "status": "failed",
                    "reason": str(exc),
                    "boundaries": {
                        "provider_call": False,
                        "database_write": False,
                        "remote_write": False,
                        "live_send": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
