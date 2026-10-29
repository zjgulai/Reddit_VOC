from __future__ import annotations

import json
import fcntl
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from scripts import report_control
from scripts.build_daily_report_release import build_release
from reddit_voc.provider_attempt_ledger import ProviderAttemptLedger, ZERO_TIP
from scripts.report_noninterference import (
    capture_from_mapping,
    capture_host_facts,
    compare_host_captures,
    compare_snapshots,
)


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "scripts/server_daily_report_admin.sh"
UPDATER = ROOT / "scripts/server_update_daily_report_runtime_env.sh"


class DailyReportOpsTests(unittest.TestCase):
    def test_host_commit_accepts_closed_v2_provider_ledger_without_legacy_log(
        self,
    ) -> None:
        """Formal Provider v2 evidence must be sufficient for the prepared commit."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider_root = root / "provider-attempts"
            authorization_id = "provider-auth-v2-only"
            prepare_id = "prepare-auth-v2-only"
            release_sha = "a" * 64
            runtime_sha = "b" * 64
            run_id = "daily_collect_20260815_0700"
            attempt_id = "attempt-v2-only"
            authorization_root = provider_root / authorization_id
            attempt_root = authorization_root / run_id / attempt_id
            attempt_root.mkdir(parents=True, mode=0o700)
            for directory in (
                provider_root,
                authorization_root,
                authorization_root / run_id,
                attempt_root,
            ):
                directory.chmod(0o700)
            binding = {
                "schema_version": "provider-attempt-binding-v1",
                "provider_authorization_id": authorization_id,
                "prepare_action_authorization_id": prepare_id,
                "release_sha256": release_sha,
                "run_id": run_id,
                "attempt_id": attempt_id,
            }
            binding_path = authorization_root / "binding.json"
            binding_path.write_bytes(
                json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )
            binding_path.chmod(0o600)
            ledger = ProviderAttemptLedger(
                path=attempt_root / "provider-attempts-v2.jsonl",
                authorization_id=authorization_id,
                release_sha256=runtime_sha,
                run_id=run_id,
                attempt_id=attempt_id,
                clock=lambda: "2026-08-15T00:01:00+00:00",
            )
            reserved = ledger.reserve(
                phase="translation",
                sequence=1,
                request_payload_sha256="c" * 64,
                expected_tip=ZERO_TIP,
            )
            started = ledger.start(
                phase="translation",
                sequence=1,
                request_payload_sha256="c" * 64,
                expected_tip=reserved.entry_hash,
            )
            ledger.terminal(
                phase="translation",
                sequence=1,
                request_payload_sha256="c" * 64,
                result="succeeded",
                response_metadata={
                    "http_status": 200,
                    "response_id": "response-fixture",
                    "actual_model": "deepseek-v4-flash",
                    "system_fingerprint": None,
                    "finish_reason": "stop",
                    "retryable": False,
                    "duration_ms": 1,
                },
                usage={
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 2,
                    "total_tokens": 3,
                },
                expected_tip=started.entry_hash,
            )
            ledger_binding = ledger.build_manifest_binding(status="complete")
            manifest = {
                "status": "complete",
                "run_id": run_id,
                "provider_authorization_id": authorization_id,
                "request_count": 1,
                "retry_count": 0,
                "provider_call": True,
                "translation_provider_call": True,
                "translation_provider_attempt_made": True,
                "translation_phase_attempt_made": True,
                "semantic_validation_phase_attempt_made": False,
                "usage": ledger_binding["usage"],
                "provider_attempt_ledger": ledger_binding,
            }
            with mock.patch.object(
                report_control,
                "_require_reserved_provider_permit",
                return_value={"max_attempts": 100},
            ):
                report_control._require_provider_attempt_evidence(
                    control_root=root / "control",
                    provider_attempt_root=provider_root,
                    provider_authorization_id=authorization_id,
                    prepare_action_authorization_id=prepare_id,
                    release_sha256=release_sha,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    manifest=manifest,
                    ledger_type=ProviderAttemptLedger,
                )
            self.assertFalse(
                (authorization_root / "provider-attempts.jsonl").exists()
            )

    def test_daily_release_namespace_never_targets_periodic_report_pointer(self) -> None:
        """Catches a daily bootstrap overwriting the live periodic-report pointer."""
        layout = report_control._host_admin_layout(
            SimpleNamespace(host_root=None)
        )
        self.assertEqual(
            layout["current"], Path("/opt/reddit-voc-daily-report/current")
        )
        self.assertEqual(
            layout["releases"], Path("/opt/reddit-voc-daily-report/releases")
        )
        self.assertNotEqual(layout["current"], Path("/opt/reddit-voc-report/current"))

        _prepared_layout, prepared_paths = report_control._prepared_admin_layout(
            SimpleNamespace(
                shadow_root=None,
                public_root=None,
                private_root=None,
                state_root=None,
                blocked_root=None,
                handoff_root=None,
                public_staging_root=None,
                private_staging_root=None,
                attempt_id=None,
            )
        )
        self.assertEqual(
            prepared_paths["state"], "/opt/reddit-voc-daily-report/state"
        )
        self.assertEqual(
            prepared_paths["blocked"], "/opt/reddit-voc-daily-report/blocked"
        )
        self.assertEqual(
            prepared_paths["handoff"], "/opt/reddit-voc-daily-report/handoff"
        )

    def test_read_host_regular_accepts_explicitly_allowed_root_owner(self) -> None:
        metadata = mock.Mock(st_mode=stat.S_IFREG | 0o644, st_uid=0)
        with (
            mock.patch.object(report_control.Path, "lstat", return_value=metadata),
            mock.patch.object(report_control.os, "open", return_value=17),
            mock.patch.object(
                report_control.os, "read", side_effect=[b"root-owned-cron\n", b""]
            ),
            mock.patch.object(report_control.os, "close") as close,
        ):
            payload = report_control._read_host_regular(
                Path("/etc/cron.d/reddit-voc-site"),
                allowed_modes=frozenset({0o644}),
                allowed_uids=frozenset({0}),
                reason="cron_file_invalid",
            )
        self.assertEqual(payload, b"root-owned-cron\n")
        close.assert_called_once_with(17)

    def test_secret_reader_rejects_path_swap_after_single_fd_open(self) -> None:
        """Catches an env path being replaced between lstat and fd consumption."""
        path_metadata = mock.Mock(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=os.getuid(),
            st_dev=7,
            st_ino=11,
        )
        descriptor_metadata = mock.Mock(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=os.getuid(),
            st_dev=7,
            st_ino=12,
        )
        with (
            mock.patch.object(
                report_control.Path, "lstat", return_value=path_metadata
            ),
            mock.patch.object(report_control.os, "open", return_value=17),
            mock.patch.object(
                report_control.os, "fstat", return_value=descriptor_metadata
            ),
            mock.patch.object(
                report_control.os, "read", side_effect=[b"secret", b""]
            ),
            mock.patch.object(report_control.os, "close") as close,
        ):
            with self.assertRaisesRegex(
                report_control.ReportControlError, "runtime_secret_file_invalid"
            ):
                report_control._read_regular(
                    Path("/run/secrets/reddit-voc-report.env"),
                    reason="runtime_secret_file_invalid",
                )
        close.assert_called_once_with(17)

    def test_admin_smoke_passes_held_lock_descriptor_to_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "daily-report.lock"
            completed = mock.Mock(
                returncode=0,
                stdout=(
                    "provider_call=false\n"
                    "translation_provider_attempt_made=false\n"
                    "report_live_send=false\n"
                    "live_send=false\n"
                    "runtime_smoke=passed\n"
                ),
            )
            with mock.patch.object(
                report_control.subprocess, "run", return_value=completed
            ) as run:
                with report_control._path_lock(lock_path) as lock_fd:
                    report_control._run_admin_smoke(
                        SimpleNamespace(local_smoke_command=None),
                        layout={},
                        launcher=Path(
                            "/opt/reddit-voc-daily-report/current/launcher.sh"
                        ),
                        inherited_lock_fd=lock_fd,
                    )
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs["pass_fds"], (lock_fd,))
            self.assertEqual(
                kwargs["env"]["REDDIT_VOC_INHERITED_LOCK_FD"], str(lock_fd)
            )

    def _admin(
        self,
        *arguments: str,
        control_root: Path | None = None,
        pass_fds: tuple[int, ...] = (),
    ):
        command = ["bash", str(ADMIN), *arguments]
        if control_root is not None:
            command.extend(["--control-root", str(control_root)])
        return subprocess.run(
            command,
            env={**os.environ, "REDDIT_VOC_LOCAL_TEST_MODE": "1"},
            capture_output=True,
            text=True,
            check=False,
            pass_fds=pass_fds,
        )

    def _updater(self, *arguments: str):
        return subprocess.run(
            ["bash", str(UPDATER), *arguments],
            env={**os.environ, "REDDIT_VOC_LOCAL_TEST_MODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

    def _updater_with_input(
        self,
        *arguments: str,
        input_text: str,
        pass_fds: tuple[int, ...] = (),
    ):
        return subprocess.run(
            ["bash", str(UPDATER), *arguments],
            env={**os.environ, "REDDIT_VOC_LOCAL_TEST_MODE": "1"},
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            pass_fds=pass_fds,
        )

    def _scheduled_cycle_fixture(
        self,
        root: Path,
        *,
        release_sha: str = "a" * 64,
        launcher_sha: str = "b" * 64,
        parent_payload_override: bytes | None = None,
    ) -> dict[str, object]:
        control = root / "control"
        control.mkdir(mode=0o700)
        webhook = "https://example.invalid/robot/send?access_token=rotated-fixture"
        credential_epoch_id = "g6r1-credential-epoch-20260811"
        destination_alias = "HighValueAsset"
        parent = {
            "schema_version": "reddit-voc-bounded-daily-live-policy-v1",
            "policy_id": "task32aa-fixture",
            "cadence": "daily",
            "starts_at_utc": "2026-08-01T08:41:23+00:00",
            "expires_at_utc": "2026-08-31T00:30:00+00:00",
            "max_scheduled_runs": 30,
            "destination_fingerprint": "0" * 64,
            "required_keyword": "LL",
        }
        parent_path = root / "parent-policy.json"
        parent_payload = parent_payload_override or json.dumps(
            parent, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        parent_path.write_bytes(parent_payload)
        parent_path.chmod(0o600)
        parent_sha = hashlib.sha256(parent_payload).hexdigest()

        stable_entrypoint = root / "g6r1_stable_launcher.py"
        stable_entrypoint.write_bytes(b"#!/usr/bin/python3\n# stable fixture\n")
        stable_entrypoint.chmod(0o600)
        stable_entrypoint_sha = hashlib.sha256(
            stable_entrypoint.read_bytes()
        ).hexdigest()
        report_env = root / "reddit-voc-report.env"
        report_env.write_bytes(b"fixture=opaque\n")
        report_env.chmod(0o600)
        report_env_stat = report_env.stat()
        report_env_receipt = report_control.build_g6r1_report_env_install_receipt(
            device_id=report_env_stat.st_dev,
            inode_id=report_env_stat.st_ino,
            owner_uid=report_env_stat.st_uid,
            owner_gid=report_env_stat.st_gid,
            credential_epoch_id=credential_epoch_id,
            destination_alias=destination_alias,
            authority_event_id="owner-env-install-event-fixture",
        )
        report_env_receipt_path = root / "report-env-install-receipt.json"
        report_env_receipt_payload = report_control.canonical_g6r1_json_bytes(
            report_env_receipt
        )
        report_env_receipt_path.write_bytes(report_env_receipt_payload)
        report_env_receipt_path.chmod(0o600)
        report_env_receipt_sha = hashlib.sha256(
            report_env_receipt_payload
        ).hexdigest()

        rotation = report_control.build_g6r1_rotation_receipt(
            rotated_at_utc="2026-08-11T12:00:00Z",
            credential_epoch_id=credential_epoch_id,
            destination_alias=destination_alias,
            authority_event_id="owner-rotation-event-fixture",
            report_env_install_receipt_sha256=report_env_receipt_sha,
        )
        rotation_path = root / "rotation-receipt.json"
        rotation_payload = report_control.canonical_g6r1_json_bytes(rotation)
        rotation_path.write_bytes(rotation_payload)
        rotation_path.chmod(0o600)
        rotation_sha = hashlib.sha256(rotation_payload).hexdigest()

        authorization_id = "owner-g6r1-scheduled-policy"
        policy = report_control.build_g6r1_scheduled_cycle_policy(
            policy_id="g6r1-20260812-20260831",
            authorization_id=authorization_id,
            parent_policy_sha256=parent_sha,
            release_sha256=release_sha,
            stable_entrypoint_sha256=stable_entrypoint_sha,
            release_launcher_sha256=launcher_sha,
            credential_epoch_id=credential_epoch_id,
            destination_alias=destination_alias,
            credential_rotation_receipt_sha256=rotation_sha,
        )
        policy_path = root / "g6r1-policy.json"
        policy_payload = report_control.canonical_g6r1_json_bytes(policy)
        policy_path.write_bytes(policy_payload)
        policy_path.chmod(0o600)
        policy_sha = hashlib.sha256(policy_payload).hexdigest()
        return {
            "control": control,
            "webhook": webhook,
            "credential_epoch_id": credential_epoch_id,
            "destination_alias": destination_alias,
            "parent_path": parent_path,
            "parent_sha": parent_sha,
            "rotation_path": rotation_path,
            "rotation_sha": rotation_sha,
            "report_env_receipt_path": report_env_receipt_path,
            "report_env_receipt_sha": report_env_receipt_sha,
            "report_env_path": report_env,
            "stable_entrypoint_path": stable_entrypoint,
            "stable_entrypoint_sha": stable_entrypoint_sha,
            "policy_path": policy_path,
            "policy_sha": policy_sha,
            "policy": policy,
            "authorization_id": authorization_id,
            "release_sha": release_sha,
            "launcher_sha": launcher_sha,
            "cycle_lease_token": "d" * 64,
        }

    def _install_scheduled_cycle_policy_permit(
        self, fixture: dict[str, object]
    ) -> subprocess.CompletedProcess[str]:
        completed = self._admin(
            "install-scheduled-cycle-policy-permit",
            "--authorization-id",
            str(fixture["authorization_id"]),
            "--expected-release-sha256",
            str(fixture["release_sha"]),
            "--expected-launcher-sha256",
            str(fixture["launcher_sha"]),
            "--expected-stable-entrypoint-sha256",
            str(fixture["stable_entrypoint_sha"]),
            "--expected-policy-sha256",
            str(fixture["policy_sha"]),
            "--expected-parent-policy-sha256",
            str(fixture["parent_sha"]),
            "--expected-credential-rotation-receipt-sha256",
            str(fixture["rotation_sha"]),
            "--max-slots",
            "20",
            "--credential-epoch-id",
            str(fixture["credential_epoch_id"]),
            "--destination-alias",
            str(fixture["destination_alias"]),
            "--expires-at",
            "2026-08-31T00:30:00Z",
            control_root=Path(fixture["control"]),
        )
        if completed.returncode != 0:
            return completed
        transaction_id = "g6r1-fixture-transaction"
        transactions = Path(fixture["control"]).parent / "transactions"
        transaction = transactions / transaction_id
        transaction.mkdir(parents=True, mode=0o700)
        transactions.chmod(0o700)
        transaction.chmod(0o700)
        journal_base = {
            "schema_version": "reddit-voc-g6r1-transaction-journal-v1",
            "transaction_id": transaction_id,
            "phase": "committed",
            "phase_history": [{"phase": "committed"}],
            "release_sha256": str(fixture["release_sha"]),
            "preimage_sha256": "e" * 64,
            "primary_schedule_state": "installed_exact",
            "secondary_sender_retired": True,
            "provider_call": False,
            "http_send": False,
            "production_database_write": False,
            "public_current_switch": True,
            "created_at_utc": "2026-08-11T12:00:00Z",
            "updated_at_utc": "2026-08-11T12:01:00Z",
        }
        journal = {
            **journal_base,
            "journal_sha256": hashlib.sha256(
                report_control.canonical_g6r1_json_bytes(journal_base)
            ).hexdigest(),
        }
        journal_payload = (
            report_control.canonical_g6r1_json_bytes(journal) + b"\n"
        )
        journal_path = transaction / "journal.json"
        journal_path.write_bytes(journal_payload)
        journal_path.chmod(0o600)
        permit = json.loads(
            Path(fixture["control"])
            .joinpath("permits", f"{fixture['authorization_id']}.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            permit,
            report_control.build_g6r1_owner_policy_permit(
                authorization_id=str(fixture["authorization_id"]),
                release_sha256=str(fixture["release_sha"]),
                stable_entrypoint_sha256=str(
                    fixture["stable_entrypoint_sha"]
                ),
                release_launcher_sha256=str(fixture["launcher_sha"]),
                policy_sha256=str(fixture["policy_sha"]),
                parent_policy_sha256=str(fixture["parent_sha"]),
                credential_rotation_receipt_sha256=str(
                    fixture["rotation_sha"]
                ),
                credential_epoch_id=str(fixture["credential_epoch_id"]),
                destination_alias=str(fixture["destination_alias"]),
            ),
        )
        permit_sha = hashlib.sha256(
            json.dumps(permit, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        owner_permit_path = Path(fixture["control"]).parent / "owner-permit.json"
        owner_permit_path.write_bytes(
            report_control.canonical_g6r1_json_bytes(permit)
        )
        owner_permit_path.chmod(0o600)
        primary_cron = Path(fixture["control"]).parent / "reddit-voc-site.cron"
        primary_cron_payload = (
            "CRON_TZ=Asia/Shanghai\n"
            "0 7 * * * ubuntu /opt/reddit-voc-site/scripts/server_daily_collect.sh "
            ">> /opt/reddit-voc-site/logs/cron-collect.log 2>&1\n"
            "0 8 * * * ubuntu /usr/bin/env -i PATH=/usr/bin:/bin "
            "HOME=/home/ubuntu LANG=C.UTF-8 /usr/bin/python3 "
            "/opt/reddit-voc-daily-report/control/bin/"
            "g6r1_stable_launcher.py "
            "scheduled-cycle >> /opt/reddit-voc-site/logs/cron-report.log 2>&1\n"
        ).encode("utf-8")
        primary_cron.write_bytes(primary_cron_payload)
        primary_cron.chmod(0o600)
        disposition = report_control.build_g6r1_secondary_disposition()
        disposition_path = (
            Path(fixture["control"]).parent / "secondary-disposition.json"
        )
        disposition_payload = report_control.canonical_g6r1_json_bytes(
            disposition
        )
        disposition_path.write_bytes(disposition_payload)
        disposition_path.chmod(0o600)
        user_crontab = Path(fixture["control"]).parent / "user-crontab.txt"
        user_crontab.write_bytes(b"")
        user_crontab.chmod(0o600)
        processes = Path(fixture["control"]).parent / "processes.txt"
        processes.write_bytes(b"python-safe-process\n")
        processes.chmod(0o600)
        marker = report_control.build_g6r1_activation_marker(
            transaction_id=transaction_id,
            release_sha256=str(fixture["release_sha"]),
            stable_entrypoint_sha256=str(fixture["stable_entrypoint_sha"]),
            release_launcher_sha256=str(fixture["launcher_sha"]),
            child_policy_sha256=str(fixture["policy_sha"]),
            owner_permit_sha256=permit_sha,
            rotation_receipt_sha256=str(fixture["rotation_sha"]),
            report_env_install_receipt_sha256=str(
                fixture["report_env_receipt_sha"]
            ),
            secondary_disposition_sha256=hashlib.sha256(
                disposition_payload
            ).hexdigest(),
            journal_file_sha256=hashlib.sha256(journal_payload).hexdigest(),
            primary_cron_sha256=hashlib.sha256(
                primary_cron_payload
            ).hexdigest(),
        )
        marker_path = Path(fixture["control"]).parent / "activation-marker.json"
        marker_path.write_bytes(
            report_control.canonical_g6r1_json_bytes(marker)
        )
        marker_path.chmod(0o600)
        fixture["transactions_root"] = transactions
        fixture["activation_marker_path"] = marker_path
        fixture["owner_permit_path"] = owner_permit_path
        fixture["primary_cron_path"] = primary_cron
        fixture["secondary_disposition_path"] = disposition_path
        fixture["user_crontab_path"] = user_crontab
        fixture["process_snapshot_path"] = processes
        return completed

    def _reserve_scheduled_cycle(
        self,
        fixture: dict[str, object],
        *,
        report_date: str = "2026-08-12",
        run_id: str = "daily_collect_20260812_0700",
    ) -> subprocess.CompletedProcess[str]:
        lease_path = Path(fixture["control"]).parent / "cycle-lease"
        lease_path.write_text(str(fixture["cycle_lease_token"]), encoding="ascii")
        lease_path.chmod(0o600)
        lease_fd = os.open(lease_path, os.O_RDONLY)
        try:
            return self._admin(
            "reserve-scheduled-cycle",
            "--expected-release-sha256",
            str(fixture["release_sha"]),
            "--expected-launcher-sha256",
            str(fixture["launcher_sha"]),
            "--run-id",
            run_id,
            "--scheduled-at",
            f"{report_date}T08:00:15+08:00",
            "--cycle-lease-fd",
            str(lease_fd),
            "--policy-file",
            str(fixture["policy_path"]),
            "--parent-policy-file",
            str(fixture["parent_path"]),
            "--credential-rotation-receipt-file",
            str(fixture["rotation_path"]),
            "--report-env-install-receipt-file",
            str(fixture["report_env_receipt_path"]),
            "--report-env-file",
            str(fixture["report_env_path"]),
            "--expected-parent-policy-sha256",
            str(fixture["parent_sha"]),
            "--activation-marker-file",
            str(fixture.get("activation_marker_path", "missing-activation-marker")),
            "--owner-policy-permit-file",
            str(fixture.get("owner_permit_path", "missing-owner-permit")),
            "--transactions-root",
            str(fixture.get("transactions_root", "missing-transactions-root")),
            "--primary-cron-file",
            str(fixture.get("primary_cron_path", "missing-primary-cron")),
            "--stable-entrypoint-file",
            str(fixture["stable_entrypoint_path"]),
            "--secondary-disposition-file",
            str(
                fixture.get(
                    "secondary_disposition_path", "missing-secondary-disposition"
                )
            ),
            "--user-crontab-snapshot-file",
            str(fixture.get("user_crontab_path", "missing-user-crontab")),
            "--process-snapshot-file",
            str(fixture.get("process_snapshot_path", "missing-process-snapshot")),
            control_root=Path(fixture["control"]),
            pass_fds=(lease_fd,),
            )
        finally:
            os.close(lease_fd)

    def test_scheduled_cycle_loads_parent_through_immutable_authority_reader(
        self,
    ) -> None:
        """Catches the annual parent being read with the 0600 secret reader."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._scheduled_cycle_fixture(Path(tmp))
            installed = self._install_scheduled_cycle_policy_permit(fixture)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            args = SimpleNamespace(
                parent_policy_file=fixture["parent_path"],
                policy_file=fixture["policy_path"],
                credential_rotation_receipt_file=fixture["rotation_path"],
                report_env_install_receipt_file=fixture[
                    "report_env_receipt_path"
                ],
                dual_credential_set_receipt_file=None,
                dual_report_env_install_receipt_file=None,
                report_env_file=fixture["report_env_path"],
                expected_parent_policy_sha256=fixture["parent_sha"],
                owner_policy_permit_file=fixture["owner_permit_path"],
                activation_marker_file=fixture["activation_marker_path"],
                transactions_root=fixture["transactions_root"],
                primary_cron_file=fixture["primary_cron_path"],
                stable_entrypoint_file=fixture["stable_entrypoint_path"],
                secondary_disposition_file=fixture[
                    "secondary_disposition_path"
                ],
                user_crontab_snapshot_file=fixture["user_crontab_path"],
                process_snapshot_file=fixture["process_snapshot_path"],
                scheduled_at="2026-08-12T08:00:15+08:00",
            )
            parent_path = Path(fixture["parent_path"])
            original_regular = report_control._read_regular
            original_authority_regular = report_control._read_authority_regular

            def guarded_regular(path: Path, *, reason: str) -> bytes:
                if path == parent_path:
                    raise report_control.ReportControlError(
                        "ordinary_parent_reader_used"
                    )
                return original_regular(path, reason=reason)

            def authority_regular(path: Path, *, reason: str) -> bytes:
                if path == parent_path:
                    return original_regular(path, reason=reason)
                return original_authority_regular(path, reason=reason)

            with (
                mock.patch.dict(
                    os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                ),
                mock.patch.object(
                    report_control,
                    "_read_regular",
                    side_effect=guarded_regular,
                ),
                mock.patch.object(
                    report_control,
                    "_read_authority_regular",
                    side_effect=authority_regular,
                ),
            ):
                authority = report_control._load_scheduled_cycle_policy(
                    args,
                    control_root=Path(fixture["control"]),
                    release_sha256=str(fixture["release_sha"]),
                    launcher_sha256=str(fixture["launcher_sha"]),
                    run_id="daily_collect_20260812_0700",
                    scheduled_at="2026-08-12T08:00:15+08:00",
                )

            self.assertEqual(authority["report_date"], "2026-08-12")
            self.assertEqual(
                authority["parent_policy_sha256"], fixture["parent_sha"]
            )

    def test_scheduled_cycle_requires_new_owner_policy_and_consumes_one_exact_slot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._scheduled_cycle_fixture(Path(tmp))

            legacy_only = self._reserve_scheduled_cycle(fixture)
            self.assertNotEqual(legacy_only.returncode, 0)
            self.assertIn("scheduled_policy_authorization_missing", legacy_only.stderr)
            self.assertFalse(
                Path(fixture["control"]).joinpath("scheduled-cycles").exists()
            )

            installed = self._install_scheduled_cycle_policy_permit(fixture)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            reserved = self._reserve_scheduled_cycle(fixture)
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            output = dict(
                line.split("=", 1)
                for line in reserved.stdout.splitlines()
                if "=" in line
            )
            cycle_id = output["cycle_id"]
            prepare_id = output["authorization_id"]
            self.assertRegex(cycle_id, r"^g6r1-cycle-20260812-[0-9a-f]{24}$")
            permit = json.loads(
                Path(fixture["control"])
                .joinpath("permits", f"{prepare_id}.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(
                permit["schema_version"],
                "report-scheduled-cycle-prepare-permit-v1",
            )
            self.assertEqual(permit["cycle_id"], cycle_id)
            self.assertEqual(permit["report_date"], "2026-08-12")
            self.assertEqual(permit["max_prepare_invocations"], 1)
            self.assertEqual(permit["max_attempts"], 100)
            self.assertFalse(
                permit["provider_attempt_policy"]["cross_process_retry"]
            )
            self.assertFalse(permit["live_send"])
            state = json.loads(
                Path(fixture["control"])
                .joinpath("permit-state", f"{prepare_id}.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "reserved")

            reused = self._reserve_scheduled_cycle(fixture)
            self.assertNotEqual(reused.returncode, 0)
            self.assertIn("scheduled_slot_already_consumed", reused.stderr)
            ledger = Path(fixture["control"]).joinpath(
                "scheduled-cycles", "ledger.jsonl"
            )
            entries = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["event"], "prepare_reserved")
            self.assertEqual(entries[0]["report_date"], "2026-08-12")
            self.assertEqual(entries[1]["event"], "prepare_unknown")

    def test_frozen_parent_preimage_b22_loads_without_rewriting_timestamps(
        self,
    ) -> None:
        frozen = (
            ROOT
            / "tests/fixtures/g6r0-task32aa-daily-live-policy-b22.json"
        )
        payload = frozen.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "b22a4e29bd055db1c67f82a7974fd01513a57f293454d042d896047a4942bb2f",
        )
        self.assertTrue(payload.endswith(b"\n"))
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._scheduled_cycle_fixture(
                Path(tmp), parent_payload_override=payload
            )
            installed = self._install_scheduled_cycle_policy_permit(fixture)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            reserved = self._reserve_scheduled_cycle(fixture)
            self.assertEqual(reserved.returncode, 0, reserved.stderr)

    def test_scheduled_cycle_policy_rejects_slot_or_rotated_destination_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._scheduled_cycle_fixture(Path(tmp))
            installed = self._install_scheduled_cycle_policy_permit(fixture)
            self.assertEqual(installed.returncode, 0, installed.stderr)

            wrong_run = self._reserve_scheduled_cycle(
                fixture, run_id="daily_collect_20260811_0700"
            )
            self.assertNotEqual(wrong_run.returncode, 0)
            self.assertIn("scheduled_slot_identity_mismatch", wrong_run.stderr)

            rotation_path = Path(fixture["rotation_path"])
            rotation = json.loads(rotation_path.read_text(encoding="utf-8"))
            rotation["destination_alias"] = "UnexpectedDestination"
            rotation_path.write_text(
                json.dumps(rotation, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            rotation_path.chmod(0o600)
            drifted = self._reserve_scheduled_cycle(fixture)
            self.assertNotEqual(drifted.returncode, 0)
            self.assertIn("credential_rotation_receipt_invalid", drifted.stderr)
            self.assertFalse(
                Path(fixture["control"]).joinpath("scheduled-cycles").exists()
            )

    def test_scheduled_cycle_derives_one_exact_send_permit_only_after_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self._scheduled_cycle_fixture(root)
            installed = self._install_scheduled_cycle_policy_permit(fixture)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            reserved = self._reserve_scheduled_cycle(fixture)
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            reservation = dict(
                line.split("=", 1)
                for line in reserved.stdout.splitlines()
                if "=" in line
            )
            cycle_id = reservation["cycle_id"]
            prepare_id = reservation["authorization_id"]
            run_id = "daily_collect_20260812_0700"
            attempt_id = "attempt-g6r1-exact"
            version_id = "20260812T000100000000Z-" + "1" * 32
            bundle_sha = "2" * 64
            outbox_sha = "3" * 64
            commit_request_sha = "4" * 64
            control = Path(fixture["control"])

            forged = self._admin(
                "terminalize-permit",
                "--authorization-id",
                prepare_id,
                "--expected-release-sha256",
                str(fixture["release_sha"]),
                "--terminal-status",
                "consumed",
                control_root=control,
            )
            self.assertNotEqual(forged.returncode, 0)
            self.assertIn(
                "scheduled_prepare_commit_receipt_required", forged.stderr
            )
            env_path = root / "runtime.env"
            env_path.write_text(
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
                "DINGTALK_WEBHOOK_URL=https://example.invalid/fixture\n"
                "DINGTALK_WEBHOOK_SECRET=fixture-only\n"
                "DINGTALK_REQUIRED_KEYWORD=LL\n"
                "REDDIT_VOC_DINGTALK_CREDENTIAL_EPOCH_ID="
                f"{fixture['credential_epoch_id']}\n"
                "REDDIT_VOC_DINGTALK_DESTINATION_ALIAS=HighValueAsset\n",
                encoding="utf-8",
            )
            env_path.chmod(0o600)
            prepared_paths: dict[str, str] = {}
            for name in (
                "public",
                "private",
                "public_staging",
                "private_staging",
                "state",
                "blocked",
                "handoff",
                "provider_attempts",
            ):
                path = root / name
                path.mkdir(mode=0o700)
                prepared_paths[name] = str(path)
            prepared = SimpleNamespace(
                run_id=run_id,
                attempt_id=attempt_id,
                artifact_version_id=version_id,
                bundle_sha256=bundle_sha,
                outbox_sha256=outbox_sha,
            )
            runtime = {
                "PreparedReportRoots": lambda **values: SimpleNamespace(**values),
                "commit_staged_prepared_report": lambda **_values: prepared,
                "load_verified_prepared_report": lambda **_values: prepared,
                "load_and_verify_delivery_ledger": lambda *_args, **_kwargs: (),
                "ProviderAttemptLedger": object,
                "schema_assets": object(),
            }
            lease_path = root / "cycle-lease"
            lease_fd = os.open(lease_path, os.O_RDONLY)
            try:
                args = SimpleNamespace(
                    expected_release_sha256=fixture["release_sha"],
                    expected_launcher_sha256=fixture["launcher_sha"],
                    run_id=run_id,
                    cycle_id=cycle_id,
                    cycle_lease_fd=lease_fd,
                    prepare_action_authorization_id=prepare_id,
                    attempt_id=attempt_id,
                    expected_artifact_version_id=version_id,
                    expected_bundle_sha256=bundle_sha,
                    expected_outbox_sha256=outbox_sha,
                    expected_commit_request_sha256=commit_request_sha,
                    authorization_id=prepare_id,
                    provider_authorization_id=None,
                    release_dir=ROOT,
                    config_root=ROOT / "config",
                    scheduled_at="2026-08-12T08:03:00+08:00",
                    policy_file=fixture["policy_path"],
                    parent_policy_file=fixture["parent_path"],
                    credential_rotation_receipt_file=fixture["rotation_path"],
                    report_env_install_receipt_file=fixture[
                        "report_env_receipt_path"
                    ],
                    report_env_file=fixture["report_env_path"],
                    expected_parent_policy_sha256=fixture["parent_sha"],
                    owner_policy_permit_file=fixture["owner_permit_path"],
                    activation_marker_file=fixture["activation_marker_path"],
                    transactions_root=fixture["transactions_root"],
                    primary_cron_file=fixture["primary_cron_path"],
                    stable_entrypoint_file=fixture["stable_entrypoint_path"],
                    secondary_disposition_file=fixture[
                        "secondary_disposition_path"
                    ],
                    user_crontab_snapshot_file=fixture["user_crontab_path"],
                    process_snapshot_file=fixture["process_snapshot_path"],
                )
                with (
                    mock.patch.dict(
                        os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                    ),
                    mock.patch.object(
                        report_control,
                        "_load_neutral_prepared_runtime",
                        return_value=runtime,
                    ),
                ):
                    with self.assertRaisesRegex(
                        report_control.ReportControlError,
                        "scheduled_cycle_not_derivable",
                    ):
                        report_control._derive_scheduled_send_permit(
                            args,
                            layout={"control": control, "env": env_path},
                            prepared_paths=prepared_paths,
                        )
                    committed = report_control._commit_prepared_admin(
                        args,
                        layout={"control": control, "env": env_path},
                        prepared_paths=prepared_paths,
                    )
                    self.assertEqual(committed["status"], "committed")
                    self.assertRegex(
                        str(committed["commit_receipt_sha256"]),
                        r"^[0-9a-f]{64}$",
                    )
                    derived = report_control._derive_scheduled_send_permit(
                        args,
                        layout={"control": control, "env": env_path},
                        prepared_paths=prepared_paths,
                    )
                    with self.assertRaisesRegex(
                        report_control.ReportControlError,
                        "scheduled_cycle_not_derivable",
                    ):
                        report_control._derive_scheduled_send_permit(
                            args,
                            layout={"control": control, "env": env_path},
                            prepared_paths=prepared_paths,
                        )
            finally:
                os.close(lease_fd)
            send_id = str(derived["authorization_id"])
            send_permit = json.loads(
                control.joinpath("permits", f"{send_id}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                send_permit["schema_version"],
                "report-scheduled-cycle-send-permit-v1",
            )
            self.assertEqual(send_permit["artifact_version_id"], version_id)
            self.assertEqual(send_permit["bundle_sha256"], bundle_sha)
            self.assertEqual(send_permit["outbox_sha256"], outbox_sha)
            self.assertEqual(
                send_permit["expires_at"], "2026-08-12T00:30:00Z"
            )
            self.assertEqual(
                send_permit["commit_request_sha256"], commit_request_sha
            )
            self.assertEqual(send_permit["destination_alias"], "HighValueAsset")
            self.assertNotIn("destination_fingerprint", send_permit)
            self.assertNotIn("cycle_lease_token", send_permit)
            with (
                mock.patch.dict(
                    os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                ),
                mock.patch.object(
                    report_control, "_expiry_is_future", return_value=True
                ),
                self.assertRaisesRegex(
                    report_control.ReportControlError,
                    "scheduled_cycle_lease_expired",
                ),
            ):
                report_control._require_send_permit(
                    control_root=control,
                    authorization_id=send_id,
                    release_sha256=str(fixture["release_sha"]),
                    run_id=run_id,
                    artifact_version_id=version_id,
                    bundle_sha256=bundle_sha,
                    outbox_sha256=outbox_sha,
                    action="initial",
                    resend_part_indexes=(),
                    expected_status="installed",
                    scheduled_cycle_id=cycle_id,
                    cycle_lease_token=str(fixture["cycle_lease_token"]),
                    scheduled_at="2026-08-12T08:30:00+08:00",
                )
            ledger = [
                json.loads(line)
                for line in control.joinpath(
                    "scheduled-cycles", "ledger.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [entry["event"] for entry in ledger],
                [
                    "prepare_reserved",
                    "prepare_committed",
                    "send_permit_derived",
                ],
            )

    def _shadow_with_reserved_permit(self, root: Path) -> tuple[Path, bytes]:
        shadow = root / "shadow"
        initialized = self._admin(
            "init-shadow-root",
            "--shadow-root",
            str(shadow),
            "--authorization-id",
            "shadow-provision-gates",
            "--expected-release-sha256",
            "3" * 64,
            "--candidate-sha256",
            "4" * 64,
            "--authorize-shadow-provisioning",
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        installed = self._admin(
            "install-shadow-permit",
            "--shadow-root",
            str(shadow),
            "--authorization-id",
            "shadow-provider-gates",
            "--expected-release-sha256",
            "3" * 64,
            "--run-id",
            "daily_collect_20260714_0700",
            "--copied-database-sha256",
            "5" * 64,
            "--max-attempts",
            "100",
            "--expires-at",
            "2030-07-14T00:00:00+00:00",
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        reserved = self._admin(
            "reserve-permit",
            "--control-root",
            str(shadow / "control"),
            "--authorization-id",
            "shadow-provider-gates",
            "--expected-release-sha256",
            "3" * 64,
            "--run-id",
            "daily_collect_20260714_0700",
        )
        self.assertEqual(reserved.returncode, 0, reserved.stderr)
        original = (
            b"# exact bytes must survive\n"
            b"REDDIT_VOC_DATABASE_PATH=/isolated/data.sqlite3\n"
            b"DINGTALK_WEBHOOK_URL=https://example.invalid/?token=$(never-run)\n"
            b"DINGTALK_WEBHOOK_SECRET=synthetic-secret-value\n"
            b"REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
            b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
            b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
            b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
            b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
        )
        env_path = shadow / "secrets" / "reddit-voc-report.env"
        env_path.write_bytes(original)
        env_path.chmod(0o600)
        return shadow, original

    def test_noninterference_capture_redacts_secrets_and_layer_allowlists(self) -> None:
        before = capture_from_mapping(
            {
                "cron_sha256": "a" * 64,
                "nginx_sha256": "b" * 64,
                "collector_sha256": "c" * 64,
                "main_site_container_id": "site-one",
                "libretranslate_container_id": "translate-one",
                "report_gates": {
                    "REDDIT_VOC_TRANSLATION_MODE": "dry_run",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
                    "DINGTALK_WEBHOOK_URL": "must-not-survive",
                },
            }
        )
        encoded = json.dumps(before, sort_keys=True)
        self.assertNotIn("must-not-survive", encoded)
        self.assertEqual(before["report_gates"]["DINGTALK_WEBHOOK_URL"], "<redacted>")
        after = {**before, "prepared_pointer": "candidate-one"}
        accepted = compare_snapshots(before=before, after=after, layer="L5")
        self.assertEqual(accepted["status"], "accepted")
        rejected = compare_snapshots(
            before=before,
            after={**after, "cron_sha256": "changed"},
            layer="L5",
        )
        self.assertEqual(rejected["status"], "blocked")
        self.assertIn("cron_sha256", rejected["unexpected_changes"])

    def test_host_capture_is_read_only_redacted_and_enforces_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp) / "host"

            def write_host_file(absolute: str, payload: str) -> Path:
                path = host / absolute.lstrip("/")
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.write_text(payload, encoding="utf-8")
                path.chmod(0o600)
                return path

            cron = write_host_file(
                "/etc/cron.d/reddit-voc-site", "fixed cron\n"
            )
            write_host_file(
                "/opt/ai-video/deploy/lighthouse/nginx.conf",
                "fixed nginx\n",
            )
            write_host_file(
                "/opt/reddit-voc-site/scripts/server_daily_collect.sh",
                "fixed collector\n",
            )
            write_host_file(
                "/opt/reddit-voc-site/scripts/server_daily_report.sh",
                "fixed launcher\n",
            )
            database = host / "opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"
            database.parent.mkdir(parents=True, mode=0o700)
            import sqlite3

            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
            database.chmod(0o600)

            release = host / (
                "opt/reddit-voc-daily-report/releases/" + "a" * 64
            )
            release.mkdir(parents=True, mode=0o700)
            current = host / "opt/reddit-voc-daily-report/current"
            current.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            current.symlink_to(release)
            state = host / "opt/reddit-voc-daily-report/state"
            state.mkdir(parents=True, mode=0o700)
            prepared_pointer = state / "prepared-current.json"
            prepared_pointer.write_text(
                json.dumps({"artifact_version_id": "one"}), encoding="utf-8"
            )
            prepared_pointer.chmod(0o600)
            outputs = host / "opt/reddit-voc-site/outputs"
            outputs.mkdir(parents=True, mode=0o700)
            target = outputs / "prepared/one/report.html"
            target.parent.mkdir(parents=True, mode=0o700)
            target.write_text("report", encoding="utf-8")
            (outputs / "latest-report.html").symlink_to(target)

            env_path = write_host_file(
                "/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env",
                "DINGTALK_WEBHOOK_SECRET=must-not-survive\n"
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n",
            )
            control = host / "home/ubuntu/.reddit-voc/report-control"
            for name in (
                "gates",
                "permits",
                "permit-state",
                "audit",
                "provider-attempts",
            ):
                control.joinpath(name).mkdir(parents=True, mode=0o700)
            snapshots = (
                host
                / "home/ubuntu/.reddit-voc/secrets/report-env-snapshots"
            )
            snapshots.mkdir(parents=True, mode=0o700)

            docker_facts = {
                "containers": {
                    "reddit_voc_site_app": {
                        "id": "site-one",
                        "started_at": "2026-07-14T00:00:00Z",
                        "restart_count": 0,
                        "mounts": [],
                    },
                    "reddit_voc_libretranslate": {
                        "id": "translate-one",
                        "started_at": "2026-07-14T00:00:00Z",
                        "restart_count": 0,
                        "mounts": [],
                    },
                    "ai_video_nginx": {
                        "id": "nginx-one",
                        "started_at": "2026-07-14T00:00:00Z",
                        "restart_count": 0,
                        "mounts": [],
                    },
                },
                "networks": {
                    "lighthouse_ai_video_net": ["nginx-one"],
                    "reddit_voc_site_net": ["site-one", "translate-one"],
                    "reddit_voc_report_net": [],
                },
                "report_containers": [],
            }
            before = capture_host_facts(
                host_root=host, docker_facts=docker_facts
            )
            encoded = json.dumps(before.public, sort_keys=True)
            self.assertNotIn("must-not-survive", encoded)
            self.assertNotIn("must-not-survive", repr(before))
            self.assertEqual(before.public["report_network_members"], [])
            self.assertEqual(
                before.public["current_release"], "a" * 64
            )
            self.assertEqual(
                before.public["cron_sha256"],
                hashlib.sha256(cron.read_bytes()).hexdigest(),
            )
            docker_facts_path = Path(tmp) / "docker-facts.json"
            docker_facts_path.write_text(
                json.dumps(docker_facts), encoding="utf-8"
            )
            capture_output = Path(tmp) / "host-capture.json"
            captured = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/report_noninterference.py"),
                    "capture-host",
                    "--host-root",
                    str(host),
                    "--docker-facts-json",
                    str(docker_facts_path),
                    "--output",
                    str(capture_output),
                ],
                env={**os.environ, "REDDIT_VOC_LOCAL_TEST_MODE": "1"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)
            self.assertNotIn(
                "must-not-survive",
                capture_output.read_text(encoding="utf-8"),
            )

            prepared_pointer.write_text(
                json.dumps({"artifact_version_id": "two"}), encoding="utf-8"
            )
            after = capture_host_facts(
                host_root=host, docker_facts=docker_facts
            )
            accepted = compare_host_captures(
                before=before, after=after, layer="L5"
            )
            self.assertEqual(accepted["status"], "accepted")
            cron.write_text("changed cron\n", encoding="utf-8")
            changed = capture_host_facts(
                host_root=host, docker_facts=docker_facts
            )
            rejected = compare_host_captures(
                before=after, after=changed, layer="L5"
            )
            self.assertEqual(rejected["status"], "blocked")
            self.assertIn("cron_sha256", rejected["unexpected_changes"])

            cron.write_text("fixed cron\n", encoding="utf-8")
            env_path.write_text(
                env_path.read_text(encoding="utf-8").replace(
                    "REDDIT_VOC_TRANSLATION_MODE=dry_run",
                    "REDDIT_VOC_TRANSLATION_MODE=deepseek",
                ).replace(
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0",
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1",
                ),
                encoding="utf-8",
            )
            live_gates = capture_host_facts(
                host_root=host, docker_facts=docker_facts
            )
            terminal_rejected = compare_host_captures(
                before=after, after=live_gates, layer="L5"
            )
            self.assertEqual(terminal_rejected["status"], "blocked")
            self.assertIn(
                "report_gates_not_all_off",
                terminal_rejected["terminal_violations"],
            )

    def test_prepare_permit_is_atomic_mode600_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            env = {**os.environ, "REDDIT_VOC_LOCAL_TEST_MODE": "1"}
            command = [
                "bash",
                str(ADMIN),
                "install-prepare-permit",
                "--control-root",
                str(control),
                "--authorization-id",
                "prepare-auth-one",
                "--expected-release-sha256",
                "a" * 64,
                "--run-id",
                "daily_collect_20260713_0700",
                "--max-attempts",
                "100",
                "--expires-at",
                "2026-07-14T00:00:00+00:00",
            ]
            first = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            permit = control / "permits" / "prepare-auth-one.json"
            self.assertEqual(permit.stat().st_mode & 0o777, 0o600)
            document = json.loads(permit.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], "report-prepare-permit-v1")
            self.assertEqual(document["max_attempts"], 100)
            second = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertNotIn("secret", first.stdout.casefold() + first.stderr.casefold())

    def test_schedule_permit_is_one_run_prepare_only_and_reserved_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            release_sha = "6" * 64
            run_id = "daily_collect_20260715_0700"
            authorization_id = "schedule-prepare-20260715"
            installed = self._admin(
                "install-schedule-permit",
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--max-attempts",
                "100",
                "--expires-at",
                "2030-07-15T00:00:00+00:00",
                control_root=control,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            permit_path = control / "permits" / f"{authorization_id}.json"
            permit = json.loads(permit_path.read_text(encoding="utf-8"))
            self.assertEqual(permit["schema_version"], "report-schedule-permit-v1")
            self.assertEqual(permit["action"], "prepare_only")
            self.assertEqual(permit["report_count"], 1)
            self.assertEqual(permit["max_attempts"], 100)
            self.assertFalse(permit["live_send"])
            self.assertFalse(permit["failure_alert"])

            reserved = self._admin(
                "reserve-scheduled-prepare",
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                control_root=control,
            )
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            self.assertIn(
                f"authorization_id={authorization_id}", reserved.stdout
            )
            state = json.loads(
                control.joinpath(
                    "permit-state", f"{authorization_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "reserved")
            self.assertEqual(
                report_control._require_reserved_prepare_permit(
                    control_root=control,
                    authorization_id=authorization_id,
                    release_sha256=release_sha,
                    run_id=run_id,
                )["schema_version"],
                "report-schedule-permit-v1",
            )
            self.assertEqual(
                report_control._require_reserved_provider_permit(
                    control_root=control,
                    authorization_id=authorization_id,
                    release_sha256=release_sha,
                    run_id=run_id,
                )["action"],
                "prepare_only",
            )
            report_control._require_reserved_gate_permit(
                control_root=control,
                authorization_id=authorization_id,
                release_sha256=release_sha,
            )
            reused = self._admin(
                "reserve-scheduled-prepare",
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                control_root=control,
            )
            self.assertNotEqual(reused.returncode, 0)

    def test_send_permit_cannot_authorize_deepseek_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            release_sha = "5" * 64
            run_id = "daily_collect_20260715_0700"
            authorization_id = "send-cannot-enable-provider"
            installed = self._admin(
                "install-send-permit",
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--expected-artifact-version-id",
                "20260715T010203456789Z-" + "5" * 32,
                "--expected-bundle-sha256",
                "6" * 64,
                "--expected-outbox-sha256",
                "7" * 64,
                "--action",
                "initial",
                "--expires-at",
                "2030-07-15T00:00:00+00:00",
                control_root=control,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            reserved = self._admin(
                "reserve-permit",
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                control_root=control,
            )
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            with self.assertRaisesRegex(
                report_control.ReportControlError,
                "gate_permit_not_reserved",
            ):
                report_control._require_reserved_gate_permit(
                    control_root=control,
                    authorization_id=authorization_id,
                    release_sha256=release_sha,
                )

    def test_admin_permit_is_immutable_and_binds_action_and_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            arguments = (
                "install-admin-permit",
                "--authorization-id",
                "admin-auth-one",
                "--expected-release-sha256",
                "a" * 64,
                "--action",
                "activate",
                "--expected-launcher-sha256",
                "b" * 64,
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
            )
            first = self._admin(*arguments, control_root=control)
            self.assertEqual(first.returncode, 0, first.stderr)
            permit = control / "permits" / "admin-auth-one.json"
            state = control / "permit-state" / "admin-auth-one.json"
            self.assertEqual(permit.stat().st_mode & 0o777, 0o600)
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            document = json.loads(permit.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], "report-admin-permit-v1")
            self.assertEqual(document["action"], "activate")
            self.assertEqual(document["expected_launcher_sha256"], "b" * 64)
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8"))["status"],
                "installed",
            )
            second = self._admin(*arguments, control_root=control)
            self.assertNotEqual(second.returncode, 0)

    def test_activate_uses_admin_permit_and_switches_only_report_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp) / "host"
            releases = host / "opt/reddit-voc-daily-report/releases"
            releases.mkdir(parents=True, mode=0o700)
            old_release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id="sha256:" + "6" * 64,
            )
            image_id = "sha256:" + "7" * 64
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id=image_id,
            )
            current = host / "opt/reddit-voc-daily-report/current"
            current.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            current.symlink_to(old_release)

            launcher_target = host / "opt/reddit-voc-site/scripts/server_daily_report.sh"
            launcher_target.parent.mkdir(parents=True, mode=0o700)
            launcher_target.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
            launcher_target.chmod(0o755)
            old_launcher_sha = hashlib.sha256(launcher_target.read_bytes()).hexdigest()
            new_launcher = release / "scripts/server_daily_report.sh"
            new_launcher_sha = hashlib.sha256(new_launcher.read_bytes()).hexdigest()

            secret_root = host / "home/ubuntu/.reddit-voc/secrets"
            secret_root.mkdir(parents=True, mode=0o700)
            report_env = secret_root / "reddit-voc-report.env"
            report_env.write_text(
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n",
                encoding="utf-8",
            )
            report_env.chmod(0o600)
            cron = host / "etc/cron.d/reddit-voc-site"
            cron.parent.mkdir(parents=True, mode=0o700)
            cron.write_text("fixed-cron\n", encoding="utf-8")
            cron.chmod(0o600)
            cron_sha = hashlib.sha256(cron.read_bytes()).hexdigest()

            fake_bin = host / "fake-bin"
            fake_bin.mkdir(mode=0o700)
            docker = fake_bin / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "[[ \"$1\" == network && \"$2\" == inspect ]] || exit 1\n"
                "if [[ \"$*\" == *Driver* ]]; then printf 'bridge\\n'; "
                "elif [[ \"$*\" == *Containers* ]]; then printf '0\\n'; "
                "elif [[ \"$*\" == *Internal* ]]; then printf 'false\\n'; "
                "else exit 1; fi\n",
                encoding="utf-8",
            )
            smoke = fake_bin / "smoke"
            smoke.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'runtime_smoke=passed\\nprovider_call=false\\n"
                "translation_provider_attempt_made=false\\n"
                "report_live_send=false\\nlive_send=false\\n'\n",
                encoding="utf-8",
            )
            docker.chmod(0o700)
            smoke.chmod(0o700)

            control = host / "home/ubuntu/.reddit-voc/report-control"
            authorization_id = "admin-activate-local-host"
            installed = self._admin(
                "install-admin-permit",
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release.name,
                "--action",
                "activate",
                "--expected-launcher-sha256",
                new_launcher_sha,
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
                control_root=control,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            activated = self._admin(
                "activate",
                "--host-root",
                str(host),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release.name,
                "--expected-launcher-sha256",
                new_launcher_sha,
                "--expected-old-launcher-sha256",
                old_launcher_sha,
                "--expected-current-release-sha256",
                old_release.name,
                "--expected-cron-sha256",
                cron_sha,
                "--maintenance-window-id",
                "maintenance-20260714-local",
                "--authorize-activate",
                "--allow-local-maintenance-window",
                "--docker-bin",
                str(docker),
                "--local-smoke-command",
                str(smoke),
            )
            self.assertEqual(activated.returncode, 0, activated.stderr)
            self.assertEqual(current.resolve(strict=True), release.resolve(strict=True))
            self.assertEqual(launcher_target.read_bytes(), new_launcher.read_bytes())
            self.assertEqual(hashlib.sha256(cron.read_bytes()).hexdigest(), cron_sha)
            state = json.loads(
                control.joinpath(
                    "permit-state", f"{authorization_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "consumed")
            self.assertFalse(control.joinpath("report.freeze").exists())
            self.assertIn("provider_call=false", activated.stdout)
            self.assertIn("live_send=false", activated.stdout)

            rollback_id = "admin-rollback-local-host"
            rollback_installed = self._admin(
                "install-admin-permit",
                "--authorization-id",
                rollback_id,
                "--expected-release-sha256",
                old_release.name,
                "--action",
                "rollback",
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
                control_root=control,
            )
            self.assertEqual(
                rollback_installed.returncode, 0, rollback_installed.stderr
            )
            rolled_back = self._admin(
                "rollback",
                "--host-root",
                str(host),
                "--authorization-id",
                rollback_id,
                "--expected-release-sha256",
                old_release.name,
                "--expected-launcher-sha256",
                new_launcher_sha,
                "--expected-current-release-sha256",
                release.name,
                "--expected-cron-sha256",
                cron_sha,
                "--maintenance-window-id",
                "maintenance-20260714-rollback",
                "--authorize-rollback",
                "--allow-local-maintenance-window",
                "--docker-bin",
                str(docker),
                "--local-smoke-command",
                str(smoke),
            )
            self.assertEqual(rolled_back.returncode, 0, rolled_back.stderr)
            self.assertEqual(
                current.resolve(strict=True), old_release.resolve(strict=True)
            )
            self.assertEqual(launcher_target.read_bytes(), new_launcher.read_bytes())
            rollback_state = json.loads(
                control.joinpath(
                    "permit-state", f"{rollback_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(rollback_state["status"], "consumed")

    def test_bootstrap_supports_explicit_absent_current_and_creates_report_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp) / "host"
            releases = host / "opt/reddit-voc-daily-report/releases"
            releases.mkdir(parents=True, mode=0o700)
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id="sha256:" + "8" * 64,
            )
            launcher_target = host / "opt/reddit-voc-site/scripts/server_daily_report.sh"
            launcher_target.parent.mkdir(parents=True, mode=0o700)
            launcher_target.write_text("#!/usr/bin/env bash\nexit 4\n", encoding="utf-8")
            launcher_target.chmod(0o755)
            old_launcher_sha = hashlib.sha256(launcher_target.read_bytes()).hexdigest()
            new_launcher_sha = hashlib.sha256(
                release.joinpath("scripts/server_daily_report.sh").read_bytes()
            ).hexdigest()
            secret_root = host / "home/ubuntu/.reddit-voc/secrets"
            secret_root.mkdir(parents=True, mode=0o700)
            report_env = secret_root / "reddit-voc-report.env"
            report_env.write_text(
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n",
                encoding="utf-8",
            )
            report_env.chmod(0o600)
            cron = host / "etc/cron.d/reddit-voc-site"
            cron.parent.mkdir(parents=True, mode=0o700)
            cron.write_text("unchanged-cron\n", encoding="utf-8")
            cron.chmod(0o600)
            cron_sha = hashlib.sha256(cron.read_bytes()).hexdigest()
            fake_bin = host / "fake-bin"
            fake_bin.mkdir(mode=0o700)
            network_state = host / "network-created"
            docker = fake_bin / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "if [[ \"$1\" == network && \"$2\" == create ]]; then\n"
                f"  : >\"{network_state}\"; printf 'network-id\\n'; exit 0\n"
                "fi\n"
                f"[[ -f \"{network_state}\" ]] || exit 1\n"
                "if [[ \"$*\" == *Driver* ]]; then printf 'bridge\\n'; "
                "elif [[ \"$*\" == *Containers* ]]; then printf '0\\n'; "
                "elif [[ \"$*\" == *Internal* ]]; then printf 'false\\n'; "
                "else exit 1; fi\n",
                encoding="utf-8",
            )
            smoke = fake_bin / "smoke"
            smoke.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'runtime_smoke=passed\\nprovider_call=false\\n"
                "translation_provider_attempt_made=false\\n"
                "report_live_send=false\\nlive_send=false\\n'\n",
                encoding="utf-8",
            )
            docker.chmod(0o700)
            smoke.chmod(0o700)
            control = host / "home/ubuntu/.reddit-voc/report-control"
            authorization_id = "admin-bootstrap-local-host"
            installed = self._admin(
                "install-admin-permit",
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release.name,
                "--action",
                "bootstrap",
                "--expected-launcher-sha256",
                new_launcher_sha,
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
                control_root=control,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            bootstrapped = self._admin(
                "bootstrap",
                "--host-root",
                str(host),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release.name,
                "--expected-launcher-sha256",
                new_launcher_sha,
                "--expected-old-launcher-sha256",
                old_launcher_sha,
                "--expected-current-release-sha256",
                "absent",
                "--expected-cron-sha256",
                cron_sha,
                "--maintenance-window-id",
                "maintenance-20260714-bootstrap",
                "--authorize-bootstrap",
                "--allow-local-maintenance-window",
                "--docker-bin",
                str(docker),
                "--local-smoke-command",
                str(smoke),
            )
            self.assertEqual(bootstrapped.returncode, 0, bootstrapped.stderr)
            self.assertTrue(network_state.exists())
            current = host / "opt/reddit-voc-daily-report/current"
            self.assertEqual(current.resolve(strict=True), release.resolve(strict=True))
            backup = control / "backups" / authorization_id
            self.assertTrue((backup / "launcher").is_file())
            self.assertTrue((backup / "report-env").is_file())
            self.assertFalse((control / "report.freeze").exists())

    def test_prepare_permit_lifecycle_is_one_way_and_hash_chain_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            install = self._admin(
                "install-prepare-permit",
                "--authorization-id",
                "prepare-auth-lifecycle",
                "--expected-release-sha256",
                "c" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
                "--max-attempts",
                "100",
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
                control_root=control,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            reserved = self._admin(
                "reserve-permit",
                "--authorization-id",
                "prepare-auth-lifecycle",
                "--expected-release-sha256",
                "c" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
                control_root=control,
            )
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            terminal = self._admin(
                "terminalize-permit",
                "--authorization-id",
                "prepare-auth-lifecycle",
                "--expected-release-sha256",
                "c" * 64,
                "--terminal-status",
                "consumed",
                control_root=control,
            )
            self.assertEqual(terminal.returncode, 0, terminal.stderr)
            repeated = self._admin(
                "reserve-permit",
                "--authorization-id",
                "prepare-auth-lifecycle",
                "--expected-release-sha256",
                "c" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
                control_root=control,
            )
            self.assertNotEqual(repeated.returncode, 0)
            state = json.loads(
                control.joinpath(
                    "permit-state", "prepare-auth-lifecycle.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "consumed")
            audit_rows = [
                json.loads(line)
                for line in control.joinpath(
                    "audit", "authorization.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [row["event"] for row in audit_rows],
                ["installed", "reserved", "consumed"],
            )
            self.assertEqual(audit_rows[0]["previous_entry_sha256"], "0" * 64)
            self.assertEqual(
                audit_rows[1]["previous_entry_sha256"],
                audit_rows[0]["entry_sha256"],
            )

    def test_permit_state_is_fail_closed_before_audit_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            document = {
                "schema_version": "report-prepare-permit-v1",
                "authorization_id": "prepare-audit-failure",
                "release_sha256": "a" * 64,
                "run_id": "daily_collect_20260714_0700",
                "expires_at": "2030-07-14T00:00:00+00:00",
                "max_attempts": 1,
                "live_send": False,
            }
            with mock.patch.object(
                report_control,
                "_append_audit",
                side_effect=report_control.ReportControlError("audit_failed"),
            ):
                with self.assertRaisesRegex(
                    report_control.ReportControlError, "audit_failed"
                ):
                    report_control._install_permit(root=control, document=document)
            state_path = control / "permit-state/prepare-audit-failure.json"
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "installed",
            )
            with self.assertRaisesRegex(
                report_control.ReportControlError, "permit_exists"
            ):
                report_control._install_permit(root=control, document=document)

            report_control._append_audit(
                root=control,
                permit=document,
                event="installed_reconciled",
                status="installed",
            )
            with mock.patch.object(
                report_control,
                "_append_audit",
                side_effect=report_control.ReportControlError("audit_failed"),
            ):
                with self.assertRaisesRegex(
                    report_control.ReportControlError, "audit_failed"
                ):
                    report_control._transition_permit(
                        root=control,
                        authorization_id="prepare-audit-failure",
                        expected_release_sha256="a" * 64,
                        expected_run_id="daily_collect_20260714_0700",
                        target_status="reserved",
                    )
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "reserved",
            )

    def test_shadow_root_descriptor_and_permit_are_isolated_and_no_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-one",
                "--expected-release-sha256",
                "d" * 64,
                "--candidate-sha256",
                "e" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            descriptor_path = shadow / "shadow-root.json"
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            self.assertEqual(descriptor["schema_version"], "report-shadow-root-v1")
            self.assertEqual(descriptor["shadow_root"], str(shadow.resolve()))
            self.assertEqual(descriptor_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(shadow.stat().st_mode & 0o777, 0o700)
            self.assertNotIn("key", json.dumps(descriptor).casefold())

            installed = self._admin(
                "install-shadow-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provider-one",
                "--expected-release-sha256",
                "d" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
                "--copied-database-sha256",
                "f" * 64,
                "--max-attempts",
                "100",
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            permit = json.loads(
                shadow.joinpath(
                    "control", "permits", "shadow-provider-one.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(permit["schema_version"], "report-shadow-permit-v1")
            self.assertEqual(permit["report_count"], 1)
            self.assertFalse(permit["live_send"])
            self.assertEqual(permit["max_attempts"], 100)

    def test_shadow_root_rejects_repo_overlap_before_creation(self) -> None:
        shadow = ROOT / "tmp" / "forbidden-shadow-root"
        result = self._admin(
            "init-shadow-root",
            "--shadow-root",
            str(shadow),
            "--authorization-id",
            "shadow-provision-overlap",
            "--expected-release-sha256",
            "1" * 64,
            "--candidate-sha256",
            "2" * 64,
            "--authorize-shadow-provisioning",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(shadow.exists())

    def test_shadow_gate_set_and_restore_preserve_every_non_gate_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shadow, original = self._shadow_with_reserved_permit(Path(tmp))
            enabled = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provider-gates",
                "--expected-release-sha256",
                "3" * 64,
                "--journal-id",
                "gate-journal-one",
                "--translation-mode",
                "deepseek",
                "--enable-deepseek",
                "1",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            active = (shadow / "secrets" / "reddit-voc-report.env").read_bytes()
            self.assertIn(b"REDDIT_VOC_TRANSLATION_MODE=deepseek\n", active)
            self.assertIn(b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n", active)
            self.assertIn(original.splitlines(keepends=True)[0], active)
            self.assertIn(original.splitlines(keepends=True)[1], active)
            self.assertIn(original.splitlines(keepends=True)[2], active)
            self.assertIn(original.splitlines(keepends=True)[3], active)
            journal = json.loads(
                shadow.joinpath(
                    "control", "gates", "gate-journal-one.json"
                ).read_text(encoding="utf-8")
            )
            encoded_journal = json.dumps(journal, sort_keys=True)
            self.assertNotIn("synthetic-secret-value", encoded_journal)
            self.assertNotIn("never-run", encoded_journal)
            snapshot = shadow / "secrets" / "snapshots" / journal["snapshot_id"]
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)

            restored = self._updater(
                "restore-gates",
                "--shadow-root",
                str(shadow),
                "--journal-id",
                "gate-journal-one",
            )
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(
                (shadow / "secrets" / "reddit-voc-report.env").read_bytes(),
                original,
            )
            self.assertFalse(snapshot.exists())
            terminal = json.loads(
                shadow.joinpath(
                    "control", "gates", "gate-journal-one.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(terminal["phase"], "restored")

    def test_base_env_verification_never_auto_recovers_enabled_legacy_gate(self) -> None:
        """Cron must fail closed instead of replacing the credential inode."""
        with tempfile.TemporaryDirectory() as tmp:
            shadow, _original = self._shadow_with_reserved_permit(Path(tmp))
            enabled = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provider-gates",
                "--expected-release-sha256",
                "3" * 64,
                "--journal-id",
                "legacy-active-gate",
                "--translation-mode",
                "deepseek",
                "--enable-deepseek",
                "1",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            env_path = shadow / "secrets/reddit-voc-report.env"
            active_payload = env_path.read_bytes()
            active_inode = env_path.stat().st_ino
            verified = self._updater(
                "verify-base-env", "--shadow-root", str(shadow)
            )
            self.assertNotEqual(verified.returncode, 0)
            self.assertIn("runtime_base_env_not_immutable", verified.stderr)
            self.assertEqual(env_path.stat().st_ino, active_inode)
            self.assertEqual(env_path.read_bytes(), active_payload)

    def test_shadow_secret_install_is_stdin_only_atomic_and_forces_gates_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-secrets",
                "--expected-release-sha256",
                "2" * 64,
                "--candidate-sha256",
                "3" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            synthetic_webhook = "synthetic-webhook-must-not-print"
            env_input = (
                "# preserved comment\n"
                f"DINGTALK_WEBHOOK_URL={synthetic_webhook}\n"
                "DINGTALK_WEBHOOK_SECRET=synthetic-signing-secret\n"
                "REDDIT_VOC_TRANSLATION_MODE=deepseek\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n"
                "REDDIT_VOC_DINGTALK_MODE=live\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1\n"
            )
            installed_env = self._updater_with_input(
                "install-env",
                "--shadow-root",
                str(shadow),
                "--authorize-secret-provisioning",
                input_text=env_input,
            )
            self.assertEqual(installed_env.returncode, 0, installed_env.stderr)
            self.assertNotIn(
                synthetic_webhook, installed_env.stdout + installed_env.stderr
            )
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            installed_payload = env_path.read_text(encoding="utf-8")
            self.assertIn("# preserved comment\n", installed_payload)
            self.assertIn(f"DINGTALK_WEBHOOK_URL={synthetic_webhook}\n", installed_payload)
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run\n", installed_payload)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n", installed_payload)
            self.assertIn("REDDIT_VOC_DINGTALK_MODE=dry_run\n", installed_payload)
            self.assertIn("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n", installed_payload)
            self.assertIn("REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n", installed_payload)
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

            synthetic_key = "sk-synthetic-only-never-print"
            installed_key = self._updater_with_input(
                "install-key",
                "--shadow-root",
                str(shadow),
                "--authorize-secret-provisioning",
                input_text=synthetic_key + "\n",
            )
            self.assertEqual(installed_key.returncode, 0, installed_key.stderr)
            self.assertNotIn(
                synthetic_key, installed_key.stdout + installed_key.stderr
            )
            key_path = shadow / "secrets" / "deepseek-api-key"
            self.assertEqual(key_path.read_bytes(), synthetic_key.encode("utf-8"))
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)

            checked = self._updater(
                "check",
                "--shadow-root",
                str(shadow),
                "--authorize-secret-provisioning",
                "--check-key",
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("secrets=<redacted>", checked.stdout)
            self.assertNotIn(synthetic_key, checked.stdout + checked.stderr)

    def test_shadow_secret_install_rejects_missing_authority_and_malformed_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-secret-reject",
                "--expected-release-sha256",
                "4" * 64,
                "--candidate-sha256",
                "5" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            missing_authority = self._updater_with_input(
                "install-key",
                "--shadow-root",
                str(shadow),
                input_text="sk-synthetic\n",
            )
            self.assertNotEqual(missing_authority.returncode, 0)
            self.assertFalse(
                (shadow / "secrets" / "deepseek-api-key").exists()
            )
            malformed = self._updater_with_input(
                "install-env",
                "--shadow-root",
                str(shadow),
                "--authorize-secret-provisioning",
                input_text=(
                    "UNEXPECTED_NAME=value\n"
                    "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                    "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
                ),
            )
            self.assertNotEqual(malformed.returncode, 0)
            self.assertFalse(
                (shadow / "secrets" / "reddit-voc-report.env").exists()
            )

    def test_materialized_prepare_env_is_attempt_scoped_and_strips_dingtalk_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow, _original = self._shadow_with_reserved_permit(root)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            secret = "synthetic-webhook-secret-must-not-copy"
            database_path = (shadow / "database" / "reddit_voc.sqlite3").resolve(
                strict=False
            )
            env_path.write_bytes(
                f"REDDIT_VOC_DATABASE_PATH={database_path}\n".encode("utf-8")
                + b"REDDIT_VOC_RUN_ID=\n"
                b"REDDIT_VOC_ATTEMPT_ID=\n"
                b"REDDIT_VOC_ARTIFACT_VERSION_ID=\n"
                b"REDDIT_VOC_REPORT_PUBLIC_ROOT=\n"
                b"REDDIT_VOC_REPORT_PRIVATE_ROOT=\n"
                b"REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT=\n"
                b"REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT=\n"
                b"REDDIT_VOC_REPORT_STATE_ROOT=\n"
                b"REDDIT_VOC_REPORT_BLOCKED_ROOT=\n"
                b"REDDIT_VOC_REPORT_HANDOFF_ROOT=\n"
                b"REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=\n"
                b"REDDIT_VOC_CONFIG_ROOT=\n"
                b"REDDIT_VOC_ARTIFACT_BASE_URL=https://reddit.brand.lute-tlz-dddd.top/artifacts\n"
                b"DINGTALK_REQUIRED_KEYWORD=LL\n"
                b"REDDIT_VOC_DINGTALK_MAX_BYTES=18000\n"
                b"REDDIT_VOC_DINGTALK_MAX_PARTS=2\n"
                b"REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
                b"DINGTALK_WEBHOOK_URL=https://example.invalid/hook\n"
                + f"DINGTALK_WEBHOOK_SECRET={secret}\n".encode("utf-8")
            )
            env_path.chmod(0o600)
            installed_action = self._admin(
                "install-prepare-permit",
                "--control-root",
                str(shadow / "control"),
                "--authorization-id",
                "prepare-action-materialized",
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
                "--max-attempts",
                "100",
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
            )
            self.assertEqual(installed_action.returncode, 0, installed_action.stderr)
            reserved_action = self._admin(
                "reserve-permit",
                "--control-root",
                str(shadow / "control"),
                "--authorization-id",
                "prepare-action-materialized",
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
            )
            self.assertEqual(reserved_action.returncode, 0, reserved_action.stderr)
            materialized = self._updater(
                "materialize-prepare-env",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "prepare-action-materialized",
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                "daily_collect_20260714_0700",
                "--attempt-id",
                "attempt-materialized",
                "--artifact-version-id",
                "20260714T010203456789Z-" + "1" * 32,
            )
            self.assertEqual(materialized.returncode, 0, materialized.stderr)
            self.assertNotIn(secret, materialized.stdout + materialized.stderr)
            attempt_env = (
                shadow
                / "control"
                / "runtime-env"
                / "attempt-materialized.env"
            )
            payload = attempt_env.read_text(encoding="utf-8")
            self.assertEqual(attempt_env.stat().st_mode & 0o777, 0o600)
            self.assertIn(f"REDDIT_VOC_DATABASE_PATH={database_path}", payload)
            self.assertIn(
                f"REDDIT_VOC_REPORT_PUBLIC_ROOT={(shadow / 'public').resolve()}",
                payload,
            )
            self.assertIn(
                f"REDDIT_VOC_REPORT_HANDOFF_ROOT={(shadow / 'handoff').resolve()}",
                payload,
            )
            self.assertIn("REDDIT_VOC_CONFIG_ROOT=/app/config", payload)
            self.assertIn(
                "REDDIT_VOC_ARTIFACT_BASE_URL=https://reddit.lute-tlz-dddd.top/artifacts\n",
                payload,
            )
            self.assertNotIn("reddit.brand.lute-tlz-dddd.top", payload)
            self.assertIn("DINGTALK_WEBHOOK_URL=\n", payload)
            self.assertIn("DINGTALK_WEBHOOK_SECRET=\n", payload)
            self.assertNotIn(secret, payload)
            removed = self._updater(
                "remove-runtime-env",
                "--shadow-root",
                str(shadow),
                "--attempt-id",
                "attempt-materialized",
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(attempt_env.exists())

    def test_provider_prepare_is_attempt_scoped_and_keeps_base_env_inode(self) -> None:
        """A successful translation attempt must not poison the next cron run."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow, _original = self._shadow_with_reserved_permit(root)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            database_path = (shadow / "database" / "reddit_voc.sqlite3").resolve(
                strict=False
            )
            env_path.write_bytes(
                f"REDDIT_VOC_DATABASE_PATH={database_path}\n".encode("utf-8")
                + b"REDDIT_VOC_RUN_ID=\n"
                b"REDDIT_VOC_ATTEMPT_ID=\n"
                b"REDDIT_VOC_ARTIFACT_VERSION_ID=\n"
                b"REDDIT_VOC_REPORT_PUBLIC_ROOT=\n"
                b"REDDIT_VOC_REPORT_PRIVATE_ROOT=\n"
                b"REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT=\n"
                b"REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT=\n"
                b"REDDIT_VOC_REPORT_STATE_ROOT=\n"
                b"REDDIT_VOC_REPORT_BLOCKED_ROOT=\n"
                b"REDDIT_VOC_REPORT_HANDOFF_ROOT=\n"
                b"REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=\n"
                b"REDDIT_VOC_CONFIG_ROOT=\n"
                b"REDDIT_VOC_ARTIFACT_BASE_URL=https://reddit.brand.lute-tlz-dddd.top/artifacts\n"
                b"DINGTALK_REQUIRED_KEYWORD=LL\n"
                b"REDDIT_VOC_DINGTALK_MAX_BYTES=18000\n"
                b"REDDIT_VOC_DINGTALK_MAX_PARTS=2\n"
                b"REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
                b"DINGTALK_WEBHOOK_URL=https://example.invalid/hook\n"
                b"DINGTALK_WEBHOOK_SECRET=synthetic-secret\n"
            )
            env_path.chmod(0o600)
            base_payload = env_path.read_bytes()
            base_inode = env_path.stat().st_ino
            run_id = "daily_collect_20260714_0700"
            action_id = "prepare-action-immutable-base"
            provider_id = "shadow-provider-gates"
            attempt_id = "attempt-immutable-base"
            installed = self._admin(
                "install-prepare-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                action_id,
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                run_id,
                "--max-attempts",
                "100",
                "--expires-at",
                "2030-07-14T00:00:00+00:00",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            reserved = self._admin(
                "reserve-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                action_id,
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                run_id,
            )
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            bound = self._admin(
                "bind-provider-attempt",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                provider_id,
                "--prepare-action-authorization-id",
                action_id,
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            materialized = self._updater(
                "materialize-prepare-env",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                action_id,
                "--provider-authorization-id",
                provider_id,
                "--expected-release-sha256",
                "3" * 64,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--artifact-version-id",
                "20260714T010203456789Z-" + "2" * 32,
            )
            self.assertEqual(materialized.returncode, 0, materialized.stderr)
            self.assertEqual(env_path.stat().st_ino, base_inode)
            self.assertEqual(env_path.read_bytes(), base_payload)
            attempt_env = shadow / "control/runtime-env" / f"{attempt_id}.env"
            attempt_payload = attempt_env.read_text(encoding="utf-8")
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=deepseek\n", attempt_payload)
            self.assertIn(
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n", attempt_payload
            )
            self.assertIn("REDDIT_VOC_DINGTALK_MODE=dry_run\n", attempt_payload)
            self.assertIn("DINGTALK_WEBHOOK_URL=\n", attempt_payload)
            self.assertIn("DINGTALK_WEBHOOK_SECRET=\n", attempt_payload)
            self.assertNotIn("synthetic-secret", attempt_payload)
            self.assertIn(
                "REDDIT_VOC_ARTIFACT_BASE_URL=https://reddit.lute-tlz-dddd.top/artifacts\n",
                attempt_payload,
            )
            self.assertNotIn("reddit.brand.lute-tlz-dddd.top", attempt_payload)
            verified = self._updater(
                "verify-base-env", "--shadow-root", str(shadow)
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_materialized_send_env_requires_exact_reserved_permit_and_has_send_only_scope(self) -> None:
        """Catches tuple drift or a send runtime inheriting prepare/Provider authority."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            release_sha = "8" * 64
            run_id = "daily_collect_20260715_0700"
            version_id = "20260715T010203456789Z-" + "8" * 32
            bundle_sha = "9" * 64
            outbox_sha = "a" * 64
            authorization_id = "send-materialized-exact"
            attempt_id = "send-attempt-materialized"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-send-materialized",
                "--expected-release-sha256",
                release_sha,
                "--candidate-sha256",
                "7" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            database = (shadow / "database" / "reddit_voc.sqlite3").resolve(
                strict=False
            )
            database.write_bytes(b"fixture")
            database.chmod(0o600)
            webhook = "https://example.invalid/robot/send?access_token=send-fixture"
            webhook_secret = "synthetic-send-secret-never-print"
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            env_path.write_text(
                "\n".join(
                    [
                        f"REDDIT_VOC_DATABASE_PATH={database}",
                        "REDDIT_VOC_RUN_ID=",
                        "REDDIT_VOC_ATTEMPT_ID=",
                        "REDDIT_VOC_ARTIFACT_VERSION_ID=",
                        "REDDIT_VOC_REPORT_PUBLIC_ROOT=",
                        "REDDIT_VOC_REPORT_PRIVATE_ROOT=",
                        "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT=",
                        "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT=",
                        "REDDIT_VOC_REPORT_STATE_ROOT=",
                        "REDDIT_VOC_REPORT_BLOCKED_ROOT=",
                        "REDDIT_VOC_REPORT_HANDOFF_ROOT=",
                        "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=",
                        "REDDIT_VOC_CONFIG_ROOT=",
                        "REDDIT_VOC_ARTIFACT_BASE_URL=https://files.example/reddit-voc",
                        "DINGTALK_REQUIRED_KEYWORD=LL",
                        "REDDIT_VOC_DINGTALK_MAX_BYTES=18000",
                        "REDDIT_VOC_DINGTALK_MAX_PARTS=2",
                        "REDDIT_VOC_TRANSLATION_MODE=dry_run",
                        "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0",
                        "REDDIT_VOC_DINGTALK_MODE=dry_run",
                        "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0",
                        "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0",
                        f"DINGTALK_WEBHOOK_URL={webhook}",
                        f"DINGTALK_WEBHOOK_SECRET={webhook_secret}",
                        "DINGTALK_WEBHOOK_URL_2=",
                        "DINGTALK_WEBHOOK_SECRET_2=",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env_path.chmod(0o600)
            installed = self._admin(
                "install-send-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--expected-artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                outbox_sha,
                "--action",
                "initial",
                "--expires-at",
                "2030-07-15T00:00:00+00:00",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            unreserved = self._updater(
                "materialize-send-env",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                outbox_sha,
                "--action",
                "initial",
            )
            self.assertNotEqual(unreserved.returncode, 0)
            self.assertFalse(
                (shadow / "control" / "runtime-env" / f"{attempt_id}.env").exists()
            )

            reserved = self._admin(
                "reserve-send-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--expected-artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                outbox_sha,
                "--action",
                "initial",
            )
            self.assertEqual(reserved.returncode, 0, reserved.stderr)
            mismatch = self._updater(
                "materialize-send-env",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                "send-attempt-mismatch",
                "--artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                "b" * 64,
                "--action",
                "initial",
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("send_permit_not_reserved", mismatch.stderr)

            materialized = self._updater(
                "materialize-send-env",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--attempt-id",
                attempt_id,
                "--artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                outbox_sha,
                "--action",
                "initial",
            )
            self.assertEqual(materialized.returncode, 0, materialized.stderr)
            self.assertNotIn(webhook, materialized.stdout + materialized.stderr)
            self.assertNotIn(
                webhook_secret, materialized.stdout + materialized.stderr
            )
            runtime_env = (
                shadow / "control" / "runtime-env" / f"{attempt_id}.env"
            )
            payload = runtime_env.read_text(encoding="utf-8")
            self.assertEqual(runtime_env.stat().st_mode & 0o777, 0o600)
            self.assertIn(f"REDDIT_VOC_RUN_ID={run_id}\n", payload)
            self.assertIn(f"REDDIT_VOC_ARTIFACT_VERSION_ID={version_id}\n", payload)
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run\n", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n", payload)
            self.assertIn("REDDIT_VOC_DINGTALK_MODE=live\n", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1\n", payload)
            self.assertIn("REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n", payload)
            self.assertIn("REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT=\n", payload)
            self.assertIn("REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT=\n", payload)
            self.assertIn("REDDIT_VOC_REPORT_BLOCKED_ROOT=\n", payload)
            self.assertIn("REDDIT_VOC_REPORT_HANDOFF_ROOT=\n", payload)
            self.assertIn("REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=\n", payload)
            self.assertIn(f"DINGTALK_WEBHOOK_URL={webhook}\n", payload)
            self.assertIn(
                f"DINGTALK_WEBHOOK_SECRET={webhook_secret}\n", payload
            )
            self.assertNotIn("DINGTALK_WEBHOOK_URL_2=", payload)
            self.assertNotIn("DINGTALK_WEBHOOK_SECRET_2=", payload)
            wrong_terminal = self._admin(
                "terminalize-send-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--expected-artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                "b" * 64,
                "--action",
                "initial",
                "--terminal-status",
                "consumed",
            )
            self.assertNotEqual(wrong_terminal.returncode, 0)
            state_path = (
                shadow
                / "control"
                / "permit-state"
                / f"{authorization_id}.json"
            )
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "reserved",
            )
            terminal = self._admin(
                "terminalize-send-permit",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                authorization_id,
                "--expected-release-sha256",
                release_sha,
                "--run-id",
                run_id,
                "--expected-artifact-version-id",
                version_id,
                "--expected-bundle-sha256",
                bundle_sha,
                "--expected-outbox-sha256",
                outbox_sha,
                "--action",
                "initial",
                "--terminal-status",
                "consumed",
            )
            self.assertEqual(terminal.returncode, 0, terminal.stderr)
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["status"],
                "consumed",
            )

    def test_shadow_updater_accepts_only_exact_inherited_locked_fd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow, _original = self._shadow_with_reserved_permit(root)
            lock_path = shadow / "lock"
            held = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                accepted = self._updater_with_input(
                    "check",
                    "--shadow-root",
                    str(shadow),
                    "--authorize-secret-provisioning",
                    "--inherited-lock-fd",
                    str(held),
                    input_text="",
                    pass_fds=(held,),
                )
            finally:
                os.close(held)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            unlocked = os.open(lock_path, os.O_RDWR)
            try:
                rejected_unlocked = self._updater_with_input(
                    "check",
                    "--shadow-root",
                    str(shadow),
                    "--authorize-secret-provisioning",
                    "--inherited-lock-fd",
                    str(unlocked),
                    input_text="",
                    pass_fds=(unlocked,),
                )
            finally:
                os.close(unlocked)
            self.assertNotEqual(rejected_unlocked.returncode, 0)

            unrelated_path = root / "unrelated.lock"
            unrelated = os.open(unrelated_path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(unrelated, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                rejected_unrelated = self._updater_with_input(
                    "check",
                    "--shadow-root",
                    str(shadow),
                    "--authorize-secret-provisioning",
                    "--inherited-lock-fd",
                    str(unrelated),
                    input_text="",
                    pass_fds=(unrelated,),
                )
            finally:
                os.close(unrelated)
            self.assertNotEqual(rejected_unrelated.returncode, 0)

    def test_shadow_recover_never_restores_enabled_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shadow, original = self._shadow_with_reserved_permit(Path(tmp))
            enabled = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provider-gates",
                "--expected-release-sha256",
                "3" * 64,
                "--journal-id",
                "gate-journal-crash",
                "--translation-mode",
                "deepseek",
                "--enable-deepseek",
                "1",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            recovered = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(
                (shadow / "secrets" / "reddit-voc-report.env").read_bytes(),
                original,
            )
            journal = json.loads(
                shadow.joinpath(
                    "control", "gates", "gate-journal-crash.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(journal["phase"], "recovered_all_off")
            self.assertEqual(list((shadow / "secrets" / "snapshots").iterdir()), [])

    def test_terminal_kill_switch_needs_no_provider_permit_and_cannot_enable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-kill",
                "--expected-release-sha256",
                "6" * 64,
                "--candidate-sha256",
                "7" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            env_path.write_bytes(
                b"REDDIT_VOC_TRANSLATION_MODE=deepseek\n"
                b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n"
                b"REDDIT_VOC_DINGTALK_MODE=live\n"
                b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1\n"
                b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1\n"
            )
            env_path.chmod(0o600)
            killed = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "kill-switch-one",
                "--expected-release-sha256",
                "6" * 64,
                "--journal-id",
                "kill-journal-one",
                "--translation-mode",
                "dry_run",
                "--enable-deepseek",
                "0",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
                "--terminal-kill-switch",
            )
            self.assertEqual(killed.returncode, 0, killed.stderr)
            payload = env_path.read_text(encoding="utf-8")
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0", payload)
            forbidden = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "kill-switch-two",
                "--expected-release-sha256",
                "6" * 64,
                "--journal-id",
                "kill-journal-two",
                "--translation-mode",
                "deepseek",
                "--enable-deepseek",
                "1",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
                "--terminal-kill-switch",
            )
            self.assertNotEqual(forbidden.returncode, 0)

    def test_shadow_lock_contention_mutates_no_gate_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shadow, original = self._shadow_with_reserved_permit(Path(tmp))
            lock_path = shadow / "lock"
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = self._updater(
                    "recover-gates", "--shadow-root", str(shadow)
                )
            finally:
                os.close(descriptor)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reason=lock_busy", result.stderr)
            self.assertEqual(
                (shadow / "secrets" / "reddit-voc-report.env").read_bytes(),
                original,
            )

    def test_restore_conflict_forces_all_gates_off_before_returning_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shadow, _original = self._shadow_with_reserved_permit(Path(tmp))
            enabled = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provider-gates",
                "--expected-release-sha256",
                "3" * 64,
                "--journal-id",
                "gate-journal-conflict",
                "--translation-mode",
                "deepseek",
                "--enable-deepseek",
                "1",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            env_path.write_bytes(
                env_path.read_bytes().replace(
                    b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0",
                    b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1",
                )
            )
            env_path.chmod(0o600)
            restored = self._updater(
                "restore-gates",
                "--shadow-root",
                str(shadow),
                "--journal-id",
                "gate-journal-conflict",
            )
            self.assertNotEqual(restored.returncode, 0)
            payload = env_path.read_text(encoding="utf-8")
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0", payload)
            self.assertIn("REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0", payload)
            journal = json.loads(
                shadow.joinpath(
                    "control", "gates", "gate-journal-conflict.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(journal["phase"], "recovered_all_off")

    def test_recover_multiple_active_journals_forces_all_off_and_terminals_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shadow, _original = self._shadow_with_reserved_permit(Path(tmp))
            enabled = self._updater(
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provider-gates",
                "--expected-release-sha256",
                "3" * 64,
                "--journal-id",
                "gate-journal-primary",
                "--translation-mode",
                "deepseek",
                "--enable-deepseek",
                "1",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            gates_root = shadow / "control" / "gates"
            duplicate = json.loads(
                gates_root.joinpath("gate-journal-primary.json").read_text(
                    encoding="utf-8"
                )
            )
            duplicate["journal_id"] = "gate-journal-secondary"
            second = gates_root / "gate-journal-secondary.json"
            second.write_text(
                json.dumps(duplicate, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            second.chmod(0o600)
            recovered = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            payload = (shadow / "secrets" / "reddit-voc-report.env").read_text(
                encoding="utf-8"
            )
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0", payload)
            for path in gates_root.glob("*.json"):
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))["phase"],
                    "recovered_all_off",
                )

    def test_recover_malformed_env_quarantines_and_installs_minimal_all_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-malformed",
                "--expected-release-sha256",
                "8" * 64,
                "--candidate-sha256",
                "9" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            env_path.write_bytes(
                b"DINGTALK_WEBHOOK_SECRET=must-not-print\n"
                b"REDDIT_VOC_TRANSLATION_MODE=deepseek\n"
                b"REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n"
                b"REDDIT_VOC_DINGTALK_MODE=live\n"
                b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1\n"
                b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1\n"
            )
            env_path.chmod(0o600)
            recovered = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertNotIn("must-not-print", recovered.stdout + recovered.stderr)
            payload = env_path.read_text(encoding="utf-8")
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0", payload)
            self.assertIn("REDDIT_VOC_DINGTALK_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0", payload)
            self.assertIn("DINGTALK_WEBHOOK_URL=", payload)
            self.assertIn("DINGTALK_WEBHOOK_SECRET=", payload)
            quarantined = list(env_path.parent.glob("reddit-voc-report.env.quarantine-*"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].stat().st_mode & 0o777, 0o600)

    def test_recover_missing_env_installs_minimal_all_off_without_permit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-missing-env",
                "--expected-release-sha256",
                "9" * 64,
                "--candidate-sha256",
                "8" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            self.assertFalse(env_path.exists())
            recovered = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            payload = env_path.read_text(encoding="utf-8")
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0", payload)
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_terminal_kill_switch_same_id_is_idempotent_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-idempotent",
                "--expected-release-sha256",
                "a" * 64,
                "--candidate-sha256",
                "b" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            env_path.write_bytes(
                b"REDDIT_VOC_TRANSLATION_MODE=deepseek\n"
                b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n"
                b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
            )
            env_path.chmod(0o600)
            arguments = (
                "set-gates",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "kill-switch-idempotent",
                "--expected-release-sha256",
                "a" * 64,
                "--journal-id",
                "kill-journal-idempotent",
                "--translation-mode",
                "dry_run",
                "--enable-deepseek",
                "0",
                "--dingtalk-mode",
                "dry_run",
                "--enable-dingtalk-live-send",
                "0",
                "--enable-failure-alert",
                "0",
                "--terminal-kill-switch",
            )
            first = self._updater(*arguments)
            second = self._updater(*arguments)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(list((shadow / "secrets" / "snapshots").iterdir()), [])

    def test_recover_corrupt_journal_forces_all_off_and_quarantines_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-corrupt-journal",
                "--expected-release-sha256",
                "c" * 64,
                "--candidate-sha256",
                "d" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            env_path = shadow / "secrets" / "reddit-voc-report.env"
            env_path.write_bytes(
                b"REDDIT_VOC_TRANSLATION_MODE=deepseek\n"
                b"REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1\n"
                b"REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                b"REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                b"REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n"
            )
            env_path.chmod(0o600)
            corrupt = shadow / "control" / "gates" / "broken.json"
            corrupt.write_bytes(b'{"phase":"applied"')
            corrupt.chmod(0o600)

            recovered = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )

            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            payload = env_path.read_text(encoding="utf-8")
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", payload)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0", payload)
            self.assertFalse(corrupt.exists())
            quarantined = list(
                corrupt.parent.glob("broken.json.quarantine-*")
            )
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].stat().st_mode & 0o777, 0o600)
            self.assertTrue(list(corrupt.parent.glob("*.incident")))

    def test_recover_removes_orphan_snapshot_and_incident_does_not_block_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shadow, original = self._shadow_with_reserved_permit(Path(tmp))
            snapshots = shadow / "secrets" / "snapshots"
            snapshots.mkdir(mode=0o700)
            orphan = snapshots / "snapshot-orphan.env"
            orphan.write_bytes(original)
            orphan.chmod(0o600)

            first = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )
            second = self._updater(
                "recover-gates", "--shadow-root", str(shadow)
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(orphan.exists())
            self.assertEqual(
                (shadow / "secrets" / "reddit-voc-report.env").read_bytes(),
                original,
            )
            self.assertTrue(list((shadow / "control" / "gates").glob("*.incident")))

    def test_shadow_permit_install_obeys_shadow_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "shadow"
            initialized = self._admin(
                "init-shadow-root",
                "--shadow-root",
                str(shadow),
                "--authorization-id",
                "shadow-provision-lock",
                "--expected-release-sha256",
                "e" * 64,
                "--candidate-sha256",
                "f" * 64,
                "--authorize-shadow-provisioning",
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            descriptor = os.open(shadow / "lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                installed = self._admin(
                    "install-shadow-permit",
                    "--shadow-root",
                    str(shadow),
                    "--authorization-id",
                    "shadow-provider-lock",
                    "--expected-release-sha256",
                    "e" * 64,
                    "--run-id",
                    "daily_collect_20260714_0700",
                    "--copied-database-sha256",
                    "1" * 64,
                    "--max-attempts",
                    "100",
                    "--expires-at",
                    "2030-07-14T00:00:00+00:00",
                )
            finally:
                os.close(descriptor)
            self.assertNotEqual(installed.returncode, 0)
            self.assertIn("reason=lock_busy", installed.stderr)
            self.assertFalse(
                shadow.joinpath(
                    "control", "permits", "shadow-provider-lock.json"
                ).exists()
            )

    def test_admin_builds_only_the_exact_365_slot_v3_owner_permit(self) -> None:
        args = SimpleNamespace(
            authorization_id="owner-g6r5-annual-dual-policy",
            expected_release_sha256="1" * 64,
            expected_stable_entrypoint_sha256="2" * 64,
            expected_release_launcher_sha256="3" * 64,
            expected_launcher_sha256="3" * 64,
            expected_policy_sha256="4" * 64,
            expected_parent_policy_sha256=(
                report_control._G6R5_DAILY_POLICY_SHA256
            ),
            expected_credential_set_receipt_sha256="5" * 64,
            expected_credential_rotation_receipt_sha256=None,
            max_slots=365,
            credential_set_epoch_id="dual-epoch-20260811",
            destination_set_id="HighValueAssetDual",
            credential_epoch_id=None,
            destination_alias=None,
            expires_at="2027-08-21T00:30:00Z",
        )
        document = report_control._permit_document(
            args, "scheduled-cycle-policy"
        )
        self.assertEqual(
            document["schema_version"],
            "report-scheduled-cycle-policy-permit-v3",
        )
        self.assertEqual(document["max_slots"], 365)
        self.assertFalse(document["automatic_resend"])
        self.assertEqual(
            document["provider_attempt_policy"]["max_attempts_total"], 36_500
        )

        args.max_slots = 364
        with self.assertRaisesRegex(
            report_control.ReportControlError,
            "scheduled_policy_slot_cap_invalid",
        ):
            report_control._permit_document(args, "scheduled-cycle-policy")

    def test_annual_slot_cap_counts_only_the_current_policy(self) -> None:
        args = SimpleNamespace(
            expected_release_sha256="1" * 64,
            expected_launcher_sha256="2" * 64,
            run_id="daily_collect_20260822_0700",
            cycle_lease_fd=9,
            scheduled_at="2026-08-22T08:00:15+08:00",
        )
        authority = {
            "policy": {
                "expires_at_utc": "2027-08-21T00:30:00Z",
                "max_slots": 365,
            },
            "policy_sha256": "3" * 64,
            "policy_authorization_id": "owner-g6r5-annual-dual-policy",
            "report_date": "2026-08-22",
            "provider_attempt_policy": (
                report_control.canonical_g6r5_provider_attempt_policy()
            ),
        }
        old_entries = [
            {
                "event": "prepare_reserved",
                "report_date": f"2025-01-{(index % 28) + 1:02d}-{index}",
                "policy_sha256": "4" * 64,
            }
            for index in range(365)
        ]
        patches = (
            mock.patch.object(
                report_control,
                "_load_scheduled_cycle_policy",
                return_value=authority,
            ),
            mock.patch.object(
                report_control, "_recover_scheduled_cycles", return_value={}
            ),
            mock.patch.object(
                report_control,
                "_load_scheduled_cycle_ledger",
                return_value=old_entries,
            ),
            mock.patch.object(
                report_control, "_read_cycle_lease", return_value="5" * 64
            ),
            mock.patch.object(report_control, "_append_scheduled_cycle_event"),
            mock.patch.object(report_control, "_install_permit"),
            mock.patch.object(report_control, "_transition_permit"),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            reserved = report_control._reserve_scheduled_cycle(
                args, control_root=Path("/unused")
            )
        self.assertEqual(reserved["status"], "reserved")

        current_entries = [
            {
                **entry,
                "policy_sha256": authority["policy_sha256"],
            }
            for entry in old_entries
        ]
        with (
            mock.patch.object(
                report_control,
                "_load_scheduled_cycle_policy",
                return_value=authority,
            ),
            mock.patch.object(
                report_control, "_recover_scheduled_cycles", return_value={}
            ),
            mock.patch.object(
                report_control,
                "_load_scheduled_cycle_ledger",
                return_value=current_entries,
            ),
            mock.patch.object(
                report_control, "_read_cycle_lease", return_value="5" * 64
            ),
            self.assertRaisesRegex(
                report_control.ReportControlError,
                "scheduled_slot_cap_exhausted",
            ),
        ):
            report_control._reserve_scheduled_cycle(
                args, control_root=Path("/unused")
            )

    def test_admin_and_gate_updater_expose_no_unrelated_service_action(self) -> None:
        admin = ADMIN.read_text(encoding="utf-8")
        updater = (ROOT / "scripts/server_update_daily_report_runtime_env.sh").read_text(
            encoding="utf-8"
        )
        control = (ROOT / "scripts/report_control.py").read_text(encoding="utf-8")
        for forbidden in [
            "docker compose",
            "nginx -s",
            "systemctl",
            "crontab -e",
            "crontab -r",
            "crontab -u",
        ]:
            self.assertNotIn(forbidden, admin + updater + control)
        self.assertIn('["crontab", "-l"]', control)
        for command in ["set-gates", "restore-gates", "recover-gates"]:
            self.assertIn(command, updater + control)


if __name__ == "__main__":
    unittest.main()
