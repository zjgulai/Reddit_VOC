#!/usr/bin/env python3
"""Build and validate an exact, immutable Reddit VOC owner promotion permit.

The permit is a local authorization artifact.  Building or validating it does
not consume it and never uploads, invokes Docker, opens SSH, or changes the
production release.  Consumption is represented by a separate immutable
receipt after public production acceptance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_promotion_packet as packet_contract
    from scripts import reddit_release_control as control
    from scripts import validate_reddit_promotion_packet as packet_validator
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_promotion_packet as packet_contract
    import reddit_release_control as control
    import validate_reddit_promotion_packet as packet_validator


SCHEMA_VERSION = "reddit_voc_promotion_permit_v1"
PRODUCTIZED_CONTRACT = "reddit_voc_promotion_permit_exact_binding_v4"
LEGACY_PRODUCTIZED_CONTRACT = "reddit_voc_promotion_permit_exact_binding_v2"
OWNER_CONFIRMATION = "authorize_exact_reddit_voc_packet_and_release"
AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
PERMIT_KEYS = {
    "authorization",
    "authorization_id",
    "authorized_actions",
    "authorized_by",
    "authorized_recorded_at_utc",
    "consumed",
    "contract",
    "expires_at_utc",
    "forbidden_actions",
    "packet",
    "packet_id",
    "packet_sha256",
    "release_sha256",
    "schema_version",
    "scope",
    "side_effects",
    "status",
}
PERMIT_AUTHORIZATION_KEYS = {
    "authorized_actions",
    "authorized_at_utc",
    "authorized_by",
    "forbidden_actions",
    "owner_confirmation",
}
PERMIT_PACKET_KEYS = {
    "data_release_id",
    "execution_runtime",
    "expected_current_data_pointer_sha256",
    "expected_current_data_release_id",
    "expected_current_release_sha256",
    "expires_at_utc",
    "nonce",
    "packet_id",
    "packet_sha256",
    "release_sha256",
    "target_data_pointer_sha256",
}
LEGACY_FLAT_PERMIT_KEYS = {
    "authorization_id",
    "authorized_actions",
    "authorized_by",
    "authorized_recorded_at_utc",
    "consumed",
    "expires_at_utc",
    "forbidden_actions",
    "packet_id",
    "packet_sha256",
    "release_sha256",
    "schema_version",
    "scope",
    "user_authorization_text",
}
LEGACY_PERMIT_PACKET_KEYS = {
    "data_release_id",
    "expected_current_release_sha256",
    "expires_at_utc",
    "nonce",
    "packet_id",
    "packet_sha256",
    "release_sha256",
}
LEGACY_PACKET_KEYS = {
    "artifacts",
    "authorization",
    "deferred_debts",
    "evidence",
    "expires_at_utc",
    "generated_at_utc",
    "nonce",
    "packet_id",
    "rollback",
    "schema_version",
    "side_effects",
    "status",
    "target",
}
LEGACY_PACKET_TARGET_KEYS = {
    "data_release_id",
    "expected_current_release_sha256",
    "release_sha256",
    "site_url",
}
LEGACY_PACKET_ROLLBACK_KEYS = {
    "ready",
    "scope",
    "shared_nginx_change_allowed",
    "target_release_sha256",
}
LEGACY_PACKET_AUTHORIZATION_KEYS = {
    "allowed_actions",
    "consumed",
    "forbidden_actions",
    "permit_required",
    "promotion_authorized",
    "required_owner_confirmation",
}
LEGACY_V3_NATIVE_PERMIT_BINDINGS = frozenset(
    {
        (
            "reddit_voc_promotion_85e851060befbc2692ded1e1",
            "34f38d536576bab7556725745b4d0efe080bd2eb169c9c617e74002fcab76040",
            "103efd8c7405d5dd7c5b414c93d7601297b9be9703c628737cdfa4a3583329a2",
            "ea15b3ef0a1af7a2c9e644b2090c4d36a3dd1038e7967ba8a78402e659a0efc1",
        ),
        (
            "reddit_voc_promotion_a042c0af6056b35c89881673",
            "e6cb274ea88335b67aad915d97d0491bcb0d8b6758664d7c3fb97f673d6d56a8",
            "ace4553d7007703e081a4a0a4a654417d332368661b357d972d1e16891de4f6e",
            "627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4",
        ),
        (
            "reddit_voc_promotion_282f91ae1c089f722e8aa963",
            "8e68138ba62a624e5c03af9070615ad6623af37358638de8a37d00b7f04c95c5",
            "7ff1227cc63e03c1102de9bad4371361d3cf00da6739cbec91d5a9c29bcdceb8",
            "9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5",
        ),
    }
)
LEGACY_PERMIT_BINDINGS = LEGACY_V3_NATIVE_PERMIT_BINDINGS | {
    (
        "reddit_voc_promotion_5a452fa724ea9f7c1beeff22",
        "c8ca362a038338593463d7245e6d9f74b8e143a1a0672ad574d0f93b3013e482",
        "83d5ebeaf2345bc78495ed99064d34dcb4f23d09d2c8eda5274110f50a510570",
        "a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3",
    )
}


class PromotionPermitError(ValueError):
    """The permit is missing or violates its exact owner authorization."""


def legacy_v3_native_permit_allowed(
    *,
    authorization_id: object,
    permit_sha256: str,
    packet_sha256: str,
    release_sha256: str,
) -> bool:
    return (
        authorization_id,
        permit_sha256,
        packet_sha256,
        release_sha256,
    ) in LEGACY_V3_NATIVE_PERMIT_BINDINGS


def legacy_permit_allowed(
    *,
    authorization_id: object,
    permit_sha256: str,
    packet_sha256: str,
    release_sha256: str,
) -> bool:
    return (
        authorization_id,
        permit_sha256,
        packet_sha256,
        release_sha256,
    ) in LEGACY_PERMIT_BINDINGS


def canonical_bytes(value: object) -> bytes:
    return control.canonical_bytes(value)


def _raise(exc: Exception) -> NoReturn:
    raise PromotionPermitError(str(exc)) from exc


def _packet_document(
    *, root: Path, packet_path: Path, expected_packet_sha256: str
) -> tuple[bytes, dict[str, Any]]:
    try:
        _, payload, value = control.read_json(
            root=root,
            path=packet_path,
            label="promotion_packet",
            expected_mode=0o600,
            expected_sha256=expected_packet_sha256,
        )
    except control.ReleaseControlError as exc:
        _raise(exc)
    return payload, value


def _validate_exact_legacy_packet(
    *,
    root: Path,
    packet: Mapping[str, Any],
    expected_release_sha256: str,
    expected_current_release_sha256: str,
) -> None:
    """Reopen one allowlisted v2 packet without making v2 newly authorizable."""

    packet_keys = frozenset(packet)
    if (
        packet.get("schema_version") != packet_contract.LEGACY_SCHEMA_VERSION
        or packet.get("status") != "ready_for_owner_authorization"
        or packet_keys
        not in {frozenset(LEGACY_PACKET_KEYS), frozenset(LEGACY_PACKET_KEYS | {"v3_lineage"})}
    ):
        raise PromotionPermitError("packet_contract_invalid")
    target = packet.get("target")
    authorization = packet.get("authorization")
    rollback = packet.get("rollback")
    if (
        not isinstance(target, dict)
        or set(target) != LEGACY_PACKET_TARGET_KEYS
        or target.get("release_sha256") != expected_release_sha256
        or target.get("expected_current_release_sha256")
        != expected_current_release_sha256
        or not isinstance(authorization, dict)
        or set(authorization) != LEGACY_PACKET_AUTHORIZATION_KEYS
        or authorization.get("allowed_actions")
        != list(packet_contract.LEGACY_ALLOWED_ACTIONS)
        or authorization.get("forbidden_actions")
        != list(packet_contract.FORBIDDEN_ACTIONS)
        or authorization.get("consumed") is not False
        or authorization.get("promotion_authorized") is not False
        or authorization.get("permit_required") is not True
        or not isinstance(rollback, dict)
        or set(rollback) != LEGACY_PACKET_ROLLBACK_KEYS
        or rollback.get("ready") is not True
        or rollback.get("scope") != "insights_current_only"
        or rollback.get("shared_nginx_change_allowed") is not False
        or rollback.get("target_release_sha256")
        != expected_current_release_sha256
        or packet.get("side_effects") != packet_contract.SIDE_EFFECTS
    ):
        raise PromotionPermitError("binding_mismatch")
    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise PromotionPermitError("artifacts_unexpected_fields")
    seen_paths: set[str] = set()
    for key, record in artifacts.items():
        if (
            not isinstance(key, str)
            or not isinstance(record, dict)
            or set(record) != {"bytes", "path", "sha256"}
            or isinstance(record.get("bytes"), bool)
            or not isinstance(record.get("bytes"), int)
            or record["bytes"] < 0
            or not isinstance(record.get("path"), str)
            or record["path"] in seen_paths
        ):
            raise PromotionPermitError("artifacts_unexpected_fields")
        seen_paths.add(record["path"])
        try:
            expected_sha = control.require_sha256(
                record.get("sha256"), label=f"artifact_{key}_sha256"
            )
            _, payload = control.read_file(
                root=root,
                path=root / Path(record["path"]),
                label=f"artifact_{key}",
            )
        except control.ReleaseControlError as exc:
            _raise(exc)
        if len(payload) != record["bytes"]:
            raise PromotionPermitError(f"artifact_{key}_bytes_mismatch")
        if control.sha256_bytes(payload) != expected_sha:
            raise PromotionPermitError(f"artifact_{key}_sha256_mismatch")


def _permit_bindings(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize both historical v1 and productized exact-binding v1 permits."""

    nested_packet = value.get("packet")
    nested_authorization = value.get("authorization")
    if nested_packet is not None or nested_authorization is not None:
        if not isinstance(nested_packet, dict) or not isinstance(
            nested_authorization, dict
        ):
            raise PromotionPermitError("authorization_invalid")
        return {
            "authorization_id": value.get("authorization_id"),
            "authorized_actions": nested_authorization.get("authorized_actions"),
            "authorized_at_utc": nested_authorization.get("authorized_at_utc"),
            "authorized_by": nested_authorization.get("authorized_by"),
            "consumed": value.get("consumed"),
            "contract": value.get("contract"),
            "data_release_id": nested_packet.get("data_release_id"),
            "execution_runtime": nested_packet.get("execution_runtime"),
            "expected_current_data_pointer_sha256": nested_packet.get(
                "expected_current_data_pointer_sha256"
            ),
            "expected_current_data_release_id": nested_packet.get(
                "expected_current_data_release_id"
            ),
            "expected_current_release_sha256": nested_packet.get(
                "expected_current_release_sha256"
            ),
            "expires_at_utc": value.get("expires_at_utc"),
            "forbidden_actions": nested_authorization.get("forbidden_actions"),
            "nonce": nested_packet.get("nonce"),
            "owner_confirmation": nested_authorization.get("owner_confirmation"),
            "packet_expires_at_utc": nested_packet.get("expires_at_utc"),
            "packet_id": nested_packet.get("packet_id"),
            "packet_sha256": nested_packet.get("packet_sha256"),
            "release_sha256": nested_packet.get("release_sha256"),
            "scope": value.get("scope"),
            "side_effects": value.get("side_effects"),
            "target_data_pointer_sha256": nested_packet.get(
                "target_data_pointer_sha256"
            ),
        }
    return {
        "authorization_id": value.get("authorization_id"),
        "authorized_actions": value.get("authorized_actions"),
        "authorized_at_utc": value.get("authorized_recorded_at_utc"),
        "authorized_by": value.get("authorized_by"),
        "consumed": value.get("consumed"),
        "contract": None,
        "data_release_id": None,
        "execution_runtime": None,
        "expected_current_data_pointer_sha256": None,
        "expected_current_data_release_id": None,
        "expected_current_release_sha256": None,
        "expires_at_utc": value.get("expires_at_utc"),
        "forbidden_actions": value.get("forbidden_actions"),
        "nonce": None,
        "owner_confirmation": None,
        "packet_expires_at_utc": value.get("expires_at_utc"),
        "packet_id": value.get("packet_id"),
        "packet_sha256": value.get("packet_sha256"),
        "release_sha256": value.get("release_sha256"),
        "scope": value.get("scope"),
        "side_effects": None,
        "target_data_pointer_sha256": None,
    }


def build_promotion_permit(
    *,
    artifact_root: Path,
    packet_artifact_root: Path | None = None,
    packet_path: Path,
    packet_sha256: str,
    release_sha256: str,
    expected_current_release_sha256: str,
    expected_current_data_release_id: str | None = None,
    expected_current_data_pointer_sha256: str | None = None,
    target_data_pointer_sha256: str | None = None,
    authorization_id: str,
    authorized_at_utc: str,
    expires_at_utc: str,
    owner_confirmation: str,
    output: Path,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        packet_root = control.require_root(packet_artifact_root or artifact_root)
        packet_root.relative_to(root)
        expected_packet_sha = control.require_sha256(
            packet_sha256, label="packet_sha256"
        )
        expected_release = control.require_sha256(
            release_sha256, label="release_sha256"
        )
        expected_current = control.require_sha256(
            expected_current_release_sha256,
            label="expected_current_release_sha256",
        )
        authorized_value, authorized_at = control.parse_utc(
            authorized_at_utc, label="authorized_at_utc"
        )
        expires_value, expires_at = control.parse_utc(
            expires_at_utc, label="expires_at_utc"
        )
    except (control.ReleaseControlError, ValueError) as exc:
        _raise(exc)
    if owner_confirmation != OWNER_CONFIRMATION:
        raise PromotionPermitError("owner_confirmation_invalid")
    if AUTHORIZATION_ID_RE.fullmatch(authorization_id) is None:
        raise PromotionPermitError("authorization_id_invalid")
    if expires_at <= authorized_at:
        raise PromotionPermitError("expiry_invalid")

    _, candidate_packet = _packet_document(
        root=packet_root,
        packet_path=packet_path,
        expected_packet_sha256=expected_packet_sha,
    )
    if candidate_packet.get("schema_version") == packet_contract.LEGACY_SCHEMA_VERSION:
        # Historical packets remain reopenable only through the exact read-only
        # allowlist in ``validate_promotion_permit``.  They can never mint a new
        # permit under the v3 data-CAS contract.
        raise PromotionPermitError("artifacts_unexpected_fields")

    try:
        packet_validator.validate_promotion_packet(
            artifact_root=packet_root,
            packet_path=packet_path,
            expected_packet_sha256=expected_packet_sha,
            now_utc=authorized_value,
        )
    except packet_validator.PromotionPacketValidationError as exc:
        _raise(exc)
    try:
        expected_current_data_pointer = control.require_sha256(
            expected_current_data_pointer_sha256,
            label="expected_current_data_pointer_sha256",
        )
        target_data_pointer = control.require_sha256(
            target_data_pointer_sha256,
            label="target_data_pointer_sha256",
        )
    except control.ReleaseControlError as exc:
        _raise(exc)
    if (
        not isinstance(expected_current_data_release_id, str)
        or packet_contract.DATA_RELEASE_RE.fullmatch(expected_current_data_release_id)
        is None
    ):
        raise PromotionPermitError("expected_current_data_release_id_invalid")
    _, packet = _packet_document(
        root=packet_root,
        packet_path=packet_path,
        expected_packet_sha256=expected_packet_sha,
    )
    target = packet.get("target")
    authorization = packet.get("authorization")
    execution_runtime = packet.get("execution_runtime")
    if (
        not isinstance(target, dict)
        or not isinstance(authorization, dict)
        or not isinstance(execution_runtime, dict)
        or set(execution_runtime) != set(packet_contract.EXECUTION_RUNTIME_KEYS)
    ):
        raise PromotionPermitError("binding_mismatch")
    packet_expiry_value, packet_expiry = control.parse_utc(
        packet.get("expires_at_utc"), label="packet_expires_at_utc"
    )
    if (
        target.get("release_sha256") != expected_release
        or target.get("expected_current_release_sha256") != expected_current
        or target.get("expected_current_data_release_id")
        != expected_current_data_release_id
        or target.get("expected_current_data_pointer_sha256")
        != expected_current_data_pointer
        or target.get("target_data_pointer_sha256") != target_data_pointer
        or expires_at > packet_expiry
        or authorization.get("allowed_actions")
        != list(packet_contract.ALLOWED_ACTIONS)
        or authorization.get("forbidden_actions")
        != list(packet_contract.FORBIDDEN_ACTIONS)
    ):
        raise PromotionPermitError("binding_mismatch")

    permit: dict[str, Any] = {
        "authorization": {
            "authorized_actions": list(packet_contract.ALLOWED_ACTIONS),
            "authorized_at_utc": authorized_value,
            "authorized_by": "owner_explicit_confirmation",
            "forbidden_actions": list(packet_contract.FORBIDDEN_ACTIONS),
            "owner_confirmation": OWNER_CONFIRMATION,
        },
        "authorization_id": authorization_id,
        # These flat mirrors preserve the established remote-runner v1 wire
        # contract.  The validator below requires them to match the stronger
        # nested exact-binding contract; they are not independent authority.
        "authorized_actions": list(packet_contract.ALLOWED_ACTIONS),
        "authorized_by": "owner_explicit_confirmation",
        "authorized_recorded_at_utc": authorized_value,
        "consumed": False,
        "contract": PRODUCTIZED_CONTRACT,
        "expires_at_utc": expires_value,
        "forbidden_actions": list(packet_contract.FORBIDDEN_ACTIONS),
        "packet": {
            "data_release_id": target.get("data_release_id"),
            "execution_runtime": {
                key: dict(execution_runtime[key])
                for key in packet_contract.EXECUTION_RUNTIME_KEYS
            },
            "expected_current_data_pointer_sha256": expected_current_data_pointer,
            "expected_current_data_release_id": expected_current_data_release_id,
            "expected_current_release_sha256": expected_current,
            "expires_at_utc": packet_expiry_value,
            "nonce": packet.get("nonce"),
            "packet_id": packet.get("packet_id"),
            "packet_sha256": expected_packet_sha,
            "release_sha256": expected_release,
            "target_data_pointer_sha256": target_data_pointer,
        },
        "packet_id": packet.get("packet_id"),
        "packet_sha256": expected_packet_sha,
        "release_sha256": expected_release,
        "schema_version": SCHEMA_VERSION,
        "scope": "insights_site_and_data_current",
        "side_effects": dict(packet_contract.SIDE_EFFECTS),
        "status": "authorized_unconsumed",
    }
    try:
        publication_status = control.write_immutable(
            root=root,
            output=output,
            value=permit,
            label="promotion_permit",
        )
    except control.ReleaseControlError as exc:
        _raise(exc)
    return {
        "authorization_id": authorization_id,
        "consumed": False,
        "deploy": False,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "expected_current_data_release_id": expected_current_data_release_id,
        "permit_sha256": control.sha256_bytes(canonical_bytes(permit)),
        "release_sha256": expected_release,
        "remote_write": False,
        "schema_version": "reddit_voc_promotion_permit_build_result_v1",
        "status": publication_status,
        "target_data_pointer_sha256": target_data_pointer,
    }


def validate_promotion_permit(
    *,
    artifact_root: Path,
    packet_artifact_root: Path | None = None,
    permit_path: Path,
    expected_permit_sha256: str,
    packet_path: Path,
    expected_packet_sha256: str,
    expected_release_sha256: str,
    expected_current_release_sha256: str,
    expected_current_data_release_id: str | None = None,
    expected_current_data_pointer_sha256: str | None = None,
    target_data_pointer_sha256: str | None = None,
    now_utc: str,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        packet_root = control.require_root(packet_artifact_root or artifact_root)
        packet_root.relative_to(root)
        expected_permit_sha = control.require_sha256(
            expected_permit_sha256, label="expected_permit_sha256"
        )
        expected_packet_sha = control.require_sha256(
            expected_packet_sha256, label="expected_packet_sha256"
        )
        expected_release = control.require_sha256(
            expected_release_sha256, label="expected_release_sha256"
        )
        expected_current = control.require_sha256(
            expected_current_release_sha256,
            label="expected_current_release_sha256",
        )
        now_value, now = control.parse_utc(now_utc, label="now_utc")
        _, _, permit = control.read_json(
            root=root,
            path=permit_path,
            label="promotion_permit",
            expected_mode=0o600,
            expected_sha256=expected_permit_sha,
        )
    except (control.ReleaseControlError, ValueError) as exc:
        _raise(exc)

    bindings = _permit_bindings(permit)
    legacy_compatible = legacy_permit_allowed(
        authorization_id=bindings.get("authorization_id"),
        permit_sha256=expected_permit_sha,
        packet_sha256=expected_packet_sha,
        release_sha256=expected_release,
    )
    permit_authorization = permit.get("authorization")
    permit_packet = permit.get("packet")
    expected_current_data_pointer: str | None = None
    target_data_pointer: str | None = None
    if legacy_compatible:
        if any(
            value is not None
            for value in (
                expected_current_data_release_id,
                expected_current_data_pointer_sha256,
                target_data_pointer_sha256,
            )
        ):
            raise PromotionPermitError("binding_mismatch")
        legacy_flat = bindings.get("contract") is None
        legacy_productized = (
            bindings.get("contract") == LEGACY_PRODUCTIZED_CONTRACT
        )
        if (
            permit.get("schema_version") != SCHEMA_VERSION
            or not (legacy_flat or legacy_productized)
            or (
                legacy_flat
                and (
                    set(permit) != LEGACY_FLAT_PERMIT_KEYS
                    or permit_authorization is not None
                    or permit_packet is not None
                )
            )
            or (
                legacy_productized
                and (
                    set(permit) != PERMIT_KEYS
                    or not isinstance(permit_authorization, dict)
                    or set(permit_authorization) != PERMIT_AUTHORIZATION_KEYS
                    or not isinstance(permit_packet, dict)
                    or set(permit_packet) != LEGACY_PERMIT_PACKET_KEYS
                )
            )
        ):
            raise PromotionPermitError("authorization_invalid")
    else:
        try:
            expected_current_data_pointer = control.require_sha256(
                expected_current_data_pointer_sha256,
                label="expected_current_data_pointer_sha256",
            )
            target_data_pointer = control.require_sha256(
                target_data_pointer_sha256,
                label="target_data_pointer_sha256",
            )
        except control.ReleaseControlError as exc:
            _raise(exc)
        if (
            not isinstance(expected_current_data_release_id, str)
            or packet_contract.DATA_RELEASE_RE.fullmatch(
                expected_current_data_release_id
            )
            is None
        ):
            raise PromotionPermitError("expected_current_data_release_id_invalid")
        if (
            permit.get("schema_version") != SCHEMA_VERSION
            or set(permit) != PERMIT_KEYS
            or not isinstance(permit_authorization, dict)
            or set(permit_authorization) != PERMIT_AUTHORIZATION_KEYS
            or not isinstance(permit_packet, dict)
            or set(permit_packet) != PERMIT_PACKET_KEYS
        ):
            raise PromotionPermitError("authorization_invalid")

    try:
        expires_value, expires_at = control.parse_utc(
            bindings.get("expires_at_utc"), label="expires_at_utc"
        )
        authorized_value, authorized_at = control.parse_utc(
            bindings.get("authorized_at_utc"), label="authorized_at_utc"
        )
    except control.ReleaseControlError as exc:
        _raise(exc)
    if now < authorized_at:
        raise PromotionPermitError("authorization_not_yet_valid")
    if now >= expires_at:
        raise PromotionPermitError("authorization_expired")
    if bindings.get("consumed") is not False:
        raise PromotionPermitError("authorization_invalid")
    expected_scope = (
        "insights_only" if legacy_compatible else "insights_site_and_data_current"
    )
    expected_actions = (
        packet_contract.LEGACY_ALLOWED_ACTIONS
        if legacy_compatible
        else packet_contract.ALLOWED_ACTIONS
    )
    if (
        bindings.get("scope") != expected_scope
        or (
            not legacy_compatible
            and bindings.get("contract") != PRODUCTIZED_CONTRACT
        )
        or bindings.get("authorized_actions") != list(expected_actions)
        or bindings.get("forbidden_actions") != list(packet_contract.FORBIDDEN_ACTIONS)
        or bindings.get("packet_sha256") != expected_packet_sha
        or bindings.get("release_sha256") != expected_release
        or (
            not legacy_compatible
            and (
                bindings.get("expected_current_data_release_id")
                != expected_current_data_release_id
                or bindings.get("expected_current_data_pointer_sha256")
                != expected_current_data_pointer
                or bindings.get("target_data_pointer_sha256")
                != target_data_pointer
                or not isinstance(bindings.get("execution_runtime"), dict)
            )
        )
    ):
        raise PromotionPermitError("binding_mismatch")

    _, packet = _packet_document(
        root=packet_root,
        packet_path=packet_path,
        expected_packet_sha256=expected_packet_sha,
    )
    if legacy_compatible:
        _validate_exact_legacy_packet(
            root=packet_root,
            packet=packet,
            expected_release_sha256=expected_release,
            expected_current_release_sha256=expected_current,
        )
    else:
        try:
            packet_validator.validate_promotion_packet(
                artifact_root=packet_root,
                packet_path=packet_path,
                expected_packet_sha256=expected_packet_sha,
                now_utc=now_value,
            )
        except packet_validator.PromotionPacketValidationError as exc:
            _raise(exc)
    target = packet.get("target")
    packet_authorization = packet.get("authorization")
    if not isinstance(target, dict) or not isinstance(packet_authorization, dict):
        raise PromotionPermitError("binding_mismatch")
    packet_expiry_value, packet_expiry = control.parse_utc(
        packet.get("expires_at_utc"), label="packet_expires_at_utc"
    )
    if (
        target.get("release_sha256") != expected_release
        or target.get("expected_current_release_sha256") != expected_current
        or (
            not legacy_compatible
            and (
                target.get("expected_current_data_release_id")
                != expected_current_data_release_id
                or target.get("expected_current_data_pointer_sha256")
                != expected_current_data_pointer
                or target.get("target_data_pointer_sha256") != target_data_pointer
                or bindings.get("execution_runtime")
                != packet.get("execution_runtime")
            )
        )
        or packet.get("packet_id") != bindings.get("packet_id")
        or expires_at > packet_expiry
        or packet_authorization.get("allowed_actions")
        != bindings.get("authorized_actions")
        or packet_authorization.get("forbidden_actions")
        != bindings.get("forbidden_actions")
    ):
        raise PromotionPermitError("binding_mismatch")
    if legacy_compatible and bindings.get("contract") is None:
        authorization_text = permit.get("user_authorization_text")
        if (
            bindings.get("authorized_by") != "owner_explicit_chat_confirmation"
            or not isinstance(authorization_text, str)
            or not authorization_text
            or permit.get("packet_id") != bindings.get("packet_id")
            or permit.get("packet_sha256") != expected_packet_sha
            or permit.get("release_sha256") != expected_release
        ):
            raise PromotionPermitError("binding_mismatch")
    else:
        if (
            bindings.get("authorized_by") != "owner_explicit_confirmation"
            or bindings.get("owner_confirmation") != OWNER_CONFIRMATION
            or bindings.get("expected_current_release_sha256") != expected_current
            or bindings.get("data_release_id") != target.get("data_release_id")
            or bindings.get("nonce") != packet.get("nonce")
            or bindings.get("packet_expires_at_utc") != packet_expiry_value
            or bindings.get("side_effects") != packet_contract.SIDE_EFFECTS
            or permit.get("status") != "authorized_unconsumed"
            or permit.get("authorized_actions")
            != bindings.get("authorized_actions")
            or permit.get("forbidden_actions")
            != bindings.get("forbidden_actions")
            or permit.get("authorized_by") != bindings.get("authorized_by")
            or permit.get("authorized_recorded_at_utc") != authorized_value
            or permit.get("packet_id") != bindings.get("packet_id")
            or permit.get("packet_sha256") != expected_packet_sha
            or permit.get("release_sha256") != expected_release
        ):
            raise PromotionPermitError("binding_mismatch")

    result = {
        "authorization_id": bindings.get("authorization_id"),
        "authorized_at_utc": authorized_value,
        "consumed": False,
        "deploy": False,
        "expires_at_utc": expires_value,
        "legacy_compatible": legacy_compatible,
        "packet_sha256": expected_packet_sha,
        "permit_sha256": expected_permit_sha,
        "release_sha256": expected_release,
        "remote_write": False,
        "schema_version": "reddit_voc_promotion_permit_validation_result_v1",
        "status": "passed",
    }
    if not legacy_compatible:
        result.update(
            {
                "expected_current_data_pointer_sha256": (
                    expected_current_data_pointer
                ),
                "expected_current_data_release_id": (
                    expected_current_data_release_id
                ),
                "target_data_pointer_sha256": target_data_pointer,
            }
        )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--packet-artifact-root", type=Path)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--expected-current-release-sha256", required=True)
    parser.add_argument("--expected-current-data-release-id", required=True)
    parser.add_argument("--expected-current-data-pointer-sha256", required=True)
    parser.add_argument("--target-data-pointer-sha256", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument(
        "--authorized-at-utc",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    parser.add_argument("--expires-at-utc", required=True)
    parser.add_argument("--owner-confirmation", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = build_promotion_permit(
            artifact_root=args.artifact_root,
            packet_artifact_root=args.packet_artifact_root,
            packet_path=args.packet,
            packet_sha256=args.packet_sha256,
            release_sha256=args.release_sha256,
            expected_current_release_sha256=args.expected_current_release_sha256,
            expected_current_data_release_id=args.expected_current_data_release_id,
            expected_current_data_pointer_sha256=(
                args.expected_current_data_pointer_sha256
            ),
            target_data_pointer_sha256=args.target_data_pointer_sha256,
            authorization_id=args.authorization_id,
            authorized_at_utc=args.authorized_at_utc,
            expires_at_utc=args.expires_at_utc,
            owner_confirmation=args.owner_confirmation,
            output=args.output,
        )
    except PromotionPermitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
