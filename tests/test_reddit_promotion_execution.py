from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any
import unittest

from scripts import build_reddit_promotion_packet as packet_builder
from scripts import build_reddit_promotion_permit as permit_builder
from scripts import promote_reddit_candidate as promotion_wrapper
from scripts import validate_reddit_promotion_execution_bundle as live_bundle


LIVE_WRAPPER = Path(__file__).resolve().parents[1] / "scripts/promote_insights_tencent.sh"
EXPECTED_HOST_FINGERPRINT = "SHA256:LIiSdEy34t6nQCaOxrZ5BI0OlskdFOTrkPsFMd/KgDY"


def write_json(path: Path, value: object, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_bytes(packet_builder.canonical_file_bytes(value))
    os.chmod(path, mode)


def fake_live_transport(
    root: Path,
    *,
    now_utc: str = "2026-07-15T10:02:00Z",
    fingerprint: str = EXPECTED_HOST_FINGERPRINT,
    runner_status: int = 0,
) -> tuple[dict[str, str], Path]:
    root.mkdir(parents=True, exist_ok=True)
    binaries = root / "fake-live-bin"
    binaries.mkdir()
    log = root / "live-transport.log"

    def executable(name: str, source: str) -> None:
        path = binaries / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)

    executable(
        "date",
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$FAKE_NOW_UTC\"\n",
    )
    executable(
        "ssh-keyscan",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "printf '%s\\n' '101.34.52.232 ssh-ed25519 AAAAC3NzaFixture'\n",
    )
    executable(
        "ssh-keygen",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "printf '256 %s 101.34.52.232 (ED25519)\\n' \"$FAKE_HOST_FINGERPRINT\"\n",
    )
    executable(
        "scp",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'SCP\t%s\n' "$*" >>"$FAKE_TRANSPORT_LOG"
exit 0
""",
    )
    executable(
        "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
payload="$(cat)"
args="$*"
operation=UNKNOWN
if [[ "$args" == *"bash -s -- /opt/reddit-voc-insights-site/runtime/.promotion-"* ]]; then
  operation=RUN
elif [[ "$args" == *"bash -s -- "* ]]; then
  operation=CREATE
elif [[ "$args" == *"sudo -n python3 - /tmp/reddit-voc-promotion-upload."* && "$args" == *" release.tgz "* ]]; then
  operation=SEAL
elif [[ "$args" == *"sudo -n python3 - /tmp/reddit-voc-promotion-upload."* ]]; then
  operation=CLEAN_UPLOAD
elif [[ "$args" == *"sudo -n python3 - /opt/reddit-voc-insights-site/runtime/.promotion-"* ]]; then
  operation=CLEAN_SEALED
fi
printf 'SSH\t%s\t%s\n' "$operation" "$args" >>"$FAKE_TRANSPORT_LOG"
case "$operation" in
  CREATE)
    printf '/tmp/reddit-voc-promotion-upload.%s.ABCDEF12\n' "$FAKE_PACKET_PREFIX"
    ;;
  SEAL)
    printf '/opt/reddit-voc-insights-site/runtime/.promotion-%s.ABCDEF123\n' "$FAKE_PACKET_PREFIX"
    ;;
  RUN)
    printf 'fake remote promotion receipt\n'
    exit "$FAKE_RUNNER_STATUS"
    ;;
esac
exit 0
""",
    )
    environment = dict(os.environ)
    environment.update(
        {
            "FAKE_HOST_FINGERPRINT": fingerprint,
            "FAKE_NOW_UTC": now_utc,
            "FAKE_RUNNER_STATUS": str(runner_status),
            "FAKE_TRANSPORT_LOG": str(log),
            "PATH": f"{binaries}:{environment['PATH']}",
        }
    )
    return environment, log


class PromotionFixture:
    release = "a" * 64
    current = "b" * 64
    expected_current_data_release = "reddit_voc_release_20260714_daily_v2"
    expected_current_data_pointer_sha = "c" * 64
    target_data_pointer_sha = "d" * 64
    data_release = "reddit_voc_release_20260715_70a917e5bdf0"
    generated = "2026-07-15T10:00:00Z"
    packet_expiry = "2026-07-15T11:00:00Z"

    def __init__(self, workspace: Path) -> None:
        self.root = workspace / "root"
        self.root.mkdir(mode=0o700)
        evidence = self.root / "evidence"
        evidence.mkdir(mode=0o700)
        self.artifacts: dict[str, Path] = {}
        for key in packet_builder.ARTIFACT_KEYS:
            path = evidence / f"{key}.json"
            path.write_bytes(f"{key}\n".encode())
            os.chmod(path, 0o600)
            self.artifacts[key] = path
        write_json(
            self.artifacts["release_manifest"],
            {
                "schema_version": packet_builder.RELEASE_SCHEMA_VERSION,
                "release_sha256": self.release,
                "target_platform": "linux/amd64",
                "current_release": {
                    "release_id": self.data_release,
                    "sha256": self.target_data_pointer_sha,
                },
            },
        )
        write_json(
            self.artifacts["production_baseline_receipt"],
            {
                "schema_version": packet_builder.BASELINE_SCHEMA_VERSION,
                "status": "passed",
                "evidence_grade": "L3-production-read-only",
                "observed_at_utc": "2026-07-15T09:59:00Z",
                "current_release_sha256": self.current,
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
                        "current_symlink": f"releases/{self.current}",
                        "data_file_count": 81,
                        "data_inventory_sha256": "e" * 64,
                        "data_total_bytes": 4096,
                        "health": "healthy",
                        "internal_pointer": self.expected_current_data_release,
                        "internal_pointer_sha256": (
                            self.expected_current_data_pointer_sha
                        ),
                        "internal_pointer_symlink": (
                            f"releases/{self.expected_current_data_release}"
                        ),
                        "internal_release_sha256": self.current,
                        "listener": "172.20.0.1:18338",
                        "mount_count": 1,
                        "network": "reddit_voc_insights_net",
                        "read_only_rootfs": True,
                        "release_label": self.current,
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
                                f"{self.current}/reddit-voc-insights-"
                                f"{self.current}.tar"
                            ),
                            "image_reference": f"reddit-voc-insights:{self.current}",
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
                                packet_builder.BASELINE_LOCK_PATHS.items()
                            )
                        },
                        "stable": True,
                    },
                    "one_shot_collectors_running": 0,
                    "one_shot_collectors_running_after": 0,
                    "observer_runtime": {
                        "contract": packet_builder.BASELINE_OBSERVER_RUNTIME_CONTRACT,
                        "contract_sha256": (
                            packet_builder.BASELINE_OBSERVER_RUNTIME_SHA256
                        ),
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
                        "data_release_id": self.expected_current_data_release,
                        "data_total_bytes": 4096,
                        "manifest_inventory_bound": True,
                        "pointer_sha256": self.expected_current_data_pointer_sha,
                        "site_manifest_sha256": "6" * 64,
                        "site_release_sha256": self.current,
                        "stable": True,
                    },
                    "site_release_manifest": {
                        "data_file_count": 81,
                        "data_inventory_sha256": "e" * 64,
                        "data_release_id": self.expected_current_data_release,
                        "data_total_bytes": 4096,
                        "manifest_sha256": "6" * 64,
                        "pointer_path": "data/reddit-voc/current-release.json",
                        "pointer_sha256": self.expected_current_data_pointer_sha,
                        "release_sha256": self.current,
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
        self.packet = private / "packet.json"
        self.permit = private / "permit.json"
        self.runtime_paths: dict[str, Path] = {}
        for key, filename in packet_builder.EXECUTION_RUNTIME_FILENAMES.items():
            path = self.root / "runtime" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"#!/usr/bin/env bash\n# exact fixture runtime: {key}\nexit 0\n",
                encoding="utf-8",
            )
            path.chmod(0o700)
            self.runtime_paths[key] = path
        packet_result = packet_builder.build_promotion_packet(
            artifact_root=self.root,
            artifact_paths=self.artifacts,
            execution_runtime_paths=self.runtime_paths,
            output=self.packet,
            site_url="https://reddit.lute-tlz-dddd.top",
            release_sha256=self.release,
            data_release_id=self.data_release,
            expected_current_release_sha256=self.current,
            expected_current_data_release_id=self.expected_current_data_release,
            expected_current_data_pointer_sha256=(
                self.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.target_data_pointer_sha,
            generated_at_utc=self.generated,
            expires_at_utc=self.packet_expiry,
            nonce="boss-visible-20260715-execution",
            max_baseline_age_seconds=900,
        )
        self.packet_sha = packet_result["packet_sha256"]

    def build_permit(self, **overrides: object) -> dict[str, Any]:
        values: dict[str, object] = {
            "artifact_root": self.root,
            "packet_path": self.packet,
            "packet_sha256": self.packet_sha,
            "release_sha256": self.release,
            "expected_current_release_sha256": self.current,
            "expected_current_data_release_id": self.expected_current_data_release,
            "expected_current_data_pointer_sha256": (
                self.expected_current_data_pointer_sha
            ),
            "target_data_pointer_sha256": self.target_data_pointer_sha,
            "authorization_id": "owner-auth-20260715-boss1",
            "authorized_at_utc": "2026-07-15T10:01:00Z",
            "expires_at_utc": "2026-07-15T10:30:00Z",
            "owner_confirmation": permit_builder.OWNER_CONFIRMATION,
            "output": self.permit,
        }
        values.update(overrides)
        return permit_builder.build_promotion_permit(**values)  # type: ignore[arg-type]


class PromotionPermitTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = PromotionFixture(Path(temporary.name))

    def test_permit_is_canonical_private_exact_and_unconsumed(self) -> None:
        result = self.fixture.build_permit()
        raw = self.fixture.permit.read_bytes()
        permit = json.loads(raw)
        self.assertEqual(raw, permit_builder.canonical_bytes(permit))
        self.assertEqual(stat.S_IMODE(self.fixture.permit.stat().st_mode), 0o600)
        self.assertEqual(result["permit_sha256"], sha256(raw).hexdigest())
        self.assertTrue(permit["authorization"])
        self.assertFalse(permit["consumed"])
        self.assertEqual(permit["packet"]["packet_sha256"], self.fixture.packet_sha)
        self.assertEqual(permit["packet"]["release_sha256"], self.fixture.release)
        packet = json.loads(self.fixture.packet.read_text(encoding="utf-8"))
        self.assertEqual(
            permit["packet"]["execution_runtime"], packet["execution_runtime"]
        )

        validated = permit_builder.validate_promotion_permit(
            artifact_root=self.fixture.root,
            permit_path=self.fixture.permit,
            expected_permit_sha256=result["permit_sha256"],
            packet_path=self.fixture.packet,
            expected_packet_sha256=self.fixture.packet_sha,
            expected_release_sha256=self.fixture.release,
            expected_current_release_sha256=self.fixture.current,
            expected_current_data_release_id=(
                self.fixture.expected_current_data_release
            ),
            expected_current_data_pointer_sha256=(
                self.fixture.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
            now_utc="2026-07-15T10:02:00Z",
        )
        self.assertEqual(validated["status"], "passed")
        self.assertFalse(validated["consumed"])
        self.assertEqual(permit["scope"], "insights_site_and_data_current")
        self.assertEqual(
            permit["packet"]["expected_current_data_release_id"],
            self.fixture.expected_current_data_release,
        )
        self.assertEqual(
            permit["packet"]["expected_current_data_pointer_sha256"],
            self.fixture.expected_current_data_pointer_sha,
        )
        self.assertEqual(
            permit["packet"]["target_data_pointer_sha256"],
            self.fixture.target_data_pointer_sha,
        )

    def test_requires_explicit_owner_confirmation_and_exact_release(self) -> None:
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "owner_confirmation"):
            self.fixture.build_permit(owner_confirmation="continue")
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "binding_mismatch"):
            self.fixture.build_permit(release_sha256="c" * 64)
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "binding_mismatch"):
            self.fixture.build_permit(
                expected_current_data_release_id="reddit_voc_release_wrong_old_data"
            )
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "binding_mismatch"):
            self.fixture.build_permit(expected_current_data_pointer_sha256="0" * 64)
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "binding_mismatch"):
            self.fixture.build_permit(target_data_pointer_sha256="0" * 64)

    def test_rejects_expired_consumed_and_tampered_permit(self) -> None:
        result = self.fixture.build_permit()
        kwargs = {
            "artifact_root": self.fixture.root,
            "permit_path": self.fixture.permit,
            "expected_permit_sha256": result["permit_sha256"],
            "packet_path": self.fixture.packet,
            "expected_packet_sha256": self.fixture.packet_sha,
            "expected_release_sha256": self.fixture.release,
            "expected_current_release_sha256": self.fixture.current,
            "expected_current_data_release_id": (
                self.fixture.expected_current_data_release
            ),
            "expected_current_data_pointer_sha256": (
                self.fixture.expected_current_data_pointer_sha
            ),
            "target_data_pointer_sha256": self.fixture.target_data_pointer_sha,
        }
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "expired"):
            permit_builder.validate_promotion_permit(
                **kwargs, now_utc="2026-07-15T10:30:00Z"
            )

        permit = json.loads(self.fixture.permit.read_text())
        permit["consumed"] = True
        self.fixture.permit.write_bytes(permit_builder.canonical_bytes(permit))
        os.chmod(self.fixture.permit, 0o600)
        tampered_sha = sha256(self.fixture.permit.read_bytes()).hexdigest()
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "authorization_invalid"):
            permit_builder.validate_promotion_permit(
                **{**kwargs, "expected_permit_sha256": tampered_sha},
                now_utc="2026-07-15T10:02:00Z",
            )

    def test_rejects_tampered_data_binding_even_with_matching_file_sha(self) -> None:
        self.fixture.build_permit()
        permit = json.loads(self.fixture.permit.read_text(encoding="utf-8"))
        permit["packet"]["expected_current_data_pointer_sha256"] = "0" * 64
        self.fixture.permit.write_bytes(permit_builder.canonical_bytes(permit))
        os.chmod(self.fixture.permit, 0o600)
        tampered_sha = sha256(self.fixture.permit.read_bytes()).hexdigest()
        with self.assertRaisesRegex(
            permit_builder.PromotionPermitError, "binding_mismatch"
        ):
            permit_builder.validate_promotion_permit(
                artifact_root=self.fixture.root,
                permit_path=self.fixture.permit,
                expected_permit_sha256=tampered_sha,
                packet_path=self.fixture.packet,
                expected_packet_sha256=self.fixture.packet_sha,
                expected_release_sha256=self.fixture.release,
                expected_current_release_sha256=self.fixture.current,
                expected_current_data_release_id=(
                    self.fixture.expected_current_data_release
                ),
                expected_current_data_pointer_sha256=(
                    self.fixture.expected_current_data_pointer_sha
                ),
                target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
                now_utc="2026-07-15T10:02:00Z",
            )

    def test_rejects_tampered_runtime_binding_even_with_matching_permit_sha(self) -> None:
        self.fixture.build_permit()
        permit = json.loads(self.fixture.permit.read_text(encoding="utf-8"))
        permit["packet"]["execution_runtime"]["remote_rollback"]["sha256"] = (
            "0" * 64
        )
        self.fixture.permit.write_bytes(permit_builder.canonical_bytes(permit))
        os.chmod(self.fixture.permit, 0o600)
        tampered_sha = sha256(self.fixture.permit.read_bytes()).hexdigest()
        with self.assertRaisesRegex(
            permit_builder.PromotionPermitError, "binding_mismatch"
        ):
            permit_builder.validate_promotion_permit(
                artifact_root=self.fixture.root,
                permit_path=self.fixture.permit,
                expected_permit_sha256=tampered_sha,
                packet_path=self.fixture.packet,
                expected_packet_sha256=self.fixture.packet_sha,
                expected_release_sha256=self.fixture.release,
                expected_current_release_sha256=self.fixture.current,
                expected_current_data_release_id=(
                    self.fixture.expected_current_data_release
                ),
                expected_current_data_pointer_sha256=(
                    self.fixture.expected_current_data_pointer_sha
                ),
                target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
                now_utc="2026-07-15T10:02:00Z",
            )

    def test_permit_expiry_cannot_outlive_packet_and_rerun_is_immutable(self) -> None:
        with self.assertRaisesRegex(permit_builder.PromotionPermitError, "binding_mismatch"):
            self.fixture.build_permit(expires_at_utc="2026-07-15T11:01:00Z")
        first = self.fixture.build_permit()
        before = self.fixture.permit.stat().st_mtime_ns
        second = self.fixture.build_permit()
        self.assertEqual(first["permit_sha256"], second["permit_sha256"])
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(self.fixture.permit.stat().st_mtime_ns, before)

    def test_permit_cli_requires_and_reports_data_bindings(self) -> None:
        output = self.fixture.root / "private" / "permit-cli.json"
        command = [
            sys.executable,
            "scripts/build_reddit_promotion_permit.py",
            "--artifact-root",
            str(self.fixture.root),
            "--packet",
            str(self.fixture.packet),
            "--packet-sha256",
            self.fixture.packet_sha,
            "--release-sha256",
            self.fixture.release,
            "--expected-current-release-sha256",
            self.fixture.current,
            "--expected-current-data-release-id",
            self.fixture.expected_current_data_release,
            "--expected-current-data-pointer-sha256",
            self.fixture.expected_current_data_pointer_sha,
            "--target-data-pointer-sha256",
            self.fixture.target_data_pointer_sha,
            "--authorization-id",
            "owner-auth-20260715-cli1",
            "--authorized-at-utc",
            "2026-07-15T10:01:00Z",
            "--expires-at-utc",
            "2026-07-15T10:30:00Z",
            "--owner-confirmation",
            permit_builder.OWNER_CONFIRMATION,
            "--output",
            str(output),
        ]
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["expected_current_data_release_id"],
            self.fixture.expected_current_data_release,
        )
        self.assertEqual(
            result["expected_current_data_pointer_sha256"],
            self.fixture.expected_current_data_pointer_sha,
        )
        self.assertEqual(
            result["target_data_pointer_sha256"],
            self.fixture.target_data_pointer_sha,
        )

        validation = subprocess.run(
            [
                sys.executable,
                "scripts/validate_reddit_promotion_permit.py",
                "--artifact-root",
                str(self.fixture.root),
                "--permit",
                str(output),
                "--permit-sha256",
                result["permit_sha256"],
                "--packet",
                str(self.fixture.packet),
                "--packet-sha256",
                self.fixture.packet_sha,
                "--release-sha256",
                self.fixture.release,
                "--expected-current-release-sha256",
                self.fixture.current,
                "--expected-current-data-release-id",
                self.fixture.expected_current_data_release,
                "--expected-current-data-pointer-sha256",
                self.fixture.expected_current_data_pointer_sha,
                "--target-data-pointer-sha256",
                self.fixture.target_data_pointer_sha,
                "--now-utc",
                "2026-07-15T10:02:00Z",
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        validated = json.loads(validation.stdout)
        self.assertEqual(validated["status"], "passed")
        self.assertEqual(
            validated["expected_current_data_release_id"],
            self.fixture.expected_current_data_release,
        )


class PromotionExecutionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = PromotionFixture(Path(temporary.name))
        self.permit_result = self.fixture.build_permit()
        packet = json.loads(self.fixture.packet.read_text(encoding="utf-8"))
        transfer = packet["artifacts"]["transfer_tgz"]
        self.archive = self.fixture.root / transfer["path"]
        self.archive_sha = str(transfer["sha256"])
        self.runner = self.fixture.runtime_paths["remote_promotion_runner"]
        self.installer = self.fixture.runtime_paths["remote_installer"]
        self.rollback = self.fixture.runtime_paths["remote_rollback"]
        self.runner_sha = sha256(self.runner.read_bytes()).hexdigest()
        self.installer_sha = sha256(self.installer.read_bytes()).hexdigest()
        self.rollback_sha = sha256(self.rollback.read_bytes()).hexdigest()
        self.output = self.fixture.root / "private" / "execution.json"

    def build_execution(self, **overrides: object) -> dict[str, Any]:
        values: dict[str, object] = {
            "artifact_root": self.fixture.root,
            "packet_path": self.fixture.packet,
            "packet_sha256": self.fixture.packet_sha,
            "permit_path": self.fixture.permit,
            "permit_sha256": self.permit_result["permit_sha256"],
            "release_archive_path": self.archive,
            "release_archive_sha256": self.archive_sha,
            "remote_runner_path": self.runner,
            "remote_runner_sha256": self.runner_sha,
            "remote_installer_path": self.installer,
            "remote_installer_sha256": self.installer_sha,
            "remote_rollback_path": self.rollback,
            "remote_rollback_sha256": self.rollback_sha,
            "release_sha256": self.fixture.release,
            "expected_current_release_sha256": self.fixture.current,
            "expected_current_data_release_id": (
                self.fixture.expected_current_data_release
            ),
            "expected_current_data_pointer_sha256": (
                self.fixture.expected_current_data_pointer_sha
            ),
            "target_data_pointer_sha256": self.fixture.target_data_pointer_sha,
            "now_utc": "2026-07-15T10:02:00Z",
            "output": self.output,
        }
        values.update(overrides)
        return promotion_wrapper.build_promotion_execution_contract(
            **values  # pyright: ignore[reportArgumentType]
        )

    def test_execution_contract_binds_exact_twelve_argument_runner_argv(self) -> None:
        result = self.build_execution()
        self.assertEqual(result["remote_runner"]["argument_count"], 12)
        self.assertEqual(
            [row["name"] for row in result["runner_argv_contract"]],
            list(promotion_wrapper.RUNNER_ARGUMENT_NAMES),
        )
        self.assertEqual(
            [row["name"] for row in result["runner_argv_contract"]][-3:],
            [
                "expected_current_data_release_id",
                "expected_current_data_pointer_sha256",
                "target_data_pointer_sha256",
            ],
        )
        self.assertEqual(
            result["bindings"]["expected_current_data_release_id"],
            self.fixture.expected_current_data_release,
        )
        self.assertEqual(
            result["bindings"]["expected_current_data_pointer_sha256"],
            self.fixture.expected_current_data_pointer_sha,
        )
        self.assertEqual(
            result["bindings"]["target_data_pointer_sha256"],
            self.fixture.target_data_pointer_sha,
        )
        self.assertEqual(
            result["execution_runtime"],
            json.loads(self.fixture.packet.read_text())["execution_runtime"],
        )
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_live_bundle_validator_reopens_all_six_exact_sources(self) -> None:
        execution = self.build_execution()
        result = live_bundle.validate_bundle(
            artifact_root=self.fixture.root,
            execution_path=self.output,
            execution_sha256=execution["execution_contract_sha256"],
            packet_path=self.fixture.packet,
            packet_sha256=self.fixture.packet_sha,
            permit_path=self.fixture.permit,
            permit_sha256=self.permit_result["permit_sha256"],
            now_utc="2026-07-15T10:02:00Z",
        )
        self.assertEqual(result["status"], "passed_local_exact_bundle")
        self.assertEqual(
            set(result["sources"]),
            {"archive", "packet", "permit", "runner", "installer", "rollback"},
        )
        self.assertEqual(
            {row["sealed_name"] for row in result["sources"].values()},
            set(live_bundle.SEALED_NAMES.values()),
        )
        self.assertEqual(
            result["runner_arguments"]["release_sha256"],
            self.fixture.release,
        )

    def test_live_bundle_validator_rejects_runtime_drift_and_exact_expiry(self) -> None:
        execution = self.build_execution()
        self.runner.write_text("#!/usr/bin/env bash\nexit 91\n", encoding="utf-8")
        with self.assertRaisesRegex(
            live_bundle.PromotionBundleError,
            "remote_promotion_runner_(bytes|sha256)_mismatch",
        ):
            live_bundle.validate_bundle(
                artifact_root=self.fixture.root,
                execution_path=self.output,
                execution_sha256=execution["execution_contract_sha256"],
                packet_path=self.fixture.packet,
                packet_sha256=self.fixture.packet_sha,
                permit_path=self.fixture.permit,
                permit_sha256=self.permit_result["permit_sha256"],
                now_utc="2026-07-15T10:02:00Z",
            )

        self.runner.write_text(
            "#!/usr/bin/env bash\n"
            "# exact fixture runtime: remote_promotion_runner\n"
            "exit 0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            live_bundle.PromotionBundleError,
            "expired",
        ):
            live_bundle.validate_bundle(
                artifact_root=self.fixture.root,
                execution_path=self.output,
                execution_sha256=execution["execution_contract_sha256"],
                packet_path=self.fixture.packet,
                packet_sha256=self.fixture.packet_sha,
                permit_path=self.fixture.permit,
                permit_sha256=self.permit_result["permit_sha256"],
                now_utc="2026-07-15T10:30:00Z",
            )

    def run_live_wrapper(
        self,
        execution: dict[str, Any],
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        environment["FAKE_PACKET_PREFIX"] = self.fixture.packet_sha[:12]
        return subprocess.run(
            [
                "bash",
                str(LIVE_WRAPPER),
                "release",
                "--artifact-root",
                str(self.fixture.root),
                "--execution-contract",
                str(self.output),
                "--execution-contract-sha256",
                execution["execution_contract_sha256"],
                "--packet",
                str(self.fixture.packet),
                "--packet-sha256",
                self.fixture.packet_sha,
                "--permit",
                str(self.fixture.permit),
                "--permit-sha256",
                self.permit_result["permit_sha256"],
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_live_wrapper_uses_fixed_host_root_sealer_and_fake_transport_only(self) -> None:
        execution = self.build_execution()
        environment, log = fake_live_transport(self.fixture.root)
        completed = self.run_live_wrapper(execution, environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([line for line in lines if line.startswith("SCP\t")]), 6)
        self.assertEqual(
            [line.split("\t", 2)[1] for line in lines if line.startswith("SSH\t")],
            ["CREATE", "SEAL", "CLEAN_UPLOAD", "RUN", "CLEAN_SEALED"],
        )
        self.assertTrue(
            all("ubuntu@101.34.52.232" in line for line in lines)
        )
        self.assertIn("controlled Reddit VOC promotion completed", completed.stdout)

        source = LIVE_WRAPPER.read_text(encoding="utf-8")
        self.assertIn(EXPECTED_HOST_FINGERPRINT, source)
        self.assertIn('REMOTE="ubuntu@101.34.52.232"', source)
        self.assertIn('runtime_root = Path("/opt/reddit-voc-insights-site/runtime")', source)
        self.assertIn("sudo -n python3", source)
        self.assertNotIn("--host", source)

    def test_live_wrapper_expiry_and_host_key_mismatch_block_before_ssh_scp(self) -> None:
        execution = self.build_execution()
        for case, environment in (
            (
                "exact_expiry",
                fake_live_transport(
                    self.fixture.root / "expiry-case",
                    now_utc="2026-07-15T10:30:00Z",
                )[0],
            ),
            (
                "host_key",
                fake_live_transport(
                    self.fixture.root / "host-key-case",
                    fingerprint="SHA256:wrong",
                )[0],
            ),
        ):
            with self.subTest(case=case):
                log = Path(environment["FAKE_TRANSPORT_LOG"])
                completed = self.run_live_wrapper(execution, environment)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(log.exists())

    def test_live_wrapper_preserves_sealed_bundle_when_remote_runner_fails(self) -> None:
        execution = self.build_execution()
        environment, log = fake_live_transport(
            self.fixture.root / "runner-failure-case",
            runner_status=91,
        )
        completed = self.run_live_wrapper(execution, environment)
        self.assertEqual(completed.returncode, 91)
        operations = [
            line.split("\t", 2)[1]
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.startswith("SSH\t")
        ]
        self.assertEqual(operations, ["CREATE", "SEAL", "CLEAN_UPLOAD", "RUN"])
        self.assertIn("root-sealed evidence retained", completed.stderr)

    def test_execution_contract_rejects_each_data_binding_mismatch(self) -> None:
        for name, value in (
            (
                "expected_current_data_release_id",
                "reddit_voc_release_wrong_old_data",
            ),
            ("expected_current_data_pointer_sha256", "0" * 64),
            ("target_data_pointer_sha256", "0" * 64),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    promotion_wrapper.PromotionExecutionError, "binding_mismatch"
                ):
                    self.build_execution(**{name: value, "output": None})

    def test_execution_validator_fails_closed_on_data_binding_tamper(self) -> None:
        self.build_execution()
        contract = json.loads(self.output.read_text(encoding="utf-8"))
        contract["bindings"]["target_data_pointer_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            promotion_wrapper.PromotionExecutionError,
            "runner_argv_binding_mismatch",
        ):
            promotion_wrapper.validate_promotion_execution_contract(contract)

    def test_execution_rejects_runtime_substitution_and_runtime_tamper(self) -> None:
        substitute = (
            self.fixture.root / "substitute" / "remote_promote_insights_v6.sh"
        )
        substitute.parent.mkdir()
        substitute.write_text("#!/usr/bin/env bash\nexit 91\n", encoding="utf-8")
        with self.assertRaisesRegex(
            promotion_wrapper.PromotionExecutionError,
            "remote_promotion_runner_(path|bytes|sha256)_mismatch",
        ):
            self.build_execution(
                remote_runner_path=substitute,
                remote_runner_sha256=sha256(substitute.read_bytes()).hexdigest(),
                output=None,
            )

        self.build_execution()
        contract = json.loads(self.output.read_text(encoding="utf-8"))
        contract["execution_runtime"]["remote_installer"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            promotion_wrapper.PromotionExecutionError,
            "execution_runtime_binding_mismatch",
        ):
            promotion_wrapper.validate_promotion_execution_contract(contract)

    def test_execution_cli_reports_twelve_argument_contract(self) -> None:
        cli_output = self.fixture.root / "private" / "execution-cli.json"
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/promote_reddit_candidate.py",
                "--artifact-root",
                str(self.fixture.root),
                "--packet",
                str(self.fixture.packet),
                "--packet-sha256",
                self.fixture.packet_sha,
                "--permit",
                str(self.fixture.permit),
                "--permit-sha256",
                str(self.permit_result["permit_sha256"]),
                "--release-archive",
                str(self.archive),
                "--release-archive-sha256",
                self.archive_sha,
                "--remote-runner",
                str(self.runner),
                "--remote-runner-sha256",
                self.runner_sha,
                "--remote-installer",
                str(self.installer),
                "--remote-installer-sha256",
                self.installer_sha,
                "--remote-rollback",
                str(self.rollback),
                "--remote-rollback-sha256",
                self.rollback_sha,
                "--release-sha256",
                self.fixture.release,
                "--expected-current-release-sha256",
                self.fixture.current,
                "--expected-current-data-release-id",
                self.fixture.expected_current_data_release,
                "--expected-current-data-pointer-sha256",
                self.fixture.expected_current_data_pointer_sha,
                "--target-data-pointer-sha256",
                self.fixture.target_data_pointer_sha,
                "--now-utc",
                "2026-07-15T10:02:00Z",
                "--output",
                str(cli_output),
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["remote_runner"]["argument_count"], 12)
        self.assertEqual(len(result["runner_argv_contract"]), 12)


if __name__ == "__main__":
    unittest.main()
