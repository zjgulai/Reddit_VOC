from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from scripts import run_reddit_candidate_registry_automation as automation


def _write(path: Path, value: object) -> bytes:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


class CandidateRegistryAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.original_root = automation.ROOT
        self.root = Path(temporary.name)
        automation.ROOT = self.root
        self.addCleanup(setattr, automation, "ROOT", self.original_root)
        self.config = self.root / "config.json"
        self.automation_root = self.root / "tmp/reddit-voc-candidate-automation"
        self.registry_root = self.root / "output/reddit-voc-candidate-registry"
        self.profile_root = self.root / "config/candidate-automation/profiles"
        self.config_value = {
            "schema_version": automation.CONFIG_SCHEMA,
            "enabled": True,
            "workspace_root": str(self.root),
            "automation_root": str(self.automation_root),
            "registry_root": str(self.registry_root),
            "inbox_root": str(self.automation_root / "inbox"),
            "receipt_root": str(self.automation_root / "schedule-receipts"),
            "profile_root": str(self.profile_root),
            "max_requests_per_cycle": 1,
            "boundaries": dict(automation.AUTOMATION_BOUNDARIES),
        }
        _write(self.config, self.config_value)

    def test_enabled_empty_inbox_is_safe_idle(self) -> None:
        result = automation.run_cycle(self.config)

        self.assertEqual(result["status"], "idle")
        self.assertTrue(result["registry_automation_enabled"])
        self.assertTrue(result["production_unchanged"])
        self.assertFalse(self.registry_root.exists())

    def test_exact_request_materializes_and_orchestrates_once(self) -> None:
        profile = self.profile_root / "reviewed-profile.json"
        profile_payload = _write(profile, {"reviewed": True})
        request_id = "incremental-20260727-001"
        _write(
            self.automation_root / "inbox" / f"{request_id}.json",
            {
                "schema_version": automation.REQUEST_SCHEMA,
                "request_id": request_id,
                "profile_path": str(profile),
                "profile_sha256": sha256(profile_payload).hexdigest(),
                "observed_at_utc": "2026-07-27T12:00:00Z",
                "source_cutoff_utc": "capture-complete",
                "boundaries": dict(automation.AUTOMATION_BOUNDARIES),
            },
        )
        contract = self.automation_root / "contracts" / f"{request_id}.json"

        def materialize(**_kwargs):
            payload = _write(contract, {"run_id": request_id})
            return {
                "status": "passed",
                "contract_path": str(contract),
                "contract_sha256": sha256(payload).hexdigest(),
            }

        orchestrate = Mock(
            return_value={
                "status": "created",
                "reason_code": "candidate_registered",
                "production_unchanged": True,
                "deploy": False,
                "remote_write": False,
            }
        )
        first = automation.run_cycle(
            self.config,
            materialize_fn=materialize,
            orchestrate_fn=orchestrate,
        )
        second = automation.run_cycle(
            self.config,
            materialize_fn=Mock(side_effect=AssertionError("must not rerun")),
            orchestrate_fn=Mock(side_effect=AssertionError("must not rerun")),
        )

        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "idle")
        orchestrate.assert_called_once()
        receipt = json.loads(Path(first["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["request_sha256"], sha256(
            (self.automation_root / "inbox" / f"{request_id}.json").read_bytes()
        ).hexdigest())
        self.assertEqual(receipt["boundaries"], automation.AUTOMATION_BOUNDARIES)
        self.assertFalse(receipt["orchestration_result"]["deploy"])

    def test_profile_sha_drift_and_boundary_tamper_fail_closed(self) -> None:
        profile = self.profile_root / "reviewed-profile.json"
        _write(profile, {"reviewed": True})
        request_id = "incremental-20260727-002"
        request_path = self.automation_root / "inbox" / f"{request_id}.json"
        request = {
            "schema_version": automation.REQUEST_SCHEMA,
            "request_id": request_id,
            "profile_path": str(profile),
            "profile_sha256": "0" * 64,
            "observed_at_utc": "2026-07-27T12:00:00Z",
            "source_cutoff_utc": "capture-complete",
            "boundaries": dict(automation.AUTOMATION_BOUNDARIES),
        }
        _write(request_path, request)
        with self.assertRaisesRegex(
            automation.CandidateRegistryAutomationError,
            "automation_profile_sha256_mismatch",
        ):
            automation.run_cycle(self.config)

        request["profile_sha256"] = sha256(profile.read_bytes()).hexdigest()
        request["boundaries"]["remote_write"] = True
        _write(request_path, request)
        with self.assertRaisesRegex(
            automation.CandidateRegistryAutomationError,
            "automation_request_contract_invalid",
        ):
            automation.run_cycle(self.config)

    def test_config_boundary_tamper_is_rejected_before_inbox_access(self) -> None:
        self.config_value["boundaries"]["promotion"] = True
        _write(self.config, self.config_value)

        with self.assertRaisesRegex(
            automation.CandidateRegistryAutomationError,
            "automation_config_contract_invalid",
        ):
            automation.run_cycle(self.config)


if __name__ == "__main__":
    unittest.main()
