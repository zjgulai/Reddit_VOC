from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from scripts import build_reddit_candidate as candidate
from scripts import orchestrate_reddit_v3_candidate as orchestrator
from scripts import validate_reddit_candidate_registry as registry_validator
from tests.test_build_reddit_candidate import Fixture, _write


SCRIPT_BY_FAMILY = {
    "source": ("materialize_reddit_v3_source_manifest_from_freeze.py", "validate_reddit_v3_source_manifest.py"),
    "canonical": ("build_reddit_v3_canonical_snapshot.py", "validate_reddit_v3_canonical_snapshot.py"),
    "facts": ("build_reddit_v3_voc_facts.py", "validate_reddit_v3_voc_facts.py"),
    "metrics": ("build_reddit_v3_metrics.py", "validate_reddit_v3_metrics.py"),
    "integrity": ("build_reddit_v3_integrity_snapshot.py", "validate_reddit_v3_integrity_snapshot.py"),
    "personas": ("build_reddit_v3_personas_snapshot.py", "validate_reddit_v3_personas_snapshot.py"),
    "casebook": ("build_reddit_casebook_snapshot.py", "validate_reddit_casebook_snapshot.py"),
    "reports": ("build_reddit_reports_snapshot.py", "validate_reddit_reports_snapshot.py"),
    "insights": ("build_reddit_insights_snapshot.py", "validate_reddit_insights_snapshot.py"),
    "export": ("build_reddit_voc_export_bundle.py", "validate_reddit_voc_export_bundle.py"),
}


def _canonical_write(path: Path, value: object, *, mode: int = 0o600) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.write_bytes(payload)
    path.chmod(mode)
    return sha256(payload).hexdigest()


class OrchestrationFixture:
    def __init__(self, root: Path, *, monitor_status: str = "complete") -> None:
        self.base = Fixture(root / "registration")
        self.root = root
        self.source = root / "source"
        self.source.mkdir()
        _canonical_write(self.source / "reddit.json", {"posts": [{"id": "p1"}]})
        self.freeze = self.base.automation / "source-freezes/fixture-a1"
        self.monitor_state = root / "monitor-state.json"
        monitor_sha = _canonical_write(self.monitor_state, {"status": monitor_status})
        self.monitor_spec = root / "monitor-spec.json"
        _canonical_write(
            self.monitor_spec,
            {
                "schema_version": "reddit_voc_candidate_monitor_spec_v1",
                "observation_interval_seconds": 0,
                "probes": [
                    {
                        "id": "pipeline",
                        "kind": "file",
                        "target": str(self.monitor_state),
                        "expected_sha256": monitor_sha,
                        "expected_http_status": None,
                        "status_path": ["status"],
                        "terminal_values": ["complete"],
                        "timeout_seconds": None,
                    }
                ],
            },
        )
        self.release_sha = "d" * 64
        release_root = root / "release"
        release_root.mkdir(mode=0o700)
        self.release_manifest = release_root / "release-manifest.json"
        _canonical_write(
            self.release_manifest,
            {
                "schema_version": "reddit_voc_insights_site_release_v2",
                "release_sha256": self.release_sha,
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
        )
        self.dist_sums = root / "release/dist-SHA256SUMS"
        self.dist_sums.write_bytes(b"0" * 64 + b"  dist/index.html\n")
        self.dist_sums.chmod(0o600)
        self.dist_sha = sha256(self.dist_sums.read_bytes()).hexdigest()
        self.image_tar = root / "release/image.tar"
        self.image_tar.write_bytes(b"fixture-image")
        self.image_tar.chmod(0o600)
        self.transfer_tgz = root / "release/release.tgz"
        self.transfer_tgz.write_bytes(b"fixture-transfer")
        self.transfer_tgz.chmod(0o600)
        self.security_receipt = root / "release/security-receipt.json"
        _canonical_write(
            self.security_receipt,
            {
                "schema_version": "reddit_voc_insights_security_validation_receipt_v1",
                "status": "passed",
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
        )
        self.final_receipt = root / "release/candidate-ui-validation-receipt.json"
        self.step_root = root / "steps"
        self.role_schema: dict[str, str] = {}
        self.role_status: dict[str, str] = {}
        self.script_role: dict[str, str] = {}

    def _steps(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        previous = "source_freeze"
        for family in orchestrator.FAMILIES:
            scripts = SCRIPT_BY_FAMILY[family]
            for suffix, script in zip(("builder", "validator"), scripts, strict=True):
                role = f"{family}_{suffix}"
                policy = candidate.V3_RECEIPT_POLICIES.get(f"{family}_receipt")
                schema = (
                    f"reddit_voc_fixture_{role}_v1"
                    if suffix == "builder"
                    else str(policy["schema_version"])
                )
                status = (
                    "candidate_built"
                    if suffix == "builder"
                    else str(policy["status"])
                )
                self.role_schema[role] = schema
                self.role_status[role] = status
                self.script_role[script] = role
                args = (
                    ["--manifest", str(self.step_root / "source_builder.json")]
                    if role == "source_validator"
                    else ["--output", str(self.step_root / f"{role}.json")]
                )
                rows.append(
                    {
                        "role": role,
                        "script": f"scripts/{script}",
                        "args": args,
                        "output_path": str(self.step_root / f"{role}.json"),
                        "expected_schema_version": schema,
                        "expected_statuses": [status],
                        "allowed_command_statuses": (
                            ["passed"]
                            if role == "source_validator"
                            else ["created", "no_change"]
                        ),
                        "upstream_bindings": [
                            {"field_path": ["upstream_sha256"], "source": previous}
                        ],
                        "dist_sha256_path": None,
                    }
                )
                previous = role
        evidence = (
            (
                "same_dist_e2e",
                "scripts/run_insights_e2e.py",
                candidate.V3_RECEIPT_POLICIES["e2e_receipt"]["schema_version"],
            ),
            (
                "same_dist_container",
                "scripts/smoke_local_insights_container.sh",
                candidate.V3_RECEIPT_POLICIES["container_receipt"]["schema_version"],
            ),
            (
                "same_dist_export",
                "scripts/validate_insights_exports.py",
                "reddit_voc_insights_export_validation_receipt_v1",
            ),
        )
        for role, script, schema in evidence:
            self.role_schema[role] = schema
            policy_key = orchestrator.V3_RECEIPT_KEY_BY_ROLE.get(role)
            self.role_status[role] = (
                str(candidate.V3_RECEIPT_POLICIES[policy_key]["status"])
                if policy_key is not None
                else "passed"
            )
            self.script_role[Path(script).name] = role
            rows.append(
                {
                    "role": role,
                    "script": script,
                    "args": ["--output", str(self.step_root / f"{role}.json")],
                    "output_path": str(self.step_root / f"{role}.json"),
                    "expected_schema_version": schema,
                    "expected_statuses": [self.role_status[role]],
                    "allowed_command_statuses": ["created", "no_change"],
                    "upstream_bindings": [
                        {"field_path": ["upstream_sha256"], "source": previous}
                    ],
                    "dist_sha256_path": ["dist_sha256"],
                }
            )
            previous = role
        return rows

    def contract(self, run_id: str) -> Path:
        artifact_root = self.root / "tmp/reddit-voc-v3/candidate-orchestration/fixture-a1"
        self.step_root = artifact_root / "steps"
        self.final_receipt = artifact_root / "final/candidate-ui-validation-receipt.json"
        steps = self._steps()
        v3_artifacts = {}
        for family in orchestrator.FAMILIES:
            v3_artifacts[f"{family}_manifest"] = f"{family}_builder"
            v3_artifacts[f"{family}_receipt"] = f"{family}_validator"
        v3_artifacts["e2e_receipt"] = "same_dist_e2e"
        v3_artifacts["container_receipt"] = "same_dist_container"
        value = {
            "schema_version": "reddit_voc_candidate_orchestration_contract_v1",
            "run_id": run_id,
            "observed_at_utc": "2026-07-16T12:00:00Z",
            "monitor_spec_path": str(self.monitor_spec),
            "source_freeze": {
                "output_root": str(self.freeze),
                "source_cutoff_utc": "capture-complete",
                "sources": [
                    {
                        "namespace": "fixture",
                        "root": str(self.source),
                        "allowlist": ["reddit.json"],
                    }
                ],
            },
            "steps": steps,
            "registration": {
                "plan_a_root": str(self.base.plan_a),
                "plan_b_source_manifest": str(self.base.source_manifest),
                "plan_b_source_receipt": str(self.base.source_receipt),
                "build_contract": str(self.base.build_contract),
                "v3_release_id": "reddit_voc_release_fixture_a1",
                "v3_source_snapshot_id": "reddit_voc_snapshot_fixture_a1",
                "v3_artifacts": v3_artifacts,
                "finalization": {
                    "generated_at_utc": "2026-07-16T12:00:00Z",
                    "expires_at_utc": "2026-07-23T12:00:00Z",
                    "release_manifest": str(self.release_manifest),
                    "dist_sums": str(self.dist_sums),
                    "image_tar": str(self.image_tar),
                    "transfer_tgz": str(self.transfer_tgz),
                    "security_receipt": str(self.security_receipt),
                    "output": str(self.final_receipt),
                },
            },
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }
        path = self.root / f"{run_id}.json"
        _canonical_write(path, value)
        return path

    def runner(self, *, fail_role: str | None = None):
        previous_sha: str | None = None

        def run(command, **_kwargs):
            nonlocal previous_sha
            role = self.script_role[Path(command[1]).name]
            output = self.step_root / f"{role}.json"
            if role == fail_role:
                return subprocess.CompletedProcess(command, 2, b"", b"fixture failure")
            if role == "source_builder":
                previous_sha = sha256(
                    (self.freeze / "source-freeze-manifest.json").read_bytes()
                ).hexdigest()
            else:
                role_order = list(self.role_schema)
                previous_role = role_order[role_order.index(role) - 1]
                previous_sha = sha256(
                    (self.step_root / f"{previous_role}.json").read_bytes()
                ).hexdigest()
            assert previous_sha is not None
            if role == "source_validator":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps({
                        "status": "passed",
                        "manifest_sha256": previous_sha,
                        "production_unchanged": True,
                    }).encode("utf-8")
                    + b"\n",
                    b"",
                )
            value = {
                "schema_version": self.role_schema[role],
                "status": self.role_status[role],
                "release_id": "reddit_voc_release_fixture_a1",
                "source_snapshot_id": "reddit_voc_snapshot_fixture_a1",
                "candidate_release_sha256": self.release_sha,
                "upstream_sha256": previous_sha,
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            }
            receipt_key = orchestrator.V3_RECEIPT_KEY_BY_ROLE.get(role)
            if receipt_key is not None:
                policy = candidate.V3_RECEIPT_POLICIES[receipt_key]
                if policy.get("lifecycle_required", True):
                    value["promotable"] = True
                    value["consumption_status"] = policy["consumption_status"]
                if policy.get("top_level_boundaries") is True:
                    value.pop("boundaries")
                    value.update(candidate.PERSONA_BOUNDARIES)
            if role == "personas_builder":
                value["boundaries"] = dict(candidate.PERSONA_BOUNDARIES)
            if role.startswith("same_dist_"):
                value["dist_sha256"] = self.dist_sha
            payload = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.parent.chmod(0o700)
            status = "no_change" if output.exists() and output.read_bytes() == payload else "created"
            if status == "created":
                output.write_bytes(payload)
                output.chmod(0o600)
            previous_sha = sha256(payload).hexdigest()
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"status": status}, sort_keys=True).encode("utf-8") + b"\n",
                b"",
            )

        return run


class RedditCandidateOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_created_then_no_change_registers_one_candidate_under_safe_boundaries(self) -> None:
        fixture = OrchestrationFixture(self.root)
        first = orchestrator.orchestrate_candidate(
            contract_path=fixture.contract("orch-run-001"),
            automation_root=fixture.base.automation,
            registry_root=fixture.base.registry,
            runner=fixture.runner(),
            workspace_root=self.root,
        )
        second = orchestrator.orchestrate_candidate(
            contract_path=fixture.contract("orch-run-002"),
            automation_root=fixture.base.automation,
            registry_root=fixture.base.registry,
            runner=fixture.runner(),
            workspace_root=self.root,
        )

        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(first["source_freeze_status"], "created")
        self.assertEqual(second["source_freeze_status"], "no_change")
        summary = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(summary["entry_count"], 1)
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["run_count"], 2)
        self.assertEqual(summary["blocked_run_count"], 0)
        entry = json.loads(
            next((fixture.base.registry / "entries").iterdir()).read_text(encoding="utf-8")
        )
        self.assertFalse(entry["boundaries"]["deploy"])
        self.assertFalse(entry["boundaries"]["remote_write"])
        self.assertFalse(entry["boundaries"]["schedule_change"])

    def test_nonterminal_monitor_blocks_before_source_or_builder_and_writes_run_only(self) -> None:
        fixture = OrchestrationFixture(self.root, monitor_status="running")
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("builder must not run")

        result = orchestrator.orchestrate_candidate(
            contract_path=fixture.contract("orch-blocked-001"),
            automation_root=fixture.base.automation,
            registry_root=fixture.base.registry,
            runner=runner,
            workspace_root=self.root,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            result["reason_code"], "no_candidate_collection_not_quiescent"
        )
        self.assertEqual(calls, [])
        self.assertFalse(fixture.freeze.exists())
        summary = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(summary["entry_count"], 0)
        self.assertEqual(summary["blocked_run_count"], 1)
        self.assertEqual(summary["failed_run_count"], 0)

    def test_step_failure_creates_no_promotable_entry_and_registry_remains_valid(self) -> None:
        fixture = OrchestrationFixture(self.root)
        with self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError, "step_exit_nonzero:metrics_builder"
        ):
            orchestrator.orchestrate_candidate(
                contract_path=fixture.contract("orch-failed-001"),
                automation_root=fixture.base.automation,
                registry_root=fixture.base.registry,
                runner=fixture.runner(fail_role="metrics_builder"),
                workspace_root=self.root,
            )
        summary = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(summary["entry_count"], 0)
        self.assertEqual(summary["event_count"], 0)
        self.assertEqual(summary["failed_run_count"], 1)
        run = json.loads(
            (fixture.base.registry / "runs/orch-failed-001.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(run["artifact_build_performed"])
        self.assertFalse(run["boundaries"]["deploy"])
        receipt = json.loads(
            (
                fixture.base.automation
                / "orchestration/orch-failed-001/orchestration-receipt.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("source_builder", receipt["steps"])
        self.assertNotIn("metrics_builder", receipt["steps"])

    def test_same_dist_mismatch_fails_before_final_receipt_and_registry_entry(self) -> None:
        fixture = OrchestrationFixture(self.root)
        base_runner = fixture.runner()

        def mismatched(command, **kwargs):
            completed = base_runner(command, **kwargs)
            if Path(command[1]).name == "validate_insights_exports.py":
                output = Path(command[command.index("--output") + 1])
                value = json.loads(output.read_text(encoding="utf-8"))
                value["dist_sha256"] = "9" * 64
                _canonical_write(output, value)
            return completed

        with self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError, "same_dist_evidence_mismatch"
        ):
            orchestrator.orchestrate_candidate(
                contract_path=fixture.contract("orch-dist-failed-001"),
                automation_root=fixture.base.automation,
                registry_root=fixture.base.registry,
                runner=mismatched,
                workspace_root=self.root,
            )
        summary = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(summary["entry_count"], 0)
        self.assertEqual(summary["failed_run_count"], 1)

    def test_role_script_map_rejects_cross_role_promotion_and_permit_scripts(self) -> None:
        artifact_root = self.root / "tmp/reddit-voc-v3/candidate-orchestration/fixture-a1"
        output = artifact_root / "steps/source_builder.json"
        substitutions: dict[str, str] = {}
        for script in (
            "scripts/build_reddit_v3_metrics.py",
            "scripts/build_reddit_promotion_packet.py",
            "scripts/build_reddit_promotion_permit.py",
            "scripts/validate_reddit_promotion_permit.py",
        ):
            with self.subTest(script=script), self.assertRaisesRegex(
                orchestrator.CandidateOrchestrationError,
                "step_script_role_mismatch:source_builder",
            ):
                orchestrator._script_command(
                    "source_builder",
                    script,
                    ["--output", str(output)],
                    substitutions,
                    output_path=output,
                    workspace_root=self.root,
                    artifact_root=artifact_root,
                )
        self.assertNotIn(
            "build_reddit_promotion_permit.py",
            set(orchestrator.ROLE_SCRIPT_MAP.values()),
        )

    def test_runner_executable_override_is_denied_even_inside_workspace(self) -> None:
        artifact_root = self.root / "tmp/reddit-voc-v3/candidate-orchestration/fixture-a1"
        output = artifact_root / "steps/same_dist_e2e.json"
        executable = self.root / "scripts/fake-runner"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        with self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "step_option_denied:--runner-executable",
        ):
            orchestrator._script_command(
                "same_dist_e2e",
                "scripts/run_insights_e2e.py",
                [
                    "--runner-executable",
                    str(executable),
                    "--output",
                    str(output),
                ],
                {},
                output_path=output,
                workspace_root=self.root,
                artifact_root=artifact_root,
            )

    def test_paths_and_output_args_are_bound_to_workspace_governed_roots(self) -> None:
        fixture = OrchestrationFixture(self.root)
        contract_path = fixture.contract("orch-path-001")
        value = json.loads(contract_path.read_text(encoding="utf-8"))
        value["source_freeze"]["sources"][0]["root"] = "/private/tmp"
        _canonical_write(contract_path, value)
        with self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "source_root_0_outside_allowed_root",
        ):
            orchestrator.orchestrate_candidate(
                contract_path=contract_path,
                automation_root=fixture.base.automation,
                registry_root=fixture.base.registry,
                runner=fixture.runner(),
                workspace_root=self.root,
            )

        artifact_root = self.root / "tmp/reddit-voc-v3/candidate-orchestration/fixture-a1"
        output = artifact_root / "steps/source_builder.json"
        with self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "step_arg_outside_allowed_root",
        ):
            orchestrator._script_command(
                "source_builder",
                "scripts/materialize_reddit_v3_source_manifest_from_freeze.py",
                ["--output", "/private/tmp/reddit-voc-escape.json"],
                {},
                output_path=output,
                workspace_root=self.root,
                artifact_root=artifact_root,
            )
        with self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "step_base_url_not_local",
        ):
            orchestrator._script_command(
                "same_dist_export",
                "scripts/validate_insights_exports.py",
                [
                    "--base-url",
                    "https://reddit.example.invalid",
                    "--output-receipt",
                    str(output),
                ],
                {},
                output_path=output,
                workspace_root=self.root,
                artifact_root=artifact_root,
            )

    def test_precommit_receipt_failure_creates_no_registry_member(self) -> None:
        fixture = OrchestrationFixture(self.root)
        original = orchestrator._write_receipt

        def fail_precommit(path, **kwargs):
            if kwargs.get("status") == "prepared":
                raise orchestrator.CandidateOrchestrationError(
                    "forced_precommit_receipt_failure"
                )
            return original(path, **kwargs)

        with mock.patch.object(
            orchestrator, "_write_receipt", side_effect=fail_precommit
        ), self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "forced_precommit_receipt_failure",
        ):
            orchestrator.orchestrate_candidate(
                contract_path=fixture.contract("orch-precommit-failed-001"),
                automation_root=fixture.base.automation,
                registry_root=fixture.base.registry,
                runner=fixture.runner(),
                workspace_root=self.root,
            )
        self.assertFalse((fixture.base.registry / "entries").exists())
        self.assertFalse((fixture.base.registry / "events").exists())
        self.assertFalse((fixture.base.registry / "runs").exists())

    def test_registry_commit_interruption_is_reentrant_after_precommit(self) -> None:
        fixture = OrchestrationFixture(self.root)
        contract = fixture.contract("orch-commit-retry-001")
        original = candidate._write_immutable
        injected = False

        def fail_event_once(path, value, *, label):
            nonlocal injected
            if label == "registry_event" and not injected:
                injected = True
                raise OSError("forced registry event failure")
            return original(path, value, label=label)

        with mock.patch.object(
            candidate, "_write_immutable", side_effect=fail_event_once
        ), self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "candidate_registry_commit_incomplete",
        ):
            orchestrator.orchestrate_candidate(
                contract_path=contract,
                automation_root=fixture.base.automation,
                registry_root=fixture.base.registry,
                runner=fixture.runner(),
                workspace_root=self.root,
            )
        self.assertEqual(len(tuple((fixture.base.registry / "entries").iterdir())), 1)
        self.assertFalse((fixture.base.registry / "events").exists())
        self.assertFalse((fixture.base.registry / "runs").exists())
        pending = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(pending["entry_count"], 0)
        self.assertEqual(pending["candidate_ids"], [])
        self.assertEqual(pending["pending_transaction_count"], 1)
        precommit = json.loads(
            (
                fixture.base.automation
                / "orchestration/orch-commit-retry-001/orchestration-receipt.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(precommit["status"], "prepared")
        self.assertEqual(precommit["registry_commit_state"], "precommit_required")
        self.assertFalse(precommit["entry_written"])

        completed = orchestrator.orchestrate_candidate(
            contract_path=contract,
            automation_root=fixture.base.automation,
            registry_root=fixture.base.registry,
            runner=fixture.runner(),
            workspace_root=self.root,
        )
        self.assertEqual(completed["status"], "created")
        summary = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(summary["entry_count"], 1)
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["run_count"], 1)

    def test_commit_marker_interruption_exposes_no_consumable_candidate(self) -> None:
        fixture = OrchestrationFixture(self.root)
        contract = fixture.contract("orch-marker-retry-001")
        original = candidate._write_immutable
        injected = False

        def fail_marker_once(path, value, *, label):
            nonlocal injected
            if label == "registry_commit" and not injected:
                injected = True
                raise OSError("forced registry marker failure")
            return original(path, value, label=label)

        with mock.patch.object(
            candidate, "_write_immutable", side_effect=fail_marker_once
        ), self.assertRaisesRegex(
            orchestrator.CandidateOrchestrationError,
            "candidate_registry_commit_incomplete",
        ):
            orchestrator.orchestrate_candidate(
                contract_path=contract,
                automation_root=fixture.base.automation,
                registry_root=fixture.base.registry,
                runner=fixture.runner(),
                workspace_root=self.root,
            )

        pending = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(pending["entry_count"], 0)
        self.assertEqual(pending["event_count"], 0)
        self.assertEqual(pending["candidate_ids"], [])
        self.assertEqual(pending["pending_transaction_count"], 1)
        self.assertEqual(pending["commit_count"], 0)

        completed = orchestrator.orchestrate_candidate(
            contract_path=contract,
            automation_root=fixture.base.automation,
            registry_root=fixture.base.registry,
            runner=fixture.runner(),
            workspace_root=self.root,
        )
        self.assertEqual(completed["status"], "created")
        summary = registry_validator.validate_registry(fixture.base.registry)
        self.assertEqual(summary["entry_count"], 1)
        self.assertEqual(summary["commit_count"], 1)
        self.assertEqual(summary["pending_transaction_count"], 0)


if __name__ == "__main__":
    unittest.main()
