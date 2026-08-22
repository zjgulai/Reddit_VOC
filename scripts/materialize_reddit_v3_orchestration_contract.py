#!/usr/bin/env python3
"""Materialize one immutable local V3 candidate orchestration contract.

The profile is an explicit, reviewed run configuration.  This module only
substitutes run-scoped values, validates the resulting contract, and writes it
under the local candidate automation root.  It never invokes builders, reads
remote systems, registers a candidate, or changes production state.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import build_reddit_candidate as candidate
    from scripts import build_reddit_candidate_monitor_receipt as monitor
    from scripts import orchestrate_reddit_v3_candidate as orchestrator
except ModuleNotFoundError:  # Direct script execution.
    import build_reddit_candidate as candidate
    import build_reddit_candidate_monitor_receipt as monitor
    import orchestrate_reddit_v3_candidate as orchestrator


ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA = "reddit_voc_candidate_orchestration_profile_v1"


class OrchestrationContractMaterializationError(ValueError):
    """The profile is unsafe, incomplete, or cannot become a valid contract."""


def _canonical_file(value: object) -> bytes:
    return candidate.canonical_bytes(value) + b"\n"


def _workspace_path(value: Path, *, workspace_root: Path, label: str) -> Path:
    try:
        return orchestrator._path_inside(
            value,
            workspace_root=workspace_root,
            allowed_root=workspace_root,
            label=label,
            require_file=True,
        )
    except orchestrator.CandidateOrchestrationError as exc:
        raise OrchestrationContractMaterializationError(str(exc)) from exc


def _load_profile(path: Path, *, workspace_root: Path) -> dict[str, Any]:
    profile_path = _workspace_path(path, workspace_root=workspace_root, label="profile")
    try:
        payload = candidate._regular_bytes(profile_path, label="orchestration_profile")
        value = json.loads(payload)
    except (candidate.CandidateRegistrationError, UnicodeError, json.JSONDecodeError) as exc:
        raise OrchestrationContractMaterializationError("orchestration_profile_invalid") from exc
    required = {
        "schema_version",
        "profile_id",
        "monitor_spec_path",
        "source_freeze",
        "steps",
        "registration",
        "boundaries",
    }
    if (
        not isinstance(value, dict)
        or payload != _canonical_file(value)
        or set(value) != required
        or value.get("schema_version") != PROFILE_SCHEMA
        or not isinstance(value.get("profile_id"), str)
        or candidate.RUN_ID_RE.fullmatch(str(value.get("profile_id"))) is None
    ):
        raise OrchestrationContractMaterializationError("orchestration_profile_contract_invalid")
    return value


def _substitute(value: object, replacements: Mapping[str, str]) -> object:
    if isinstance(value, str):
        rendered = value
        for token, replacement in replacements.items():
            rendered = rendered.replace(token, replacement)
        if "${" in rendered:
            raise OrchestrationContractMaterializationError("profile_placeholder_unknown")
        return rendered
    if isinstance(value, list):
        return [_substitute(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, replacements) for key, item in value.items()}
    return value


def _terminal_marker_spec(path: Path, *, workspace_root: Path) -> None:
    monitor_path = _workspace_path(path, workspace_root=workspace_root, label="monitor_spec")
    try:
        payload = candidate._regular_bytes(monitor_path, label="monitor_spec")
        value = json.loads(payload)
    except (candidate.CandidateRegistrationError, UnicodeError, json.JSONDecodeError) as exc:
        raise OrchestrationContractMaterializationError("terminal_marker_spec_invalid") from exc
    if (
        not isinstance(value, dict)
        or payload != _canonical_file(value)
        or value.get("schema_version") != monitor.SPEC_SCHEMA_V2
        or not isinstance(value.get("terminal_marker"), dict)
    ):
        raise OrchestrationContractMaterializationError("terminal_marker_spec_required")


def materialize_orchestration_contract(
    *,
    profile_path: Path,
    run_id: str,
    observed_at_utc: str,
    source_cutoff_utc: str,
    automation_root: Path = candidate.AUTOMATION_ROOT,
    workspace_root: Path = ROOT,
) -> dict[str, Any]:
    """Create a validated run-scoped contract from an immutable local profile."""

    if candidate.RUN_ID_RE.fullmatch(run_id) is None:
        raise OrchestrationContractMaterializationError("run_id_invalid")
    try:
        candidate._require_utc(observed_at_utc, label="observed_at_utc")
    except candidate.CandidateRegistrationError as exc:
        raise OrchestrationContractMaterializationError(str(exc)) from exc
    if not isinstance(source_cutoff_utc, str) or not source_cutoff_utc:
        raise OrchestrationContractMaterializationError("source_cutoff_utc_invalid")

    workspace = Path(os.path.abspath(os.fspath(workspace_root)))
    automation = Path(os.path.abspath(os.fspath(automation_root)))
    try:
        automation = orchestrator._path_inside(
            automation,
            workspace_root=workspace,
            allowed_root=workspace,
            label="automation_root",
        )
    except orchestrator.CandidateOrchestrationError as exc:
        raise OrchestrationContractMaterializationError(str(exc)) from exc
    profile = _load_profile(Path(profile_path), workspace_root=workspace)
    _terminal_marker_spec(Path(str(profile["monitor_spec_path"])), workspace_root=workspace)
    artifact_root = workspace / "tmp/reddit-voc-v3/candidate-orchestration" / run_id
    replacements = {
        "${RUN_ID}": run_id,
        "${OBSERVED_AT_UTC}": observed_at_utc,
        "${SOURCE_CUTOFF_UTC}": source_cutoff_utc,
        "${AUTOMATION_ROOT}": str(automation),
        "${ARTIFACT_ROOT}": str(artifact_root),
    }
    rendered = _substitute(profile, replacements)
    if not isinstance(rendered, dict):  # Defensive; profile is an object above.
        raise OrchestrationContractMaterializationError("orchestration_profile_contract_invalid")
    contract = {
        "schema_version": orchestrator.CONTRACT_SCHEMA,
        "run_id": run_id,
        "observed_at_utc": observed_at_utc,
        "monitor_spec_path": rendered["monitor_spec_path"],
        "source_freeze": rendered["source_freeze"],
        "steps": rendered["steps"],
        "registration": rendered["registration"],
        "boundaries": rendered["boundaries"],
    }
    try:
        source = orchestrator._source_freeze_contract(contract["source_freeze"])
        steps = orchestrator._step_contracts(contract["steps"])
        registration = orchestrator._registration_contract(contract["registration"])
        if contract["boundaries"] != candidate.SAFE_BOUNDARIES:
            raise orchestrator.CandidateOrchestrationError("orchestration_boundaries_invalid")
        expected_freeze_root = automation / "source-freezes" / run_id
        if Path(str(source["output_root"])) != expected_freeze_root:
            raise orchestrator.CandidateOrchestrationError("source_freeze_root_binding_invalid")
        observed_artifact_root = orchestrator._validate_contract_paths(
            contract,
            source,
            registration,
            workspace_root=workspace,
            automation_root=automation,
            run_root=automation / "orchestration" / run_id,
        )
        if observed_artifact_root != artifact_root:
            raise orchestrator.CandidateOrchestrationError("candidate_artifact_root_binding_invalid")
    except orchestrator.CandidateOrchestrationError as exc:
        raise OrchestrationContractMaterializationError(str(exc)) from exc

    output = automation / "contracts" / f"{run_id}.json"
    status = candidate._write_immutable(output, contract, label="orchestration_contract")
    payload = candidate._regular_bytes(output, label="orchestration_contract", expected_mode=0o600)
    return {
        "schema_version": "reddit_voc_candidate_orchestration_contract_materialization_result_v1",
        "status": "passed",
        "write_status": status,
        "profile_id": profile["profile_id"],
        "contract_path": str(output.absolute()),
        "contract_sha256": sha256(payload).hexdigest(),
        "production_unchanged": True,
        "deploy": False,
        "remote_write": False,
        "schedule_change": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--source-cutoff-utc", required=True)
    parser.add_argument("--automation-root", type=Path, default=candidate.AUTOMATION_ROOT)
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = materialize_orchestration_contract(
            profile_path=args.profile,
            run_id=args.run_id,
            observed_at_utc=args.observed_at_utc,
            source_cutoff_utc=args.source_cutoff_utc,
            automation_root=args.automation_root,
            workspace_root=args.workspace_root,
        )
    except OrchestrationContractMaterializationError as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
