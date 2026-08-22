from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from typing import Any

from scripts import build_reddit_candidate_data_closure as builder
from scripts import validate_reddit_candidate_data_closure as validator


SOURCE_CUTOFF = "2026-07-15T08:47:22.379946Z"
CODE_CUTOFF = "2026-07-15T09:30:00.000000Z"
INPUT_EVIDENCE = "e" * 64
RELEASE_SHA = "9" * 64


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(value) + b"\n"
    path.write_bytes(payload)
    return sha256(payload).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(_canonical_bytes(row) + b"\n" for row in rows)
    path.write_bytes(payload)
    return {
        "bytes": len(payload),
        "rows": len(rows),
        "sha256": sha256(payload).hexdigest(),
    }


def _file_contract(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


def _identity_contract(values: set[str]) -> dict[str, Any]:
    payload = "".join(f"{value}\n" for value in sorted(values)).encode("utf-8")
    return {"count": len(values), "ids_lf_sha256": sha256(payload).hexdigest()}


def _public_inventory(root: Path) -> tuple[int, int, str]:
    rows: list[tuple[str, int, str]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            rows.append(
                (
                    path.relative_to(root).as_posix(),
                    len(payload),
                    sha256(payload).hexdigest(),
                )
            )
            total += len(payload)
    inventory = "".join(
        f"{relative}\t{size}\t{digest}\n" for relative, size, digest in rows
    ).encode("utf-8")
    return len(rows), total, sha256(inventory).hexdigest()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths: dict[str, Path] = {}
        self.shas: dict[str, str] = {}
        self._build()

    def _base(
        self,
        root: Path,
        *,
        version: str,
        posts: list[dict[str, Any]],
        comments: list[dict[str, Any]],
        quarantine: list[dict[str, Any]],
        schema: str,
    ) -> str:
        _write_json(root / "posts.json", posts)
        _write_json(root / "comments.json", comments)
        _write_json(root / "quarantine.json", quarantine)
        manifest = {
            "schema_version": schema,
            "dataset_version": version,
            "all_checks_passed": True,
            "canonical_counts": {
                "posts": len(posts),
                "linked_comments": len(comments),
                "quarantined_comments": len(quarantine),
                "stored_comments": len(comments) + len(quarantine),
            },
            "files": {
                name: _file_contract(root / name)
                for name in ("posts.json", "comments.json", "quarantine.json")
            },
            "provider_call": False,
            "live_send": False,
            "production_unchanged": True,
        }
        return _write_json(root / "manifest.json", manifest)

    def _private_dataset_manifest(
        self,
        root: Path,
        *,
        schema: str,
        version: str,
        payload_name: str,
        base_sha: str,
        ledger_sha: str,
        ledger_receipt_sha: str,
        insights_sha: str | None = None,
    ) -> str:
        _write_json(root / payload_name, {"fixture": version})
        manifest: dict[str, Any] = {
            "schema_version": schema,
            "dataset_version": version,
            "base_manifest_sha256": base_sha,
            "files": {payload_name: _file_contract(root / payload_name)},
            "boundaries": dict(builder.BOUNDARIES),
        }
        if schema in {
            "reddit_voc_insights_manifest_v1",
            "reddit_voc_reports_manifest_v1",
        }:
            manifest["status"] = "passed_provisional_risk_threshold"
            manifest["identity_gate"] = {
                "candidate_ledger_manifest_sha256": ledger_sha,
                "ledger_validation_receipt_sha256": ledger_receipt_sha,
                "unaccounted_total": 0,
            }
        if insights_sha is not None:
            manifest["insights_manifest_sha256"] = insights_sha
        return _write_json(root / "manifest.json", manifest)

    def _public_manifest(
        self,
        path: Path,
        *,
        private: dict[str, Any],
        payload_name: str,
        base_sha: str | None = None,
        insights_sha: str | None = None,
        base_style: bool = False,
    ) -> str:
        _write_json(path.parent / payload_name, {"public": private["dataset_version"]})
        manifest: dict[str, Any] = {
            "schema_version": private["schema_version"],
            "dataset_version": private["dataset_version"],
            "files": {payload_name: _file_contract(path.parent / payload_name)},
        }
        if base_style:
            manifest.update(
                {
                    "provider_call": False,
                    "live_send": False,
                    "production_unchanged": True,
                }
            )
        else:
            manifest["boundaries"] = dict(builder.BOUNDARIES)
        if base_sha is not None:
            manifest["base_manifest_sha256"] = base_sha
        if insights_sha is not None:
            manifest["insights_manifest_sha256"] = insights_sha
        return _write_json(path, manifest)

    def _build(self) -> None:
        post = {"post_id": "p00001"}
        baseline_comments = [{"comment_id": "t1_c0", "post_id": "p00001"}]
        baseline_quarantine = [{"comment_id": "t1_q0", "post_id": None}]
        candidate_comments = [
            {"comment_id": "t1_c0", "post_id": "p00001"},
            {"comment_id": "t1_c1", "post_id": "p00001"},
            {"comment_id": "t1_q0", "post_id": "p00001"},
        ]
        baseline_root = self.root / "baseline"
        candidate_root = self.root / "candidate-base"
        baseline_sha = self._base(
            baseline_root,
            version="base-production-v1",
            posts=[post],
            comments=baseline_comments,
            quarantine=baseline_quarantine,
            schema="reddit_voc_site_snapshot_manifest_v1",
        )
        base_sha = self._base(
            candidate_root,
            version="base-candidate-v2",
            posts=[post],
            comments=candidate_comments,
            quarantine=[],
            schema="reddit_voc_site_snapshot_manifest_v2",
        )
        self.paths["production_baseline_root"] = baseline_root
        self.paths["candidate_base_root"] = candidate_root
        self.shas["production_baseline_manifest"] = baseline_sha
        self.shas["candidate_base_manifest"] = base_sha

        source_path = self.root / "source-freeze-manifest.json"
        source_sha = _write_json(
            source_path,
            {
                "schema_version": "reddit_voc_candidate_source_freeze_v1",
                "source_cutoff_utc": SOURCE_CUTOFF,
                "boundaries": {
                    "provider_call": False,
                    "provider_attempt_made": False,
                    "database_write": False,
                    "remote_write": False,
                    "deploy": False,
                    "live_send": False,
                },
            },
        )
        self.paths["source_freeze_manifest"] = source_path
        self.shas["source_freeze_manifest"] = source_sha

        acceptance_path = self.root / "production-acceptance.json"
        acceptance_sha = _write_json(
            acceptance_path,
            {
                "schema_version": "reddit_voc_production_acceptance_receipt_v1",
                "status": "production_accepted_with_explicit_coverage_debt",
                "release": {"current_production_release_sha256": RELEASE_SHA},
                "datasets": {
                    "base": "base-production-v1",
                    "published_posts": 1,
                    "linked_comments": 1,
                    "stored_comments": 2,
                    "quarantined_comments": 1,
                },
            },
        )
        self.paths["production_acceptance_receipt"] = acceptance_path
        self.shas["production_acceptance_receipt"] = acceptance_sha

        p0 = p1 = {"p00001"}
        l0 = {"t1_c0"}
        q0 = {"t1_q0"}
        c0 = l0 | q0
        l1 = {"t1_c0", "t1_c1", "t1_q0"}
        q1: set[str] = set()
        c1 = l1
        identity_sets = {
            "p0": _identity_contract(p0),
            "p1": _identity_contract(p1),
            "l0": _identity_contract(l0),
            "l1": _identity_contract(l1),
            "q0": _identity_contract(q0),
            "q1": _identity_contract(q1),
            "c0": _identity_contract(c0),
            "c1": _identity_contract(c1),
        }
        common = {
            "input_evidence_sha256": INPUT_EVIDENCE,
            "source_cutoff_utc": SOURCE_CUTOFF,
        }
        ledger_root = self.root / "ledgers"
        rows = {
            "source-occurrence-ledger.jsonl": [
                {
                    **common,
                    "occurrence_key": "occurrence:1",
                    "status": "accepted_new_occurrence",
                }
            ],
            "post-identity-delta-ledger.jsonl": [
                {
                    **common,
                    "post_id": "p00001",
                    "status": "existing_unchanged",
                    "release_net_new": False,
                }
            ],
            "comment-identity-delta-ledger.jsonl": [
                {
                    **common,
                    "comment_id": "t1_c0",
                    "status": "existing_unchanged",
                    "release_net_new": False,
                },
                {
                    **common,
                    "comment_id": "t1_c1",
                    "status": "new_linked",
                    "release_net_new": True,
                },
                {
                    **common,
                    "comment_id": "t1_q0",
                    "status": "existing_quarantine_relinked",
                    "release_net_new": False,
                },
            ],
            "coverage-work-ledger.jsonl": [
                {
                    **common,
                    "work_item_key": "lineage:p00001",
                    "status": "open_carried",
                }
            ],
        }
        ledger_contracts = {
            name: _write_jsonl(ledger_root / name, value) for name, value in rows.items()
        }
        accounting = {
            "source_occurrences": {
                "total": 1,
                "status_counts": {"accepted_new_occurrence": 1},
                "unaccounted": 0,
            },
            "posts": {
                "baseline": 1,
                "candidate": 1,
                "release_net_new": 0,
                "status_counts": {"existing_unchanged": 1},
                "unaccounted": 0,
            },
            "comments": {
                "baseline": 2,
                "candidate": 3,
                "release_net_new": 1,
                "status_counts": {
                    "existing_unchanged": 1,
                    "new_linked": 1,
                    "existing_quarantine_relinked": 1,
                },
                "unaccounted": 0,
            },
            "coverage": {
                "total": 1,
                "status_counts": {"open_carried": 1},
                "unaccounted": 0,
            },
            "unaccounted_total": 0,
        }
        ledger_manifest = {
            "schema_version": "reddit_voc_candidate_ledger_manifest_v2",
            "status": "a2_identity_closed_with_explicit_coverage_debt",
            "source_cutoff_utc": SOURCE_CUTOFF,
            "input_evidence_sha256": INPUT_EVIDENCE,
            "inputs": {
                "source_freeze_manifest_sha256": source_sha,
                "production_baseline_manifest_sha256": baseline_sha,
                "candidate_base_manifest_sha256": base_sha,
            },
            "ledgers": ledger_contracts,
            "identity_sets": identity_sets,
            "accounting": accounting,
            "set_relations": {
                "p0_subset_p1": True,
                "c0_subset_c1": True,
                "l1_intersection_q1_empty": True,
                "all_linked_comment_parents_exist": True,
            },
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": False,
            "remote_write": False,
            "production_merge": False,
            "deployment": False,
            "live_send": False,
            "production_unchanged": True,
        }
        ledger_sha = _write_json(
            ledger_root / "candidate-ledger-manifest.json", ledger_manifest
        )
        self.paths["candidate_ledger_root"] = ledger_root
        self.shas["candidate_ledger_manifest"] = ledger_sha

        ledger_receipt_path = self.root / "ledger-receipt.json"
        ledger_receipt_sha = _write_json(
            ledger_receipt_path,
            {
                "schema_version": "reddit_voc_candidate_ledger_validation_receipt_v1",
                "status": "passed",
                "candidate_ledger_manifest_sha256": ledger_sha,
                "identity_sets": identity_sets,
                "counts": {
                    "source_occurrences": 1,
                    "post_rows": 1,
                    "comment_rows": 3,
                    "coverage_rows": 1,
                    "release_net_new_posts": 0,
                    "release_net_new_comments": 1,
                    "unaccounted_total": 0,
                },
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "remote_write": False,
                "production_merge": False,
                "deployment": False,
                "live_send": False,
                "production_unchanged": True,
            },
        )
        self.paths["ledger_validation_receipt"] = ledger_receipt_path
        self.shas["ledger_validation_receipt"] = ledger_receipt_sha

        config_root = self.root / "config"
        _write_json(config_root / "coverage-profile.json", {"fixture": True})
        config_path = config_root / "manifest.json"
        config_sha = _write_json(
            config_path,
            {
                "schema_version": "reddit_voc_incremental_candidate_config_manifest_v1",
                "files": {
                    "coverage-profile.json": _file_contract(
                        config_root / "coverage-profile.json"
                    )
                },
                "identity_gate": {
                    "candidate_base_manifest_sha256": base_sha,
                    "candidate_ledger_manifest_sha256": ledger_sha,
                    "input_evidence_sha256": INPUT_EVIDENCE,
                    "ledger_validation_receipt_sha256": ledger_receipt_sha,
                    "unaccounted_total": 0,
                },
                "boundaries": {
                    "provider_call": False,
                    "database_write": False,
                    "deploy": False,
                    "live_send": False,
                },
            },
        )
        self.paths["config_manifest"] = config_path
        self.shas["config_manifest"] = config_sha

        code_root = self.root / "code-root"
        code_files: dict[str, dict[str, Any]] = {}
        for relative in builder.CODE_ALLOWLIST:
            code_file = code_root / relative
            code_file.parent.mkdir(parents=True, exist_ok=True)
            code_file.write_bytes(f"fixture-code:{relative}\n".encode("utf-8"))
            code_files[relative] = _file_contract(code_file)
        code_path = self.root / "code-freeze.json"
        code_sha = _write_json(
            code_path,
            {
                "schema_version": "reddit_voc_data_build_code_freeze_v1",
                "allowlist_version": "plan_a_data_build_v1",
                "code_cutoff_utc": CODE_CUTOFF,
                "files": code_files,
                "boundaries": dict(builder.BOUNDARIES),
            },
        )
        self.paths["code_freeze_manifest"] = code_path
        self.paths["code_root"] = code_root
        self.shas["code_freeze_manifest"] = code_sha

        insights_root = self.root / "insights"
        insights_sha = self._private_dataset_manifest(
            insights_root,
            schema="reddit_voc_insights_manifest_v1",
            version="insights-candidate-v1",
            payload_name="insights.json",
            base_sha=base_sha,
            ledger_sha=ledger_sha,
            ledger_receipt_sha=ledger_receipt_sha,
        )
        reports_root = self.root / "reports"
        reports_sha = self._private_dataset_manifest(
            reports_root,
            schema="reddit_voc_reports_manifest_v1",
            version="reports-candidate-v1",
            payload_name="report-index.json",
            base_sha=base_sha,
            ledger_sha=ledger_sha,
            ledger_receipt_sha=ledger_receipt_sha,
            insights_sha=insights_sha,
        )
        self.paths["insights_root"] = insights_root
        self.paths["reports_root"] = reports_root
        self.shas["insights_manifest"] = insights_sha
        self.shas["reports_manifest"] = reports_sha

        analytics_receipt_path = self.root / "analytics-receipt.json"
        analytics_receipt_sha = _write_json(
            analytics_receipt_path,
            {
                "schema_version": "reddit_voc_site_analytics_validation_v1",
                "status": "passed_release_candidate",
                "base_manifest_sha256": base_sha,
                "insights_manifest_sha256": insights_sha,
                "reports_manifest_sha256": reports_sha,
                "provider_call": False,
                "database_write": False,
                "deploy": False,
                "live_send": False,
                "webhook_send": False,
                "schedule_change": False,
                "production_unchanged": True,
            },
        )
        self.paths["analytics_validation_receipt"] = analytics_receipt_path
        self.shas["analytics_validation_receipt"] = analytics_receipt_sha

        personas_root = self.root / "personas"
        personas_sha = self._private_dataset_manifest(
            personas_root,
            schema="reddit_voc_personas_manifest_v1",
            version="personas-candidate-v1",
            payload_name="personas.json",
            base_sha=base_sha,
            ledger_sha=ledger_sha,
            ledger_receipt_sha=ledger_receipt_sha,
            insights_sha=insights_sha,
        )
        self.paths["personas_root"] = personas_root
        self.shas["personas_manifest"] = personas_sha
        personas_receipt_path = self.root / "personas-receipt.json"
        personas_receipt_sha = _write_json(
            personas_receipt_path,
            {
                "schema_version": "reddit_voc_personas_validation_v1",
                "status": "passed",
                "manifest_sha256": personas_sha,
                "base_manifest_sha256": base_sha,
                "insights_manifest_sha256": insights_sha,
                "provider_call": False,
                "database_write": False,
                "deploy": False,
                "live_send": False,
                "webhook_send": False,
                "production_unchanged": True,
            },
        )
        self.paths["personas_validation_receipt"] = personas_receipt_path
        self.shas["personas_validation_receipt"] = personas_receipt_sha

        base_manifest = json.loads((candidate_root / "manifest.json").read_text())
        insights_manifest = json.loads((insights_root / "manifest.json").read_text())
        reports_manifest = json.loads((reports_root / "manifest.json").read_text())
        personas_manifest = json.loads((personas_root / "manifest.json").read_text())
        public_root = self.root / "public"
        base_public_path = (
            public_root
            / "data"
            / "reddit-voc"
            / base_manifest["dataset_version"]
            / "manifest-public.json"
        )
        base_public_sha = self._public_manifest(
            base_public_path,
            private=base_manifest,
            payload_name="posts-public.json",
            base_style=True,
        )
        insights_public_path = (
            public_root
            / "data"
            / "reddit-voc"
            / insights_manifest["dataset_version"]
            / "public"
            / "manifest.json"
        )
        insights_public_sha = self._public_manifest(
            insights_public_path,
            private=insights_manifest,
            payload_name="insights.json",
            base_sha=base_sha,
        )
        reports_public_path = (
            public_root
            / "data"
            / "reddit-voc"
            / reports_manifest["dataset_version"]
            / "public"
            / "manifest.json"
        )
        reports_public_sha = self._public_manifest(
            reports_public_path,
            private=reports_manifest,
            payload_name="report-index.json",
            base_sha=base_sha,
            insights_sha=insights_sha,
        )
        personas_public_path = (
            public_root
            / "data"
            / "reddit-voc"
            / personas_manifest["dataset_version"]
            / "manifest.json"
        )
        personas_public_sha = self._public_manifest(
            personas_public_path,
            private=personas_manifest,
            payload_name="personas.json",
            base_sha=base_sha,
            insights_sha=insights_sha,
        )
        public_file_count, public_bytes, public_inventory_sha = _public_inventory(public_root)
        self.paths["public_root"] = public_root
        self.shas["public_inventory"] = public_inventory_sha

        cases_root = self.root / "cases"
        index_path = cases_root / "case-index.v1.json"
        index_sha = _write_json(
            index_path,
            {
                "schemaVersion": 1,
                "datasetVersion": "case-catalog-v1",
                "approvedDelta": [],
            },
        )
        cases_path = cases_root / "manifest.v1.json"
        cases_sha = _write_json(
            cases_path,
            {
                "schemaVersion": 1,
                "datasetVersion": "case-catalog-v1",
                "provenance": {"networkSearch": False},
                "seed": {
                    "source": "bundled_seed",
                    "count": 38,
                    "contentSha256": "a" * 64,
                },
                "legacyUnverified": {
                    "source": "bundled_legacy_snapshot",
                    "count": 12,
                    "contentSha256": "b" * 64,
                },
                "approvedDelta": {
                    "source": "versioned_static_index",
                    "count": 0,
                    "contentSha256": sha256(b"[]").hexdigest(),
                },
                "index": {
                    "path": "/data/cases/case-index.v1.json",
                    "sha256": index_sha,
                },
            },
        )
        self.paths["cases_manifest"] = cases_path
        self.paths["cases_index"] = index_path
        self.shas["cases_manifest"] = cases_sha
        self.shas["cases_index"] = index_sha

        public_receipt_path = self.root / "public-receipt.json"
        public_receipt_sha = _write_json(
            public_receipt_path,
            {
                "schema_version": "reddit_voc_public_projection_validation_v1",
                "status": "passed_release_candidate",
                "validated_at_utc": SOURCE_CUTOFF,
                "public_inventory": {
                    "file_count": public_file_count,
                    "total_bytes": public_bytes,
                    "inventory_sha256": public_inventory_sha,
                },
                "lineage": {
                    "base": {
                        "dataset_version": base_manifest["dataset_version"],
                        "private_manifest_sha256": base_sha,
                        "public_manifest_sha256": base_public_sha,
                    },
                    "insights": {
                        "dataset_version": insights_manifest["dataset_version"],
                        "private_manifest_sha256": insights_sha,
                        "public_manifest_sha256": insights_public_sha,
                    },
                    "reports": {
                        "dataset_version": reports_manifest["dataset_version"],
                        "private_manifest_sha256": reports_sha,
                        "public_manifest_sha256": reports_public_sha,
                    },
                    "personas": {
                        "dataset_version": personas_manifest["dataset_version"],
                        "private_manifest_sha256": personas_sha,
                        "public_manifest_sha256": personas_public_sha,
                    },
                },
                "cases": {
                    "dataset_version": "case-catalog-v1",
                    "selected_count": 38,
                    "unverified_count": 12,
                    "approved_delta_count": 0,
                    "manifest_sha256": cases_sha,
                    "index_sha256": index_sha,
                    "seed_content_sha256": "a" * 64,
                    "legacy_unverified_content_sha256": "b" * 64,
                    "approved_delta_content_sha256": sha256(b"[]").hexdigest(),
                },
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "remote_write": False,
                "deploy": False,
                "live_send": False,
                "webhook_send": False,
                "schedule_change": False,
                "production_unchanged": True,
            },
        )
        self.paths["public_validation_receipt"] = public_receipt_path
        self.shas["public_validation_receipt"] = public_receipt_sha

        self.output_root = self.root / "closure-output"

    def build_args(self) -> argparse.Namespace:
        values: dict[str, Any] = {
            **{name: str(path) for name, path in self.paths.items()},
            **{f"expected_{name}_sha256": digest for name, digest in self.shas.items()},
            "output_root": str(self.output_root),
        }
        return argparse.Namespace(**values)


class CandidateDataClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build(self) -> tuple[argparse.Namespace, dict[str, Any]]:
        args = self.fixture.build_args()
        result = builder.build_candidate_data_closure(args)
        return args, result

    def _validator_args(
        self, build_args: argparse.Namespace, result: dict[str, Any]
    ) -> argparse.Namespace:
        values = vars(build_args).copy()
        values.pop("output_root")
        values.update(
            {
                "candidate_root": result["candidate_root"],
                "expected_candidate_data_manifest_sha256": result[
                    "candidate_data_manifest_sha256"
                ],
                "expected_reconciliation_sha256": result[
                    "reconciliation_sha256"
                ],
            }
        )
        return argparse.Namespace(**values)

    def test_build_validate_no_change_and_private_modes(self) -> None:
        build_args, result = self._build()
        self.assertEqual(result["status"], "created")
        candidate_root = Path(result["candidate_root"])
        self.assertEqual(stat.S_IMODE(candidate_root.stat().st_mode), 0o700)
        reconciliation_path = candidate_root / "candidate-data-reconciliation-ledger.jsonl"
        manifest_path = candidate_root / "candidate-data-manifest.json"
        self.assertEqual(stat.S_IMODE(reconciliation_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
        source_copy = candidate_root / "source-freeze-manifest.json"
        self.assertEqual(stat.S_IMODE(source_copy.stat().st_mode), 0o600)
        self.assertEqual(
            source_copy.read_bytes(),
            self.fixture.paths["source_freeze_manifest"].read_bytes(),
        )
        for name in builder.LEDGER_NAMES:
            copied = candidate_root / name
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
            self.assertEqual(
                copied.read_bytes(),
                (self.fixture.paths["candidate_ledger_root"] / name).read_bytes(),
            )
        reconciliation = json.loads(reconciliation_path.read_text())
        self.assertNotIn("reconciliation_sha256", reconciliation)
        self.assertNotIn("candidate_data_manifest_sha256", reconciliation)

        validation_args = self._validator_args(build_args, result)
        validated = validator.validate_candidate_data_closure(validation_args)
        self.assertEqual(validated["status"], "created")
        self.assertTrue(validated["production_unchanged"])
        receipt_path = Path(validated["receipt_path"])
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        self.assertEqual(
            validator.validate_candidate_data_closure(validation_args)["status"],
            "no_change",
        )
        self.assertEqual(builder.build_candidate_data_closure(build_args)["status"], "no_change")

    def test_reconciliation_self_hash_is_rejected(self) -> None:
        build_args, result = self._build()
        candidate_root = Path(result["candidate_root"])
        reconciliation_path = candidate_root / "candidate-data-reconciliation-ledger.jsonl"
        manifest_path = candidate_root / "candidate-data-manifest.json"
        reconciliation = json.loads(reconciliation_path.read_text())
        reconciliation["reconciliation_sha256"] = "f" * 64
        reconciliation_sha = _write_json(reconciliation_path, reconciliation)
        manifest = json.loads(manifest_path.read_text())
        manifest["reconciliation"].update(
            {
                "bytes": reconciliation_path.stat().st_size,
                "sha256": reconciliation_sha,
            }
        )
        manifest_sha = _write_json(manifest_path, manifest)
        validation_args = self._validator_args(build_args, result)
        validation_args.expected_candidate_data_manifest_sha256 = manifest_sha
        validation_args.expected_reconciliation_sha256 = reconciliation_sha
        with self.assertRaisesRegex(
            validator.CandidateDataClosureValidationError,
            "reconciliation_self_hash_present",
        ):
            validator.validate_candidate_data_closure(validation_args)

    def test_ledger_tamper_fails_closed(self) -> None:
        args = self.fixture.build_args()
        path = self.fixture.paths["candidate_ledger_root"] / "coverage-work-ledger.jsonl"
        path.write_bytes(path.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(
            builder.CandidateDataClosureError, "ledger_file_binding_invalid"
        ):
            builder.build_candidate_data_closure(args)

    def test_existing_output_collision_fails_closed(self) -> None:
        args, result = self._build()
        path = Path(result["candidate_root"]) / "candidate-data-reconciliation-ledger.jsonl"
        path.write_bytes(path.read_bytes() + b" ")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(
            builder.CandidateDataClosureError,
            "candidate_publication_immutable_collision",
        ):
            builder.build_candidate_data_closure(args)

    def test_copied_ledger_tamper_fails_independent_validation(self) -> None:
        build_args, result = self._build()
        copied = Path(result["candidate_root"]) / "coverage-work-ledger.jsonl"
        copied.write_bytes(copied.read_bytes() + b"{}\n")
        os.chmod(copied, 0o600)
        validation_args = self._validator_args(build_args, result)
        with self.assertRaisesRegex(
            validator.CandidateDataClosureValidationError,
            "copied_ledger_drift",
        ):
            validator.validate_candidate_data_closure(validation_args)

    def test_copied_ledger_collision_blocks_builder_no_change(self) -> None:
        args, result = self._build()
        copied = Path(result["candidate_root"]) / "post-identity-delta-ledger.jsonl"
        copied.write_bytes(copied.read_bytes() + b" ")
        os.chmod(copied, 0o600)
        with self.assertRaisesRegex(
            builder.CandidateDataClosureError,
            "candidate_publication_immutable_collision",
        ):
            builder.build_candidate_data_closure(args)

    def test_expected_sha_drift_fails_closed(self) -> None:
        args = self.fixture.build_args()
        args.expected_cases_index_sha256 = "0" * 64
        with self.assertRaisesRegex(
            builder.CandidateDataClosureError, "cases_index_sha256_mismatch"
        ):
            builder.build_candidate_data_closure(args)

    def test_side_effect_boundary_fails_closed(self) -> None:
        args = self.fixture.build_args()
        code_path = self.fixture.paths["code_freeze_manifest"]
        code = json.loads(code_path.read_text())
        code["boundaries"]["provider_call"] = True
        args.expected_code_freeze_manifest_sha256 = _write_json(code_path, code)
        with self.assertRaisesRegex(
            builder.CandidateDataClosureError,
            "code_freeze_boundaries_invalid",
        ):
            builder.build_candidate_data_closure(args)

    def test_code_root_file_tamper_fails_builder_and_validator(self) -> None:
        build_args, result = self._build()
        code_file = (
            self.fixture.paths["code_root"]
            / builder.CODE_ALLOWLIST[0]
        )
        code_file.write_bytes(code_file.read_bytes() + b"tamper")
        with self.assertRaisesRegex(
            builder.CandidateDataClosureError,
            "code_file_binding_invalid",
        ):
            builder.build_candidate_data_closure(build_args)
        validation_args = self._validator_args(build_args, result)
        with self.assertRaisesRegex(
            validator.CandidateDataClosureValidationError,
            "code_file_binding_invalid",
        ):
            validator.validate_candidate_data_closure(validation_args)


if __name__ == "__main__":
    unittest.main()
