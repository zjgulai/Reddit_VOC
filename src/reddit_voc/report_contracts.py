from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Protocol, runtime_checkable


Phase = Literal["translation", "semantic_validation"]
_PHASES = frozenset({"translation", "semantic_validation"})
_KNOWN_SCHEMA_IDS = frozenset(
    {
        "daily-translation-manifest-v1",
        "daily-translation-attempt-v1",
        "daily-prepared-bundle-index-v1",
    }
)
_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "const",
        "enum",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "minLength",
        "pattern",
        "minimum",
    }
)


@dataclass(frozen=True)
class ReportSchemaAssets:
    manifest_schema: Mapping[str, object]
    attempt_schema: Mapping[str, object]
    bundle_index_schema: Mapping[str, object]
    sha256_by_name: Mapping[str, str]


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class AttemptEvidence:
    sequence: int
    phase: Phase
    http_status: int | None
    outcome: str
    retryable: bool
    duration_ms: int
    response_id: str | None
    actual_model: str | None
    system_fingerprint: str | None
    finish_reason: str | None
    usage: TokenUsage | None


class ProviderAttemptLifecycleSink(Protocol):
    """Durable callbacks around the exact external provider boundary."""

    def reserve(
        self,
        *,
        sequence: int,
        phase: Phase,
        request_payload_sha256: str,
    ) -> None: ...

    def start(
        self,
        *,
        sequence: int,
        phase: Phase,
        request_payload_sha256: str,
    ) -> None: ...

    def terminal(
        self,
        *,
        sequence: int,
        phase: Phase,
        request_payload_sha256: str,
        evidence: AttemptEvidence,
    ) -> None: ...

    def unknown(
        self,
        *,
        sequence: int,
        phase: Phase,
        request_payload_sha256: str,
    ) -> None: ...


@dataclass(frozen=True)
class MonotonicDeadline:
    expires_at: float


class AttemptReservationSink(Protocol):
    def __call__(self, *, sequence: int, phase: Phase) -> None: ...


class AttemptBudget:
    def __init__(
        self,
        max_attempts: int = 100,
        *,
        reservation_sink: AttemptReservationSink | None = None,
    ) -> None:
        if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
            raise ValueError("attempt_budget_out_of_range")
        self._max_attempts = max_attempts
        self._reservation_sink = reservation_sink
        self._used = 0
        self._lock = threading.Lock()

    def reserve(self, phase: Phase) -> int:
        if phase not in _PHASES:
            raise ValueError("invalid_attempt_phase")
        with self._lock:
            if self._used >= self._max_attempts:
                raise RuntimeError("attempt_budget_exhausted")
            sequence = self._used + 1
            if self._reservation_sink is not None:
                self._reservation_sink(sequence=sequence, phase=phase)
            self._used = sequence
            return sequence

    @property
    def used(self) -> int:
        with self._lock:
            return self._used


@runtime_checkable
class JsonCompletion(Protocol):
    request_id: str
    model: str
    system_fingerprint: str | None
    finish_reason: str
    content: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]


class JsonCompletionClient(Protocol):
    def complete_json(
        self,
        *,
        phase: Phase,
        system_prompt: str,
        user_payload: Mapping[str, object],
        deadline: MonotonicDeadline,
        attempt_budget: AttemptBudget,
    ) -> JsonCompletion: ...


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _trusted_regular_path(*, trusted_root: Path, path: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(trusted_root)))
    candidate = Path(os.path.abspath(os.fspath(path)))
    if trusted_root.is_symlink():
        raise ValueError("trusted_root_is_symlink")
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path_outside_trusted_root") from exc
    if not relative.parts:
        raise ValueError("not_regular_file")
    current = root
    try:
        root_stat = current.lstat()
    except OSError as exc:
        raise ValueError("trusted_root_unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("trusted_root_not_directory")
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise ValueError("path_outside_trusted_root")
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise ValueError("asset_unavailable") from exc
        if stat.S_ISLNK(current_stat.st_mode):
            raise ValueError("not_regular_file")
    if not stat.S_ISREG(current_stat.st_mode):
        raise ValueError("not_regular_file")
    return candidate


def read_regular_utf8(*, trusted_root: Path, path: Path) -> str:
    candidate = _trusted_regular_path(trusted_root=trusted_root, path=path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ValueError("asset_open_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("not_regular_file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(5 * 1024 * 1024 + 1)
        if len(payload) > 5 * 1024 * 1024:
            raise ValueError("asset_too_large")
    finally:
        os.close(descriptor)
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid_utf8") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def load_regular_json(*, trusted_root: Path, path: Path) -> object:
    text = read_regular_utf8(trusted_root=trusted_root, path=path)
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except ValueError as exc:
        if str(exc).startswith("duplicate_json_key"):
            raise
        raise ValueError("invalid_json") from exc


def _assert_schema_definition(schema: object, *, path: str = "$") -> Mapping[str, object]:
    if not isinstance(schema, Mapping):
        raise ValueError(f"schema_node_not_object:{path}")
    unknown = sorted(set(schema) - _SUPPORTED_SCHEMA_KEYWORDS)
    if unknown:
        raise ValueError(f"unsupported_schema_keyword:{path}:{unknown[0]}")
    declared_type = schema.get("type")
    if isinstance(declared_type, list):
        if declared_type != ["string", "null"]:
            raise ValueError(f"unsupported_type_union:{path}")
    elif declared_type is not None and declared_type not in {
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
        "null",
    }:
        raise ValueError(f"unsupported_schema_type:{path}")
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise ValueError(f"schema_properties_not_object:{path}")
        for name, child in properties.items():
            if not isinstance(name, str):
                raise ValueError(f"schema_property_name_invalid:{path}")
            _assert_schema_definition(child, path=f"{path}.properties.{name}")
    items = schema.get("items")
    if items is not None:
        _assert_schema_definition(items, path=f"{path}.items")
    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise ValueError(f"schema_pattern_not_string:{path}")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"schema_pattern_invalid:{path}") from exc
    return schema


def _type_matches(declared_type: object, value: object) -> bool:
    if declared_type == ["string", "null"]:
        return value is None or isinstance(value, str)
    if declared_type == "object":
        return isinstance(value, Mapping)
    if declared_type == "array":
        return isinstance(value, list)
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "null":
        return value is None
    return True


def _validate_value(schema: Mapping[str, object], value: object, *, path: str) -> None:
    declared_type = schema.get("type")
    if declared_type is not None and not _type_matches(declared_type, value):
        raise ValueError(f"schema_type_mismatch:{path}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"schema_const_mismatch:{path}")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or value not in enum:
            raise ValueError(f"schema_enum_mismatch:{path}")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ValueError(f"schema_required_invalid:{path}")
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"schema_required_missing:{path}:{missing[0]}")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"schema_properties_not_object:{path}")
        unknown = [name for name in value if name not in properties]
        if unknown and schema.get("additionalProperties") is False:
            raise ValueError(f"schema_additional_property:{path}:{unknown[0]}")
        for name, child_schema in properties.items():
            if name in value:
                _validate_value(child_schema, value[name], path=f"{path}.{name}")

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if minimum_items is not None:
            if isinstance(minimum_items, bool) or not isinstance(minimum_items, int):
                raise ValueError(f"schema_min_items_invalid:{path}")
            if len(value) < minimum_items:
                raise ValueError(f"schema_min_items_failed:{path}")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_value(item_schema, item, path=f"{path}[{index}]")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < int(minimum_length):
            raise ValueError(f"schema_min_length_failed:{path}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            raise ValueError(f"schema_pattern_failed:{path}")

    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema:
        if value < schema["minimum"]:
            raise ValueError(f"schema_minimum_failed:{path}")


def _validate_bundle_index_semantics(value: object) -> None:
    if not isinstance(value, Mapping):
        return
    entries = value.get("entries")
    if not isinstance(entries, list):
        return
    sort_keys: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        scope = str(entry.get("scope") or "")
        relative_path = str(entry.get("relative_path") or "")
        parts = Path(relative_path).parts
        if (
            not relative_path
            or Path(relative_path).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative_path
        ):
            raise ValueError("bundle_index_path_unsafe")
        if relative_path in {
            "bundle-index.json",
            "daily-prepared-bundle-index-v1.schema.json",
        }:
            raise ValueError("bundle_index_lists_itself")
        sort_keys.append((scope, relative_path))
    if sort_keys != sorted(sort_keys):
        raise ValueError("bundle_index_entries_not_sorted")
    if len(sort_keys) != len(set(sort_keys)):
        raise ValueError("bundle_index_entries_duplicate")


def validate_schema_instance(*, schema: Mapping[str, object], value: object) -> None:
    checked_schema = _assert_schema_definition(schema)
    _validate_value(checked_schema, value, path="$")
    if checked_schema.get("$id") == "daily-prepared-bundle-index-v1":
        _validate_bundle_index_semantics(value)


def load_and_validate_schema(
    *, trusted_root: Path, schema_path: Path, value: object
) -> None:
    schema = load_regular_json(trusted_root=trusted_root, path=schema_path)
    if not isinstance(schema, Mapping):
        raise ValueError("schema_root_not_object")
    if schema.get("$id") not in _KNOWN_SCHEMA_IDS:
        raise ValueError("unknown_schema_version")
    validate_schema_instance(schema=schema, value=value)


def load_report_schema_assets(*, config_root: Path) -> ReportSchemaAssets:
    schema_root = config_root / "schemas"
    names = {
        "manifest_schema": "daily-translation-manifest-v1.schema.json",
        "attempt_schema": "daily-translation-attempt-v1.schema.json",
        "bundle_index_schema": "daily-prepared-bundle-index-v1.schema.json",
    }
    loaded: dict[str, Mapping[str, object]] = {}
    hashes: dict[str, str] = {}
    for field_name, file_name in names.items():
        path = schema_root / file_name
        text = read_regular_utf8(trusted_root=config_root, path=path)
        value = load_regular_json(trusted_root=config_root, path=path)
        if not isinstance(value, Mapping):
            raise ValueError("schema_root_not_object")
        expected_id = file_name.removesuffix(".schema.json")
        if value.get("$id") != expected_id or value.get("$id") not in _KNOWN_SCHEMA_IDS:
            raise ValueError("unknown_schema_version")
        _assert_schema_definition(value)
        loaded[field_name] = value
        hashes[file_name] = sha256_hex(text.encode("utf-8"))
    return ReportSchemaAssets(
        manifest_schema=loaded["manifest_schema"],
        attempt_schema=loaded["attempt_schema"],
        bundle_index_schema=loaded["bundle_index_schema"],
        sha256_by_name=hashes,
    )


def load_translation_terms_document(*, config_root: Path) -> Mapping[str, object]:
    value = load_regular_json(
        trusted_root=config_root,
        path=config_root / "translation_terms.json",
    )
    if not isinstance(value, Mapping):
        raise ValueError("translation_terms_root_invalid")
    root_keys = {
        "schema_version",
        "preserve_exact",
        "case_sensitive_terms",
        "case_insensitive_terms",
        "model_patterns",
        "unit_patterns",
        "allow_source_equal_patterns",
        "source_signal_rules",
    }
    if set(value) != root_keys:
        raise ValueError("translation_terms_keys_invalid")
    if value.get("schema_version") != "translation-terms-v1":
        raise ValueError("translation_terms_version_invalid")
    rules = value.get("source_signal_rules")
    if not isinstance(rules, Mapping) or set(rules) != {"negation", "comparison", "sentiment"}:
        raise ValueError("translation_terms_signal_keys_invalid")
    list_fields = [
        "preserve_exact",
        "case_sensitive_terms",
        "case_insensitive_terms",
        "model_patterns",
        "unit_patterns",
        "allow_source_equal_patterns",
    ]
    for field_name in list_fields:
        _validate_sorted_string_list(value.get(field_name), field_name=field_name)
    for field_name in ["negation", "comparison", "sentiment"]:
        _validate_sorted_string_list(rules.get(field_name), field_name=f"source_signal_rules.{field_name}")
    for field_name in ["model_patterns", "unit_patterns", "allow_source_equal_patterns"]:
        _validate_regex_list(value[field_name], field_name=field_name)
    for field_name in ["negation", "comparison", "sentiment"]:
        _validate_regex_list(rules[field_name], field_name=f"source_signal_rules.{field_name}")
    return value


def _validate_sorted_string_list(value: object, *, field_name: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"translation_terms_list_invalid:{field_name}")
    if value != sorted(set(value)):
        raise ValueError(f"translation_terms_not_sorted_unique:{field_name}")


def _validate_regex_list(value: object, *, field_name: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"translation_terms_list_invalid:{field_name}")
    for pattern in value:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"translation_terms_invalid_regex:{field_name}") from exc
