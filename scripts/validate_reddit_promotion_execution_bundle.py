#!/usr/bin/env python3
"""Reopen and validate every local byte required by a live promotion wrapper.

This validator is deliberately local-only.  It emits the exact six source
files and twelve runner arguments that a separately authorized transport
wrapper may seal on the production host.  It never opens a network connection
or mutates production state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, NoReturn

try:
    from scripts import build_reddit_promotion_permit as permit_contract
    from scripts import promote_reddit_candidate as execution_contract
    from scripts import reddit_release_control as control
    from scripts import validate_reddit_promotion_packet as packet_validator
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_promotion_permit as permit_contract
    import promote_reddit_candidate as execution_contract
    import reddit_release_control as control
    import validate_reddit_promotion_packet as packet_validator


SCHEMA_VERSION = "reddit_voc_live_promotion_bundle_validation_v1"
SEALED_NAMES = {
    "archive": "release.tgz",
    "packet": "packet.json",
    "permit": "permit.json",
    "runner": "remote_promote_insights_v6.sh",
    "installer": "remote_install_insights_release.sh",
    "rollback": "remote_rollback_insights.sh",
}


class PromotionBundleError(ValueError):
    """The exact local promotion bundle failed closed."""


def _fail(message: str) -> NoReturn:
    raise PromotionBundleError(message)


def _relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        _fail(f"{label}_path_invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail(f"{label}_path_invalid")
    return value


def _read_bound_file(
    *,
    root: Path,
    relative: object,
    label: str,
    expected_sha256: object,
    expected_bytes: object | None = None,
    expected_mode: int | None = None,
) -> tuple[Path, bytes, str]:
    path_value = _relative_path(relative, label=label)
    path = root / Path(*PurePosixPath(path_value).parts)
    try:
        observed_relative, payload = control.read_file(
            root=root,
            path=path,
            label=label,
            expected_mode=expected_mode,
        )
        expected_sha = control.require_sha256(
            expected_sha256,
            label=f"{label}_sha256",
        )
    except control.ReleaseControlError as exc:
        raise PromotionBundleError(str(exc)) from exc
    if observed_relative != path_value:
        _fail(f"{label}_path_mismatch")
    if control.sha256_bytes(payload) != expected_sha:
        _fail(f"{label}_sha256_mismatch")
    if expected_bytes is not None and (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
        or len(payload) != expected_bytes
    ):
        _fail(f"{label}_bytes_mismatch")
    return path, payload, expected_sha


def validate_bundle(
    *,
    artifact_root: Path,
    execution_path: Path,
    execution_sha256: str,
    packet_path: Path,
    packet_sha256: str,
    permit_path: Path,
    permit_sha256: str,
    now_utc: str,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        execution_relative, _execution_payload, execution = control.read_json(
            root=root,
            path=execution_path,
            label="promotion_execution_contract",
            expected_mode=0o600,
            expected_sha256=execution_sha256,
        )
        execution_contract.validate_promotion_execution_contract(execution)
    except (
        control.ReleaseControlError,
        execution_contract.PromotionExecutionError,
    ) as exc:
        raise PromotionBundleError(str(exc)) from exc

    bindings = execution.get("bindings")
    rows = execution.get("runner_argv_contract")
    runtime = execution.get("execution_runtime")
    if (
        not isinstance(bindings, dict)
        or not isinstance(rows, list)
        or not isinstance(runtime, dict)
    ):
        _fail("execution_contract_shape_invalid")
    argv = {
        row["name"]: row["value"]
        for row in rows
        if isinstance(row, dict) and set(row) == {"name", "value"}
    }
    if set(argv) != set(execution_contract.RUNNER_ARGUMENT_NAMES):
        _fail("runner_argv_contract_invalid")

    try:
        explicit_packet_relative, _ = control.read_file(
            root=root,
            path=packet_path,
            label="promotion_packet",
            expected_mode=0o600,
        )
        explicit_permit_relative, _ = control.read_file(
            root=root,
            path=permit_path,
            label="promotion_permit",
            expected_mode=0o600,
        )
    except control.ReleaseControlError as exc:
        raise PromotionBundleError(str(exc)) from exc
    if (
        explicit_packet_relative != argv["packet_path"]
        or explicit_permit_relative != argv["permit_path"]
        or bindings.get("packet_sha256") != packet_sha256
        or bindings.get("permit_sha256") != permit_sha256
    ):
        _fail("explicit_authority_path_binding_mismatch")

    try:
        packet_validator.validate_promotion_packet(
            artifact_root=root,
            packet_path=packet_path,
            expected_packet_sha256=packet_sha256,
            now_utc=now_utc,
        )
        permit_contract.validate_promotion_permit(
            artifact_root=root,
            packet_artifact_root=root,
            permit_path=permit_path,
            expected_permit_sha256=permit_sha256,
            packet_path=packet_path,
            expected_packet_sha256=packet_sha256,
            expected_release_sha256=str(bindings.get("release_sha256", "")),
            expected_current_release_sha256=str(
                bindings.get("expected_current_release_sha256", "")
            ),
            expected_current_data_release_id=str(
                bindings.get("expected_current_data_release_id", "")
            ),
            expected_current_data_pointer_sha256=str(
                bindings.get("expected_current_data_pointer_sha256", "")
            ),
            target_data_pointer_sha256=str(
                bindings.get("target_data_pointer_sha256", "")
            ),
            now_utc=now_utc,
        )
    except (
        packet_validator.PromotionPacketValidationError,
        permit_contract.PromotionPermitError,
    ) as exc:
        raise PromotionBundleError(str(exc)) from exc

    sources: dict[str, dict[str, Any]] = {}
    archive, archive_payload, archive_sha = _read_bound_file(
        root=root,
        relative=argv["archive_path"],
        label="release_archive",
        expected_sha256=bindings.get("archive_sha256"),
        expected_bytes=bindings.get("archive_bytes"),
    )
    sources["archive"] = {
        "bytes": len(archive_payload),
        "path": str(archive),
        "sealed_name": SEALED_NAMES["archive"],
        "sha256": archive_sha,
    }
    for label, explicit_path, expected_sha, sealed_name in (
        ("packet", packet_path, packet_sha256, SEALED_NAMES["packet"]),
        ("permit", permit_path, permit_sha256, SEALED_NAMES["permit"]),
    ):
        relative = argv[f"{label}_path"]
        path, payload, digest = _read_bound_file(
            root=root,
            relative=relative,
            label=f"promotion_{label}",
            expected_sha256=expected_sha,
            expected_mode=0o600,
        )
        if path != Path(explicit_path).absolute():
            _fail(f"explicit_{label}_path_mismatch")
        sources[label] = {
            "bytes": len(payload),
            "path": str(path),
            "sealed_name": sealed_name,
            "sha256": digest,
        }

    runtime_bindings = {
        "runner": ("remote_promotion_runner", "runner_sha256"),
        "installer": ("remote_installer", "installer_sha256"),
        "rollback": ("remote_rollback", "rollback_sha256"),
    }
    for label, (runtime_key, binding_key) in runtime_bindings.items():
        record = runtime.get(runtime_key)
        if not isinstance(record, dict):
            _fail(f"{label}_runtime_binding_invalid")
        path, payload, digest = _read_bound_file(
            root=root,
            relative=record.get("path"),
            label=f"remote_{label}",
            expected_sha256=bindings.get(binding_key),
            expected_bytes=record.get("bytes"),
        )
        if record.get("sha256") != digest:
            _fail(f"{label}_runtime_binding_mismatch")
        sources[label] = {
            "bytes": len(payload),
            "path": str(path),
            "sealed_name": SEALED_NAMES[label],
            "sha256": digest,
        }

    ordered_arguments = [argv[name] for name in execution_contract.RUNNER_ARGUMENT_NAMES]
    if ordered_arguments[1:] != [
        bindings["archive_sha256"],
        argv["packet_path"],
        bindings["packet_sha256"],
        argv["permit_path"],
        bindings["permit_sha256"],
        bindings["release_sha256"],
        bindings["expected_current_release_sha256"],
        bindings["data_release_id"],
        bindings["expected_current_data_release_id"],
        bindings["expected_current_data_pointer_sha256"],
        bindings["target_data_pointer_sha256"],
    ]:
        _fail("runner_argv_binding_mismatch")

    return {
        "artifact_root": str(root),
        "execution_contract": {
            "path": execution_relative,
            "sha256": execution_sha256,
        },
        "runner_arguments": {
            name: argv[name] for name in execution_contract.RUNNER_ARGUMENT_NAMES
        },
        "schema_version": SCHEMA_VERSION,
        "sources": sources,
        "status": "passed_local_exact_bundle",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--execution-contract", type=Path, required=True)
    parser.add_argument("--execution-contract-sha256", required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--permit-sha256", required=True)
    parser.add_argument("--now-utc", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_bundle(
            artifact_root=args.artifact_root,
            execution_path=args.execution_contract,
            execution_sha256=args.execution_contract_sha256,
            packet_path=args.packet,
            packet_sha256=args.packet_sha256,
            permit_path=args.permit,
            permit_sha256=args.permit_sha256,
            now_utc=args.now_utc,
        )
    except PromotionBundleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
