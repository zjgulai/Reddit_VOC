#!/usr/bin/env python3
"""Validate one exact Reddit VOC promotion packet and every bound artifact.

Validation is local and read-only.  Passing this command does not authorize or
consume a permit and does not perform any remote, Docker, database, scheduling,
collector, or production action.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_promotion_packet as contract
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_promotion_packet as contract


TOP_LEVEL_KEYS = {
    "artifacts",
    "authorization",
    "deferred_debts",
    "evidence",
    "expires_at_utc",
    "execution_runtime",
    "generated_at_utc",
    "nonce",
    "packet_id",
    "production_baseline_cas",
    "rollback",
    "schema_version",
    "side_effects",
    "status",
    "target",
}
TOP_LEVEL_V3_KEYS = TOP_LEVEL_KEYS | {"v3_lineage"}
TARGET_KEYS = {
    "data_release_id",
    "expected_current_data_pointer_sha256",
    "expected_current_data_release_id",
    "expected_current_release_sha256",
    "release_sha256",
    "site_url",
    "target_data_pointer_sha256",
}
AUTHORIZATION_KEYS = {
    "allowed_actions",
    "consumed",
    "forbidden_actions",
    "permit_required",
    "promotion_authorized",
    "required_owner_confirmation",
}
ROLLBACK_KEYS = {
    "readiness_mode",
    "ready",
    "scope",
    "shared_nginx_change_allowed",
    "target_data_file_count",
    "target_data_inventory_sha256",
    "target_data_pointer_sha256",
    "target_data_release_id",
    "target_data_total_bytes",
    "target_release_manifest_sha256",
    "target_release_sha256",
    "target_release_sha256s_sha256",
    "valid_until_utc",
}
EVIDENCE_KEYS = {
    "all_artifacts_reopened",
    "artifact_count",
    "baseline_max_age_seconds",
    "evidence_grade",
}
ARTIFACT_RECORD_KEYS = {"bytes", "path", "sha256"}
V3_LINEAGE_KEYS = {
    "artifact_sha256s",
    "candidate_release_sha256",
    "release_id",
    "source_snapshot_id",
}


class PromotionPacketValidationError(ValueError):
    """The packet or one of its immutable artifacts failed closed."""


def _raise_contract(exc: contract.PromotionPacketError) -> NoReturn:
    raise PromotionPacketValidationError(str(exc)) from exc


def _exact_keys(value: object, expected: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PromotionPacketValidationError(f"{label}_not_object")
    if set(value) != expected:
        raise PromotionPacketValidationError(f"{label}_unexpected_fields")
    return value


def _load_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionPacketValidationError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise PromotionPacketValidationError(f"{label}_not_object")
    return value


def _require_sha(value: object, *, label: str) -> str:
    try:
        return contract.require_sha256(value, label=label)
    except contract.PromotionPacketError as exc:
        _raise_contract(exc)
    raise AssertionError("unreachable")


def _parse_utc(value: object, *, label: str) -> tuple[str, datetime]:
    try:
        return contract.parse_utc(value, label=label)
    except contract.PromotionPacketError as exc:
        _raise_contract(exc)
    raise AssertionError("unreachable")


def _validate_fixed_contracts(packet: Mapping[str, Any]) -> None:
    if (
        packet.get("schema_version") != contract.SCHEMA_VERSION
        or packet.get("status") != "ready_for_owner_authorization"
    ):
        raise PromotionPacketValidationError("packet_contract_invalid")

    authorization = _exact_keys(
        packet.get("authorization"), AUTHORIZATION_KEYS, label="authorization"
    )
    if (
        authorization.get("allowed_actions") != list(contract.ALLOWED_ACTIONS)
        or authorization.get("forbidden_actions") != list(contract.FORBIDDEN_ACTIONS)
        or authorization.get("required_owner_confirmation")
        != ["packet_sha256", "release_sha256"]
        or authorization.get("promotion_authorized") is not False
        or authorization.get("consumed") is not False
        or authorization.get("permit_required") is not True
    ):
        raise PromotionPacketValidationError("authorization_contract_invalid")
    if packet.get("side_effects") != contract.SIDE_EFFECTS:
        raise PromotionPacketValidationError("side_effects_contract_invalid")
    if packet.get("deferred_debts") not in (
        contract.DEFERRED_DEBTS,
        contract.LEGACY_DEFERRED_DEBTS,
    ):
        raise PromotionPacketValidationError("deferred_debts_contract_invalid")


def validate_promotion_packet(
    *,
    artifact_root: Path,
    packet_path: Path,
    expected_packet_sha256: str,
    now_utc: str,
    allow_legacy_v3_native: bool = False,
) -> dict[str, Any]:
    try:
        root = contract._require_root(artifact_root)
        packet_relative, packet_payload = contract.read_explicit_file(
            root,
            packet_path,
            label="promotion_packet",
            expected_mode=0o600,
        )
    except contract.PromotionPacketError as exc:
        _raise_contract(exc)
    expected_packet_sha = _require_sha(
        expected_packet_sha256, label="expected_packet_sha256"
    )
    actual_packet_sha = contract.sha256_bytes(packet_payload)
    if actual_packet_sha != expected_packet_sha:
        raise PromotionPacketValidationError("promotion_packet_sha256_mismatch")
    packet = _load_object(packet_payload, label="promotion_packet")
    if packet_payload != contract.canonical_file_bytes(packet):
        raise PromotionPacketValidationError("promotion_packet_noncanonical")
    if set(packet) == TOP_LEVEL_KEYS:
        packet = _exact_keys(packet, TOP_LEVEL_KEYS, label="promotion_packet")
        v3_enabled = False
    elif set(packet) == TOP_LEVEL_V3_KEYS:
        packet = _exact_keys(packet, TOP_LEVEL_V3_KEYS, label="promotion_packet")
        v3_enabled = True
    else:
        raise PromotionPacketValidationError("promotion_packet_unexpected_fields")
    _validate_fixed_contracts(packet)

    generated_value, generated_at = _parse_utc(
        packet.get("generated_at_utc"), label="generated_at_utc"
    )
    expires_value, expires_at = _parse_utc(
        packet.get("expires_at_utc"), label="expires_at_utc"
    )
    now_value, now = _parse_utc(now_utc, label="now_utc")
    del now_value
    if expires_at <= generated_at:
        raise PromotionPacketValidationError("expiry_invalid")
    if now < generated_at:
        raise PromotionPacketValidationError("packet_not_yet_valid")
    if now >= expires_at:
        raise PromotionPacketValidationError("packet_expired")

    nonce = packet.get("nonce")
    if not isinstance(nonce, str) or contract.NONCE_RE.fullmatch(nonce) is None:
        raise PromotionPacketValidationError("nonce_invalid")
    target = _exact_keys(packet.get("target"), TARGET_KEYS, label="target")
    release_sha = _require_sha(target.get("release_sha256"), label="release_sha256")
    expected_current = _require_sha(
        target.get("expected_current_release_sha256"),
        label="expected_current_release_sha256",
    )
    data_release_id = target.get("data_release_id")
    if (
        not isinstance(data_release_id, str)
        or contract.DATA_RELEASE_RE.fullmatch(data_release_id) is None
    ):
        raise PromotionPacketValidationError("data_release_id_invalid")
    expected_current_data_release_id = target.get(
        "expected_current_data_release_id"
    )
    if (
        not isinstance(expected_current_data_release_id, str)
        or contract.DATA_RELEASE_RE.fullmatch(expected_current_data_release_id)
        is None
    ):
        raise PromotionPacketValidationError(
            "expected_current_data_release_id_invalid"
        )
    expected_current_data_pointer = _require_sha(
        target.get("expected_current_data_pointer_sha256"),
        label="expected_current_data_pointer_sha256",
    )
    target_data_pointer = _require_sha(
        target.get("target_data_pointer_sha256"),
        label="target_data_pointer_sha256",
    )
    if data_release_id == expected_current_data_release_id:
        raise PromotionPacketValidationError("data_release_transition_invalid")
    try:
        normalized_site = contract._site_url(target.get("site_url"))
    except contract.PromotionPacketError as exc:
        _raise_contract(exc)
    if normalized_site != target.get("site_url"):
        raise PromotionPacketValidationError("site_url_noncanonical")

    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PromotionPacketValidationError("artifacts_unexpected_fields")
    expected_artifact_keys = frozenset(artifacts)
    if v3_enabled:
        allowed_v3_sets = {
            contract.V3_EXTENSION_ARTIFACT_SET,
            contract.V3_NATIVE_ARTIFACT_SET,
        }
        legacy_native_set = frozenset(contract.V3_NATIVE_LEGACY_ARTIFACT_KEYS)
        if allow_legacy_v3_native:
            allowed_v3_sets.add(legacy_native_set)
        if expected_artifact_keys not in allowed_v3_sets:
            raise PromotionPacketValidationError("artifacts_unexpected_fields")
    elif expected_artifact_keys != contract.LEGACY_ARTIFACT_SET:
        raise PromotionPacketValidationError("artifacts_unexpected_fields")
    payloads: dict[str, bytes] = {}
    seen_paths: set[str] = set()
    if expected_artifact_keys == contract.V3_NATIVE_ARTIFACT_SET:
        artifact_order = contract.V3_NATIVE_ARTIFACT_KEYS
    elif expected_artifact_keys == frozenset(contract.V3_NATIVE_LEGACY_ARTIFACT_KEYS):
        artifact_order = contract.V3_NATIVE_LEGACY_ARTIFACT_KEYS
    else:
        artifact_order = (*contract.ARTIFACT_KEYS, *contract.V3_ARTIFACT_KEYS)
    for key in artifact_order:
        if key not in expected_artifact_keys:
            continue
        record = _exact_keys(
            artifacts.get(key), ARTIFACT_RECORD_KEYS, label=f"artifact_{key}"
        )
        path = record.get("path")
        if path == packet_relative:
            raise PromotionPacketValidationError("artifact_cannot_be_packet")
        if not isinstance(path, str) or path in seen_paths:
            raise PromotionPacketValidationError("artifact_path_duplicate")
        seen_paths.add(path)
        expected_bytes = record.get("bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise PromotionPacketValidationError(f"artifact_{key}_bytes_invalid")
        expected_sha = _require_sha(record.get("sha256"), label=f"artifact_{key}_sha256")
        try:
            payload = contract.read_relative_file(root, path, label=f"artifact_{key}")
        except contract.PromotionPacketError as exc:
            _raise_contract(exc)
        if len(payload) != expected_bytes:
            raise PromotionPacketValidationError(f"artifact_{key}_bytes_mismatch")
        if contract.sha256_bytes(payload) != expected_sha:
            raise PromotionPacketValidationError(f"artifact_{key}_sha256_mismatch")
        payloads[key] = payload

    execution_runtime = _exact_keys(
        packet.get("execution_runtime"),
        set(contract.EXECUTION_RUNTIME_KEYS),
        label="execution_runtime",
    )
    for key in contract.EXECUTION_RUNTIME_KEYS:
        record = _exact_keys(
            execution_runtime.get(key),
            ARTIFACT_RECORD_KEYS,
            label=f"execution_runtime_{key}",
        )
        path = record.get("path")
        if (
            not isinstance(path, str)
            or path in seen_paths
            or Path(path).name != contract.EXECUTION_RUNTIME_FILENAMES[key]
        ):
            raise PromotionPacketValidationError(
                f"execution_runtime_{key}_path_invalid"
            )
        expected_bytes = record.get("bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes <= 0
        ):
            raise PromotionPacketValidationError(
                f"execution_runtime_{key}_bytes_invalid"
            )
        expected_sha = _require_sha(
            record.get("sha256"), label=f"execution_runtime_{key}_sha256"
        )
        try:
            runtime_payload = contract.read_relative_file(
                root,
                path,
                label=f"execution_runtime_{key}",
            )
        except contract.PromotionPacketError as exc:
            _raise_contract(exc)
        if len(runtime_payload) != expected_bytes:
            raise PromotionPacketValidationError(
                f"execution_runtime_{key}_bytes_mismatch"
            )
        if contract.sha256_bytes(runtime_payload) != expected_sha:
            raise PromotionPacketValidationError(
                f"execution_runtime_{key}_sha256_mismatch"
            )
        seen_paths.add(path)

    evidence = _exact_keys(packet.get("evidence"), EVIDENCE_KEYS, label="evidence")
    baseline_max_age = evidence.get("baseline_max_age_seconds")
    if (
        evidence.get("all_artifacts_reopened") is not True
        or evidence.get("artifact_count") != len(expected_artifact_keys)
        or evidence.get("evidence_grade")
        != "L2-local-candidate-plus-L3-production-read-only-baseline"
        or isinstance(baseline_max_age, bool)
        or not isinstance(baseline_max_age, int)
        or not 1 <= baseline_max_age <= 3600
    ):
        raise PromotionPacketValidationError("evidence_contract_invalid")

    release_manifest = _load_object(
        payloads["release_manifest"], label="release_manifest"
    )
    baseline_receipt = _load_object(
        payloads["production_baseline_receipt"],
        label="production_baseline_receipt",
    )
    try:
        contract._validate_release_manifest(
            release_manifest,
            release_sha256=release_sha,
            data_release_id=data_release_id,
            target_data_pointer_sha256=target_data_pointer,
        )
        baseline_bindings = contract._validate_baseline_receipt(
            baseline_receipt,
            expected_current_release_sha256=expected_current,
            expected_current_data_release_id=expected_current_data_release_id,
            expected_current_data_pointer_sha256=expected_current_data_pointer,
            generated_at=generated_at,
            max_age_seconds=baseline_max_age,
        )
    except contract.PromotionPacketError as exc:
        _raise_contract(exc)

    v3_lineage = None
    if v3_enabled:
        v3_lineage = _exact_keys(
            packet.get("v3_lineage"), V3_LINEAGE_KEYS, label="v3_lineage"
        )
        artifact_shas = v3_lineage.get("artifact_sha256s")
        expected_v3_lineage_keys = (
            expected_artifact_keys
            if expected_artifact_keys in {
                contract.V3_NATIVE_ARTIFACT_SET,
                frozenset(contract.V3_NATIVE_LEGACY_ARTIFACT_KEYS),
            }
            else frozenset(contract.V3_ARTIFACT_KEYS)
        )
        if (
            not isinstance(artifact_shas, dict)
            or frozenset(artifact_shas) != expected_v3_lineage_keys
            or v3_lineage.get("candidate_release_sha256") != release_sha
            or not isinstance(v3_lineage.get("release_id"), str)
            or not v3_lineage["release_id"]
            or not isinstance(v3_lineage.get("source_snapshot_id"), str)
            or not v3_lineage["source_snapshot_id"]
        ):
            raise PromotionPacketValidationError("v3_lineage_contract_invalid")
        for key in expected_v3_lineage_keys:
            if artifact_shas.get(key) != artifacts[key]["sha256"]:
                raise PromotionPacketValidationError(
                    "v3_lineage_artifact_binding_invalid"
                )
        try:
            independently_derived = contract._validate_v3_artifacts(
                payloads,
                artifacts,
                release_id=str(v3_lineage["release_id"]),
                source_snapshot_id=str(v3_lineage["source_snapshot_id"]),
                candidate_release_sha256=release_sha,
                packet_generated_at=generated_at,
                allow_legacy_native=allow_legacy_v3_native,
            )
        except contract.PromotionPacketError as exc:
            _raise_contract(exc)
        if independently_derived != dict(v3_lineage):
            raise PromotionPacketValidationError("v3_lineage_replay_mismatch")

    baseline_rollback_bindings = baseline_bindings["rollback"]
    production_baseline_cas = packet.get("production_baseline_cas")
    if production_baseline_cas != baseline_bindings["cas"]:
        raise PromotionPacketValidationError("production_baseline_cas_mismatch")
    rollback = _exact_keys(packet.get("rollback"), ROLLBACK_KEYS, label="rollback")
    if (
        rollback.get("readiness_mode") != "immediate_same_baseline_window"
        or rollback.get("ready") is not True
        or rollback.get("scope") != "insights_site_and_data_current"
        or rollback.get("shared_nginx_change_allowed") is not False
        or rollback.get("target_release_sha256") != expected_current
        or rollback.get("target_data_release_id")
        != expected_current_data_release_id
        or rollback.get("target_data_pointer_sha256")
        != expected_current_data_pointer
        or rollback.get("target_data_inventory_sha256")
        != baseline_rollback_bindings["target_data_inventory_sha256"]
        or rollback.get("target_data_file_count")
        != baseline_rollback_bindings["target_data_file_count"]
        or rollback.get("target_data_total_bytes")
        != baseline_rollback_bindings["target_data_total_bytes"]
        or rollback.get("target_release_manifest_sha256")
        != baseline_rollback_bindings["target_release_manifest_sha256"]
        or rollback.get("target_release_sha256s_sha256")
        != baseline_rollback_bindings["target_release_sha256s_sha256"]
        or rollback.get("valid_until_utc") != expires_value
    ):
        raise PromotionPacketValidationError("rollback_contract_invalid")

    identity = {
        "baseline_receipt_sha256": artifacts["production_baseline_receipt"]["sha256"],
        "data_release_id": data_release_id,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "expected_current_data_release_id": expected_current_data_release_id,
        "expires_at_utc": expires_value,
        "execution_runtime": dict(execution_runtime),
        "generated_at_utc": generated_value,
        "nonce": nonce,
        "production_baseline_cas": production_baseline_cas,
        "release_sha256": release_sha,
        "target_data_pointer_sha256": target_data_pointer,
    }
    if v3_lineage is not None:
        identity["v3_lineage"] = dict(v3_lineage)
    if packet.get("packet_id") != contract._packet_id(identity):
        raise PromotionPacketValidationError("packet_id_mismatch")

    return {
        "artifact_count": len(expected_artifact_keys),
        "consumed": False,
        "data_release_id": data_release_id,
        "deploy": False,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "expected_current_data_release_id": expected_current_data_release_id,
        "expires_at_utc": expires_value,
        "packet_sha256": actual_packet_sha,
        "promotion_authorized": False,
        "release_sha256": release_sha,
        "remote_write": False,
        "schema_version": "reddit_voc_promotion_packet_validation_result_v1",
        "status": "passed",
        "target_data_pointer_sha256": target_data_pointer,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--expected-packet-sha256", required=True)
    parser.add_argument(
        "--now-utc",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_promotion_packet(
            artifact_root=args.artifact_root,
            packet_path=args.packet,
            expected_packet_sha256=args.expected_packet_sha256,
            now_utc=args.now_utc,
        )
    except PromotionPacketValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
