#!/usr/bin/env python3
"""Build one immutable private V3 workbook-import candidate bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_source_manifest import SourceManifestError, load_source_manifest  # noqa: E402
from reddit_voc.v3_workbook_import import (  # noqa: E402
    WorkbookImportError,
    build_workbook_import,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", default=Path.cwd(), type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        manifest = load_source_manifest(arguments.source_manifest, arguments.project_root)
        summary = build_workbook_import(
            manifest,
            arguments.output_root,
            project_root=arguments.project_root,
        )
    except (SourceManifestError, WorkbookImportError) as exc:
        print(f"reddit_add_data_import_failed:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
