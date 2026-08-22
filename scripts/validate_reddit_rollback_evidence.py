#!/usr/bin/env python3
"""Validate prior Reddit VOC deployment evidence for a release rollback.

Accepted evidence is either the historical line-based container receipt, the
current canonical ``promotion-*.json`` remote receipt, or a bound public
production acceptance receipt.  This command is local and read-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_production_acceptance as acceptance_contract
    from scripts import reddit_release_control as control
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_production_acceptance as acceptance_contract
    import reddit_release_control as control


REMOTE_SCHEMA_VERSION_V1 = "reddit_voc_remote_promotion_receipt_v1"
REMOTE_SCHEMA_VERSION_V2 = "reddit_voc_remote_promotion_receipt_v2"
REMOTE_STATUS = "promoted_pending_public_acceptance"
HISTORICAL_REMOTE_V1_RECEIPTS = {
    "0a672425654533326bf183e2cf9ab86d19957450d659d62f0d30ff34b988e819": (
        "e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240"
    ),
    "4460f75aff7e7979c491a3c59b4419bbf8d886dec0ad62c6a4b6998be54c3cfd": (
        "e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b"
    ),
    "6f8d263ca21d7779ffd1344c76f64710f052b1637f083c7d0f72cf44a190e969": (
        "130e228cdf7e9d936a862b5a992533e21ae2d3df01b90889d1b5a0b9ec8571ad"
    ),
    "c4e7d2f01b186bfb2313cf5176e388c0c5e6d8ba795e4fcaf15709ffdf6e597a": (
        "9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5"
    ),
    "dbab71ee93144b48b88d8c2afedc2d8af02ac0ad3b13be815be9e665524f6373": (
        "6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2"
    ),
    "f34148b00c16d24a1a7e364f3f6469474a6dbf82c651fe57d89db7427035c49c": (
        "ebaa5443906628145f9fbe05777d4218b1ec6d53b78e9d7f4f86fa8fbe9df313"
    ),
}
HISTORICAL_LEGACY_CONTAINER_RECEIPTS: dict[str, str] = {}


class RollbackEvidenceError(ValueError):
    """A rollback target lacks exact prior L4 deployment evidence."""


def _fail(message: str) -> NoReturn:
    raise RollbackEvidenceError(message)


def validate_remote_promotion_document(
    value: Mapping[str, Any], *, expected_release_sha256: str,
    receipt_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        expected_release = control.require_sha256(
            expected_release_sha256, label="expected_release_sha256"
        )
        release_sha = control.require_sha256(
            value.get("release_sha256"), label="release_sha256"
        )
        previous_sha = control.require_sha256(
            value.get("previous_release_sha256"), label="previous_release_sha256"
        )
        packet_sha = control.require_sha256(
            value.get("packet_sha256"), label="packet_sha256"
        )
        permit_sha = control.require_sha256(
            value.get("permit_sha256"), label="permit_sha256"
        )
        control.require_sha256(value.get("collector_id"), label="collector_id")
        control.require_sha256(value.get("translation_id"), label="translation_id")
        control.require_sha256(value.get("cron_sha256"), label="cron_sha256")
        control.require_sha256(value.get("nginx_sha256"), label="nginx_sha256")
        generated_value, _ = control.parse_utc(
            value.get("generated_at_utc"), label="generated_at_utc"
        )
    except control.ReleaseControlError as exc:
        raise RollbackEvidenceError(str(exc)) from exc
    schema_version = value.get("schema_version")
    if (
        schema_version not in {REMOTE_SCHEMA_VERSION_V1, REMOTE_SCHEMA_VERSION_V2}
        or value.get("status") != REMOTE_STATUS
        or value.get("evidence_grade") != "L4-authorized-live"
    ):
        _fail("remote_promotion_contract_invalid")
    if (
        schema_version == REMOTE_SCHEMA_VERSION_V1
        and HISTORICAL_REMOTE_V1_RECEIPTS.get(str(receipt_sha256)) != release_sha
    ):
        _fail("remote_promotion_v1_not_exactly_allowlisted")
    if release_sha != expected_release or previous_sha == release_sha:
        _fail("remote_promotion_release_binding_mismatch")
    if (
        value.get("candidate_18339_smoke") is not True
        or value.get("production_container_smoke") is not True
        or value.get("collector_restart_count") != 0
        or value.get("translation_restart_count") != 0
        or value.get("database_write") is not False
        or value.get("live_send") is not False
        or value.get("provider_call") is not False
        or value.get("shared_nginx_modified") is not False
    ):
        _fail("remote_promotion_invariant_invalid")
    data_release_id = value.get("data_release_id")
    if not isinstance(data_release_id, str) or not data_release_id.startswith(
        "reddit_voc_release_"
    ):
        _fail("remote_promotion_data_release_invalid")
    result: dict[str, Any] = {
        "data_release_id": data_release_id,
        "generated_at_utc": generated_value,
        "packet_sha256": packet_sha,
        "permit_sha256": permit_sha,
        "previous_release_sha256": previous_sha,
        "release_sha256": release_sha,
        "status": "passed",
    }
    if schema_version == REMOTE_SCHEMA_VERSION_V2:
        previous_data_release_id = value.get("previous_data_release_id")
        if (
            not isinstance(previous_data_release_id, str)
            or not previous_data_release_id.startswith("reddit_voc_release_")
            or previous_data_release_id == data_release_id
        ):
            _fail("remote_promotion_previous_data_release_invalid")
        try:
            data_pointer_sha = control.require_sha256(
                value.get("data_pointer_sha256"), label="data_pointer_sha256"
            )
            data_inventory_sha = control.require_sha256(
                value.get("data_inventory_sha256"), label="data_inventory_sha256"
            )
            previous_data_pointer_sha = control.require_sha256(
                value.get("previous_data_pointer_sha256"),
                label="previous_data_pointer_sha256",
            )
        except control.ReleaseControlError as exc:
            raise RollbackEvidenceError(str(exc)) from exc
        if data_pointer_sha == previous_data_pointer_sha:
            _fail("remote_promotion_data_pointer_transition_invalid")
        try:
            data_file_count = control.require_nonnegative_int(
                value.get("data_file_count"), label="data_file_count"
            )
            data_total_bytes = control.require_nonnegative_int(
                value.get("data_total_bytes"), label="data_total_bytes"
            )
        except control.ReleaseControlError as exc:
            raise RollbackEvidenceError(str(exc)) from exc
        if data_file_count == 0 or data_total_bytes == 0:
            _fail("remote_promotion_data_inventory_invalid")
        if (
            value.get("four_exports_complete") is not False
            or value.get("candidate_exports_validation_bound") is not True
        ):
            _fail("remote_promotion_data_projection_invalid")
        result.update(
            {
                "data_pointer_sha256": data_pointer_sha,
                "data_inventory_sha256": data_inventory_sha,
                "data_file_count": data_file_count,
                "data_total_bytes": data_total_bytes,
                "previous_data_pointer_sha256": previous_data_pointer_sha,
                "previous_data_release_id": previous_data_release_id,
                "schema_version": REMOTE_SCHEMA_VERSION_V2,
            }
        )
    else:
        result["schema_version"] = REMOTE_SCHEMA_VERSION_V1
    return result


def _validate_legacy_container_receipt(
    payload: bytes, *, expected_release_sha256: str
) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise RollbackEvidenceError("legacy_receipt_encoding_invalid") from exc
    lines = text.splitlines()
    if len(lines) != len(set(lines)):
        _fail("legacy_receipt_duplicate_line")
    expected_lines = {
        "evidence_grade=L4-authorized-live",
        f"release_sha={expected_release_sha256}",
        "release_marker_verified=true",
        "image_dist_checksums_verified=true",
        "collector_id_unchanged=true",
        "nginx_unchanged=true",
        "cron_unchanged=true",
    }
    if not expected_lines.issubset(lines):
        _fail("legacy_container_receipt_invalid")
    return {
        "release_sha256": expected_release_sha256,
        "status": "passed",
    }


def validate_rollback_evidence(
    *,
    artifact_root: Path,
    expected_release_sha256: str,
    promotion_receipt_path: Path | None = None,
    expected_promotion_receipt_sha256: str | None = None,
    acceptance_receipt_path: Path | None = None,
    expected_acceptance_receipt_sha256: str | None = None,
    legacy_container_receipt_path: Path | None = None,
    expected_legacy_container_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    sources = (
        promotion_receipt_path is not None,
        acceptance_receipt_path is not None,
        legacy_container_receipt_path is not None,
    )
    if not any(sources):
        _fail("rollback_evidence_required")
    try:
        root = control.require_root(artifact_root)
        expected_release = control.require_sha256(
            expected_release_sha256, label="expected_release_sha256"
        )
    except control.ReleaseControlError as exc:
        raise RollbackEvidenceError(str(exc)) from exc
    promotion: dict[str, Any] | None = None
    promotion_sha: str | None = None
    acceptance: dict[str, Any] | None = None
    evidence_types: list[str] = []

    if promotion_receipt_path is not None:
        if expected_promotion_receipt_sha256 is None:
            _fail("expected_promotion_receipt_sha256_required")
        try:
            _, payload, value = control.read_json(
                root=root,
                path=promotion_receipt_path,
                label="remote_promotion_receipt",
                expected_mode=0o600,
                expected_sha256=expected_promotion_receipt_sha256,
            )
        except control.ReleaseControlError as exc:
            raise RollbackEvidenceError(str(exc)) from exc
        promotion = validate_remote_promotion_document(
            value,
            expected_release_sha256=expected_release,
            receipt_sha256=control.sha256_bytes(payload),
        )
        promotion_sha = control.sha256_bytes(payload)
        evidence_types.append("remote_promotion_receipt")

    if acceptance_receipt_path is not None:
        if expected_acceptance_receipt_sha256 is None:
            _fail("expected_acceptance_receipt_sha256_required")
        expected_acceptance_sha = expected_acceptance_receipt_sha256
        try:
            acceptance = acceptance_contract.validate_production_acceptance(
                artifact_root=root,
                receipt_path=acceptance_receipt_path,
                expected_receipt_sha256=expected_acceptance_sha,
                expected_release_sha256=expected_release,
                expected_remote_promotion_receipt_sha256=promotion_sha,
            )
        except acceptance_contract.ProductionAcceptanceError as exc:
            raise RollbackEvidenceError(str(exc)) from exc
        evidence_types.append("production_acceptance_receipt")

    if promotion is not None and acceptance is not None:
        if (
            acceptance["packet_sha256"] != promotion["packet_sha256"]
            or acceptance["permit_sha256"] != promotion["permit_sha256"]
            or acceptance["data_release_id"] != promotion["data_release_id"]
            or acceptance["rollback_target_release_sha256"]
            != promotion["previous_release_sha256"]
        ):
            _fail("promotion_acceptance_binding_mismatch")
        if promotion["schema_version"] == REMOTE_SCHEMA_VERSION_V2:
            if (
                acceptance.get("data_pointer_sha256")
                != promotion["data_pointer_sha256"]
                or acceptance.get("data_inventory_sha256")
                != promotion["data_inventory_sha256"]
                or acceptance.get("data_file_count")
                != promotion["data_file_count"]
                or acceptance.get("data_total_bytes")
                != promotion["data_total_bytes"]
                or acceptance.get("rollback_target_data_release_id")
                != promotion["previous_data_release_id"]
                or acceptance.get("rollback_target_data_pointer_sha256")
                != promotion["previous_data_pointer_sha256"]
            ):
                _fail("promotion_acceptance_data_binding_mismatch")

    dual_promotion = (
        promotion is not None
        and promotion.get("schema_version") == REMOTE_SCHEMA_VERSION_V2
    )
    dual_acceptance = (
        acceptance is not None
        and acceptance.get("schema_version")
        == "reddit_voc_production_acceptance_validation_result_v2"
    )
    if dual_promotion and not dual_acceptance:
        _fail("dual_rollback_requires_bound_v2_acceptance")
    if dual_acceptance:
        assert acceptance is not None
        if promotion is None:
            _fail("dual_rollback_requires_v2_promotion_receipt")
        if acceptance.get("upstream_evidence_reopened") is not True:
            _fail("dual_rollback_acceptance_upstream_not_reopened")

    if legacy_container_receipt_path is not None:
        if expected_legacy_container_receipt_sha256 is None:
            _fail("expected_legacy_container_receipt_sha256_required")
        try:
            _, payload = control.read_file(
                root=root,
                path=legacy_container_receipt_path,
                label="legacy_container_deployment_receipt",
            )
            expected_legacy_sha = control.require_sha256(
                expected_legacy_container_receipt_sha256,
                label="expected_legacy_container_receipt_sha256",
            )
        except control.ReleaseControlError as exc:
            raise RollbackEvidenceError(str(exc)) from exc
        if control.sha256_bytes(payload) != expected_legacy_sha:
            _fail("legacy_container_receipt_sha256_mismatch")
        if (
            HISTORICAL_LEGACY_CONTAINER_RECEIPTS.get(expected_legacy_sha)
            != expected_release
        ):
            _fail("legacy_container_receipt_not_exactly_allowlisted")
        _validate_legacy_container_receipt(
            payload, expected_release_sha256=expected_release
        )
        evidence_types.append("legacy_container_deployment_receipt")

    return {
        "deploy": False,
        "evidence_types": evidence_types,
        "release_sha256": expected_release,
        "remote_write": False,
        "schema_version": "reddit_voc_rollback_evidence_validation_result_v1",
        "status": "passed_local_read_only",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--promotion-receipt", type=Path)
    parser.add_argument("--expected-promotion-receipt-sha256")
    parser.add_argument("--acceptance-receipt", type=Path)
    parser.add_argument("--expected-acceptance-receipt-sha256")
    parser.add_argument("--legacy-container-receipt", type=Path)
    parser.add_argument("--expected-legacy-container-receipt-sha256")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_rollback_evidence(
            artifact_root=args.artifact_root,
            expected_release_sha256=args.expected_release_sha256,
            promotion_receipt_path=args.promotion_receipt,
            expected_promotion_receipt_sha256=(
                args.expected_promotion_receipt_sha256
            ),
            acceptance_receipt_path=args.acceptance_receipt,
            expected_acceptance_receipt_sha256=(
                args.expected_acceptance_receipt_sha256
            ),
            legacy_container_receipt_path=args.legacy_container_receipt,
            expected_legacy_container_receipt_sha256=(
                args.expected_legacy_container_receipt_sha256
            ),
        )
    except RollbackEvidenceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
