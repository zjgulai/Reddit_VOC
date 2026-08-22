#!/usr/bin/env python3
"""Run one fail-closed local candidate-registry automation cycle."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

try:
    from scripts import build_reddit_candidate as candidate
    from scripts import materialize_reddit_v3_orchestration_contract as materializer
    from scripts import orchestrate_reddit_v3_candidate as orchestrator
except ModuleNotFoundError:  # Direct script execution.
    import build_reddit_candidate as candidate
    import materialize_reddit_v3_orchestration_contract as materializer
    import orchestrate_reddit_v3_candidate as orchestrator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/automation/reddit-voc-candidate-registry-v1.json"
CONFIG_SCHEMA = "reddit_voc_candidate_registry_automation_config_v1"
REQUEST_SCHEMA = "reddit_voc_candidate_registry_automation_request_v1"
RECEIPT_SCHEMA = "reddit_voc_candidate_registry_automation_receipt_v1"
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
AUTOMATION_BOUNDARIES = {
    "candidate_only": True,
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "promotion": False,
    "provider_call": False,
    "remote_write": False,
    "schedule_change": False,
}


class CandidateRegistryAutomationError(ValueError):
    """The local automation configuration or request is unsafe."""


def _canonical_file(value: object) -> bytes:
    return candidate.canonical_bytes(value) + b"\n"


def _load_canonical_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = candidate._regular_bytes(path, label=label)
        value = json.loads(payload)
    except (
        candidate.CandidateRegistrationError,
        UnicodeError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        raise CandidateRegistryAutomationError(f"{label}_invalid") from exc
    if not isinstance(value, dict) or payload != _canonical_file(value):
        raise CandidateRegistryAutomationError(f"{label}_contract_invalid")
    return value, payload


def _inside(
    value: str,
    *,
    workspace_root: Path,
    allowed_root: Path,
    label: str,
    require_file: bool = False,
) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = workspace_root / path
    try:
        return orchestrator._path_inside(
            Path(os.path.abspath(os.fspath(path))),
            workspace_root=workspace_root,
            allowed_root=allowed_root,
            label=label,
            require_file=require_file,
        )
    except orchestrator.CandidateOrchestrationError as exc:
        raise CandidateRegistryAutomationError(str(exc)) from exc


def _load_config(path: Path) -> dict[str, Any]:
    value, _ = _load_canonical_object(path, label="automation_config")
    required = {
        "schema_version",
        "enabled",
        "workspace_root",
        "automation_root",
        "registry_root",
        "inbox_root",
        "receipt_root",
        "profile_root",
        "max_requests_per_cycle",
        "boundaries",
    }
    if (
        set(value) != required
        or value.get("schema_version") != CONFIG_SCHEMA
        or not isinstance(value.get("enabled"), bool)
        or value.get("max_requests_per_cycle") != 1
        or value.get("boundaries") != AUTOMATION_BOUNDARIES
    ):
        raise CandidateRegistryAutomationError("automation_config_contract_invalid")
    for key in (
        "workspace_root",
        "automation_root",
        "registry_root",
        "inbox_root",
        "receipt_root",
        "profile_root",
    ):
        if not isinstance(value.get(key), str) or not value[key]:
            raise CandidateRegistryAutomationError("automation_config_contract_invalid")
    return value


def _request(
    path: Path,
    *,
    workspace_root: Path,
    profile_root: Path,
) -> tuple[dict[str, Any], str, Path]:
    value, payload = _load_canonical_object(path, label="automation_request")
    required = {
        "schema_version",
        "request_id",
        "profile_path",
        "profile_sha256",
        "observed_at_utc",
        "source_cutoff_utc",
        "boundaries",
    }
    request_id = value.get("request_id")
    if (
        set(value) != required
        or value.get("schema_version") != REQUEST_SCHEMA
        or not isinstance(request_id, str)
        or REQUEST_ID_RE.fullmatch(request_id) is None
        or path.stem != request_id
        or not isinstance(value.get("profile_path"), str)
        or SHA256_RE.fullmatch(str(value.get("profile_sha256"))) is None
        or not isinstance(value.get("observed_at_utc"), str)
        or not isinstance(value.get("source_cutoff_utc"), str)
        or not value["source_cutoff_utc"]
        or value.get("boundaries") != AUTOMATION_BOUNDARIES
    ):
        raise CandidateRegistryAutomationError("automation_request_contract_invalid")
    try:
        candidate._require_utc(value["observed_at_utc"], label="observed_at_utc")
    except candidate.CandidateRegistrationError as exc:
        raise CandidateRegistryAutomationError(str(exc)) from exc
    profile = _inside(
        value["profile_path"],
        workspace_root=workspace_root,
        allowed_root=profile_root,
        label="automation_profile",
        require_file=True,
    )
    profile_payload = candidate._regular_bytes(profile, label="automation_profile")
    if sha256(profile_payload).hexdigest() != value["profile_sha256"]:
        raise CandidateRegistryAutomationError("automation_profile_sha256_mismatch")
    return value, sha256(payload).hexdigest(), profile


def _receipt(
    *,
    request: Mapping[str, Any],
    request_sha256: str,
    profile: Path,
    status: str,
    reason_code: str,
    materialization_result: Mapping[str, Any] | None,
    orchestration_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request_sha256,
        "profile_path": str(profile),
        "profile_sha256": request["profile_sha256"],
        "status": status,
        "reason_code": reason_code,
        "materialization_result": materialization_result,
        "orchestration_result": orchestration_result,
        "registry_automation_enabled": True,
        "boundaries": dict(AUTOMATION_BOUNDARIES),
    }


def run_cycle(
    config_path: Path = DEFAULT_CONFIG,
    *,
    materialize_fn: Callable[..., Mapping[str, Any]] = (
        materializer.materialize_orchestration_contract
    ),
    orchestrate_fn: Callable[..., Mapping[str, Any]] = orchestrator.orchestrate_candidate,
) -> dict[str, Any]:
    config = _load_config(config_path)
    workspace = Path(os.path.abspath(os.fspath(Path(config["workspace_root"]))))
    if workspace != ROOT:
        raise CandidateRegistryAutomationError("automation_workspace_root_invalid")
    automation_root = _inside(
        config["automation_root"],
        workspace_root=workspace,
        allowed_root=workspace,
        label="automation_root",
    )
    registry_root = _inside(
        config["registry_root"],
        workspace_root=workspace,
        allowed_root=workspace,
        label="registry_root",
    )
    inbox_root = _inside(
        config["inbox_root"],
        workspace_root=workspace,
        allowed_root=automation_root,
        label="automation_inbox_root",
    )
    receipt_root = _inside(
        config["receipt_root"],
        workspace_root=workspace,
        allowed_root=automation_root,
        label="automation_receipt_root",
    )
    profile_root = _inside(
        config["profile_root"],
        workspace_root=workspace,
        allowed_root=workspace,
        label="automation_profile_root",
    )
    if not config["enabled"]:
        return {
            "schema_version": RECEIPT_SCHEMA,
            "status": "disabled",
            "reason_code": "registry_automation_disabled",
            "registry_automation_enabled": False,
            "production_unchanged": True,
        }

    inbox_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    requests = [
        path
        for path in sorted(inbox_root.glob("*.json"))
        if not (receipt_root / path.name).exists()
    ]
    if not requests:
        return {
            "schema_version": RECEIPT_SCHEMA,
            "status": "idle",
            "reason_code": "no_pending_request",
            "pending_request_count": 0,
            "registry_automation_enabled": True,
            "production_unchanged": True,
        }

    request, request_sha, profile = _request(
        requests[0],
        workspace_root=workspace,
        profile_root=profile_root,
    )
    materialization_result: Mapping[str, Any] | None = None
    orchestration_result: Mapping[str, Any] | None = None
    try:
        materialization_result = materialize_fn(
            profile_path=profile,
            run_id=request["request_id"],
            observed_at_utc=request["observed_at_utc"],
            source_cutoff_utc=request["source_cutoff_utc"],
            automation_root=automation_root,
            workspace_root=workspace,
        )
        contract_path = Path(str(materialization_result["contract_path"]))
        orchestration_result = orchestrate_fn(
            contract_path=contract_path,
            automation_root=automation_root,
            registry_root=registry_root,
            workspace_root=workspace,
        )
        status = str(orchestration_result.get("status"))
        reason_code = str(
            orchestration_result.get(
                "reason_code",
                "candidate_registered" if status == "created" else "candidate_no_change",
            )
        )
        if status not in {"created", "no_change", "blocked"}:
            status = "failed"
    except candidate.CandidateBuildBusy:
        status = "blocked"
        reason_code = "candidate_build_already_running"
    except (
        CandidateRegistryAutomationError,
        materializer.OrchestrationContractMaterializationError,
        orchestrator.CandidateOrchestrationError,
        candidate.CandidateRegistrationError,
        KeyError,
        OSError,
    ) as exc:
        status = "failed"
        reason_code = candidate._reason_code(exc)

    receipt = _receipt(
        request=request,
        request_sha256=request_sha,
        profile=profile,
        status=status,
        reason_code=reason_code,
        materialization_result=materialization_result,
        orchestration_result=orchestration_result,
    )
    receipt_path = receipt_root / f"{request['request_id']}.json"
    candidate._write_immutable(receipt_path, receipt, label="automation_receipt")
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": status,
        "reason_code": reason_code,
        "request_id": request["request_id"],
        "receipt_path": str(receipt_path),
        "registry_automation_enabled": True,
        "production_unchanged": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    try:
        result = run_cycle(args.config)
    except CandidateRegistryAutomationError as exc:
        result = {
            "schema_version": RECEIPT_SCHEMA,
            "status": "failed",
            "reason_code": candidate._reason_code(exc),
            "registry_automation_enabled": False,
            "production_unchanged": True,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] in {"idle", "disabled", "created", "no_change"}:
        return 0
    if result["status"] == "blocked":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
