from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.audit_insights_dist import (
    AuditError,
    CASE_STOCK_CONTRACTS,
    V3_INSIGHTS_SIDECAR_CONTRACTS,
    V3_INSIGHTS_SIDECAR_BYTES,
    V3_INSIGHTS_SIDECAR_MANIFEST_SHA256,
    V3_INSIGHTS_SIDECAR_SHA256,
    _v3_insights_sidecar,
    audit_dist,
    discover_contract,
    prepare_dist,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _file_contract(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": _sha(path)}


def _write_manifest(
    root: Path,
    *,
    dataset_version: str,
    files: list[str],
    extra: dict[str, object],
    name: str = "manifest.json",
) -> Path:
    path = root / name
    _write_json(
        path,
        {
            "schema_version": "fixture_manifest_v1",
            "dataset_version": dataset_version,
            "files": {relative: _file_contract(root / relative) for relative in files},
            **extra,
        },
    )
    return path


def _case_bundle(dist: Path) -> tuple[Path, Path]:
    case_root = dist / "data/cases"
    index_path = case_root / "case-index.v1.json"
    _write_json(
        index_path,
        {
            "schemaVersion": 1,
            "datasetVersion": "case_catalog_fixture_v1",
            "approvedDelta": [],
        },
    )
    manifest_path = case_root / "manifest.v1.json"
    _write_json(
        manifest_path,
        {
            "schemaVersion": 1,
            "datasetVersion": "case_catalog_fixture_v1",
            "generatedAt": "2026-07-15T00:00:00.000Z",
            "freshness": {"mode": "static"},
            "provenance": {
                "process": "manual_seed_plus_approved_static_delta",
                "networkSearch": False,
            },
            "seed": dict(CASE_STOCK_CONTRACTS["seed"]),
            "legacyUnverified": dict(CASE_STOCK_CONTRACTS["legacyUnverified"]),
            "approvedDelta": {
                "source": "versioned_static_index",
                "version": "approved_delta_fixture_v1",
                "count": 0,
                "contentSha256": sha256(b"[]").hexdigest(),
            },
            "index": {
                "path": "/data/cases/case-index.v1.json",
                "sha256": _sha(index_path),
            },
        },
    )
    return manifest_path, index_path


def _build_fixture(dist: Path, *, generation: str) -> dict[str, str]:
    versions = {
        "base": f"reddit_voc_site_snapshot_fixture_{generation}",
        "insights": f"reddit_voc_insights_fixture_{generation}",
        "reports": f"reddit_voc_reports_fixture_{generation}",
        "personas": f"reddit_voc_personas_fixture_{generation}",
    }
    data = dist / "data/reddit-voc"
    base = data / versions["base"]
    insights = data / versions["insights"] / "public"
    reports = data / versions["reports"] / "public"
    personas = data / versions["personas"]

    for name, payload in (
        ("aggregates-public.json", {"headline": {"posts": 1}}),
        ("posts-public.json", [{"post_id": "fixture-post", "author_pseudonym": None}]),
        ("comments-public.json", [{"comment_id": "fixture-comment", "author_pseudonym": None}]),
        ("tag-dictionary-public.json", {"rules": []}),
    ):
        _write_json(base / name, payload)
    base_lineage = "a" * 64
    base_manifest = _write_manifest(
        base,
        dataset_version=versions["base"],
        files=[
            "aggregates-public.json",
            "posts-public.json",
            "comments-public.json",
            "tag-dictionary-public.json",
        ],
        extra={
            "projection": {"audience": "public_ui"},
            "privacy": {"author_display": "suppressed"},
        },
        name="manifest-public.json",
    )

    _write_json(
        insights / "insights.json",
        {"dataset_version": versions["insights"], "risk_level": "high"},
    )
    _write_json(
        insights / "semantic-audit.json",
        {"schema_version": "fixture_audit_v1", "samples_included": False},
    )
    insights_lineage = "b" * 64
    insights_manifest = _write_manifest(
        insights,
        dataset_version=versions["insights"],
        files=["insights.json", "semantic-audit.json"],
        extra={
            "projection": {"audience": "public_ui"},
            "base_dataset_version": versions["base"],
            "base_manifest_sha256": base_lineage,
        },
    )

    report_index: dict[str, object] = {
        "schema_version": "fixture_report_index_v1",
        "dataset_version": versions["reports"],
        "current": {},
        "archive": {},
    }
    report_paths: list[str] = []
    dynamic_suffix = "2026-05" if generation == "v2" else "2026-06"
    for collection in ("current", "archive"):
        group = report_index[collection]
        assert isinstance(group, dict)
        for period in ("daily", "weekly", "monthly"):
            relative = (
                f"{collection}/{period}.json"
                if collection == "current"
                else f"{collection}/{period}-{dynamic_suffix}.json"
            )
            group[period] = {"path": relative, "period": period}
            report_paths.append(relative)
            _write_json(
                reports / relative,
                {
                    "schema_version": "fixture_report_v1",
                    "identity": {
                        "dataset_version": versions["reports"],
                        "period": period,
                    },
                },
            )
    _write_json(reports / "report-index.json", report_index)
    reports_manifest = _write_manifest(
        reports,
        dataset_version=versions["reports"],
        files=["report-index.json", *report_paths],
        extra={
            "projection": {"audience": "public_ui"},
            "base_dataset_version": versions["base"],
            "base_manifest_sha256": base_lineage,
            "insights_dataset_version": versions["insights"],
            "insights_manifest_sha256": insights_lineage,
        },
    )

    _write_json(
        personas / "personas.json",
        {"dataset_version": versions["personas"], "personas": []},
    )
    _write_json(
        personas / "persona-tags.json",
        {"dataset_version": versions["personas"], "assignments": []},
    )
    avatar = personas / "assets/fixture.svg"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n', encoding="utf-8")
    personas_manifest = _write_manifest(
        personas,
        dataset_version=versions["personas"],
        files=["personas.json", "persona-tags.json", "assets/fixture.svg"],
        extra={
            "base_dataset_version": versions["base"],
            "base_manifest_sha256": base_lineage,
            "insights_dataset_version": versions["insights"],
            "insights_manifest_sha256": insights_lineage,
            "boundaries": {
                "author_level_personas": False,
                "counts_are_content_entities_not_users": True,
                "derived_from_reddit_media": False,
                "identity_claim": False,
                "public_author_identifiers": False,
                "real_user_image": False,
                "synthetic_avatars": True,
            },
        },
    )

    case_manifest, case_index = _case_bundle(dist)
    pointer = {
        "schema_version": "reddit_voc_current_release_v1",
        "release_id": f"reddit_voc_release_fixture_{generation}",
        "generated_at_utc": "2026-07-15T00:00:00Z",
        "datasets": {
            "base": {
                "dataset_version": versions["base"],
                "manifest_path": f"data/reddit-voc/{versions['base']}/manifest-public.json",
                "public_manifest_sha256": _sha(base_manifest),
                "lineage_manifest_sha256": base_lineage,
            },
            "insights": {
                "dataset_version": versions["insights"],
                "manifest_path": f"data/reddit-voc/{versions['insights']}/public/manifest.json",
                "public_manifest_sha256": _sha(insights_manifest),
                "lineage_manifest_sha256": insights_lineage,
            },
            "reports": {
                "dataset_version": versions["reports"],
                "manifest_path": f"data/reddit-voc/{versions['reports']}/public/manifest.json",
                "public_manifest_sha256": _sha(reports_manifest),
                "lineage_manifest_sha256": "c" * 64,
            },
            "personas": {
                "dataset_version": versions["personas"],
                "manifest_path": f"data/reddit-voc/{versions['personas']}/manifest.json",
                "public_manifest_sha256": _sha(personas_manifest),
                "lineage_manifest_sha256": _sha(personas_manifest),
            },
        },
        "cases": {
            "dataset_version": "case_catalog_fixture_v1",
            "manifest_path": "data/cases/manifest.v1.json",
            "public_manifest_sha256": _sha(case_manifest),
            "index_path": "data/cases/case-index.v1.json",
            "index_sha256": _sha(case_index),
            "stock_content_preserved": True,
            "approved_delta_count": 0,
        },
        "boundaries": {
            "case_gallery_stock_preserved": True,
            "collector_isolation_required": True,
            "login_required": False,
        },
    }
    _write_json(data / "current-release.json", pointer)
    return versions


def _v3_boundaries() -> dict[str, bool]:
    return {
        "database_write": False,
        "deploy": False,
        "live_send": False,
        "production_unchanged": True,
        "provider_call": False,
        "remote_write": False,
    }


def _v3_coverage(source_snapshot_id: str, *, fixture_field: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "comparison_contract_basis": "owner_attested_dataset_scope_window",
        "comparison_contract_proven": True,
        "completeness_percent": 100,
        "coverage_attestation": {
            "attestation_basis": "data_owner_declaration",
            "completeness_percent": 100,
            "evidence_class": "owner_attested_not_crawler_proof",
            "source_snapshot_id": source_snapshot_id,
        },
        "data_owner_coverage_attestation_sha256": "e" * 64,
    }
    if fixture_field:
        value["fixture_only"] = False
    return value


def _v3_file_contract(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return {
            **_file_contract(path),
            "media_type": "image/svg+xml",
            "width": 512,
            "height": 512,
        }
    return {
        **_file_contract(path),
        "media_type": (
            "application/x-ndjson" if suffix == ".jsonl" else "application/json"
        ),
        "rows": 1,
    }


def _copy_v3_fixed_auxiliary_projections(dist: Path) -> None:
    source_root = (
        Path(__file__).resolve().parents[1]
        / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
    )
    contracts = {
        "reddit_voc_casebook_20260716_public_a1": ("manifest.json", "casebook.json"),
        "reddit_voc_brand_health_20260719_center_refresh_003": (
            "manifest.json",
            "brand-health.json",
        ),
        "reddit_voc_quarter_insights_20260719_center_refresh_003": (
            "manifest.json",
            "quarter-insights.json",
        ),
        "reddit_voc_v2-business-activation-e229fbf2901862918997": (
            "manifest.json",
            "activation.json",
        ),
    }
    for version, names in contracts.items():
        destination = dist / "data/reddit-voc" / version
        destination.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copyfile(source_root / version / name, destination / name)


def _build_v3_fixture(dist: Path) -> dict[str, str]:
    versions = _build_fixture(dist, generation="v3")
    _copy_v3_fixed_auxiliary_projections(dist)
    source_snapshot_id = "reddit_add_data_20260715_v1"
    data = dist / "data/reddit-voc"
    roots = {
        "base": data / versions["base"],
        "insights": data / versions["insights"] / "public",
        "reports": data / versions["reports"] / "public",
        "personas": data / versions["personas"],
    }

    base_files = {
        name: _file_contract(roots["base"] / name)
        for name in (
            "aggregates-public.json",
            "posts-public.json",
            "comments-public.json",
            "tag-dictionary-public.json",
        )
    }
    _write_json(
        roots["base"] / "manifest-public.json",
        {
            "schema_version": "reddit_voc_site_snapshot_manifest_v3",
            "dataset_version": versions["base"],
            "source_snapshot_id": source_snapshot_id,
            "status": "validated_candidate",
            "promotable": True,
            "privacy_safe_projection": True,
            "completeness_percent": 100,
            "completeness_basis": "data_owner_declaration",
            "consumption_status": "eligible_for_current_release_candidate_binding",
            "lineage_manifest_sha256": "a" * 64,
            "privacy": {
                "author_display": "suppressed",
                "stable_pseudonym_exposed": False,
            },
            "boundaries": _v3_boundaries(),
            "files": base_files,
        },
    )

    for path in sorted(roots["insights"].glob("*.json")):
        path.unlink()
    insights_lineage = "b" * 64
    _write_json(
        roots["insights"] / "insights.json",
        {
            "schema_version": "reddit_voc_insights_public_v3",
            "dataset_version": versions["insights"],
            "privacy_safe_projection": True,
            "source": {"source_snapshot_id": source_snapshot_id},
            "boundaries": _v3_boundaries(),
            **_v3_coverage(source_snapshot_id),
        },
    )
    _write_json(
        roots["insights"] / "validation-receipt.json",
        {
            "schema_version": "reddit_voc_insights_validation_receipt_v3",
            "status": "passed_candidate_only",
            "promotable": True,
            "deterministic_full_byte_replay": True,
            "bundle_manifest_sha256": insights_lineage,
            "boundaries": _v3_boundaries(),
            **_v3_coverage(source_snapshot_id),
        },
    )
    insights_files = {
        name: _file_contract(roots["insights"] / name)
        for name in ("insights.json", "validation-receipt.json")
    }
    _write_json(
        roots["insights"] / "manifest.json",
        {
            "schema_version": "reddit_voc_insights_public_manifest_v3",
            "dataset_version": versions["insights"],
            "source_snapshot_id": source_snapshot_id,
            "status": "validated_candidate",
            "promotable": True,
            "privacy_safe_projection": True,
            "consumption_status": "eligible_for_frontend_candidate_consumption",
            "independent_validation_status": "passed",
            "lineage_manifest_sha256": insights_lineage,
            "validation_receipt_sha256": insights_files["validation-receipt.json"]["sha256"],
            "boundaries": _v3_boundaries(),
            "files": insights_files,
            **_v3_coverage(source_snapshot_id),
        },
    )

    for path in sorted(roots["reports"].rglob("*.json"), reverse=True):
        path.unlink()
    reports_lineage = "c" * 64
    reports_index = {
        "schema_version": "reddit_voc_report_index_v3",
        "dataset_version": versions["reports"],
        "business_entry_count": 41,
        "business_history_index_path": "business-history-index.json",
        "current_entry_count": 3,
        "history_entry_count": 38,
        "source": {"source_snapshot_id": source_snapshot_id},
        "reports": {
            grain: {
                "grain": grain,
                "artifact_path": f"current/{grain}.json",
                "period": {
                    "daily": {
                        "grain": "daily", "is_complete": True,
                        "period_id": "daily:2026-07-18:2026-07-19",
                        "start": "2026-07-18", "end": "2026-07-19",
                    },
                    "weekly": {
                        "grain": "weekly", "is_complete": True,
                        "period_id": "weekly:2026-07-13:2026-07-20",
                        "start": "2026-07-13", "end": "2026-07-20",
                    },
                    "monthly": {
                        "grain": "monthly", "is_complete": True,
                        "period_id": "monthly:2026-07-01:2026-08-01",
                        "start": "2026-07-01", "end": "2026-08-01",
                    },
                }[grain],
            }
            for grain in ("daily", "weekly", "monthly")
        },
        **_v3_coverage(source_snapshot_id, fixture_field=False),
    }
    _write_json(roots["reports"] / "report-index.json", reports_index)
    for grain in ("daily", "weekly", "monthly"):
        common = {
            "schema_version": "reddit_voc_report_v3",
            "grain": grain,
            "source": {"source_snapshot_id": source_snapshot_id},
            "boundaries": _v3_boundaries(),
            **_v3_coverage(source_snapshot_id),
        }
        _write_json(
            roots["reports"] / f"current/{grain}.json",
            {
                **common,
                "artifact_role": "latest_complete_calendar_period",
                "comparison_archive_path": f"archive/{grain}.json",
            },
        )
        _write_json(
            roots["reports"] / f"archive/{grain}.json",
            {**common, "artifact_role": "internal_comparison_archive"},
        )
    history_reports: dict[str, list[dict[str, object]]] = {
        "daily": [],
        "weekly": [],
        "monthly": [],
    }
    history_paths: list[str] = []
    current_starts = {
        "daily": date(2026, 7, 18),
        "weekly": date(2026, 7, 13),
        "monthly": date(2026, 7, 1),
    }
    for grain, count in {"daily": 14, "weekly": 12, "monthly": 12}.items():
        end = current_starts[grain]
        for _ in range(count):
            if grain == "daily":
                start = end - timedelta(days=1)
            elif grain == "weekly":
                start = end - timedelta(days=7)
            else:
                start = date(
                    end.year - (1 if end.month == 1 else 0),
                    12 if end.month == 1 else end.month - 1,
                    1,
                )
            period = {
                "grain": grain,
                "is_complete": True,
                "period_id": f"{grain}:{start.isoformat()}:{end.isoformat()}",
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
            if grain == "daily":
                relative = f"history/daily/{start.isoformat()}.json"
            elif grain == "weekly":
                relative = (
                    f"history/weekly/{start.isoformat()}_"
                    f"{(end - timedelta(days=1)).isoformat()}.json"
                )
            else:
                relative = f"history/monthly/{start:%Y-%m}.json"
            _write_json(
                roots["reports"] / relative,
                {
                    "schema_version": "reddit_voc_report_v3",
                    "artifact_role": "historical_complete_calendar_period",
                    "business_entry_visible": True,
                    "entry_label": "历史完整周期",
                    "grain": grain,
                    "period": period,
                    "source": {"source_snapshot_id": source_snapshot_id},
                    "boundaries": _v3_boundaries(),
                    **_v3_coverage(source_snapshot_id),
                },
            )
            history_paths.append(relative)
            history_reports[grain].append(
                {
                    "artifact_path": relative,
                    "artifact_sha256": _sha(roots["reports"] / relative),
                    "entry_label": "历史完整周期",
                    "grain": grain,
                    "period": period,
                }
            )
            end = start
    _write_json(
        roots["reports"] / "business-history-index.json",
        {
            "schema_version": "reddit_voc_business_history_index_v1",
            "dataset_version": versions["reports"],
            "history_entry_count": 38,
            "total_business_entry_count": 41,
            "latest_complete_period_excluded": True,
            "limits": {"daily": 14, "weekly": 12, "monthly": 12},
            "order": "newest_first",
            "reports": history_reports,
            "source": {"source_snapshot_id": source_snapshot_id},
            **_v3_coverage(source_snapshot_id, fixture_field=False),
        },
    )
    _write_json(
        roots["reports"] / "validation-receipt.json",
        {
            "schema_version": "reddit_voc_reports_validation_receipt_v3",
            "status": "passed_candidate_only",
            "promotable": True,
            "deterministic_full_byte_replay": True,
            "bundle_manifest_sha256": reports_lineage,
            "business_entry_count": 41,
            "history_report_count": 38,
            "report_count": 44,
            "boundaries": _v3_boundaries(),
            **_v3_coverage(source_snapshot_id),
        },
    )
    reports_names = (
        "report-index.json",
        "business-history-index.json",
        "validation-receipt.json",
        "current/daily.json",
        "current/weekly.json",
        "current/monthly.json",
        "archive/daily.json",
        "archive/weekly.json",
        "archive/monthly.json",
        *history_paths,
    )
    reports_files = {
        name: _file_contract(roots["reports"] / name) for name in reports_names
    }
    _write_json(
        roots["reports"] / "manifest.json",
        {
            "schema_version": "reddit_voc_reports_public_manifest_v3",
            "dataset_version": versions["reports"],
            "source_snapshot_id": source_snapshot_id,
            "status": "validated_candidate",
            "promotable": True,
            "privacy_safe_projection": True,
            "consumption_status": "eligible_for_frontend_candidate_consumption",
            "independent_validation_status": "passed",
            "lineage_manifest_sha256": reports_lineage,
            "validation_receipt_sha256": reports_files["validation-receipt.json"]["sha256"],
            "business_entry_count": 41,
            "history_report_count": 38,
            "report_count": 44,
            "contract_extensions": ["reddit_voc_business_history_index_v1"],
            "boundaries": _v3_boundaries(),
            "files": reports_files,
            **_v3_coverage(source_snapshot_id),
        },
    )

    for path in sorted(roots["personas"].rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
    persona_json = {
        "personas.json": {
            "schema_version": "reddit_voc_personas_v3",
            "snapshot_id": versions["personas"],
            "persona_cohort_count": 8,
            "personas": [],
        },
        "persona-tags.json": {
            "schema_version": "reddit_voc_persona_cohort_assignments_v1",
            "snapshot_id": versions["personas"],
            "assignments": [],
        },
        "persona-atomic-catalog.json": {
            "schema_version": "reddit_voc_persona_atomic_catalog_v1",
            "snapshot_id": versions["personas"],
            "personas": [],
        },
        "persona-cohort-bridge.json": {
            "schema_version": "reddit_voc_persona_cohort_bridge_v1",
            "snapshot_id": versions["personas"],
            "cohorts": [],
        },
    }
    for name, value in persona_json.items():
        _write_json(roots["personas"] / name, value)
    atomic_path = roots["personas"] / "persona-atomic-facts.jsonl"
    _write_json(
        atomic_path,
        {
            "schema_version": "reddit_voc_persona_atomic_fact_v1",
            "snapshot_id": versions["personas"],
            "author_pseudonym": None,
        },
    )
    avatar_names = (
        "persona-competitor-comparer.svg",
        "persona-explicit-advocate.svg",
        "persona-fallback-neutral.svg",
        "persona-fit-output-optimizer.svg",
        "persona-operations-troubleshooter.svg",
        "persona-product-evaluator.svg",
        "persona-purchase-decision.svg",
        "persona-service-support-seeker.svg",
        "persona-work-scenario.svg",
    )
    for name in avatar_names:
        path = roots["personas"] / "assets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n', encoding="utf-8")
    persona_names = (*persona_json, "persona-atomic-facts.jsonl", *(f"assets/{name}" for name in avatar_names))
    persona_files = {
        name: _v3_file_contract(roots["personas"] / name) for name in persona_names
    }
    _write_json(
        roots["personas"] / "manifest.json",
        {
            "schema_version": "reddit_voc_personas_manifest_v3",
            "snapshot_id": versions["personas"],
            "governed_signal_source_snapshot_id": source_snapshot_id,
            "status": "candidate_built",
            "consumption_status": "eligible_for_downstream_consumption",
            "promotable": True,
            "upstream": {
                "consumption_status": "eligible_for_downstream_consumption",
                "promotable": True,
            },
            "boundaries": {
                **_v3_boundaries(),
                "author_level_personas": False,
                "counts_are_content_entities_not_users": True,
                "demographics_supported": False,
                "population_share_supported": False,
                "real_user_images": False,
            },
            "files": persona_files,
        },
    )

    pointer_path = data / "current-release.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    lineages = {
        "base": "a" * 64,
        "insights": insights_lineage,
        "reports": reports_lineage,
        "personas": _sha(roots["personas"] / "manifest.json"),
    }
    for key, root in roots.items():
        manifest_name = "manifest-public.json" if key == "base" else "manifest.json"
        manifest_path = root / manifest_name
        pointer["datasets"][key]["public_manifest_sha256"] = _sha(manifest_path)
        pointer["datasets"][key]["lineage_manifest_sha256"] = lineages[key]
    _write_json(pointer_path, pointer)
    return versions


def _contract(dist: Path, versions: dict[str, str]):
    return discover_contract(
        dist,
        base_version=versions["base"],
        insights_version=versions["insights"],
        reports_version=versions["reports"],
        personas_version=versions["personas"],
        current_release_path="data/reddit-voc/current-release.json",
    )


class InsightsDistAuditTests(unittest.TestCase):
    def _attach_stylesheet(self, dist: Path, css: str) -> Path:
        stylesheet = dist / "assets/index-test.css"
        stylesheet.parent.mkdir(parents=True, exist_ok=True)
        stylesheet.write_text(css, encoding="utf-8")
        (dist / "index.html").write_text(
            '<!doctype html><link rel="stylesheet" href="/assets/index-test.css">',
            encoding="utf-8",
        )
        return stylesheet

    def test_compatible_v1_bundle_passes(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v1")
            audit_dist(dist, _contract(dist, versions))

    def test_compiled_tailwind_stylesheet_passes(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v1")
            self._attach_stylesheet(
                dist,
                ".flex{display:flex}.grid{display:grid}.hidden{display:none}",
            )

            audit_dist(dist, _contract(dist, versions))

    def test_raw_tailwind_directives_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v1")
            self._attach_stylesheet(
                dist,
                "@tailwind base;@tailwind components;@tailwind utilities;",
            )

            with self.assertRaisesRegex(AuditError, "unresolved Tailwind directive"):
                audit_dist(dist, _contract(dist, versions))

    def test_missing_compiled_layout_utility_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v1")
            self._attach_stylesheet(
                dist,
                ".flex{display:flex}.grid{display:grid}",
            )

            with self.assertRaisesRegex(AuditError, "missing required layout utilities"):
                audit_dist(dist, _contract(dist, versions))

    def test_synthetic_v2_dynamic_report_paths_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v2")
            audit_dist(dist, _contract(dist, versions))

    def test_coordinated_v3_bundle_passes_without_legacy_semantic_audit(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            contract = _contract(dist, versions)
            insights_root = dist / f"data/reddit-voc/{versions['insights']}/public"
            self.assertFalse((insights_root / "semantic-audit.json").exists())
            self.assertEqual(len(contract.public_ndjson_files), 1)
            audit_dist(dist, contract)

    def test_g5_translated_base_requires_exact_admission_receipt(self) -> None:
        project = Path(__file__).resolve().parents[1]
        root = (
            project
            / "tmp/reddit-voc-v3/p2e-freshness-automation-20260810"
            / "g5-local-public-candidate"
        )
        dist = root / "release-dist-v4"
        kwargs = {
            "base_version": "reddit_voc_site_snapshot_20260810_g4t_merged_v1",
            "insights_version": "reddit_voc_insights_20260810_v3_13ef45e02dce_r93deea839dd7",
            "reports_version": "reddit_voc_reports_20260810_v3_13ef45e02dce_history6_observed_comparisons",
            "personas_version": "reddit_voc_personas_20260810_daily_v1",
            "current_release_path": "data/reddit-voc/current-release.json",
        }
        with self.assertRaisesRegex(AuditError, "base V3 public files contract mismatch"):
            discover_contract(dist, **kwargs)

        contract = discover_contract(
            dist,
            translation_admission_receipt=(
                root / "receipts/g5-local-public-candidate-admission.json"
            ),
            **kwargs,
        )
        self.assertEqual(
            contract.release_id, "reddit_voc_release_20260810_g5_local_candidate_v2"
        )
        self.assertIn(
            PurePosixPath(
                "data/reddit-voc/reddit_voc_site_snapshot_20260810_g4t_merged_v1/"
                "post-translations-public.json"
            ),
            contract.allowed_data_files,
        )

    def test_mixed_v3_and_legacy_manifests_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            personas_root = dist / f"data/reddit-voc/{versions['personas']}"
            manifest_path = personas_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = "fixture_manifest_v2"
            manifest["dataset_version"] = versions["personas"]
            _write_json(manifest_path, manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["personas"]["public_manifest_sha256"] = _sha(manifest_path)
            pointer["datasets"]["personas"]["lineage_manifest_sha256"] = _sha(manifest_path)
            _write_json(pointer_path, pointer)
            with self.assertRaisesRegex(AuditError, "all four V3 datasets"):
                _contract(dist, versions)

    def test_v3_reports_reject_any_extra_declared_file(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            reports_root = dist / f"data/reddit-voc/{versions['reports']}/public"
            extra_path = reports_root / "archive/extra.json"
            _write_json(extra_path, {"schema_version": "unreviewed"})
            manifest_path = reports_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["archive/extra.json"] = _file_contract(extra_path)
            _write_json(manifest_path, manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["reports"]["public_manifest_sha256"] = _sha(manifest_path)
            _write_json(pointer_path, pointer)
            with self.assertRaisesRegex(AuditError, "reports V3 public files contract mismatch"):
                _contract(dist, versions)

    def test_v3_reports_reject_rehashed_history_period_id_drift(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            reports_root = dist / f"data/reddit-voc/{versions['reports']}/public"
            history_index_path = reports_root / "business-history-index.json"
            history_index = json.loads(history_index_path.read_text(encoding="utf-8"))
            entry = history_index["reports"]["daily"][0]
            report_path = reports_root / entry["artifact_path"]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            entry["period"]["period_id"] = "daily:drifted-period-id"
            report["period"] = entry["period"]
            _write_json(report_path, report)
            entry["artifact_sha256"] = _sha(report_path)
            _write_json(history_index_path, history_index)
            manifest_path = reports_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][entry["artifact_path"]] = _file_contract(report_path)
            manifest["files"]["business-history-index.json"] = _file_contract(history_index_path)
            _write_json(manifest_path, manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["reports"]["public_manifest_sha256"] = _sha(manifest_path)
            _write_json(pointer_path, pointer)

            with self.assertRaisesRegex(AuditError, "business history sequence"):
                _contract(dist, versions)

    def test_v3_persona_requires_snapshot_id_not_dataset_version(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            manifest_path = dist / f"data/reddit-voc/{versions['personas']}/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["snapshot_id"] = "reddit_voc_personas_different_v3"
            manifest["dataset_version"] = versions["personas"]
            _write_json(manifest_path, manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["personas"]["public_manifest_sha256"] = _sha(manifest_path)
            pointer["datasets"]["personas"]["lineage_manifest_sha256"] = _sha(manifest_path)
            _write_json(pointer_path, pointer)
            with self.assertRaisesRegex(AuditError, "snapshot_id does not match"):
                _contract(dist, versions)

    def test_v3_unreviewed_insights_sidecar_is_not_allowlisted(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            sidecar = (
                dist
                / f"data/reddit-voc/{versions['insights']}/public/public-validation-receipt.json"
            )
            _write_json(sidecar, {"status": "unreviewed"})
            contract = _contract(dist, versions)
            with self.assertRaisesRegex(AuditError, "allowlist mismatch"):
                audit_dist(dist, contract)

    def test_v3_base_non_null_author_pseudonym_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            base_root = dist / f"data/reddit-voc/{versions['base']}"
            posts_path = base_root / "posts-public.json"
            _write_json(
                posts_path,
                [{"post_id": "fixture-post", "author_pseudonym": "stable-link"}],
            )
            manifest_path = base_root / "manifest-public.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["posts-public.json"] = _file_contract(posts_path)
            _write_json(manifest_path, manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["base"]["public_manifest_sha256"] = _sha(manifest_path)
            _write_json(pointer_path, pointer)
            contract = _contract(dist, versions)
            with self.assertRaisesRegex(AuditError, "public author linkage remained"):
                audit_dist(dist, contract)

    def test_reviewed_v3_insights_sidecar_contract_is_exact(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            root = PurePosixPath(
                "data/reddit-voc/reddit_voc_insights_fixture_v3/public"
            )
            sidecar = dist.joinpath(*root.parts) / "public-validation-receipt.json"
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_bytes(b"x" * V3_INSIGHTS_SIDECAR_BYTES)
            with patch(
                "scripts.audit_insights_dist._file_sha256",
                return_value=V3_INSIGHTS_SIDECAR_SHA256,
            ):
                self.assertEqual(
                    _v3_insights_sidecar(
                        dist,
                        root,
                        manifest_sha256=V3_INSIGHTS_SIDECAR_MANIFEST_SHA256,
                    ),
                    root / "public-validation-receipt.json",
                )
            sidecar.write_bytes(b"x" * (V3_INSIGHTS_SIDECAR_BYTES - 1))
            with self.assertRaisesRegex(AuditError, "sidecar mismatch"):
                _v3_insights_sidecar(
                    dist,
                    root,
                    manifest_sha256=V3_INSIGHTS_SIDECAR_MANIFEST_SHA256,
                )

    def test_current_v3_insights_sidecar_contract_is_preserved(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            root = PurePosixPath(
                "data/reddit-voc/reddit_voc_insights_current_v3/public"
            )
            current_manifest_sha = (
                "e92d8b4e8a65a451af48cdbc3fe946198187b9239fa3e8f04c9b25b82fb4be2f"
            )
            contract = V3_INSIGHTS_SIDECAR_CONTRACTS[current_manifest_sha]
            sidecar = dist.joinpath(*root.parts) / "public-validation-receipt.json"
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_bytes(b"x" * contract["bytes"])
            with patch(
                "scripts.audit_insights_dist._file_sha256",
                return_value=contract["sha256"],
            ):
                self.assertEqual(
                    _v3_insights_sidecar(
                        dist,
                        root,
                        manifest_sha256=current_manifest_sha,
                    ),
                    root / "public-validation-receipt.json",
                )

    def test_unreviewed_v3_insights_sidecar_contract_is_not_admitted(self) -> None:
        with TemporaryDirectory() as temporary:
            self.assertIsNone(
                _v3_insights_sidecar(
                    Path(temporary),
                    PurePosixPath("data/reddit-voc/unreviewed/public"),
                    manifest_sha256="0" * 64,
                )
            )

    def test_v3_prepare_dist_preserves_only_fixed_auxiliary_projection_shape(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            contract = _contract(dist, versions)
            fixed = {
                dist
                / "data/reddit-voc/reddit_voc_casebook_20260716_public_a1/manifest.json",
                dist
                / "data/reddit-voc/reddit_voc_casebook_20260716_public_a1/casebook.json",
                dist
                / "data/reddit-voc/reddit_voc_brand_health_20260719_center_refresh_003/manifest.json",
                dist
                / "data/reddit-voc/reddit_voc_brand_health_20260719_center_refresh_003/brand-health.json",
                dist
                / "data/reddit-voc/reddit_voc_quarter_insights_20260719_center_refresh_003/manifest.json",
                dist
                / "data/reddit-voc/reddit_voc_quarter_insights_20260719_center_refresh_003/quarter-insights.json",
                dist
                / "data/reddit-voc/reddit_voc_v2-business-activation-e229fbf2901862918997/manifest.json",
                dist
                / "data/reddit-voc/reddit_voc_v2-business-activation-e229fbf2901862918997/activation.json",
            }
            extra_inside_fixed_root = (
                dist
                / "data/reddit-voc/reddit_voc_casebook_20260716_public_a1/unreviewed.json"
            )
            extra_projection = (
                dist
                / "data/reddit-voc/reddit_voc_brand_health_unreviewed/manifest.json"
            )
            _write_json(extra_inside_fixed_root, {"status": "unreviewed"})
            _write_json(extra_projection, {"status": "unreviewed"})
            prepare_dist(dist, contract)
            self.assertTrue(all(path.is_file() for path in fixed))
            self.assertFalse(extra_inside_fixed_root.exists())
            self.assertFalse(extra_projection.exists())
            audit_dist(dist, contract)

    def test_v3_fixed_auxiliary_hash_drift_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_v3_fixture(dist)
            casebook = (
                dist
                / "data/reddit-voc/reddit_voc_casebook_20260716_public_a1/casebook.json"
            )
            _write_json(casebook, {"schema_version": "tampered"})
            with self.assertRaisesRegex(AuditError, "auxiliary projection data contract mismatch"):
                _contract(dist, versions)

    def test_prepare_removes_private_and_stale_data_only_inside_dist(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v2")
            private = dist / f"data/reddit-voc/{versions['base']}/posts.json"
            _write_json(private, [{"private": True}])
            stale = dist / "data/reddit-voc/reddit_voc_site_snapshot_stale_v1/posts.json"
            _write_json(stale, [])
            foreign = dist / "data/private/raw.json"
            _write_json(foreign, {"private": True})
            contract = _contract(dist, versions)
            with self.assertRaises(AuditError):
                audit_dist(dist, contract)
            prepare_dist(dist, contract)
            self.assertFalse(private.exists())
            self.assertFalse(stale.exists())
            self.assertFalse(foreign.exists())
            audit_dist(dist, contract)

    def test_pointer_manifest_sha_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v2")
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["base"]["public_manifest_sha256"] = "f" * 64
            _write_json(pointer_path, pointer)
            with self.assertRaisesRegex(AuditError, "manifest SHA-256 mismatch"):
                _contract(dist, versions)

    def test_login_or_collector_boundary_change_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v2")
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["boundaries"]["login_required"] = True
            _write_json(pointer_path, pointer)
            with self.assertRaisesRegex(AuditError, "boundaries are unsafe"):
                _contract(dist, versions)

    def test_case_stock_change_fails_even_when_pointer_is_rehashed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v2")
            case_manifest_path = dist / "data/cases/manifest.v1.json"
            case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
            case_manifest["seed"]["count"] = 39
            _write_json(case_manifest_path, case_manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["cases"]["public_manifest_sha256"] = _sha(case_manifest_path)
            _write_json(pointer_path, pointer)
            with self.assertRaisesRegex(AuditError, "case stock contract changed"):
                _contract(dist, versions)

    def test_non_null_public_author_linkage_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            dist = Path(temporary)
            versions = _build_fixture(dist, generation="v2")
            base = dist / f"data/reddit-voc/{versions['base']}"
            posts_path = base / "posts-public.json"
            _write_json(posts_path, [{"post_id": "fixture-post", "author_pseudonym": "unsafe"}])
            manifest_path = base / "manifest-public.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["posts-public.json"] = _file_contract(posts_path)
            _write_json(manifest_path, manifest)
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["base"]["public_manifest_sha256"] = _sha(manifest_path)
            _write_json(pointer_path, pointer)
            contract = _contract(dist, versions)
            with self.assertRaisesRegex(AuditError, "public author linkage remained"):
                audit_dist(dist, contract)


if __name__ == "__main__":
    unittest.main()
