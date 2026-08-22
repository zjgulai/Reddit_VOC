#!/usr/bin/env python3
"""Build an immutable SourceBatch from a read-only server collector SQLite snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.server_snapshot_source_batch import (  # noqa: E402
    ServerSnapshotSourceBatchError,
    build_server_snapshot_source_batch,
)


def _utc(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ServerSnapshotSourceBatchError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ServerSnapshotSourceBatchError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--window-start-utc", required=True)
    parser.add_argument("--window-end-utc", required=True)
    parser.add_argument("--query-profile", type=Path, required=True)
    parser.add_argument("--coverage-profile", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_server_snapshot_source_batch(
            source_database_path=args.source_database,
            output_root=args.output_root,
            batch_id=args.batch_id,
            window_start_utc=_utc(args.window_start_utc, label="window_start_utc"),
            window_end_utc=_utc(args.window_end_utc, label="window_end_utc"),
            query_profile_path=args.query_profile,
            coverage_profile_path=args.coverage_profile,
        )
    except (OSError, ServerSnapshotSourceBatchError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "manifest_path": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "source_database_sha256": result.source_database_sha256,
                "status": result.write_status,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
