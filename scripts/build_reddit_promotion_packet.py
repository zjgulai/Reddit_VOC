#!/usr/bin/env python3
"""Build one immutable, authorization-free Reddit VOC promotion packet.

Every artifact path is explicit and must remain beneath ``--artifact-root``.
The command only reads local evidence and writes one mode-0600 canonical JSON
packet.  It never discovers a "latest" artifact, contacts a server, invokes
Docker, grants a permit, or performs a production side effect.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import errno
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit


SCHEMA_VERSION = "reddit_voc_promotion_packet_v4"
LEGACY_SCHEMA_VERSION = "reddit_voc_promotion_packet_v2"
BASELINE_SCHEMA_VERSION = "reddit_voc_production_baseline_receipt_v1"
BASELINE_OBSERVER_RUNTIME_CONTRACT = "reddit_voc_production_baseline_observer_v5"
BASELINE_OBSERVER_RUNTIME_SHA256 = sha256(
    BASELINE_OBSERVER_RUNTIME_CONTRACT.encode("ascii")
).hexdigest()
RELEASE_SCHEMA_VERSION = "reddit_voc_insights_site_release_v2"
BASELINE_LOCK_PATHS = {
    "promotion": "/opt/reddit-voc-insights-site/.promotion.lock",
    "deploy": "/opt/reddit-voc-insights-site/.deploy.lock",
    "data_release": "/opt/reddit-voc-insights-data/locks/data-release.lock",
}

EXECUTION_RUNTIME_FILENAMES = {
    "remote_promotion_runner": "remote_promote_insights_v6.sh",
    "remote_installer": "remote_install_insights_release.sh",
    "remote_rollback": "remote_rollback_insights.sh",
}
EXECUTION_RUNTIME_KEYS = tuple(EXECUTION_RUNTIME_FILENAMES)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{15,127}$")
DATA_RELEASE_RE = re.compile(r"^reddit_voc_release_[a-z0-9][a-z0-9_-]{2,127}$")

ARTIFACT_KEYS = (
    "plan_a_manifest",
    "plan_a_reconciliation",
    "plan_a_receipt",
    "plan_a_source_freeze_manifest",
    "plan_b_manifest",
    "plan_b_receipt",
    "plan_b_source_stage_receipt",
    "build_receipt",
    "release_manifest",
    "release_sha256sums",
    "dist_sha256sums",
    "linux_amd64_image_tar",
    "transfer_tgz",
    "e2e_receipt",
    "local_container_smoke_receipt",
    "production_baseline_receipt",
)
RELEASE_EVIDENCE_ARTIFACT_KEYS = (
    "build_receipt",
    "release_manifest",
    "release_sha256sums",
    "dist_sha256sums",
    "linux_amd64_image_tar",
    "transfer_tgz",
    "e2e_receipt",
    "local_container_smoke_receipt",
    "production_baseline_receipt",
    "candidate_ui_validation_receipt",
)
V3_NATIVE_LINEAGE_ARTIFACT_KEYS = (
    "v3_frontend_source_manifest",
    "v3_frontend_source_receipt",
    "v3_frontend_source_stage_receipt",
    "v3_base_manifest",
    "v3_base_receipt",
    "v3_insights_manifest",
    "v3_insights_receipt",
    "v3_reports_manifest",
    "v3_reports_receipt",
    "v3_personas_manifest",
    "v3_personas_receipt",
)
V3_NATIVE_ARTIFACT_KEYS = (
    *V3_NATIVE_LINEAGE_ARTIFACT_KEYS,
    *RELEASE_EVIDENCE_ARTIFACT_KEYS,
)
V3_NATIVE_LEGACY_ARTIFACT_KEYS = tuple(
    key for key in V3_NATIVE_ARTIFACT_KEYS
    if key != "candidate_ui_validation_receipt"
)
V3_MANIFEST_FAMILIES = (
    "source",
    "canonical",
    "facts",
    "metrics",
    "integrity",
    "personas",
    "casebook",
    "reports",
    "insights",
    "export",
)
V3_RECEIPT_FAMILIES = (*V3_MANIFEST_FAMILIES, "e2e", "container")
V3_ARTIFACT_KEYS = tuple(
    sorted(
        {
            *(f"v3_{family}_manifest" for family in V3_MANIFEST_FAMILIES),
            *(f"v3_{family}_receipt" for family in V3_RECEIPT_FAMILIES),
        }
    )
)
LEGACY_ARTIFACT_SET = frozenset(ARTIFACT_KEYS)
V3_EXTENSION_ARTIFACT_SET = frozenset((*ARTIFACT_KEYS, *V3_ARTIFACT_KEYS))
V3_NATIVE_ARTIFACT_SET = frozenset(V3_NATIVE_ARTIFACT_KEYS)

LEGACY_ALLOWED_ACTIONS = (
    "read_only_remote_preflight",
    "upload_exact_release_artifacts_to_isolated_directory",
    "verify_exact_remote_artifact_hashes",
    "load_exact_linux_amd64_image",
    "start_only_reddit_voc_insights_candidate_18339",
    "run_candidate_runtime_smoke",
    "compare_and_swap_only_insights_current",
    "run_public_production_acceptance",
    "rollback_only_insights_current",
)
ALLOWED_ACTIONS = (
    *LEGACY_ALLOWED_ACTIONS[:3],
    "stage_exact_insights_data_release",
    *LEGACY_ALLOWED_ACTIONS[3:7],
    "compare_and_swap_only_insights_data_current",
    *LEGACY_ALLOWED_ACTIONS[7:8],
    "persist_exact_rollback_authority_evidence",
    *LEGACY_ALLOWED_ACTIONS[8:],
    "rollback_only_insights_data_current",
)

FORBIDDEN_ACTIONS = (
    "modify_collector",
    "restart_collector",
    "modify_cron",
    "modify_shared_nginx",
    "modify_tls",
    "modify_dns",
    "modify_other_docker_environment",
    "docker_prune",
    "provider_call",
    "database_write",
    "schedule_change",
    "live_send",
    "enable_candidate_registry_automation",
    "claim_four_exports_complete",
)

SIDE_EFFECTS = {
    "collector_modified": False,
    "cron_modified": False,
    "database_write": False,
    "deploy": False,
    "dns_modified": False,
    "live_send": False,
    "other_docker_modified": False,
    "production_switch": False,
    "provider_call": False,
    "remote_write": False,
    "schedule_change": False,
    "shared_nginx_modified": False,
    "tls_modified": False,
}
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
V3_FRONTEND_SOURCE_SCHEMA = "reddit_voc_frontend_source_manifest_v2"
V3_FRONTEND_RECEIPT_SCHEMA = "reddit_voc_candidate_ui_source_validation_receipt_v2"
V3_FRONTEND_STAGE_RECEIPT_SCHEMA = "reddit_voc_frontend_source_stage_receipt_v1"
V3_FRONTEND_LINEAGE_CONTRACT = "reddit_voc_v3_four_dataset_frontend_lineage_v1"
V3_FRONTEND_LINEAGE_CONTRACTS = {
    V3_FRONTEND_LINEAGE_CONTRACT,
    "reddit_voc_v3_seven_dataset_frontend_lineage_v2",
}
V3_CORE_DATASET_KEYS = {"base", "insights", "reports", "personas"}
V3_AUXILIARY_DATASET_KEYS = {"brand_health", "quarter_insights", "casebook"}
V3_DATASET_MANIFEST_SCHEMAS = {
    "base": "reddit_voc_site_snapshot_manifest_v3",
    "insights": "reddit_voc_insights_public_manifest_v3",
    "reports": "reddit_voc_reports_public_manifest_v3",
    "personas": "reddit_voc_personas_manifest_v3",
}
V3_DATASET_RECEIPT_SCHEMAS = {
    "base": "reddit_voc_base_public_validation_receipt_v1",
    "insights": "reddit_voc_insights_public_validation_receipt_v3",
    "reports": "reddit_voc_reports_public_validation_receipt_v3",
    "personas": "reddit_voc_personas_validation_v3",
}

LEGACY_DEFERRED_DEBTS = {
    "four_exports": {
        "blocks_initial_boss_visibility": False,
        "status": "deferred_after_initial_production_visibility",
    },
    "registry": {
        "blocks_initial_boss_visibility": False,
        "status": "deferred_after_initial_production_visibility",
    },
}
DEFERRED_DEBTS = {
    "four_exports": {
        "blocks_initial_boss_visibility": False,
        "status": "passed_local_same_release_validation",
    },
    "unresolved_parent_comments": {
        "blocks_initial_boss_visibility": False,
        "count": 6953,
        "status": "preserved_structure_debt",
    },
    "source_pagination": {
        "blocks_initial_boss_visibility": False,
        "status": "partial_source_coverage_bound_to_current_release",
    },
    "daily_automation": {
        "blocks_initial_boss_visibility": False,
        "status": "not_enabled_manual_candidate_only",
    },
    "registry": {
        "blocks_initial_boss_visibility": False,
        "status": "deferred_after_initial_production_visibility",
    },
}


class PromotionPacketError(ValueError):
    """The requested packet would violate its immutable evidence contract."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_file_bytes(value: object) -> bytes:
    return canonical_bytes(value) + b"\n"


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise PromotionPacketError(f"{label}_invalid")
    return value


def parse_utc(value: object, *, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not value.strip():
        raise PromotionPacketError(f"{label}_invalid")
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PromotionPacketError(f"{label}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PromotionPacketError(f"{label}_not_utc")
    normalized = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return normalized, parsed.astimezone(timezone.utc)


def _require_root(path: Path) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise PromotionPacketError("artifact_root_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PromotionPacketError("artifact_root_unsafe")
    return candidate


def _raw_path_has_parent_reference(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _relative_from_explicit(root: Path, path: Path, *, label: str) -> str:
    if _raw_path_has_parent_reference(path):
        raise PromotionPacketError(f"{label}_path_invalid")
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise PromotionPacketError(f"{label}_path_escape") from exc
    if not relative.parts:
        raise PromotionPacketError(f"{label}_path_invalid")
    value = PurePosixPath(*relative.parts).as_posix()
    if value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise PromotionPacketError(f"{label}_path_invalid")
    return value


def _relative_parts(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PromotionPacketError(f"{label}_path_invalid")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or value != relative.as_posix()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise PromotionPacketError(f"{label}_path_invalid")
    return relative.parts


def _regular_bytes(path: Path, *, label: str, expected_mode: int | None = None) -> bytes:
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise PromotionPacketError(f"{label}_missing") from exc
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISREG(path_metadata.st_mode)
        or path_metadata.st_nlink != 1
    ):
        raise PromotionPacketError(f"{label}_unsafe")
    if expected_mode is not None:
        if stat.S_IMODE(path_metadata.st_mode) != expected_mode:
            raise PromotionPacketError(f"{label}_mode_invalid")
        if path_metadata.st_uid != os.getuid():
            raise PromotionPacketError(f"{label}_owner_invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PromotionPacketError(f"{label}_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or after.st_nlink != 1
        or identity_before != identity_after
        or (before.st_dev, before.st_ino)
        != (path_metadata.st_dev, path_metadata.st_ino)
    ):
        raise PromotionPacketError(f"{label}_drift")
    if expected_mode is not None and (
        before.st_uid != os.getuid()
        or after.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != expected_mode
        or stat.S_IMODE(after.st_mode) != expected_mode
    ):
        raise PromotionPacketError(f"{label}_drift")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise PromotionPacketError(f"{label}_drift")
    return payload


def read_relative_file(
    root: Path,
    relative: object,
    *,
    label: str,
    expected_mode: int | None = None,
) -> bytes:
    parts = _relative_parts(relative, label=label)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise PromotionPacketError(f"{label}_missing") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PromotionPacketError(f"{label}_unsafe")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise PromotionPacketError(f"{label}_unsafe")
    return _regular_bytes(current, label=label, expected_mode=expected_mode)


def read_explicit_file(
    root: Path,
    path: Path,
    *,
    label: str,
    expected_mode: int | None = None,
) -> tuple[str, bytes]:
    relative = _relative_from_explicit(root, path, label=label)
    return relative, read_relative_file(
        root, relative, label=label, expected_mode=expected_mode
    )


def _load_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionPacketError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise PromotionPacketError(f"{label}_not_object")
    return value


def _artifact_record(root: Path, path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    relative, payload = read_explicit_file(root, path, label=label)
    return {
        "bytes": len(payload),
        "path": relative,
        "sha256": sha256_bytes(payload),
    }, payload


def _site_url(value: object) -> str:
    if not isinstance(value, str):
        raise PromotionPacketError("site_url_invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise PromotionPacketError("site_url_invalid")
    return f"https://{parsed.netloc}"


def _validate_release_manifest(
    value: Mapping[str, Any],
    *,
    release_sha256: str,
    data_release_id: str,
    target_data_pointer_sha256: str,
) -> None:
    current = value.get("current_release")
    if (
        value.get("schema_version") != RELEASE_SCHEMA_VERSION
        or value.get("release_sha256") != release_sha256
        or value.get("target_platform") != "linux/amd64"
        or not isinstance(current, dict)
        or current.get("release_id") != data_release_id
        or current.get("sha256") != target_data_pointer_sha256
    ):
        raise PromotionPacketError("release_manifest_contract_invalid")


def _validate_baseline_receipt(
    value: Mapping[str, Any],
    *,
    expected_current_release_sha256: str,
    expected_current_data_release_id: str,
    expected_current_data_pointer_sha256: str,
    generated_at: datetime,
    max_age_seconds: int,
) -> dict[str, Any]:
    observed_value, observed_at = parse_utc(
        value.get("observed_at_utc"), label="baseline_observed_at_utc"
    )
    age_seconds = (generated_at - observed_at).total_seconds()
    observations_value = value.get("observations")
    observations = observations_value if isinstance(observations_value, dict) else {}
    insights = observations.get("insights")
    collector = observations.get("collector")
    translation = observations.get("libretranslate")
    observer_runtime = observations.get("observer_runtime")
    locks = observations.get("locks")
    lock_identities = locks.get("identities") if isinstance(locks, dict) else None
    database = observations.get("database")
    report_pointer = observations.get("report_pointer")
    containers = observations.get("running_containers")
    cron = observations.get("cron")
    shared_nginx = observations.get("shared_nginx")
    release_sums = observations.get("release_sha256s")
    site_tuple = observations.get("site_data_tuple")
    site_manifest = observations.get("site_release_manifest")
    runtime_contract = insights.get("runtime_contract") if isinstance(insights, dict) else None
    data_file_count = (
        insights.get("data_file_count") if isinstance(insights, dict) else None
    )
    data_total_bytes = (
        insights.get("data_total_bytes") if isinstance(insights, dict) else None
    )

    def positive_integer(candidate: object) -> bool:
        return (
            not isinstance(candidate, bool)
            and isinstance(candidate, int)
            and candidate > 0
        )

    def zero_integer(candidate: object) -> bool:
        return (
            not isinstance(candidate, bool)
            and isinstance(candidate, int)
            and candidate == 0
        )

    def pristine_container(candidate: object) -> bool:
        return (
            isinstance(candidate, dict)
            and SHA256_RE.fullmatch(str(candidate.get("container_id"))) is not None
            and candidate.get("health") == "healthy"
            and zero_integer(candidate.get("restart_count"))
        )

    def stable_file(candidate: object, *, allow_absent: bool = False) -> bool:
        if not isinstance(candidate, dict):
            return False
        before = candidate.get("before")
        after = candidate.get("after")
        return (
            candidate.get("stable") is True
            and isinstance(before, str)
            and (
                (allow_absent and before == "absent")
                or re.fullmatch(r"[0-9]+:[0-9]+:[0-9]+", before) is not None
            )
            and after == before
        )

    def exact_runtime_contract(candidate: object) -> bool:
        if not isinstance(candidate, dict) or set(candidate) != {
            "cap_add",
            "cap_drop",
            "collector_listener_reachable",
            "command",
            "component_label",
            "device_access",
            "entrypoint",
            "host_port_binding",
            "image_id",
            "image_archive_config_digest_verified",
            "image_archive_path",
            "image_reference",
            "image_tag_id_verified",
            "init",
            "memory_bytes",
            "mount",
            "nano_cpus",
            "network",
            "network_attachment_id_verified",
            "network_mode",
            "no_new_privileges",
            "pid_namespace",
            "pids_limit",
            "privileged",
            "read_only_rootfs",
            "restart_policy",
            "runtime",
            "tmpfs_options",
            "user",
        }:
            return False
        mount = candidate.get("mount")
        binding = candidate.get("host_port_binding")
        network = candidate.get("network")
        return (
            candidate.get("cap_add") == []
            and candidate.get("cap_drop") == ["ALL"]
            and candidate.get("collector_listener_reachable") is False
            and candidate.get("command") == ["nginx", "-g", "daemon off;"]
            and candidate.get("component_label") == "insights-site"
            and candidate.get("device_access") is False
            and candidate.get("entrypoint") == ["/docker-entrypoint.sh"]
            and binding == {"HostIp": "172.20.0.1", "HostPort": "18338"}
            and isinstance(candidate.get("image_id"), str)
            and re.fullmatch(r"sha256:[a-f0-9]{64}", candidate["image_id"])
            is not None
            and candidate.get("image_archive_config_digest_verified") is True
            and candidate.get("image_archive_path")
            == (
                "/opt/reddit-voc-insights-site/releases/"
                f"{expected_current_release_sha256}/reddit-voc-insights-"
                f"{expected_current_release_sha256}.tar"
            )
            and candidate.get("image_reference")
            == f"reddit-voc-insights:{expected_current_release_sha256}"
            and candidate.get("image_tag_id_verified") is True
            and candidate.get("init") is True
            and candidate.get("memory_bytes") == 268435456
            and mount
            == {
                "destination": "/srv/reddit-voc-data",
                "propagation": "rprivate",
                "read_only": True,
                "source": "/opt/reddit-voc-insights-data",
                "type": "bind",
            }
            and candidate.get("nano_cpus") == 500000000
            and isinstance(network, dict)
            and set(network)
            == {"driver", "icc", "id", "internal", "ip_masquerade", "name"}
            and network.get("driver") == "bridge"
            and network.get("icc") is False
            and SHA256_RE.fullmatch(str(network.get("id"))) is not None
            and network.get("internal") is False
            and network.get("ip_masquerade") is False
            and network.get("name") == "reddit_voc_insights_net"
            and candidate.get("network_attachment_id_verified") is True
            and candidate.get("network_mode") == "reddit_voc_insights_net"
            and candidate.get("no_new_privileges") is True
            and candidate.get("pid_namespace") == "private"
            and candidate.get("pids_limit") == 100
            and candidate.get("privileged") is False
            and candidate.get("read_only_rootfs") is True
            and candidate.get("restart_policy") == "unless-stopped"
            and candidate.get("runtime") == "runc"
            and candidate.get("tmpfs_options")
            == sorted(
                {
                    "rw",
                    "noexec",
                    "nosuid",
                    "nodev",
                    "size=32m",
                    "uid=101",
                    "gid=101",
                    "mode=1777",
                }
            )
            and candidate.get("user") == "101:101"
        )

    runtime_uid = (
        observer_runtime.get("uid") if isinstance(observer_runtime, dict) else None
    )
    locks_valid = (
        isinstance(locks, dict)
        and locks.get("stable") is True
        and isinstance(lock_identities, dict)
        and set(lock_identities) == set(BASELINE_LOCK_PATHS)
        and not isinstance(runtime_uid, bool)
        and isinstance(runtime_uid, int)
        and runtime_uid >= 0
    )
    if locks_valid and isinstance(lock_identities, dict):
        for name, expected_path in BASELINE_LOCK_PATHS.items():
            identity = lock_identities.get(name)
            device = identity.get("device") if isinstance(identity, dict) else None
            if (
                not isinstance(identity, dict)
                or identity.get("path") != expected_path
                or identity.get("mode") != "0600"
                or identity.get("nlink") != 1
                or identity.get("uid") != runtime_uid
                or isinstance(device, bool)
                or not isinstance(device, int)
                or device < 0
                or not positive_integer(identity.get("inode"))
            ):
                locks_valid = False
                break

    inventory_sha = (
        insights.get("data_inventory_sha256") if isinstance(insights, dict) else None
    )
    site_inventory_bound = (
        site_tuple.get("manifest_inventory_bound")
        if isinstance(site_tuple, dict)
        else None
    )
    site_manifest_inventory_valid = False
    if isinstance(site_manifest, dict) and isinstance(site_inventory_bound, bool):
        manifest_inventory = (
            site_manifest.get("data_inventory_sha256"),
            site_manifest.get("data_file_count"),
            site_manifest.get("data_total_bytes"),
        )
        site_manifest_inventory_valid = (
            manifest_inventory == (inventory_sha, data_file_count, data_total_bytes)
            if site_inventory_bound
            else manifest_inventory == (None, None, None)
        )

    if (
        value.get("schema_version") != BASELINE_SCHEMA_VERSION
        or value.get("status") != "passed"
        or value.get("evidence_grade") != "L3-production-read-only"
        or value.get("current_release_sha256")
        != expected_current_release_sha256
        or not isinstance(observations_value, dict)
        or not isinstance(insights, dict)
        or not zero_integer(observations.get("candidate_container_count"))
        or not zero_integer(observations.get("candidate_container_count_after"))
        or not zero_integer(observations.get("candidate_container_residue_count"))
        or not zero_integer(observations.get("candidate_container_residue_count_after"))
        or not zero_integer(observations.get("candidate_listener_18339_count"))
        or not zero_integer(observations.get("candidate_listener_18339_count_after"))
        or not zero_integer(observations.get("one_shot_collectors_running"))
        or not zero_integer(observations.get("one_shot_collectors_running_after"))
        or not zero_integer(observations.get("report_network_containers_running"))
        or not zero_integer(observations.get("report_network_containers_running_after"))
        or observations.get("quiet_counts_stable") is not True
        or not pristine_container(collector)
        or not pristine_container(translation)
        or not pristine_container(insights)
        or insights.get("release_label") != expected_current_release_sha256
        or insights.get("internal_release_sha256")
        != expected_current_release_sha256
        or insights.get("current_symlink")
        != f"releases/{expected_current_release_sha256}"
        or insights.get("internal_pointer") != expected_current_data_release_id
        or insights.get("internal_pointer_sha256")
        != expected_current_data_pointer_sha256
        or insights.get("internal_pointer_symlink")
        != f"releases/{expected_current_data_release_id}"
        or insights.get("listener") != "172.20.0.1:18338"
        or insights.get("mount_count") != 1
        or insights.get("user") != "101:101"
        or insights.get("read_only_rootfs") is not True
        or insights.get("network") != "reddit_voc_insights_net"
        or not exact_runtime_contract(runtime_contract)
        or SHA256_RE.fullmatch(str(inventory_sha)) is None
        or isinstance(data_file_count, bool)
        or not isinstance(data_file_count, int)
        or data_file_count <= 0
        or isinstance(data_total_bytes, bool)
        or not isinstance(data_total_bytes, int)
        or data_total_bytes <= 0
        or not stable_file(database)
        or not stable_file(report_pointer, allow_absent=True)
        or not isinstance(containers, dict)
        or containers.get("scope") != "docker_ps_a"
        or containers.get("stable") is not True
        or not positive_integer(containers.get("count"))
        or SHA256_RE.fullmatch(str(containers.get("inventory_sha256"))) is None
        or containers.get("protected_scope")
        != "docker_ps_a_excluding_insights_transaction"
        or not positive_integer(containers.get("protected_count"))
        or SHA256_RE.fullmatch(
            str(containers.get("protected_inventory_sha256"))
        )
        is None
        or not isinstance(cron, dict)
        or cron.get("stable") is not True
        or SHA256_RE.fullmatch(str(cron.get("sha256"))) is None
        or observations.get("cron_sha256") != cron.get("sha256")
        or not isinstance(shared_nginx, dict)
        or shared_nginx.get("stable") is not True
        or SHA256_RE.fullmatch(str(shared_nginx.get("sha256"))) is None
        or observations.get("shared_nginx_sha256") != shared_nginx.get("sha256")
        or not isinstance(release_sums, dict)
        or release_sums.get("verified_before") is not True
        or release_sums.get("verified_after") is not True
        or release_sums.get("stable") is not True
        or SHA256_RE.fullmatch(str(release_sums.get("sha256"))) is None
        or observations.get("release_sha256sums_verified") is not True
        or not isinstance(observer_runtime, dict)
        or observer_runtime.get("contract") != BASELINE_OBSERVER_RUNTIME_CONTRACT
        or observer_runtime.get("contract_sha256")
        != BASELINE_OBSERVER_RUNTIME_SHA256
        or not locks_valid
        or not isinstance(site_tuple, dict)
        or site_tuple.get("stable") is not True
        or site_tuple.get("data_release_id")
        != expected_current_data_release_id
        or site_tuple.get("pointer_sha256")
        != expected_current_data_pointer_sha256
        or site_tuple.get("site_release_sha256")
        != expected_current_release_sha256
        or site_tuple.get("data_inventory_sha256") != inventory_sha
        or site_tuple.get("data_file_count") != data_file_count
        or site_tuple.get("data_total_bytes") != data_total_bytes
        or SHA256_RE.fullmatch(str(site_tuple.get("site_manifest_sha256"))) is None
        or not isinstance(site_manifest, dict)
        or site_manifest.get("stable") is not True
        or site_manifest.get("served_exact") is not True
        or site_manifest.get("pointer_path")
        != "data/reddit-voc/current-release.json"
        or site_manifest.get("data_release_id")
        != expected_current_data_release_id
        or site_manifest.get("pointer_sha256")
        != expected_current_data_pointer_sha256
        or site_manifest.get("release_sha256")
        != expected_current_release_sha256
        or site_manifest.get("manifest_sha256")
        != site_tuple.get("site_manifest_sha256")
        or not site_manifest_inventory_valid
        or value.get("production_unchanged") is not True
        or value.get("remote_write") is not False
        or age_seconds < 0
        or age_seconds > max_age_seconds
    ):
        raise PromotionPacketError("production_baseline_receipt_contract_invalid")
    assert isinstance(release_sums, dict)
    assert isinstance(site_manifest, dict)
    assert isinstance(collector, dict)
    assert isinstance(translation, dict)
    assert isinstance(insights, dict)
    assert isinstance(runtime_contract, dict)
    assert isinstance(runtime_contract["network"], dict)
    assert isinstance(containers, dict)
    assert isinstance(database, dict)
    assert isinstance(report_pointer, dict)
    assert isinstance(lock_identities, dict)
    assert isinstance(cron, dict)
    assert isinstance(shared_nginx, dict)
    return {
        "cas": {
            "collector": {
                "container_id": collector["container_id"],
                "health": collector["health"],
                "restart_count": collector["restart_count"],
            },
            "container_inventory": {
                "count": containers["count"],
                "protected_count": containers["protected_count"],
                "protected_sha256": containers[
                    "protected_inventory_sha256"
                ],
                "sha256": containers["inventory_sha256"],
            },
            "cron_sha256": cron["sha256"],
            "database_identity": database["before"],
            "insights": {
                "container_id": insights["container_id"],
                "health": insights["health"],
                "image_id": runtime_contract["image_id"],
                "network_id": runtime_contract["network"]["id"],
                "restart_count": insights["restart_count"],
            },
            "lock_identities": lock_identities,
            "observed_at_utc": observed_value,
            "report_pointer_identity": report_pointer["before"],
            "shared_nginx_sha256": shared_nginx["sha256"],
            "translation": {
                "container_id": translation["container_id"],
                "health": translation["health"],
                "restart_count": translation["restart_count"],
            },
        },
        "rollback": {
            "target_data_file_count": data_file_count,
            "target_data_inventory_sha256": str(inventory_sha),
            "target_data_total_bytes": data_total_bytes,
            "target_release_manifest_sha256": str(
                site_manifest["manifest_sha256"]
            ),
            "target_release_sha256s_sha256": str(release_sums["sha256"]),
        },
    }


def _packet_id(packet_identity: Mapping[str, Any]) -> str:
    return f"reddit_voc_promotion_{sha256_bytes(canonical_bytes(packet_identity))[:24]}"


def _v3_boundary_object(value: Mapping[str, Any], *, flat: bool = False) -> Mapping[str, Any]:
    boundaries = value if flat else value.get("boundaries")
    if (
        not isinstance(boundaries, dict)
        or any(boundaries.get(name) is not expected for name, expected in V3_BOUNDARIES.items())
    ):
        raise PromotionPacketError("v3_native_boundaries_invalid")
    return boundaries


def _validate_periodic_report_publication(
    value: object, *, release_id: str
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "assets",
        "bundle_id",
        "contract",
        "data_release_id",
        "manifest_relative_path",
        "manifest_sha256",
        "source_bundle_manifest_sha256",
    }:
        raise PromotionPacketError("v3_periodic_report_publication_contract_invalid")
    bundle_id = value.get("bundle_id")
    if (
        value.get("contract") != "reddit_voc_periodic_report_frontend_publication_v1"
        or value.get("data_release_id") != release_id
        or not isinstance(bundle_id, str)
        or not bundle_id.startswith("periodic_")
        or SHA256_RE.fullmatch(str(value.get("manifest_sha256"))) is None
        or SHA256_RE.fullmatch(str(value.get("source_bundle_manifest_sha256"))) is None
        or value.get("manifest_relative_path")
        != f"public/periodic-report-assets/{bundle_id}/manifest.json"
    ):
        raise PromotionPacketError("v3_periodic_report_publication_contract_invalid")
    assets = value.get("assets")
    if not isinstance(assets, list) or len(assets) != 3:
        raise PromotionPacketError("v3_periodic_report_publication_assets_invalid")
    grains: set[str] = set()
    for row in assets:
        if not isinstance(row, Mapping) or set(row) != {
            "bytes",
            "grain",
            "relative_path",
            "sha256",
        }:
            raise PromotionPacketError("v3_periodic_report_publication_assets_invalid")
        grain = row.get("grain")
        path = row.get("relative_path")
        if (
            grain not in {"daily", "weekly", "monthly"}
            or grain in grains
            or isinstance(row.get("bytes"), bool)
            or not isinstance(row.get("bytes"), int)
            or row["bytes"] <= 0
            or path
            != f"public/periodic-report-assets/{bundle_id}/public/{grain}/poster.png"
            or PurePosixPath(str(path)).is_absolute()
            or ".." in PurePosixPath(str(path)).parts
            or SHA256_RE.fullmatch(str(row.get("sha256"))) is None
        ):
            raise PromotionPacketError("v3_periodic_report_publication_assets_invalid")
        grains.add(str(grain))
    if grains != {"daily", "weekly", "monthly"}:
        raise PromotionPacketError("v3_periodic_report_publication_assets_invalid")
    return value


def _validate_v3_native_artifacts(
    payloads: Mapping[str, bytes],
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    release_id: str | None,
    source_snapshot_id: str | None,
    candidate_release_sha256: str,
    packet_generated_at: datetime,
    allow_legacy_native: bool = False,
) -> dict[str, Any]:
    expected_native_keys = (
        V3_NATIVE_LEGACY_ARTIFACT_KEYS
        if allow_legacy_native
        else V3_NATIVE_ARTIFACT_KEYS
    )
    if (
        set(payloads) != set(expected_native_keys)
        or not isinstance(release_id, str)
        or not release_id
        or not isinstance(source_snapshot_id, str)
        or not source_snapshot_id
    ):
        raise PromotionPacketError("v3_native_artifact_set_invalid")
    values: dict[str, dict[str, Any]] = {}
    for key in V3_NATIVE_LINEAGE_ARTIFACT_KEYS:
        value = _load_object(payloads[key], label=key)
        # The governed personas validator predates the canonical compact-JSON
        # writers used by the other V3 contracts.  Its exact bytes are still
        # immutable and SHA-bound by the packet, so accept that one established
        # serialization while keeping canonical JSON mandatory elsewhere.
        if (
            key != "v3_personas_receipt"
            and canonical_file_bytes(value) != payloads[key]
        ):
            raise PromotionPacketError(f"{key}_noncanonical")
        values[key] = value

    source_manifest = values["v3_frontend_source_manifest"]
    source_receipt = values["v3_frontend_source_receipt"]
    source_stage_receipt = values["v3_frontend_source_stage_receipt"]
    candidate_input_sha = source_manifest.get("frontend_candidate_input_sha256")
    source_manifest_sha = artifacts["v3_frontend_source_manifest"]["sha256"]
    if (
        source_manifest.get("schema_version") != V3_FRONTEND_SOURCE_SCHEMA
        or source_manifest.get("status") != "frontend_source_frozen_local"
        or not isinstance(candidate_input_sha, str)
        or SHA256_RE.fullmatch(candidate_input_sha) is None
    ):
        raise PromotionPacketError("v3_frontend_source_manifest_contract_invalid")
    _v3_boundary_object(source_manifest)
    upstream = source_manifest.get("upstream")
    lineage = upstream.get("v3_lineage") if isinstance(upstream, dict) else None
    periodic_publication = (
        upstream.get("periodic_report_publication")
        if isinstance(upstream, dict)
        else None
    )
    datasets = lineage.get("datasets") if isinstance(lineage, dict) else None
    current_release_pointer_sha = (
        lineage.get("current_release_pointer_sha256")
        if isinstance(lineage, dict)
        else None
    )
    auxiliary_manifests = (
        lineage.get("auxiliary_public_manifests")
        if isinstance(lineage, dict)
        else None
    )
    if (
        not isinstance(upstream, dict)
        or set(upstream) not in (
            {"v3_lineage"},
            {"v3_lineage", "periodic_report_publication"},
        )
        or not isinstance(lineage, dict)
        or lineage.get("contract") not in V3_FRONTEND_LINEAGE_CONTRACTS
        or lineage.get("source_snapshot_id") != source_snapshot_id
        or not isinstance(current_release_pointer_sha, str)
        or SHA256_RE.fullmatch(current_release_pointer_sha) is None
        or not isinstance(datasets, dict)
        or set(datasets) != V3_CORE_DATASET_KEYS
        or not isinstance(auxiliary_manifests, list)
    ):
        raise PromotionPacketError("v3_frontend_source_lineage_invalid")
    periodic_publication = _validate_periodic_report_publication(
        periodic_publication,
        release_id=release_id,
    )
    lineage_contract = lineage["contract"]
    if (
        lineage_contract == "reddit_voc_v3_seven_dataset_frontend_lineage_v2"
        and (
            set(lineage)
            != {
                "auxiliary_public_manifests",
                "contract",
                "current_release_pointer_sha256",
                "datasets",
                "source_snapshot_id",
            }
            or len(auxiliary_manifests) != len(V3_AUXILIARY_DATASET_KEYS)
        )
    ):
        raise PromotionPacketError("v3_auxiliary_manifest_contract_invalid")
    if (
        source_receipt.get("schema_version") != V3_FRONTEND_RECEIPT_SCHEMA
        or source_receipt.get("status") != "passed_local_source_validation"
        or source_receipt.get("frontend_candidate_input_sha256") != candidate_input_sha
        or source_receipt.get("frontend_source_manifest_sha256") != source_manifest_sha
        or source_receipt.get("v3_lineage") != lineage
        or source_receipt.get("periodic_report_publication")
        != periodic_publication
    ):
        raise PromotionPacketError("v3_frontend_source_receipt_contract_invalid")
    _v3_boundary_object(source_receipt)
    if (
        source_stage_receipt.get("schema_version")
        != V3_FRONTEND_STAGE_RECEIPT_SCHEMA
        or source_stage_receipt.get("status") != "source_stage_materialized_local"
        or source_stage_receipt.get("frontend_candidate_input_sha256")
        != candidate_input_sha
        or source_stage_receipt.get("frontend_source_manifest_sha256")
        != source_manifest_sha
        or source_stage_receipt.get("frontend_source_manifest_schema")
        != V3_FRONTEND_SOURCE_SCHEMA
    ):
        raise PromotionPacketError("v3_frontend_source_stage_receipt_contract_invalid")
    _v3_boundary_object(source_stage_receipt)

    for name in ("base", "insights", "reports", "personas"):
        manifest_key = f"v3_{name}_manifest"
        receipt_key = f"v3_{name}_receipt"
        manifest = values[manifest_key]
        receipt = values[receipt_key]
        binding = datasets.get(name)
        manifest_sha = artifacts[manifest_key]["sha256"]
        receipt_sha = artifacts[receipt_key]["sha256"]
        observed_version = (
            manifest.get("snapshot_id")
            if name == "personas"
            else manifest.get("dataset_version")
        )
        observed_snapshot = (
            manifest.get("governed_signal_source_snapshot_id")
            if name == "personas"
            else manifest.get("source_snapshot_id")
        )
        if (
            not isinstance(binding, dict)
            or manifest.get("schema_version") != V3_DATASET_MANIFEST_SCHEMAS[name]
            or observed_version != binding.get("dataset_version")
            or observed_snapshot != source_snapshot_id
            or binding.get("public_manifest_sha256") != manifest_sha
            or binding.get("validation_receipt_sha256") != receipt_sha
            or binding.get("validation_receipt_schema")
            != V3_DATASET_RECEIPT_SCHEMAS[name]
            or manifest.get("promotable") is not True
        ):
            raise PromotionPacketError(f"v3_{name}_dataset_lineage_invalid")
        manifest_generated = manifest.get("generated_at_utc")
        if manifest_generated is not None:
            _, manifest_generated_at = parse_utc(
                manifest_generated,
                label=f"v3_{name}_manifest_generated_at_utc",
            )
            if manifest_generated_at > packet_generated_at:
                raise PromotionPacketError(
                    f"v3_{name}_manifest_generated_after_packet"
                )
        _v3_boundary_object(manifest)
        expected_receipt_status = "passed" if name == "personas" else "passed_candidate_only"
        receipt_manifest_sha = (
            receipt.get("manifest_sha256")
            if name == "personas"
            else receipt.get("bundle_manifest_sha256")
        )
        if (
            receipt.get("schema_version") != V3_DATASET_RECEIPT_SCHEMAS[name]
            or receipt.get("status") != expected_receipt_status
            or receipt.get("promotable") is not True
            or receipt_manifest_sha != manifest_sha
        ):
            raise PromotionPacketError(f"v3_{name}_receipt_lineage_invalid")
        _v3_boundary_object(receipt, flat=name == "personas")
        expected_lineage_sha = (
            manifest_sha
            if name == "personas"
            else manifest.get("lineage_manifest_sha256")
        )
        if binding.get("lineage_manifest_sha256") != expected_lineage_sha:
            raise PromotionPacketError(f"v3_{name}_private_lineage_invalid")

    release_manifest = _load_object(
        payloads["release_manifest"], label="release_manifest"
    )
    frontend_source = release_manifest.get("frontend_source")
    release_current = release_manifest.get("current_release")
    release_dataset_versions = release_manifest.get("dataset_versions")
    release_dataset_manifests = release_manifest.get("dataset_manifests")
    release_files = release_manifest.get("files")
    if (
        not isinstance(frontend_source, dict)
        or frontend_source.get("contract_schema_version")
        != V3_FRONTEND_SOURCE_SCHEMA
        or frontend_source.get("frontend_candidate_input_sha256")
        != candidate_input_sha
        or frontend_source.get("manifest", {}).get("sha256") != source_manifest_sha
        or frontend_source.get("validation_receipt", {}).get("sha256")
        != artifacts["v3_frontend_source_receipt"]["sha256"]
        or frontend_source.get("v3_lineage") != lineage
        or frontend_source.get("periodic_report_publication")
        != periodic_publication
        or release_manifest.get("current_release", {}).get("release_id") != release_id
    ):
        raise PromotionPacketError("v3_release_frontend_lineage_invalid")
    if (
        not isinstance(release_current, dict)
        or release_current.get("release_id") != release_id
        or release_current.get("sha256") != current_release_pointer_sha
        or not isinstance(release_dataset_versions, dict)
        or set(release_dataset_versions)
        != (
            V3_CORE_DATASET_KEYS | V3_AUXILIARY_DATASET_KEYS
            if lineage_contract == "reddit_voc_v3_seven_dataset_frontend_lineage_v2"
            else V3_CORE_DATASET_KEYS
        )
        or not isinstance(release_dataset_manifests, dict)
        or set(release_dataset_manifests) != set(release_dataset_versions)
        or not isinstance(release_files, list)
    ):
        raise PromotionPacketError("v3_release_data_lineage_invalid")
    release_file_shas: dict[str, str] = {}
    for row in release_files:
        if (
            not isinstance(row, dict)
            or set(row) != {"bytes", "path", "sha256"}
            or isinstance(row.get("bytes"), bool)
            or not isinstance(row.get("bytes"), int)
            or row["bytes"] < 0
            or not isinstance(row.get("path"), str)
            or not isinstance(row.get("sha256"), str)
            or SHA256_RE.fullmatch(row["sha256"]) is None
            or row["path"] in release_file_shas
        ):
            raise PromotionPacketError("v3_release_file_inventory_invalid")
        _relative_parts(row["path"], label="v3_release_file")
        release_file_shas[row["path"]] = row["sha256"]
    release_pointer_path = release_current.get("path")
    if (
        not isinstance(release_pointer_path, str)
        or release_file_shas.get(release_pointer_path) != current_release_pointer_sha
    ):
        raise PromotionPacketError("v3_release_pointer_inventory_invalid")
    for name in ("base", "insights", "reports", "personas"):
        binding = datasets[name]
        release_binding = release_dataset_manifests[name]
        source_manifest_path = binding.get("public_manifest_relative_path")
        source_parts = _relative_parts(
            source_manifest_path, label=f"v3_{name}_public_manifest_path"
        )
        if source_parts[0] != "public":
            raise PromotionPacketError(f"v3_{name}_public_manifest_path_invalid")
        release_manifest_path = PurePosixPath(*source_parts[1:]).as_posix()
        if (
            release_dataset_versions[name] != binding.get("dataset_version")
            or not isinstance(release_binding, dict)
            or release_binding.get("manifest_path") != release_manifest_path
            or release_binding.get("public_manifest_sha256")
            != binding.get("public_manifest_sha256")
            or release_binding.get("lineage_manifest_sha256")
            != binding.get("lineage_manifest_sha256")
            or release_file_shas.get(release_manifest_path)
            != binding.get("public_manifest_sha256")
        ):
            raise PromotionPacketError(f"v3_{name}_release_lineage_invalid")
    seen_auxiliary: set[str] = set()
    for row in auxiliary_manifests:
        if (
            not isinstance(row, dict)
            or set(row) != {"relative_path", "sha256"}
            or not isinstance(row.get("relative_path"), str)
            or not isinstance(row.get("sha256"), str)
            or SHA256_RE.fullmatch(row["sha256"]) is None
        ):
            raise PromotionPacketError("v3_auxiliary_manifest_contract_invalid")
        source_parts = _relative_parts(
            row["relative_path"], label="v3_auxiliary_manifest_path"
        )
        if source_parts[0] != "public":
            raise PromotionPacketError("v3_auxiliary_manifest_path_invalid")
        release_path = PurePosixPath(*source_parts[1:]).as_posix()
        if (
            release_path in seen_auxiliary
            or release_file_shas.get(release_path) != row["sha256"]
        ):
            raise PromotionPacketError("v3_auxiliary_manifest_lineage_invalid")
        seen_auxiliary.add(release_path)
    if lineage_contract == "reddit_voc_v3_seven_dataset_frontend_lineage_v2":
        for name in V3_AUXILIARY_DATASET_KEYS:
            version = release_dataset_versions[name]
            release_binding = release_dataset_manifests[name]
            expected_path = f"data/reddit-voc/{version}/manifest.json"
            if (
                not isinstance(version, str)
                or not isinstance(release_binding, dict)
                or release_binding.get("manifest_path") != expected_path
                or expected_path not in seen_auxiliary
                or release_binding.get("public_manifest_sha256")
                != release_file_shas.get(expected_path)
                or release_binding.get("lineage_manifest_sha256")
                != release_file_shas.get(expected_path)
            ):
                raise PromotionPacketError(f"v3_{name}_release_lineage_invalid")
    build_receipt = _load_object(payloads["build_receipt"], label="build_receipt")
    expected_data_lineage = {
        "current_release": release_current,
        "dataset_manifests": release_dataset_manifests,
        "dataset_versions": release_dataset_versions,
    }
    if (
        build_receipt.get("schema_version") != "reddit_voc_insights_build_receipt_v1"
        or build_receipt.get("status") != "passed_local_build"
        or build_receipt.get("release_sha256") != candidate_release_sha256
        or build_receipt.get("frontend_source") != frontend_source
        or build_receipt.get("data_lineage") != expected_data_lineage
    ):
        raise PromotionPacketError("v3_build_receipt_lineage_invalid")

    if not allow_legacy_native:
        candidate_receipt = _load_object(
            payloads["candidate_ui_validation_receipt"],
            label="candidate_ui_validation_receipt",
        )
        if canonical_file_bytes(candidate_receipt) != payloads["candidate_ui_validation_receipt"]:
            raise PromotionPacketError("candidate_ui_validation_receipt_noncanonical")
        candidate_v3_lineage = candidate_receipt.get("v3_lineage")
        expected_candidate_v3_lineage = {
            "artifact_sha256s": {
                key: str(artifacts[key]["sha256"])
                for key in V3_NATIVE_LINEAGE_ARTIFACT_KEYS
            },
            "candidate_release_sha256": candidate_release_sha256,
            "release_id": release_id,
            "source_snapshot_id": source_snapshot_id,
        }
        candidate_evidence = candidate_receipt.get("evidence")
        candidate_deliverables = candidate_receipt.get("deliverables")
        candidate_release = candidate_receipt.get("release")
        candidate_lineage = candidate_receipt.get("lineage")
        if (
            candidate_receipt.get("schema_version")
            != "reddit_voc_candidate_ui_validation_receipt_v2"
            or candidate_receipt.get("status") != "passed_local_candidate_validation"
            or candidate_v3_lineage != expected_candidate_v3_lineage
            or not isinstance(candidate_release, dict)
            or candidate_release.get("release_sha256") != candidate_release_sha256
            or not isinstance(candidate_lineage, dict)
            or candidate_lineage.get("build_contract_sha256")
            != artifacts["build_receipt"]["sha256"]
            or not isinstance(candidate_deliverables, dict)
            or candidate_deliverables.get("image_tar_sha256")
            != artifacts["linux_amd64_image_tar"]["sha256"]
            or candidate_deliverables.get("transfer_tgz_sha256")
            != artifacts["transfer_tgz"]["sha256"]
            or not isinstance(candidate_evidence, dict)
            or candidate_evidence.get("browser_e2e_evidence_sha256")
            != artifacts["e2e_receipt"]["sha256"]
            or candidate_evidence.get("container_evidence_sha256")
            != artifacts["local_container_smoke_receipt"]["sha256"]
            or any(
                not isinstance(candidate_evidence.get(key), str)
                or SHA256_RE.fullmatch(str(candidate_evidence.get(key))) is None
                for key in (
                    "export_evidence_sha256",
                    "security_evidence_sha256",
                    "ui_validation_evidence_sha256",
                )
            )
        ):
            raise PromotionPacketError("candidate_ui_validation_receipt_contract_invalid")
        _v3_boundary_object(candidate_receipt)

    return {
        "artifact_sha256s": {
            key: str(artifacts[key]["sha256"]) for key in expected_native_keys
        },
        "candidate_release_sha256": candidate_release_sha256,
        "release_id": release_id,
        "source_snapshot_id": source_snapshot_id,
    }


def _validate_v3_artifacts(
    payloads: Mapping[str, bytes],
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    release_id: str | None,
    source_snapshot_id: str | None,
    candidate_release_sha256: str,
    packet_generated_at: datetime,
    allow_legacy_native: bool = False,
) -> dict[str, Any] | None:
    payload_keys = set(payloads)
    if (
        payload_keys == set(V3_NATIVE_ARTIFACT_KEYS)
        or payload_keys == set(V3_NATIVE_LEGACY_ARTIFACT_KEYS)
    ):
        return _validate_v3_native_artifacts(
            payloads,
            artifacts,
            release_id=release_id,
            source_snapshot_id=source_snapshot_id,
            candidate_release_sha256=candidate_release_sha256,
            packet_generated_at=packet_generated_at,
            allow_legacy_native=(
                allow_legacy_native
                and payload_keys == set(V3_NATIVE_LEGACY_ARTIFACT_KEYS)
            ),
        )
    present = set(payloads) & set(V3_ARTIFACT_KEYS)
    if not present:
        if release_id is not None or source_snapshot_id is not None:
            raise PromotionPacketError("v3_lineage_without_artifacts")
        return None
    if (
        present != set(V3_ARTIFACT_KEYS)
        or not isinstance(release_id, str)
        or not release_id
        or not isinstance(source_snapshot_id, str)
        or not source_snapshot_id
    ):
        raise PromotionPacketError("v3_artifact_set_invalid")
    observed_release_ids: set[str] = set()
    observed_snapshot_ids: set[str] = set()
    artifact_sha256s: dict[str, str] = {}
    for key in V3_ARTIFACT_KEYS:
        value = _load_object(payloads[key], label=key)
        if canonical_file_bytes(value) != payloads[key]:
            raise PromotionPacketError(f"{key}_noncanonical")
        boundaries = value.get("boundaries")
        if (
            not isinstance(boundaries, dict)
            or any(boundaries.get(name) is not expected for name, expected in V3_BOUNDARIES.items())
            or any(
                name != "production_unchanged" and state is not False
                for name, state in boundaries.items()
            )
        ):
            raise PromotionPacketError(f"{key}_boundaries_invalid")
        status = value.get("status")
        if key.endswith("_receipt") and (
            not isinstance(status, str) or not status.startswith("passed")
        ):
            raise PromotionPacketError(f"{key}_not_passed")
        if isinstance(value.get("release_id"), str):
            observed_release_ids.add(str(value["release_id"]))
        if isinstance(value.get("source_snapshot_id"), str):
            observed_snapshot_ids.add(str(value["source_snapshot_id"]))
        release_sha = value.get("candidate_release_sha256")
        if release_sha is not None and release_sha != candidate_release_sha256:
            raise PromotionPacketError("v3_candidate_release_mismatch")
        artifact_sha256s[key] = str(artifacts[key]["sha256"])
    if observed_release_ids - {release_id}:
        raise PromotionPacketError("v3_mixed_release_id")
    if observed_snapshot_ids - {source_snapshot_id}:
        raise PromotionPacketError("v3_mixed_source_snapshot_id")
    return {
        "artifact_sha256s": artifact_sha256s,
        "candidate_release_sha256": candidate_release_sha256,
        "release_id": release_id,
        "source_snapshot_id": source_snapshot_id,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish ``source`` without replacing an existing path.

    Linux and macOS expose different names for the same no-replace primitive.
    Failing closed on any other platform is preferable to emulating it with a
    hard link, because a crash could otherwise leave a writable alias to an
    artifact that is treated as immutable authority.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise PromotionPacketError("immutable_noreplace_unsupported")
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, source_bytes, -100, destination_bytes, 1)
    elif sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise PromotionPacketError("immutable_noreplace_unsupported")
        renamex_np.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source_bytes, destination_bytes, 0x00000004)
    else:
        raise PromotionPacketError("immutable_noreplace_unsupported")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), destination)
    raise OSError(error, os.strerror(error), destination)


def write_immutable_packet(root: Path, output: Path, packet: Mapping[str, Any]) -> str:
    relative = _relative_from_explicit(root, output, label="promotion_packet_output")
    parts = _relative_parts(relative, label="promotion_packet_output")
    destination = root.joinpath(*parts)
    parent_relative = PurePosixPath(*parts[:-1]).as_posix() if len(parts) > 1 else None
    if parent_relative is not None:
        current = root
        for part in _relative_parts(parent_relative, label="promotion_packet_output_parent"):
            current = current / part
            try:
                metadata = os.lstat(current)
            except OSError as exc:
                raise PromotionPacketError("promotion_packet_output_parent_missing") from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise PromotionPacketError("promotion_packet_output_parent_unsafe")
    payload = canonical_file_bytes(packet)
    if destination.exists() or destination.is_symlink():
        existing = read_relative_file(
            root,
            relative,
            label="promotion_packet",
            expected_mode=0o600,
        )
        if existing != payload:
            raise PromotionPacketError("promotion_packet_immutable_collision")
        return "no_change"

    temporary = destination.parent / (
        f".{destination.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        try:
            _rename_noreplace(temporary, destination)
        except FileExistsError:
            existing = read_relative_file(
                root,
                relative,
                label="promotion_packet",
                expected_mode=0o600,
            )
            if existing != payload:
                raise PromotionPacketError("promotion_packet_immutable_collision")
            return "no_change"
        _fsync_directory(destination.parent)
        return "created"
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_promotion_packet(
    *,
    artifact_root: Path,
    artifact_paths: Mapping[str, Path],
    execution_runtime_paths: Mapping[str, Path],
    output: Path,
    site_url: str,
    release_sha256: str,
    data_release_id: str,
    expected_current_release_sha256: str,
    expected_current_data_release_id: str,
    expected_current_data_pointer_sha256: str,
    target_data_pointer_sha256: str,
    generated_at_utc: str,
    expires_at_utc: str,
    nonce: str,
    max_baseline_age_seconds: int,
    v3_release_id: str | None = None,
    v3_source_snapshot_id: str | None = None,
) -> dict[str, Any]:
    root = _require_root(artifact_root)
    release_sha = require_sha256(release_sha256, label="release_sha256")
    expected_current = require_sha256(
        expected_current_release_sha256,
        label="expected_current_release_sha256",
    )
    expected_current_data_pointer = require_sha256(
        expected_current_data_pointer_sha256,
        label="expected_current_data_pointer_sha256",
    )
    target_data_pointer = require_sha256(
        target_data_pointer_sha256,
        label="target_data_pointer_sha256",
    )
    if not isinstance(data_release_id, str) or DATA_RELEASE_RE.fullmatch(data_release_id) is None:
        raise PromotionPacketError("data_release_id_invalid")
    if (
        not isinstance(expected_current_data_release_id, str)
        or DATA_RELEASE_RE.fullmatch(expected_current_data_release_id) is None
    ):
        raise PromotionPacketError("expected_current_data_release_id_invalid")
    if not isinstance(nonce, str) or NONCE_RE.fullmatch(nonce) is None:
        raise PromotionPacketError("nonce_invalid")
    if (
        isinstance(max_baseline_age_seconds, bool)
        or not isinstance(max_baseline_age_seconds, int)
        or not 1 <= max_baseline_age_seconds <= 3600
    ):
        raise PromotionPacketError("max_baseline_age_seconds_invalid")
    generated_value, generated_at = parse_utc(
        generated_at_utc, label="generated_at_utc"
    )
    expires_value, expires_at = parse_utc(expires_at_utc, label="expires_at_utc")
    if expires_at <= generated_at:
        raise PromotionPacketError("expiry_invalid")
    site = _site_url(site_url)
    artifact_path_keys = frozenset(artifact_paths)
    if artifact_path_keys not in {
        LEGACY_ARTIFACT_SET,
        V3_EXTENSION_ARTIFACT_SET,
        V3_NATIVE_ARTIFACT_SET,
    }:
        raise PromotionPacketError("artifact_paths_contract_invalid")

    artifacts: dict[str, dict[str, Any]] = {}
    artifact_payloads: dict[str, bytes] = {}
    seen_paths: set[str] = set()
    if artifact_path_keys == V3_NATIVE_ARTIFACT_SET:
        artifact_keys = V3_NATIVE_ARTIFACT_KEYS
    else:
        artifact_keys = tuple(
            key
            for key in (*ARTIFACT_KEYS, *V3_ARTIFACT_KEYS)
            if key in artifact_paths
        )
    for key in artifact_keys:
        record, payload = _artifact_record(root, Path(artifact_paths[key]), label=key)
        if record["path"] in seen_paths:
            raise PromotionPacketError("artifact_path_duplicate")
        seen_paths.add(record["path"])
        artifacts[key] = record
        artifact_payloads[key] = payload

    if set(execution_runtime_paths) != set(EXECUTION_RUNTIME_KEYS):
        raise PromotionPacketError("execution_runtime_paths_contract_invalid")
    execution_runtime: dict[str, dict[str, Any]] = {}
    for key in EXECUTION_RUNTIME_KEYS:
        record, payload = _artifact_record(
            root,
            Path(execution_runtime_paths[key]),
            label=f"execution_runtime_{key}",
        )
        if record["path"] in seen_paths:
            raise PromotionPacketError("execution_runtime_path_duplicate")
        if PurePosixPath(record["path"]).name != EXECUTION_RUNTIME_FILENAMES[key]:
            raise PromotionPacketError(
                f"execution_runtime_{key}_filename_invalid"
            )
        if not payload:
            raise PromotionPacketError(f"execution_runtime_{key}_empty")
        seen_paths.add(record["path"])
        execution_runtime[key] = record

    _validate_release_manifest(
        _load_object(artifact_payloads["release_manifest"], label="release_manifest"),
        release_sha256=release_sha,
        data_release_id=data_release_id,
        target_data_pointer_sha256=target_data_pointer,
    )
    baseline_bindings = _validate_baseline_receipt(
        _load_object(
            artifact_payloads["production_baseline_receipt"],
            label="production_baseline_receipt",
        ),
        expected_current_release_sha256=expected_current,
        expected_current_data_release_id=expected_current_data_release_id,
        expected_current_data_pointer_sha256=expected_current_data_pointer,
        generated_at=generated_at,
        max_age_seconds=max_baseline_age_seconds,
    )
    v3_lineage = _validate_v3_artifacts(
        artifact_payloads,
        artifacts,
        release_id=v3_release_id,
        source_snapshot_id=v3_source_snapshot_id,
        candidate_release_sha256=release_sha,
        packet_generated_at=generated_at,
    )

    baseline_rollback_bindings = baseline_bindings["rollback"]
    production_baseline_cas = baseline_bindings["cas"]
    identity = {
        "baseline_receipt_sha256": artifacts["production_baseline_receipt"]["sha256"],
        "data_release_id": data_release_id,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "expected_current_data_release_id": expected_current_data_release_id,
        "expires_at_utc": expires_value,
        "execution_runtime": execution_runtime,
        "generated_at_utc": generated_value,
        "nonce": nonce,
        "production_baseline_cas": production_baseline_cas,
        "release_sha256": release_sha,
        "target_data_pointer_sha256": target_data_pointer,
    }
    if v3_lineage is not None:
        identity["v3_lineage"] = v3_lineage
    packet = {
        "artifacts": artifacts,
        "authorization": {
            "allowed_actions": list(ALLOWED_ACTIONS),
            "consumed": False,
            "forbidden_actions": list(FORBIDDEN_ACTIONS),
            "permit_required": True,
            "promotion_authorized": False,
            "required_owner_confirmation": ["packet_sha256", "release_sha256"],
        },
        "deferred_debts": DEFERRED_DEBTS,
        "evidence": {
            "all_artifacts_reopened": True,
            "artifact_count": len(artifact_keys),
            "baseline_max_age_seconds": max_baseline_age_seconds,
            "evidence_grade": "L2-local-candidate-plus-L3-production-read-only-baseline",
        },
        "expires_at_utc": expires_value,
        "execution_runtime": execution_runtime,
        "generated_at_utc": generated_value,
        "nonce": nonce,
        "packet_id": _packet_id(identity),
        "production_baseline_cas": production_baseline_cas,
        "rollback": {
            "readiness_mode": "immediate_same_baseline_window",
            "ready": True,
            "scope": "insights_site_and_data_current",
            "shared_nginx_change_allowed": False,
            "target_data_pointer_sha256": expected_current_data_pointer,
            "target_data_release_id": expected_current_data_release_id,
            **baseline_rollback_bindings,
            "target_release_sha256": expected_current,
            "valid_until_utc": expires_value,
        },
        "schema_version": SCHEMA_VERSION,
        "side_effects": SIDE_EFFECTS,
        "status": "ready_for_owner_authorization",
        "target": {
            "data_release_id": data_release_id,
            "expected_current_data_pointer_sha256": expected_current_data_pointer,
            "expected_current_data_release_id": expected_current_data_release_id,
            "expected_current_release_sha256": expected_current,
            "release_sha256": release_sha,
            "site_url": site,
            "target_data_pointer_sha256": target_data_pointer,
        },
    }
    if v3_lineage is not None:
        packet["v3_lineage"] = v3_lineage
    publication_status = write_immutable_packet(root, output, packet)
    payload = canonical_file_bytes(packet)
    return {
        "data_release_id": data_release_id,
        "deploy": False,
        "expected_current_data_pointer_sha256": expected_current_data_pointer,
        "expected_current_data_release_id": expected_current_data_release_id,
        "packet_path": _relative_from_explicit(root, output, label="promotion_packet_output"),
        "packet_sha256": sha256_bytes(payload),
        "promotion_authorized": False,
        "release_sha256": release_sha,
        "remote_write": False,
        "schema_version": "reddit_voc_promotion_packet_build_result_v1",
        "status": publication_status,
        "target_data_pointer_sha256": target_data_pointer,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    for key in ARTIFACT_KEYS:
        parser.add_argument(f"--{key.replace('_', '-')}", dest=key, type=Path)
    for key in EXECUTION_RUNTIME_KEYS:
        parser.add_argument(
            f"--{key.replace('_', '-')}", dest=key, type=Path, required=True
        )
    parser.add_argument(
        "--candidate-ui-validation-receipt",
        dest="candidate_ui_validation_receipt",
        type=Path,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site-url", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--data-release-id", required=True)
    parser.add_argument("--expected-current-release-sha256", required=True)
    parser.add_argument("--expected-current-data-release-id", required=True)
    parser.add_argument("--expected-current-data-pointer-sha256", required=True)
    parser.add_argument("--target-data-pointer-sha256", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--expires-at-utc", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--max-baseline-age-seconds", type=int, default=900)
    parser.add_argument("--v3-release-id")
    parser.add_argument("--v3-source-snapshot-id")
    parser.add_argument("--v3-artifact", action="append")
    return parser


def _v3_cli_artifacts(values: list[str] | None) -> dict[str, Path]:
    if values is None:
        return {}
    result: dict[str, Path] = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise PromotionPacketError("v3_artifact_argument_invalid")
        key, path = value.split("=", 1)
        if (
            key not in {*V3_ARTIFACT_KEYS, *V3_NATIVE_LINEAGE_ARTIFACT_KEYS}
            or key in result
            or not path
        ):
            raise PromotionPacketError("v3_artifact_argument_invalid")
        result[key] = Path(path)
    return result


def main() -> int:
    args = _parser().parse_args()
    artifact_paths = {
        key: value
        for key in ARTIFACT_KEYS
        if (value := getattr(args, key)) is not None
    }
    if args.candidate_ui_validation_receipt is not None:
        artifact_paths["candidate_ui_validation_receipt"] = (
            args.candidate_ui_validation_receipt
        )
    try:
        artifact_paths.update(_v3_cli_artifacts(args.v3_artifact))
        result = build_promotion_packet(
            artifact_root=args.artifact_root,
            artifact_paths=artifact_paths,
            execution_runtime_paths={
                key: getattr(args, key) for key in EXECUTION_RUNTIME_KEYS
            },
            output=args.output,
            site_url=args.site_url,
            release_sha256=args.release_sha256,
            data_release_id=args.data_release_id,
            expected_current_release_sha256=args.expected_current_release_sha256,
            expected_current_data_release_id=args.expected_current_data_release_id,
            expected_current_data_pointer_sha256=(
                args.expected_current_data_pointer_sha256
            ),
            target_data_pointer_sha256=args.target_data_pointer_sha256,
            generated_at_utc=args.generated_at_utc,
            expires_at_utc=args.expires_at_utc,
            nonce=args.nonce,
            max_baseline_age_seconds=args.max_baseline_age_seconds,
            v3_release_id=args.v3_release_id,
            v3_source_snapshot_id=args.v3_source_snapshot_id,
        )
    except PromotionPacketError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
