#!/usr/bin/env python3
"""Seal one successful Reddit VOC promotion as an immutable consumption receipt.

The builder reopens the exact packet, unconsumed permit, and public production
acceptance receipt.  It never mutates the permit and has no remote execution
capability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_production_acceptance as acceptance_contract
    from scripts import build_reddit_promotion_packet as packet_contract
    from scripts import build_reddit_promotion_permit as permit_contract
    from scripts import reddit_release_control as control
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_production_acceptance as acceptance_contract
    import build_reddit_promotion_packet as packet_contract
    import build_reddit_promotion_permit as permit_contract
    import reddit_release_control as control


SCHEMA_VERSION = "reddit_voc_promotion_consumption_receipt_v1"
SCHEMA_VERSION_V2 = "reddit_voc_promotion_consumption_receipt_v2"
STATUS = "consumed_successfully"
SUCCESS_ACTIONS = tuple(
    action
    for action in packet_contract.ALLOWED_ACTIONS
    if not action.startswith("rollback_only_")
)
LEGACY_SUCCESS_ACTIONS = (
    "read_only_remote_preflight",
    "upload_exact_release_artifacts_to_isolated_directory",
    "verify_exact_remote_artifact_hashes",
    "load_exact_linux_amd64_image",
    "start_only_reddit_voc_insights_candidate_18339",
    "run_candidate_runtime_smoke",
    "compare_and_swap_only_insights_current",
    "run_public_production_acceptance",
)
SIDE_EFFECTS = {
    "collector_modified": False,
    "cron_modified": False,
    "database_write": False,
    "dns_modified": False,
    "live_send": False,
    "other_docker_environment_modified": False,
    "provider_call": False,
    "schedule_change": False,
    "shared_nginx_modified": False,
    "tls_modified": False,
}
AUTHORIZATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
HISTORICAL_V1_RECEIPT_SHA256S = frozenset(
    {
        "20d4d05d832e42427ec37c6e26b1e3d68434a618f1e1b286cdb55503c0259058",
        "2ef71fab8e1330d51f5c5bca6b732739c883da110c2d38d0cb339c59827c4599",
        "5904305d34426abb3b8dc62629bde5f480cffb9991f10c7ce42d09cf51ba1e5c",
        "684f39057ec8017a30a61b18b8beb419dc24bdf6970d981f22e64bc5278fa1ba",
        "9c0f26442fe0ab65c301232f7cce6337f3d96162eacab4dae50e28167d564fc5",
        "ad73e0a147a0abea22b8d372581dc5efe585dc1bc80db1ee0e905864955689be",
        "de757bd20e2fa3a6571c07c11b1f8106570020ef7ff6fe3dac5a38cca469323c",
    }
)


class PromotionConsumptionError(ValueError):
    """The consumption receipt is not bound to one accepted promotion."""


def _fail(message: str) -> NoReturn:
    raise PromotionConsumptionError(message)


def _object(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label}_not_object")
    return value


def _relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        _fail(f"{label}_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        _fail(f"{label}_invalid")
    return value


def validate_promotion_consumption_document(
    value: Mapping[str, Any],
    *,
    expected_packet_sha256: str | None = None,
    expected_permit_sha256: str | None = None,
    expected_release_sha256: str | None = None,
    expected_remote_promotion_receipt_sha256: str | None = None,
    expected_acceptance_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    if schema_version not in {SCHEMA_VERSION, SCHEMA_VERSION_V2} or value.get("status") != STATUS:
        _fail("consumption_contract_invalid")
    authorization_id = value.get("authorization_id")
    if (
        not isinstance(authorization_id, str)
        or AUTHORIZATION_ID_RE.fullmatch(authorization_id) is None
    ):
        _fail("authorization_id_invalid")
    try:
        consumed_value, _ = control.parse_utc(
            value.get("consumed_at_utc"), label="consumed_at_utc"
        )
        packet_sha = control.require_sha256(
            value.get("packet_sha256"), label="packet_sha256"
        )
        permit_sha = control.require_sha256(
            value.get("permit_sha256"), label="permit_sha256"
        )
        release_sha = control.require_sha256(
            value.get("release_sha256"), label="release_sha256"
        )
        remote_sha = control.require_sha256(
            value.get("remote_promotion_receipt_sha256"),
            label="remote_promotion_receipt_sha256",
        )
    except control.ReleaseControlError as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    actions_performed = value.get("actions_performed")
    expected_actions = (
        LEGACY_SUCCESS_ACTIONS
        if schema_version == SCHEMA_VERSION
        else SUCCESS_ACTIONS
    )
    if (
        not isinstance(actions_performed, list)
        or tuple(actions_performed) != tuple(expected_actions)
    ):
        _fail("actions_performed_invalid")
    if value.get("forbidden_actions_performed") != []:
        _fail("forbidden_actions_performed_invalid")
    if value.get("side_effects") != SIDE_EFFECTS:
        _fail("side_effects_invalid")

    data_binding: dict[str, Any] | None = None
    if schema_version == SCHEMA_VERSION and "data_binding" in value:
        _fail("legacy_consumption_data_binding_forbidden")
    if schema_version == SCHEMA_VERSION_V2:
        binding = _object(value.get("data_binding"), label="data_binding")
        expected_binding_keys = {
            "current_data_file_count",
            "current_data_inventory_sha256",
            "current_data_pointer_sha256",
            "current_data_release_id",
            "current_data_total_bytes",
            "previous_data_pointer_sha256",
            "previous_data_release_id",
        }
        if set(binding) != expected_binding_keys:
            _fail("data_binding_unexpected_fields")
        for name in ("current_data_release_id", "previous_data_release_id"):
            item = binding.get(name)
            if (
                not isinstance(item, str)
                or packet_contract.DATA_RELEASE_RE.fullmatch(item) is None
            ):
                _fail(f"{name}_invalid")
        try:
            for name in (
                "current_data_inventory_sha256",
                "current_data_pointer_sha256",
                "previous_data_pointer_sha256",
            ):
                control.require_sha256(binding.get(name), label=name)
            for name in ("current_data_file_count", "current_data_total_bytes"):
                count = control.require_nonnegative_int(binding.get(name), label=name)
                if count == 0:
                    _fail(f"{name}_invalid")
        except control.ReleaseControlError as exc:
            raise PromotionConsumptionError(str(exc)) from exc
        if (
            binding["current_data_release_id"]
            == binding["previous_data_release_id"]
            or binding["current_data_pointer_sha256"]
            == binding["previous_data_pointer_sha256"]
        ):
            _fail("data_binding_transition_invalid")
        data_binding = dict(binding)

    acceptance = _object(value.get("production_acceptance"), label="production_acceptance")
    acceptance_path = _relative_path(
        acceptance.get("path"), label="production_acceptance_path"
    )
    try:
        acceptance_sha = control.require_sha256(
            acceptance.get("sha256"), label="production_acceptance_sha256"
        )
    except control.ReleaseControlError as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    if acceptance.get("status") != acceptance_contract.STATUS:
        _fail("production_acceptance_status_invalid")

    expected_bindings = (
        (packet_sha, expected_packet_sha256, "packet_binding_mismatch"),
        (permit_sha, expected_permit_sha256, "permit_binding_mismatch"),
        (release_sha, expected_release_sha256, "release_binding_mismatch"),
        (
            remote_sha,
            expected_remote_promotion_receipt_sha256,
            "remote_promotion_receipt_binding_mismatch",
        ),
        (
            acceptance_sha,
            expected_acceptance_receipt_sha256,
            "production_acceptance_binding_mismatch",
        ),
    )
    for observed, expected, label in expected_bindings:
        if expected is None:
            continue
        try:
            normalized = control.require_sha256(expected, label=f"expected_{label}")
        except control.ReleaseControlError as exc:
            raise PromotionConsumptionError(str(exc)) from exc
        if observed != normalized:
            _fail(label)

    result: dict[str, Any] = {
        "acceptance_receipt_path": acceptance_path,
        "acceptance_receipt_sha256": acceptance_sha,
        "authorization_id": authorization_id,
        "consumed_at_utc": consumed_value,
        "packet_sha256": packet_sha,
        "permit_sha256": permit_sha,
        "release_sha256": release_sha,
        "remote_promotion_receipt_sha256": remote_sha,
        "schema_version": "reddit_voc_promotion_consumption_validation_result_v1",
        "status": "passed",
    }
    if data_binding is not None:
        result["data_binding"] = data_binding
        result["schema_version"] = "reddit_voc_promotion_consumption_validation_result_v2"
    return result


def validate_promotion_consumption(
    *,
    artifact_root: Path,
    receipt_path: Path,
    expected_receipt_sha256: str,
    expected_packet_sha256: str | None = None,
    expected_permit_sha256: str | None = None,
    expected_release_sha256: str | None = None,
    expected_remote_promotion_receipt_sha256: str | None = None,
    expected_acceptance_receipt_sha256: str | None = None,
    reopen_acceptance: bool = True,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        _, payload, value = control.read_json(
            root=root,
            path=receipt_path,
            label="promotion_consumption_receipt",
            expected_mode=0o600,
            expected_sha256=expected_receipt_sha256,
        )
    except control.ReleaseControlError as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    result = validate_promotion_consumption_document(
        value,
        expected_packet_sha256=expected_packet_sha256,
        expected_permit_sha256=expected_permit_sha256,
        expected_release_sha256=expected_release_sha256,
        expected_remote_promotion_receipt_sha256=(
            expected_remote_promotion_receipt_sha256
        ),
        expected_acceptance_receipt_sha256=expected_acceptance_receipt_sha256,
    )
    receipt_sha256 = control.sha256_bytes(payload)
    if (
        result.get("schema_version")
        == "reddit_voc_promotion_consumption_validation_result_v1"
        and receipt_sha256 not in HISTORICAL_V1_RECEIPT_SHA256S
    ):
        _fail("legacy_v1_consumption_not_exactly_allowlisted")
    if (
        result.get("schema_version")
        == "reddit_voc_promotion_consumption_validation_result_v2"
        and not reopen_acceptance
    ):
        _fail("v2_consumption_requires_reopened_acceptance")
    if reopen_acceptance:
        acceptance_path = root.joinpath(
            *PurePosixPath(result["acceptance_receipt_path"]).parts
        )
        try:
            accepted = acceptance_contract.validate_production_acceptance(
                artifact_root=root,
                receipt_path=acceptance_path,
                expected_receipt_sha256=result["acceptance_receipt_sha256"],
                expected_release_sha256=result["release_sha256"],
                expected_packet_sha256=result["packet_sha256"],
                expected_permit_sha256=result["permit_sha256"],
                expected_remote_promotion_receipt_sha256=result[
                    "remote_promotion_receipt_sha256"
                ],
            )
        except acceptance_contract.ProductionAcceptanceError as exc:
            raise PromotionConsumptionError(str(exc)) from exc
        _, accepted_at = control.parse_utc(
            accepted["accepted_at_utc"], label="accepted_at_utc"
        )
        _, consumed_at = control.parse_utc(
            result["consumed_at_utc"], label="consumed_at_utc"
        )
        if consumed_at < accepted_at:
            _fail("consumption_precedes_acceptance")
        if (
            result.get("schema_version")
            == "reddit_voc_promotion_consumption_validation_result_v2"
        ):
            if (
                accepted.get("schema_version")
                != "reddit_voc_production_acceptance_validation_result_v2"
                or accepted.get("upstream_evidence_reopened") is not True
            ):
                _fail("v2_consumption_acceptance_evidence_not_reopened")
            expected_data_binding = {
                "current_data_file_count": accepted["data_file_count"],
                "current_data_inventory_sha256": accepted[
                    "data_inventory_sha256"
                ],
                "current_data_pointer_sha256": accepted["data_pointer_sha256"],
                "current_data_release_id": accepted["data_release_id"],
                "current_data_total_bytes": accepted["data_total_bytes"],
                "previous_data_pointer_sha256": accepted[
                    "rollback_target_data_pointer_sha256"
                ],
                "previous_data_release_id": accepted[
                    "rollback_target_data_release_id"
                ],
            }
            if result.get("data_binding") != expected_data_binding:
                _fail("v2_consumption_data_binding_mismatch")
        elif (
            accepted.get("schema_version")
            != "reddit_voc_production_acceptance_validation_result_v1"
        ):
            _fail("legacy_consumption_acceptance_schema_mismatch")
    result["acceptance_reopened"] = reopen_acceptance
    result["consumption_receipt_sha256"] = receipt_sha256
    return result


def build_promotion_consumption(
    *,
    artifact_root: Path,
    packet_artifact_root: Path | None = None,
    packet_path: Path,
    packet_sha256: str,
    permit_path: Path,
    permit_sha256: str,
    acceptance_receipt_path: Path,
    acceptance_receipt_sha256: str,
    release_sha256: str,
    expected_current_release_sha256: str,
    expected_current_data_release_id: str,
    expected_current_data_pointer_sha256: str,
    target_data_pointer_sha256: str,
    consumed_at_utc: str,
    output: Path,
) -> dict[str, Any]:
    try:
        root = control.require_root(artifact_root)
        packet_sha = control.require_sha256(packet_sha256, label="packet_sha256")
        permit_sha = control.require_sha256(permit_sha256, label="permit_sha256")
        acceptance_sha = control.require_sha256(
            acceptance_receipt_sha256, label="acceptance_receipt_sha256"
        )
        release_sha = control.require_sha256(
            release_sha256, label="release_sha256"
        )
        consumed_value, _ = control.parse_utc(
            consumed_at_utc, label="consumed_at_utc"
        )
    except control.ReleaseControlError as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    try:
        acceptance = acceptance_contract.validate_production_acceptance(
            artifact_root=root,
            receipt_path=acceptance_receipt_path,
            expected_receipt_sha256=acceptance_sha,
            expected_release_sha256=release_sha,
            expected_packet_sha256=packet_sha,
            expected_permit_sha256=permit_sha,
        )
        acceptance_relative, _, _ = control.read_json(
            root=root,
            path=acceptance_receipt_path,
            label="production_acceptance_receipt",
            expected_mode=0o600,
            expected_sha256=acceptance_sha,
        )
        _, _, permit = control.read_json(
            root=root,
            path=permit_path,
            label="promotion_permit",
            expected_mode=0o600,
            expected_sha256=permit_sha,
        )
    except (
        acceptance_contract.ProductionAcceptanceError,
        control.ReleaseControlError,
    ) as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    accepted_value, accepted_at = control.parse_utc(
        acceptance["accepted_at_utc"], label="accepted_at_utc"
    )
    _, consumed_at = control.parse_utc(consumed_value, label="consumed_at_utc")
    if consumed_at < accepted_at:
        _fail("consumption_precedes_acceptance")
    # The permit authorizes the production actions through public acceptance;
    # the immutable consumption document is only an after-the-fact seal.  A
    # delayed/crash-recovered seal must therefore validate the permit at the
    # already reopened acceptance time, while still requiring the seal time to
    # follow acceptance.  This preserves expiry for every authorized action
    # without making a successful transaction impossible to record later.
    try:
        permit_validation = permit_contract.validate_promotion_permit(
            artifact_root=root,
            packet_artifact_root=packet_artifact_root,
            permit_path=permit_path,
            expected_permit_sha256=permit_sha,
            packet_path=packet_path,
            expected_packet_sha256=packet_sha,
            expected_release_sha256=release_sha,
            expected_current_release_sha256=expected_current_release_sha256,
            expected_current_data_release_id=expected_current_data_release_id,
            expected_current_data_pointer_sha256=(
                expected_current_data_pointer_sha256
            ),
            target_data_pointer_sha256=target_data_pointer_sha256,
            now_utc=accepted_value,
        )
    except permit_contract.PromotionPermitError as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    if permit_validation.get("legacy_compatible") is not False:
        _fail("new_consumption_requires_exact_binding_v4_permit")
    if (
        acceptance.get("schema_version")
        != "reddit_voc_production_acceptance_validation_result_v2"
        or acceptance.get("upstream_evidence_reopened") is not True
        or acceptance.get("data_pointer_sha256") != target_data_pointer_sha256
        or acceptance.get("rollback_target_data_release_id")
        != expected_current_data_release_id
        or acceptance.get("rollback_target_data_pointer_sha256")
        != expected_current_data_pointer_sha256
    ):
        _fail("production_acceptance_data_binding_mismatch")
    bindings = permit_contract._permit_bindings(permit)
    authorization_id = bindings.get("authorization_id")
    if (
        not isinstance(authorization_id, str)
        or AUTHORIZATION_ID_RE.fullmatch(authorization_id) is None
    ):
        _fail("authorization_id_invalid")

    receipt: dict[str, Any] = {
        "actions_performed": list(SUCCESS_ACTIONS),
        "authorization_id": authorization_id,
        "consumed_at_utc": consumed_value,
        "forbidden_actions_performed": [],
        "packet_sha256": packet_sha,
        "permit_sha256": permit_sha,
        "production_acceptance": {
            "path": acceptance_relative,
            "sha256": acceptance_sha,
            "status": acceptance_contract.STATUS,
        },
        "release_sha256": release_sha,
        "remote_promotion_receipt_sha256": acceptance[
            "remote_promotion_receipt_sha256"
        ],
        "data_binding": {
            "current_data_file_count": acceptance["data_file_count"],
            "current_data_inventory_sha256": acceptance[
                "data_inventory_sha256"
            ],
            "current_data_pointer_sha256": acceptance["data_pointer_sha256"],
            "current_data_release_id": acceptance["data_release_id"],
            "current_data_total_bytes": acceptance["data_total_bytes"],
            "previous_data_pointer_sha256": acceptance[
                "rollback_target_data_pointer_sha256"
            ],
            "previous_data_release_id": acceptance[
                "rollback_target_data_release_id"
            ],
        },
        "schema_version": SCHEMA_VERSION_V2,
        "side_effects": dict(SIDE_EFFECTS),
        "status": STATUS,
    }
    validation = validate_promotion_consumption_document(
        receipt,
        expected_packet_sha256=packet_sha,
        expected_permit_sha256=permit_sha,
        expected_release_sha256=release_sha,
        expected_remote_promotion_receipt_sha256=acceptance[
            "remote_promotion_receipt_sha256"
        ],
        expected_acceptance_receipt_sha256=acceptance_sha,
    )
    try:
        publication_status = control.write_immutable(
            root=root,
            output=output,
            value=receipt,
            label="promotion_consumption_receipt",
        )
    except control.ReleaseControlError as exc:
        raise PromotionConsumptionError(str(exc)) from exc
    return {
        **validation,
        "consumption_receipt_sha256": control.sha256_bytes(
            control.canonical_bytes(receipt)
        ),
        "publication_status": publication_status,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--packet-artifact-root", type=Path)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--permit-sha256", required=True)
    parser.add_argument("--acceptance-receipt", type=Path, required=True)
    parser.add_argument("--acceptance-receipt-sha256", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--expected-current-release-sha256", required=True)
    parser.add_argument("--expected-current-data-release-id", required=True)
    parser.add_argument("--expected-current-data-pointer-sha256", required=True)
    parser.add_argument("--target-data-pointer-sha256", required=True)
    parser.add_argument("--consumed-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = build_promotion_consumption(
            artifact_root=args.artifact_root,
            packet_artifact_root=args.packet_artifact_root,
            packet_path=args.packet,
            packet_sha256=args.packet_sha256,
            permit_path=args.permit,
            permit_sha256=args.permit_sha256,
            acceptance_receipt_path=args.acceptance_receipt,
            acceptance_receipt_sha256=args.acceptance_receipt_sha256,
            release_sha256=args.release_sha256,
            expected_current_release_sha256=args.expected_current_release_sha256,
            expected_current_data_release_id=args.expected_current_data_release_id,
            expected_current_data_pointer_sha256=(
                args.expected_current_data_pointer_sha256
            ),
            target_data_pointer_sha256=args.target_data_pointer_sha256,
            consumed_at_utc=args.consumed_at_utc,
            output=args.output,
        )
    except PromotionConsumptionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
