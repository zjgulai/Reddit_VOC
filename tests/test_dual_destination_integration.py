from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import report_control


class DualDestinationIntegrationTests(unittest.TestCase):
    def test_v2_authority_documents_are_canonical_and_v1_bytes_stay_frozen(self) -> None:
        v1 = report_control.build_g6r1_scheduled_cycle_policy(
            policy_id="p",
            authorization_id="a",
            parent_policy_sha256="1" * 64,
            release_sha256="2" * 64,
            stable_entrypoint_sha256="3" * 64,
            release_launcher_sha256="4" * 64,
            credential_epoch_id="e",
            destination_alias="HighValueAsset",
            credential_rotation_receipt_sha256="5" * 64,
        )
        self.assertEqual(
            hashlib.sha256(
                report_control.canonical_g6r1_json_bytes(v1)
            ).hexdigest(),
            "9188fbaabc8a4ad7e7d06c3ca9c6c0eb3995738734ae4312092a4676347bdd82",
        )

        env_receipt = report_control.build_g6r1_dual_report_env_install_receipt(
            device_id=1,
            inode_id=2,
            owner_uid=1000,
            owner_gid=1000,
            credential_set_epoch_id="dual-epoch-20260811",
            destination_set_id="HighValueAssetDual",
            authority_event_id="dual-env-installed",
        )
        report_control.validate_g6r1_dual_report_env_install_receipt(env_receipt)
        env_sha = hashlib.sha256(
            report_control.canonical_g6r1_json_bytes(env_receipt)
        ).hexdigest()
        credential_receipt = (
            report_control.build_g6r1_dual_credential_set_receipt(
                installed_at_utc="2026-08-11T12:00:00Z",
                credential_set_epoch_id="dual-epoch-20260811",
                destination_set_id="HighValueAssetDual",
                authority_event_id="dual-credentials-installed",
                report_env_install_receipt_sha256=env_sha,
            )
        )
        report_control.validate_g6r1_dual_credential_set_receipt(
            credential_receipt
        )
        policy = report_control.build_g6r1_scheduled_cycle_policy_v2(
            policy_id="g6r1-dual-20260812-20260831",
            authorization_id="owner-dual-policy",
            parent_policy_sha256="1" * 64,
            release_sha256="2" * 64,
            stable_entrypoint_sha256="3" * 64,
            release_launcher_sha256="4" * 64,
            credential_set_epoch_id="dual-epoch-20260811",
            destination_set_id="HighValueAssetDual",
            credential_set_receipt_sha256="5" * 64,
        )
        report_control.validate_g6r1_scheduled_cycle_policy_v2(
            policy,
            parent_policy_sha256="1" * 64,
            release_sha256="2" * 64,
            stable_entrypoint_sha256="3" * 64,
            release_launcher_sha256="4" * 64,
        )
        self.assertEqual(
            policy["destinations"],
            [
                {
                    "destination_id": "primary",
                    "destination_alias": "HighValueAsset",
                },
                {
                    "destination_id": "secondary",
                    "destination_alias": "HighValueAssetSecondary",
                },
            ],
        )
        forbidden_fragments = (
            "access_token=",
            "dingtalk_webhook_url",
            "dingtalk_webhook_secret",
            "destination_fingerprint",
        )
        authority_bytes = report_control.canonical_g6r1_json_bytes(
            {
                "env": env_receipt,
                "credentials": credential_receipt,
                "policy": policy,
            }
        ).lower()
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment.encode("ascii"), authority_bytes)

        reordered = dict(policy)
        reordered["destinations"] = list(reversed(policy["destinations"]))
        with self.assertRaisesRegex(
            report_control.ReportControlError, "scheduled_policy_invalid"
        ):
            report_control.validate_g6r1_scheduled_cycle_policy_v2(
                reordered,
                parent_policy_sha256="1" * 64,
                release_sha256="2" * 64,
                stable_entrypoint_sha256="3" * 64,
                release_launcher_sha256="4" * 64,
            )

    def test_v3_authority_has_365_exact_bjt_slots_and_no_auto_resend(
        self,
    ) -> None:
        fixture_path = Path(__file__).resolve().parent / "fixtures" / (
            "g6r5-dual-daily-live-policy-20260822-20270821.json"
        )
        fixture_payload = fixture_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(fixture_payload).hexdigest(),
            report_control._G6R5_DAILY_POLICY_SHA256,
        )
        parent = json.loads(fixture_payload)
        report_control.validate_g6r5_parent_policy(parent)

        policy = report_control.build_g6r5_scheduled_cycle_policy_v3(
            policy_id="g6r5-dual-20260822-20270821",
            authorization_id="owner-g6r5-annual-dual-policy",
            parent_policy_sha256=report_control._G6R5_DAILY_POLICY_SHA256,
            release_sha256="1" * 64,
            stable_entrypoint_sha256="2" * 64,
            release_launcher_sha256="3" * 64,
            credential_set_epoch_id="dual-epoch-20260811",
            destination_set_id="HighValueAssetDual",
            credential_set_receipt_sha256="4" * 64,
        )
        report_control.validate_g6r5_scheduled_cycle_policy_v3(
            policy,
            parent_policy_sha256=report_control._G6R5_DAILY_POLICY_SHA256,
            release_sha256="1" * 64,
            stable_entrypoint_sha256="2" * 64,
            release_launcher_sha256="3" * 64,
        )
        slots = policy["slots"]
        self.assertEqual(len(slots), 365)
        self.assertEqual(slots[0]["report_date"], "2026-08-22")
        self.assertEqual(slots[-1]["report_date"], "2027-08-21")
        self.assertEqual(len({slot["report_date"] for slot in slots}), 365)
        self.assertEqual(len({slot["run_id"] for slot in slots}), 365)
        self.assertTrue(
            all(
                slot["provider_prepare_allowed"] is True
                and slot["send_allowed"] is True
                and slot["slot_end_at_utc"].endswith("T00:30:00Z")
                for slot in slots
            )
        )
        self.assertFalse(policy["automatic_resend"])
        self.assertEqual(
            policy["provider_attempt_policy"]["max_attempts_total"], 36_500
        )

        policy_sha = hashlib.sha256(
            report_control.canonical_g6r1_json_bytes(policy)
        ).hexdigest()
        owner = report_control.build_g6r5_owner_policy_permit_v3(
            authorization_id="owner-g6r5-annual-dual-policy",
            release_sha256="1" * 64,
            stable_entrypoint_sha256="2" * 64,
            release_launcher_sha256="3" * 64,
            policy_sha256=policy_sha,
            parent_policy_sha256=report_control._G6R5_DAILY_POLICY_SHA256,
            credential_set_receipt_sha256="4" * 64,
            credential_set_epoch_id="dual-epoch-20260811",
            destination_set_id="HighValueAssetDual",
        )
        report_control.validate_g6r5_owner_policy_permit_v3(
            owner,
            authorization_id="owner-g6r5-annual-dual-policy",
            release_sha256="1" * 64,
            stable_entrypoint_sha256="2" * 64,
            release_launcher_sha256="3" * 64,
            policy_sha256=policy_sha,
            parent_policy_sha256=report_control._G6R5_DAILY_POLICY_SHA256,
            credential_set_receipt_sha256="4" * 64,
            credential_set_epoch_id="dual-epoch-20260811",
            destination_set_id="HighValueAssetDual",
        )
        self.assertEqual(owner["expires_at"], "2027-08-21T00:30:00Z")
        self.assertFalse(owner["automatic_resend"])

        drifted = dict(policy)
        drifted["automatic_resend"] = True
        with self.assertRaisesRegex(
            report_control.ReportControlError, "scheduled_policy_invalid"
        ):
            report_control.validate_g6r5_scheduled_cycle_policy_v3(
                drifted,
                parent_policy_sha256=report_control._G6R5_DAILY_POLICY_SHA256,
                release_sha256="1" * 64,
                stable_entrypoint_sha256="2" * 64,
                release_launcher_sha256="3" * 64,
            )

    def test_v2_send_permit_materializes_both_destinations_and_records_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            control.mkdir(mode=0o700)
            state_root = root / "state"
            run_id = "daily_collect_20260812_0700"
            run_delivery_root = state_root / "delivery" / run_id
            run_delivery_root.mkdir(parents=True, mode=0o700)
            for path in (state_root, state_root / "delivery"):
                path.chmod(0o700)

            release_sha = "1" * 64
            launcher_sha = "2" * 64
            policy_sha = "3" * 64
            bundle_sha = "4" * 64
            outbox_sha = "5" * 64
            commit_request_sha = "6" * 64
            lease_token = "7" * 64
            lease_sha = hashlib.sha256(lease_token.encode("ascii")).hexdigest()
            cycle_id = "g6r1-cycle-20260812-dualfixture"
            prepare_id = "g6r1-prepare-dualfixture"
            attempt_id = "g6r1-attempt-dualfixture"
            send_id = "g6r1-send-dualfixture"
            version_id = "20260812T000100000000Z-" + "8" * 32
            event_values = {
                "control_root": control,
                "cycle_id": cycle_id,
                "report_date": "2026-08-12",
                "run_id": run_id,
                "release_sha256": release_sha,
                "launcher_sha256": launcher_sha,
                "policy_sha256": policy_sha,
                "policy_authorization_id": "owner-dual-policy",
                "prepare_authorization_id": prepare_id,
                "cycle_lease_sha256": lease_sha,
            }
            reserved = report_control._append_scheduled_cycle_event(
                **event_values, event="prepare_reserved"
            )
            receipt = report_control._write_scheduled_commit_receipt(
                control_root=control,
                prepare_permit={"cycle_id": cycle_id},
                latest=reserved,
                attempt_id=attempt_id,
                artifact_version_id=version_id,
                bundle_sha256=bundle_sha,
                outbox_sha256=outbox_sha,
                commit_request_sha256=commit_request_sha,
                provider_authorization_id=None,
            )
            report_control._append_scheduled_cycle_event(
                **event_values,
                event="prepare_committed",
                prepare_attempt_id=attempt_id,
                artifact_version_id=version_id,
                bundle_sha256=bundle_sha,
                outbox_sha256=outbox_sha,
                commit_request_sha256=commit_request_sha,
                commit_receipt_sha256=str(receipt["commit_receipt_sha256"]),
            )
            report_control._append_scheduled_cycle_event(
                **event_values,
                event="send_permit_derived",
                prepare_attempt_id=attempt_id,
                send_authorization_id=send_id,
                artifact_version_id=version_id,
                bundle_sha256=bundle_sha,
                outbox_sha256=outbox_sha,
                commit_request_sha256=commit_request_sha,
                commit_receipt_sha256=str(receipt["commit_receipt_sha256"]),
            )
            permit = {
                "schema_version": "report-scheduled-cycle-send-permit-v2",
                "authorization_id": send_id,
                "release_sha256": release_sha,
                "expires_at": "2026-08-12T00:30:00Z",
                "run_id": run_id,
                "action": "initial",
                "artifact_version_id": version_id,
                "bundle_sha256": bundle_sha,
                "outbox_sha256": outbox_sha,
                "commit_request_sha256": commit_request_sha,
                "commit_receipt_sha256": receipt["commit_receipt_sha256"],
                "resend_part_indexes": [],
                "cycle_id": cycle_id,
                "report_date": "2026-08-12",
                "policy_sha256": policy_sha,
                "policy_authorization_id": "owner-dual-policy",
                "launcher_sha256": launcher_sha,
                "prepare_authorization_id": prepare_id,
                "prepare_attempt_id": attempt_id,
                "credential_set_epoch_id": "dual-epoch-20260811",
                "destination_set_id": "HighValueAssetDual",
                "destinations": report_control.canonical_g6r1_dual_destinations(),
                "delivery_plan": report_control.canonical_g6r1_dual_delivery_plan(),
                "required_keyword": "LL",
                "automatic_resend": False,
                "cycle_lease_sha256": lease_sha,
            }
            report_control._install_permit(root=control, document=permit)
            with mock.patch.object(
                report_control, "_expiry_is_future", return_value=True
            ):
                report_control._transition_permit(
                    root=control,
                    authorization_id=send_id,
                    expected_release_sha256=release_sha,
                    expected_run_id=run_id,
                    target_status="reserved",
                )

            env_path = root / "report.env"
            primary_url = "https://oapi.dingtalk.com/robot/send?access_token=primary"
            secondary_url = "https://oapi.dingtalk.com/robot/send?access_token=secondary"
            database_root = root / "database"
            database_root.mkdir(mode=0o700)
            public = root / "public"
            private = root / "private"
            for path in (public, private):
                path.mkdir(mode=0o700)
            env_path.write_text(
                "\n".join(
                    (
                        f"REDDIT_VOC_DATABASE_PATH={database_root / 'reddit_voc.sqlite3'}",
                        "REDDIT_VOC_RUN_ID=base-run",
                        "REDDIT_VOC_ATTEMPT_ID=base-attempt",
                        "REDDIT_VOC_ARTIFACT_VERSION_ID=base-version",
                        f"REDDIT_VOC_REPORT_PUBLIC_ROOT={public}",
                        f"REDDIT_VOC_REPORT_PRIVATE_ROOT={private}",
                        "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT=unused",
                        "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT=unused",
                        f"REDDIT_VOC_REPORT_STATE_ROOT={state_root}",
                        "REDDIT_VOC_REPORT_BLOCKED_ROOT=unused",
                        "REDDIT_VOC_REPORT_HANDOFF_ROOT=unused",
                        "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=unused",
                        "REDDIT_VOC_CONFIG_ROOT=/app/config",
                        "REDDIT_VOC_TRANSLATION_MODE=dry_run",
                        "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0",
                        "REDDIT_VOC_DINGTALK_MODE=dry_run",
                        "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0",
                        "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0",
                        "DINGTALK_REQUIRED_KEYWORD=LL",
                        "REDDIT_VOC_DINGTALK_CREDENTIAL_SET_EPOCH_ID=dual-epoch-20260811",
                        "REDDIT_VOC_DINGTALK_DESTINATION_SET_ID=HighValueAssetDual",
                        "REDDIT_VOC_DINGTALK_PRIMARY_DESTINATION_ALIAS=HighValueAsset",
                        "REDDIT_VOC_DINGTALK_SECONDARY_DESTINATION_ALIAS=HighValueAssetSecondary",
                        f"DINGTALK_WEBHOOK_URL={primary_url}",
                        "DINGTALK_WEBHOOK_SECRET=primary-signing-secret",
                        f"DINGTALK_WEBHOOK_URL_2={secondary_url}",
                        "DINGTALK_WEBHOOK_SECRET_2=secondary-signing-secret",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            env_path.chmod(0o600)
            lease_path = root / "lease"
            lease_path.write_text(lease_token, encoding="ascii")
            lease_path.chmod(0o600)
            lease_fd = os.open(lease_path, os.O_RDONLY)
            common_args = {
                "authorization_id": send_id,
                "expected_release_sha256": release_sha,
                "run_id": run_id,
                "expected_artifact_version_id": version_id,
                "expected_bundle_sha256": bundle_sha,
                "expected_outbox_sha256": outbox_sha,
                "action": "initial",
                "resend_part_index": [],
                "scheduled_cycle_id": cycle_id,
                "cycle_lease_fd": lease_fd,
                "scheduled_at": "2026-08-12T08:03:00+08:00",
            }
            try:
                materialize_args = SimpleNamespace(
                    **common_args,
                    attempt_id=send_id,
                    artifact_version_id=version_id,
                )
                with (
                    mock.patch.dict(
                        os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                    ),
                    mock.patch.object(
                        report_control, "_expiry_is_future", return_value=True
                    ),
                ):
                    original_env = env_path.read_text(encoding="utf-8")
                    missing_secondary = original_env.replace(
                        f"DINGTALK_WEBHOOK_URL_2={secondary_url}",
                        "DINGTALK_WEBHOOK_URL_2=",
                    )
                    env_path.write_text(missing_secondary, encoding="utf-8")
                    env_path.chmod(0o600)
                    with self.assertRaisesRegex(
                        report_control.ReportControlError,
                        "scheduled_destination_binding_invalid",
                    ):
                        report_control._materialize_send_env(
                            SimpleNamespace(
                                **common_args,
                                attempt_id="g6r1-send-dual-missing",
                                artifact_version_id=version_id,
                            ),
                            {
                                "control": control,
                                "env": env_path,
                                "descriptor": {
                                    "paths": {
                                        "database": str(database_root),
                                        "public": str(public),
                                        "private": str(private),
                                        "state": str(state_root),
                                    }
                                },
                            },
                        )
                    self.assertFalse(
                        control.joinpath(
                            "runtime-env", "g6r1-send-dual-missing.env"
                        ).exists()
                    )
                    env_path.write_text(
                        original_env.replace(secondary_url, primary_url),
                        encoding="utf-8",
                    )
                    env_path.chmod(0o600)
                    with self.assertRaisesRegex(
                        report_control.ReportControlError,
                        "scheduled_destination_binding_invalid",
                    ):
                        report_control._materialize_send_env(
                            SimpleNamespace(
                                **common_args,
                                attempt_id="g6r1-send-dual-duplicate",
                                artifact_version_id=version_id,
                            ),
                            {
                                "control": control,
                                "env": env_path,
                                "descriptor": {
                                    "paths": {
                                        "database": str(database_root),
                                        "public": str(public),
                                        "private": str(private),
                                        "state": str(state_root),
                                    }
                                },
                            },
                        )
                    env_path.write_text(original_env, encoding="utf-8")
                    env_path.chmod(0o600)
                    result = report_control._materialize_send_env(
                        materialize_args,
                        {
                            "control": control,
                            "env": env_path,
                            "descriptor": {
                                "paths": {
                                    "database": str(database_root),
                                    "public": str(public),
                                    "private": str(private),
                                    "state": str(state_root),
                                }
                            },
                        },
                    )
                    self.assertEqual(result["destination_mode"], "dual")
                    runtime_env = Path(str(result["runtime_env"])).read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(primary_url, runtime_env)
                    self.assertIn(secondary_url, runtime_env)

                    terminal_args = SimpleNamespace(
                        **common_args,
                        terminal_status="partial",
                        delivery_status="partially_sent",
                        primary_delivery_status="sent",
                        secondary_delivery_status="rejected",
                        primary_ledger_tip="9" * 64,
                        secondary_ledger_tip="a" * 64,
                    )
                    self.assertEqual(
                        report_control._terminalize_send_permit(
                            terminal_args, control_root=control
                        ),
                        "partial",
                    )
            finally:
                os.close(lease_fd)

            state = json.loads(
                control.joinpath("permit-state", f"{send_id}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["status"], "partial")
            self.assertEqual(
                [
                    item["destination_id"]
                    for item in state["terminal_evidence"]["destinations"]
                ],
                ["primary", "secondary"],
            )
            ledger_events = [
                json.loads(line)["event"]
                for line in control.joinpath(
                    "scheduled-cycles", "ledger.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(ledger_events[-1], "send_partial")
            audit = [
                json.loads(line)
                for line in control.joinpath(
                    "audit", "authorization.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                audit[-1]["terminal_evidence_sha256"],
                state["terminal_evidence_sha256"],
            )

    def test_v3_annual_authority_loader_closes_the_exact_activation_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            control.mkdir(mode=0o700)
            release_sha = "1" * 64
            launcher_sha = "2" * 64
            parent_path = root / "parent.json"
            parent_payload = Path(__file__).resolve().parent.joinpath(
                "fixtures",
                "g6r5-dual-daily-live-policy-20260822-20270821.json",
            ).read_bytes()
            parent = json.loads(parent_payload)
            self.assertEqual(parent, report_control.build_g6r5_parent_policy())
            parent_path.write_bytes(parent_payload)
            parent_path.chmod(0o600)
            parent_sha = hashlib.sha256(parent_payload).hexdigest()
            self.assertEqual(parent_sha, report_control._G6R5_DAILY_POLICY_SHA256)

            stable_path = root / "stable.py"
            stable_path.write_bytes(b"#!/usr/bin/python3\n# stable fixture\n")
            stable_path.chmod(0o600)
            stable_sha = hashlib.sha256(stable_path.read_bytes()).hexdigest()
            report_env_path = root / "report.env"
            report_env_path.write_bytes(b"owner-installed-opaque-fixture\n")
            report_env_path.chmod(0o600)
            metadata = report_env_path.stat()
            env_receipt = report_control.build_g6r1_dual_report_env_install_receipt(
                device_id=metadata.st_dev,
                inode_id=metadata.st_ino,
                owner_uid=metadata.st_uid,
                owner_gid=metadata.st_gid,
                credential_set_epoch_id="dual-epoch-20260811",
                destination_set_id="HighValueAssetDual",
                authority_event_id="dual-env-installed",
            )
            env_receipt_path = root / "dual-env-receipt.json"
            env_receipt_payload = report_control.canonical_g6r1_json_bytes(
                env_receipt
            )
            env_receipt_path.write_bytes(env_receipt_payload)
            env_receipt_path.chmod(0o600)
            env_receipt_sha = hashlib.sha256(env_receipt_payload).hexdigest()
            credential_receipt = (
                report_control.build_g6r1_dual_credential_set_receipt(
                    installed_at_utc="2026-08-11T12:00:00Z",
                    credential_set_epoch_id="dual-epoch-20260811",
                    destination_set_id="HighValueAssetDual",
                    authority_event_id="dual-credentials-installed",
                    report_env_install_receipt_sha256=env_receipt_sha,
                )
            )
            credential_path = root / "dual-credential-receipt.json"
            credential_payload = report_control.canonical_g6r1_json_bytes(
                credential_receipt
            )
            credential_path.write_bytes(credential_payload)
            credential_path.chmod(0o600)
            credential_sha = hashlib.sha256(credential_payload).hexdigest()
            authorization_id = "owner-g6r5-annual-dual-policy"
            policy = report_control.build_g6r5_scheduled_cycle_policy_v3(
                policy_id="g6r5-dual-20260822-20270821",
                authorization_id=authorization_id,
                parent_policy_sha256=parent_sha,
                release_sha256=release_sha,
                stable_entrypoint_sha256=stable_sha,
                release_launcher_sha256=launcher_sha,
                credential_set_epoch_id="dual-epoch-20260811",
                destination_set_id="HighValueAssetDual",
                credential_set_receipt_sha256=credential_sha,
            )
            policy_path = root / "policy.json"
            policy_payload = report_control.canonical_g6r1_json_bytes(policy)
            policy_path.write_bytes(policy_payload)
            policy_path.chmod(0o600)
            policy_sha = hashlib.sha256(policy_payload).hexdigest()
            owner_permit = report_control.build_g6r5_owner_policy_permit_v3(
                authorization_id=authorization_id,
                release_sha256=release_sha,
                stable_entrypoint_sha256=stable_sha,
                release_launcher_sha256=launcher_sha,
                policy_sha256=policy_sha,
                parent_policy_sha256=parent_sha,
                credential_set_receipt_sha256=credential_sha,
                credential_set_epoch_id="dual-epoch-20260811",
                destination_set_id="HighValueAssetDual",
            )
            owner_path = root / "owner-permit.json"
            owner_payload = report_control.canonical_g6r1_json_bytes(
                owner_permit
            )
            owner_path.write_bytes(owner_payload)
            owner_path.chmod(0o600)
            owner_sha = hashlib.sha256(owner_payload).hexdigest()

            transaction_id = "g6r5-dual-transaction"
            transactions = root / "transactions"
            transaction = transactions / transaction_id
            transaction.mkdir(parents=True, mode=0o700)
            transactions.chmod(0o700)
            journal_base = {
                "schema_version": "reddit-voc-g6r1-transaction-journal-v1",
                "transaction_id": transaction_id,
                "phase": "committed",
                "phase_history": [{"phase": "committed"}],
                "release_sha256": release_sha,
                "preimage_sha256": "3" * 64,
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
            cron_payload = (
                "CRON_TZ=Asia/Shanghai\n"
                "0 8 * * * ubuntu /usr/bin/env -i PATH=/usr/bin:/bin "
                "HOME=/home/ubuntu LANG=C.UTF-8 /usr/bin/python3 "
                "/opt/reddit-voc-daily-report/control/bin/"
                "g6r1_stable_launcher.py scheduled-cycle >> "
                "/opt/reddit-voc-site/logs/cron-report.log 2>&1\n"
            ).encode("utf-8")
            cron_path = root / "reddit-voc-site.cron"
            cron_path.write_bytes(cron_payload)
            cron_path.chmod(0o600)
            disposition = report_control.build_g6r1_secondary_disposition()
            disposition_payload = report_control.canonical_g6r1_json_bytes(
                disposition
            )
            disposition_path = root / "secondary-disposition.json"
            disposition_path.write_bytes(disposition_payload)
            disposition_path.chmod(0o600)
            user_crontab = root / "user-crontab.txt"
            user_crontab.write_bytes(b"")
            user_crontab.chmod(0o600)
            processes = root / "processes.txt"
            processes.write_bytes(b"python-safe-process\n")
            processes.chmod(0o600)
            marker = report_control.build_g6r1_activation_marker_v2(
                transaction_id=transaction_id,
                release_sha256=release_sha,
                stable_entrypoint_sha256=stable_sha,
                release_launcher_sha256=launcher_sha,
                child_policy_sha256=policy_sha,
                owner_permit_sha256=owner_sha,
                credential_set_receipt_sha256=credential_sha,
                report_env_install_receipt_sha256=env_receipt_sha,
                destination_set_id="HighValueAssetDual",
                secondary_disposition_sha256=hashlib.sha256(
                    disposition_payload
                ).hexdigest(),
                journal_file_sha256=hashlib.sha256(journal_payload).hexdigest(),
                primary_cron_sha256=hashlib.sha256(cron_payload).hexdigest(),
            )
            marker_path = root / "activation.json"
            marker_path.write_bytes(
                report_control.canonical_g6r1_json_bytes(marker)
            )
            marker_path.chmod(0o600)
            args = SimpleNamespace(
                parent_policy_file=parent_path,
                policy_file=policy_path,
                credential_rotation_receipt_file=root / "unused-rotation.json",
                report_env_install_receipt_file=root / "unused-env.json",
                dual_credential_set_receipt_file=credential_path,
                dual_report_env_install_receipt_file=env_receipt_path,
                report_env_file=report_env_path,
                expected_parent_policy_sha256=parent_sha,
                owner_policy_permit_file=owner_path,
                activation_marker_file=marker_path,
                transactions_root=transactions,
                primary_cron_file=cron_path,
                stable_entrypoint_file=stable_path,
                secondary_disposition_file=disposition_path,
                user_crontab_snapshot_file=user_crontab,
                process_snapshot_file=processes,
                scheduled_at="2026-08-22T08:00:15+08:00",
            )
            with mock.patch.dict(
                os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
            ):
                loaded = report_control._load_scheduled_cycle_policy(
                    args,
                    control_root=control,
                    release_sha256=release_sha,
                    launcher_sha256=launcher_sha,
                    run_id="daily_collect_20260822_0700",
                    scheduled_at="2026-08-22T08:00:15+08:00",
                )
            self.assertEqual(loaded["destination_mode"], "dual")
            self.assertEqual(
                loaded["credential_set_receipt_sha256"], credential_sha
            )
            self.assertIsNone(loaded["credential_rotation_receipt_sha256"])
            self.assertEqual(loaded["policy"]["max_slots"], 365)
            self.assertEqual(len(loaded["policy"]["slots"]), 365)
            self.assertEqual(
                loaded["policy"]["slots"][0]["report_date"], "2026-08-22"
            )
            self.assertEqual(
                loaded["policy"]["slots"][-1]["report_date"], "2027-08-21"
            )
            self.assertFalse(loaded["policy"]["automatic_resend"])

            args.expected_release_sha256 = release_sha
            args.expected_launcher_sha256 = launcher_sha
            args.run_id = "daily_collect_20260822_0700"
            args.cycle_lease_fd = 9
            with (
                mock.patch.dict(
                    os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                ),
                mock.patch.object(
                    report_control,
                    "_read_cycle_lease",
                    return_value="d" * 64,
                ),
            ):
                reserved = report_control._reserve_scheduled_cycle(
                    args, control_root=control
                )
            self.assertEqual(reserved["status"], "reserved")
            prepare_id = reserved["authorization_id"]
            prepare_permit = json.loads(
                control.joinpath("permits", f"{prepare_id}.json").read_bytes()
            )
            self.assertEqual(
                prepare_permit["provider_attempt_policy"][
                    "max_attempts_total"
                ],
                36_500,
            )
            self.assertEqual(prepare_permit["max_attempts"], 100)

            with mock.patch.dict(
                os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
            ):
                last = report_control._load_scheduled_cycle_policy(
                    args,
                    control_root=control,
                    release_sha256=release_sha,
                    launcher_sha256=launcher_sha,
                    run_id="daily_collect_20270821_0700",
                    scheduled_at="2027-08-21T08:04:59+08:00",
                )
            self.assertEqual(last["report_date"], "2027-08-21")

            with (
                mock.patch.dict(
                    os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                ),
                self.assertRaisesRegex(
                    report_control.ReportControlError,
                    "scheduled_slot_identity_mismatch",
                ),
            ):
                report_control._load_scheduled_cycle_policy(
                    args,
                    control_root=control,
                    release_sha256=release_sha,
                    launcher_sha256=launcher_sha,
                    run_id="daily_collect_20270822_0700",
                    scheduled_at="2027-08-22T08:00:15+08:00",
                )

            drifted = dict(policy)
            drifted["destinations"] = list(reversed(policy["destinations"]))
            policy_path.write_bytes(
                report_control.canonical_g6r1_json_bytes(drifted)
            )
            policy_path.chmod(0o600)
            with (
                mock.patch.dict(
                    os.environ, {"REDDIT_VOC_LOCAL_TEST_MODE": "1"}
                ),
                self.assertRaisesRegex(
                    report_control.ReportControlError,
                    "scheduled_policy_invalid",
                ),
            ):
                report_control._load_scheduled_cycle_policy(
                    args,
                    control_root=control,
                    release_sha256=release_sha,
                    launcher_sha256=launcher_sha,
                    run_id="daily_collect_20260822_0700",
                    scheduled_at="2026-08-22T08:00:15+08:00",
                )


if __name__ == "__main__":
    unittest.main()
