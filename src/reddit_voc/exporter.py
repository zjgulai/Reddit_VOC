from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import VocStore


POST_FIELDS = [
    "post_id",
    "run_id",
    "raw_capture_id",
    "subreddit",
    "title",
    "selftext",
    "source_url",
    "created_at_utc",
    "score",
    "num_comments_reported",
    "parsed_comment_count",
    "more_node_count",
    "coverage_grade",
    "matched_keywords",
    "author_hash",
    "media_urls",
]

COMMENT_FIELDS = [
    "comment_id",
    "post_id",
    "run_id",
    "raw_capture_id",
    "parent_id",
    "body",
    "created_at_utc",
    "score",
    "depth",
    "is_submitter",
    "matched_keywords",
    "author_hash",
    "deleted_or_removed",
    "source_url",
]

ANALYSIS_FIELDS = [
    "analysis_id",
    "run_id",
    "source_type",
    "source_id",
    "analysis_version",
    "sentiment_label",
    "sentiment_score",
    "topic",
    "severity",
    "confidence",
    "pain_points",
    "provider_call",
    "source_url",
]


@dataclass(frozen=True)
class ExportResult:
    run_id: str
    posts_jsonl: Path
    comments_jsonl: Path
    analysis_jsonl: Path
    posts_csv: Path
    comments_csv: Path
    analysis_csv: Path
    post_count: int
    comment_count: int
    analysis_count: int
    provider_call: bool = False
    live_send: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "posts_jsonl": str(self.posts_jsonl),
            "comments_jsonl": str(self.comments_jsonl),
            "analysis_jsonl": str(self.analysis_jsonl),
            "posts_csv": str(self.posts_csv),
            "comments_csv": str(self.comments_csv),
            "analysis_csv": str(self.analysis_csv),
            "post_count": self.post_count,
            "comment_count": self.comment_count,
            "analysis_count": self.analysis_count,
            "provider_call": self.provider_call,
            "live_send": self.live_send,
        }


def export_run(store: VocStore, *, run_id: str, output_dir: Path | str) -> ExportResult:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    posts = store.fetch_metric_threads_for_run(run_id)
    comments = store.fetch_metric_comments_for_run(run_id)
    analysis = store.fetch_analysis_for_run(run_id)

    posts_jsonl = out / f"{run_id}-posts.jsonl"
    comments_jsonl = out / f"{run_id}-comments.jsonl"
    analysis_jsonl = out / f"{run_id}-analysis.jsonl"
    posts_csv = out / f"{run_id}-posts.csv"
    comments_csv = out / f"{run_id}-comments.csv"
    analysis_csv = out / f"{run_id}-analysis.csv"

    _write_jsonl(posts_jsonl, posts)
    _write_jsonl(comments_jsonl, comments)
    _write_jsonl(analysis_jsonl, analysis)
    _write_csv(posts_csv, POST_FIELDS, posts)
    _write_csv(comments_csv, COMMENT_FIELDS, comments)
    _write_csv(analysis_csv, ANALYSIS_FIELDS, analysis)

    return ExportResult(
        run_id=run_id,
        posts_jsonl=posts_jsonl,
        comments_jsonl=comments_jsonl,
        analysis_jsonl=analysis_jsonl,
        posts_csv=posts_csv,
        comments_csv=comments_csv,
        analysis_csv=analysis_csv,
        post_count=len(posts),
        comment_count=len(comments),
        analysis_count=len(analysis),
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value
