#!/usr/bin/env python3
"""Build a deterministic, read-only comment repair queue."""

from __future__ import annotations

import argparse
from pathlib import Path

from reddit_voc.comment_repair import build_comment_repair_plan, write_comment_repair_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--provider-request-ceiling", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = build_comment_repair_plan(
        args.database,
        run_id=args.run_id,
        provider_request_ceiling=args.provider_request_ceiling,
    )
    digest = write_comment_repair_plan(plan, args.output)
    print(
        f"repair_plan_sha256={digest} candidates={plan.candidate_count} "
        f"selected={plan.selected_candidate_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

