from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import VocStore
from .time_window import daily_window


def parse_anchor_utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("anchor timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def build_missed_run_report(
    store: VocStore,
    *,
    anchor_utc: datetime,
    timezone_name: str = "Asia/Shanghai",
    run_hour: int = 7,
) -> dict[str, Any]:
    window = daily_window(anchor=anchor_utc, timezone_name=timezone_name, run_hour=run_hour)
    matching_runs = store.find_runs_by_window(
        window.start_utc.isoformat(),
        window.end_utc.isoformat(),
    )
    return {
        "status": "covered" if matching_runs else "missed",
        "expected_run_at_local": window.run_at_local.isoformat(),
        "window_start_utc": window.start_utc.isoformat(),
        "window_end_utc": window.end_utc.isoformat(),
        "matching_run_ids": [str(run["run_id"]) for run in matching_runs],
        "matching_statuses": {str(run["run_id"]): str(run["status"]) for run in matching_runs},
        "provider_call": False,
        "live_send": False,
    }


def build_run_issue_summary(run_status: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    counts = run_status.get("counts", {}) or {}
    coverage = run_status.get("coverage", {}) or {}

    if run_status.get("reason") == "run_not_found":
        issues.append({"code": "run_not_found", "severity": "high"})
    elif run_status.get("status") == "failed":
        issues.append({"code": "run_failed", "severity": "high"})
    if run_status.get("status") == "empty":
        issues.append({"code": "empty_result", "severity": "medium"})
    if int(counts.get("threads", 0) or 0) > 0 and int(counts.get("analysis", 0) or 0) == 0:
        issues.append({"code": "analysis_missing", "severity": "high"})
    for grade in ["partial", "post_only", "failed"]:
        count = int(coverage.get(grade, 0) or 0)
        if count:
            issues.append({"code": f"{grade}_coverage", "severity": "medium", "count": count})
    if bool(run_status.get("provider_call")):
        issues.append({"code": "provider_call_enabled", "severity": "high"})
    if bool(run_status.get("live_send")):
        issues.append({"code": "live_send_enabled", "severity": "high"})

    return {
        "run_id": run_status.get("run_id"),
        "operational_state": "clear" if not issues else "attention",
        "run_status": run_status,
        "issues": issues,
        "provider_call": False,
        "live_send": False,
    }


@dataclass(frozen=True)
class PruneResult:
    path: str
    pattern: str
    keep_last: int
    apply: bool
    kept: list[str]
    candidates: list[str]
    removed: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "pattern": self.pattern,
            "keep_last": self.keep_last,
            "apply": self.apply,
            "kept": self.kept,
            "candidates": self.candidates,
            "removed": self.removed,
        }


def prune_files(
    *,
    paths: list[Path],
    patterns: list[str],
    keep_last: int,
    apply: bool,
) -> dict[str, Any]:
    if keep_last < 1:
        raise ValueError("keep_last must be >= 1")

    results: list[PruneResult] = []
    for path in paths:
        for pattern in patterns:
            if path.is_file():
                files = [path]
            elif path.exists():
                files = [candidate for candidate in path.glob(pattern) if candidate.is_file()]
            else:
                files = []
            files = sorted(files, key=lambda item: (item.stat().st_mtime_ns, str(item)), reverse=True)
            kept = files[:keep_last]
            candidates = files[keep_last:]
            removed: list[Path] = []
            if apply:
                for candidate in candidates:
                    candidate.unlink()
                    removed.append(candidate)
            results.append(
                PruneResult(
                    path=str(path),
                    pattern=pattern,
                    keep_last=keep_last,
                    apply=apply,
                    kept=[str(item) for item in kept],
                    candidates=[str(item) for item in candidates],
                    removed=[str(item) for item in removed],
                )
            )

    return {
        "status": "ok",
        "provider_call": False,
        "live_send": False,
        "results": [result.as_dict() for result in results],
    }
