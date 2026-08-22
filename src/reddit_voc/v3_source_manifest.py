from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from reddit_voc.report_contracts import canonical_json_bytes


SCHEMA_VERSION = "reddit_voc_source_manifest_v1"
FULL_SCOPE_SELECTION = "owner_attested_complete_scope"
NEGATIVE_SELECTION = "outcome_conditioned_negative"
OWNER_UNKNOWN_QUERY = "owner_attested_unknown"
MOMCOZY_SINGLE_PERIOD = "momcozy_internal_single_period"

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_DIMENSION = re.compile(r"^[A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*$")
_CALENDAR_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SIDE_EFFECT_KEYS = (
    "database_write",
    "deploy",
    "live_send",
    "provider_call",
    "remote_write",
)
_FULL_SCOPE_BLOCKED_USES = frozenset(
    {
        "cross_brand_visibility",
        "market_share",
        "rv_in_05",
        "sov",
        "trend",
    }
)
_NEGATIVE_BLOCKED_USES = frozenset(
    {
        "brand_health",
        "cross_brand_visibility",
        "market_share",
        MOMCOZY_SINGLE_PERIOD,
        "rv_in_05",
        "sov",
        "trend",
    }
)


class SourceManifestError(ValueError):
    pass


@dataclass(frozen=True)
class WorkbookContract:
    sheet_name: str
    expected_dimension: str
    expected_headers: tuple[str, ...]
    expected_data_rows: int
    expected_post_rows: int
    expected_comment_rows: int


@dataclass(frozen=True)
class SelectionWindow:
    start_calendar_date: str
    end_calendar_date: str


@dataclass(frozen=True)
class SourceContract:
    source_snapshot_id: str
    relative_path: PurePosixPath
    sha256: str
    bytes: int
    workbook: WorkbookContract
    source_kind: str
    selection_class: str
    query_profile_status: str
    source_timezone_status: str
    event_time_precision: str
    selection_window: SelectionWindow
    coverage_status: str
    allowed_metric_families: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    selection_reason_codes: tuple[str, ...]

    @property
    def expected_headers(self) -> tuple[str, ...]:
        return self.workbook.expected_headers

    @property
    def expected_data_rows(self) -> int:
        return self.workbook.expected_data_rows


@dataclass(frozen=True)
class BaseContract:
    dataset_version: str
    manifest_relative_path: PurePosixPath
    lineage_manifest_relative_path: PurePosixPath
    public_manifest_sha256: str
    lineage_manifest_sha256: str


@dataclass(frozen=True)
class OwnerAttestation:
    attestation_id: str
    attested_at_calendar_date: str
    statement_cn: str
    applies_to_source_snapshot_ids: tuple[str, ...]
    sha256: str


@dataclass(frozen=True)
class SideEffectBoundaries:
    provider_call: bool
    database_write: bool
    remote_write: bool
    deploy: bool
    live_send: bool
    production_unchanged: bool


@dataclass(frozen=True)
class SourceManifest:
    schema_version: str
    dataset_id: str
    base: BaseContract
    owner_attestation: OwnerAttestation
    sources: tuple[SourceContract, ...]
    boundaries: SideEffectBoundaries
    manifest_sha256: str

    @property
    def base_dataset_version(self) -> str:
        return self.base.dataset_version

    @property
    def base_lineage_manifest_sha256(self) -> str:
        return self.base.lineage_manifest_sha256

    @property
    def source_rows(self) -> int:
        return sum(item.expected_data_rows for item in self.sources)

    def source(self, source_snapshot_id: str) -> SourceContract:
        for item in self.sources:
            if item.source_snapshot_id == source_snapshot_id:
                return item
        raise SourceManifestError(f"unknown source_snapshot_id:{source_snapshot_id}")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceManifestError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], label: str) -> None:
    actual = set(value)
    target = set(expected)
    if actual != target:
        raise SourceManifestError(
            f"{label} keys mismatch:missing={sorted(target - actual)}:extra={sorted(actual - target)}"
        )


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceManifestError(f"{label} must be a non-empty string")
    return value


def _safe_id(value: object, label: str) -> str:
    result = _string(value, label)
    if not _SAFE_ID.fullmatch(result):
        raise SourceManifestError(f"{label} is invalid")
    return result


def _sha(value: object, label: str) -> str:
    result = _string(value, label)
    if not _SHA256.fullmatch(result):
        raise SourceManifestError(f"{label} must be sha256")
    return result


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SourceManifestError(f"{label} must be a positive integer")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceManifestError(f"{label} must be a nonnegative integer")
    return value


def _sorted_strings(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise SourceManifestError(f"{label} must be a list of strings")
    result = tuple(_string(item, f"{label}[]") for item in value)
    if len(set(result)) != len(result):
        raise SourceManifestError(f"{label} contains duplicates")
    if result != tuple(sorted(result)):
        raise SourceManifestError(f"{label} must be sorted")
    return result


def _ordered_strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SourceManifestError(f"{label} must be a list of strings")
    result = tuple(_string(item, f"{label}[]") for item in value)
    if len(set(result)) != len(result):
        raise SourceManifestError(f"{label} contains duplicates")
    return result


def _calendar_date(value: object, label: str) -> str:
    result = _string(value, label)
    if not _CALENDAR_DATE.fullmatch(result):
        raise SourceManifestError(f"{label} must be YYYY-MM-DD")
    try:
        date.fromisoformat(result)
    except ValueError as exc:
        raise SourceManifestError(f"{label} must be YYYY-MM-DD") from exc
    return result


def _safe_relative_path(value: object, label: str) -> PurePosixPath:
    raw = _string(value, label)
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise SourceManifestError(f"unsafe {label}")
    return relative


def _read_open_file(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_regular_path_once(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        raise SourceManifestError(f"{label} unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SourceManifestError(f"{label} must be a regular file")
        return _read_open_file(descriptor)
    finally:
        os.close(descriptor)


def _read_regular_relative_once(
    project_root: Path,
    relative: PurePosixPath,
    label: str,
) -> bytes:
    root = Path(os.path.abspath(os.fspath(project_root)))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    opened: list[int] = []
    try:
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            raise SourceManifestError("project_root must be a regular directory")
        directory_fd = os.open(os.fspath(root), directory_flags)
        opened.append(directory_fd)
        for part in relative.parts[:-1]:
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened.append(directory_fd)
        file_fd = os.open(relative.parts[-1], flags, dir_fd=directory_fd)
        opened.append(file_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise SourceManifestError(f"{label} must be a regular file")
        return _read_open_file(file_fd)
    except OSError as exc:
        raise SourceManifestError(f"{label} unavailable:{relative.as_posix()}") from exc
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceManifestError(f"duplicate json key:{key}")
        result[key] = value
    return result


def _load_canonical_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = _read_regular_path_once(path, "manifest")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceManifestError("manifest is not valid UTF-8 JSON") from exc
    document = _object(value, "manifest")
    if payload != canonical_json_bytes(document) + b"\n":
        raise SourceManifestError("manifest bytes are not canonical")
    return document, payload


def _bound_json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceManifestError(f"{label} is not valid JSON") from exc
    return _object(value, label)


def _parse_base(value: object, project_root: Path) -> BaseContract:
    document = _object(value, "base")
    _exact_keys(
        document,
        {
            "dataset_version",
            "lineage_manifest_relative_path",
            "manifest_relative_path",
            "public_manifest_sha256",
            "lineage_manifest_sha256",
        },
        "base",
    )
    contract = BaseContract(
        dataset_version=_safe_id(document["dataset_version"], "base.dataset_version"),
        manifest_relative_path=_safe_relative_path(
            document["manifest_relative_path"], "base manifest_relative_path"
        ),
        lineage_manifest_relative_path=_safe_relative_path(
            document["lineage_manifest_relative_path"],
            "base lineage_manifest_relative_path",
        ),
        public_manifest_sha256=_sha(
            document["public_manifest_sha256"], "base.public_manifest_sha256"
        ),
        lineage_manifest_sha256=_sha(
            document["lineage_manifest_sha256"], "base.lineage_manifest_sha256"
        ),
    )
    if (
        contract.manifest_relative_path == contract.lineage_manifest_relative_path
        or contract.public_manifest_sha256 == contract.lineage_manifest_sha256
    ):
        raise SourceManifestError("base public and lineage bindings must be distinct")

    public_payload = _read_regular_relative_once(
        project_root,
        contract.manifest_relative_path,
        "base manifest",
    )
    lineage_payload = _read_regular_relative_once(
        project_root,
        contract.lineage_manifest_relative_path,
        "base lineage manifest",
    )
    if hashlib.sha256(public_payload).hexdigest() != contract.public_manifest_sha256:
        raise SourceManifestError("base public manifest sha256 mismatch")
    if hashlib.sha256(lineage_payload).hexdigest() != contract.lineage_manifest_sha256:
        raise SourceManifestError("base lineage manifest sha256 mismatch")

    public_value = _bound_json_object(public_payload, "base manifest")
    lineage_value = _bound_json_object(lineage_payload, "base lineage manifest")
    if public_value.get("dataset_version") != contract.dataset_version:
        raise SourceManifestError("base dataset_version mismatch")
    if lineage_value.get("dataset_version") != contract.dataset_version:
        raise SourceManifestError("base lineage dataset_version mismatch")
    supported_schemas = {
        "reddit_voc_site_snapshot_manifest_v1",
        "reddit_voc_site_snapshot_manifest_v2",
    }
    if public_value.get("schema_version") not in supported_schemas:
        raise SourceManifestError("base schema_version unsupported")
    if lineage_value.get("schema_version") not in supported_schemas:
        raise SourceManifestError("base lineage schema_version unsupported")
    projection = public_value.get("projection")
    if not isinstance(projection, dict) or projection.get("audience") != "public_ui":
        raise SourceManifestError("base public manifest role mismatch")
    if not isinstance(lineage_value.get("source_boundaries"), dict):
        raise SourceManifestError("base lineage manifest role mismatch")
    return contract


def _parse_attestation(value: object) -> OwnerAttestation:
    document = _object(value, "owner_attestation")
    _exact_keys(
        document,
        {
            "attestation_id",
            "attested_at_calendar_date",
            "statement_cn",
            "applies_to_source_snapshot_ids",
            "sha256",
        },
        "owner_attestation",
    )
    source_ids = _sorted_strings(
        document["applies_to_source_snapshot_ids"],
        "owner_attestation.applies_to_source_snapshot_ids",
    )
    attestation_payload = {
        "attestation_id": _safe_id(
            document["attestation_id"], "owner_attestation.attestation_id"
        ),
        "attested_at_calendar_date": _calendar_date(
            document["attested_at_calendar_date"],
            "owner_attestation.attested_at_calendar_date",
        ),
        "statement_cn": _string(
            document["statement_cn"], "owner_attestation.statement_cn"
        ),
        "applies_to_source_snapshot_ids": list(source_ids),
    }
    expected_sha = hashlib.sha256(canonical_json_bytes(attestation_payload)).hexdigest()
    if _sha(document["sha256"], "owner_attestation.sha256") != expected_sha:
        raise SourceManifestError("owner attestation sha256 mismatch")
    return OwnerAttestation(
        attestation_id=str(attestation_payload["attestation_id"]),
        attested_at_calendar_date=str(attestation_payload["attested_at_calendar_date"]),
        statement_cn=str(attestation_payload["statement_cn"]),
        applies_to_source_snapshot_ids=source_ids,
        sha256=expected_sha,
    )


def _parse_workbook(value: object, label: str) -> WorkbookContract:
    document = _object(value, label)
    _exact_keys(
        document,
        {
            "sheet_name",
            "expected_dimension",
            "expected_headers",
            "expected_data_rows",
            "expected_entity_counts",
        },
        label,
    )
    headers = _ordered_strings(document["expected_headers"], f"{label}.expected_headers")
    dimension = _string(document["expected_dimension"], f"{label}.expected_dimension")
    if not _DIMENSION.fullmatch(dimension):
        raise SourceManifestError(f"{label}.expected_dimension is invalid")
    entity_counts = _object(document["expected_entity_counts"], f"{label}.expected_entity_counts")
    _exact_keys(entity_counts, {"posts", "comments"}, f"{label}.expected_entity_counts")
    post_rows = _nonnegative_integer(
        entity_counts["posts"], f"{label}.expected_entity_counts.posts"
    )
    comment_rows = _nonnegative_integer(
        entity_counts["comments"], f"{label}.expected_entity_counts.comments"
    )
    data_rows = _positive_integer(
        document["expected_data_rows"], f"{label}.expected_data_rows"
    )
    if post_rows + comment_rows != data_rows:
        raise SourceManifestError(f"{label}.expected_entity_counts are not conserved")
    return WorkbookContract(
        sheet_name=_string(document["sheet_name"], f"{label}.sheet_name"),
        expected_dimension=dimension,
        expected_headers=headers,
        expected_data_rows=data_rows,
        expected_post_rows=post_rows,
        expected_comment_rows=comment_rows,
    )


def _parse_window(value: object, label: str) -> SelectionWindow:
    document = _object(value, label)
    _exact_keys(document, {"start_calendar_date", "end_calendar_date"}, label)
    start = _calendar_date(document["start_calendar_date"], f"{label}.start_calendar_date")
    end = _calendar_date(document["end_calendar_date"], f"{label}.end_calendar_date")
    if start > end:
        raise SourceManifestError(f"{label} is reversed")
    return SelectionWindow(start_calendar_date=start, end_calendar_date=end)


def _validate_source_policy(source: SourceContract) -> None:
    blocked = frozenset(source.blocked_uses)
    if source.selection_class == FULL_SCOPE_SELECTION:
        if frozenset(source.allowed_metric_families) & blocked:
            raise SourceManifestError("allowed and blocked metric families overlap")
        if source.query_profile_status != OWNER_UNKNOWN_QUERY:
            raise SourceManifestError("full-scope source query profile must be owner_attested_unknown")
        if source.allowed_metric_families != (MOMCOZY_SINGLE_PERIOD,):
            raise SourceManifestError("full-scope source may allow only Momcozy single-period metrics")
        if blocked != _FULL_SCOPE_BLOCKED_USES:
            raise SourceManifestError("full-scope source blocked uses mismatch")
        if source.coverage_status != FULL_SCOPE_SELECTION:
            raise SourceManifestError("full-scope source coverage status mismatch")
    elif source.selection_class == NEGATIVE_SELECTION:
        if source.allowed_metric_families:
            raise SourceManifestError("negative-selected source cannot allow metrics")
        if blocked != _NEGATIVE_BLOCKED_USES:
            raise SourceManifestError("negative-selected source blocked uses mismatch")
        if source.query_profile_status != "not_applicable":
            raise SourceManifestError("negative-selected source query profile must be not_applicable")
        if source.coverage_status != NEGATIVE_SELECTION:
            raise SourceManifestError("negative-selected source coverage status mismatch")
    else:
        raise SourceManifestError("unsupported selection_class")


def _parse_source(value: object, project_root: Path, index: int) -> SourceContract:
    label = f"sources[{index}]"
    document = _object(value, label)
    _exact_keys(
        document,
        {
            "source_snapshot_id",
            "relative_path",
            "sha256",
            "bytes",
            "workbook",
            "source_kind",
            "selection_class",
            "query_profile_status",
            "source_timezone_status",
            "event_time_precision",
            "selection_window",
            "coverage_status",
            "allowed_metric_families",
            "blocked_uses",
            "selection_reason_codes",
        },
        label,
    )
    relative = _safe_relative_path(document["relative_path"], "source relative_path")
    payload = _read_regular_relative_once(
        project_root,
        relative,
        "source file",
    )
    expected_bytes = _positive_integer(document["bytes"], f"{label}.bytes")
    if len(payload) != expected_bytes:
        raise SourceManifestError(f"source bytes mismatch:{relative.as_posix()}")
    expected_sha = _sha(document["sha256"], f"{label}.sha256")
    if hashlib.sha256(payload).hexdigest() != expected_sha:
        raise SourceManifestError(f"source sha256 mismatch:{relative.as_posix()}")
    source = SourceContract(
        source_snapshot_id=_safe_id(
            document["source_snapshot_id"], f"{label}.source_snapshot_id"
        ),
        relative_path=relative,
        sha256=expected_sha,
        bytes=expected_bytes,
        workbook=_parse_workbook(document["workbook"], f"{label}.workbook"),
        source_kind=_safe_id(document["source_kind"], f"{label}.source_kind"),
        selection_class=_safe_id(
            document["selection_class"], f"{label}.selection_class"
        ),
        query_profile_status=_safe_id(
            document["query_profile_status"], f"{label}.query_profile_status"
        ),
        source_timezone_status=_safe_id(
            document["source_timezone_status"], f"{label}.source_timezone_status"
        ),
        event_time_precision=_safe_id(
            document["event_time_precision"], f"{label}.event_time_precision"
        ),
        selection_window=_parse_window(
            document["selection_window"], f"{label}.selection_window"
        ),
        coverage_status=_safe_id(
            document["coverage_status"], f"{label}.coverage_status"
        ),
        allowed_metric_families=_sorted_strings(
            document["allowed_metric_families"],
            f"{label}.allowed_metric_families",
            allow_empty=True,
        ),
        blocked_uses=_sorted_strings(document["blocked_uses"], f"{label}.blocked_uses"),
        selection_reason_codes=_sorted_strings(
            document["selection_reason_codes"], f"{label}.selection_reason_codes"
        ),
    )
    if source.source_kind != "workbook_export":
        raise SourceManifestError("unsupported source_kind")
    if source.source_timezone_status != "unknown" or source.event_time_precision != "day":
        raise SourceManifestError("workbook time precision must be floating day")
    _validate_source_policy(source)
    return source


def _parse_boundaries(value: object) -> SideEffectBoundaries:
    document = _object(value, "boundaries")
    _exact_keys(document, {*_SIDE_EFFECT_KEYS, "production_unchanged"}, "boundaries")
    for key in _SIDE_EFFECT_KEYS:
        if document[key] is not False:
            raise SourceManifestError(f"side-effect boundary must be false:{key}")
    if document["production_unchanged"] is not True:
        raise SourceManifestError("side-effect boundary production_unchanged must be true")
    return SideEffectBoundaries(
        provider_call=False,
        database_write=False,
        remote_write=False,
        deploy=False,
        live_send=False,
        production_unchanged=True,
    )


def load_source_manifest(path: Path, project_root: Path) -> SourceManifest:
    document, payload = _load_canonical_manifest(Path(path))
    _exact_keys(
        document,
        {
            "schema_version",
            "dataset_id",
            "base",
            "owner_attestation",
            "sources",
            "boundaries",
        },
        "manifest",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise SourceManifestError("unsupported source manifest schema_version")
    sources_value = document["sources"]
    if not isinstance(sources_value, list) or not sources_value:
        raise SourceManifestError("sources must be a non-empty list")
    sources = tuple(
        _parse_source(item, Path(project_root), index)
        for index, item in enumerate(sources_value)
    )
    source_ids = tuple(item.source_snapshot_id for item in sources)
    if len(set(source_ids)) != len(source_ids):
        raise SourceManifestError("duplicate source_snapshot_id")
    if source_ids != tuple(sorted(source_ids)):
        raise SourceManifestError("sources must be sorted by source_snapshot_id")
    attestation = _parse_attestation(document["owner_attestation"])
    if set(attestation.applies_to_source_snapshot_ids) != {
        item.source_snapshot_id
        for item in sources
        if item.selection_class == FULL_SCOPE_SELECTION
    }:
        raise SourceManifestError("owner attestation scope mismatch")
    return SourceManifest(
        schema_version=SCHEMA_VERSION,
        dataset_id=_safe_id(document["dataset_id"], "dataset_id"),
        base=_parse_base(document["base"], Path(project_root)),
        owner_attestation=attestation,
        sources=sources,
        boundaries=_parse_boundaries(document["boundaries"]),
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )
