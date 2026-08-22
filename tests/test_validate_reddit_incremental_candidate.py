from __future__ import annotations

from contextlib import redirect_stderr
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any
import unittest

from scripts.validate_reddit_incremental_candidate import (
    IncrementalCandidateValidationError,
    _validate_base,
    main,
    validate_candidate,
    write_immutable_receipt,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _compact_sha(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _add_payload(directory: Path, name: str, payload: str) -> dict[str, object]:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return {"bytes": path.stat().st_size, "sha256": _sha(path)}


def _side_effect_boundaries(*, personas: bool = False) -> dict[str, object]:
    value: dict[str, object] = {
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "deploy": False,
        "independent_human_review": False,
        "production_unchanged": True,
    }
    if personas:
        value.update(
            {
                "webhook_send": False,
                "schedule_change": False,
                "synthetic_avatars": True,
                "real_user_image": False,
            }
        )
    return value


class IncrementalCandidateValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.versions = {
            "base": "reddit_voc_site_snapshot_20260716_fixture",
            "insights": "reddit_voc_insights_20260716_fixture",
            "reports": "reddit_voc_reports_20260716_fixture",
            "personas": "reddit_voc_personas_20260716_fixture",
        }
        self.private = {
            layer: self.root / "candidate" / layer / version
            for layer, version in self.versions.items()
        }
        self.public = self.root / "public"
        self.frontend_dist = self.root / "candidate/frontend/dist"
        self.release_metadata = (
            self.root / "candidate/frontend/release/release-manifest.json"
        )
        self.base_receipt = self.root / "candidate/base-receipt.json"
        self.analytics_receipt = self.root / "candidate/analytics-receipt.json"
        self.personas_receipt = self.root / "candidate/personas-receipt.json"
        self.freeze_path = self.root / "candidate/input-freeze.json"
        self._write_private_layers()
        self._write_receipts()
        self._write_freeze()
        self._write_public_bundle()
        self._write_frontend_release()

    def _write_private_layers(self) -> None:
        base_dir = self.private["base"]
        base_files = {"payload.json": _add_payload(base_dir, "payload.json", "{}\n")}
        self.base_manifest = {
            "schema_version": "reddit_voc_site_snapshot_manifest_v1",
            "dataset_version": self.versions["base"],
            "all_checks_passed": True,
            "checks": {"fixture": True},
            "production_unchanged": True,
            "provider_call": False,
            "live_send": False,
            "analysis": {"provider_call": False},
            "source_boundaries": {
                "tencent_v2_search_hydrated": {
                    "admission_status": "passed_with_partial_comment_coverage",
                    "target_count": 3,
                    "target_lf_sha256": "a" * 64,
                    "admitted_posts": 2,
                    "admitted_observed_comments": 7,
                    "lineage_gap_count": 1,
                    "lineage_gap_lf_sha256": "b" * 64,
                    "snapshot_sha256": "c" * 64,
                    "comment_coverage_debt": {
                        "cursor_outstanding": 2,
                        "page_pagination_outstanding": 3,
                        "partial_threads": 2,
                    },
                    "provider_call": False,
                    "database_write": False,
                    "live_send": False,
                    "production_merge": False,
                }
            },
            "fusion_accounting": {
                "coverage_debt_is_not_zero_filled": True,
                "v2_comment_coverage_debt": {
                    "cursor_outstanding": 2,
                    "page_pagination_outstanding": 3,
                    "partial_threads": 2,
                },
            },
            "canonical_counts": {
                "posts": 10,
                "stored_comments": 20,
                "linked_comments": 19,
                "quarantined_comments": 1,
            },
            "files": base_files,
        }
        _write_json(base_dir / "manifest.json", self.base_manifest)
        self.base_sha = _sha(base_dir / "manifest.json")

        insights_dir = self.private["insights"]
        insights_files = {
            "insights.json": _add_payload(insights_dir, "insights.json", "{}\n")
        }
        self.insights_manifest = {
            "schema_version": "reddit_voc_insights_manifest_v1",
            "dataset_version": self.versions["insights"],
            "base_dataset_version": self.versions["base"],
            "base_manifest_sha256": self.base_sha,
            "status": "passed_provisional_risk_threshold",
            "boundaries": _side_effect_boundaries(),
            "files": insights_files,
        }
        _write_json(insights_dir / "manifest.json", self.insights_manifest)
        self.insights_sha = _sha(insights_dir / "manifest.json")

        reports_dir = self.private["reports"]
        reports_files = {
            "report-index.json": _add_payload(
                reports_dir, "report-index.json", "{}\n"
            )
        }
        report_boundaries = _side_effect_boundaries()
        report_boundaries.update({"webhook_send": False, "schedule_change": False})
        self.reports_manifest = {
            "schema_version": "reddit_voc_reports_manifest_v1",
            "dataset_version": self.versions["reports"],
            "base_dataset_version": self.versions["base"],
            "base_manifest_sha256": self.base_sha,
            "insights_dataset_version": self.versions["insights"],
            "insights_manifest_sha256": self.insights_sha,
            "report_count": 6,
            "status": "passed_provisional_risk_threshold",
            "boundaries": report_boundaries,
            "files": reports_files,
        }
        _write_json(reports_dir / "manifest.json", self.reports_manifest)
        self.reports_sha = _sha(reports_dir / "manifest.json")

        personas_dir = self.private["personas"]
        persona_files = {
            "personas.json": _add_payload(personas_dir, "personas.json", "{}\n")
        }
        self.personas_manifest = {
            "schema_version": "reddit_voc_personas_manifest_v1",
            "dataset_version": self.versions["personas"],
            "base_dataset_version": self.versions["base"],
            "base_manifest_sha256": self.base_sha,
            "insights_dataset_version": self.versions["insights"],
            "insights_manifest_sha256": self.insights_sha,
            "persona_count": 2,
            "assignment_count": 4,
            "boundaries": _side_effect_boundaries(personas=True),
            "files": persona_files,
        }
        _write_json(personas_dir / "manifest.json", self.personas_manifest)
        self.personas_sha = _sha(personas_dir / "manifest.json")

    def _write_receipts(self) -> None:
        base_receipt = {
            "schema_version": "reddit_voc_site_snapshot_validation_v2",
            "status": "passed_release_candidate",
            "release_candidate": True,
            "dataset_version": self.versions["base"],
            "checks": {"fixture": True},
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "deploy": False,
            "counts": {
                "posts": 10,
                "stored_comments": 20,
                "linked_comments": 19,
                "quarantined_comments": 1,
            },
        }
        if (
            self.base_manifest["schema_version"]
            == "reddit_voc_site_snapshot_manifest_v2"
        ):
            base_receipt["manifest_sha256"] = self.base_sha
        _write_json(
            self.base_receipt,
            base_receipt,
        )
        _write_json(
            self.analytics_receipt,
            {
                "schema_version": "reddit_voc_site_analytics_validation_v1",
                "status": "passed_release_candidate",
                "release_candidate": True,
                "checks": {"fixture": True},
                "base_dataset_version": self.versions["base"],
                "insights_dataset_version": self.versions["insights"],
                "reports_dataset_version": self.versions["reports"],
                "base_manifest_sha256": self.base_sha,
                "insights_manifest_sha256": self.insights_sha,
                "reports_manifest_sha256": self.reports_sha,
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "live_send": False,
                "webhook_send": False,
                "deploy": False,
                "schedule_change": False,
                "independent_human_review": False,
            },
        )
        _write_json(
            self.personas_receipt,
            {
                "schema_version": "reddit_voc_personas_validation_v1",
                "status": "passed",
                "dataset_version": self.versions["personas"],
                "base_manifest_sha256": self.base_sha,
                "insights_manifest_sha256": self.insights_sha,
                "checks": {"fixture": True},
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "live_send": False,
                "webhook_send": False,
                "deploy": False,
                "independent_human_review": False,
            },
        )

    def _write_freeze(self) -> None:
        source = self.root / "source-artifact.txt"
        source.write_text("frozen\n", encoding="utf-8")
        _write_json(
            self.freeze_path,
            {
                "schema_version": "reddit_voc_incremental_input_freeze_v1",
                "freeze_id": "reddit_voc_incremental_freeze_20260716_fixture_rc2",
                "generated_at_utc": "2026-07-16T01:00:00Z",
                "source_cutoff_utc": "2026-07-16T00:59:00Z",
                "report_anchor_date": "2026-07-16",
                "identity": {
                    "set_id": "discovery_only",
                    "previous_count": 2,
                    "previous_lf_sha256": "d" * 64,
                    "candidate_count": 3,
                    "candidate_lf_sha256": "a" * 64,
                    "added_count": 1,
                    "added_lf_sha256": "e" * 64,
                    "monotonic_without_tombstone": True,
                },
                "coverage": {
                    "admitted_post_count": 2,
                    "observed_comment_count": 7,
                    "lineage_gap_count": 1,
                    "lineage_gap_lf_sha256": "b" * 64,
                    "cursor_outstanding": 2,
                    "page_pagination_outstanding": 3,
                    "raw_snapshot_sha256": "c" * 64,
                },
                "artifacts": {
                    "fixture": {
                        "repo_relative_path": "source-artifact.txt",
                        "bytes": source.stat().st_size,
                        "sha256": _sha(source),
                    }
                },
                "status": "frozen_build_input",
                "evidence_grade": "L2-local-immutable-input",
                "boundaries": {
                    "provider_call": False,
                    "provider_attempt_made": False,
                    "remote_write": False,
                    "database_write": False,
                    "production_merge": False,
                    "deploy": False,
                    "schedule_change": False,
                    "live_send": False,
                },
            },
        )
        self.freeze_sha = _sha(self.freeze_path)

    def _public_path(self, layer: str) -> Path:
        version = self.versions[layer]
        if layer == "base":
            return self.public / f"data/reddit-voc/{version}/manifest-public.json"
        if layer in {"insights", "reports"}:
            return self.public / f"data/reddit-voc/{version}/public/manifest.json"
        return self.public / f"data/reddit-voc/{version}/manifest.json"

    def _write_public_bundle(self) -> None:
        manifests = {
            "base": self.base_manifest,
            "insights": self.insights_manifest,
            "reports": self.reports_manifest,
            "personas": self.personas_manifest,
        }
        for layer, manifest in manifests.items():
            public_manifest = self._public_path(layer)
            for name in manifest["files"]:
                _add_payload(public_manifest.parent, name, "{}\n")
            _write_json(public_manifest, manifest)

        cases_root = self.public / "data/cases"
        approved_rows: list[dict[str, object]] = []
        _write_json(
            cases_root / "case-index.v1.json",
            {
                "schemaVersion": 1,
                "datasetVersion": "case_catalog_20260716_v1",
                "approvedDelta": approved_rows,
            },
        )
        cases_manifest = {
            "schemaVersion": 1,
            "datasetVersion": "case_catalog_20260716_v1",
            "seed": {
                "source": "bundled_seed",
                "version": "case_seed_bundled_v1",
                "count": 38,
                "contentSha256": "372fa672767ed2585300cd1d47141b6189d3d6784b98c4bc8a69074db5ba48a7",
            },
            "legacyUnverified": {
                "source": "bundled_legacy_snapshot",
                "version": "legacy_unverified_bundled_v1",
                "count": 12,
                "contentSha256": "9d09b10949eb3790b34507d13dcbddcaf5fcd6e9f81e96dddd7e12ef86691de2",
            },
            "approvedDelta": {
                "source": "versioned_static_index",
                "version": "approved_delta_20260716_v1",
                "count": 0,
                "contentSha256": _compact_sha(approved_rows),
            },
            "index": {
                "path": "/data/cases/case-index.v1.json",
                "sha256": _sha(cases_root / "case-index.v1.json"),
            },
        }
        _write_json(cases_root / "manifest.v1.json", cases_manifest)
        bindings: dict[str, object] = {}
        private_shas = {
            "base": self.base_sha,
            "insights": self.insights_sha,
            "reports": self.reports_sha,
            "personas": self.personas_sha,
        }
        for layer in self.versions:
            path = self._public_path(layer)
            bindings[layer] = {
                "dataset_version": self.versions[layer],
                "manifest_path": path.relative_to(self.public).as_posix(),
                "public_manifest_sha256": _sha(path),
                "lineage_manifest_sha256": private_shas[layer],
            }
        _write_json(
            self.public / "data/reddit-voc/current-release.json",
            {
                "schema_version": "reddit_voc_current_release_v1",
                "release_id": "reddit_voc_release_20260716_fixture",
                "generated_at_utc": "2026-07-16T02:00:00Z",
                "datasets": bindings,
                "cases": {
                    "dataset_version": "case_catalog_20260716_v1",
                    "manifest_path": "data/cases/manifest.v1.json",
                    "public_manifest_sha256": _sha(cases_root / "manifest.v1.json"),
                    "index_path": "data/cases/case-index.v1.json",
                    "index_sha256": _sha(cases_root / "case-index.v1.json"),
                    "stock_content_preserved": True,
                    "approved_delta_count": 0,
                },
                "boundaries": {
                    "case_gallery_stock_preserved": True,
                    "collector_isolation_required": True,
                    "login_required": False,
                },
            },
        )

    def _source_descriptor(self, relative: str, payload: str) -> dict[str, object]:
        ui_root = self.root / "ref/UI/momcozy-reddit-workbench"
        if relative == "package-lock.json" or relative.startswith(
            "deploy/insights/"
        ):
            path = ui_root / relative
        else:
            path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
        }

    def _write_frontend_release(self) -> None:
        if self.frontend_dist.exists():
            shutil.rmtree(self.frontend_dist)
        shutil.copytree(self.public / "data", self.frontend_dist / "data")
        (self.frontend_dist / "index.html").write_text(
            "<!doctype html>\n", encoding="utf-8"
        )
        files = []
        for path in sorted(
            item for item in self.frontend_dist.rglob("*") if item.is_file()
        ):
            files.append(
                {
                    "path": path.relative_to(self.frontend_dist).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha(path),
                }
            )
        deployment_paths = (
            "deploy/insights/Dockerfile",
            "deploy/insights/nginx.conf",
            "deploy/insights/compose.yaml",
            "deploy/insights/build-release.mjs",
        )
        build_paths = (
            "package-lock.json",
            "scripts/build_public_tag_dictionary.py",
            "scripts/build_public_site_projection.py",
            "scripts/build_insights_release.sh",
            "scripts/audit_insights_dist.py",
            "ref/UI/momcozy-reddit-workbench/.dockerignore",
        )
        deployment_inputs = [
            self._source_descriptor(path, f"deployment:{path}\n")
            for path in deployment_paths
        ]
        build_inputs = [
            self._source_descriptor(path, f"build:{path}\n") for path in build_paths
        ]
        pointer_path = self.public / "data/reddit-voc/current-release.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        dataset_versions = {
            layer: pointer["datasets"][layer]["dataset_version"]
            for layer in ("base", "insights", "reports", "personas")
        }
        dataset_manifests = {
            layer: {
                "manifest_path": pointer["datasets"][layer]["manifest_path"],
                "public_manifest_sha256": pointer["datasets"][layer][
                    "public_manifest_sha256"
                ],
                "lineage_manifest_sha256": pointer["datasets"][layer][
                    "lineage_manifest_sha256"
                ],
            }
            for layer in ("base", "insights", "reports", "personas")
        }
        current_release = {
            "path": "data/reddit-voc/current-release.json",
            "release_id": pointer["release_id"],
            "sha256": _sha(pointer_path),
        }
        content_descriptor = {
            "build_contract_version": "reddit_voc_insights_container_v4",
            "target_platform": "linux/amd64",
            "nginx_base_image": f"fixture.invalid/nginx@sha256:{'d' * 64}",
            "files": files,
            "deployment_inputs": deployment_inputs,
            "build_inputs": build_inputs,
            "toolchain": {"node": "v22.0.0-fixture", "npm": "10.0.0-fixture"},
            "dataset_versions": dataset_versions,
            "dataset_manifests": dataset_manifests,
            "current_release": current_release,
            "collection_status": {
                "latest_collection_integrated": True,
                "latest_collection_fully_hydrated": False,
            },
        }
        release_sha = sha256(
            json.dumps(
                content_descriptor,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        _write_json(
            self.release_metadata,
            {
                "schema_version": "reddit_voc_insights_site_release_v2",
                "release_sha256": release_sha,
                "generated_at_utc": "2026-07-16T02:30:00Z",
                "delivery_mode": "immutable_static_container",
                "public_access": True,
                "authentication_enabled": False,
                "latest_collection_integrated": True,
                "latest_collection_fully_hydrated": False,
                "nginx_base_image": f"fixture.invalid/nginx@sha256:{'d' * 64}",
                "target_platform": "linux/amd64",
                "build_contract_version": "reddit_voc_insights_container_v4",
                "deployment_inputs": deployment_inputs,
                "build_inputs": build_inputs,
                "toolchain": {
                    "node": "v22.0.0-fixture",
                    "npm": "10.0.0-fixture",
                },
                "dataset_versions": dataset_versions,
                "dataset_manifests": dataset_manifests,
                "current_release": current_release,
                "file_count": len(files),
                "files": files,
                "boundaries": {
                    "provider_call": False,
                    "database_write": False,
                    "live_send": False,
                    "webhook_send": False,
                    "schedule_change": False,
                    "collector_restart": False,
                    "collector_isolation_required": True,
                    "case_gallery_stock_preserved": True,
                    "login_required": False,
                },
            },
        )

    def _validate(self) -> dict[str, Any]:
        return validate_candidate(
            project_root=self.root,
            input_freeze_path=self.freeze_path,
            expected_input_freeze_sha256=self.freeze_sha,
            base_dir=self.private["base"],
            base_validation_receipt_path=self.base_receipt,
            insights_dir=self.private["insights"],
            reports_dir=self.private["reports"],
            analytics_validation_receipt_path=self.analytics_receipt,
            personas_dir=self.private["personas"],
            personas_validation_receipt_path=self.personas_receipt,
            public_root=self.public,
            frontend_dist=self.frontend_dist,
            release_metadata_manifest_path=self.release_metadata,
            validated_at_utc="2026-07-16T03:00:00Z",
        )

    def _replace_freeze_id(self, freeze_id: str) -> None:
        freeze = json.loads(self.freeze_path.read_text(encoding="utf-8"))
        freeze["freeze_id"] = freeze_id
        _write_json(self.freeze_path, freeze)
        self.freeze_sha = _sha(self.freeze_path)

    def _upgrade_base_manifest_to_v2(self) -> None:
        v2_debt = self.base_manifest["source_boundaries"][
            "tencent_v2_search_hydrated"
        ]["comment_coverage_debt"]
        hydration_debt = {
            "first_page_missing": 1,
            "cursor_outstanding": 1,
            "page_pagination_outstanding": 2,
            "failed_reports": 1,
            "partial_threads": 2,
            "not_observed_threads": 1,
            "failure_reason_counts": {"fixture_failure": 1},
        }
        self.base_manifest["schema_version"] = (
            "reddit_voc_site_snapshot_manifest_v2"
        )
        self.base_manifest["source_boundaries"].update(
            {
                "imported_archive": {},
                "historical_canonical": {},
                "tencent_production_primary": {},
                "tencent_isolated_staging": {},
                "tencent_existing_post_comment_hydration": {
                    "admission_status": (
                        "passed_with_explicit_comment_coverage_debt"
                    ),
                    "snapshot_sha256": "f" * 64,
                    "input_posts": 0,
                    "input_comments": 2,
                    "overlap_posts": 0,
                    "overlap_comments": 0,
                    "net_new_posts": 0,
                    "net_new_comments": 2,
                    "materialized_comments": 2,
                    "release_candidate_comments": 2,
                    "preceding_overlap_comments": 0,
                    "preceding_body_conflicts": 0,
                    "comment_coverage_debt": hydration_debt,
                    "fusion_role": "existing_post_comment_delta_after_v2",
                    "dedup_key": {
                        "posts": "post_id",
                        "comments": "comment_id",
                    },
                    "precedence_policy": "preceding_canonical_wins",
                    "provider_call": False,
                    "database_write": False,
                    "production_merge": False,
                    "live_send": False,
                },
            }
        )
        self.base_manifest["fusion_accounting"].update(
            {
                "load_order": [
                    "imported_archive",
                    "historical_canonical_lineage_only",
                    "tencent_production_primary",
                    "tencent_isolated_staging_overlay",
                    "tencent_v2_search_hydrated_disjoint_append",
                    "tencent_existing_post_comment_hydration_append",
                ],
                "existing_post_hydration_coverage_debt": hydration_debt,
                "comment_coverage_debt_union": {
                    "first_page_missing": 2,
                    "first_page_missing_lf_sha256": "1" * 64,
                    "cursor_outstanding": 3,
                    "cursor_outstanding_lf_sha256": "2" * 64,
                    "page_pagination_outstanding": 4,
                    "page_pagination_outstanding_lf_sha256": "3" * 64,
                    "failed_reports": 1,
                    "failed_reports_lf_sha256": "4" * 64,
                    "partial_threads": 3,
                    "partial_thread_ids_lf_sha256": "5" * 64,
                    "not_observed_threads": 2,
                    "not_observed_thread_ids_lf_sha256": "1" * 64,
                    "source_counts": {
                        "v2": {
                            "first_page_missing": 1,
                            "cursor_outstanding": v2_debt[
                                "cursor_outstanding"
                            ],
                            "page_pagination_outstanding": v2_debt[
                                "page_pagination_outstanding"
                            ],
                            "failed_reports": 0,
                        },
                        "existing_post_hydration": hydration_debt,
                    },
                    "key_union_not_numeric_sum": True,
                },
            }
        )
        _write_json(
            self.private["base"] / "manifest.json", self.base_manifest
        )
        self.base_sha = _sha(self.private["base"] / "manifest.json")

        self.insights_manifest["base_manifest_sha256"] = self.base_sha
        _write_json(
            self.private["insights"] / "manifest.json", self.insights_manifest
        )
        self.insights_sha = _sha(self.private["insights"] / "manifest.json")
        self.reports_manifest["base_manifest_sha256"] = self.base_sha
        self.reports_manifest["insights_manifest_sha256"] = self.insights_sha
        _write_json(
            self.private["reports"] / "manifest.json", self.reports_manifest
        )
        self.reports_sha = _sha(self.private["reports"] / "manifest.json")
        self.personas_manifest["base_manifest_sha256"] = self.base_sha
        self.personas_manifest["insights_manifest_sha256"] = self.insights_sha
        _write_json(
            self.private["personas"] / "manifest.json", self.personas_manifest
        )
        self.personas_sha = _sha(self.private["personas"] / "manifest.json")
        self._write_receipts()
        self._write_public_bundle()
        self._write_frontend_release()

    def _validate_base_only(self) -> tuple[object, ...]:
        freeze = json.loads(self.freeze_path.read_text(encoding="utf-8"))
        return _validate_base(
            base_dir=self.private["base"],
            receipt_path=self.base_receipt,
            freeze=freeze,
        )

    def test_validates_cross_layer_candidate_with_explicit_debt(self) -> None:
        receipt = self._validate()

        self.assertEqual(
            receipt["status"], "candidate_validated_with_explicit_debt"
        )
        self.assertEqual(receipt["hydration_status"], "partial_with_explicit_debt")
        self.assertFalse(receipt["completion_claim_supported"])
        self.assertEqual(receipt["coverage_debt"]["lineage_gap_count"], 1)
        self.assertEqual(
            receipt["coverage_debt"],
            {
                "lineage_gap_count": 1,
                "cursor_outstanding": 2,
                "page_pagination_outstanding": 3,
                "partial_threads": 2,
            },
        )
        self.assertEqual(receipt["cases"]["seed"], 38)
        self.assertEqual(receipt["cases"]["legacy_unverified"], 12)
        self.assertTrue(receipt["frontend"]["latest_collection_integrated"])
        self.assertFalse(
            receipt["frontend"]["latest_collection_fully_hydrated"]
        )
        self.assertFalse(
            receipt["frontend"]["container_build_completed_claim_supported"]
        )
        self.assertFalse(receipt["frontend"]["deploy_completed_claim_supported"])
        self.assertFalse(receipt["frontend"]["browser_e2e_evaluated"])
        self.assertTrue(all(receipt["checks"].values()))
        self.assertTrue(all(value is False for value in receipt["boundaries"].values()))

    def test_v2_base_prefers_comment_coverage_debt_union(self) -> None:
        self._upgrade_base_manifest_to_v2()

        receipt = self._validate()

        self.assertEqual(receipt["coverage_debt"]["cursor_outstanding"], 3)
        self.assertEqual(
            receipt["coverage_debt"]["page_pagination_outstanding"], 4
        )
        self.assertEqual(receipt["coverage_debt"]["partial_threads"], 3)
        self.assertEqual(receipt["coverage_debt"]["failed_reports"], 1)
        self.assertTrue(
            receipt["coverage_debt"]["key_union_not_numeric_sum"]
        )

    def test_rejects_v2_base_without_hydration_source(self) -> None:
        self._upgrade_base_manifest_to_v2()
        manifest_path = self.private["base"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["source_boundaries"][
            "tencent_existing_post_comment_hydration"
        ]
        _write_json(manifest_path, manifest)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "base_v2_source_set_invalid",
        ):
            self._validate_base_only()

    def test_rejects_v2_base_hydration_load_order_drift(self) -> None:
        self._upgrade_base_manifest_to_v2()
        manifest_path = self.private["base"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["fusion_accounting"]["load_order"][-1] = (
            "tencent_existing_post_comment_hydration_overlay"
        )
        _write_json(manifest_path, manifest)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "base_v2_load_order_invalid",
        ):
            self._validate_base_only()

    def test_rejects_v2_base_that_substitutes_v2_only_debt_for_union(self) -> None:
        self._upgrade_base_manifest_to_v2()
        manifest_path = self.private["base"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["fusion_accounting"]["comment_coverage_debt_union"] = dict(
            manifest["fusion_accounting"]["v2_comment_coverage_debt"]
        )
        _write_json(manifest_path, manifest)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "base_v2_coverage_union_invalid",
        ):
            self._validate_base_only()

    def test_rejects_v2_base_stale_validation_receipt(self) -> None:
        self._upgrade_base_manifest_to_v2()
        receipt = json.loads(self.base_receipt.read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = "0" * 64
        _write_json(self.base_receipt, receipt)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "base_v2_receipt_manifest_sha256_mismatch",
        ):
            self._validate_base_only()

    def test_accepts_rc3_freeze_generation_without_weakening_hash_binding(self) -> None:
        self._replace_freeze_id(
            "reddit_voc_incremental_freeze_20260716_fixture_rc3"
        )

        receipt = self._validate()

        self.assertEqual(receipt["input_freeze"]["rc_generation"], 3)
        self.assertEqual(receipt["input_freeze"]["sha256"], self.freeze_sha)
        self.assertTrue(
            receipt["checks"][
                "immutable_rc_generation_input_freeze_and_artifacts"
            ]
        )

    def test_rejects_missing_rc_rc1_and_unsafe_freeze_ids(self) -> None:
        invalid_ids = (
            "reddit_voc_incremental_freeze_20260716_fixture",
            "reddit_voc_incremental_freeze_20260716_fixture_rc0",
            "reddit_voc_incremental_freeze_20260716_fixture_rc1",
            "reddit_voc_incremental_freeze_20260716_fixture_rc01",
            "reddit_voc_incremental_freeze_20260716_Fixture_rc3",
            "reddit_voc_incremental_freeze_20260716_fixture/rc3",
            "reddit_voc_incremental_freeze_20260716_fixture._rc3",
        )
        for freeze_id in invalid_ids:
            with self.subTest(freeze_id=freeze_id):
                self._replace_freeze_id(freeze_id)
                with self.assertRaisesRegex(
                    IncrementalCandidateValidationError,
                    "input_freeze_rc_generation_invalid",
                ):
                    self._validate()

    def test_receipt_write_is_atomic_no_change_and_collision_safe(self) -> None:
        receipt = self._validate()
        path = self.root / "receipts/candidate.json"
        self.assertEqual(write_immutable_receipt(path, receipt), "created")
        first_mtime = path.stat().st_mtime_ns
        self.assertEqual(write_immutable_receipt(path, receipt), "no_change")
        self.assertEqual(path.stat().st_mtime_ns, first_mtime)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        changed = dict(receipt)
        changed["validated_at_utc"] = "2026-07-16T03:01:00Z"
        with self.assertRaisesRegex(
            IncrementalCandidateValidationError, "receipt_immutable_collision"
        ):
            write_immutable_receipt(path, changed)

    def test_rejects_zero_filled_coverage_debt(self) -> None:
        freeze = json.loads(self.freeze_path.read_text(encoding="utf-8"))
        freeze["coverage"]["cursor_outstanding"] = 0
        _write_json(self.freeze_path, freeze)
        self.freeze_sha = _sha(self.freeze_path)
        with self.assertRaisesRegex(
            IncrementalCandidateValidationError, "input_freeze_cursor_debt_invalid"
        ):
            self._validate()

    def test_rejects_public_boundary_drift_even_when_pointer_is_rehashed(self) -> None:
        path = self._public_path("insights")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["boundaries"]["provider_call"] = True
        _write_json(path, manifest)
        pointer_path = self.public / "data/reddit-voc/current-release.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["datasets"]["insights"]["public_manifest_sha256"] = _sha(path)
        _write_json(pointer_path, pointer)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "public_insights_provider_call_boundary_invalid",
        ):
            self._validate()

    def test_rejects_case_stock_replacement_even_when_rehashed(self) -> None:
        path = self.public / "data/cases/manifest.v1.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["seed"]["count"] = 37
        _write_json(path, manifest)
        pointer_path = self.public / "data/reddit-voc/current-release.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["cases"]["public_manifest_sha256"] = _sha(path)
        _write_json(pointer_path, pointer)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError, "cases_seed_stock_changed"
        ):
            self._validate()

    def test_rejects_analytics_receipt_lineage_drift(self) -> None:
        receipt = json.loads(self.analytics_receipt.read_text(encoding="utf-8"))
        receipt["reports_manifest_sha256"] = "0" * 64
        _write_json(self.analytics_receipt, receipt)
        with self.assertRaisesRegex(
            IncrementalCandidateValidationError, "analytics_receipt_lineage_mismatch"
        ):
            self._validate()

    def test_rejects_frontend_data_tamper_against_public_bundle(self) -> None:
        path = self.frontend_dist / "data/cases/manifest.v1.json"
        path.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError, "frontend_data_public_mismatch"
        ):
            self._validate()

    def test_rejects_missing_frontend_data_file(self) -> None:
        (self.frontend_dist / "data/cases/manifest.v1.json").unlink()

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError, "frontend_data_public_mismatch"
        ):
            self._validate()

    def test_rejects_frontend_data_symlink(self) -> None:
        path = self.frontend_dist / "data/cases/manifest.v1.json"
        path.unlink()
        path.symlink_to(self.public / "data/cases/manifest.v1.json")

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "frontend_dist_data_symlink_forbidden",
        ):
            self._validate()

    def test_rejects_collection_status_that_overstates_hydration(self) -> None:
        metadata = json.loads(self.release_metadata.read_text(encoding="utf-8"))
        metadata["latest_collection_fully_hydrated"] = True
        _write_json(self.release_metadata, metadata)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "release_metadata_collection_status_invalid",
        ):
            self._validate()

    def test_rejects_release_metadata_pointer_sha_tamper(self) -> None:
        metadata = json.loads(self.release_metadata.read_text(encoding="utf-8"))
        metadata["current_release"]["sha256"] = "0" * 64
        _write_json(self.release_metadata, metadata)

        with self.assertRaisesRegex(
            IncrementalCandidateValidationError,
            "release_metadata_current_release_mismatch",
        ):
            self._validate()

    def test_rejects_container_or_deploy_completion_claim_field(self) -> None:
        for field in ("container_build_completed", "deployment_completed"):
            with self.subTest(field=field):
                self._write_frontend_release()
                metadata = json.loads(
                    self.release_metadata.read_text(encoding="utf-8")
                )
                metadata[field] = True
                _write_json(self.release_metadata, metadata)
                with self.assertRaisesRegex(
                    IncrementalCandidateValidationError,
                    "release_metadata_field_contract_mismatch",
                ):
                    self._validate()

    def test_cli_failure_is_fail_closed_and_writes_no_receipt(self) -> None:
        receipt_path = self.root / "receipts/should-not-exist.json"
        arguments = [
            "--project-root",
            str(self.root),
            "--input-freeze",
            str(self.freeze_path),
            "--expected-input-freeze-sha256",
            "0" * 64,
            "--base-dir",
            str(self.private["base"]),
            "--base-validation-receipt",
            str(self.base_receipt),
            "--insights-dir",
            str(self.private["insights"]),
            "--reports-dir",
            str(self.private["reports"]),
            "--analytics-validation-receipt",
            str(self.analytics_receipt),
            "--personas-dir",
            str(self.private["personas"]),
            "--personas-validation-receipt",
            str(self.personas_receipt),
            "--public-root",
            str(self.public),
            "--frontend-dist",
            str(self.frontend_dist),
            "--release-metadata-manifest",
            str(self.release_metadata),
            "--validated-at-utc",
            "2026-07-16T03:00:00Z",
            "--receipt",
            str(receipt_path),
        ]
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = main(arguments)
        self.assertEqual(status, 1)
        self.assertIn('"status": "fail-closed"', stderr.getvalue())
        self.assertFalse(receipt_path.exists())


if __name__ == "__main__":
    unittest.main()
