from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts import build_reddit_candidate as candidate
from scripts import validate_reddit_candidate_registry as validator
from tests.test_build_reddit_candidate import Fixture, NativeV3Fixture, _write


def _v3_args(fixture: Fixture, *, mixed_key: str | None = None):
    args = fixture.args(run_id="v3-run-001")
    paths = {}
    shas = {}
    for key in sorted(candidate.V3_LINEAGE_ARTIFACT_KEYS):
        policy = candidate.V3_RECEIPT_POLICIES.get(key)
        value = {
            "schema_version": (
                policy["schema_version"]
                if policy is not None
                else f"reddit_voc_fixture_{key}_v1"
            ),
            "status": policy["status"] if policy is not None else "candidate_built",
            "release_id": (
                "reddit_voc_release_mixed_a1"
                if key == mixed_key
                else "reddit_voc_release_fixture_a1"
            ),
            "source_snapshot_id": "reddit_voc_snapshot_fixture_a1",
            "candidate_release_sha256": "d" * 64,
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }
        if policy is not None and policy.get("lifecycle_required", True):
            value["promotable"] = True
            value["consumption_status"] = policy["consumption_status"]
        if key == "source_receipt":
            value["validator_summary"] = {
                "production_unchanged": True,
                "status": "passed",
            }
        if key in {"personas_manifest", "personas_receipt"}:
            if key == "personas_manifest":
                value["boundaries"] = dict(candidate.PERSONA_BOUNDARIES)
            else:
                value.pop("boundaries")
                value.update(candidate.PERSONA_BOUNDARIES)
        path = fixture.root / "v3" / f"{key}.json"
        paths[key] = path
        shas[key] = _write(path, value)
    args.v3_artifact_paths = paths
    args.expected_v3_artifact_sha256s = shas
    args.v3_release_id = "reddit_voc_release_fixture_a1"
    args.v3_source_snapshot_id = "reddit_voc_snapshot_fixture_a1"
    return args


class ValidateRedditCandidateRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def _registered(self) -> dict:
        return candidate.register_candidate(
            self.fixture.args(),
            automation_root=self.fixture.automation,
            registry_root=self.fixture.registry,
        )

    def test_validates_exact_tree_hash_identity_and_artifacts(self) -> None:
        registered = self._registered()
        summary = validator.validate_registry(self.fixture.registry)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["entry_count"], 1)
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["run_count"], 1)
        self.assertEqual(summary["candidate_ids"], [registered["candidate_id"]])

    def test_tampered_entry_and_noncanonical_bytes_fail_closed(self) -> None:
        registered = self._registered()
        entry = self.fixture.registry / "entries" / f"{registered['candidate_id']}.json"
        entry.write_bytes(entry.read_bytes() + b" ")
        os.chmod(entry, 0o600)
        with self.assertRaisesRegex(validator.RegistryValidationError, "canonical"):
            validator.validate_registry(self.fixture.registry)

    def test_symlink_mode_and_unknown_tree_member_fail_closed(self) -> None:
        registered = self._registered()
        entry = self.fixture.registry / "entries" / f"{registered['candidate_id']}.json"
        entry.chmod(0o644)
        with self.assertRaisesRegex(validator.RegistryValidationError, "mode"):
            validator.validate_registry(self.fixture.registry)
        entry.chmod(0o600)

        unknown = self.fixture.registry / "latest.json"
        unknown.write_text("{}\n", encoding="utf-8")
        unknown.chmod(0o600)
        with self.assertRaisesRegex(validator.RegistryValidationError, "tree"):
            validator.validate_registry(self.fixture.registry)
        unknown.unlink()

        target = self.fixture.root / "outside.json"
        target.write_text("{}\n", encoding="utf-8")
        linked = self.fixture.registry / "runs/linked.json"
        linked.symlink_to(target)
        with self.assertRaisesRegex(validator.RegistryValidationError, "unsafe"):
            validator.validate_registry(self.fixture.registry)

    def test_failed_run_is_allowed_without_entry_or_event(self) -> None:
        value = self.fixture._final_receipt()
        value["boundaries"]["remote_write"] = True
        from tests.test_build_reddit_candidate import _write

        self.fixture.final_receipt_sha = _write(self.fixture.final_receipt, value)
        with self.assertRaises(candidate.CandidateRegistrationError):
            candidate.register_candidate(
                self.fixture.args(run_id="failed-run"),
                automation_root=self.fixture.automation,
                registry_root=self.fixture.registry,
            )
        summary = validator.validate_registry(self.fixture.registry)
        self.assertEqual(summary["entry_count"], 0)
        self.assertEqual(summary["event_count"], 0)
        self.assertEqual(summary["failed_run_count"], 1)

    def test_artifact_hash_drift_fails_closed(self) -> None:
        self._registered()
        self.fixture.final_receipt.write_bytes(
            self.fixture.final_receipt.read_bytes() + b" "
        )
        with self.assertRaisesRegex(validator.RegistryValidationError, "artifact_sha256"):
            validator.validate_registry(self.fixture.registry)

    def test_v2_entry_binds_exact_v3_lineage_and_preserves_v1_registry(self) -> None:
        v1 = self._registered()
        v2 = candidate.register_candidate(
            _v3_args(self.fixture),
            automation_root=self.fixture.automation,
            registry_root=self.fixture.registry,
        )
        self.assertNotEqual(v1["candidate_id"], v2["candidate_id"])
        entry = json.loads(
            (
                self.fixture.registry
                / "entries"
                / f"{v2['candidate_id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            entry["schema_version"], "reddit_voc_candidate_registry_entry_v2"
        )
        self.assertEqual(
            set(entry["v3_lineage"]["artifact_sha256s"]),
            candidate.V3_LINEAGE_ARTIFACT_KEYS,
        )
        summary = validator.validate_registry(self.fixture.registry)
        self.assertEqual(summary["entry_count"], 2)

    def test_native_v3_entry_uses_exact_native_artifact_set(self) -> None:
        native = NativeV3Fixture(self.fixture.root / "native")
        registered = candidate.register_candidate(
            native.args(),
            automation_root=native.automation,
            registry_root=native.registry,
        )

        summary = validator.validate_registry(native.registry)

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["candidate_ids"], [registered["candidate_id"]])
        entry = json.loads(
            (
                native.registry
                / "entries"
                / f"{registered['candidate_id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(entry["v3_lineage"]["artifact_sha256s"]),
            candidate.V3_NATIVE_LINEAGE_ARTIFACT_KEYS,
        )
        self.assertEqual(
            set(entry["artifacts"]),
            validator.NATIVE_REGISTRY_BASE_ARTIFACT_KEYS
            | candidate.V3_NATIVE_LINEAGE_ARTIFACT_KEYS,
        )

    def test_v2_mixed_release_fails_before_registry_entry(self) -> None:
        with self.assertRaisesRegex(
            candidate.CandidateRegistrationError, "mixed_release"
        ):
            candidate.register_candidate(
                _v3_args(self.fixture, mixed_key="metrics_receipt"),
                automation_root=self.fixture.automation,
                registry_root=self.fixture.registry,
            )
        summary = validator.validate_registry(self.fixture.registry)
        self.assertEqual(summary["entry_count"], 0)
        self.assertEqual(summary["failed_run_count"], 1)

    def test_v3_nonpromotable_or_wrong_receipt_status_cannot_register(self) -> None:
        cases = (
            ("metrics_receipt", "promotable", False, "not_promotable"),
            (
                "reports_receipt",
                "status",
                "passed",
                "status_invalid",
            ),
        )
        for index, (key, field, replacement, error) in enumerate(cases):
            with self.subTest(key=key):
                args = _v3_args(self.fixture)
                args.run_id = f"v3-policy-failed-{index}"
                path = args.v3_artifact_paths[key]
                value = json.loads(path.read_text(encoding="utf-8"))
                value[field] = replacement
                args.expected_v3_artifact_sha256s[key] = _write(path, value)
                with self.assertRaisesRegex(
                    candidate.CandidateRegistrationError, error
                ):
                    candidate.register_candidate(
                        args,
                        automation_root=self.fixture.automation,
                        registry_root=self.fixture.registry,
                    )
                summary = validator.validate_registry(self.fixture.registry)
                self.assertEqual(summary["entry_count"], 0)

    def test_v3_receipt_schema_and_boundary_are_exact(self) -> None:
        args = _v3_args(self.fixture)
        args.run_id = "v3-schema-failed"
        path = args.v3_artifact_paths["export_receipt"]
        value = json.loads(path.read_text(encoding="utf-8"))
        value["schema_version"] = "reddit_voc_export_bundle_validation_receipt_v0"
        args.expected_v3_artifact_sha256s["export_receipt"] = _write(path, value)
        with self.assertRaisesRegex(candidate.CandidateRegistrationError, "schema_invalid"):
            candidate.register_candidate(
                args,
                automation_root=self.fixture.automation,
                registry_root=self.fixture.registry,
            )

        args = _v3_args(self.fixture)
        args.run_id = "v3-boundary-failed"
        path = args.v3_artifact_paths["e2e_receipt"]
        value = json.loads(path.read_text(encoding="utf-8"))
        value["boundaries"]["deploy"] = True
        args.expected_v3_artifact_sha256s["e2e_receipt"] = _write(path, value)
        with self.assertRaisesRegex(
            candidate.CandidateRegistrationError, "boundaries_invalid"
        ):
            candidate.register_candidate(
                args,
                automation_root=self.fixture.automation,
                registry_root=self.fixture.registry,
            )


if __name__ == "__main__":
    unittest.main()
