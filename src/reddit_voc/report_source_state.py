from __future__ import annotations

from typing import Mapping


def classify_report_source_state(
    *, status: object, post_count: object, comment_count: object
) -> Mapping[str, object]:
    normalized_status = str(status or "")
    if type(post_count) is not int or post_count < 0:
        raise RuntimeError("report_source_post_count_invalid")
    if type(comment_count) is not int or comment_count < 0:
        raise RuntimeError("report_source_comment_count_invalid")
    if normalized_status == "failed":
        raise RuntimeError("report_source_run_failed")
    if normalized_status not in {"success", "partial", "empty"}:
        raise RuntimeError("report_source_status_invalid")
    if normalized_status == "empty":
        if post_count != 0 or comment_count != 0:
            raise RuntimeError("report_source_empty_has_observations")
        mode = "empty_success"
    else:
        if post_count == 0:
            raise RuntimeError("report_source_no_observations")
        mode = (
            "observed_partial"
            if normalized_status == "partial"
            else "observed_complete"
        )
    return {
        "schema_version": "daily-report-source-state-v1",
        "status": normalized_status,
        "mode": mode,
        "post_count": post_count,
        "comment_count": comment_count,
        "business_report_allowed": True,
        "failure_alert_allowed": False,
    }


def validate_frozen_report_source_state(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "status",
        "mode",
        "post_count",
        "comment_count",
        "business_report_allowed",
        "failure_alert_allowed",
    }:
        raise RuntimeError("validation_report_source_state_invalid")
    if value.get("schema_version") != "daily-report-source-state-v1":
        raise RuntimeError("validation_report_source_state_invalid")
    try:
        expected = classify_report_source_state(
            status=value.get("status"),
            post_count=value.get("post_count"),
            comment_count=value.get("comment_count"),
        )
    except RuntimeError as exc:
        raise RuntimeError("validation_report_source_state_invalid") from exc
    if dict(value) != dict(expected):
        raise RuntimeError("validation_report_source_state_invalid")
    return expected
