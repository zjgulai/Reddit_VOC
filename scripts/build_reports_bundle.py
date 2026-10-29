#!/usr/bin/env python3
"""Driver: assemble inputs from the public root and emit a fresh reports bundle.

Usage:
    python3 scripts/build_reports_bundle.py --public-root /opt/voc-report/html \
        --out /tmp/gen-reports [--template <dir>]

The bundle is written to `--out` (never in place) so it can be validated before
it replaces the live dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recompute_reports_bundle import build_reports_bundle  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else hashlib.sha256(b"").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=Path("/opt/voc-report/html"))
    parser.add_argument("--out", type=Path, default=Path("/tmp/gen-reports"))
    parser.add_argument("--template", type=Path, default=None)
    args = parser.parse_args()

    public_root = args.public_root
    release = json.loads((public_root / "data/reddit-voc/current-release.json").read_text(encoding="utf-8"))
    base = release["datasets"]["base"]
    reports = release["datasets"]["reports"]
    base_dir = public_root / "data/reddit-voc" / base["dataset_version"]
    posts = json.loads((base_dir / "posts-public.json").read_text(encoding="utf-8"))
    comments = json.loads((base_dir / "comments-public.json").read_text(encoding="utf-8"))
    brand_health = json.loads(
        (public_root / "data/reddit-voc" / release["datasets"]["brand_health"]["dataset_version"] / "brand-health.json")
        .read_text(encoding="utf-8")
    )

    template = args.template or (public_root / reports["manifest_path"]).parent
    anchor = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)).date()

    source_hashes = {
        "metrics_candidate_manifest_sha256": _sha(public_root / base["manifest_path"]),
        "metrics_input_manifest_sha256": _sha(base_dir / "tag-dictionary-public.json"),
        "metrics_validation_receipt_sha256": _sha(base_dir / "aggregates-public.json"),
        "periodized_metrics_sha256": _sha(
            public_root / "data/reddit-voc"
            / release["datasets"]["quarter_insights"]["dataset_version"]
            / "quarter-insights.json"
        ),
    }

    files = build_reports_bundle(
        posts=posts,
        comments=comments,
        brand_health=brand_health,
        template_dir=template,
        dataset_version=reports["dataset_version"],
        source_snapshot_id=base["dataset_version"],
        source_hashes=source_hashes,
        anchor=anchor,
    )

    out: Path = args.out
    for relative, payload in files.items():
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    manifest = json.loads(files["manifest.json"])
    index = json.loads(files["report-index.json"])
    print(json.dumps({
        "out": str(out),
        "anchor": anchor.isoformat(),
        "files": sorted(files),
        "lineage_manifest_sha256": manifest["lineage_manifest_sha256"],
        "validation_receipt_sha256": manifest["validation_receipt_sha256"],
        "manifest_sha256": hashlib.sha256(files["manifest.json"]).hexdigest(),
        "as_of_date": index["as_of_date"],
        "daily_period": index["reports"]["daily"]["period"],
        "weekly_period": index["reports"]["weekly"]["period"],
        "monthly_period": index["reports"]["monthly"]["period"],
        "summary": manifest["summary"],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
