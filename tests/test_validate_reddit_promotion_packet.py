from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from typing import Any

from scripts import build_reddit_promotion_packet as builder
from scripts import validate_reddit_promotion_packet as validator
from tests.test_build_reddit_promotion_packet import Fixture


class ValidateRedditPromotionPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))
        self.build_result = self.fixture.build()

    def _validate(self, **overrides: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "artifact_root": self.fixture.root,
            "packet_path": self.fixture.output,
            "expected_packet_sha256": self.build_result["packet_sha256"],
            "now_utc": "2026-07-15T10:01:00Z",
        }
        values.update(overrides)
        return validator.validate_promotion_packet(**values)

    def _rewrite_packet(self, packet: dict[str, object], *, canonical: bool = True) -> str:
        payload = (
            builder.canonical_file_bytes(packet)
            if canonical
            else json.dumps(packet, indent=2).encode("utf-8") + b"\n"
        )
        self.fixture.output.write_bytes(payload)
        os.chmod(self.fixture.output, 0o600)
        return sha256(payload).hexdigest()

    def test_reopens_and_validates_exact_packet_and_all_artifacts(self) -> None:
        result = self._validate()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["artifact_count"], len(builder.ARTIFACT_KEYS))
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["consumed"])
        self.assertFalse(result["deploy"])
        self.assertFalse(result["remote_write"])

    def test_artifact_tamper_and_symlink_fail_closed(self) -> None:
        artifact = self.fixture.paths["plan_a_reconciliation"]
        artifact.write_bytes(artifact.read_bytes() + b"tamper")
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "artifact_plan_a_reconciliation_bytes_mismatch",
        ):
            self._validate()

        artifact.write_bytes(b"evidence:plan_a_reconciliation\n")
        outside = self.fixture.workspace / "outside.bin"
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        artifact.symlink_to(outside)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "artifact_plan_a_reconciliation_unsafe",
        ):
            self._validate()

    def test_execution_runtime_tamper_and_contract_downgrade_fail_closed(self) -> None:
        runtime = self.fixture.runtime_paths["remote_installer"]
        runtime.write_bytes(runtime.read_bytes() + b"# tamper\n")
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "execution_runtime_remote_installer_bytes_mismatch",
        ):
            self._validate()

        runtime.write_text(
            "#!/usr/bin/env bash\n# exact fixture runtime: remote_installer\nexit 0\n",
            encoding="utf-8",
        )
        packet = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        packet.pop("execution_runtime")
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "promotion_packet_unexpected_fields",
        ):
            self._validate(expected_packet_sha256=expected)

    def test_execution_runtime_record_path_and_packet_identity_are_bound(self) -> None:
        packet = json.loads(self.fixture.output.read_text(encoding="utf-8"))
        record = packet["execution_runtime"]["remote_rollback"]
        replacement = self.fixture.root / "runtime" / "remote_rollback_insights.sh"
        replacement.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
        record["bytes"] = replacement.stat().st_size
        record["sha256"] = sha256(replacement.read_bytes()).hexdigest()
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "packet_id_mismatch",
        ):
            self._validate(expected_packet_sha256=expected)

    def test_extra_fields_noncanonical_bytes_and_mode_are_rejected(self) -> None:
        packet = json.loads(self.fixture.output.read_text())
        packet["unexpected"] = False
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "promotion_packet_unexpected_fields",
        ):
            self._validate(expected_packet_sha256=expected)

        packet.pop("unexpected")
        expected = self._rewrite_packet(packet, canonical=False)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "promotion_packet_noncanonical",
        ):
            self._validate(expected_packet_sha256=expected)

        self._rewrite_packet(packet)
        os.chmod(self.fixture.output, 0o644)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "promotion_packet_mode_invalid",
        ):
            self._validate(expected_packet_sha256=sha256(self.fixture.output.read_bytes()).hexdigest())

    def test_packet_artifact_path_escape_and_duplicate_are_rejected(self) -> None:
        packet = json.loads(self.fixture.output.read_text())
        packet["artifacts"]["plan_a_receipt"]["path"] = "../outside.bin"
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError, "path_invalid"
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(builder.canonical_file_bytes(json.loads(
            self.fixture.output.read_text()
        )))
        packet["artifacts"]["plan_a_receipt"]["path"] = packet["artifacts"][
            "plan_a_manifest"
        ]["path"]
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError, "artifact_path_duplicate"
        ):
            self._validate(expected_packet_sha256=expected)

    def test_expired_future_and_wrong_packet_hash_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError, "packet_expired"
        ):
            self._validate(now_utc="2026-07-15T11:00:00Z")
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError, "packet_not_yet_valid"
        ):
            self._validate(now_utc="2026-07-15T09:59:59Z")
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "promotion_packet_sha256_mismatch",
        ):
            self._validate(expected_packet_sha256="0" * 64)

    def test_authorization_or_side_effect_tamper_is_rejected(self) -> None:
        packet = json.loads(self.fixture.output.read_text())
        packet["authorization"]["promotion_authorized"] = True
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "authorization_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet["authorization"]["promotion_authorized"] = False
        packet["side_effects"]["deploy"] = True
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "side_effects_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

    def test_site_and_data_cas_bindings_fail_closed_on_tamper(self) -> None:
        self.fixture.build()
        pristine = json.loads(self.fixture.output.read_text())
        packet = json.loads(json.dumps(pristine))
        packet["target"]["expected_current_data_pointer_sha256"] = "e" * 64
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "production_baseline_receipt_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["target"]["target_data_pointer_sha256"] = "e" * 64
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "release_manifest_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["target_data_release_id"] = (
            "reddit_voc_release_wrong_rollback"
        )
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["readiness_mode"] = "long_lived"
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["valid_until_utc"] = "2026-07-15T12:00:00Z"
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["production_baseline_cas"]["collector"]["container_id"] = (
            "f" * 64
        )
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "production_baseline_cas_mismatch",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["target_data_inventory_sha256"] = "9" * 64
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["target_data_file_count"] = 82
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["target_release_manifest_sha256"] = "7" * 64
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["rollback"]["target_release_sha256s_sha256"] = "8" * 64
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "rollback_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

        packet = json.loads(json.dumps(pristine))
        packet["authorization"]["allowed_actions"].remove(
            "compare_and_swap_only_insights_data_current"
        )
        expected = self._rewrite_packet(packet)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError,
            "authorization_contract_invalid",
        ):
            self._validate(expected_packet_sha256=expected)

    def test_extended_v2_packet_replays_v3_lineage_and_stays_unauthorized(self) -> None:
        output = self.fixture.root / "private/promotion-packet-v3.json"
        result = self.fixture.build(
            **self.fixture.v3_kwargs(),
            output=output,
        )
        validated = validator.validate_promotion_packet(
            artifact_root=self.fixture.root,
            packet_path=output,
            expected_packet_sha256=result["packet_sha256"],
            now_utc="2026-07-15T10:01:00Z",
        )
        self.assertEqual(
            validated["artifact_count"],
            len(builder.ARTIFACT_KEYS) + len(builder.V3_ARTIFACT_KEYS),
        )
        self.assertFalse(validated["promotion_authorized"])

        packet = json.loads(output.read_text(encoding="utf-8"))
        packet["v3_lineage"]["artifact_sha256s"]["v3_metrics_receipt"] = "0" * 64
        payload = builder.canonical_file_bytes(packet)
        output.write_bytes(payload)
        output.chmod(0o600)
        with self.assertRaisesRegex(
            validator.PromotionPacketValidationError, "artifact_binding"
        ):
            validator.validate_promotion_packet(
                artifact_root=self.fixture.root,
                packet_path=output,
                expected_packet_sha256=sha256(payload).hexdigest(),
                now_utc="2026-07-15T10:01:00Z",
            )

    def test_native_v3_packet_replays_without_legacy_plan_artifacts(self) -> None:
        output = self.fixture.root / "private/promotion-packet-v3-native.json"
        result = self.fixture.build(
            **self.fixture.v3_native_kwargs(),
            output=output,
        )
        validated = validator.validate_promotion_packet(
            artifact_root=self.fixture.root,
            packet_path=output,
            expected_packet_sha256=result["packet_sha256"],
            now_utc="2026-07-15T10:01:00Z",
        )
        self.assertEqual(validated["artifact_count"], len(builder.V3_NATIVE_ARTIFACT_KEYS))
        self.assertFalse(validated["promotion_authorized"])

if __name__ == "__main__":
    unittest.main()
