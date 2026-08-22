#!/usr/bin/env python3
"""Independently validate a private Plan-A candidate-data closure.

The validator deliberately does not import or call the closure builder.  It
reopens the four detail ledgers, Base roots, downstream manifests, validation
receipts, public projection, and case inventory before writing one immutable
local receipt.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any, Iterable, Mapping, Sequence


RECONCILIATION_SCHEMA = "reddit_voc_candidate_data_reconciliation_v1"
MANIFEST_SCHEMA = "reddit_voc_candidate_data_manifest_v1"
RECEIPT_SCHEMA = "reddit_voc_candidate_data_validation_receipt_v1"
SOURCE_FREEZE_SCHEMA = "reddit_voc_candidate_source_freeze_v1"
LEDGER_MANIFEST_SCHEMA = "reddit_voc_candidate_ledger_manifest_v2"
LEDGER_RECEIPT_SCHEMA = "reddit_voc_candidate_ledger_validation_receipt_v1"
CONFIG_MANIFEST_SCHEMA = "reddit_voc_incremental_candidate_config_manifest_v1"
ANALYTICS_RECEIPT_SCHEMA = "reddit_voc_site_analytics_validation_v1"
PERSONAS_RECEIPT_SCHEMA = "reddit_voc_personas_validation_v1"
CODE_FREEZE_SCHEMA = "reddit_voc_data_build_code_freeze_v1"
PRODUCTION_ACCEPTANCE_SCHEMA = "reddit_voc_production_acceptance_receipt_v1"
BASE_MANIFEST_SCHEMAS = {
    "reddit_voc_site_snapshot_manifest_v1",
    "reddit_voc_site_snapshot_manifest_v2",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEDGER_NAMES = (
    "source-occurrence-ledger.jsonl",
    "post-identity-delta-ledger.jsonl",
    "comment-identity-delta-ledger.jsonl",
    "coverage-work-ledger.jsonl",
)
COPIED_INPUT_NAMES = ("source-freeze-manifest.json", *LEDGER_NAMES)
REQUIRED_PUBLICATION_NAMES = (
    *COPIED_INPUT_NAMES,
    "candidate-data-reconciliation-ledger.jsonl",
    "candidate-data-manifest.json",
)
LEDGER_PRIMARY_KEYS = {
    "source-occurrence-ledger.jsonl": "occurrence_key",
    "post-identity-delta-ledger.jsonl": "post_id",
    "comment-identity-delta-ledger.jsonl": "comment_id",
    "coverage-work-ledger.jsonl": "work_item_key",
}
LEDGER_STATUS_SETS = {
    "source-occurrence-ledger.jsonl": {
        "accepted_new_occurrence",
        "accepted_duplicate_occurrence",
        "superseded_by_precedence",
        "rejected_invalid",
        "quarantined_input",
    },
    "post-identity-delta-ledger.jsonl": {
        "newly_admitted",
        "existing_upgraded",
        "existing_unchanged",
        "pending_lineage",
        "rejected",
    },
    "comment-identity-delta-ledger.jsonl": {
        "new_linked",
        "new_quarantined",
        "existing_upgraded",
        "existing_unchanged",
        "existing_quarantine_relinked",
        "existing_quarantine_retained",
        "rejected",
    },
    "coverage-work-ledger.jsonl": {
        "closed_success",
        "closed_no_more",
        "superseded",
        "retryable_failed",
        "nonretryable_rejected",
        "open_carried",
    },
}
CODE_ALLOWLIST = (
    "scripts/build_public_site_projection.py",
    "scripts/build_reddit_candidate_data_closure.py",
    "scripts/build_reddit_candidate_ledgers.py",
    "scripts/build_reddit_personas_snapshot.py",
    "scripts/build_reddit_semantic_compatibility.py",
    "scripts/build_reddit_site_insights.py",
    "scripts/build_reddit_site_snapshot.py",
    "scripts/materialize_reddit_incremental_configs.py",
    "scripts/validate_public_site_projection.py",
    "scripts/validate_reddit_candidate_data_closure.py",
    "scripts/validate_reddit_candidate_ledgers.py",
    "scripts/validate_reddit_personas_snapshot.py",
    "scripts/validate_reddit_site_analytics.py",
    "scripts/validate_reddit_site_snapshot.py",
    "src/reddit_voc/risk_report_contracts.py",
)
BOUNDARIES = {
    "provider_call": False,
    "provider_attempt_made": False,
    "database_write": False,
    "remote_write": False,
    "production_merge": False,
    "deployment": False,
    "deploy": False,
    "live_send": False,
    "webhook_send": False,
    "schedule_change": False,
    "collector_change": False,
    "production_unchanged": True,
}
SIDE_EFFECT_KEYS = {
    "provider_call",
    "provider_attempt_made",
    "database_write",
    "remote_write",
    "production_merge",
    "deployment",
    "deploy",
    "live_send",
    "webhook_send",
    "schedule_change",
    "collector_change",
}
SELF_HASH_FIELDS = {
    "reconciliation_sha256",
    "candidate_data_manifest_sha256",
    "candidate_data_validation_receipt_sha256",
}


class CandidateDataClosureValidationError(ValueError):
    """One independently checked closure invariant failed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_sha256(values: Iterable[str]) -> str:
    payload = "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    return _sha256_bytes(payload)


def _reject_traversal(path: Path, *, label: str) -> None:
    if ".." in path.parts:
        raise CandidateDataClosureValidationError(f"{label}_path_traversal")


def _regular_file(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    _reject_traversal(path, label=label)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateDataClosureValidationError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateDataClosureValidationError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise CandidateDataClosureValidationError(f"{label}_mode_invalid")
    return metadata


def _directory(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    _reject_traversal(path, label=label)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateDataClosureValidationError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CandidateDataClosureValidationError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise CandidateDataClosureValidationError(f"{label}_mode_invalid")
    return metadata


def _load_json(path: Path, *, label: str, canonical: bool = False) -> dict[str, Any]:
    _regular_file(path, label=label)
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateDataClosureValidationError(f"{label}_invalid") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CandidateDataClosureValidationError(f"{label}_invalid")
    if canonical and payload != _canonical_bytes(value) + b"\n":
        raise CandidateDataClosureValidationError(f"{label}_noncanonical")
    return value


def _expected_file(path: Path, expected: str, *, label: str, mode: int | None = None) -> str:
    if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
        raise CandidateDataClosureValidationError(f"{label}_expected_sha256_invalid")
    _regular_file(path, label=label, mode=mode)
    actual = _file_sha256(path)
    if actual != expected:
        raise CandidateDataClosureValidationError(f"{label}_sha256_mismatch")
    return actual


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateDataClosureValidationError(f"{label}_path_invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise CandidateDataClosureValidationError(f"{label}_path_invalid")
    return value


def _assert_side_effect_boundaries(value: object, *, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SIDE_EFFECT_KEYS and child is not False:
                raise CandidateDataClosureValidationError(
                    f"{label}_side_effect_boundary_invalid"
                )
            _assert_side_effect_boundaries(child, label=label)
    elif isinstance(value, list):
        for child in value:
            _assert_side_effect_boundaries(child, label=label)


def _assert_no_self_hash(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SELF_HASH_FIELDS:
                raise CandidateDataClosureValidationError("reconciliation_self_hash_present")
            _assert_no_self_hash(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_self_hash(child)


def _validate_file_contracts(root: Path, manifest: Mapping[str, Any], *, label: str) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise CandidateDataClosureValidationError(f"{label}_files_invalid")
    for name, contract in files.items():
        relative = _safe_relative(name, label=f"{label}_file")
        if not isinstance(contract, dict):
            raise CandidateDataClosureValidationError(f"{label}_file_contract_invalid")
        path = root / relative
        metadata = _regular_file(path, label=f"{label}_file")
        if (
            contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(path)
        ):
            raise CandidateDataClosureValidationError(f"{label}_file_binding_invalid")


def _load_entity_rows(path: Path, *, label: str) -> list[dict[str, Any]]:
    _regular_file(path, label=label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateDataClosureValidationError(f"{label}_invalid") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise CandidateDataClosureValidationError(f"{label}_invalid")
    return value


def _unique_ids(rows: Sequence[Mapping[str, Any]], field: str, *, label: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        value = row.get(field)
        if not isinstance(value, str) or not value or value in result:
            raise CandidateDataClosureValidationError(f"{label}_identity_invalid")
        result.add(value)
    return result


def _validate_base(
    root: Path,
    expected_manifest_sha256: str,
    *,
    label: str,
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    _directory(root, label=label)
    manifest_path = root / "manifest.json"
    _expected_file(manifest_path, expected_manifest_sha256, label=f"{label}_manifest")
    manifest = _load_json(manifest_path, label=f"{label}_manifest")
    if manifest.get("schema_version") not in BASE_MANIFEST_SCHEMAS:
        raise CandidateDataClosureValidationError(f"{label}_schema_invalid")
    if manifest.get("all_checks_passed") is not True:
        raise CandidateDataClosureValidationError(f"{label}_checks_invalid")
    _validate_file_contracts(root, manifest, label=label)
    posts = _load_entity_rows(root / "posts.json", label=f"{label}_posts")
    comments = _load_entity_rows(root / "comments.json", label=f"{label}_comments")
    quarantine = _load_entity_rows(root / "quarantine.json", label=f"{label}_quarantine")
    post_ids = _unique_ids(posts, "post_id", label=f"{label}_posts")
    linked_ids = _unique_ids(comments, "comment_id", label=f"{label}_comments")
    quarantine_ids = _unique_ids(quarantine, "comment_id", label=f"{label}_quarantine")
    if linked_ids & quarantine_ids:
        raise CandidateDataClosureValidationError(f"{label}_comment_overlap")
    if any(row.get("post_id") not in post_ids for row in comments):
        raise CandidateDataClosureValidationError(f"{label}_linked_parent_missing")
    counts = manifest.get("canonical_counts")
    expected_counts = {
        "posts": len(post_ids),
        "linked_comments": len(linked_ids),
        "quarantined_comments": len(quarantine_ids),
        "stored_comments": len(linked_ids | quarantine_ids),
    }
    if not isinstance(counts, dict) or any(counts.get(key) != value for key, value in expected_counts.items()):
        raise CandidateDataClosureValidationError(f"{label}_counts_invalid")
    if (
        manifest.get("provider_call") is not False
        or manifest.get("live_send") is not False
        or manifest.get("production_unchanged") is not True
    ):
        raise CandidateDataClosureValidationError(f"{label}_boundary_invalid")
    return manifest, {
        "posts": post_ids,
        "linked": linked_ids,
        "quarantine": quarantine_ids,
        "comments": linked_ids | quarantine_ids,
    }


def _load_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    _regular_file(path, label=label)
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise CandidateDataClosureValidationError(f"{label}_noncanonical")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(payload.splitlines(keepends=True)):
        try:
            value = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateDataClosureValidationError(f"{label}_invalid") from exc
        if not isinstance(value, dict) or line != _canonical_bytes(value) + b"\n":
            raise CandidateDataClosureValidationError(f"{label}_noncanonical")
        if not all(isinstance(key, str) for key in value):
            raise CandidateDataClosureValidationError(f"{label}_invalid")
        rows.append(value)
    return rows


def _identity_contract(values: set[str]) -> dict[str, Any]:
    return {"count": len(values), "ids_lf_sha256": _identity_sha256(values)}


def _validate_ledgers(
    root: Path,
    expected_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    source_sha256: str,
    baseline_sha256: str,
    candidate_sha256: str,
    baseline_sets: Mapping[str, set[str]],
    candidate_sets: Mapping[str, set[str]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    _directory(root, label="ledger_root")
    manifest_path = root / "candidate-ledger-manifest.json"
    _expected_file(manifest_path, expected_manifest_sha256, label="ledger_manifest")
    manifest = _load_json(manifest_path, label="ledger_manifest")
    if (
        manifest.get("schema_version") != LEDGER_MANIFEST_SCHEMA
        or manifest.get("status") != "a2_identity_closed_with_explicit_coverage_debt"
    ):
        raise CandidateDataClosureValidationError("ledger_manifest_status_invalid")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or (
        inputs.get("source_freeze_manifest_sha256") != source_sha256
        or inputs.get("production_baseline_manifest_sha256") != baseline_sha256
        or inputs.get("candidate_base_manifest_sha256") != candidate_sha256
    ):
        raise CandidateDataClosureValidationError("ledger_input_lineage_invalid")
    input_evidence = manifest.get("input_evidence_sha256")
    cutoff = manifest.get("source_cutoff_utc")
    if (
        not isinstance(input_evidence, str)
        or SHA256_RE.fullmatch(input_evidence) is None
        or not isinstance(cutoff, str)
        or not cutoff.endswith("Z")
    ):
        raise CandidateDataClosureValidationError("ledger_input_evidence_invalid")
    contracts = manifest.get("ledgers")
    if not isinstance(contracts, dict) or set(contracts) != set(LEDGER_NAMES):
        raise CandidateDataClosureValidationError("ledger_inventory_invalid")
    ledger_rows: dict[str, list[dict[str, Any]]] = {}
    for name in LEDGER_NAMES:
        path = root / name
        rows = _load_jsonl(path, label=name)
        contract = contracts.get(name)
        metadata = _regular_file(path, label=name)
        if (
            not isinstance(contract, dict)
            or contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(path)
            or contract.get("rows") != len(rows)
        ):
            raise CandidateDataClosureValidationError("ledger_file_binding_invalid")
        primary_key = LEDGER_PRIMARY_KEYS[name]
        seen: set[str] = set()
        for row in rows:
            key = row.get(primary_key)
            if not isinstance(key, str) or not key or key in seen:
                raise CandidateDataClosureValidationError("ledger_primary_key_invalid")
            seen.add(key)
            if row.get("status") not in LEDGER_STATUS_SETS[name]:
                raise CandidateDataClosureValidationError("ledger_status_invalid")
            if row.get("input_evidence_sha256") != input_evidence or row.get("source_cutoff_utc") != cutoff:
                raise CandidateDataClosureValidationError("ledger_row_lineage_invalid")
        ledger_rows[name] = rows

    p0 = baseline_sets["posts"]
    p1 = candidate_sets["posts"]
    l0 = baseline_sets["linked"]
    l1 = candidate_sets["linked"]
    q0 = baseline_sets["quarantine"]
    q1 = candidate_sets["quarantine"]
    c0 = baseline_sets["comments"]
    c1 = candidate_sets["comments"]
    expected_identity_sets = {
        "p0": _identity_contract(p0),
        "p1": _identity_contract(p1),
        "l0": _identity_contract(l0),
        "l1": _identity_contract(l1),
        "q0": _identity_contract(q0),
        "q1": _identity_contract(q1),
        "c0": _identity_contract(c0),
        "c1": _identity_contract(c1),
    }
    if manifest.get("identity_sets") != expected_identity_sets:
        raise CandidateDataClosureValidationError("ledger_identity_sets_invalid")
    if not p0 <= p1 or not c0 <= c1 or l1 & q1:
        raise CandidateDataClosureValidationError("ledger_set_conservation_invalid")

    post_rows = ledger_rows["post-identity-delta-ledger.jsonl"]
    comment_rows = ledger_rows["comment-identity-delta-ledger.jsonl"]
    occurrence_rows = ledger_rows["source-occurrence-ledger.jsonl"]
    coverage_rows = ledger_rows["coverage-work-ledger.jsonl"]
    post_map = {str(row["post_id"]): row for row in post_rows}
    comment_map = {str(row["comment_id"]): row for row in comment_rows}
    if not p1 <= set(post_map) or not c1 <= set(comment_map):
        raise CandidateDataClosureValidationError("ledger_candidate_identity_unaccounted")
    if {key for key, row in post_map.items() if row["status"] == "newly_admitted"} != p1 - p0:
        raise CandidateDataClosureValidationError("ledger_net_new_posts_invalid")
    if {
        key
        for key, row in comment_map.items()
        if row["status"] in {"new_linked", "new_quarantined"}
    } != c1 - c0:
        raise CandidateDataClosureValidationError("ledger_net_new_comments_invalid")
    if {
        key
        for key, row in comment_map.items()
        if row["status"] == "existing_quarantine_relinked"
    } != q0 & l1:
        raise CandidateDataClosureValidationError("ledger_quarantine_relink_invalid")

    accounting = manifest.get("accounting")
    if not isinstance(accounting, dict) or accounting.get("unaccounted_total") != 0:
        raise CandidateDataClosureValidationError("ledger_unaccounted_invalid")
    expected_counters = {
        "source_occurrences": Counter(str(row["status"]) for row in occurrence_rows),
        "posts": Counter(str(row["status"]) for row in post_rows),
        "comments": Counter(str(row["status"]) for row in comment_rows),
        "coverage": Counter(str(row["status"]) for row in coverage_rows),
    }
    expected_totals = {
        "source_occurrences": len(occurrence_rows),
        "posts": len(post_rows),
        "comments": len(comment_rows),
        "coverage": len(coverage_rows),
    }
    for section, counter in expected_counters.items():
        value = accounting.get(section)
        if not isinstance(value, dict) or value.get("status_counts") != dict(counter):
            raise CandidateDataClosureValidationError("ledger_status_counts_invalid")
        if value.get("unaccounted") != 0:
            raise CandidateDataClosureValidationError("ledger_unaccounted_invalid")
        if section in {"source_occurrences", "coverage"} and value.get("total") != expected_totals[section]:
            raise CandidateDataClosureValidationError("ledger_total_invalid")
    posts_accounting = accounting["posts"]
    comments_accounting = accounting["comments"]
    if (
        posts_accounting.get("baseline") != len(p0)
        or posts_accounting.get("candidate") != len(p1)
        or posts_accounting.get("release_net_new") != len(p1 - p0)
        or comments_accounting.get("baseline") != len(c0)
        or comments_accounting.get("candidate") != len(c1)
        or comments_accounting.get("release_net_new") != len(c1 - c0)
    ):
        raise CandidateDataClosureValidationError("ledger_delta_accounting_invalid")
    relations = manifest.get("set_relations")
    if not isinstance(relations, dict) or any(
        relations.get(field) is not True
        for field in (
            "p0_subset_p1",
            "c0_subset_c1",
            "l1_intersection_q1_empty",
            "all_linked_comment_parents_exist",
        )
    ):
        raise CandidateDataClosureValidationError("ledger_set_relations_invalid")
    _assert_side_effect_boundaries(manifest, label="ledger_manifest")
    if manifest.get("production_unchanged") is not True:
        raise CandidateDataClosureValidationError("ledger_production_boundary_invalid")

    _expected_file(receipt_path, expected_receipt_sha256, label="ledger_receipt")
    receipt = _load_json(receipt_path, label="ledger_receipt")
    if (
        receipt.get("schema_version") != LEDGER_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("candidate_ledger_manifest_sha256") != expected_manifest_sha256
        or receipt.get("identity_sets") != expected_identity_sets
    ):
        raise CandidateDataClosureValidationError("ledger_receipt_lineage_invalid")
    receipt_counts = receipt.get("counts")
    if not isinstance(receipt_counts, dict) or (
        receipt_counts.get("source_occurrences") != len(occurrence_rows)
        or receipt_counts.get("post_rows") != len(post_rows)
        or receipt_counts.get("comment_rows") != len(comment_rows)
        or receipt_counts.get("coverage_rows") != len(coverage_rows)
        or receipt_counts.get("release_net_new_posts") != len(p1 - p0)
        or receipt_counts.get("release_net_new_comments") != len(c1 - c0)
        or receipt_counts.get("unaccounted_total") != 0
    ):
        raise CandidateDataClosureValidationError("ledger_receipt_counts_invalid")
    _assert_side_effect_boundaries(receipt, label="ledger_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureValidationError("ledger_receipt_boundary_invalid")
    return manifest, receipt, ledger_rows


def _validate_candidate_copies(
    *,
    candidate_root: Path,
    candidate_manifest: Mapping[str, Any],
    source_path: Path,
    source_sha256: str,
    ledger_root: Path,
    ledger_manifest: Mapping[str, Any],
    external_ledger_rows: Mapping[str, list[dict[str, Any]]],
    reconciliation_contract: Mapping[str, Any],
) -> None:
    ledger_contracts = ledger_manifest.get("ledgers")
    if not isinstance(ledger_contracts, dict):
        raise CandidateDataClosureValidationError("ledger_inventory_invalid")
    source_metadata = _regular_file(source_path, label="source_freeze_manifest")
    expected_contracts: dict[str, Any] = {
        "source-freeze-manifest.json": {
            "bytes": source_metadata.st_size,
            "sha256": source_sha256,
        },
        **deepcopy(ledger_contracts),
        "candidate-data-reconciliation-ledger.jsonl": {
            key: reconciliation_contract.get(key)
            for key in ("bytes", "rows", "sha256")
        },
    }
    files = candidate_manifest.get("files")
    if files != expected_contracts:
        raise CandidateDataClosureValidationError(
            "candidate_manifest_file_contracts_invalid"
        )

    copied_source = candidate_root / "source-freeze-manifest.json"
    _regular_file(copied_source, label="copied_source_freeze", mode=0o600)
    if copied_source.read_bytes() != source_path.read_bytes():
        raise CandidateDataClosureValidationError("copied_source_freeze_drift")
    _load_json(copied_source, label="copied_source_freeze", canonical=True)

    for name in LEDGER_NAMES:
        external_path = ledger_root / name
        copied_path = candidate_root / name
        _regular_file(copied_path, label="copied_ledger", mode=0o600)
        if copied_path.read_bytes() != external_path.read_bytes():
            raise CandidateDataClosureValidationError("copied_ledger_drift")
        copied_rows = _load_jsonl(copied_path, label=f"copied_{name}")
        if copied_rows != external_ledger_rows[name]:
            raise CandidateDataClosureValidationError("copied_ledger_rows_drift")
        contract = expected_contracts[name]
        metadata = _regular_file(copied_path, label="copied_ledger", mode=0o600)
        if (
            not isinstance(contract, dict)
            or contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(copied_path)
            or contract.get("rows") != len(copied_rows)
        ):
            raise CandidateDataClosureValidationError(
                "copied_ledger_contract_invalid"
            )


def _code_file_path(root: Path, relative: str) -> Path:
    _directory(root, label="code_root")
    pure = PurePosixPath(relative)
    current = root
    for part in pure.parts[:-1]:
        current = current / part
        _directory(current, label="code_parent")
    target = root / relative
    _regular_file(target, label="code_file")
    return target


def _validate_code_freeze(
    path: Path, expected_sha256: str, code_root: Path
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="code_freeze_manifest")
    manifest = _load_json(path, label="code_freeze_manifest")
    if (
        manifest.get("schema_version") != CODE_FREEZE_SCHEMA
        or manifest.get("allowlist_version") != "plan_a_data_build_v1"
    ):
        raise CandidateDataClosureValidationError("code_freeze_schema_invalid")
    cutoff = manifest.get("code_cutoff_utc")
    files = manifest.get("files")
    if not isinstance(cutoff, str) or not cutoff.endswith("Z"):
        raise CandidateDataClosureValidationError("code_cutoff_utc_invalid")
    if not isinstance(files, dict) or set(files) != set(CODE_ALLOWLIST):
        raise CandidateDataClosureValidationError("code_allowlist_invalid")
    for relative, contract in files.items():
        _safe_relative(relative, label="code_allowlist")
        if (
            not isinstance(contract, dict)
            or not isinstance(contract.get("bytes"), int)
            or isinstance(contract.get("bytes"), bool)
            or contract["bytes"] < 0
            or not isinstance(contract.get("sha256"), str)
            or SHA256_RE.fullmatch(contract["sha256"]) is None
        ):
            raise CandidateDataClosureValidationError("code_file_contract_invalid")
        code_path = _code_file_path(code_root, relative)
        metadata = _regular_file(code_path, label="code_file")
        if (
            contract.get("bytes") != metadata.st_size
            or contract.get("sha256") != _file_sha256(code_path)
        ):
            raise CandidateDataClosureValidationError("code_file_binding_invalid")
    if manifest.get("boundaries") != BOUNDARIES:
        raise CandidateDataClosureValidationError("code_freeze_boundaries_invalid")
    _assert_side_effect_boundaries(manifest.get("boundaries"), label="code_freeze")
    return manifest


def _validate_config(
    path: Path,
    expected_sha256: str,
    *,
    base_sha256: str,
    ledger_sha256: str,
    ledger_receipt_sha256: str,
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="config_manifest")
    manifest = _load_json(path, label="config_manifest")
    if manifest.get("schema_version") != CONFIG_MANIFEST_SCHEMA:
        raise CandidateDataClosureValidationError("config_schema_invalid")
    gate = manifest.get("identity_gate")
    if not isinstance(gate, dict) or (
        gate.get("candidate_base_manifest_sha256") != base_sha256
        or gate.get("candidate_ledger_manifest_sha256") != ledger_sha256
        or gate.get("ledger_validation_receipt_sha256") != ledger_receipt_sha256
        or gate.get("unaccounted_total") != 0
    ):
        raise CandidateDataClosureValidationError("config_identity_gate_invalid")
    _validate_file_contracts(path.parent, manifest, label="config")
    _assert_side_effect_boundaries(manifest, label="config")
    return manifest


def _validate_analytics(
    insights_root: Path,
    expected_insights_sha256: str,
    reports_root: Path,
    expected_reports_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    base_sha256: str,
    ledger_sha256: str,
    ledger_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _directory(insights_root, label="insights_root")
    _directory(reports_root, label="reports_root")
    insights_path = insights_root / "manifest.json"
    reports_path = reports_root / "manifest.json"
    _expected_file(insights_path, expected_insights_sha256, label="insights_manifest")
    _expected_file(reports_path, expected_reports_sha256, label="reports_manifest")
    insights = _load_json(insights_path, label="insights_manifest")
    reports = _load_json(reports_path, label="reports_manifest")
    if (
        insights.get("schema_version") != "reddit_voc_insights_manifest_v1"
        or insights.get("base_manifest_sha256") != base_sha256
    ):
        raise CandidateDataClosureValidationError("insights_lineage_invalid")
    if (
        reports.get("schema_version") != "reddit_voc_reports_manifest_v1"
        or reports.get("base_manifest_sha256") != base_sha256
        or reports.get("insights_manifest_sha256") != expected_insights_sha256
    ):
        raise CandidateDataClosureValidationError("reports_lineage_invalid")
    for root, value, label in (
        (insights_root, insights, "insights"),
        (reports_root, reports, "reports"),
    ):
        gate = value.get("identity_gate")
        if not isinstance(gate, dict) or (
            gate.get("candidate_ledger_manifest_sha256") != ledger_sha256
            or gate.get("ledger_validation_receipt_sha256") != ledger_receipt_sha256
            or gate.get("unaccounted_total") != 0
        ):
            raise CandidateDataClosureValidationError(f"{label}_identity_gate_invalid")
        _validate_file_contracts(root, value, label=label)
        _assert_side_effect_boundaries(value, label=label)
        boundaries = value.get("boundaries")
        if not isinstance(boundaries, dict) or boundaries.get("production_unchanged") is not True:
            raise CandidateDataClosureValidationError(f"{label}_boundary_invalid")
    _expected_file(receipt_path, expected_receipt_sha256, label="analytics_receipt")
    receipt = _load_json(receipt_path, label="analytics_receipt")
    if (
        receipt.get("schema_version") != ANALYTICS_RECEIPT_SCHEMA
        or receipt.get("status") != "passed_release_candidate"
        or receipt.get("base_manifest_sha256") != base_sha256
        or receipt.get("insights_manifest_sha256") != expected_insights_sha256
        or receipt.get("reports_manifest_sha256") != expected_reports_sha256
    ):
        raise CandidateDataClosureValidationError("analytics_receipt_lineage_invalid")
    _assert_side_effect_boundaries(receipt, label="analytics_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureValidationError("analytics_receipt_boundary_invalid")
    return insights, reports, receipt


def _validate_personas(
    root: Path,
    expected_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    base_sha256: str,
    insights_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _directory(root, label="personas_root")
    manifest_path = root / "manifest.json"
    _expected_file(manifest_path, expected_manifest_sha256, label="personas_manifest")
    manifest = _load_json(manifest_path, label="personas_manifest")
    if (
        manifest.get("schema_version") != "reddit_voc_personas_manifest_v1"
        or manifest.get("base_manifest_sha256") != base_sha256
        or manifest.get("insights_manifest_sha256") != insights_sha256
    ):
        raise CandidateDataClosureValidationError("personas_lineage_invalid")
    _validate_file_contracts(root, manifest, label="personas")
    _assert_side_effect_boundaries(manifest, label="personas")
    boundaries = manifest.get("boundaries")
    if not isinstance(boundaries, dict) or boundaries.get("production_unchanged") is not True:
        raise CandidateDataClosureValidationError("personas_boundary_invalid")
    _expected_file(receipt_path, expected_receipt_sha256, label="personas_receipt")
    receipt = _load_json(receipt_path, label="personas_receipt")
    if (
        receipt.get("schema_version") != PERSONAS_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("manifest_sha256") != expected_manifest_sha256
        or receipt.get("base_manifest_sha256") != base_sha256
        or receipt.get("insights_manifest_sha256") != insights_sha256
    ):
        raise CandidateDataClosureValidationError("personas_receipt_lineage_invalid")
    _assert_side_effect_boundaries(receipt, label="personas_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureValidationError("personas_receipt_boundary_invalid")
    return manifest, receipt


def _public_inventory(root: Path) -> tuple[int, int, str]:
    _directory(root, label="public_root")
    rows: list[tuple[str, int, str]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise CandidateDataClosureValidationError("public_tree_symlink")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise CandidateDataClosureValidationError("public_tree_unsafe")
        rows.append((relative, metadata.st_size, _file_sha256(path)))
        total_bytes += metadata.st_size
    if not rows:
        raise CandidateDataClosureValidationError("public_tree_empty")
    payload = "".join(f"{path}\t{size}\t{digest}\n" for path, size, digest in rows).encode("utf-8")
    return len(rows), total_bytes, _sha256_bytes(payload)


def _validate_public(
    root: Path,
    expected_inventory_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    *,
    base: Mapping[str, Any],
    base_sha256: str,
    insights: Mapping[str, Any],
    insights_sha256: str,
    reports: Mapping[str, Any],
    reports_sha256: str,
    personas: Mapping[str, Any],
    personas_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    file_count, total_bytes, inventory_sha = _public_inventory(root)
    if inventory_sha != expected_inventory_sha256:
        raise CandidateDataClosureValidationError("public_inventory_sha256_mismatch")
    versions = {
        "base": base.get("dataset_version"),
        "insights": insights.get("dataset_version"),
        "reports": reports.get("dataset_version"),
        "personas": personas.get("dataset_version"),
    }
    if not all(isinstance(value, str) and value for value in versions.values()):
        raise CandidateDataClosureValidationError("public_version_invalid")
    manifest_paths = {
        "base": root / "data" / "reddit-voc" / str(versions["base"]) / "manifest-public.json",
        "insights": root / "data" / "reddit-voc" / str(versions["insights"]) / "public" / "manifest.json",
        "reports": root / "data" / "reddit-voc" / str(versions["reports"]) / "public" / "manifest.json",
        "personas": root / "data" / "reddit-voc" / str(versions["personas"]) / "manifest.json",
    }
    manifests: dict[str, dict[str, Any]] = {}
    manifest_hashes: dict[str, str] = {}
    for label, path in manifest_paths.items():
        manifests[label] = _load_json(path, label=f"public_{label}_manifest")
        manifest_hashes[label] = _file_sha256(path)
        _validate_file_contracts(path.parent, manifests[label], label=f"public_{label}")
        _assert_side_effect_boundaries(manifests[label], label=f"public_{label}")
        boundaries = manifests[label].get("boundaries")
        if boundaries is not None and (
            not isinstance(boundaries, dict)
            or boundaries.get("production_unchanged") is not True
        ):
            raise CandidateDataClosureValidationError(f"public_{label}_boundary_invalid")
    if manifests["base"].get("dataset_version") != versions["base"]:
        raise CandidateDataClosureValidationError("public_base_version_invalid")
    for label in ("insights", "reports", "personas"):
        if manifests[label].get("base_manifest_sha256") != base_sha256:
            raise CandidateDataClosureValidationError("public_base_lineage_invalid")
        if manifests[label].get("dataset_version") != versions[label]:
            raise CandidateDataClosureValidationError("public_dataset_version_invalid")
    if (
        manifests["reports"].get("insights_manifest_sha256") != insights_sha256
        or manifests["personas"].get("insights_manifest_sha256") != insights_sha256
    ):
        raise CandidateDataClosureValidationError("public_insights_lineage_invalid")

    _expected_file(receipt_path, expected_receipt_sha256, label="public_validation_receipt")
    receipt = _load_json(receipt_path, label="public_validation_receipt")
    if (
        receipt.get("schema_version")
        != "reddit_voc_public_projection_validation_v1"
        or receipt.get("status") != "passed_release_candidate"
    ):
        raise CandidateDataClosureValidationError(
            "public_validation_receipt_status_invalid"
        )
    if receipt.get("public_inventory") != {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_sha,
    }:
        raise CandidateDataClosureValidationError(
            "public_validation_receipt_inventory_invalid"
        )
    expected_lineage = {
        "base": {
            "dataset_version": versions["base"],
            "private_manifest_sha256": base_sha256,
            "public_manifest_sha256": manifest_hashes["base"],
        },
        "insights": {
            "dataset_version": versions["insights"],
            "private_manifest_sha256": insights_sha256,
            "public_manifest_sha256": manifest_hashes["insights"],
        },
        "reports": {
            "dataset_version": versions["reports"],
            "private_manifest_sha256": reports_sha256,
            "public_manifest_sha256": manifest_hashes["reports"],
        },
        "personas": {
            "dataset_version": versions["personas"],
            "private_manifest_sha256": personas_sha256,
            "public_manifest_sha256": manifest_hashes["personas"],
        },
    }
    if receipt.get("lineage") != expected_lineage:
        raise CandidateDataClosureValidationError("public_validation_receipt_lineage_invalid")
    _assert_side_effect_boundaries(receipt, label="public_validation_receipt")
    if receipt.get("production_unchanged") is not True:
        raise CandidateDataClosureValidationError("public_validation_receipt_boundary_invalid")
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "inventory_sha256": inventory_sha,
        "manifest_sha256": manifest_hashes,
    }, receipt


def _validate_cases(
    manifest_path: Path,
    expected_manifest_sha256: str,
    index_path: Path,
    expected_index_sha256: str,
) -> dict[str, Any]:
    _expected_file(manifest_path, expected_manifest_sha256, label="cases_manifest")
    _expected_file(index_path, expected_index_sha256, label="cases_index")
    manifest = _load_json(manifest_path, label="cases_manifest")
    index = _load_json(index_path, label="cases_index")
    if manifest.get("schemaVersion") != 1 or index.get("schemaVersion") != 1:
        raise CandidateDataClosureValidationError("cases_schema_invalid")
    if manifest.get("datasetVersion") != index.get("datasetVersion"):
        raise CandidateDataClosureValidationError("cases_version_invalid")
    seed = manifest.get("seed")
    legacy = manifest.get("legacyUnverified")
    delta = manifest.get("approvedDelta")
    approved = index.get("approvedDelta")
    if not isinstance(seed, dict) or seed.get("count") != 38:
        raise CandidateDataClosureValidationError("cases_selected_count_invalid")
    if not isinstance(legacy, dict) or legacy.get("count") != 12:
        raise CandidateDataClosureValidationError("cases_unverified_count_invalid")
    if not isinstance(delta, dict) or not isinstance(approved, list) or delta.get("count") != len(approved):
        raise CandidateDataClosureValidationError("cases_delta_count_invalid")
    if len(approved) != 0 or delta.get("contentSha256") != _sha256_bytes(_canonical_bytes(approved)):
        raise CandidateDataClosureValidationError("cases_delta_invalid")
    index_contract = manifest.get("index")
    if not isinstance(index_contract, dict) or index_contract.get("sha256") != expected_index_sha256:
        raise CandidateDataClosureValidationError("cases_index_lineage_invalid")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("networkSearch") is not False:
        raise CandidateDataClosureValidationError("cases_network_boundary_invalid")
    return {
        "dataset_version": manifest.get("datasetVersion"),
        "selected_count": 38,
        "unverified_count": 12,
        "approved_delta_count": 0,
        "manifest_sha256": expected_manifest_sha256,
        "index_sha256": expected_index_sha256,
        "seed_content_sha256": seed.get("contentSha256"),
        "legacy_unverified_content_sha256": legacy.get("contentSha256"),
        "approved_delta_content_sha256": delta.get("contentSha256"),
    }


def _validate_production_acceptance(
    path: Path,
    expected_sha256: str,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    _expected_file(path, expected_sha256, label="production_acceptance_receipt")
    receipt = _load_json(path, label="production_acceptance_receipt")
    if (
        receipt.get("schema_version") != PRODUCTION_ACCEPTANCE_SCHEMA
        or receipt.get("status") != "production_accepted_with_explicit_coverage_debt"
    ):
        raise CandidateDataClosureValidationError("production_acceptance_status_invalid")
    release = receipt.get("release")
    datasets = receipt.get("datasets")
    if (
        not isinstance(release, dict)
        or not isinstance(release.get("current_production_release_sha256"), str)
        or SHA256_RE.fullmatch(release["current_production_release_sha256"]) is None
        or not isinstance(datasets, dict)
        or datasets.get("base") != baseline.get("dataset_version")
    ):
        raise CandidateDataClosureValidationError("production_acceptance_lineage_invalid")
    counts = baseline.get("canonical_counts")
    if not isinstance(counts, dict):
        raise CandidateDataClosureValidationError("production_baseline_counts_invalid")
    for receipt_key, base_key in (
        ("published_posts", "posts"),
        ("linked_comments", "linked_comments"),
        ("stored_comments", "stored_comments"),
        ("quarantined_comments", "quarantined_comments"),
    ):
        if datasets.get(receipt_key) != counts.get(base_key):
            raise CandidateDataClosureValidationError("production_acceptance_counts_invalid")
    return receipt


def _candidate_input(
    *,
    source_sha256: str,
    baseline_sha256: str,
    config_sha256: str,
    code_sha256: str,
) -> tuple[dict[str, str], str]:
    value = {
        "code_freeze_manifest_sha256": code_sha256,
        "config_manifest_sha256": config_sha256,
        "production_baseline_manifest_sha256": baseline_sha256,
        "source_freeze_manifest_sha256": source_sha256,
    }
    return value, _sha256_bytes(_canonical_bytes(value))


def _coverage_transition(accounting: Mapping[str, Any]) -> dict[str, Any]:
    coverage = accounting.get("coverage")
    if not isinstance(coverage, dict):
        raise CandidateDataClosureValidationError("coverage_accounting_invalid")
    total = coverage.get("total")
    statuses = coverage.get("status_counts")
    if not isinstance(total, int) or not isinstance(statuses, dict):
        raise CandidateDataClosureValidationError("coverage_accounting_invalid")
    open_count = sum(
        value
        for key, value in statuses.items()
        if key in {"retryable_failed", "open_carried"} and isinstance(value, int)
    )
    return {
        "before": {"frozen_work_items": total},
        "after": {
            "open_work_items": open_count,
            "terminal_work_items": total - open_count,
            "status_counts": deepcopy(statuses),
        },
    }


def _validate_closure_documents(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate_root = Path(args.candidate_root)
    _directory(candidate_root, label="candidate_root", mode=0o700)
    allowed_members = {
        *REQUIRED_PUBLICATION_NAMES,
        "candidate-data-validation-receipt.json",
    }
    members = {path.name for path in candidate_root.iterdir()}
    if not set(REQUIRED_PUBLICATION_NAMES) <= members or not members <= allowed_members:
        raise CandidateDataClosureValidationError("candidate_root_inventory_invalid")
    manifest_path = candidate_root / "candidate-data-manifest.json"
    reconciliation_path = candidate_root / "candidate-data-reconciliation-ledger.jsonl"
    _expected_file(
        manifest_path,
        args.expected_candidate_data_manifest_sha256,
        label="candidate_data_manifest",
        mode=0o600,
    )
    _expected_file(
        reconciliation_path,
        args.expected_reconciliation_sha256,
        label="candidate_data_reconciliation",
        mode=0o600,
    )
    manifest = _load_json(manifest_path, label="candidate_data_manifest", canonical=True)
    rows = _load_jsonl(reconciliation_path, label="candidate_data_reconciliation")
    if len(rows) != 1:
        raise CandidateDataClosureValidationError("reconciliation_row_count_invalid")
    reconciliation = rows[0]
    _assert_no_self_hash(reconciliation)
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("status") != "candidate_data_built_local":
        raise CandidateDataClosureValidationError("candidate_data_manifest_status_invalid")
    if reconciliation.get("schema_version") != RECONCILIATION_SCHEMA:
        raise CandidateDataClosureValidationError("reconciliation_schema_invalid")
    contract = manifest.get("reconciliation")
    metadata = _regular_file(reconciliation_path, label="candidate_data_reconciliation", mode=0o600)
    if not isinstance(contract, dict) or contract != {
        "path": "candidate-data-reconciliation-ledger.jsonl",
        "rows": 1,
        "bytes": metadata.st_size,
        "sha256": args.expected_reconciliation_sha256,
    }:
        raise CandidateDataClosureValidationError("reconciliation_outer_binding_invalid")

    source_path = Path(args.source_freeze_manifest)
    source_sha = _expected_file(
        source_path,
        args.expected_source_freeze_manifest_sha256,
        label="source_freeze_manifest",
    )
    source = _load_json(source_path, label="source_freeze_manifest")
    if source.get("schema_version") != SOURCE_FREEZE_SCHEMA:
        raise CandidateDataClosureValidationError("source_freeze_schema_invalid")
    source_cutoff = source.get("source_cutoff_utc")
    if not isinstance(source_cutoff, str) or not source_cutoff.endswith("Z"):
        raise CandidateDataClosureValidationError("source_cutoff_utc_invalid")
    _assert_side_effect_boundaries(source.get("boundaries"), label="source_freeze")

    baseline_sha = args.expected_production_baseline_manifest_sha256
    baseline, baseline_sets = _validate_base(
        Path(args.production_baseline_root), baseline_sha, label="production_baseline"
    )
    base_sha = args.expected_candidate_base_manifest_sha256
    base, candidate_sets = _validate_base(
        Path(args.candidate_base_root), base_sha, label="candidate_base"
    )
    production_receipt = _validate_production_acceptance(
        Path(args.production_acceptance_receipt),
        args.expected_production_acceptance_receipt_sha256,
        baseline,
    )
    ledger, _ledger_receipt, ledger_rows = _validate_ledgers(
        Path(args.candidate_ledger_root),
        args.expected_candidate_ledger_manifest_sha256,
        Path(args.ledger_validation_receipt),
        args.expected_ledger_validation_receipt_sha256,
        source_sha256=source_sha,
        baseline_sha256=baseline_sha,
        candidate_sha256=base_sha,
        baseline_sets=baseline_sets,
        candidate_sets=candidate_sets,
    )
    _validate_candidate_copies(
        candidate_root=candidate_root,
        candidate_manifest=manifest,
        source_path=source_path,
        source_sha256=source_sha,
        ledger_root=Path(args.candidate_ledger_root),
        ledger_manifest=ledger,
        external_ledger_rows=ledger_rows,
        reconciliation_contract=contract,
    )
    _validate_config(
        Path(args.config_manifest),
        args.expected_config_manifest_sha256,
        base_sha256=base_sha,
        ledger_sha256=args.expected_candidate_ledger_manifest_sha256,
        ledger_receipt_sha256=args.expected_ledger_validation_receipt_sha256,
    )
    code = _validate_code_freeze(
        Path(args.code_freeze_manifest),
        args.expected_code_freeze_manifest_sha256,
        Path(args.code_root),
    )
    insights, reports, _analytics_receipt = _validate_analytics(
        Path(args.insights_root),
        args.expected_insights_manifest_sha256,
        Path(args.reports_root),
        args.expected_reports_manifest_sha256,
        Path(args.analytics_validation_receipt),
        args.expected_analytics_validation_receipt_sha256,
        base_sha256=base_sha,
        ledger_sha256=args.expected_candidate_ledger_manifest_sha256,
        ledger_receipt_sha256=args.expected_ledger_validation_receipt_sha256,
    )
    personas, _personas_receipt = _validate_personas(
        Path(args.personas_root),
        args.expected_personas_manifest_sha256,
        Path(args.personas_validation_receipt),
        args.expected_personas_validation_receipt_sha256,
        base_sha256=base_sha,
        insights_sha256=args.expected_insights_manifest_sha256,
    )
    public, public_receipt = _validate_public(
        Path(args.public_root),
        args.expected_public_inventory_sha256,
        Path(args.public_validation_receipt),
        args.expected_public_validation_receipt_sha256,
        base=base,
        base_sha256=base_sha,
        insights=insights,
        insights_sha256=args.expected_insights_manifest_sha256,
        reports=reports,
        reports_sha256=args.expected_reports_manifest_sha256,
        personas=personas,
        personas_sha256=args.expected_personas_manifest_sha256,
    )
    cases = _validate_cases(
        Path(args.cases_manifest),
        args.expected_cases_manifest_sha256,
        Path(args.cases_index),
        args.expected_cases_index_sha256,
    )
    if public_receipt.get("cases") != cases:
        raise CandidateDataClosureValidationError(
            "public_validation_receipt_cases_invalid"
        )
    input_payload, candidate_input_sha = _candidate_input(
        source_sha256=source_sha,
        baseline_sha256=baseline_sha,
        config_sha256=args.expected_config_manifest_sha256,
        code_sha256=args.expected_code_freeze_manifest_sha256,
    )
    if candidate_root.name != candidate_input_sha:
        raise CandidateDataClosureValidationError("candidate_root_identity_invalid")
    if (
        manifest.get("candidate_input_sha256") != candidate_input_sha
        or reconciliation.get("candidate_input_sha256") != candidate_input_sha
        or manifest.get("candidate_input") != input_payload
    ):
        raise CandidateDataClosureValidationError("candidate_input_binding_invalid")
    if (
        manifest.get("source_cutoff_utc") != source_cutoff
        or reconciliation.get("source_cutoff_utc") != source_cutoff
        or manifest.get("code_cutoff_utc") != code.get("code_cutoff_utc")
        or reconciliation.get("code_cutoff_utc") != code.get("code_cutoff_utc")
    ):
        raise CandidateDataClosureValidationError("cutoff_binding_invalid")
    accounting = ledger.get("accounting")
    identity_sets = ledger.get("identity_sets")
    detail_ledgers = ledger.get("ledgers")
    if not isinstance(accounting, dict) or not isinstance(identity_sets, dict) or not isinstance(detail_ledgers, dict):
        raise CandidateDataClosureValidationError("ledger_reconciliation_fields_invalid")
    comment_statuses = accounting.get("comments", {}).get("status_counts", {})
    if not isinstance(comment_statuses, dict):
        raise CandidateDataClosureValidationError("comment_accounting_invalid")
    release = production_receipt["release"]
    expected_reconciliation_fields = {
        "production_baseline": {
            "dataset_version": baseline.get("dataset_version"),
            "manifest_sha256": baseline_sha,
            "release_sha256": release["current_production_release_sha256"],
            "acceptance_receipt_sha256": args.expected_production_acceptance_receipt_sha256,
        },
        "input_freeze_sha256": source_sha,
        "identity_sets": identity_sets,
        "detail_ledgers": detail_ledgers,
        "accounting": accounting,
        "coverage_transition": _coverage_transition(accounting),
        "quarantine_transitions": {
            "new_quarantined": comment_statuses.get("new_quarantined", 0),
            "relinked": comment_statuses.get("existing_quarantine_relinked", 0),
            "retained": comment_statuses.get("existing_quarantine_retained", 0),
        },
        "outputs": {
            "base_manifest_sha256": base_sha,
            "insights_manifest_sha256": args.expected_insights_manifest_sha256,
            "reports_manifest_sha256": args.expected_reports_manifest_sha256,
            "personas_manifest_sha256": args.expected_personas_manifest_sha256,
            "public_inventory_sha256": public["inventory_sha256"],
            "public_manifest_sha256": public["manifest_sha256"],
            "cases_manifest_sha256": cases["manifest_sha256"],
            "cases_index_sha256": cases["index_sha256"],
        },
        "validation_receipts": {
            "candidate_ledgers": args.expected_ledger_validation_receipt_sha256,
            "analytics": args.expected_analytics_validation_receipt_sha256,
            "personas": args.expected_personas_validation_receipt_sha256,
            "public": args.expected_public_validation_receipt_sha256,
        },
        "validation_code": {
            "public_projection_validator_sha256": code["files"]
            ["scripts/validate_public_site_projection.py"]["sha256"],
        },
        "cases": cases,
        "evidence_grade": "L2_local_candidate_with_L3_readonly_baseline",
        "boundaries": BOUNDARIES,
    }
    for field, value in expected_reconciliation_fields.items():
        if reconciliation.get(field) != value:
            raise CandidateDataClosureValidationError(f"reconciliation_{field}_invalid")
    if set(reconciliation) != {
        "schema_version",
        "candidate_input_sha256",
        "source_cutoff_utc",
        "code_cutoff_utc",
        *expected_reconciliation_fields.keys(),
    }:
        raise CandidateDataClosureValidationError("reconciliation_fields_invalid")
    expected_lineage = {
        "production_acceptance_receipt_sha256": args.expected_production_acceptance_receipt_sha256,
        "candidate_base_manifest_sha256": base_sha,
        "candidate_ledger_manifest_sha256": args.expected_candidate_ledger_manifest_sha256,
        "ledger_validation_receipt_sha256": args.expected_ledger_validation_receipt_sha256,
        "analytics_validation_receipt_sha256": args.expected_analytics_validation_receipt_sha256,
        "personas_validation_receipt_sha256": args.expected_personas_validation_receipt_sha256,
        "public_validation_receipt_sha256": args.expected_public_validation_receipt_sha256,
        "public_projection_validator_code_sha256": code["files"]
        ["scripts/validate_public_site_projection.py"]["sha256"],
        "insights_manifest_sha256": args.expected_insights_manifest_sha256,
        "reports_manifest_sha256": args.expected_reports_manifest_sha256,
        "personas_manifest_sha256": args.expected_personas_manifest_sha256,
        "public_inventory_sha256": public["inventory_sha256"],
        "cases_manifest_sha256": cases["manifest_sha256"],
        "cases_index_sha256": cases["index_sha256"],
    }
    if manifest.get("lineage") != expected_lineage:
        raise CandidateDataClosureValidationError("candidate_manifest_lineage_invalid")
    expected_counts = {
        "detail_ledgers": 4,
        "public_files": public["file_count"],
        "public_bytes": public["total_bytes"],
        "cases_selected": 38,
        "cases_unverified": 12,
        "cases_approved_delta": 0,
        "unaccounted_total": 0,
    }
    if manifest.get("counts") != expected_counts:
        raise CandidateDataClosureValidationError("candidate_manifest_counts_invalid")
    if manifest.get("evidence_grade") != "L2_local_candidate_with_L3_readonly_baseline":
        raise CandidateDataClosureValidationError("candidate_manifest_evidence_grade_invalid")
    if manifest.get("boundaries") != BOUNDARIES or reconciliation.get("boundaries") != BOUNDARIES:
        raise CandidateDataClosureValidationError("candidate_boundary_invalid")
    _assert_side_effect_boundaries(manifest, label="candidate_manifest")
    _assert_side_effect_boundaries(reconciliation, label="reconciliation")
    return manifest, reconciliation, {
        "candidate_input_sha256": candidate_input_sha,
        "ledger_rows": {name: len(rows) for name, rows in ledger_rows.items()},
        "public_files": public["file_count"],
        "public_bytes": public["total_bytes"],
        "release_net_new_posts": accounting["posts"]["release_net_new"],
        "release_net_new_comments": accounting["comments"]["release_net_new"],
        "unaccounted_total": 0,
    }


def _write_immutable_receipt(path: Path, value: dict[str, Any]) -> str:
    parent = path.parent
    _directory(parent, label="receipt_parent", mode=0o700)
    payload = _canonical_bytes(value) + b"\n"
    if path.exists() or path.is_symlink():
        _regular_file(path, label="receipt", mode=0o600)
        if path.read_bytes() == payload:
            return "no_change"
        raise CandidateDataClosureValidationError("receipt_immutable_collision")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".closure-receipt-", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _regular_file(path, label="receipt", mode=0o600)
            if path.read_bytes() != payload:
                raise CandidateDataClosureValidationError("receipt_immutable_collision")
            return "no_change"
        _regular_file(path, label="receipt", mode=0o600)
        if path.read_bytes() != payload:
            raise CandidateDataClosureValidationError("receipt_write_verification_failed")
        return "created"
    except CandidateDataClosureValidationError:
        raise
    except OSError as exc:
        raise CandidateDataClosureValidationError("receipt_write_failed") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def validate_candidate_data_closure(args: argparse.Namespace) -> dict[str, Any]:
    manifest, _reconciliation, summary = _validate_closure_documents(args)
    candidate_root = Path(args.candidate_root)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed",
        "candidate_input_sha256": summary["candidate_input_sha256"],
        "candidate_data_manifest_sha256": args.expected_candidate_data_manifest_sha256,
        "reconciliation_sha256": args.expected_reconciliation_sha256,
        "validator_code_sha256": _file_sha256(Path(__file__)),
        "checks": {
            "candidate_input_four_hash_contract": True,
            "code_allowlist_and_separate_cutoff": True,
            "detail_ledger_hash_rows_and_conservation": True,
            "identity_sets_and_unaccounted_zero": True,
            "base_analytics_personas_lineage": True,
            "public_inventory_and_independent_receipt": True,
            "cases_38_12_0": True,
            "reconciliation_has_no_self_hash": True,
            "outer_manifest_binds_reconciliation": True,
            "side_effect_boundaries": True,
            "private_output_modes": True,
        },
        "counts": {
            "source_occurrence_rows": summary["ledger_rows"]["source-occurrence-ledger.jsonl"],
            "post_rows": summary["ledger_rows"]["post-identity-delta-ledger.jsonl"],
            "comment_rows": summary["ledger_rows"]["comment-identity-delta-ledger.jsonl"],
            "coverage_rows": summary["ledger_rows"]["coverage-work-ledger.jsonl"],
            "release_net_new_posts": summary["release_net_new_posts"],
            "release_net_new_comments": summary["release_net_new_comments"],
            "public_files": summary["public_files"],
            "public_bytes": summary["public_bytes"],
            "cases_selected": 38,
            "cases_unverified": 12,
            "cases_approved_delta": 0,
            "unaccounted_total": summary["unaccounted_total"],
        },
        "source_cutoff_utc": manifest["source_cutoff_utc"],
        "code_cutoff_utc": manifest["code_cutoff_utc"],
        "evidence_grade": "L2_local_independent_validation",
        "boundaries": deepcopy(BOUNDARIES),
    }
    receipt_path = candidate_root / "candidate-data-validation-receipt.json"
    publication_status = _write_immutable_receipt(receipt_path, receipt)
    return {
        "status": publication_status,
        "candidate_input_sha256": summary["candidate_input_sha256"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": _file_sha256(receipt_path),
        "production_unchanged": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    path_sha_pairs = (
        ("source-freeze-manifest", "source-freeze-manifest"),
        ("production-acceptance-receipt", "production-acceptance-receipt"),
        ("ledger-validation-receipt", "ledger-validation-receipt"),
        ("config-manifest", "config-manifest"),
        ("code-freeze-manifest", "code-freeze-manifest"),
        ("analytics-validation-receipt", "analytics-validation-receipt"),
        ("personas-validation-receipt", "personas-validation-receipt"),
        ("public-validation-receipt", "public-validation-receipt"),
        ("cases-manifest", "cases-manifest"),
        ("cases-index", "cases-index"),
    )
    for option, expected in path_sha_pairs:
        parser.add_argument(f"--{option}", required=True)
        parser.add_argument(f"--expected-{expected}-sha256", required=True)
    root_sha_pairs = (
        ("production-baseline-root", "production-baseline-manifest"),
        ("candidate-base-root", "candidate-base-manifest"),
        ("candidate-ledger-root", "candidate-ledger-manifest"),
        ("insights-root", "insights-manifest"),
        ("reports-root", "reports-manifest"),
        ("personas-root", "personas-manifest"),
        ("public-root", "public-inventory"),
    )
    for option, expected in root_sha_pairs:
        parser.add_argument(f"--{option}", required=True)
        parser.add_argument(f"--expected-{expected}-sha256", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--expected-candidate-data-manifest-sha256", required=True)
    parser.add_argument("--expected-reconciliation-sha256", required=True)
    parser.add_argument("--code-root", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = validate_candidate_data_closure(args)
    except CandidateDataClosureValidationError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
