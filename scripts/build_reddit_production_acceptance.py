#!/usr/bin/env python3
"""Build and validate immutable Reddit VOC public production acceptance.

The builder only seals already-observed evidence supplied as an explicit local
JSON document.  It does not collect evidence, access the public site, open SSH,
or perform any deployment action.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_promotion_packet as packet_contract
    from scripts import reddit_release_control as control
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_promotion_packet as packet_contract
    import reddit_release_control as control


SCHEMA_VERSION = "reddit_voc_production_acceptance_receipt_v1"
SCHEMA_VERSION_V2 = "reddit_voc_production_acceptance_receipt_v2"
STATUS = "passed_public_production_acceptance"
REMOTE_PROMOTION_STATUS = "promoted_pending_public_acceptance"
REMOTE_PROMOTION_SCHEMA_V2 = "reddit_voc_remote_promotion_receipt_v2"
PUBLIC_HTTP_SCHEMA = "reddit_voc_public_http_acceptance_observation_v1"
PUBLIC_ROUTES = frozenset(
    {
        "/",
        "/dashboard",
        "/dashboard/reports",
        "/dashboard/analytics",
        "/dashboard/insights",
        "/dashboard/search",
        "/dashboard/ugc-showcase",
        "/dashboard/messages",
        "/dashboard/settings",
        "/features",
        "/how-it-works",
        "/faq",
        "/cases",
    }
)
BROWSER_VIEWPORTS = frozenset({"desktop", "mobile"})
HISTORICAL_V1_RECEIPT_SHA256S = frozenset(
    {
        "23d45bd73cd93b5c54872afd3fd4f0716a9d54ff554892886b7427d614c50473",
        "972253ec811ed4627a033a1675c071e3b683f0c22f045833002afe184a61a914",
        "b5fcd6821de7f4047b1deb9bee6bd60c3d81bcaa6380fc2d8e8912f0a5a76ade",
        "c37248efc026457286adbc3d7d8eab9005d24072e889afab67b120004518255a",
        "c609b83bd200fc010afb9bbc89e7bdc61b4f9135b318ea0892485eec9abdeb1d",
        "ead3173a3384b45da7317e8daf98b4560ad7e12726dfc30f0585ed9dbaf98570",
        "f4faf9b94329791607eb0feb3f18b41df47161bb67caeb764bc178637ee3ff22",
    }
)
REMOTE_PROMOTION_BASENAME_RE = re.compile(
    r"^promotion-[0-9]{8}T[0-9]{6}Z-([a-f0-9]{64})\.json$"
)


class ProductionAcceptanceError(ValueError):
    """Observed production evidence does not satisfy the acceptance contract."""


def _fail(message: str) -> NoReturn:
    raise ProductionAcceptanceError(message)


def _object(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label}_not_object")
    return value


def _false_boundaries(boundaries: Mapping[str, Any]) -> None:
    for name in (
        "database_write",
        "live_send",
        "provider_call",
        "schedule_change",
        "shared_nginx_modified",
    ):
        if boundaries.get(name) is not False:
            _fail(f"boundary_{name}_invalid")


def _acceptance_path(value: object, *, release_sha256: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        _fail("remote_promotion_receipt_path_invalid")
    path = PurePosixPath(value)
    match = REMOTE_PROMOTION_BASENAME_RE.fullmatch(path.name)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or match is None
        or match.group(1) != release_sha256
        or path.parts[:4] != ("/", "opt", "reddit-voc-insights-site", "evidence")
    ):
        _fail("remote_promotion_receipt_path_invalid")
    return value


def _evidence_record(value: object, *, label: str) -> Mapping[str, Any]:
    record = _object(value, label=label)
    if set(record) != {"path", "sha256"}:
        _fail(f"{label}_unexpected_fields")
    path = record.get("path")
    if not isinstance(path, str) or not path or "\\" in path:
        _fail(f"{label}_path_invalid")
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path:
        _fail(f"{label}_path_invalid")
    try:
        control.require_sha256(record.get("sha256"), label=f"{label}_sha256")
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    return record


def _read_evidence_json(
    *, root: Path, record: Mapping[str, Any], label: str, canonical: bool
) -> tuple[str, bytes, dict[str, Any]]:
    normalized = _evidence_record(record, label=label)
    path = root.joinpath(*PurePosixPath(str(normalized["path"])).parts)
    try:
        relative, payload = control.read_file(
            root=root, path=path, label=label, expected_mode=0o600
        )
        if control.sha256_bytes(payload) != normalized["sha256"]:
            _fail(f"{label}_sha256_mismatch")
        value = control.load_json_bytes(
            payload, label=label, canonical_required=canonical
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    return relative, payload, value


def _validate_evidence_time(
    value: object, *, label: str, acceptance: Mapping[str, Any]
) -> datetime:
    try:
        _, observed_at = control.parse_utc(value, label=label)
        _, accepted_at = control.parse_utc(
            acceptance.get("accepted_at_utc"), label="accepted_at_utc"
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    age_seconds = (accepted_at - observed_at).total_seconds()
    if age_seconds < 0 or age_seconds > 3600:
        _fail(f"{label}_outside_acceptance_window")
    return observed_at


def _validate_remote_promotion_v2(
    value: Mapping[str, Any], *, acceptance: Mapping[str, Any]
) -> datetime:
    authorization = _object(acceptance.get("authorization"), label="authorization")
    rollback = _object(acceptance.get("rollback"), label="rollback")
    invariants = _object(acceptance.get("invariants"), label="invariants")
    for name in (
        "collector_id", "cron_sha256", "data_inventory_sha256",
        "data_pointer_sha256", "nginx_sha256", "packet_sha256",
        "permit_sha256", "previous_data_pointer_sha256",
        "previous_release_sha256", "release_sha256", "translation_id",
    ):
        try:
            control.require_sha256(value.get(name), label=f"remote_{name}")
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
    observed_at = _validate_evidence_time(
        value.get("generated_at_utc"),
        label="remote_promotion_generated_at_utc",
        acceptance=acceptance,
    )
    if (
        value.get("schema_version") != REMOTE_PROMOTION_SCHEMA_V2
        or value.get("status") != REMOTE_PROMOTION_STATUS
        or value.get("evidence_grade") != "L4-authorized-live"
        or value.get("release_sha256") != acceptance.get("release_sha256")
        or value.get("packet_sha256") != authorization.get("packet_sha256")
        or value.get("permit_sha256") != authorization.get("permit_sha256")
        or value.get("data_release_id") != acceptance.get("data_release_id")
        or value.get("data_pointer_sha256") != acceptance.get("data_pointer_sha256")
        or value.get("data_inventory_sha256") != acceptance.get("data_inventory_sha256")
        or value.get("data_file_count") != acceptance.get("data_file_count")
        or value.get("data_total_bytes") != acceptance.get("data_total_bytes")
        or value.get("previous_release_sha256")
        != rollback.get("target_release_sha256")
        or value.get("previous_data_release_id")
        != rollback.get("target_data_release_id")
        or value.get("previous_data_pointer_sha256")
        != rollback.get("target_data_pointer_sha256")
        or value.get("collector_id") != invariants.get("collector_id")
        or value.get("collector_restart_count")
        != invariants.get("collector_restart_count")
        or value.get("translation_id") != invariants.get("translation_id")
        or value.get("translation_restart_count")
        != invariants.get("translation_restart_count")
        or value.get("cron_sha256") != invariants.get("cron_sha256")
        or value.get("nginx_sha256") != invariants.get("shared_nginx_sha256")
        or value.get("candidate_18339_smoke") is not True
        or value.get("production_container_smoke") is not True
        or value.get("four_exports_complete") is not False
        or value.get("candidate_exports_validation_bound") is not True
        or value.get("database_write") is not False
        or value.get("live_send") is not False
        or value.get("provider_call") is not False
        or value.get("shared_nginx_modified") is not False
    ):
        _fail("remote_promotion_upstream_binding_mismatch")
    return observed_at


def _validate_public_http(
    value: Mapping[str, Any], *, acceptance: Mapping[str, Any],
    dataset_versions: Mapping[str, str]
) -> datetime:
    summary = _object(acceptance.get("public_http"), label="public_http")
    counts = _object(value.get("counts"), label="public_http_counts")
    pointer = _object(value.get("data_pointer"), label="public_http_data_pointer")
    marker = _object(value.get("release_marker"), label="public_http_release_marker")
    health = _object(value.get("health"), label="public_http_health")
    routes = value.get("routes")
    artifacts = value.get("public_artifacts")
    security = value.get("security_paths")
    if not isinstance(routes, list):
        _fail("public_http_routes_invalid")
    if not isinstance(artifacts, list):
        _fail("public_http_artifacts_invalid")
    if not isinstance(security, list):
        _fail("public_http_security_paths_invalid")

    def path_statuses(
        rows: list[object], *, label: str, expected_status: int
    ) -> list[str]:
        paths: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("status") != expected_status:
                _fail(f"{label}_status_invalid")
            path = row.get("path")
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or "\\" in path
                or ".." in PurePosixPath(path).parts
            ):
                _fail(f"{label}_path_invalid")
            paths.append(path)
        if len(paths) != len(set(paths)):
            _fail(f"{label}_duplicate_path")
        return paths

    route_paths = path_statuses(
        routes, label="public_http_route", expected_status=200
    )
    artifact_paths = path_statuses(
        artifacts, label="public_http_artifact", expected_status=200
    )
    security_paths = path_statuses(
        security, label="public_http_security", expected_status=404
    )
    observed_at = _validate_evidence_time(
        value.get("observed_at_utc"),
        label="public_http_observed_at_utc",
        acceptance=acceptance,
    )
    expected_artifact_paths = {
        "/release.json",
        "/data/reddit-voc/current-release.json",
        f"/data/reddit-voc/{dataset_versions['base']}/manifest-public.json",
        f"/data/reddit-voc/{dataset_versions['insights']}/public/manifest.json",
        f"/data/reddit-voc/{dataset_versions['reports']}/public/manifest.json",
        f"/data/reddit-voc/{dataset_versions['personas']}/manifest.json",
        "/data/cases/manifest.v1.json",
        "/data/cases/case-index.v1.json",
    }
    expected_security_paths = {
        "/.env",
        "/.env.local",
        "/frontend-source-manifest.json",
        "/candidate-ui-source-validation-receipt.json",
        "/candidate-ui-validation-receipt.json",
        "/release-manifest.json",
        f"/data/reddit-voc/{dataset_versions['base']}/manifest.json",
        f"/data/reddit-voc/{dataset_versions['base']}/aggregates.json",
        f"/data/reddit-voc/{dataset_versions['base']}/posts.json",
        f"/data/reddit-voc/{dataset_versions['base']}/comments.json",
        f"/data/reddit-voc/{dataset_versions['base']}/quarantine.json",
        f"/data/reddit-voc/{dataset_versions['base']}/tag-dictionary.json",
        f"/data/reddit-voc/{dataset_versions['insights']}/manifest.json",
        f"/data/reddit-voc/{dataset_versions['insights']}/insights.json",
        f"/data/reddit-voc/{dataset_versions['insights']}/semantic-audit.json",
        f"/data/reddit-voc/{dataset_versions['reports']}/manifest.json",
        f"/data/reddit-voc/{dataset_versions['reports']}/report-index.json",
        f"/data/reddit-voc/{dataset_versions['reports']}/current/daily.json",
        f"/data/reddit-voc/{dataset_versions['reports']}/archive/daily.json",
        f"/data/reddit-voc/{dataset_versions['personas']}/imports/private.json",
    }
    if (
        value.get("schema_version") != PUBLIC_HTTP_SCHEMA
        or value.get("status") != "passed_public_http_acceptance"
        or value.get("evidence_grade") != "L3-public-read-only"
        or value.get("base_url") != acceptance.get("site_url")
        or value.get("expected_release_sha256") != acceptance.get("release_sha256")
        or value.get("expected_data_release_id") != acceptance.get("data_release_id")
        or value.get("expected_data_pointer_sha256")
        != acceptance.get("data_pointer_sha256")
        or marker.get("release_sha256") != acceptance.get("release_sha256")
        or pointer.get("release_id") != acceptance.get("data_release_id")
        or pointer.get("sha256") != acceptance.get("data_pointer_sha256")
        or health != {"body": "ok", "path": "/healthz", "status": 200}
        or value.get("tls_verified") is not True
        or value.get("remote_write") is not False
        or frozenset(route_paths) != PUBLIC_ROUTES
        or set(artifact_paths) != expected_artifact_paths
        or set(security_paths) != expected_security_paths
        or counts.get("route_200_count") != 13
        or counts.get("public_artifact_200_count") != 8
        or counts.get("security_404_count") != 20
        or summary.get("route_200_count") != 13
        or summary.get("public_artifact_200_count") != 8
        or summary.get("security_404_count") != 20
        or summary.get("health_http_200") is not True
        or summary.get("release_marker_verified") is not True
        or summary.get("tls_verified") is not True
    ):
        _fail("public_http_upstream_binding_mismatch")
    return observed_at


def _validate_public_browser(
    value: Mapping[str, Any], *, acceptance: Mapping[str, Any]
) -> tuple[dict[str, str], datetime]:
    summary = _object(acceptance.get("public_browser"), label="public_browser")
    release = _object(value.get("release"), label="public_browser_release")
    routes = value.get("routes")
    browser_errors = value.get("browserErrors")
    same_origin_failures = value.get("sameOriginHttpFailures")
    external_requests = value.get("externalRequests")
    if not isinstance(routes, list) or not routes:
        _fail("public_browser_routes_invalid")
    if not isinstance(browser_errors, list):
        _fail("public_browser_errors_invalid")
    if not isinstance(same_origin_failures, list):
        _fail("public_browser_http_failures_invalid")
    if not isinstance(external_requests, list):
        _fail("public_browser_external_requests_invalid")
    expected_route_pairs = {
        (viewport, route)
        for viewport in BROWSER_VIEWPORTS
        for route in PUBLIC_ROUTES
    }
    observed_route_pairs: set[tuple[str, str]] = set()
    for row in routes:
        if not isinstance(row, dict):
            _fail("public_browser_route_invalid")
        viewport = row.get("viewport")
        route = row.get("route")
        if not isinstance(viewport, str) or not isinstance(route, str):
            _fail("public_browser_route_identity_invalid")
        pair = (viewport, route)
        if pair in observed_route_pairs:
            _fail("public_browser_route_duplicate")
        observed_route_pairs.add(pair)
    dashboard = value.get("dashboard")
    insights = value.get("insights")
    reports = value.get("reports")
    dataset_versions = release.get("datasetVersions")
    required_dataset_keys = {
        "base",
        "brand_health",
        "casebook",
        "insights",
        "personas",
        "quarter_insights",
        "reports",
    }
    observed_at = _validate_evidence_time(
        value.get("observedAtUtc"),
        label="public_browser_observed_at_utc",
        acceptance=acceptance,
    )
    reports_valid = False
    if isinstance(reports, list) and len(reports) == 3:
        reports_valid = True
        observed_periods: set[str] = set()
        for report in reports:
            if not isinstance(report, dict):
                reports_valid = False
                break
            period = report.get("period")
            expected_indicator_count = report.get("expectedIndicatorCount")
            indicator_count = report.get("indicatorCount")
            fixed_indicator_count = 7 if period == "日报" else 11
            fixed_history_count = 15 if period == "日报" else 13
            if (
                period not in {"日报", "周报", "月报"}
                or not isinstance(period, str)
                or period in observed_periods
                or not isinstance(expected_indicator_count, int)
                or expected_indicator_count <= 0
                or expected_indicator_count != fixed_indicator_count
                or indicator_count != expected_indicator_count
                or report.get("helpButtonCount") != indicator_count
                or not isinstance(report.get("trendCount"), int)
                or report.get("trendCount", 0) <= 0
                or report.get("historicalPeriodOptionCount")
                != report.get("expectedHistoricalPeriodOptionCount")
                or report.get("expectedHistoricalPeriodOptionCount")
                != fixed_history_count
                or "数据锚点：" not in str(report.get("availablePeriodText"))
                or any(
                    report.get(name) is not True
                    for name in (
                        "completeness100",
                        "storyMapComplete",
                        "operationalBody",
                        "comparison",
                        "upTrendRed",
                        "downTrendGreen",
                        "unavailableAbsent",
                        "periodScopePresent",
                        "latestCompleteSelected",
                        "historyContractVisible",
                        "legacyTermsAbsent",
                        "dailyMidnightLabelAbsent",
                    )
                )
                or report.get("storyMapCount") != 1
            ):
                reports_valid = False
                break
            observed_periods.add(period)
        reports_valid = reports_valid and observed_periods == {"日报", "周报", "月报"}
    if (
        value.get("status") != "passed"
        or value.get("evidenceLevel") != "browser_dom_network_acceptance"
        or value.get("baseUrl") != acceptance.get("site_url")
        or release.get("releaseSha256") != acceptance.get("release_sha256")
        or release.get("releaseId") != acceptance.get("data_release_id")
        or release.get("releasePointerSha256") != acceptance.get("data_pointer_sha256")
        or release.get("noLogin") is not True
        or release.get("collectorIsolation") is not True
        or not isinstance(dataset_versions, dict)
        or set(dataset_versions) != required_dataset_keys
        or any(
            not isinstance(dataset_version, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,127}", dataset_version)
            is None
            for dataset_version in dataset_versions.values()
        )
        or observed_route_pairs != expected_route_pairs
        or any(
            not isinstance(row, dict)
            or row.get("status") != 200
            or row.get("finalPath") != row.get("route")
            or not isinstance(row.get("textLength"), int)
            or row.get("textLength", 0) < 100
            or row.get("requiredTextPresent") is not True
            or row.get("forbiddenLegacyGateTextPresent") is not False
            or row.get("horizontalOverflow") is not False
            or row.get("passwordInputs") != 0
            or row.get("loginControls") != []
            or row.get("abnormalPromptIcons") != 0
            for row in routes
        )
        or dashboard
        != {
            "circularRadarAndFiveClickableFormulas": True,
            "dualAxisTrendExact": True,
            "executiveDigestPresent": True,
            "missionImageAbsent": True,
            "threeUrlBackedRangesExact": True,
        }
        or insights
        != {
            "automationAttributionBoundaryVisible": True,
            "caseReferencesMethodOnly": True,
            "controlledEvidence": True,
            "eightPersonaGroupsAndQuarterAssignmentsExact": True,
            "fourUrlBackedThemeTabsExact": True,
            "geoAndAutomationCountsExact": True,
            "legacyDarkPanelsAbsent": True,
            "quarterWindowAndCountsExact": True,
        }
        or not reports_valid
        or browser_errors != []
        or same_origin_failures != []
        or external_requests != []
        or summary.get("status") != "passed"
        or summary.get("evaluated_pages") != len(routes)
        or summary.get("browser_error_count") != len(browser_errors)
        or summary.get("same_origin_http_failure_count")
        != len(same_origin_failures)
        or summary.get("external_request_count") != len(external_requests)
    ):
        _fail("public_browser_upstream_binding_mismatch")
    assert isinstance(dataset_versions, dict)
    return {key: str(item) for key, item in dataset_versions.items()}, observed_at


def _reopen_upstream_evidence(
    *, root: Path, acceptance: Mapping[str, Any]
) -> dict[str, str]:
    sources = _object(acceptance.get("evidence_sources"), label="evidence_sources")
    if set(sources) != {
        "public_browser_receipt", "public_http_observation",
        "remote_promotion_receipt",
    }:
        _fail("evidence_sources_unexpected_fields")
    records: dict[str, str] = {}
    remote_record = _evidence_record(
        sources.get("remote_promotion_receipt"), label="remote_promotion_evidence"
    )
    http_record = _evidence_record(
        sources.get("public_http_observation"), label="public_http_evidence"
    )
    browser_record = _evidence_record(
        sources.get("public_browser_receipt"), label="public_browser_evidence"
    )
    _, _, remote = _read_evidence_json(
        root=root, record=remote_record, label="remote_promotion_evidence", canonical=True
    )
    _, _, http = _read_evidence_json(
        root=root, record=http_record, label="public_http_evidence", canonical=True
    )
    _, _, browser = _read_evidence_json(
        root=root, record=browser_record, label="public_browser_evidence", canonical=False
    )
    remote_observed_at = _validate_remote_promotion_v2(
        remote, acceptance=acceptance
    )
    dataset_versions, browser_observed_at = _validate_public_browser(
        browser, acceptance=acceptance
    )
    http_observed_at = _validate_public_http(
        http, acceptance=acceptance, dataset_versions=dataset_versions
    )
    if (
        http_observed_at < remote_observed_at
        or browser_observed_at < remote_observed_at
    ):
        _fail("public_acceptance_precedes_remote_promotion")
    remote_summary = _object(
        acceptance.get("remote_promotion_receipt"), label="remote_promotion_receipt"
    )
    if remote_summary.get("sha256") != remote_record.get("sha256"):
        _fail("remote_promotion_summary_sha256_mismatch")
    for name, record in (
        ("remote_promotion_receipt", remote_record),
        ("public_http_observation", http_record),
        ("public_browser_receipt", browser_record),
    ):
        records[name] = str(record["sha256"])
    return records


def validate_production_acceptance_document(
    value: Mapping[str, Any],
    *,
    expected_release_sha256: str | None = None,
    expected_packet_sha256: str | None = None,
    expected_permit_sha256: str | None = None,
    expected_remote_promotion_receipt_sha256: str | None = None,
    historical_v1_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        release_sha = control.require_sha256(
            value.get("release_sha256"), label="release_sha256"
        )
        accepted_value, _ = control.parse_utc(
            value.get("accepted_at_utc"), label="accepted_at_utc"
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    schema_version = value.get("schema_version")
    if schema_version not in {SCHEMA_VERSION, SCHEMA_VERSION_V2} or value.get("status") != STATUS:
        _fail("acceptance_contract_invalid")
    if schema_version == SCHEMA_VERSION:
        if historical_v1_receipt_sha256 not in HISTORICAL_V1_RECEIPT_SHA256S:
            _fail("legacy_v1_acceptance_not_exactly_allowlisted")
    elif "evidence_sources" not in value:
        _fail("v2_acceptance_evidence_sources_required")
    if value.get("evidence_grade") != "L4-authorized-live":
        _fail("evidence_grade_invalid")
    if expected_release_sha256 is not None:
        try:
            expected_release = control.require_sha256(
                expected_release_sha256, label="expected_release_sha256"
            )
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
        if release_sha != expected_release:
            _fail("release_binding_mismatch")
    try:
        normalized_site = packet_contract._site_url(value.get("site_url"))
    except packet_contract.PromotionPacketError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    if normalized_site != value.get("site_url"):
        _fail("site_url_noncanonical")
    data_release_id = value.get("data_release_id")
    if (
        not isinstance(data_release_id, str)
        or packet_contract.DATA_RELEASE_RE.fullmatch(data_release_id) is None
    ):
        _fail("data_release_id_invalid")
    data_pointer_sha: str | None = None
    data_inventory_sha: str | None = None
    data_file_count: int | None = None
    data_total_bytes: int | None = None
    if schema_version == SCHEMA_VERSION_V2:
        try:
            data_pointer_sha = control.require_sha256(
                value.get("data_pointer_sha256"), label="data_pointer_sha256"
            )
            data_inventory_sha = control.require_sha256(
                value.get("data_inventory_sha256"), label="data_inventory_sha256"
            )
            data_file_count = control.require_nonnegative_int(
                value.get("data_file_count"), label="data_file_count"
            )
            data_total_bytes = control.require_nonnegative_int(
                value.get("data_total_bytes"), label="data_total_bytes"
            )
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
        if data_file_count == 0 or data_total_bytes == 0:
            _fail("data_inventory_invalid")

    authorization = _object(value.get("authorization"), label="authorization")
    try:
        packet_sha = control.require_sha256(
            authorization.get("packet_sha256"), label="packet_sha256"
        )
        permit_sha = control.require_sha256(
            authorization.get("permit_sha256"), label="permit_sha256"
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    if authorization.get("user_authorized") is not True:
        _fail("authorization_invalid")
    for observed, expected, label in (
        (packet_sha, expected_packet_sha256, "packet_binding_mismatch"),
        (permit_sha, expected_permit_sha256, "permit_binding_mismatch"),
    ):
        if expected is not None:
            try:
                normalized_expected = control.require_sha256(
                    expected, label=f"expected_{label}"
                )
            except control.ReleaseControlError as exc:
                raise ProductionAcceptanceError(str(exc)) from exc
            if observed != normalized_expected:
                _fail(label)

    remote = _object(
        value.get("remote_promotion_receipt"), label="remote_promotion_receipt"
    )
    try:
        remote_sha = control.require_sha256(
            remote.get("sha256"), label="remote_promotion_receipt_sha256"
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    _acceptance_path(remote.get("path"), release_sha256=release_sha)
    if remote.get("status") != REMOTE_PROMOTION_STATUS:
        _fail("remote_promotion_receipt_status_invalid")
    if expected_remote_promotion_receipt_sha256 is not None:
        try:
            expected_remote_sha = control.require_sha256(
                expected_remote_promotion_receipt_sha256,
                label="expected_remote_promotion_receipt_sha256",
            )
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
        if remote_sha != expected_remote_sha:
            _fail("remote_promotion_receipt_binding_mismatch")

    rollback = _object(value.get("rollback"), label="rollback")
    try:
        rollback_release = control.require_sha256(
            rollback.get("target_release_sha256"),
            label="rollback_target_release_sha256",
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    if rollback.get("ready") is not True or rollback_release == release_sha:
        _fail("rollback_contract_invalid")
    rollback_data_release_id: str | None = None
    rollback_data_pointer_sha: str | None = None
    if schema_version == SCHEMA_VERSION_V2:
        rollback_data_release_id = rollback.get("target_data_release_id")
        if (
            not isinstance(rollback_data_release_id, str)
            or packet_contract.DATA_RELEASE_RE.fullmatch(rollback_data_release_id)
            is None
            or rollback_data_release_id == data_release_id
        ):
            _fail("rollback_data_release_invalid")
        try:
            rollback_data_pointer_sha = control.require_sha256(
                rollback.get("target_data_pointer_sha256"),
                label="rollback_target_data_pointer_sha256",
            )
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
        if rollback_data_pointer_sha == data_pointer_sha:
            _fail("rollback_data_pointer_invalid")

    container = _object(value.get("container"), label="container")
    if (
        container.get("release_sha256") != release_sha
        or container.get("health") != "healthy"
        or container.get("runtime_contract_verified") is not True
        or container.get("restart_count") != 0
    ):
        _fail("container_contract_invalid")
    data_mount = container.get("data_mount")
    if data_mount is None:
        if schema_version == SCHEMA_VERSION_V2:
            _fail("container_data_mount_required")
        expected_mount_count = 0
    else:
        mounted = _object(data_mount, label="container_data_mount")
        expected_data_mount = {
            "contract_version": "reddit_voc_data_mount_v1",
            "type": "bind",
            "source": "/opt/reddit-voc-insights-data",
            "destination": "/srv/reddit-voc-data",
            "read_only": True,
            "propagation": "rprivate",
        }
        if dict(mounted) != expected_data_mount:
            _fail("container_data_mount_invalid")
        expected_mount_count = 1
    optional_container_contract = {
        "mount_count": expected_mount_count,
        "read_only_rootfs": True,
        "user": "101:101",
    }
    for name, expected in optional_container_contract.items():
        if name in container and container.get(name) != expected:
            _fail(f"container_{name}_invalid")

    public_http = _object(value.get("public_http"), label="public_http")
    for name in ("health_http_200", "release_marker_verified", "tls_verified"):
        if public_http.get(name) is not True:
            _fail(f"public_http_{name}_invalid")
    for name in ("public_artifact_200_count", "route_200_count", "security_404_count"):
        try:
            count = control.require_nonnegative_int(public_http.get(name), label=name)
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
        if count == 0:
            _fail(f"public_http_{name}_invalid")

    public_browser = _object(value.get("public_browser"), label="public_browser")
    if public_browser.get("status") != "passed":
        _fail("public_browser_status_invalid")
    for name in (
        "browser_error_count",
        "external_request_count",
        "same_origin_http_failure_count",
    ):
        if public_browser.get(name) != 0:
            _fail(f"public_browser_{name}_invalid")
    try:
        evaluated_pages = control.require_nonnegative_int(
            public_browser.get("evaluated_pages"), label="evaluated_pages"
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    if evaluated_pages == 0:
        _fail("public_browser_evaluated_pages_invalid")

    boundaries = _object(value.get("boundaries"), label="boundaries")
    _false_boundaries(boundaries)
    invariants = _object(value.get("invariants"), label="invariants")
    required_invariants: dict[str, object] = {
        "candidate_container_count": 0,
        "collector_health": "healthy",
        "collector_restart_count": 0,
        "database_stable": True,
        "new_release_checksums_verified": True,
        "one_shot_count": 0,
        "port_18339_listener_count": 0,
        "report_pointer_stable": True,
        "rollback_release_checksums_verified": True,
        "translation_health": "healthy",
        "translation_restart_count": 0,
    }
    for name, expected in required_invariants.items():
        if invariants.get(name) != expected:
            _fail(f"invariant_{name}_invalid")
    if not (
        invariants.get("running_container_inventory_stable") is True
        or invariants.get("running_container_count_stable") is True
    ):
        _fail("invariant_running_container_stability_invalid")
    for name in ("collector_id", "translation_id", "cron_sha256", "shared_nginx_sha256"):
        observed = invariants.get(name)
        try:
            control.require_sha256(observed, label=f"invariant_{name}")
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc

    data = value.get("data")
    if data is not None:
        data_object = _object(data, label="data")
        for name, count in data_object.items():
            try:
                control.require_nonnegative_int(count, label=f"data_{name}")
            except control.ReleaseControlError as exc:
                raise ProductionAcceptanceError(str(exc)) from exc
        required_counts = {
            "linked_comments",
            "posts",
            "quarantined_comments",
            "stored_comments",
            "unresolved_parent_comments",
        }
        if required_counts.issubset(data_object) and (
            data_object["linked_comments"]
            + data_object["unresolved_parent_comments"]
            + data_object["quarantined_comments"]
            != data_object["stored_comments"]
        ):
            _fail("data_comment_reconciliation_invalid")

    result: dict[str, Any] = {
        "accepted_at_utc": accepted_value,
        "data_release_id": data_release_id,
        "packet_sha256": packet_sha,
        "permit_sha256": permit_sha,
        "release_sha256": release_sha,
        "remote_promotion_receipt_sha256": remote_sha,
        "rollback_target_release_sha256": rollback_release,
        "schema_version": "reddit_voc_production_acceptance_validation_result_v1",
        "status": "passed",
    }
    if schema_version == SCHEMA_VERSION_V2:
        result.update(
            {
                "data_pointer_sha256": data_pointer_sha,
                "data_inventory_sha256": data_inventory_sha,
                "data_file_count": data_file_count,
                "data_total_bytes": data_total_bytes,
                "rollback_target_data_pointer_sha256": rollback_data_pointer_sha,
                "rollback_target_data_release_id": rollback_data_release_id,
                "schema_version": "reddit_voc_production_acceptance_validation_result_v2",
            }
        )
    return result


def validate_production_acceptance(
    *,
    artifact_root: Path,
    receipt_path: Path,
    expected_receipt_sha256: str,
    expected_release_sha256: str | None = None,
    expected_packet_sha256: str | None = None,
    expected_permit_sha256: str | None = None,
    expected_remote_promotion_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        _, payload, value = control.read_json(
            root=root,
            path=receipt_path,
            label="production_acceptance_receipt",
            expected_mode=0o600,
            expected_sha256=expected_receipt_sha256,
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    result = validate_production_acceptance_document(
        value,
        expected_release_sha256=expected_release_sha256,
        expected_packet_sha256=expected_packet_sha256,
        expected_permit_sha256=expected_permit_sha256,
        expected_remote_promotion_receipt_sha256=(
            expected_remote_promotion_receipt_sha256
        ),
        historical_v1_receipt_sha256=control.sha256_bytes(payload),
    )
    if value.get("schema_version") == SCHEMA_VERSION_V2:
        result["upstream_evidence"] = _reopen_upstream_evidence(
            root=root, acceptance=value
        )
        result["upstream_evidence_reopened"] = True
    else:
        result["upstream_evidence_reopened"] = False
    result["acceptance_receipt_sha256"] = control.sha256_bytes(payload)
    return result


def build_production_acceptance(
    *,
    artifact_root: Path,
    output: Path,
    source_receipt_path: Path | None = None,
    receipt: Mapping[str, Any] | None = None,
    expected_release_sha256: str | None = None,
    expected_packet_sha256: str | None = None,
    expected_permit_sha256: str | None = None,
    expected_remote_promotion_receipt_sha256: str | None = None,
    promotion_receipt_path: Path | None = None,
    public_http_observation_path: Path | None = None,
    expected_public_http_observation_sha256: str | None = None,
    public_browser_receipt_path: Path | None = None,
    expected_public_browser_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    if (source_receipt_path is None) == (receipt is None):
        _fail("exactly_one_acceptance_source_required")
    if source_receipt_path is not None:
        try:
            _, _, source_value = control.read_json(
                root=root,
                path=source_receipt_path,
                label="production_acceptance_source",
                expected_mode=None,
            )
        except control.ReleaseControlError as exc:
            raise ProductionAcceptanceError(str(exc)) from exc
    else:
        source_value = dict(receipt or {})
    if source_value.get("schema_version") == SCHEMA_VERSION:
        _fail("legacy_v1_acceptance_build_forbidden")
    if source_value.get("schema_version") == SCHEMA_VERSION_V2:
        required_sources = (
            promotion_receipt_path,
            expected_remote_promotion_receipt_sha256,
            public_http_observation_path,
            expected_public_http_observation_sha256,
            public_browser_receipt_path,
            expected_public_browser_receipt_sha256,
        )
        if any(item is None for item in required_sources):
            _fail("v2_acceptance_requires_three_bound_upstream_receipts")
        source_records: dict[str, dict[str, str]] = {}
        for name, path, digest in (
            (
                "remote_promotion_receipt",
                promotion_receipt_path,
                expected_remote_promotion_receipt_sha256,
            ),
            (
                "public_http_observation",
                public_http_observation_path,
                expected_public_http_observation_sha256,
            ),
            (
                "public_browser_receipt",
                public_browser_receipt_path,
                expected_public_browser_receipt_sha256,
            ),
        ):
            assert path is not None and digest is not None
            try:
                normalized_digest = control.require_sha256(
                    digest, label=f"expected_{name}_sha256"
                )
                relative, payload = control.read_file(
                    root=root,
                    path=path,
                    label=name,
                    expected_mode=0o600,
                )
            except control.ReleaseControlError as exc:
                raise ProductionAcceptanceError(str(exc)) from exc
            if control.sha256_bytes(payload) != normalized_digest:
                _fail(f"{name}_sha256_mismatch")
            source_records[name] = {
                "path": relative,
                "sha256": normalized_digest,
            }
        source_value["evidence_sources"] = source_records
    validation = validate_production_acceptance_document(
        source_value,
        expected_release_sha256=expected_release_sha256,
        expected_packet_sha256=expected_packet_sha256,
        expected_permit_sha256=expected_permit_sha256,
        expected_remote_promotion_receipt_sha256=(
            expected_remote_promotion_receipt_sha256
        ),
    )
    if source_value.get("schema_version") == SCHEMA_VERSION_V2:
        validation["upstream_evidence"] = _reopen_upstream_evidence(
            root=root, acceptance=source_value
        )
        validation["upstream_evidence_reopened"] = True
    try:
        publication_status = control.write_immutable(
            root=root,
            output=output,
            value=source_value,
            label="production_acceptance_receipt",
        )
    except control.ReleaseControlError as exc:
        raise ProductionAcceptanceError(str(exc)) from exc
    return {
        **validation,
        "acceptance_receipt_sha256": control.sha256_bytes(
            control.canonical_bytes(source_value)
        ),
        "publication_status": publication_status,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--expected-release-sha256")
    parser.add_argument("--expected-packet-sha256")
    parser.add_argument("--expected-permit-sha256")
    parser.add_argument("--expected-remote-promotion-receipt-sha256")
    parser.add_argument("--promotion-receipt", type=Path)
    parser.add_argument("--public-http-observation", type=Path)
    parser.add_argument("--expected-public-http-observation-sha256")
    parser.add_argument("--public-browser-receipt", type=Path)
    parser.add_argument("--expected-public-browser-receipt-sha256")
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    common = {
        "artifact_root": args.artifact_root,
        "expected_release_sha256": args.expected_release_sha256,
        "expected_packet_sha256": args.expected_packet_sha256,
        "expected_permit_sha256": args.expected_permit_sha256,
        "expected_remote_promotion_receipt_sha256": (
            args.expected_remote_promotion_receipt_sha256
        ),
        "promotion_receipt_path": args.promotion_receipt,
        "public_http_observation_path": args.public_http_observation,
        "expected_public_http_observation_sha256": (
            args.expected_public_http_observation_sha256
        ),
        "public_browser_receipt_path": args.public_browser_receipt,
        "expected_public_browser_receipt_sha256": (
            args.expected_public_browser_receipt_sha256
        ),
    }
    try:
        result = build_production_acceptance(
            **common,
            source_receipt_path=args.source_receipt,
            output=args.output,
        )
    except ProductionAcceptanceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
