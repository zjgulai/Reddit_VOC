#!/usr/bin/env python3
"""Run the local-only Reddit VOC V3 candidate pipeline and stop at registry.

The orchestrator owns the existing singleton lock across read-only monitoring,
allowlisted local source freeze, explicit in-repository builders/validators,
same-dist evidence, final receipt construction, and append-only registration.
It has no SSH, deployment, scheduler, collector, cron, or database code path.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

try:
    from scripts import build_reddit_candidate as candidate
    from scripts.build_reddit_candidate_monitor_receipt import (
        CandidateMonitorError,
        build_monitor_receipt,
    )
    from scripts.capture_reddit_candidate_sources import (
        CandidateSourceCaptureError,
        _resolve_source_cutoff,
        capture_local_allowlist,
        materialize_source_freeze,
    )
except ModuleNotFoundError:  # Direct script execution.
    import build_reddit_candidate as candidate
    from build_reddit_candidate_monitor_receipt import (
        CandidateMonitorError,
        build_monitor_receipt,
    )
    from capture_reddit_candidate_sources import (
        CandidateSourceCaptureError,
        _resolve_source_cutoff,
        capture_local_allowlist,
        materialize_source_freeze,
    )


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SCHEMA = "reddit_voc_candidate_orchestration_contract_v1"
RECEIPT_SCHEMA = "reddit_voc_candidate_orchestration_receipt_v1"
BLOCKED_RUN_SCHEMA = "reddit_voc_candidate_orchestration_run_v1"
ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

FAMILIES = candidate.V3_MANIFEST_FAMILIES
REQUIRED_ROLES = tuple(
    role
    for family in FAMILIES
    for role in (f"{family}_builder", f"{family}_validator")
) + ("same_dist_e2e", "same_dist_container", "same_dist_export")

ROLE_SCRIPT_MAP = {
    "source_builder": "materialize_reddit_v3_source_manifest_from_freeze.py",
    "source_validator": "validate_reddit_v3_source_manifest.py",
    "canonical_builder": "build_reddit_v3_canonical_snapshot.py",
    "canonical_validator": "validate_reddit_v3_canonical_snapshot.py",
    "facts_builder": "build_reddit_v3_voc_facts.py",
    "facts_validator": "validate_reddit_v3_voc_facts.py",
    "metrics_builder": "build_reddit_v3_metrics.py",
    "metrics_validator": "validate_reddit_v3_metrics.py",
    "integrity_builder": "build_reddit_v3_integrity_snapshot.py",
    "integrity_validator": "validate_reddit_v3_integrity_snapshot.py",
    "personas_builder": "build_reddit_v3_personas_snapshot.py",
    "personas_validator": "validate_reddit_v3_personas_snapshot.py",
    "casebook_builder": "build_reddit_casebook_snapshot.py",
    "casebook_validator": "validate_reddit_casebook_snapshot.py",
    "reports_builder": "build_reddit_reports_snapshot.py",
    "reports_validator": "validate_reddit_reports_snapshot.py",
    "insights_builder": "build_reddit_insights_snapshot.py",
    "insights_validator": "validate_reddit_insights_snapshot.py",
    "export_builder": "build_reddit_voc_export_bundle.py",
    "export_validator": "validate_reddit_voc_export_bundle.py",
    "same_dist_e2e": "run_insights_e2e.py",
    "same_dist_container": "smoke_local_insights_container.sh",
    "same_dist_export": "validate_insights_exports.py",
}
if set(ROLE_SCRIPT_MAP) != set(REQUIRED_ROLES):  # import-time invariant
    raise RuntimeError("candidate orchestrator role/script map is incomplete")

DENIED_SCRIPT_TOKENS = ("deploy", "promote", "remote", "rollback", "cron", "server")
OUTPUT_PATH_OPTIONS = frozenset(
    {
        "--output",
        "--output-dir",
        "--output-receipt",
        "--output-root",
        "--receipt",
        "--receipt-path",
    }
)
EXPLICIT_PATH_OPTIONS = frozenset(
    {
        "--automation-policy",
        "--base-snapshot-dir",
        "--base-manifest",
        "--build-contract",
        "--bundle-root",
        "--callback-template",
        "--candidate-root",
        "--canonical-root",
        "--canonical-validation-receipt",
        "--cohort-config",
        "--decisions",
        "--dist-root",
        "--e2e-script",
        "--eligibility-policy",
        "--facts-dir",
        "--facts-receipt",
        "--facts-root",
        "--facts-validation-receipt",
        "--governance-casebook",
        "--governed-receipt",
        "--governed-root",
        "--governed-signals-manifest",
        "--governed-signals-validation-receipt",
        "--image-tar",
        "--import-bundle-root",
        "--import-validation-receipt",
        "--input",
        "--insights-dir",
        "--manifest",
        "--materialization-metadata",
        "--metrics-reporting",
        "--overlay-dir",
        "--persona-dictionary",
        "--personas-dir",
        "--policy",
        "--project-root",
        "--reference-manifest",
        "--reference-receipt",
        "--reference-registry-root",
        "--registry",
        "--release-dir",
        "--release-manifest",
        "--reports-dir",
        "--sample",
        "--security-receipt",
        "--snapshot-dir",
        "--source-facts-manifest",
        "--source-freeze-manifest",
        "--source-facts-validation-receipt",
        "--source-manifest",
        "--transfer-tgz",
        "--upstream-root",
        "--upstream-validation-receipt",
        "--entities-full",
        "--voc-facts",
        "--casebook-root",
    }
) | OUTPUT_PATH_OPTIONS
STDOUT_ARTIFACT_ROLES = frozenset({"source_validator"})
STATUSLESS_ARTIFACT_ROLES = frozenset({"source_builder"})
DENIED_STEP_OPTIONS = frozenset({"--runner-executable"})
V3_RECEIPT_KEY_BY_ROLE = {
    **{f"{family}_validator": f"{family}_receipt" for family in FAMILIES},
    "same_dist_e2e": "e2e_receipt",
    "same_dist_container": "container_receipt",
}


class CandidateOrchestrationError(ValueError):
    """The orchestration contract or one local step failed closed."""


def _canonical_file(value: object) -> bytes:
    return candidate.canonical_bytes(value) + b"\n"


def _absolute_path(value: object, *, base: Path, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not os.fspath(value):
        raise CandidateOrchestrationError(f"{label}_path_invalid")
    raw = Path(os.fspath(value))
    path = raw if raw.is_absolute() else base / raw
    return Path(os.path.abspath(os.fspath(path)))


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(root))) == os.fspath(root)
    except ValueError:
        return False


def _path_inside(
    value: object,
    *,
    workspace_root: Path,
    allowed_root: Path,
    label: str,
    require_file: bool = False,
    require_directory: bool = False,
) -> Path:
    workspace = _absolute_path(workspace_root, base=ROOT, label="workspace_root")
    allowed = _absolute_path(allowed_root, base=workspace, label=f"{label}_allowed_root")
    path = _absolute_path(value, base=workspace, label=label)
    if not _inside(allowed, workspace) or not _inside(path, allowed):
        raise CandidateOrchestrationError(f"{label}_outside_allowed_root")

    for current in (workspace, *[workspace / Path(*path.relative_to(workspace).parts[:index]) for index in range(1, len(path.relative_to(workspace).parts) + 1)]):
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise CandidateOrchestrationError(f"{label}_unsafe") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CandidateOrchestrationError(f"{label}_unsafe")

    if require_file:
        try:
            metadata = os.lstat(path)
        except OSError as exc:
            raise CandidateOrchestrationError(f"{label}_missing") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise CandidateOrchestrationError(f"{label}_unsafe")
    if require_directory:
        try:
            metadata = os.lstat(path)
        except OSError as exc:
            raise CandidateOrchestrationError(f"{label}_missing") from exc
        if not stat.S_ISDIR(metadata.st_mode):
            raise CandidateOrchestrationError(f"{label}_unsafe")
    return path


def _local_base_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise CandidateOrchestrationError("step_base_url_not_local")


def _validate_step_args(
    args: Sequence[str],
    *,
    output_path: Path,
    workspace_root: Path,
    artifact_root: Path,
    allow_stdout_artifact: bool,
) -> None:
    output_targets: list[Path] = []
    index = 0
    while index < len(args):
        item = args[index]
        option, separator, inline_value = item.partition("=")
        if option in DENIED_STEP_OPTIONS:
            raise CandidateOrchestrationError(f"step_option_denied:{option}")
        if option == "--base-url":
            if not separator and index + 1 >= len(args):
                raise CandidateOrchestrationError("step_args_invalid")
            value = inline_value if separator else args[index + 1]
            if not value:
                raise CandidateOrchestrationError("step_args_invalid")
            _local_base_url(value)
            index += 1 if separator else 2
            continue
        if option in EXPLICIT_PATH_OPTIONS:
            if not separator and index + 1 >= len(args):
                raise CandidateOrchestrationError("step_args_invalid")
            value = inline_value if separator else args[index + 1]
            if not value:
                raise CandidateOrchestrationError("step_args_invalid")
            allowed = artifact_root if option in OUTPUT_PATH_OPTIONS else workspace_root
            path = _path_inside(
                value,
                workspace_root=workspace_root,
                allowed_root=allowed,
                label="step_arg",
            )
            if option == "--project-root" and path != workspace_root:
                raise CandidateOrchestrationError("step_project_root_mismatch")
            if option in OUTPUT_PATH_OPTIONS:
                output_targets.append(path)
            index += 1 if separator else 2
            continue
        if option.startswith("--"):
            index += 1
            continue
        if Path(item).is_absolute():
            _path_inside(
                item,
                workspace_root=workspace_root,
                allowed_root=workspace_root,
                label="step_positional_arg",
            )
        index += 1

    if not output_targets and allow_stdout_artifact:
        return
    if not output_targets or not any(
        output_path == target or _inside(output_path, target) for target in output_targets
    ):
        raise CandidateOrchestrationError("step_output_arg_binding_invalid")


def _load_object(path: Path, *, label: str, canonical_required: bool = True) -> tuple[dict[str, Any], bytes]:
    payload = candidate._regular_bytes(Path(path), label=label)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateOrchestrationError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise CandidateOrchestrationError(f"{label}_not_object")
    if canonical_required and payload not in {candidate.canonical_bytes(value), _canonical_file(value)}:
        raise CandidateOrchestrationError(f"{label}_noncanonical")
    return value, payload


def _load_contract(path: Path) -> tuple[dict[str, Any], str]:
    value, payload = _load_object(path, label="orchestration_contract")
    if set(value) != {
        "schema_version",
        "run_id",
        "observed_at_utc",
        "monitor_spec_path",
        "source_freeze",
        "steps",
        "registration",
        "boundaries",
    }:
        raise CandidateOrchestrationError("orchestration_contract_fields_invalid")
    if value.get("schema_version") != CONTRACT_SCHEMA:
        raise CandidateOrchestrationError("orchestration_contract_schema_invalid")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or candidate.RUN_ID_RE.fullmatch(run_id) is None:
        raise CandidateOrchestrationError("run_id_invalid")
    candidate._require_utc(value.get("observed_at_utc"), label="observed_at_utc")
    if value.get("boundaries") != candidate.SAFE_BOUNDARIES:
        raise CandidateOrchestrationError("orchestration_boundaries_invalid")
    return value, sha256(payload).hexdigest()


def _source_freeze_contract(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"output_root", "source_cutoff_utc", "sources"}:
        raise CandidateOrchestrationError("source_freeze_contract_invalid")
    if not isinstance(value.get("output_root"), str) or not value["output_root"]:
        raise CandidateOrchestrationError("source_freeze_output_invalid")
    if not isinstance(value.get("source_cutoff_utc"), str) or not value["source_cutoff_utc"]:
        raise CandidateOrchestrationError("source_cutoff_invalid")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CandidateOrchestrationError("source_allowlist_empty")
    namespaces: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"namespace", "root", "allowlist"}:
            raise CandidateOrchestrationError("source_contract_invalid")
        namespace = source.get("namespace")
        allowlist = source.get("allowlist")
        if (
            not isinstance(namespace, str)
            or namespace in namespaces
            or not isinstance(source.get("root"), str)
            or not source["root"]
            or not isinstance(allowlist, list)
            or not allowlist
            or any(not isinstance(item, str) or not item for item in allowlist)
        ):
            raise CandidateOrchestrationError("source_contract_invalid")
        namespaces.add(namespace)
    return value


def _script_command(
    role: str,
    script_value: object,
    args_value: object,
    substitutions: Mapping[str, str],
    *,
    output_path: Path,
    workspace_root: Path,
    artifact_root: Path,
) -> list[str]:
    if role not in ROLE_SCRIPT_MAP:
        raise CandidateOrchestrationError("step_role_not_allowlisted")
    if not isinstance(script_value, str) or not script_value:
        raise CandidateOrchestrationError("step_script_invalid")
    relative = PurePosixPath(script_value)
    if relative.is_absolute() or relative.parts[:1] != ("scripts",) or ".." in relative.parts:
        raise CandidateOrchestrationError("step_script_outside_repository")
    raw_script = ROOT / relative.as_posix()
    if raw_script.is_symlink():
        raise CandidateOrchestrationError("step_script_unsafe")
    script = raw_script.resolve()
    scripts_root = (ROOT / "scripts").resolve()
    if script.parent != scripts_root or not script.is_file():
        raise CandidateOrchestrationError("step_script_unsafe")
    basename = script.name
    if any(token in basename for token in DENIED_SCRIPT_TOKENS):
        raise CandidateOrchestrationError("step_script_denied")
    if basename != ROLE_SCRIPT_MAP[role]:
        raise CandidateOrchestrationError(f"step_script_role_mismatch:{role}")
    if not isinstance(args_value, list) or any(not isinstance(item, str) for item in args_value):
        raise CandidateOrchestrationError("step_args_invalid")
    args: list[str] = []
    for item in args_value:
        replaced = item
        for token, replacement in substitutions.items():
            replaced = replaced.replace(token, replacement)
        if "${" in replaced or "\x00" in replaced:
            raise CandidateOrchestrationError("step_arg_placeholder_invalid")
        args.append(replaced)
    _validate_step_args(
        args,
        output_path=output_path,
        workspace_root=workspace_root,
        artifact_root=artifact_root,
        allow_stdout_artifact=role in STDOUT_ARTIFACT_ROLES,
    )
    if script.suffix == ".py":
        return [sys.executable, str(script), *args]
    return ["/bin/bash", str(script), *args]


def _field(value: object, path: Sequence[str], *, label: str) -> object:
    current = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise CandidateOrchestrationError(f"{label}_field_missing")
        current = current[key]
    return current


def _assign_field(value: dict[str, Any], path: Sequence[str], assigned: object) -> None:
    current = value
    for key in path[:-1]:
        existing = current.get(key)
        if existing is None:
            existing = {}
            current[key] = existing
        if not isinstance(existing, dict):
            raise CandidateOrchestrationError("stdout_artifact_binding_conflict")
        current = existing
    final = path[-1]
    if final in current and current[final] != assigned:
        raise CandidateOrchestrationError("stdout_artifact_binding_conflict")
    current[final] = assigned


def _step_contracts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise CandidateOrchestrationError("steps_invalid")
    required_keys = {
        "role",
        "script",
        "args",
        "output_path",
        "expected_schema_version",
        "expected_statuses",
        "allowed_command_statuses",
        "upstream_bindings",
        "dist_sha256_path",
    }
    roles: list[str] = []
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != required_keys:
            raise CandidateOrchestrationError("step_contract_invalid")
        role = raw.get("role")
        expected_statuses = raw.get("expected_statuses")
        command_statuses = raw.get("allowed_command_statuses")
        bindings = raw.get("upstream_bindings")
        dist_path = raw.get("dist_sha256_path")
        if (
            not isinstance(role, str)
            or ROLE_RE.fullmatch(role) is None
            or role in roles
            or not isinstance(raw.get("output_path"), str)
            or not raw["output_path"]
            or not isinstance(raw.get("expected_schema_version"), str)
            or not raw["expected_schema_version"]
            or not isinstance(expected_statuses, list)
            or (
                not expected_statuses
                and role not in STATUSLESS_ARTIFACT_ROLES
            )
            or any(not isinstance(item, str) or not item for item in expected_statuses)
            or not isinstance(command_statuses, list)
            or not command_statuses
            or any(not isinstance(item, str) or not item for item in command_statuses)
            or not isinstance(bindings, list)
            or not bindings
            or (
                dist_path is not None
                and (
                    not isinstance(dist_path, list)
                    or not dist_path
                    or any(not isinstance(item, str) or not item for item in dist_path)
                )
            )
        ):
            raise CandidateOrchestrationError("step_contract_invalid")
        if raw.get("script") != f"scripts/{ROLE_SCRIPT_MAP.get(role, '')}":
            raise CandidateOrchestrationError(f"step_script_role_mismatch:{role}")
        receipt_key = V3_RECEIPT_KEY_BY_ROLE.get(str(role))
        if receipt_key is not None:
            policy = candidate.V3_RECEIPT_POLICIES[receipt_key]
            if (
                raw.get("expected_schema_version") != policy["schema_version"]
                or expected_statuses != [policy["status"]]
            ):
                raise CandidateOrchestrationError(f"step_receipt_policy_mismatch:{role}")
        for binding in bindings:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"field_path", "source"}
                or not isinstance(binding.get("source"), str)
                or not binding["source"]
                or not isinstance(binding.get("field_path"), list)
                or not binding["field_path"]
                or any(not isinstance(item, str) or not item for item in binding["field_path"])
            ):
                raise CandidateOrchestrationError("step_binding_invalid")
        roles.append(role)
        normalized.append(raw)
    required_positions = []
    for role in REQUIRED_ROLES:
        if role not in roles:
            raise CandidateOrchestrationError(f"required_step_missing:{role}")
        required_positions.append(roles.index(role))
    if required_positions != sorted(required_positions) or roles[0] != "source_builder":
        raise CandidateOrchestrationError("required_step_order_invalid")
    if roles[-3:] != ["same_dist_e2e", "same_dist_container", "same_dist_export"]:
        raise CandidateOrchestrationError("same_dist_step_order_invalid")
    for family in FAMILIES:
        validator = normalized[roles.index(f"{family}_validator")]
        if f"{family}_builder" not in {item["source"] for item in validator["upstream_bindings"]}:
            raise CandidateOrchestrationError(f"validator_builder_binding_missing:{family}")
    source_builder = normalized[roles.index("source_builder")]
    source_validator = normalized[roles.index("source_validator")]
    source_builder_sources = {item["source"] for item in source_builder["upstream_bindings"]}
    source_validator_sources = {item["source"] for item in source_validator["upstream_bindings"]}
    if "source_freeze" not in source_builder_sources and not {
        "source_freeze",
        "source_builder",
    }.issubset(source_validator_sources):
        raise CandidateOrchestrationError("source_freeze_binding_missing")
    for role in ("same_dist_e2e", "same_dist_container", "same_dist_export"):
        if normalized[roles.index(role)]["dist_sha256_path"] is None:
            raise CandidateOrchestrationError(f"same_dist_field_missing:{role}")
    return normalized


def _registration_contract(value: object) -> dict[str, Any]:
    keys = {
        "plan_a_root",
        "plan_b_source_manifest",
        "plan_b_source_receipt",
        "build_contract",
        "v3_release_id",
        "v3_source_snapshot_id",
        "v3_artifacts",
        "finalization",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise CandidateOrchestrationError("registration_contract_invalid")
    for key in keys - {"v3_artifacts", "finalization"}:
        if not isinstance(value.get(key), str) or not value[key]:
            raise CandidateOrchestrationError("registration_contract_invalid")
    artifacts = value.get("v3_artifacts")
    if (
        not isinstance(artifacts, dict)
        or set(artifacts) != candidate.V3_LINEAGE_ARTIFACT_KEYS
        or any(not isinstance(role, str) or not role for role in artifacts.values())
    ):
        raise CandidateOrchestrationError("registration_v3_artifacts_invalid")
    expected_artifacts = {
        **{
            f"{family}_manifest": f"{family}_builder"
            for family in FAMILIES
        },
        **{
            f"{family}_receipt": f"{family}_validator"
            for family in FAMILIES
        },
        "e2e_receipt": "same_dist_e2e",
        "container_receipt": "same_dist_container",
    }
    if artifacts != expected_artifacts:
        raise CandidateOrchestrationError("registration_v3_artifact_role_mismatch")
    finalization = value.get("finalization")
    final_keys = {
        "generated_at_utc",
        "expires_at_utc",
        "release_manifest",
        "dist_sums",
        "image_tar",
        "transfer_tgz",
        "security_receipt",
        "output",
    }
    if (
        not isinstance(finalization, dict)
        or set(finalization) != final_keys
        or any(not isinstance(finalization.get(key), str) or not finalization[key] for key in final_keys)
    ):
        raise CandidateOrchestrationError("finalization_contract_invalid")
    candidate._require_utc(finalization["generated_at_utc"], label="generated_at_utc")
    candidate._require_utc(finalization["expires_at_utc"], label="expires_at_utc")
    return value


def _validate_contract_paths(
    contract: Mapping[str, Any],
    source_contract: Mapping[str, Any],
    registration: Mapping[str, Any],
    *,
    workspace_root: Path,
    automation_root: Path,
    run_root: Path,
) -> Path:
    _path_inside(
        contract["monitor_spec_path"],
        workspace_root=workspace_root,
        allowed_root=workspace_root,
        label="monitor_spec",
        require_file=True,
    )
    freeze_root = _path_inside(
        source_contract["output_root"],
        workspace_root=workspace_root,
        allowed_root=automation_root / "source-freezes",
        label="source_freeze_output",
    )
    if (
        freeze_root.parent != automation_root / "source-freezes"
        or candidate.RUN_ID_RE.fullmatch(freeze_root.name) is None
    ):
        raise CandidateOrchestrationError("source_freeze_root_binding_invalid")
    for index, source in enumerate(source_contract["sources"]):
        _path_inside(
            source["root"],
            workspace_root=workspace_root,
            allowed_root=workspace_root,
            label=f"source_root_{index}",
            require_directory=True,
        )

    for key in (
        "plan_a_root",
        "plan_b_source_manifest",
        "plan_b_source_receipt",
        "build_contract",
    ):
        _path_inside(
            registration[key],
            workspace_root=workspace_root,
            allowed_root=workspace_root,
            label=f"registration_{key}",
        )
    finalization = registration["finalization"]
    for key in (
        "release_manifest",
        "dist_sums",
        "image_tar",
        "transfer_tgz",
        "security_receipt",
    ):
        _path_inside(
            finalization[key],
            workspace_root=workspace_root,
            allowed_root=workspace_root,
            label=f"finalization_{key}",
        )
    # Every selected V3 builder already constrains private outputs below this
    # project-local root.  The orchestrator narrows it one level further.
    artifact_parent = workspace_root / "tmp/reddit-voc-v3/candidate-orchestration"
    governed_outputs = [
        _path_inside(
            step["output_path"],
            workspace_root=workspace_root,
            allowed_root=artifact_parent,
            label=f"step_{step['role']}_output",
        )
        for step in contract["steps"]
    ]
    governed_outputs.append(
        _path_inside(
            finalization["output"],
            workspace_root=workspace_root,
            allowed_root=artifact_parent,
            label="finalization_output",
        )
    )
    artifact_ids: set[str] = set()
    for output in governed_outputs:
        relative = output.relative_to(artifact_parent)
        if len(relative.parts) < 2 or candidate.RUN_ID_RE.fullmatch(relative.parts[0]) is None:
            raise CandidateOrchestrationError("candidate_artifact_root_binding_invalid")
        artifact_ids.add(relative.parts[0])
    if len(artifact_ids) != 1:
        raise CandidateOrchestrationError("candidate_artifact_root_mismatch")
    return artifact_parent / next(iter(artifact_ids))


def _safe_boundaries(value: object, *, label: str) -> None:
    try:
        candidate._safe_boundaries(value, label=label)
    except candidate.CandidateRegistrationError as exc:
        raise CandidateOrchestrationError(str(exc)) from exc


def _parse_command_result(payload: bytes, *, role: str) -> dict[str, Any]:
    for line in reversed([item for item in payload.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    raise CandidateOrchestrationError(f"step_stdout_result_missing:{role}")


def _sanitized_environment() -> dict[str, str]:
    return {
        "HOME": os.environ.get("HOME", str(ROOT)),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(ROOT),
    }


def _run_steps(
    steps: Sequence[Mapping[str, Any]],
    *,
    source_freeze_root: Path,
    source_freeze_sha256: str,
    run_root: Path,
    artifact_root: Path,
    workspace_root: Path,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    substitutions = {
        "${SOURCE_FREEZE_ROOT}": str(source_freeze_root.absolute()),
        "${SOURCE_FREEZE_MANIFEST}": str((source_freeze_root / "source-freeze-manifest.json").absolute()),
        "${RUN_ROOT}": str(run_root.absolute()),
        "${ARTIFACT_ROOT}": str(artifact_root.absolute()),
    }
    if results is None:
        results = {}
    for step in steps:
        role = str(step["role"])
        for binding in step["upstream_bindings"]:
            source = str(binding["source"])
            if source != "source_freeze" and source not in results:
                raise CandidateOrchestrationError(f"step_binding_not_prior:{role}:{source}")
        output = _path_inside(
            step["output_path"],
            workspace_root=workspace_root,
            allowed_root=artifact_root,
            label=f"step_{role}_output",
        )
        command = _script_command(
            role,
            step["script"],
            step["args"],
            substitutions,
            output_path=output,
            workspace_root=workspace_root,
            artifact_root=artifact_root,
        )
        completed = runner(
            command,
            cwd=ROOT,
            env=_sanitized_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=1800,
        )
        if completed.returncode != 0:
            raise CandidateOrchestrationError(f"step_exit_nonzero:{role}")
        command_result = _parse_command_result(completed.stdout, role=role)
        if command_result.get("status") not in set(step["allowed_command_statuses"]):
            raise CandidateOrchestrationError(f"step_command_status_invalid:{role}")
        if role in STDOUT_ARTIFACT_ROLES and not output.exists() and not output.is_symlink():
            receipt: dict[str, Any] = {
                "schema_version": step["expected_schema_version"],
                "status": command_result["status"],
                "consumption_status": candidate.V3_RECEIPT_POLICIES[
                    V3_RECEIPT_KEY_BY_ROLE[role]
                ]["consumption_status"],
                "promotable": True,
                "validator_summary": command_result,
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            }
            for binding in step["upstream_bindings"]:
                source = str(binding["source"])
                expected = (
                    source_freeze_sha256
                    if source == "source_freeze"
                    else str(results[source]["sha256"])
                )
                _assign_field(receipt, binding["field_path"], expected)
            candidate._write_immutable(
                output, receipt, label=f"stdout_step_{role}"
            )
        value, payload = _load_object(output, label=f"step_{role}")
        if value.get("schema_version") != step["expected_schema_version"]:
            raise CandidateOrchestrationError(f"step_schema_invalid:{role}")
        if step["expected_statuses"] and value.get("status") not in set(step["expected_statuses"]):
            raise CandidateOrchestrationError(f"step_artifact_status_invalid:{role}")
        receipt_key = V3_RECEIPT_KEY_BY_ROLE.get(role)
        if receipt_key is not None:
            try:
                candidate._validate_v3_receipt(receipt_key, value)
            except candidate.CandidateRegistrationError as exc:
                raise CandidateOrchestrationError(str(exc)) from exc
        elif role == "personas_builder":
            if value.get("boundaries") != candidate.PERSONA_BOUNDARIES:
                raise CandidateOrchestrationError("step_personas_builder_boundaries_invalid")
        else:
            _safe_boundaries(value.get("boundaries"), label=f"step_{role}")
        for binding in step["upstream_bindings"]:
            source = str(binding["source"])
            expected = (
                source_freeze_sha256
                if source == "source_freeze"
                else str(results[source]["sha256"])
            )
            observed = _field(value, binding["field_path"], label=f"step_{role}_binding")
            if observed != expected:
                raise CandidateOrchestrationError(f"step_upstream_sha_mismatch:{role}:{source}")
        digest = sha256(payload).hexdigest()
        dist_sha: str | None = None
        if step["dist_sha256_path"] is not None:
            dist_value = _field(value, step["dist_sha256_path"], label=f"step_{role}_dist")
            if not isinstance(dist_value, str) or candidate.SHA256_RE.fullmatch(dist_value) is None:
                raise CandidateOrchestrationError(f"step_dist_sha_invalid:{role}")
            dist_sha = dist_value
        results[role] = {
            "path": str(output.absolute()),
            "sha256": digest,
            "schema_version": value["schema_version"],
            "status": value.get("status"),
            "dist_sha256": dist_sha,
        }
    dist_shas = {str(results[role]["dist_sha256"]) for role in ("same_dist_e2e", "same_dist_container", "same_dist_export")}
    if len(dist_shas) != 1:
        raise CandidateOrchestrationError("same_dist_evidence_mismatch")
    return results


def _sha(path: Path, *, label: str) -> str:
    return sha256(candidate._regular_bytes(path, label=label)).hexdigest()


def _registration_args(
    contract: Mapping[str, Any],
    *,
    run_id: str,
    step_results: Mapping[str, Mapping[str, Any]],
) -> tuple[SimpleNamespace, str]:
    plan_a_root = Path(str(contract["plan_a_root"]))
    plan_a_input = plan_a_root.name
    candidate._require_sha(plan_a_input, label="expected_plan_a_input_sha256")
    plan_a_manifest = plan_a_root / "candidate-data-manifest.json"
    plan_a_receipt = plan_a_root / "candidate-data-validation-receipt.json"
    plan_b_manifest = Path(str(contract["plan_b_source_manifest"]))
    plan_b_receipt = Path(str(contract["plan_b_source_receipt"]))
    source_manifest_value, _ = _load_object(plan_b_manifest, label="plan_b_source_manifest")
    plan_b_input = source_manifest_value.get("frontend_candidate_input_sha256")
    candidate._require_sha(plan_b_input, label="expected_plan_b_input_sha256")
    build_contract = Path(str(contract["build_contract"]))
    finalization = contract["finalization"]
    release_manifest = Path(str(finalization["release_manifest"]))
    dist_sums = Path(str(finalization["dist_sums"]))
    image_tar = Path(str(finalization["image_tar"]))
    transfer_tgz = Path(str(finalization["transfer_tgz"]))
    security_receipt = Path(str(finalization["security_receipt"]))
    final_output = Path(str(finalization["output"]))
    hashes = {
        "plan_a_manifest": _sha(plan_a_manifest, label="plan_a_manifest"),
        "plan_a_receipt": _sha(plan_a_receipt, label="plan_a_receipt"),
        "plan_b_manifest": _sha(plan_b_manifest, label="plan_b_source_manifest"),
        "plan_b_receipt": _sha(plan_b_receipt, label="plan_b_source_receipt"),
        "build_contract": _sha(build_contract, label="build_contract"),
        "release_manifest": _sha(release_manifest, label="release_manifest"),
        "dist_sums": _sha(dist_sums, label="dist_sums"),
        "image_tar": _sha(image_tar, label="image_tar"),
        "transfer_tgz": _sha(transfer_tgz, label="transfer_tgz"),
        "security_receipt": _sha(security_receipt, label="security_receipt"),
    }
    final_args = SimpleNamespace(
        generated_at_utc=finalization["generated_at_utc"],
        expires_at_utc=finalization["expires_at_utc"],
        expected_plan_a_input_sha256=plan_a_input,
        expected_plan_a_manifest_sha256=hashes["plan_a_manifest"],
        expected_plan_a_receipt_sha256=hashes["plan_a_receipt"],
        expected_plan_b_input_sha256=plan_b_input,
        expected_plan_b_source_manifest_sha256=hashes["plan_b_manifest"],
        expected_plan_b_source_receipt_sha256=hashes["plan_b_receipt"],
        expected_build_contract_sha256=hashes["build_contract"],
        release_manifest=release_manifest,
        expected_release_manifest_sha256=hashes["release_manifest"],
        dist_sums=dist_sums,
        expected_dist_sums_sha256=hashes["dist_sums"],
        image_tar=image_tar,
        expected_image_tar_sha256=hashes["image_tar"],
        transfer_tgz=transfer_tgz,
        expected_transfer_tgz_sha256=hashes["transfer_tgz"],
        browser_e2e_receipt=Path(str(step_results["same_dist_e2e"]["path"])),
        expected_browser_e2e_receipt_sha256=step_results["same_dist_e2e"]["sha256"],
        export_receipt=Path(str(step_results["same_dist_export"]["path"])),
        expected_export_receipt_sha256=step_results["same_dist_export"]["sha256"],
        container_smoke_receipt=Path(str(step_results["same_dist_container"]["path"])),
        expected_container_smoke_receipt_sha256=step_results["same_dist_container"]["sha256"],
        security_receipt=security_receipt,
        expected_security_receipt_sha256=hashes["security_receipt"],
        output=final_output,
    )
    candidate.build_final_ui_receipt(final_args)
    final_sha = _sha(final_output, label="final_receipt")
    final_value, _ = _load_object(final_output, label="final_receipt")
    common_dist = step_results["same_dist_e2e"]["dist_sha256"]
    if _field(final_value, ["release", "dist_manifest_sha256"], label="final_receipt") != common_dist:
        raise CandidateOrchestrationError("final_receipt_same_dist_mismatch")
    expected_v3_paths: dict[str, Path] = {}
    expected_v3_shas: dict[str, str] = {}
    for key, role_value in contract["v3_artifacts"].items():
        role = str(role_value)
        if role not in step_results:
            raise CandidateOrchestrationError(f"registration_step_missing:{key}:{role}")
        expected_v3_paths[key] = Path(str(step_results[role]["path"]))
        expected_v3_shas[key] = str(step_results[role]["sha256"])
    registration_args = SimpleNamespace(
        run_id=run_id,
        plan_a_root=plan_a_root,
        expected_plan_a_input_sha256=plan_a_input,
        expected_plan_a_manifest_sha256=hashes["plan_a_manifest"],
        expected_plan_a_receipt_sha256=hashes["plan_a_receipt"],
        plan_b_source_manifest=plan_b_manifest,
        expected_plan_b_source_manifest_sha256=hashes["plan_b_manifest"],
        plan_b_source_receipt=plan_b_receipt,
        expected_plan_b_source_receipt_sha256=hashes["plan_b_receipt"],
        expected_plan_b_input_sha256=plan_b_input,
        build_contract=build_contract,
        expected_build_contract_sha256=hashes["build_contract"],
        final_receipt=final_output,
        expected_final_receipt_sha256=final_sha,
        v3_release_id=contract["v3_release_id"],
        v3_source_snapshot_id=contract["v3_source_snapshot_id"],
        v3_artifact_paths=expected_v3_paths,
        expected_v3_artifact_sha256s=expected_v3_shas,
    )
    return registration_args, final_sha


def _orchestration_run(
    *,
    run_id: str,
    status: str,
    reason_code: str,
    contract_sha256: str,
    monitor_sha256: str | None,
    source_freeze_sha256: str | None,
    artifact_build_performed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": BLOCKED_RUN_SCHEMA,
        "run_id": run_id,
        "status": status,
        "result_status": status,
        "reason_code": reason_code,
        "phase": "candidate_only_orchestration",
        "artifact_build_performed": artifact_build_performed,
        "candidate_id": None,
        "candidate_input_sha256": None,
        "entry_written": False,
        "event_written": False,
        "orchestration_contract_sha256": contract_sha256,
        "monitor_receipt_sha256": monitor_sha256,
        "source_freeze_manifest_sha256": source_freeze_sha256,
        "boundaries": dict(candidate.SAFE_BOUNDARIES),
    }


def _write_run(registry_root: Path, value: Mapping[str, Any]) -> None:
    candidate._write_immutable(
        registry_root / "runs" / f"{value['run_id']}.json",
        value,
        label="registry_run",
    )


def _write_receipt(
    path: Path,
    *,
    run_id: str,
    status: str,
    reason_code: str,
    contract_sha256: str,
    monitor_sha256: str | None,
    source_freeze_sha256: str | None,
    final_receipt_sha256: str | None,
    candidate_result: Mapping[str, Any] | None,
    step_results: Mapping[str, Mapping[str, Any]],
    registry_commit_state: str = "not_started",
) -> dict[str, Any]:
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "run_id": run_id,
        "status": status,
        "reason_code": reason_code,
        "orchestration_contract_sha256": contract_sha256,
        "monitor_receipt_sha256": monitor_sha256,
        "source_freeze_manifest_sha256": source_freeze_sha256,
        "final_receipt_sha256": final_receipt_sha256,
        "candidate_id": None if candidate_result is None else candidate_result.get("candidate_id"),
        "candidate_input_sha256": None if candidate_result is None else candidate_result.get("candidate_input_sha256"),
        "release_sha256": None if candidate_result is None else candidate_result.get("release_sha256"),
        "registry_commit_state": registry_commit_state,
        "entry_written": False,
        "event_written": False,
        "steps": {
            role: {
                "path": value["path"],
                "sha256": value["sha256"],
                "schema_version": value["schema_version"],
                "status": value["status"],
            }
            for role, value in sorted(step_results.items())
        },
        "boundaries": dict(candidate.SAFE_BOUNDARIES),
    }
    candidate._write_immutable(path, receipt, label="orchestration_receipt")
    return receipt


def orchestrate_candidate(
    *,
    contract_path: Path,
    automation_root: Path = candidate.AUTOMATION_ROOT,
    registry_root: Path = candidate.REGISTRY_ROOT,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    workspace_root: Path = ROOT,
) -> dict[str, Any]:
    workspace = _absolute_path(workspace_root, base=ROOT, label="workspace_root")
    _path_inside(
        workspace,
        workspace_root=workspace,
        allowed_root=workspace,
        label="workspace_root",
        require_directory=True,
    )
    contract_file = _path_inside(
        contract_path,
        workspace_root=workspace,
        allowed_root=workspace,
        label="orchestration_contract",
        require_file=True,
    )
    automation = _path_inside(
        automation_root,
        workspace_root=workspace,
        allowed_root=workspace,
        label="automation_root",
    )
    registry = _path_inside(
        registry_root,
        workspace_root=workspace,
        allowed_root=workspace,
        label="registry_root",
    )
    contract, contract_sha = _load_contract(contract_file)
    run_id = str(contract["run_id"])
    source_contract = _source_freeze_contract(contract["source_freeze"])
    steps = _step_contracts(contract["steps"])
    registration = _registration_contract(contract["registration"])
    run_root = automation / "orchestration" / run_id
    artifact_root = _validate_contract_paths(
        contract,
        source_contract,
        registration,
        workspace_root=workspace,
        automation_root=automation,
        run_root=run_root,
    )
    monitor_path = run_root / "monitor-receipt.json"
    receipt_path = run_root / "orchestration-receipt.json"
    monitor_sha: str | None = None
    source_sha: str | None = None
    step_results: dict[str, dict[str, Any]] = {}
    registration_started = False
    precommit_attempted = False
    with candidate.candidate_lock(automation):
        try:
            monitor_result = build_monitor_receipt(
                spec_path=_path_inside(
                    contract["monitor_spec_path"],
                    workspace_root=workspace,
                    allowed_root=workspace,
                    label="monitor_spec",
                    require_file=True,
                ),
                output_path=monitor_path,
                observed_at_utc=str(contract["observed_at_utc"]),
                monitor_root=workspace,
            )
            monitor_sha = str(monitor_result["receipt_sha256"])
            if monitor_result["status"] != "passed":
                reason = "no_candidate_collection_not_quiescent"
                _write_run(
                    registry,
                    _orchestration_run(
                        run_id=run_id,
                        status="blocked",
                        reason_code=reason,
                        contract_sha256=contract_sha,
                        monitor_sha256=monitor_sha,
                        source_freeze_sha256=None,
                        artifact_build_performed=False,
                    ),
                )
                _write_receipt(
                    receipt_path,
                    run_id=run_id,
                    status="blocked",
                    reason_code=reason,
                    contract_sha256=contract_sha,
                    monitor_sha256=monitor_sha,
                    source_freeze_sha256=None,
                    final_receipt_sha256=None,
                    candidate_result=None,
                    step_results={},
                )
                return {
                    "schema_version": "reddit_voc_candidate_orchestration_result_v1",
                    "status": "blocked",
                    "reason_code": reason,
                    "registry_write": "run_only",
                    "production_unchanged": True,
                    "deploy": False,
                    "remote_write": False,
                    "schedule_change": False,
                }

            members = []
            for source in source_contract["sources"]:
                members.extend(
                    capture_local_allowlist(
                        str(source["namespace"]),
                        _path_inside(
                            source["root"],
                            workspace_root=workspace,
                            allowed_root=workspace,
                            label="source_root",
                            require_directory=True,
                        ),
                        list(source["allowlist"]),
                    )
                )
            freeze_root = _path_inside(
                source_contract["output_root"],
                workspace_root=workspace,
                allowed_root=automation / "source-freezes",
                label="source_freeze_output",
            )
            candidate._ensure_private_directory(automation / "source-freezes")
            cutoff = _resolve_source_cutoff(str(source_contract["source_cutoff_utc"]), freeze_root)
            _, freeze_status = materialize_source_freeze(
                freeze_root,
                source_cutoff_utc=cutoff,
                members=members,
            )
            freeze_manifest = freeze_root / "source-freeze-manifest.json"
            source_sha = _sha(freeze_manifest, label="source_freeze_manifest")
            step_results = _run_steps(
                steps,
                source_freeze_root=freeze_root,
                source_freeze_sha256=source_sha,
                run_root=run_root,
                artifact_root=artifact_root,
                workspace_root=workspace,
                runner=runner,
                results=step_results,
            )
            registration_args, final_sha = _registration_args(
                registration,
                run_id=run_id,
                step_results=step_results,
            )
            prepared = candidate.prepare_candidate_registration(
                registration_args,
                registry_root=registry,
            )
            precommit_attempted = True
            _write_receipt(
                receipt_path,
                run_id=run_id,
                status="prepared",
                reason_code="candidate_registration_precommit",
                contract_sha256=contract_sha,
                monitor_sha256=monitor_sha,
                source_freeze_sha256=source_sha,
                final_receipt_sha256=final_sha,
                candidate_result=prepared.result,
                step_results=step_results,
                registry_commit_state="precommit_required",
            )
            registration_started = True
            registered = candidate.commit_prepared_candidate(prepared)
            return {
                "schema_version": "reddit_voc_candidate_orchestration_result_v1",
                "status": registered["status"],
                "reason_code": "candidate_registered",
                "candidate_id": registered["candidate_id"],
                "candidate_input_sha256": registered["candidate_input_sha256"],
                "release_sha256": registered["release_sha256"],
                "source_freeze_status": freeze_status,
                "orchestration_receipt": str(receipt_path.absolute()),
                "production_unchanged": True,
                "deploy": False,
                "remote_write": False,
                "schedule_change": False,
            }
        except (
            CandidateMonitorError,
            CandidateSourceCaptureError,
            CandidateOrchestrationError,
            candidate.CandidateRegistrationError,
            OSError,
        ) as exc:
            reason = candidate._reason_code(exc)
            if not registration_started and not precommit_attempted:
                _write_run(
                    registry,
                    _orchestration_run(
                        run_id=run_id,
                        status="failed",
                        reason_code=reason,
                        contract_sha256=contract_sha,
                        monitor_sha256=monitor_sha,
                        source_freeze_sha256=source_sha,
                        artifact_build_performed=bool(step_results),
                    ),
                )
            if not registration_started and not precommit_attempted:
                _write_receipt(
                    receipt_path,
                    run_id=run_id,
                    status="failed",
                    reason_code=reason,
                    contract_sha256=contract_sha,
                    monitor_sha256=monitor_sha,
                    source_freeze_sha256=source_sha,
                    final_receipt_sha256=None,
                    candidate_result=None,
                    step_results=step_results,
                )
            raise CandidateOrchestrationError(reason) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--automation-root", type=Path, default=candidate.AUTOMATION_ROOT)
    parser.add_argument("--registry-root", type=Path, default=candidate.REGISTRY_ROOT)
    args = parser.parse_args()
    try:
        result = orchestrate_candidate(
            contract_path=args.contract,
            automation_root=args.automation_root,
            registry_root=args.registry_root,
        )
    except candidate.CandidateBuildBusy:
        result = {
            "schema_version": "reddit_voc_candidate_orchestration_result_v1",
            "status": "blocked",
            "reason_code": "candidate_build_already_running",
            "registry_write": False,
            "production_unchanged": True,
            "deploy": False,
            "remote_write": False,
            "schedule_change": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3
    except CandidateOrchestrationError as exc:
        result = {
            "schema_version": "reddit_voc_candidate_orchestration_result_v1",
            "status": "failed",
            "reason_code": candidate._reason_code(exc),
            "production_unchanged": True,
            "deploy": False,
            "remote_write": False,
            "schedule_change": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"created", "no_change"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
