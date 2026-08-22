from __future__ import annotations

from collections import Counter
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import uuid
from typing import Any

from reddit_voc.v3_canonical_identity import (
    CanonicalIdentityError,
    CommentState,
    canonical_comment_fullname,
    canonical_parent_id,
    canonical_post_fullname,
    canonical_post_id,
)


SHA256_HEX_LENGTH = 64
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
IMPORT_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "parent-link-ledger.jsonl",
    "posts.jsonl",
    "row-outcomes.jsonl",
}
FAILURE_MARKER = ".publish-failed"
RECEIPT_FIELDS = {
    "base_lineage_manifest_sha256",
    "base_public_manifest_sha256",
    "boundaries",
    "bundle_manifest_sha256",
    "consumption_status",
    "counts",
    "promotable",
    "schema_version",
    "source_manifest_sha256",
    "status",
    "unaccounted_import_identities",
    "unaccounted_source_rows",
}
LINKED_PARENT_STATUSES = {
    "linked_base_post",
    "linked_governed_base_comment",
    "linked_workbook_post",
}


class CanonicalFusionError(ValueError):
    """An input binding or canonical conservation rule failed closed."""


@dataclass(frozen=True)
class CanonicalSnapshotResult:
    schema_version: str
    dataset_id: str
    manifest_sha256: str
    posts: int
    stored_comments: int
    linked_comments: int
    unresolved_parent_comments: int
    quarantined_comments: int
    boundaries: dict[str, bool]


@dataclass(frozen=True)
class _InputBinding:
    value: dict[str, Any]
    sha256: str


@dataclass(frozen=True)
class _BaseData:
    posts: dict[str, dict[str, Any]]
    comments: dict[str, dict[str, Any]]
    quarantine: dict[str, dict[str, Any]]
    unresolved: dict[str, dict[str, Any]]
    parent_resolution: dict[str, str]
    parent_lineage_debt_counts: dict[str, int]


@dataclass(frozen=True)
class _ImportData:
    posts: dict[str, dict[str, Any]]
    comments: dict[str, dict[str, Any]]
    parent_links: dict[str, dict[str, Any]]
    row_outcomes: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    manifest: dict[str, Any]


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalFusionError("value is not canonical JSON serializable") from exc


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256_HEX_LENGTH:
        raise CanonicalFusionError(f"{label} must be a SHA-256 hex digest")
    normalized = value.casefold()
    if any(character not in "0123456789abcdef" for character in normalized):
        raise CanonicalFusionError(f"{label} must be a SHA-256 hex digest")
    return normalized


def _reject_constant(value: str) -> None:
    raise CanonicalFusionError(f"non-finite JSON number is forbidden: {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CanonicalFusionError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite(value: object, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise CanonicalFusionError(f"{label} contains a non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _reject_nonfinite(item, label)
    elif isinstance(value, list):
        for item in value:
            _reject_nonfinite(item, label)


def _decode_json(payload: bytes, label: str) -> object:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalFusionError(f"{label} is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except CanonicalFusionError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise CanonicalFusionError(f"{label} is not valid JSON") from exc
    _reject_nonfinite(value, label)
    return value


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    value = _decode_json(payload, label)
    if not isinstance(value, dict):
        raise CanonicalFusionError(f"{label} must be a JSON object")
    return value


def _json_array(payload: bytes, label: str) -> list[dict[str, Any]]:
    value = _decode_json(payload, label)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CanonicalFusionError(f"{label} must be an array of objects")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise CanonicalFusionError(f"{label} must end with a newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        if not line:
            raise CanonicalFusionError(f"{label} contains a blank JSONL row")
        row = _json_object(line, f"{label} row {ordinal}")
        if canonical_json_bytes(row) != line:
            raise CanonicalFusionError(f"{label} row {ordinal} is not canonical JSON")
        rows.append(row)
    return rows


def _ensure_under(path: Path, parent: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        parent_resolved = parent.resolve(strict=True)
        resolved.relative_to(parent_resolved)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise CanonicalFusionError(f"{label} is outside the project boundary") from exc
    return resolved


def _reject_symlink_chain(path: Path, *, stop: Path, label: str) -> None:
    current = path
    stop_resolved = stop.resolve(strict=True)
    while True:
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current = current.parent
            continue
        if stat.S_ISLNK(mode):
            raise CanonicalFusionError(f"{label} may not use symlinks")
        if current.resolve(strict=True) == stop_resolved:
            return
        if current.parent == current:
            raise CanonicalFusionError(f"{label} is outside the project boundary")
        current = current.parent


def _read_regular_file(path: Path, *, project_root: Path, label: str) -> bytes:
    _ensure_under(path, project_root, label)
    _reject_symlink_chain(path, stop=project_root, label=label)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CanonicalFusionError(f"unable to read {label}") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise CanonicalFusionError(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_binding(
    path: Path,
    *,
    expected_sha256: str,
    project_root: Path,
    label: str,
) -> _InputBinding:
    payload = _read_regular_file(path, project_root=project_root, label=label)
    actual = _sha256(payload)
    if actual != _require_sha256(expected_sha256, f"{label} expected SHA-256"):
        raise CanonicalFusionError(f"{label} hash binding mismatch")
    return _InputBinding(_json_object(payload, label), actual)


def _relative_project_path(project_root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise CanonicalFusionError(f"{label} must be a project-relative path")
    candidate = project_root / value
    return _ensure_under(candidate, project_root, label)


def _binding_from_manifest(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CanonicalFusionError(f"{label} binding is missing")
    expected_keys = {"bytes", "sha256"}
    if not expected_keys.issubset(value):
        raise CanonicalFusionError(f"{label} binding is incomplete")
    _require_sha256(value["sha256"], f"{label} SHA-256")
    if not isinstance(value["bytes"], int) or isinstance(value["bytes"], bool) or value["bytes"] < 0:
        raise CanonicalFusionError(f"{label} byte count is invalid")
    if "rows" in value and (
        not isinstance(value["rows"], int) or isinstance(value["rows"], bool) or value["rows"] < 0
    ):
        raise CanonicalFusionError(f"{label} row count is invalid")
    return value


def _read_manifest_member(
    root: Path,
    name: str,
    binding: object,
    *,
    project_root: Path,
    label: str,
) -> bytes:
    expected = _binding_from_manifest(binding, label)
    payload = _read_regular_file(root / name, project_root=project_root, label=label)
    if len(payload) != expected["bytes"] or _sha256(payload) != expected["sha256"]:
        raise CanonicalFusionError(f"{label} file binding mismatch")
    if "rows" in expected and payload.count(b"\n") != expected["rows"]:
        raise CanonicalFusionError(f"{label} row binding mismatch")
    return payload


def _identity_map(
    rows: list[dict[str, Any]],
    *,
    entity_type: str,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            if entity_type == "post":
                canonical_id = canonical_post_fullname(row.get("post_id"))
                if row.get("reddit_id") not in (None, canonical_id):
                    raise CanonicalIdentityError("post reddit_id mismatch")
            else:
                canonical_id = canonical_comment_fullname(row.get("comment_id"))
                if row.get("reddit_id") not in (None, canonical_id):
                    raise CanonicalIdentityError("comment reddit_id mismatch")
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError(f"{label} contains an invalid identity") from exc
        if canonical_id in result:
            raise CanonicalFusionError(f"{label} contains duplicate canonical identities")
        result[canonical_id] = row
    return result


def _load_base(
    source_manifest: dict[str, Any],
    *,
    project_root: Path,
    expected_public_sha256: str,
    expected_lineage_sha256: str,
) -> _BaseData:
    base = source_manifest.get("base")
    if not isinstance(base, dict):
        raise CanonicalFusionError("SourceManifest Base binding is missing")
    source_public_sha = _require_sha256(base.get("public_manifest_sha256"), "Base public manifest SHA-256")
    source_lineage_sha = _require_sha256(base.get("lineage_manifest_sha256"), "Base lineage manifest SHA-256")
    if source_public_sha != _require_sha256(expected_public_sha256, "expected Base public manifest SHA-256"):
        raise CanonicalFusionError("Base public manifest SHA-256 binding mismatch")
    if source_lineage_sha != _require_sha256(expected_lineage_sha256, "expected Base lineage manifest SHA-256"):
        raise CanonicalFusionError("Base lineage manifest SHA-256 binding mismatch")

    public_path = _relative_project_path(
        project_root, base.get("manifest_relative_path"), "Base public manifest path"
    )
    lineage_path = _relative_project_path(
        project_root, base.get("lineage_manifest_relative_path"), "Base lineage manifest path"
    )
    public_binding = _read_binding(
        public_path,
        expected_sha256=source_public_sha,
        project_root=project_root,
        label="Base public manifest",
    )
    lineage_binding = _read_binding(
        lineage_path,
        expected_sha256=source_lineage_sha,
        project_root=project_root,
        label="Base lineage manifest",
    )
    public_manifest = public_binding.value
    lineage_manifest = lineage_binding.value
    expected_dataset = base.get("dataset_version")
    if (
        not isinstance(expected_dataset, str)
        or public_manifest.get("dataset_version") != expected_dataset
        or lineage_manifest.get("dataset_version") != expected_dataset
    ):
        raise CanonicalFusionError("Base dataset version binding mismatch")
    if public_manifest.get("all_checks_passed") is not True or lineage_manifest.get("all_checks_passed") is not True:
        raise CanonicalFusionError("Base manifests are not validated")

    private_files = lineage_manifest.get("files")
    public_files = public_manifest.get("files")
    if not isinstance(private_files, dict) or not isinstance(public_files, dict):
        raise CanonicalFusionError("Base file bindings are missing")
    private_posts = _json_array(
        _read_manifest_member(
            lineage_path.parent,
            "posts.json",
            private_files.get("posts.json"),
            project_root=project_root,
            label="Base private posts",
        ),
        "Base private posts",
    )
    private_comments = _json_array(
        _read_manifest_member(
            lineage_path.parent,
            "comments.json",
            private_files.get("comments.json"),
            project_root=project_root,
            label="Base private comments",
        ),
        "Base private comments",
    )
    quarantine_rows = _json_array(
        _read_manifest_member(
            lineage_path.parent,
            "quarantine.json",
            private_files.get("quarantine.json"),
            project_root=project_root,
            label="Base quarantine",
        ),
        "Base quarantine",
    )
    unresolved_rows = []
    unresolved_binding = private_files.get("unresolved-parent-ledger.jsonl")
    if unresolved_binding is not None:
        unresolved_rows = _jsonl(
            _read_manifest_member(
                lineage_path.parent,
                "unresolved-parent-ledger.jsonl",
                unresolved_binding,
                project_root=project_root,
                label="Base unresolved parent ledger",
            ),
            "Base unresolved parent ledger",
        )
    public_posts = _json_array(
        _read_manifest_member(
            public_path.parent,
            "posts-public.json",
            public_files.get("posts-public.json"),
            project_root=project_root,
            label="Base public posts",
        ),
        "Base public posts",
    )
    public_comments = _json_array(
        _read_manifest_member(
            public_path.parent,
            "comments-public.json",
            public_files.get("comments-public.json"),
            project_root=project_root,
            label="Base public comments",
        ),
        "Base public comments",
    )

    posts = _identity_map(private_posts, entity_type="post", label="Base private posts")
    comments = _identity_map(private_comments, entity_type="comment", label="Base private comments")
    public_post_map = _identity_map(public_posts, entity_type="post", label="Base public posts")
    public_comment_map = _identity_map(public_comments, entity_type="comment", label="Base public comments")
    if set(posts) != set(public_post_map) or set(comments) != set(public_comment_map):
        raise CanonicalFusionError("Base public/private identity sets differ")

    quarantine = _identity_map(quarantine_rows, entity_type="comment", label="Base quarantine")
    unresolved: dict[str, dict[str, Any]] = {}
    for row in unresolved_rows:
        try:
            canonical_id = canonical_comment_fullname(row.get("canonical_reddit_id"))
            post_id = canonical_post_id(row.get("post_id"))
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError("Base unresolved parent identity is invalid") from exc
        if row.get("comment_state") != CommentState.UNRESOLVED_PARENT.value:
            raise CanonicalFusionError("Base unresolved parent ledger state is not unresolved")
        if row.get("schema_version") != "reddit_voc_canonical_unresolved_parent_v1":
            raise CanonicalFusionError("Base unresolved parent ledger schema version is invalid")
        if canonical_id in unresolved:
            raise CanonicalFusionError("Base unresolved parent ledger contains duplicate identities")
        unresolved[canonical_id] = row
        source_parent_link = row.get("source_parent_link")
        if isinstance(source_parent_link, dict) and source_parent_link.get("post_id") != str(post_id):
            raise CanonicalFusionError("Base unresolved parent ledger post identity mismatch")
    if set(comments) & set(quarantine):
        raise CanonicalFusionError("Base linked and quarantine comment identities overlap")
    post_ids = {canonical_post_id(item) for item in posts}
    comment_posts: dict[str, str] = {}
    comment_parents: dict[str, str] = {}
    parent_resolution: dict[str, str] = {}
    missing_immediate_parent_id = 0
    missing_parent_comment_entity = 0
    for canonical_id, row in comments.items():
        try:
            post_id = canonical_post_id(row.get("post_id"))
            if post_id not in post_ids:
                raise CanonicalIdentityError("comment root post is absent")
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError("Base comment parent binding is invalid") from exc
        public_row = public_comment_map[canonical_id]
        try:
            public_post_id = canonical_post_id(public_row.get("post_id"))
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError("Base public comment post binding is invalid") from exc
        if public_post_id != post_id:
            raise CanonicalFusionError("Base public/private comment post bindings differ")
        raw_parent = row.get("parent_id")
        public_raw_parent = public_row.get("parent_id")
        comment_posts[canonical_id] = post_id
        if raw_parent is None:
            if public_raw_parent is not None:
                raise CanonicalFusionError("Base public/private comment parent bindings differ")
            missing_immediate_parent_id += 1
            parent_resolution[canonical_id] = "missing_immediate_parent_id"
            continue
        try:
            parent = canonical_parent_id(raw_parent)
            public_parent = canonical_parent_id(public_raw_parent)
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError("Base comment parent binding is invalid") from exc
        if public_parent.fullname != parent.fullname:
            raise CanonicalFusionError("Base public/private comment parent bindings differ")
        if parent.entity_type == "post":
            if parent.bare_id != post_id:
                raise CanonicalFusionError("Base direct comment root does not match post_id")
            parent_resolution[canonical_id] = "resolved_root_parent"
        else:
            if parent.fullname not in comments:
                missing_parent_comment_entity += 1
                parent_resolution[canonical_id] = "missing_parent_comment_entity"
            else:
                comment_parents[canonical_id] = parent.fullname
                parent_resolution[canonical_id] = "resolved_nested_parent"
    for canonical_id, parent_id in comment_parents.items():
        if comment_posts[parent_id] != comment_posts[canonical_id]:
            raise CanonicalFusionError("Base nested comment parent crosses threads")
    visit_state: dict[str, int] = {}

    def visit(comment_id: str) -> None:
        state = visit_state.get(comment_id, 0)
        if state == 1:
            raise CanonicalFusionError("Base nested comment parent cycle detected")
        if state == 2:
            return
        visit_state[comment_id] = 1
        parent_id = comment_parents.get(comment_id)
        if parent_id is not None:
            visit(parent_id)
        visit_state[comment_id] = 2

    for canonical_id in comments:
        visit(canonical_id)
    nested_links_whose_parent_record_lacks_immediate_parent_id = sum(
        comments[parent_id].get("parent_id") is None for parent_id in comment_parents.values()
    )
    for row in quarantine.values():
        try:
            missing_post_id = canonical_post_id(row.get("missing_post_id"))
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError("Base quarantine parent identity is invalid") from exc
        if missing_post_id in post_ids:
            raise CanonicalFusionError("Base quarantine parent unexpectedly exists")

    counts = lineage_manifest.get("canonical_counts")
    expected_counts = {
        "linked_comments": len(comments),
        "posts": len(posts),
        "quarantined_comments": len(quarantine),
        "stored_comments": len(comments) + len(quarantine),
    }
    if counts != expected_counts or public_manifest.get("canonical_counts") != expected_counts:
        raise CanonicalFusionError("Base canonical count binding mismatch")
    return _BaseData(
        posts,
        comments,
        quarantine,
        unresolved,
        parent_resolution,
        {
            "missing_immediate_parent_id": missing_immediate_parent_id,
            "missing_parent_comment_entity": missing_parent_comment_entity,
            "nested_links_whose_parent_record_lacks_immediate_parent_id": (
                nested_links_whose_parent_record_lacks_immediate_parent_id
            ),
        },
    )


def _validate_import_manifest(
    manifest: dict[str, Any],
    *,
    source_manifest_sha256: str,
    base_public_sha256: str,
    base_lineage_sha256: str,
) -> None:
    if manifest.get("schema_version") != "reddit_voc_workbook_import_manifest_v1":
        raise CanonicalFusionError("workbook import manifest schema is unsupported")
    if (
        manifest.get("status") != "candidate_built"
        or manifest.get("independent_validation_status") != "pending"
        or manifest.get("consumption_status") != "blocked_pending_independent_validation"
        or manifest.get("promotable") is not False
        or manifest.get("validation_receipt_sha256") is not None
    ):
        raise CanonicalFusionError("workbook import manifest lifecycle is invalid")
    if manifest.get("boundaries") != EXPECTED_BOUNDARIES:
        raise CanonicalFusionError("workbook import manifest boundaries are invalid")
    if manifest.get("source_manifest_sha256") != source_manifest_sha256:
        raise CanonicalFusionError("workbook import SourceManifest binding mismatch")
    base = manifest.get("base")
    if not isinstance(base, dict):
        raise CanonicalFusionError("workbook import Base binding is missing")
    if (
        base.get("public_manifest_sha256") != base_public_sha256
        or base.get("lineage_manifest_sha256") != base_lineage_sha256
    ):
        raise CanonicalFusionError("workbook import Base hash binding mismatch")


def _load_import(
    root: Path,
    manifest_binding: _InputBinding,
    *,
    project_root: Path,
    source_manifest_sha256: str,
    base_public_sha256: str,
    base_lineage_sha256: str,
) -> _ImportData:
    manifest = manifest_binding.value
    _validate_import_manifest(
        manifest,
        source_manifest_sha256=source_manifest_sha256,
        base_public_sha256=base_public_sha256,
        base_lineage_sha256=base_lineage_sha256,
    )
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != IMPORT_FILES:
        raise CanonicalFusionError("workbook import file set is invalid")
    parsed: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(IMPORT_FILES):
        payload = _read_manifest_member(
            root,
            name,
            files[name],
            project_root=project_root,
            label=f"workbook import {name}",
        )
        parsed[name] = _jsonl(payload, f"workbook import {name}")
    posts = _identity_map(parsed["posts.jsonl"], entity_type="post", label="workbook import posts")
    comments = _identity_map(parsed["comments.jsonl"], entity_type="comment", label="workbook import comments")
    parent_links = _identity_map(
        parsed["parent-link-ledger.jsonl"], entity_type="comment", label="workbook parent ledger"
    )
    if set(parent_links) != set(comments):
        raise CanonicalFusionError("workbook comment/parent ledger identity sets differ")
    return _ImportData(
        posts,
        comments,
        parent_links,
        parsed["row-outcomes.jsonl"],
        parsed["conflict-ledger.jsonl"],
        manifest,
    )


def _validate_receipt(
    receipt: dict[str, Any],
    *,
    import_manifest_sha256: str,
    source_manifest_sha256: str,
    base_public_sha256: str,
    base_lineage_sha256: str,
    import_counts: object,
) -> None:
    if set(receipt) != RECEIPT_FIELDS:
        raise CanonicalFusionError("validation receipt fields are not the frozen contract")
    if receipt.get("schema_version") != "reddit_voc_workbook_import_validation_receipt_v1":
        raise CanonicalFusionError("validation receipt schema is unsupported")
    if receipt.get("status") != "passed":
        raise CanonicalFusionError("validation receipt status is not passed")
    if receipt.get("consumption_status") != "blocked_pending_canonical_snapshot":
        raise CanonicalFusionError("validation receipt consumption status is invalid")
    if receipt.get("promotable") is not False:
        raise CanonicalFusionError("validation receipt promotable boundary is invalid")
    if receipt.get("boundaries") != EXPECTED_BOUNDARIES:
        raise CanonicalFusionError("validation receipt boundaries are invalid")
    if receipt.get("bundle_manifest_sha256") != import_manifest_sha256:
        raise CanonicalFusionError("validation receipt workbook manifest binding mismatch")
    if receipt.get("source_manifest_sha256") != source_manifest_sha256:
        raise CanonicalFusionError("validation receipt SourceManifest binding mismatch")
    if (
        receipt.get("base_public_manifest_sha256") != base_public_sha256
        or receipt.get("base_lineage_manifest_sha256") != base_lineage_sha256
    ):
        raise CanonicalFusionError("validation receipt Base manifest binding mismatch")
    if receipt.get("counts") != import_counts:
        raise CanonicalFusionError("validation receipt count binding mismatch")
    for field in ("unaccounted_source_rows", "unaccounted_import_identities"):
        value = receipt.get(field)
        if type(value) is not int or value != 0:
            raise CanonicalFusionError("validation receipt has unaccounted records")


def _validate_workbook_membership(base: _BaseData, imported: _ImportData) -> None:
    base_post_ids = set(base.posts)
    base_comment_ids = set(base.comments) | set(base.quarantine) | set(base.unresolved)
    for canonical_id, row in imported.posts.items():
        overlap = canonical_id in base_post_ids
        if row.get("entity_type") != "post" or row.get("canonical_reddit_id") != canonical_id:
            raise CanonicalFusionError("workbook post identity fields disagree")
        if row.get("base_overlap") is not overlap:
            raise CanonicalFusionError("workbook post Base overlap binding mismatch")
        expected_outcome = "exact_base_overlap" if overlap else row.get("terminal_outcome")
        if overlap and expected_outcome != row.get("terminal_outcome"):
            raise CanonicalFusionError("workbook post overlap outcome is invalid")
    all_post_ids = base_post_ids | set(imported.posts)
    for canonical_id, row in imported.comments.items():
        overlap = canonical_id in base_comment_ids
        if row.get("entity_type") != "comment" or row.get("canonical_reddit_id") != canonical_id:
            raise CanonicalFusionError("workbook comment identity fields disagree")
        if row.get("base_overlap") is not overlap:
            raise CanonicalFusionError("workbook comment Base overlap binding mismatch")
        if overlap and row.get("terminal_outcome") != "exact_base_overlap":
            raise CanonicalFusionError("workbook comment overlap outcome is invalid")
        parent = imported.parent_links[canonical_id]
        try:
            post_fullname = canonical_post_fullname(row.get("post_id"))
        except CanonicalIdentityError as exc:
            raise CanonicalFusionError("workbook comment root identity is invalid") from exc
        if parent.get("post_id") != row.get("post_id"):
            raise CanonicalFusionError("workbook comment parent ledger disagrees")
        if overlap:
            continue
        status = parent.get("parent_link_status")
        if status == CommentState.UNRESOLVED_PARENT.value:
            if post_fullname in all_post_ids:
                raise CanonicalFusionError("unresolved workbook parent exists in canonical posts")
        elif status in LINKED_PARENT_STATUSES:
            if post_fullname not in all_post_ids:
                raise CanonicalFusionError("linked workbook parent is absent")
        else:
            raise CanonicalFusionError("workbook parent link status is unsupported")


def _validate_source_row_accounting(imported: _ImportData) -> dict[str, str]:
    counts = imported.manifest.get("counts")
    if not isinstance(counts, dict):
        raise CanonicalFusionError("workbook import counts are missing")
    row_counts = Counter()
    outcomes_by_occurrence: dict[str, str] = {}
    valid_ids = set(imported.posts) | set(imported.comments)
    for row in imported.row_outcomes:
        canonical_id = row.get("canonical_reddit_id")
        occurrence_key = row.get("occurrence_key")
        outcome = row.get("terminal_outcome")
        if canonical_id not in valid_ids:
            raise CanonicalFusionError("row outcome has an unknown canonical identity")
        if not isinstance(occurrence_key, str) or not occurrence_key or occurrence_key in outcomes_by_occurrence:
            raise CanonicalFusionError("row outcome occurrence key is invalid or duplicate")
        if not isinstance(outcome, str) or not outcome:
            raise CanonicalFusionError("row terminal outcome is invalid")
        outcomes_by_occurrence[occurrence_key] = outcome
        row_counts[outcome] += 1
    if len(imported.row_outcomes) != counts.get("source_rows"):
        raise CanonicalFusionError("source row count is not conserved")
    expected_outcomes = counts.get("terminal_outcomes")
    if not isinstance(expected_outcomes, dict):
        raise CanonicalFusionError("source row terminal outcome contract is missing")
    observed_outcomes = {key: row_counts.get(key, 0) for key in expected_outcomes}
    if set(row_counts) - set(expected_outcomes) or observed_outcomes != expected_outcomes:
        raise CanonicalFusionError("source row terminal outcomes are not conserved")
    if counts.get("distinct_posts") != len(imported.posts) or counts.get("distinct_comments") != len(imported.comments):
        raise CanonicalFusionError("workbook distinct identity counts disagree")
    for row in [*imported.posts.values(), *imported.comments.values()]:
        occurrences = row.get("source_occurrences")
        if not isinstance(occurrences, list) or not occurrences:
            raise CanonicalFusionError("workbook entity lacks source provenance")
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                raise CanonicalFusionError("workbook source occurrence is invalid")
            key = occurrence.get("occurrence_key")
            if key not in outcomes_by_occurrence:
                raise CanonicalFusionError("workbook source occurrence has no row outcome")
    if sum(len(row["source_occurrences"]) for row in [*imported.posts.values(), *imported.comments.values()]) != len(
        outcomes_by_occurrence
    ):
        raise CanonicalFusionError("workbook source occurrence accounting is not one-to-one")
    return outcomes_by_occurrence


def _base_provenance_row(canonical_id: str, entity_type: str, record: dict[str, Any]) -> dict[str, Any]:
    record_sha = _sha256(canonical_json_bytes(record))
    occurrences = record.get("source_occurrences", record.get("source_kinds", []))
    return {
        "canonical_reddit_id": canonical_id,
        "entity_type": entity_type,
        "provenance_id": _sha256(
            canonical_json_bytes([canonical_id, "governed_base_entity", record_sha])
        ),
        "schema_version": "reddit_voc_canonical_provenance_v1",
        "source_occurrence_count": len(occurrences) if isinstance(occurrences, list) else 0,
        "source_payload_sha256": record_sha,
        "source_role": "governed_base_entity",
    }


def _workbook_provenance_rows(
    canonical_id: str,
    entity_type: str,
    row: dict[str, Any],
    outcomes_by_occurrence: dict[str, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for occurrence in row["source_occurrences"]:
        key = occurrence["occurrence_key"]
        payload_sha = _sha256(canonical_json_bytes(occurrence))
        result.append(
            {
                "canonical_reddit_id": canonical_id,
                "entity_type": entity_type,
                "occurrence_key": key,
                "provenance_id": _sha256(
                    canonical_json_bytes([canonical_id, "workbook_occurrence", key, payload_sha])
                ),
                "schema_version": "reddit_voc_canonical_provenance_v1",
                "source_occurrence": occurrence,
                "source_payload_sha256": payload_sha,
                "source_role": "workbook_occurrence",
                "source_row_terminal_outcome": outcomes_by_occurrence[key],
            }
        )
    return result


def _materialize(
    base: _BaseData,
    imported: _ImportData,
    outcomes_by_occurrence: dict[str, str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    posts: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    unresolved_by_id = dict(base.unresolved)
    base_comment_states: dict[str, str] = {
        canonical_id: (
            CommentState.UNRESOLVED_PARENT.value
            if canonical_id in base.unresolved
            else CommentState.LINKED.value
        )
        for canonical_id in base.comments
    }
    for canonical_id in set(base.comments) & set(imported.comments):
        parent = imported.parent_links[canonical_id]
        if parent["parent_link_status"] in LINKED_PARENT_STATUSES:
            base_comment_states[canonical_id] = CommentState.LINKED.value

    def unresolved_ledger_row(
        canonical_id: str,
        row: dict[str, Any],
        parent: dict[str, Any],
        terminal_outcome: str,
    ) -> dict[str, Any]:
        return {
            "canonical_reddit_id": canonical_id,
            "comment_state": CommentState.UNRESOLVED_PARENT.value,
            "post_id": canonical_post_id(row["post_id"]),
            "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
            "source_parent_link": {
                "comment_id": canonical_id,
                "parent_link_status": parent["parent_link_status"],
                "post_id": canonical_post_id(row["post_id"]),
            },
            "source_terminal_outcome": terminal_outcome,
        }

    for canonical_id in sorted(base.posts):
        record = base.posts[canonical_id]
        posts.append(
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": canonical_id,
                "entity_type": "post",
                "post_id": canonical_post_id(canonical_id),
                "record": record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_post_v1",
            }
        )
        provenance.append(_base_provenance_row(canonical_id, "post", record))
    for canonical_id in sorted(imported.posts):
        row = imported.posts[canonical_id]
        provenance.extend(_workbook_provenance_rows(canonical_id, "post", row, outcomes_by_occurrence))
        if canonical_id in base.posts:
            continue
        posts.append(
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": canonical_id,
                "entity_type": "post",
                "post_id": canonical_post_id(canonical_id),
                "record": row,
                "record_authority": "workbook_net_new",
                "schema_version": "reddit_voc_canonical_post_v1",
            }
        )

    for canonical_id in sorted(base.comments):
        record = base.comments[canonical_id]
        comment_state = base_comment_states[canonical_id]
        comments.append(
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": canonical_id,
                "comment_state": comment_state,
                "entity_type": "comment",
                "immediate_parent_resolution": base.parent_resolution[canonical_id],
                "post_id": canonical_post_id(record["post_id"]),
                "record": record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_comment_v1",
            }
        )
        if comment_state == CommentState.UNRESOLVED_PARENT.value:
            unresolved_by_id[canonical_id] = base.unresolved[canonical_id]
        provenance.append(_base_provenance_row(canonical_id, "comment", record))
    for canonical_id in sorted(base.quarantine):
        record = base.quarantine[canonical_id]
        quarantine.append(
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": canonical_id,
                "comment_state": CommentState.QUARANTINED.value,
                "entity_type": "comment",
                "record": record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_quarantine_v1",
            }
        )
        provenance.append(_base_provenance_row(canonical_id, "comment", record))

    for canonical_id in sorted(imported.comments):
        row = imported.comments[canonical_id]
        provenance.extend(_workbook_provenance_rows(canonical_id, "comment", row, outcomes_by_occurrence))
        if canonical_id in base.comments:
            parent = imported.parent_links[canonical_id]
            if parent["parent_link_status"] in LINKED_PARENT_STATUSES:
                unresolved_by_id.pop(canonical_id, None)
            else:
                unresolved_by_id[canonical_id] = unresolved_ledger_row(
                    canonical_id,
                    row,
                    parent,
                    row["terminal_outcome"],
                )
            continue
        if canonical_id in base.quarantine:
            if canonical_id in base.unresolved:
                parent = imported.parent_links[canonical_id]
                state = (
                    CommentState.LINKED
                    if parent["parent_link_status"] in LINKED_PARENT_STATUSES
                    else CommentState.UNRESOLVED_PARENT
                )
                comments.append(
                    {
                        "canonical_identity_state": "canonical_identity",
                        "canonical_reddit_id": canonical_id,
                        "comment_state": state.value,
                        "entity_type": "comment",
                        "post_id": canonical_post_id(row["post_id"]),
                        "record": row,
                        "record_authority": "workbook_net_new",
                        "schema_version": "reddit_voc_canonical_comment_v1",
                    }
                )
                if state is CommentState.UNRESOLVED_PARENT:
                    unresolved_by_id[canonical_id] = unresolved_ledger_row(
                        canonical_id,
                        row,
                        parent,
                        row["terminal_outcome"],
                    )
                else:
                    unresolved_by_id.pop(canonical_id, None)
            continue
        if canonical_id in base.unresolved:
            parent = imported.parent_links[canonical_id]
            state = (
                CommentState.LINKED
                if parent["parent_link_status"] in LINKED_PARENT_STATUSES
                else CommentState.UNRESOLVED_PARENT
            )
            comments.append(
                {
                    "canonical_identity_state": "canonical_identity",
                    "canonical_reddit_id": canonical_id,
                    "comment_state": state.value,
                    "entity_type": "comment",
                    "post_id": canonical_post_id(row["post_id"]),
                    "record": row,
                    "record_authority": "workbook_net_new",
                    "schema_version": "reddit_voc_canonical_comment_v1",
                }
            )
            if state is CommentState.UNRESOLVED_PARENT:
                unresolved_by_id[canonical_id] = unresolved_ledger_row(
                    canonical_id,
                    row,
                    parent,
                    row["terminal_outcome"],
                )
            else:
                unresolved_by_id.pop(canonical_id, None)
            continue
        parent = imported.parent_links[canonical_id]
        state = (
            CommentState.UNRESOLVED_PARENT
            if parent["parent_link_status"] == CommentState.UNRESOLVED_PARENT.value
            else CommentState.LINKED
        )
        comments.append(
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": canonical_id,
                "comment_state": state.value,
                "entity_type": "comment",
                "post_id": canonical_post_id(row["post_id"]),
                "record": row,
                "record_authority": "workbook_net_new",
                "schema_version": "reddit_voc_canonical_comment_v1",
            }
        )
        if state is CommentState.UNRESOLVED_PARENT:
            unresolved_by_id[canonical_id] = unresolved_ledger_row(
                canonical_id,
                row,
                parent,
                row["terminal_outcome"],
            )

    for row in unresolved_by_id.values():
        unresolved.append(row)

    for row in imported.conflicts:
        canonical_id = row.get("canonical_reddit_id")
        if (
            canonical_id
            not in set(base.posts)
            | set(base.comments)
            | set(base.quarantine)
            | set(base.unresolved)
            | set(imported.posts)
            | set(imported.comments)
        ):
            raise CanonicalFusionError("workbook conflict references an unknown identity")
        conflicts.append(
            {
                "canonical_reddit_id": canonical_id,
                "conflict_type": row.get("conflict_type"),
                "entity_type": row.get("entity_type"),
                "resolution": row.get("resolution"),
                "schema_version": "reddit_voc_canonical_conflict_v1",
                "source_conflict_record": row,
                "source_conflict_sha256": _sha256(canonical_json_bytes(row)),
                "source_role": "workbook_import_conflict",
            }
        )

    posts.sort(key=lambda row: str(row["canonical_reddit_id"]))
    comments.sort(key=lambda row: str(row["canonical_reddit_id"]))
    quarantine.sort(key=lambda row: str(row["canonical_reddit_id"]))
    unresolved.sort(key=lambda row: str(row["canonical_reddit_id"]))
    provenance.sort(key=lambda row: (str(row["canonical_reddit_id"]), str(row["provenance_id"])))
    conflicts.sort(
        key=lambda row: (
            str(row["canonical_reddit_id"]),
            str(row["conflict_type"]),
            str(row["source_conflict_sha256"]),
        )
    )
    return posts, comments, quarantine, unresolved, provenance, conflicts


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _rename_noreplace(source_fd: int, source_name: str, target_fd: int, target_name: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source_name)
    encoded_target = os.fsencode(target_name)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(source_fd, encoded_source, target_fd, encoded_target, 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(source_fd, encoded_source, target_fd, encoded_target, 1)
    else:
        raise CanonicalFusionError("atomic no-replace rename unavailable")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise CanonicalFusionError("immutable output already exists")
    raise OSError(error_number, os.strerror(error_number))


def _private_output_parts(
    output_root: Path,
    project_root: Path,
) -> tuple[Path, tuple[str, ...]]:
    root = Path(os.path.abspath(os.fspath(project_root)))
    private_root = root / "tmp/reddit-voc-v3"
    target = Path(
        os.path.abspath(
            os.fspath(output_root if output_root.is_absolute() else root / output_root)
        )
    )
    try:
        relative = target.relative_to(private_root)
    except ValueError as exc:
        raise CanonicalFusionError(
            "canonical output must stay below private tmp/reddit-voc-v3"
        ) from exc
    if not relative.parts or any(
        part in {"", ".", ".."} or "/" in part or "\\" in part
        for part in relative.parts
    ):
        raise CanonicalFusionError("canonical output path is unsafe")
    return root, relative.parts


def _open_or_create_directory_at(
    parent_fd: int,
    name: str,
    *,
    private: bool,
) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        os.mkdir(name, 0o700 if private else 0o755, dir_fd=parent_fd)
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise CanonicalFusionError("canonical output ancestor must be a directory")
    if private and stat.S_IMODE(metadata.st_mode) & 0o077:
        os.close(descriptor)
        raise CanonicalFusionError("canonical output ancestor must be private")
    return descriptor


def _open_output_parent(
    output_root: Path,
    project_root: Path,
) -> tuple[str, list[int]]:
    root, relative_parts = _private_output_parts(output_root, project_root)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    opened: list[int] = []
    try:
        descriptor = os.open(os.fspath(root), directory_flags)
        opened.append(descriptor)
        descriptor = _open_or_create_directory_at(descriptor, "tmp", private=False)
        opened.append(descriptor)
        descriptor = _open_or_create_directory_at(
            descriptor,
            "reddit-voc-v3",
            private=True,
        )
        opened.append(descriptor)
        for part in relative_parts[:-1]:
            descriptor = _open_or_create_directory_at(
                descriptor,
                part,
                private=True,
            )
            opened.append(descriptor)
        return relative_parts[-1], opened
    except CanonicalFusionError:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError as exc:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise CanonicalFusionError("canonical output parent is unavailable or unsafe") from exc


def _directory_identity_at(directory_fd: int, name: str) -> tuple[int, int] | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino


def _cleanup_staging_contents(staging_fd: int, names: list[str]) -> None:
    for name in reversed(names):
        try:
            os.unlink(name, dir_fd=staging_fd)
        except OSError:
            pass
    try:
        os.fsync(staging_fd)
    except OSError:
        pass


def _mark_failed_shell(staging_fd: int) -> None:
    """Mark a retained failed-publish directory as non-consumable.

    POSIX offers no portable operation that removes a directory only when it
    still names the inode held by an open descriptor. Retaining this shell
    avoids deleting a foreign replacement during failure cleanup. The marker
    is zero length so this path does not reuse the payload write loop that may
    itself have failed.
    """

    descriptor: int | None = None
    try:
        descriptor = os.open(
            FAILURE_MARKER,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=staging_fd,
        )
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    except OSError:
        # Preserve the original publish exception. The shell remains outside
        # every valid candidate inventory even if this best-effort marker fails.
        pass
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    try:
        os.fsync(staging_fd)
    except OSError:
        pass


def _write_bundle(output_root: Path, payloads: dict[str, bytes], *, project_root: Path) -> None:
    output_name, opened = _open_output_parent(Path(output_root), Path(project_root))
    parent_fd = opened[-1]
    staging_name = f".{output_name}.staging-{uuid.uuid4().hex}"
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    completed = False
    staging_identity: tuple[int, int] | None = None
    staging_fd: int | None = None
    staged_names: list[str] = []
    try:
        try:
            os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CanonicalFusionError("immutable output already exists")
        os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
        staging_fd = os.open(staging_name, directory_flags, dir_fd=parent_fd)
        os.fchmod(staging_fd, 0o700)
        staging_stat = os.fstat(staging_fd)
        staging_identity = (staging_stat.st_dev, staging_stat.st_ino)
        for name in sorted(payloads):
            if name in {"", ".", ".."} or "/" in name or "\\" in name:
                raise CanonicalFusionError("canonical payload file name is unsafe")
            descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=staging_fd,
            )
            staged_names.append(name)
            try:
                os.fchmod(descriptor, 0o600)
                payload = payloads[name]
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("canonical bundle write made no progress")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(staging_fd)
        _rename_noreplace(parent_fd, staging_name, parent_fd, output_name)
        os.fsync(parent_fd)
        if _directory_identity_at(parent_fd, output_name) != staging_identity:
            raise CanonicalFusionError("canonical publish ownership changed")
        completed = True
    except CanonicalFusionError:
        raise
    except OSError as exc:
        raise CanonicalFusionError("unable to publish canonical bundle") from exc
    finally:
        if not completed and staging_fd is not None:
            _cleanup_staging_contents(staging_fd, staged_names)
            _mark_failed_shell(staging_fd)
        if staging_fd is not None:
            try:
                os.close(staging_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def build_canonical_snapshot(
    *,
    import_bundle_root: Path,
    import_bundle_manifest_sha256: str,
    import_validation_receipt_path: Path,
    import_validation_receipt_sha256: str,
    source_manifest_path: Path,
    base_public_manifest_sha256: str,
    base_lineage_manifest_sha256: str,
    output_root: Path,
    project_root: Path,
) -> CanonicalSnapshotResult:
    project_root = project_root.resolve(strict=True)
    import_bundle_manifest_sha256 = _require_sha256(
        import_bundle_manifest_sha256, "workbook import manifest SHA-256"
    )
    import_validation_receipt_sha256 = _require_sha256(
        import_validation_receipt_sha256, "validation receipt SHA-256"
    )
    base_public_manifest_sha256 = _require_sha256(
        base_public_manifest_sha256, "Base public manifest SHA-256"
    )
    base_lineage_manifest_sha256 = _require_sha256(
        base_lineage_manifest_sha256, "Base lineage manifest SHA-256"
    )
    import_bundle_root = _ensure_under(import_bundle_root, project_root, "workbook import bundle")
    _reject_symlink_chain(import_bundle_root, stop=project_root, label="workbook import bundle")
    if not import_bundle_root.is_dir():
        raise CanonicalFusionError("workbook import bundle must be a directory")
    try:
        bundle_members = {item.name for item in import_bundle_root.iterdir()}
    except OSError as exc:
        raise CanonicalFusionError("unable to enumerate workbook import bundle") from exc
    if bundle_members != IMPORT_FILES | {"manifest.json"}:
        raise CanonicalFusionError("workbook import bundle member set is invalid")

    import_manifest_binding = _read_binding(
        import_bundle_root / "manifest.json",
        expected_sha256=import_bundle_manifest_sha256,
        project_root=project_root,
        label="workbook import manifest",
    )
    source_payload = _read_regular_file(
        source_manifest_path, project_root=project_root, label="SourceManifest"
    )
    source_sha256 = _sha256(source_payload)
    source_manifest = _json_object(source_payload, "SourceManifest")
    if source_manifest.get("schema_version") != "reddit_voc_source_manifest_v1":
        raise CanonicalFusionError("SourceManifest schema is unsupported")
    if source_manifest.get("boundaries") != EXPECTED_BOUNDARIES:
        raise CanonicalFusionError("SourceManifest boundaries are invalid")
    _validate_import_manifest(
        import_manifest_binding.value,
        source_manifest_sha256=source_sha256,
        base_public_sha256=_require_sha256(base_public_manifest_sha256, "Base public manifest SHA-256"),
        base_lineage_sha256=_require_sha256(base_lineage_manifest_sha256, "Base lineage manifest SHA-256"),
    )
    receipt_binding = _read_binding(
        import_validation_receipt_path,
        expected_sha256=import_validation_receipt_sha256,
        project_root=project_root,
        label="validation receipt",
    )
    _validate_receipt(
        receipt_binding.value,
        import_manifest_sha256=import_manifest_binding.sha256,
        source_manifest_sha256=source_sha256,
        base_public_sha256=base_public_manifest_sha256,
        base_lineage_sha256=base_lineage_manifest_sha256,
        import_counts=import_manifest_binding.value.get("counts"),
    )
    base = _load_base(
        source_manifest,
        project_root=project_root,
        expected_public_sha256=base_public_manifest_sha256,
        expected_lineage_sha256=base_lineage_manifest_sha256,
    )
    imported = _load_import(
        import_bundle_root,
        import_manifest_binding,
        project_root=project_root,
        source_manifest_sha256=source_sha256,
        base_public_sha256=base_public_manifest_sha256,
        base_lineage_sha256=base_lineage_manifest_sha256,
    )
    _validate_workbook_membership(base, imported)
    outcomes_by_occurrence = _validate_source_row_accounting(imported)
    posts, comments, quarantine, unresolved, provenance, conflicts = _materialize(
        base, imported, outcomes_by_occurrence
    )

    linked_count = sum(row["comment_state"] == CommentState.LINKED.value for row in comments)
    unresolved_count = sum(
        row["comment_state"] == CommentState.UNRESOLVED_PARENT.value for row in comments
    )
    quarantined_count = len(quarantine)
    stored_count = len(comments) + quarantined_count
    if unresolved_count != len(unresolved):
        raise CanonicalFusionError("unresolved parent ledger is not conserved")
    if linked_count + unresolved_count + quarantined_count != stored_count:
        raise CanonicalFusionError("canonical comment states are not conserved")

    document_rows = {
        "comments.jsonl": comments,
        "conflict-ledger.jsonl": conflicts,
        "posts.jsonl": posts,
        "provenance-ledger.jsonl": provenance,
        "quarantine.jsonl": quarantine,
        "unresolved-parent-ledger.jsonl": unresolved,
    }
    payloads = {name: _jsonl_bytes(rows) for name, rows in document_rows.items()}
    file_bindings = {
        name: {
            "bytes": len(payload),
            "rows": len(document_rows[name]),
            "sha256": _sha256(payload),
        }
        for name, payload in sorted(payloads.items())
    }
    dataset_id = f"{imported.manifest['dataset_id']}_canonical_v1"
    manifest = {
        "boundaries": EXPECTED_BOUNDARIES,
        "canonical_counts": {
            "comments_jsonl": len(comments),
            "linked_comments": linked_count,
            "posts": len(posts),
            "quarantined_comments": quarantined_count,
            "stored_comments": stored_count,
            "unresolved_parent_comments": unresolved_count,
        },
        "consumption_status": "blocked_pending_independent_validation",
        "dataset_id": dataset_id,
        "files": file_bindings,
        "independent_validation_status": "pending",
        "inputs": {
            "base_lineage_manifest_sha256": base_lineage_manifest_sha256,
            "base_public_manifest_sha256": base_public_manifest_sha256,
            "source_manifest_sha256": source_sha256,
            "workbook_import_manifest_sha256": import_manifest_binding.sha256,
            "workbook_import_validation_receipt_sha256": receipt_binding.sha256,
        },
        "promotable": False,
        "schema_version": "reddit_voc_canonical_snapshot_manifest_v1",
        "source_row_accounting": {
            "layer_separation": "source_row_terminal_disposition_is_not_canonical_entity_state",
            "source_rows": imported.manifest["counts"]["source_rows"],
            "terminal_outcomes": imported.manifest["counts"]["terminal_outcomes"],
        },
        "state_contract": {
            "canonical_identity": True,
            "comment_states": [state.value for state in CommentState],
            "states_mutually_exclusive": True,
        },
        "governed_base_parent_lineage_debt": {
            **base.parent_lineage_debt_counts,
            "linked_definition": "post_id_resolves_to_canonical_post_not_complete_immediate_parent_chain",
            "workbook_unresolved_parent_separate": True,
        },
        "status": "candidate_built",
        "validation_receipt_sha256": None,
    }
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    payloads["manifest.json"] = manifest_payload
    _write_bundle(output_root, payloads, project_root=project_root)
    return CanonicalSnapshotResult(
        schema_version=str(manifest["schema_version"]),
        dataset_id=dataset_id,
        manifest_sha256=_sha256(manifest_payload),
        posts=len(posts),
        stored_comments=stored_count,
        linked_comments=linked_count,
        unresolved_parent_comments=unresolved_count,
        quarantined_comments=quarantined_count,
        boundaries=dict(EXPECTED_BOUNDARIES),
    )
