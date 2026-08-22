#!/usr/bin/env python3
"""Prepare a local-only execution contract for a Reddit VOC promotion.

Despite the historical filename, this productized wrapper never executes SSH,
SCP, Docker, curl, or the bound remote runner.  It validates exact local bytes
and emits the twelve-argument contract expected by the established remote runner.
An external, separately authorized operator is required for any real remote
execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_promotion_packet as packet_contract
    from scripts import build_reddit_promotion_permit as permit_contract
    from scripts import reddit_release_control as control
    from scripts import validate_reddit_promotion_packet as packet_validator
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_promotion_packet as packet_contract
    import build_reddit_promotion_permit as permit_contract
    import reddit_release_control as control
    import validate_reddit_promotion_packet as packet_validator


SCHEMA_VERSION = "reddit_voc_promotion_execution_contract_v3"
STATUS = "ready_for_explicit_external_execution"
RUNNER_ARGUMENT_NAMES = (
    "archive_path",
    "archive_sha256",
    "packet_path",
    "packet_sha256",
    "permit_path",
    "permit_sha256",
    "release_sha256",
    "expected_current_release_sha256",
    "data_release_id",
    "expected_current_data_release_id",
    "expected_current_data_pointer_sha256",
    "target_data_pointer_sha256",
)

EXECUTION_BINDING_KEYS = {
    "archive_bytes",
    "archive_sha256",
    "data_release_id",
    "expected_current_data_pointer_sha256",
    "expected_current_data_release_id",
    "expected_current_release_sha256",
    "installer_sha256",
    "packet_sha256",
    "permit_sha256",
    "release_sha256",
    "rollback_sha256",
    "runner_sha256",
    "target_data_pointer_sha256",
}
EXECUTION_CONTRACT_KEYS = {
    "authorized_actions",
    "bindings",
    "execution",
    "execution_runtime",
    "forbidden_actions",
    "remote_runner",
    "runner_argv_contract",
    "schema_version",
    "side_effects",
    "status",
}


class PromotionExecutionError(ValueError):
    """The local promotion execution contract failed closed."""


def _fail(message: str) -> NoReturn:
    raise PromotionExecutionError(message)


def _load_packet(
    *, root: Path, packet_path: Path, packet_sha256: str
) -> tuple[str, dict[str, Any]]:
    try:
        relative, _, value = control.read_json(
            root=root,
            path=packet_path,
            label="promotion_packet",
            expected_mode=0o600,
            expected_sha256=packet_sha256,
        )
    except control.ReleaseControlError as exc:
        raise PromotionExecutionError(str(exc)) from exc
    return relative, value


def validate_promotion_execution_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        set(value) != EXECUTION_CONTRACT_KEYS
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != STATUS
    ):
        _fail("execution_contract_invalid")
    execution = value.get("execution")
    if not isinstance(execution, dict) or execution != {
        "deploy": False,
        "executed": False,
        "mode": "local_contract_only",
        "production_switch": False,
        "remote_write": False,
        "ssh": False,
    }:
        _fail("execution_boundary_invalid")
    bindings = value.get("bindings")
    if not isinstance(bindings, dict) or set(bindings) != EXECUTION_BINDING_KEYS:
        _fail("execution_bindings_invalid")
    for name in (
        "archive_sha256",
        "expected_current_data_pointer_sha256",
        "expected_current_release_sha256",
        "installer_sha256",
        "packet_sha256",
        "permit_sha256",
        "release_sha256",
        "rollback_sha256",
        "runner_sha256",
        "target_data_pointer_sha256",
    ):
        try:
            control.require_sha256(bindings.get(name), label=name)
        except control.ReleaseControlError as exc:
            raise PromotionExecutionError(str(exc)) from exc
    archive_bytes = bindings.get("archive_bytes")
    if (
        isinstance(archive_bytes, bool)
        or not isinstance(archive_bytes, int)
        or archive_bytes <= 0
    ):
        _fail("archive_bytes_invalid")
    for name in ("data_release_id", "expected_current_data_release_id"):
        value_for_name = bindings.get(name)
        if (
            not isinstance(value_for_name, str)
            or packet_contract.DATA_RELEASE_RE.fullmatch(value_for_name) is None
        ):
            _fail(f"{name}_invalid")
    argv = value.get("runner_argv_contract")
    if (
        not isinstance(argv, list)
        or len(argv) != len(RUNNER_ARGUMENT_NAMES)
        or [row.get("name") for row in argv if isinstance(row, dict)]
        != list(RUNNER_ARGUMENT_NAMES)
        or any(
            not isinstance(row, dict) or set(row) != {"name", "value"}
            for row in argv
        )
    ):
        _fail("runner_argv_contract_invalid")
    expected_values = {
        "archive_sha256": bindings["archive_sha256"],
        "expected_current_release_sha256": bindings[
            "expected_current_release_sha256"
        ],
        "packet_sha256": bindings["packet_sha256"],
        "permit_sha256": bindings["permit_sha256"],
        "release_sha256": bindings["release_sha256"],
        "data_release_id": bindings.get("data_release_id"),
        "expected_current_data_release_id": bindings[
            "expected_current_data_release_id"
        ],
        "expected_current_data_pointer_sha256": bindings[
            "expected_current_data_pointer_sha256"
        ],
        "target_data_pointer_sha256": bindings["target_data_pointer_sha256"],
    }
    for row in argv:
        name = row["name"]
        if name in expected_values and row["value"] != expected_values[name]:
            _fail("runner_argv_binding_mismatch")
        if name.endswith("_path"):
            path = row["value"]
            if (
                not isinstance(path, str)
                or not path
                or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
            ):
                _fail("runner_argv_path_invalid")
    remote_runner = value.get("remote_runner")
    if (
        not isinstance(remote_runner, dict)
        or set(remote_runner) != {"argument_count", "path", "sha256"}
        or remote_runner.get("argument_count") != len(RUNNER_ARGUMENT_NAMES)
        or remote_runner.get("sha256") != bindings["runner_sha256"]
        or not isinstance(remote_runner.get("path"), str)
        or not remote_runner["path"]
        or PurePosixPath(remote_runner["path"]).is_absolute()
        or ".." in PurePosixPath(remote_runner["path"]).parts
    ):
        _fail("remote_runner_contract_invalid")
    execution_runtime = value.get("execution_runtime")
    if (
        not isinstance(execution_runtime, dict)
        or set(execution_runtime) != set(packet_contract.EXECUTION_RUNTIME_KEYS)
    ):
        _fail("execution_runtime_invalid")
    seen_runtime_paths: set[str] = set()
    runtime_binding_shas = {
        "remote_promotion_runner": bindings["runner_sha256"],
        "remote_installer": bindings["installer_sha256"],
        "remote_rollback": bindings["rollback_sha256"],
    }
    for key in packet_contract.EXECUTION_RUNTIME_KEYS:
        record = execution_runtime.get(key)
        if not isinstance(record, dict) or set(record) != {"bytes", "path", "sha256"}:
            _fail("execution_runtime_invalid")
        path = record.get("path")
        size = record.get("bytes")
        if (
            not isinstance(path, str)
            or not path
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or PurePosixPath(path).name
            != packet_contract.EXECUTION_RUNTIME_FILENAMES[key]
            or path in seen_runtime_paths
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or record.get("sha256") != runtime_binding_shas[key]
        ):
            _fail("execution_runtime_binding_mismatch")
        seen_runtime_paths.add(path)
    if (
        remote_runner.get("path")
        != execution_runtime["remote_promotion_runner"]["path"]
    ):
        _fail("remote_runner_runtime_path_mismatch")
    if value.get("side_effects") != packet_contract.SIDE_EFFECTS:
        _fail("execution_side_effects_invalid")
    if value.get("authorized_actions") != list(packet_contract.ALLOWED_ACTIONS):
        _fail("execution_actions_invalid")
    if value.get("forbidden_actions") != list(packet_contract.FORBIDDEN_ACTIONS):
        _fail("execution_forbidden_actions_invalid")
    return {
        "deploy": False,
        "executed": False,
        "packet_sha256": bindings["packet_sha256"],
        "permit_sha256": bindings["permit_sha256"],
        "release_sha256": bindings["release_sha256"],
        "remote_write": False,
        "schema_version": "reddit_voc_promotion_execution_validation_result_v1",
        "ssh": False,
        "status": "passed_local_contract",
    }


def build_promotion_execution_contract(
    *,
    artifact_root: Path,
    packet_artifact_root: Path | None = None,
    packet_path: Path,
    packet_sha256: str,
    permit_path: Path,
    permit_sha256: str,
    release_archive_path: Path,
    release_archive_sha256: str,
    remote_runner_path: Path,
    remote_runner_sha256: str,
    remote_installer_path: Path,
    remote_installer_sha256: str,
    remote_rollback_path: Path,
    remote_rollback_sha256: str,
    release_sha256: str,
    expected_current_release_sha256: str,
    expected_current_data_release_id: str,
    expected_current_data_pointer_sha256: str,
    target_data_pointer_sha256: str,
    now_utc: str,
    output: Path | None = None,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        packet_root = control.require_root(packet_artifact_root or artifact_root)
        packet_root.relative_to(root)
        expected_packet_sha = control.require_sha256(
            packet_sha256, label="packet_sha256"
        )
        expected_permit_sha = control.require_sha256(
            permit_sha256, label="permit_sha256"
        )
        expected_archive_sha = control.require_sha256(
            release_archive_sha256, label="release_archive_sha256"
        )
        expected_runner_sha = control.require_sha256(
            remote_runner_sha256, label="remote_runner_sha256"
        )
        expected_installer_sha = control.require_sha256(
            remote_installer_sha256, label="remote_installer_sha256"
        )
        expected_rollback_sha = control.require_sha256(
            remote_rollback_sha256, label="remote_rollback_sha256"
        )
        expected_release = control.require_sha256(
            release_sha256, label="release_sha256"
        )
        expected_current = control.require_sha256(
            expected_current_release_sha256,
            label="expected_current_release_sha256",
        )
        expected_current_data_pointer = control.require_sha256(
            expected_current_data_pointer_sha256,
            label="expected_current_data_pointer_sha256",
        )
        target_data_pointer = control.require_sha256(
            target_data_pointer_sha256,
            label="target_data_pointer_sha256",
        )
    except (control.ReleaseControlError, ValueError) as exc:
        raise PromotionExecutionError(str(exc)) from exc
    if (
        not isinstance(expected_current_data_release_id, str)
        or packet_contract.DATA_RELEASE_RE.fullmatch(expected_current_data_release_id)
        is None
    ):
        _fail("expected_current_data_release_id_invalid")
    try:
        packet_validator.validate_promotion_packet(
            artifact_root=packet_root,
            packet_path=packet_path,
            expected_packet_sha256=expected_packet_sha,
            now_utc=now_utc,
        )
        permit_contract.validate_promotion_permit(
            artifact_root=root,
            packet_artifact_root=packet_root,
            permit_path=permit_path,
            expected_permit_sha256=expected_permit_sha,
            packet_path=packet_path,
            expected_packet_sha256=expected_packet_sha,
            expected_release_sha256=expected_release,
            expected_current_release_sha256=expected_current,
            expected_current_data_release_id=expected_current_data_release_id,
            expected_current_data_pointer_sha256=expected_current_data_pointer,
            target_data_pointer_sha256=target_data_pointer,
            now_utc=now_utc,
        )
    except (
        packet_validator.PromotionPacketValidationError,
        permit_contract.PromotionPermitError,
    ) as exc:
        raise PromotionExecutionError(str(exc)) from exc
    packet_relative, packet = _load_packet(
        root=packet_root,
        packet_path=packet_path,
        packet_sha256=expected_packet_sha,
    )
    target = packet.get("target")
    artifacts = packet.get("artifacts")
    execution_runtime = packet.get("execution_runtime")
    transfer = artifacts.get("transfer_tgz") if isinstance(artifacts, dict) else None
    if (
        not isinstance(target, dict)
        or not isinstance(transfer, dict)
        or not isinstance(execution_runtime, dict)
    ):
        _fail("packet_execution_binding_invalid")
    if (
        target.get("release_sha256") != expected_release
        or target.get("expected_current_release_sha256") != expected_current
        or target.get("expected_current_data_release_id")
        != expected_current_data_release_id
        or target.get("expected_current_data_pointer_sha256")
        != expected_current_data_pointer
        or target.get("target_data_pointer_sha256") != target_data_pointer
    ):
        _fail("packet_execution_binding_invalid")
    try:
        archive_relative, archive_payload = control.read_file(
            root=packet_root,
            path=release_archive_path,
            label="release_archive",
        )
        packet_control_relative, _ = control.read_file(
            root=root,
            path=packet_path,
            label="promotion_packet",
            expected_mode=0o600,
        )
        archive_control_relative, _ = control.read_file(
            root=root,
            path=release_archive_path,
            label="release_archive",
        )
        runner_relative, runner_payload = control.read_file(
            root=packet_root,
            path=remote_runner_path,
            label="remote_promotion_runner",
        )
        installer_relative, installer_payload = control.read_file(
            root=packet_root,
            path=remote_installer_path,
            label="remote_installer",
        )
        rollback_relative, rollback_payload = control.read_file(
            root=packet_root,
            path=remote_rollback_path,
            label="remote_rollback",
        )
        permit_relative, _ = control.read_file(
            root=root,
            path=permit_path,
            label="promotion_permit",
            expected_mode=0o600,
        )
    except control.ReleaseControlError as exc:
        raise PromotionExecutionError(str(exc)) from exc
    if (
        control.sha256_bytes(archive_payload) != expected_archive_sha
        or transfer.get("path") != archive_relative
        or transfer.get("sha256") != expected_archive_sha
        or transfer.get("bytes") != len(archive_payload)
    ):
        _fail("release_archive_binding_mismatch")
    runtime_payloads = {
        "remote_promotion_runner": (runner_relative, runner_payload, expected_runner_sha),
        "remote_installer": (installer_relative, installer_payload, expected_installer_sha),
        "remote_rollback": (rollback_relative, rollback_payload, expected_rollback_sha),
    }
    for key, (relative, payload, expected_sha) in runtime_payloads.items():
        record = execution_runtime.get(key)
        if not isinstance(record, dict) or record.get("path") != relative:
            _fail(f"{key}_path_mismatch")
        if record.get("bytes") != len(payload):
            _fail(f"{key}_bytes_mismatch")
        if (
            control.sha256_bytes(payload) != expected_sha
            or record.get("sha256") != expected_sha
        ):
            _fail(f"{key}_sha256_mismatch")

    data_release_id = target.get("data_release_id")
    bindings = {
        "archive_bytes": len(archive_payload),
        "archive_sha256": expected_archive_sha,
        "data_release_id": data_release_id,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "expected_current_data_release_id": expected_current_data_release_id,
        "expected_current_release_sha256": expected_current,
        "installer_sha256": expected_installer_sha,
        "packet_sha256": expected_packet_sha,
        "permit_sha256": expected_permit_sha,
        "release_sha256": expected_release,
        "rollback_sha256": expected_rollback_sha,
        "runner_sha256": expected_runner_sha,
        "target_data_pointer_sha256": target_data_pointer,
    }
    argument_values = {
        "archive_path": archive_relative,
        "archive_sha256": expected_archive_sha,
        "packet_path": packet_control_relative,
        "packet_sha256": expected_packet_sha,
        "permit_path": permit_relative,
        "permit_sha256": expected_permit_sha,
        "release_sha256": expected_release,
        "expected_current_release_sha256": expected_current,
        "data_release_id": data_release_id,
        "expected_current_data_release_id": expected_current_data_release_id,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "target_data_pointer_sha256": target_data_pointer,
    }
    argument_values["archive_path"] = archive_control_relative
    contract: dict[str, Any] = {
        "authorized_actions": list(packet_contract.ALLOWED_ACTIONS),
        "bindings": bindings,
        "execution": {
            "deploy": False,
            "executed": False,
            "mode": "local_contract_only",
            "production_switch": False,
            "remote_write": False,
            "ssh": False,
        },
        "forbidden_actions": list(packet_contract.FORBIDDEN_ACTIONS),
        "execution_runtime": {
            key: dict(execution_runtime[key])
            for key in packet_contract.EXECUTION_RUNTIME_KEYS
        },
        "remote_runner": {
            "argument_count": len(RUNNER_ARGUMENT_NAMES),
            "path": runner_relative,
            "sha256": expected_runner_sha,
        },
        "runner_argv_contract": [
            {"name": name, "value": argument_values[name]}
            for name in RUNNER_ARGUMENT_NAMES
        ],
        "schema_version": SCHEMA_VERSION,
        "side_effects": dict(packet_contract.SIDE_EFFECTS),
        "status": STATUS,
    }
    validation = validate_promotion_execution_contract(contract)
    publication_status = "not_written"
    if output is not None:
        try:
            publication_status = control.write_immutable(
                root=root,
                output=output,
                value=contract,
                label="promotion_execution_contract",
            )
        except control.ReleaseControlError as exc:
            raise PromotionExecutionError(str(exc)) from exc
    return {
        **contract,
        "execution_contract_sha256": control.sha256_bytes(
            control.canonical_bytes(contract)
        ),
        "publication_status": publication_status,
        "validation": validation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--packet-artifact-root", type=Path)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--permit-sha256", required=True)
    parser.add_argument("--release-archive", type=Path, required=True)
    parser.add_argument("--release-archive-sha256", required=True)
    parser.add_argument("--remote-runner", type=Path, required=True)
    parser.add_argument("--remote-runner-sha256", required=True)
    parser.add_argument("--remote-installer", type=Path, required=True)
    parser.add_argument("--remote-installer-sha256", required=True)
    parser.add_argument("--remote-rollback", type=Path, required=True)
    parser.add_argument("--remote-rollback-sha256", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--expected-current-release-sha256", required=True)
    parser.add_argument("--expected-current-data-release-id", required=True)
    parser.add_argument("--expected-current-data-pointer-sha256", required=True)
    parser.add_argument("--target-data-pointer-sha256", required=True)
    parser.add_argument("--now-utc", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = build_promotion_execution_contract(
            artifact_root=args.artifact_root,
            packet_artifact_root=args.packet_artifact_root,
            packet_path=args.packet,
            packet_sha256=args.packet_sha256,
            permit_path=args.permit,
            permit_sha256=args.permit_sha256,
            release_archive_path=args.release_archive,
            release_archive_sha256=args.release_archive_sha256,
            remote_runner_path=args.remote_runner,
            remote_runner_sha256=args.remote_runner_sha256,
            remote_installer_path=args.remote_installer,
            remote_installer_sha256=args.remote_installer_sha256,
            remote_rollback_path=args.remote_rollback,
            remote_rollback_sha256=args.remote_rollback_sha256,
            release_sha256=args.release_sha256,
            expected_current_release_sha256=args.expected_current_release_sha256,
            expected_current_data_release_id=args.expected_current_data_release_id,
            expected_current_data_pointer_sha256=(
                args.expected_current_data_pointer_sha256
            ),
            target_data_pointer_sha256=args.target_data_pointer_sha256,
            now_utc=args.now_utc,
            output=args.output,
        )
    except PromotionExecutionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
