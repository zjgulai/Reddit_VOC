from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from typing import Any

from scripts import build_reddit_promotion_packet as builder


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(builder.canonical_file_bytes(value))


class Fixture:
    release_sha = "a" * 64
    expected_current = "b" * 64
    expected_current_data_release_id = "reddit_voc_release_20260714_daily_v2"
    expected_current_data_pointer_sha = "c" * 64
    target_data_pointer_sha = "d" * 64
    data_release_id = "reddit_voc_release_20260715_70a917e5bdf0"
    generated_at = "2026-07-15T10:00:00Z"
    expires_at = "2026-07-15T11:00:00Z"
    nonce = "boss-visible-20260715-0001"

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.root = workspace / "artifact-root"
        self.root.mkdir(mode=0o700)
        self.paths: dict[str, Path] = {}
        for key in builder.ARTIFACT_KEYS:
            path = self.root / "evidence" / f"{key}.bin"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"evidence:{key}\n".encode())
            self.paths[key] = path

        _write_json(
            self.paths["release_manifest"],
            {
                "schema_version": builder.RELEASE_SCHEMA_VERSION,
                "release_sha256": self.release_sha,
                "target_platform": "linux/amd64",
                "current_release": {
                    "release_id": self.data_release_id,
                    "sha256": self.target_data_pointer_sha,
                },
            },
        )
        _write_json(
            self.paths["production_baseline_receipt"],
            {
                "schema_version": builder.BASELINE_SCHEMA_VERSION,
                "status": "passed",
                "evidence_grade": "L3-production-read-only",
                "observed_at_utc": "2026-07-15T09:59:00Z",
                "current_release_sha256": self.expected_current,
                "observations": {
                    "candidate_container_count": 0,
                    "candidate_container_count_after": 0,
                    "candidate_container_residue_count": 0,
                    "candidate_container_residue_count_after": 0,
                    "candidate_listener_18339_count": 0,
                    "candidate_listener_18339_count_after": 0,
                    "collector": {
                        "container_id": "1" * 64,
                        "health": "healthy",
                        "restart_count": 0,
                    },
                    "cron": {"sha256": "f" * 64, "stable": True},
                    "cron_sha256": "f" * 64,
                    "database": {
                        "after": "1:2:3",
                        "before": "1:2:3",
                        "stable": True,
                    },
                    "insights": {
                        "container_id": "3" * 64,
                        "current_symlink": f"releases/{self.expected_current}",
                        "data_file_count": 81,
                        "data_inventory_sha256": "e" * 64,
                        "data_total_bytes": 4096,
                        "health": "healthy",
                        "internal_pointer": self.expected_current_data_release_id,
                        "internal_pointer_sha256": self.expected_current_data_pointer_sha,
                        "internal_pointer_symlink": (
                            f"releases/{self.expected_current_data_release_id}"
                        ),
                        "internal_release_sha256": self.expected_current,
                        "listener": "172.20.0.1:18338",
                        "mount_count": 1,
                        "network": "reddit_voc_insights_net",
                        "read_only_rootfs": True,
                        "release_label": self.expected_current,
                        "restart_count": 0,
                        "runtime_contract": {
                            "cap_add": [],
                            "cap_drop": ["ALL"],
                            "collector_listener_reachable": False,
                            "command": ["nginx", "-g", "daemon off;"],
                            "component_label": "insights-site",
                            "device_access": False,
                            "entrypoint": ["/docker-entrypoint.sh"],
                            "host_port_binding": {
                                "HostIp": "172.20.0.1",
                                "HostPort": "18338",
                            },
                            "image_id": "sha256:" + "7" * 64,
                            "image_archive_config_digest_verified": True,
                            "image_archive_path": (
                                "/opt/reddit-voc-insights-site/releases/"
                                f"{self.expected_current}/reddit-voc-insights-"
                                f"{self.expected_current}.tar"
                            ),
                            "image_reference": (
                                f"reddit-voc-insights:{self.expected_current}"
                            ),
                            "image_tag_id_verified": True,
                            "init": True,
                            "memory_bytes": 268435456,
                            "mount": {
                                "destination": "/srv/reddit-voc-data",
                                "propagation": "rprivate",
                                "read_only": True,
                                "source": "/opt/reddit-voc-insights-data",
                                "type": "bind",
                            },
                            "nano_cpus": 500000000,
                            "network": {
                                "driver": "bridge",
                                "icc": False,
                                "id": "8" * 64,
                                "internal": False,
                                "ip_masquerade": False,
                                "name": "reddit_voc_insights_net",
                            },
                            "network_attachment_id_verified": True,
                            "network_mode": "reddit_voc_insights_net",
                            "no_new_privileges": True,
                            "pid_namespace": "private",
                            "pids_limit": 100,
                            "privileged": False,
                            "read_only_rootfs": True,
                            "restart_policy": "unless-stopped",
                            "runtime": "runc",
                            "tmpfs_options": sorted(
                                {
                                    "rw", "noexec", "nosuid", "nodev",
                                    "size=32m", "uid=101", "gid=101",
                                    "mode=1777",
                                }
                            ),
                            "user": "101:101",
                        },
                        "user": "101:101",
                    },
                    "libretranslate": {
                        "container_id": "2" * 64,
                        "health": "healthy",
                        "restart_count": 0,
                    },
                    "locks": {
                        "identities": {
                            name: {
                                "device": 1,
                                "inode": index + 10,
                                "mode": "0600",
                                "nlink": 1,
                                "path": path,
                                "uid": 1000,
                            }
                            for index, (name, path) in enumerate(
                                builder.BASELINE_LOCK_PATHS.items()
                            )
                        },
                        "stable": True,
                    },
                    "one_shot_collectors_running": 0,
                    "one_shot_collectors_running_after": 0,
                    "observer_runtime": {
                        "contract": builder.BASELINE_OBSERVER_RUNTIME_CONTRACT,
                        "contract_sha256": builder.BASELINE_OBSERVER_RUNTIME_SHA256,
                        "uid": 1000,
                    },
                    "quiet_counts_stable": True,
                    "release_sha256s": {
                        "sha256": "4" * 64,
                        "stable": True,
                        "verified_after": True,
                        "verified_before": True,
                    },
                    "release_sha256sums_verified": True,
                    "report_network_containers_running": 0,
                    "report_network_containers_running_after": 0,
                    "report_pointer": {
                        "after": "4:5:6",
                        "before": "4:5:6",
                        "stable": True,
                    },
                    "running_containers": {
                        "count": 3,
                        "inventory_sha256": "5" * 64,
                        "protected_count": 2,
                        "protected_inventory_sha256": "9" * 64,
                        "protected_scope": (
                            "docker_ps_a_excluding_insights_transaction"
                        ),
                        "scope": "docker_ps_a",
                        "stable": True,
                    },
                    "shared_nginx": {"sha256": "0" * 64, "stable": True},
                    "shared_nginx_sha256": "0" * 64,
                    "site_data_tuple": {
                        "data_file_count": 81,
                        "data_inventory_sha256": "e" * 64,
                        "data_release_id": self.expected_current_data_release_id,
                        "data_total_bytes": 4096,
                        "manifest_inventory_bound": True,
                        "pointer_sha256": self.expected_current_data_pointer_sha,
                        "site_manifest_sha256": "6" * 64,
                        "site_release_sha256": self.expected_current,
                        "stable": True,
                    },
                    "site_release_manifest": {
                        "data_file_count": 81,
                        "data_inventory_sha256": "e" * 64,
                        "data_release_id": self.expected_current_data_release_id,
                        "data_total_bytes": 4096,
                        "manifest_sha256": "6" * 64,
                        "pointer_path": "data/reddit-voc/current-release.json",
                        "pointer_sha256": self.expected_current_data_pointer_sha,
                        "release_sha256": self.expected_current,
                        "served_exact": True,
                        "stable": True,
                    },
                },
                "production_unchanged": True,
                "remote_write": False,
            },
        )
        private = self.root / "private"
        private.mkdir(mode=0o700)
        self.output = private / "promotion-packet.json"
        self.runtime_paths: dict[str, Path] = {}
        for key, filename in builder.EXECUTION_RUNTIME_FILENAMES.items():
            path = self.root / "runtime" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"#!/usr/bin/env bash\n# exact fixture runtime: {key}\nexit 0\n",
                encoding="utf-8",
            )
            path.chmod(0o700)
            self.runtime_paths[key] = path

    def kwargs(self, **overrides: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "artifact_root": self.root,
            "artifact_paths": dict(self.paths),
            "execution_runtime_paths": dict(self.runtime_paths),
            "output": self.output,
            "site_url": "https://reddit.lute-tlz-dddd.top",
            "release_sha256": self.release_sha,
            "data_release_id": self.data_release_id,
            "expected_current_release_sha256": self.expected_current,
            "expected_current_data_release_id": self.expected_current_data_release_id,
            "expected_current_data_pointer_sha256": (
                self.expected_current_data_pointer_sha
            ),
            "target_data_pointer_sha256": self.target_data_pointer_sha,
            "generated_at_utc": self.generated_at,
            "expires_at_utc": self.expires_at,
            "nonce": self.nonce,
            "max_baseline_age_seconds": 900,
        }
        values.update(overrides)
        return values

    def build(self, **overrides: Any) -> dict[str, Any]:
        return builder.build_promotion_packet(**self.kwargs(**overrides))

    def v3_kwargs(self, *, mixed_key: str | None = None) -> dict[str, Any]:
        paths = dict(self.paths)
        for key in builder.V3_ARTIFACT_KEYS:
            value = {
                "schema_version": f"reddit_voc_fixture_{key}_v1",
                "status": "passed" if key.endswith("_receipt") else "candidate_built",
                "release_id": (
                    "reddit_voc_release_mixed_a1"
                    if key == mixed_key
                    else self.data_release_id
                ),
                "source_snapshot_id": "reddit_voc_snapshot_fixture_a1",
                "candidate_release_sha256": self.release_sha,
                "boundaries": dict(builder.V3_BOUNDARIES),
            }
            path = self.root / "v3" / f"{key}.json"
            _write_json(path, value)
            paths[key] = path
        return {
            "artifact_paths": paths,
            "v3_release_id": self.data_release_id,
            "v3_source_snapshot_id": "reddit_voc_snapshot_fixture_a1",
        }

    def v3_native_kwargs(self) -> dict[str, Any]:
        snapshot_id = "reddit_voc_snapshot_fixture_v3_a1"
        candidate_input = "c" * 64
        current_release_pointer_sha = sha256(b"current-release-v3").hexdigest()
        auxiliary_sha = sha256(b"brand-health-v3").hexdigest()
        paths = {
            key: self.paths[key]
            for key in builder.RELEASE_EVIDENCE_ARTIFACT_KEYS
            if key != "candidate_ui_validation_receipt"
        }
        paths["candidate_ui_validation_receipt"] = (
            self.root / "v3-native/candidate-ui-validation-receipt.json"
        )
        datasets: dict[str, dict[str, str]] = {}
        release_dataset_manifests: dict[str, dict[str, str]] = {}
        release_files: list[dict[str, Any]] = [
            {
                "bytes": 1,
                "path": "data/reddit-voc/current-release.json",
                "sha256": current_release_pointer_sha,
            },
            {
                "bytes": 1,
                "path": "data/reddit-voc/brand-health/manifest.json",
                "sha256": auxiliary_sha,
            },
        ]
        dataset_versions = {
            "base": "reddit_voc_site_snapshot_fixture_v3_a1",
            "insights": "reddit_voc_insights_fixture_v3_a1",
            "reports": "reddit_voc_reports_fixture_v3_a1",
            "personas": "reddit_voc_personas_fixture_v3_a1",
        }
        for name in ("base", "insights", "reports", "personas"):
            manifest_key = f"v3_{name}_manifest"
            receipt_key = f"v3_{name}_receipt"
            manifest_path = self.root / "v3-native" / f"{manifest_key}.json"
            receipt_path = self.root / "v3-native" / f"{receipt_key}.json"
            manifest = {
                "schema_version": builder.V3_DATASET_MANIFEST_SCHEMAS[name],
                "promotable": True,
                "boundaries": dict(builder.V3_BOUNDARIES),
            }
            if name == "personas":
                manifest.update(
                    {
                        "snapshot_id": dataset_versions[name],
                        "governed_signal_source_snapshot_id": snapshot_id,
                    }
                )
            else:
                manifest.update(
                    {
                        "dataset_version": dataset_versions[name],
                        "source_snapshot_id": snapshot_id,
                        "lineage_manifest_sha256": sha256(
                            f"lineage:{name}".encode()
                        ).hexdigest(),
                    }
                )
            _write_json(manifest_path, manifest)
            manifest_sha = sha256(manifest_path.read_bytes()).hexdigest()
            receipt = {
                "schema_version": builder.V3_DATASET_RECEIPT_SCHEMAS[name],
                "status": "passed" if name == "personas" else "passed_candidate_only",
                "promotable": True,
            }
            if name == "personas":
                receipt.update(
                    {
                        "manifest_sha256": manifest_sha,
                        **builder.V3_BOUNDARIES,
                    }
                )
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                receipt_path.write_text(
                    json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            else:
                receipt.update(
                    {
                        "bundle_manifest_sha256": manifest_sha,
                        "boundaries": dict(builder.V3_BOUNDARIES),
                    }
                )
                _write_json(receipt_path, receipt)
            receipt_sha = sha256(receipt_path.read_bytes()).hexdigest()
            paths[manifest_key] = manifest_path
            paths[receipt_key] = receipt_path
            public_manifest_relative_path = (
                f"public/data/reddit-voc/{dataset_versions[name]}/manifest.json"
            )
            release_manifest_path = public_manifest_relative_path.removeprefix("public/")
            datasets[name] = {
                "dataset_version": dataset_versions[name],
                "lineage_manifest_sha256": (
                    manifest_sha
                    if name == "personas"
                    else str(manifest["lineage_manifest_sha256"])
                ),
                "public_manifest_relative_path": public_manifest_relative_path,
                "public_manifest_sha256": manifest_sha,
                "validation_receipt_schema": builder.V3_DATASET_RECEIPT_SCHEMAS[name],
                "validation_receipt_sha256": receipt_sha,
            }
            release_dataset_manifests[name] = {
                "manifest_path": release_manifest_path,
                "public_manifest_sha256": manifest_sha,
                "lineage_manifest_sha256": datasets[name]["lineage_manifest_sha256"],
            }
            release_files.append(
                {"bytes": 1, "path": release_manifest_path, "sha256": manifest_sha}
            )

        lineage = {
            "auxiliary_public_manifests": [
                {
                    "relative_path": "public/data/reddit-voc/brand-health/manifest.json",
                    "sha256": auxiliary_sha,
                }
            ],
            "contract": builder.V3_FRONTEND_LINEAGE_CONTRACT,
            "current_release_pointer_sha256": current_release_pointer_sha,
            "source_snapshot_id": snapshot_id,
            "datasets": datasets,
        }
        source_manifest_path = self.root / "v3-native/frontend-source-manifest.json"
        source_receipt_path = self.root / "v3-native/frontend-source-receipt.json"
        source_stage_path = self.root / "v3-native/frontend-source-stage-receipt.json"
        _write_json(
            source_manifest_path,
            {
                "schema_version": builder.V3_FRONTEND_SOURCE_SCHEMA,
                "status": "frontend_source_frozen_local",
                "frontend_candidate_input_sha256": candidate_input,
                "upstream": {"v3_lineage": lineage},
                "boundaries": dict(builder.V3_BOUNDARIES),
            },
        )
        source_manifest_sha = sha256(source_manifest_path.read_bytes()).hexdigest()
        _write_json(
            source_receipt_path,
            {
                "schema_version": builder.V3_FRONTEND_RECEIPT_SCHEMA,
                "status": "passed_local_source_validation",
                "frontend_candidate_input_sha256": candidate_input,
                "frontend_source_manifest_sha256": source_manifest_sha,
                "v3_lineage": lineage,
                "boundaries": dict(builder.V3_BOUNDARIES),
            },
        )
        source_receipt_sha = sha256(source_receipt_path.read_bytes()).hexdigest()
        _write_json(
            source_stage_path,
            {
                "schema_version": builder.V3_FRONTEND_STAGE_RECEIPT_SCHEMA,
                "status": "source_stage_materialized_local",
                "frontend_candidate_input_sha256": candidate_input,
                "frontend_source_manifest_sha256": source_manifest_sha,
                "frontend_source_manifest_schema": builder.V3_FRONTEND_SOURCE_SCHEMA,
                "boundaries": dict(builder.V3_BOUNDARIES),
            },
        )
        paths.update(
            {
                "v3_frontend_source_manifest": source_manifest_path,
                "v3_frontend_source_receipt": source_receipt_path,
                "v3_frontend_source_stage_receipt": source_stage_path,
            }
        )
        frontend_source = {
            "contract_schema_version": builder.V3_FRONTEND_SOURCE_SCHEMA,
            "frontend_candidate_input_sha256": candidate_input,
            "manifest": {"sha256": source_manifest_sha},
            "validation_receipt": {"sha256": source_receipt_sha},
            "v3_lineage": lineage,
        }
        data_lineage = {
            "current_release": {
                "path": "data/reddit-voc/current-release.json",
                "release_id": self.data_release_id,
                "sha256": current_release_pointer_sha,
            },
            "dataset_manifests": release_dataset_manifests,
            "dataset_versions": dataset_versions,
        }
        _write_json(
            paths["release_manifest"],
            {
                "schema_version": builder.RELEASE_SCHEMA_VERSION,
                "release_sha256": self.release_sha,
                "target_platform": "linux/amd64",
                **data_lineage,
                "files": release_files,
                "frontend_source": frontend_source,
            },
        )
        _write_json(
            paths["build_receipt"],
            {
                "schema_version": "reddit_voc_insights_build_receipt_v1",
                "status": "passed_local_build",
                "release_sha256": self.release_sha,
                "frontend_source": frontend_source,
                "data_lineage": data_lineage,
            },
        )
        candidate_v3_artifact_shas = {
            key: sha256(paths[key].read_bytes()).hexdigest()
            for key in builder.V3_NATIVE_LINEAGE_ARTIFACT_KEYS
        }
        _write_json(
            paths["candidate_ui_validation_receipt"],
            {
                "schema_version": "reddit_voc_candidate_ui_validation_receipt_v2",
                "status": "passed_local_candidate_validation",
                "lineage": {
                    "build_contract_sha256": sha256(
                        paths["build_receipt"].read_bytes()
                    ).hexdigest(),
                },
                "release": {"release_sha256": self.release_sha},
                "deliverables": {
                    "image_tar_sha256": sha256(
                        paths["linux_amd64_image_tar"].read_bytes()
                    ).hexdigest(),
                    "transfer_tgz_sha256": sha256(
                        paths["transfer_tgz"].read_bytes()
                    ).hexdigest(),
                },
                "evidence": {
                    "browser_e2e_evidence_sha256": sha256(
                        paths["e2e_receipt"].read_bytes()
                    ).hexdigest(),
                    "container_evidence_sha256": sha256(
                        paths["local_container_smoke_receipt"].read_bytes()
                    ).hexdigest(),
                    "export_evidence_sha256": "d" * 64,
                    "security_evidence_sha256": "e" * 64,
                    "ui_validation_evidence_sha256": "f" * 64,
                },
                "v3_lineage": {
                    "artifact_sha256s": candidate_v3_artifact_shas,
                    "candidate_release_sha256": self.release_sha,
                    "release_id": self.data_release_id,
                    "source_snapshot_id": snapshot_id,
                },
                "boundaries": dict(builder.V3_BOUNDARIES),
            },
        )
        return {
            "artifact_paths": paths,
            "target_data_pointer_sha256": current_release_pointer_sha,
            "v3_release_id": self.data_release_id,
            "v3_source_snapshot_id": snapshot_id,
        }


class BuildRedditPromotionPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_builds_canonical_private_packet_with_explicit_debt(self) -> None:
        result = self.fixture.build()
        self.assertEqual(result["status"], "created")
        payload = self.fixture.output.read_bytes()
        packet = json.loads(payload)

        self.assertEqual(payload, builder.canonical_file_bytes(packet))
        self.assertEqual(stat.S_IMODE(self.fixture.output.stat().st_mode), 0o600)
        self.assertEqual(result["packet_sha256"], sha256(payload).hexdigest())
        self.assertEqual(set(packet["artifacts"]), set(builder.ARTIFACT_KEYS))
        self.assertFalse(packet["authorization"]["promotion_authorized"])
        self.assertFalse(packet["authorization"]["consumed"])
        self.assertFalse(packet["side_effects"]["deploy"])
        self.assertEqual(packet["deferred_debts"], builder.DEFERRED_DEBTS)
        self.assertEqual(packet["schema_version"], "reddit_voc_promotion_packet_v4")
        self.assertEqual(
            set(packet["execution_runtime"]),
            set(builder.EXECUTION_RUNTIME_KEYS),
        )
        for key, record in packet["execution_runtime"].items():
            runtime = self.fixture.root / record["path"]
            self.assertEqual(runtime, self.fixture.runtime_paths[key])
            self.assertEqual(record["bytes"], runtime.stat().st_size)
            self.assertEqual(record["sha256"], sha256(runtime.read_bytes()).hexdigest())
        self.assertEqual(
            packet["target"]["expected_current_data_release_id"],
            self.fixture.expected_current_data_release_id,
        )
        self.assertEqual(
            packet["target"]["expected_current_data_pointer_sha256"],
            self.fixture.expected_current_data_pointer_sha,
        )
        self.assertEqual(
            packet["target"]["target_data_pointer_sha256"],
            self.fixture.target_data_pointer_sha,
        )
        self.assertEqual(
            packet["rollback"],
            {
                "readiness_mode": "immediate_same_baseline_window",
                "ready": True,
                "scope": "insights_site_and_data_current",
                "shared_nginx_change_allowed": False,
                "target_data_file_count": 81,
                "target_data_inventory_sha256": "e" * 64,
                "target_data_pointer_sha256": (
                    self.fixture.expected_current_data_pointer_sha
                ),
                "target_data_release_id": (
                    self.fixture.expected_current_data_release_id
                ),
                "target_data_total_bytes": 4096,
                "target_release_manifest_sha256": "6" * 64,
                "target_release_sha256": self.fixture.expected_current,
                "target_release_sha256s_sha256": "4" * 64,
                "valid_until_utc": self.fixture.expires_at,
            },
        )
        baseline_cas = packet["production_baseline_cas"]
        self.assertEqual(
            baseline_cas["collector"],
            {
                "container_id": "1" * 64,
                "health": "healthy",
                "restart_count": 0,
            },
        )
        self.assertEqual(
            baseline_cas["insights"]["image_id"], "sha256:" + "7" * 64
        )
        self.assertEqual(baseline_cas["insights"]["network_id"], "8" * 64)
        self.assertEqual(
            baseline_cas["container_inventory"],
            {
                "count": 3,
                "protected_count": 2,
                "protected_sha256": "9" * 64,
                "sha256": "5" * 64,
            },
        )
        self.assertEqual(baseline_cas["database_identity"], "1:2:3")
        self.assertEqual(baseline_cas["report_pointer_identity"], "4:5:6")
        for action in (
            "stage_exact_insights_data_release",
            "compare_and_swap_only_insights_data_current",
            "persist_exact_rollback_authority_evidence",
            "rollback_only_insights_data_current",
        ):
            self.assertIn(action, packet["authorization"]["allowed_actions"])
        for key, record in packet["artifacts"].items():
            self.assertFalse(Path(record["path"]).is_absolute(), key)
            artifact = self.fixture.root / record["path"]
            self.assertEqual(record["bytes"], artifact.stat().st_size)
            self.assertEqual(record["sha256"], sha256(artifact.read_bytes()).hexdigest())

    def test_exact_rerun_is_no_change_and_collision_fails_closed(self) -> None:
        self.assertEqual(self.fixture.build()["status"], "created")
        self.assertEqual(self.fixture.output.stat().st_nlink, 1)
        self.assertEqual(
            list(
                self.fixture.output.parent.glob(
                    f".{self.fixture.output.name}.tmp-*"
                )
            ),
            [],
        )
        original_mtime = self.fixture.output.stat().st_mtime_ns
        self.assertEqual(self.fixture.build()["status"], "no_change")
        self.assertEqual(self.fixture.output.stat().st_mtime_ns, original_mtime)

        self.fixture.output.write_bytes(self.fixture.output.read_bytes() + b" ")
        os.chmod(self.fixture.output, 0o600)
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "promotion_packet_immutable_collision"
        ):
            self.fixture.build()

    def test_hardlinked_artifact_and_existing_output_fail_closed(self) -> None:
        artifact = self.fixture.paths["plan_a_manifest"]
        artifact_alias = self.fixture.workspace / "plan-a-manifest-alias.json"
        os.link(artifact, artifact_alias)
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "plan_a_manifest_unsafe"
        ):
            self.fixture.build()
        artifact_alias.unlink()

        self.assertEqual(self.fixture.build()["status"], "created")
        output_alias = self.fixture.workspace / "promotion-packet-alias.json"
        os.link(self.fixture.output, output_alias)
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "promotion_packet_unsafe"
        ):
            self.fixture.build()
        output_alias.unlink()

    def test_symlink_duplicate_and_escape_artifacts_are_rejected(self) -> None:
        target = self.fixture.workspace / "outside.bin"
        target.write_bytes(b"outside\n")
        linked = self.fixture.paths["plan_a_manifest"]
        linked.unlink()
        linked.symlink_to(target)
        with self.assertRaisesRegex(builder.PromotionPacketError, "plan_a_manifest_unsafe"):
            self.fixture.build()

        linked.unlink()
        linked.write_bytes(b"restored\n")
        duplicate = dict(self.fixture.paths)
        duplicate["plan_a_receipt"] = duplicate["plan_a_manifest"]
        with self.assertRaisesRegex(builder.PromotionPacketError, "artifact_path_duplicate"):
            self.fixture.build(artifact_paths=duplicate)

        escaped = dict(self.fixture.paths)
        escaped["plan_a_receipt"] = self.fixture.root / ".." / "outside.bin"
        with self.assertRaisesRegex(builder.PromotionPacketError, "path_invalid"):
            self.fixture.build(artifact_paths=escaped)

    def test_execution_runtime_is_required_unique_and_exactly_named(self) -> None:
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "execution_runtime_paths_contract_invalid"
        ):
            self.fixture.build(execution_runtime_paths={})

        duplicate = dict(self.fixture.runtime_paths)
        duplicate["remote_installer"] = duplicate["remote_promotion_runner"]
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "execution_runtime_path_duplicate"
        ):
            self.fixture.build(execution_runtime_paths=duplicate)

        wrong_name = self.fixture.root / "runtime" / "not-the-runner.sh"
        wrong_name.write_bytes(
            self.fixture.runtime_paths["remote_promotion_runner"].read_bytes()
        )
        mismatched = dict(self.fixture.runtime_paths)
        mismatched["remote_promotion_runner"] = wrong_name
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "execution_runtime_remote_promotion_runner_filename_invalid",
        ):
            self.fixture.build(execution_runtime_paths=mismatched)

    def test_release_and_fresh_l3_baseline_are_cross_checked(self) -> None:
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "release_manifest_contract_invalid"
        ):
            self.fixture.build(release_sha256="c" * 64)

        baseline = json.loads(
            self.fixture.paths["production_baseline_receipt"].read_text()
        )
        baseline["observed_at_utc"] = "2026-07-15T09:00:00Z"
        _write_json(self.fixture.paths["production_baseline_receipt"], baseline)
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

    def test_baseline_runtime_security_contract_is_required(self) -> None:
        baseline = json.loads(
            self.fixture.paths["production_baseline_receipt"].read_text()
        )
        runtime = baseline["observations"]["insights"]["runtime_contract"]
        runtime["privileged"] = True
        _write_json(self.fixture.paths["production_baseline_receipt"], baseline)
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

    def test_baseline_binds_an_absent_report_pointer_but_requires_database(self) -> None:
        baseline_path = self.fixture.paths["production_baseline_receipt"]
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["observations"]["report_pointer"] = {
            "after": "absent",
            "before": "absent",
            "stable": True,
        }
        _write_json(baseline_path, baseline)
        self.fixture.build()
        packet = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        self.assertEqual(
            packet["production_baseline_cas"]["report_pointer_identity"],
            "absent",
        )

        self.fixture.output.unlink()
        baseline["observations"]["database"] = {
            "after": "absent",
            "before": "absent",
            "stable": True,
        }
        _write_json(baseline_path, baseline)
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

    def test_data_pointer_identities_are_cross_checked(self) -> None:
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "release_manifest_contract_invalid"
        ):
            self.fixture.build(target_data_pointer_sha256="0" * 64)

        baseline = json.loads(
            self.fixture.paths["production_baseline_receipt"].read_text()
        )
        baseline["observations"]["insights"]["internal_pointer"] = (
            "reddit_voc_release_wrong_old_data"
        )
        _write_json(self.fixture.paths["production_baseline_receipt"], baseline)
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

        baseline["observations"]["insights"]["internal_pointer"] = (
            self.fixture.expected_current_data_release_id
        )
        baseline["observations"]["insights"]["internal_pointer_sha256"] = "0" * 64
        _write_json(self.fixture.paths["production_baseline_receipt"], baseline)
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

    def test_minimal_baseline_receipt_is_rejected(self) -> None:
        _write_json(
            self.fixture.paths["production_baseline_receipt"],
            {
                "schema_version": builder.BASELINE_SCHEMA_VERSION,
                "status": "passed",
                "evidence_grade": "L3-production-read-only",
                "observed_at_utc": "2026-07-15T09:59:00Z",
                "current_release_sha256": self.fixture.expected_current,
                "observations": {
                    "candidate_container_count": 0,
                    "candidate_listener_18339_count": 0,
                    "insights": {
                        "internal_pointer": (
                            self.fixture.expected_current_data_release_id
                        ),
                        "internal_pointer_sha256": (
                            self.fixture.expected_current_data_pointer_sha
                        ),
                    },
                    "one_shot_collectors_running": 0,
                },
                "production_unchanged": True,
                "remote_write": False,
            },
        )
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

    def test_baseline_rejects_mixed_site_data_tuple(self) -> None:
        baseline_path = self.fixture.paths["production_baseline_receipt"]
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["observations"]["site_release_manifest"]["data_release_id"] = (
            "reddit_voc_release_mixed_site_manifest"
        )
        _write_json(baseline_path, baseline)
        with self.assertRaisesRegex(
            builder.PromotionPacketError,
            "production_baseline_receipt_contract_invalid",
        ):
            self.fixture.build()

    def test_production_baseline_requires_quiet_exact_runtime_and_data_inventory(self) -> None:
        baseline_path = self.fixture.paths["production_baseline_receipt"]
        pristine = json.loads(baseline_path.read_text(encoding="utf-8"))
        mutations = (
            ("candidate_container_count", 1),
            ("candidate_listener_18339_count", 1),
            ("one_shot_collectors_running", 1),
        )
        for name, value in mutations:
            with self.subTest(name=name):
                baseline = json.loads(json.dumps(pristine))
                baseline["observations"][name] = value
                _write_json(baseline_path, baseline)
                with self.assertRaisesRegex(
                    builder.PromotionPacketError,
                    "production_baseline_receipt_contract_invalid",
                ):
                    self.fixture.build()

        for name, value in (
            ("mount_count", 2),
            ("user", "0:0"),
            ("read_only_rootfs", False),
            ("network", "bridge"),
            ("data_inventory_sha256", ""),
            ("data_file_count", 0),
            ("data_total_bytes", 0),
        ):
            with self.subTest(name=name):
                baseline = json.loads(json.dumps(pristine))
                baseline["observations"]["insights"][name] = value
                _write_json(baseline_path, baseline)
                with self.assertRaisesRegex(
                    builder.PromotionPacketError,
                    "production_baseline_receipt_contract_invalid",
                ):
                    self.fixture.build()
        _write_json(baseline_path, pristine)

    def test_output_must_remain_private_and_beneath_artifact_root(self) -> None:
        outside = self.fixture.workspace / "packet.json"
        with self.assertRaisesRegex(builder.PromotionPacketError, "path_escape"):
            self.fixture.build(output=outside)

        self.fixture.build()
        os.chmod(self.fixture.output, 0o644)
        with self.assertRaisesRegex(builder.PromotionPacketError, "mode_invalid"):
            self.fixture.build()

    def test_builder_and_validator_cli_round_trip(self) -> None:
        cli_output = self.fixture.root / "private" / "promotion-packet-cli.json"
        command = [
            sys.executable,
            "scripts/build_reddit_promotion_packet.py",
            "--artifact-root",
            str(self.fixture.root),
        ]
        for key in builder.ARTIFACT_KEYS:
            command.extend([f"--{key.replace('_', '-')}", str(self.fixture.paths[key])])
        for key, path in self.fixture.runtime_paths.items():
            command.extend([f"--{key.replace('_', '-')}", str(path)])
        command.extend(
            [
                "--output",
                str(cli_output),
                "--site-url",
                "https://reddit.lute-tlz-dddd.top",
                "--release-sha256",
                self.fixture.release_sha,
                "--data-release-id",
                self.fixture.data_release_id,
                "--expected-current-release-sha256",
                self.fixture.expected_current,
                "--expected-current-data-release-id",
                self.fixture.expected_current_data_release_id,
                "--expected-current-data-pointer-sha256",
                self.fixture.expected_current_data_pointer_sha,
                "--target-data-pointer-sha256",
                self.fixture.target_data_pointer_sha,
                "--generated-at-utc",
                self.fixture.generated_at,
                "--expires-at-utc",
                self.fixture.expires_at,
                "--nonce",
                "boss-visible-20260715-cli1",
                "--max-baseline-age-seconds",
                "900",
            ]
        )
        root = Path(__file__).resolve().parents[1]
        built = subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(built.stdout)
        self.assertEqual(result["status"], "created")

        validated = subprocess.run(
            [
                sys.executable,
                "scripts/validate_reddit_promotion_packet.py",
                "--artifact-root",
                str(self.fixture.root),
                "--packet",
                str(cli_output),
                "--expected-packet-sha256",
                result["packet_sha256"],
                "--now-utc",
                "2026-07-15T10:01:00Z",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        validation = json.loads(validated.stdout)
        self.assertEqual(validation["status"], "passed")
        self.assertFalse(validation["promotion_authorized"])

    def test_v2_packet_append_only_binds_all_v3_receipts_without_authorizing(self) -> None:
        result = self.fixture.build(**self.fixture.v3_kwargs())
        packet = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        self.assertEqual(packet["schema_version"], builder.SCHEMA_VERSION)
        self.assertEqual(
            set(packet["v3_lineage"]["artifact_sha256s"]),
            set(builder.V3_ARTIFACT_KEYS),
        )
        self.assertEqual(
            set(packet["artifacts"]),
            set(builder.ARTIFACT_KEYS) | set(builder.V3_ARTIFACT_KEYS),
        )
        self.assertFalse(packet["authorization"]["promotion_authorized"])
        self.assertFalse(result["promotion_authorized"])

    def test_v2_packet_rejects_mixed_v3_release(self) -> None:
        with self.assertRaisesRegex(builder.PromotionPacketError, "mixed_release"):
            self.fixture.build(**self.fixture.v3_kwargs(mixed_key="v3_metrics_receipt"))

    def test_native_v3_packet_replaces_plan_lineage_and_stays_unauthorized(self) -> None:
        result = self.fixture.build(**self.fixture.v3_native_kwargs())
        packet = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        self.assertEqual(set(packet["artifacts"]), set(builder.V3_NATIVE_ARTIFACT_KEYS))
        self.assertFalse(any(key.startswith("plan_") for key in packet["artifacts"]))
        self.assertEqual(
            set(packet["v3_lineage"]["artifact_sha256s"]),
            set(builder.V3_NATIVE_ARTIFACT_KEYS),
        )
        self.assertFalse(packet["authorization"]["promotion_authorized"])
        self.assertFalse(result["promotion_authorized"])

    def test_native_v3_cli_accepts_exact_native_set(self) -> None:
        native = self.fixture.v3_native_kwargs()
        paths = native["artifact_paths"]
        output = self.fixture.root / "private/promotion-packet-v3-native-cli.json"
        command = [
            sys.executable,
            "scripts/build_reddit_promotion_packet.py",
            "--artifact-root",
            str(self.fixture.root),
        ]
        for key in builder.RELEASE_EVIDENCE_ARTIFACT_KEYS:
            command.extend([f"--{key.replace('_', '-')}", str(paths[key])])
        for key in builder.V3_NATIVE_LINEAGE_ARTIFACT_KEYS:
            command.extend(["--v3-artifact", f"{key}={paths[key]}"])
        for key, path in self.fixture.runtime_paths.items():
            command.extend([f"--{key.replace('_', '-')}", str(path)])
        command.extend(
            [
                "--output",
                str(output),
                "--site-url",
                "https://reddit.lute-tlz-dddd.top",
                "--release-sha256",
                self.fixture.release_sha,
                "--data-release-id",
                self.fixture.data_release_id,
                "--expected-current-release-sha256",
                self.fixture.expected_current,
                "--expected-current-data-release-id",
                self.fixture.expected_current_data_release_id,
                "--expected-current-data-pointer-sha256",
                self.fixture.expected_current_data_pointer_sha,
                "--target-data-pointer-sha256",
                str(native["target_data_pointer_sha256"]),
                "--generated-at-utc",
                self.fixture.generated_at,
                "--expires-at-utc",
                self.fixture.expires_at,
                "--nonce",
                "boss-visible-20260715-native-cli",
                "--max-baseline-age-seconds",
                "900",
                "--v3-release-id",
                str(native["v3_release_id"]),
                "--v3-source-snapshot-id",
                str(native["v3_source_snapshot_id"]),
            ]
        )
        built = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(built.stdout)
        self.assertEqual(result["status"], "created")
        packet = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(set(packet["artifacts"]), set(builder.V3_NATIVE_ARTIFACT_KEYS))

    def test_native_v3_rejects_release_pointer_substitution(self) -> None:
        native = self.fixture.v3_native_kwargs()
        release_path = native["artifact_paths"]["release_manifest"]
        release = json.loads(release_path.read_text(encoding="utf-8"))
        release["current_release"]["sha256"] = "0" * 64
        _write_json(release_path, release)
        with self.assertRaisesRegex(
            builder.PromotionPacketError, "release_manifest_contract_invalid"
        ):
            self.fixture.build(**native)


if __name__ == "__main__":
    unittest.main()
