from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import materialize_reddit_v3_orchestration_contract as materializer
from scripts import orchestrate_reddit_v3_candidate as orchestrator
from tests.test_reddit_candidate_orchestrator import OrchestrationFixture, _canonical_write


def _replace(value: object, source: str, target: str) -> object:
    if isinstance(value, str):
        return value.replace(source, target)
    if isinstance(value, list):
        return [_replace(item, source, target) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, source, target) for key, item in value.items()}
    return value


class OrchestrationContractMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = OrchestrationFixture(self.root)
        marker = {
            "id": "completion-marker",
            "kind": "file",
            "target": str(self.fixture.monitor_state),
            "expected_sha256": None,
            "expected_http_status": None,
            "status_path": ["status"],
            "terminal_values": ["complete"],
            "timeout_seconds": None,
        }
        _canonical_write(
            self.fixture.monitor_spec,
            {
                "schema_version": "reddit_voc_candidate_monitor_spec_v2",
                "observation_interval_seconds": 0,
                "terminal_marker": marker,
                "probes": [{**marker, "id": "collector-state"}],
            },
        )
        seed = json.loads(
            self.fixture.contract("profile-seed").read_text(encoding="utf-8")
        )
        artifact_seed = str(
            self.root / "tmp/reddit-voc-v3/candidate-orchestration/fixture-a1"
        )
        profile_value = _replace(seed, artifact_seed, "${ARTIFACT_ROOT}")
        assert isinstance(profile_value, dict)
        profile_value.pop("run_id")
        profile_value.pop("observed_at_utc")
        profile_value["schema_version"] = materializer.PROFILE_SCHEMA
        profile_value["profile_id"] = "fixture-profile-a1"
        profile_value["source_freeze"]["output_root"] = (
            "${AUTOMATION_ROOT}/source-freezes/${RUN_ID}"
        )
        profile_value["source_freeze"]["source_cutoff_utc"] = "${SOURCE_CUTOFF_UTC}"
        profile_value["registration"]["finalization"]["generated_at_utc"] = (
            "${OBSERVED_AT_UTC}"
        )
        self.profile = self.root / "profile.json"
        _canonical_write(self.profile, profile_value)

    def test_materializes_valid_run_contract_idempotently(self) -> None:
        first = materializer.materialize_orchestration_contract(
            profile_path=self.profile,
            run_id="local-cycle-001",
            observed_at_utc="2026-07-18T00:00:00Z",
            source_cutoff_utc="capture-complete",
            automation_root=self.fixture.base.automation,
            workspace_root=self.root,
        )
        second = materializer.materialize_orchestration_contract(
            profile_path=self.profile,
            run_id="local-cycle-001",
            observed_at_utc="2026-07-18T00:00:00Z",
            source_cutoff_utc="capture-complete",
            automation_root=self.fixture.base.automation,
            workspace_root=self.root,
        )
        self.assertEqual(first["write_status"], "created")
        self.assertEqual(second["write_status"], "no_change")
        contract = json.loads(Path(first["contract_path"]).read_text(encoding="utf-8"))
        self.assertEqual(contract["run_id"], "local-cycle-001")
        self.assertEqual(
            contract["source_freeze"]["output_root"],
            str(self.fixture.base.automation / "source-freezes/local-cycle-001"),
        )
        self.assertEqual(
            orchestrator._step_contracts(contract["steps"])[0]["role"],
            "source_builder",
        )

    def test_rejects_unknown_placeholder_and_v1_monitor_spec(self) -> None:
        profile_value = json.loads(self.profile.read_text(encoding="utf-8"))
        profile_value["source_freeze"]["sources"][0]["root"] = "${UNKNOWN_ROOT}"
        _canonical_write(self.profile, profile_value)
        with self.assertRaisesRegex(
            materializer.OrchestrationContractMaterializationError,
            "profile_placeholder_unknown",
        ):
            materializer.materialize_orchestration_contract(
                profile_path=self.profile,
                run_id="local-cycle-002",
                observed_at_utc="2026-07-18T00:00:00Z",
                source_cutoff_utc="capture-complete",
                automation_root=self.fixture.base.automation,
                workspace_root=self.root,
            )

        profile_value["source_freeze"]["sources"][0]["root"] = str(self.fixture.source)
        _canonical_write(self.profile, profile_value)
        _canonical_write(
            self.fixture.monitor_spec,
            {
                "schema_version": "reddit_voc_candidate_monitor_spec_v1",
                "observation_interval_seconds": 0,
                "probes": [],
            },
        )
        with self.assertRaisesRegex(
            materializer.OrchestrationContractMaterializationError,
            "terminal_marker_spec_required",
        ):
            materializer.materialize_orchestration_contract(
                profile_path=self.profile,
                run_id="local-cycle-002",
                observed_at_utc="2026-07-18T00:00:00Z",
                source_cutoff_utc="capture-complete",
                automation_root=self.fixture.base.automation,
                workspace_root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
