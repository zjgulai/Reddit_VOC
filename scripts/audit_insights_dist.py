#!/usr/bin/env python3
"""Prepare and audit the immutable public Reddit VOC data bundle.

The current-release pointer is the only runtime selector.  Explicit version
arguments are independent expectations so a stale or substituted pointer fails
closed.  ``--prepare-dist`` removes only files below ``dist/data`` that are not
bound by the selected public manifests; it never mutates the source public tree.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterator


CURRENT_RELEASE_PATH = PurePosixPath("data/reddit-voc/current-release.json")
CASE_MANIFEST_PATH = PurePosixPath("data/cases/manifest.v1.json")
CASE_INDEX_PATH = PurePosixPath("data/cases/case-index.v1.json")
DATASET_KEYS = ("base", "insights", "reports", "personas")
V2_AUXILIARY_DATASET_KEYS = ("brand_health", "quarter_insights", "casebook")
VERSION_PREFIXES = {
    "base": "reddit_voc_site_snapshot_",
    "insights": "reddit_voc_insights_",
    "reports": "reddit_voc_reports_",
    "personas": "reddit_voc_personas_",
}
SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
V3_MANIFEST_SCHEMAS = {
    "base": "reddit_voc_site_snapshot_manifest_v3",
    "insights": "reddit_voc_insights_public_manifest_v3",
    "reports": "reddit_voc_reports_public_manifest_v3",
    "personas": "reddit_voc_personas_manifest_v3",
}
V3_BASE_FILES = frozenset(
    {
        "aggregates-public.json",
        "posts-public.json",
        "comments-public.json",
        "tag-dictionary-public.json",
    }
)
V3_TRANSLATED_BASE_FILES = frozenset(
    {
        *V3_BASE_FILES,
        "post-translations-public.json",
        "comment-translations-public.json",
    }
)
V3_INSIGHTS_FILES = frozenset({"insights.json", "validation-receipt.json"})
V3_REPORTS_FILES = frozenset(
    {
        "report-index.json",
        "validation-receipt.json",
        "current/daily.json",
        "current/weekly.json",
        "current/monthly.json",
        "archive/daily.json",
        "archive/weekly.json",
        "archive/monthly.json",
    }
)
V3_REPORTS_HISTORY_BOOTSTRAP_FILES = frozenset(
    {*V3_REPORTS_FILES, "business-history-index.json"}
)
V3_PERSONA_FILES = frozenset(
    {
        "personas.json",
        "persona-tags.json",
        "persona-atomic-catalog.json",
        "persona-atomic-facts.jsonl",
        "persona-cohort-bridge.json",
        "assets/persona-competitor-comparer.svg",
        "assets/persona-explicit-advocate.svg",
        "assets/persona-fallback-neutral.svg",
        "assets/persona-fit-output-optimizer.svg",
        "assets/persona-operations-troubleshooter.svg",
        "assets/persona-product-evaluator.svg",
        "assets/persona-purchase-decision.svg",
        "assets/persona-service-support-seeker.svg",
        "assets/persona-work-scenario.svg",
    }
)
V3_EXPECTED_FILES = {
    "base": V3_BASE_FILES,
    "insights": V3_INSIGHTS_FILES,
    "reports": V3_REPORTS_FILES,
    "personas": V3_PERSONA_FILES,
}
V3_STATIC_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}

# This independent public receipt is intentionally not declared by the frozen
# insights manifest.  Admit only these reviewed pairs; a future manifest must
# receive its own reviewed contract instead of inheriting a wildcard.
V3_INSIGHTS_SIDECAR_NAME = "public-validation-receipt.json"
V3_INSIGHTS_SIDECAR_MANIFEST_SHA256 = (
    "0449f1d6412eec301415f322feb0b6a525d568a2d8267851b29fa077447446aa"
)
V3_INSIGHTS_SIDECAR_BYTES = 633
V3_INSIGHTS_SIDECAR_SHA256 = (
    "dfdbca2be18152d0d593c82ab646f204d782274210a74d1a2e5ced211bcf7ca4"
)
V3_INSIGHTS_SIDECAR_CONTRACTS = {
    V3_INSIGHTS_SIDECAR_MANIFEST_SHA256: {
        "bytes": V3_INSIGHTS_SIDECAR_BYTES,
        "sha256": V3_INSIGHTS_SIDECAR_SHA256,
    },
    "8c6b0d3f1fa27857cc31d74870e7da985da669f02fcb89fec00d32bb56ddd348": {
        "bytes": 633,
        "sha256": "f7fefc4176da485104e7cd858ae26b2664aef62f20036b02d2b9a6be0ea3c30d",
    },
    "e92d8b4e8a65a451af48cdbc3fe946198187b9239fa3e8f04c9b25b82fb4be2f": {
        "bytes": 633,
        "sha256": "fbf155db5abba51d5578479f4b2d9933c1ebe68218c528a054a499d31da2e5b1",
    },
    "82e44dcf995372167b08f4e2ec92267b1d113db90ce95867d1e72949fa8124a3": {
        "bytes": 633,
        "sha256": "32d3e5fbdbc2d7ebe61f27d5518aaa7aa5beff84f71134f07b655d18cae5357c",
    },
    "9c0d84009e25090e14a278e3d953908f255e65a33707f627bbb476d134c5354a": {
        "bytes": 633,
        "sha256": "a9d97d0778f2e1ada156a411835ffad03f2b159dd7c29433b0958cba8939517a",
    },
    "e43ac17c0dda5e8f481d35e7426c17c83acf6115c4af76457ee0ac7009702024": {
        "bytes": 791,
        "sha256": "f1a5977eab86db1b1af56f54064e67f1578616d754faa58c1d4a85a004e821cf",
    },
    "a3d4e5377d878219e377520f4fa87553226e13465dca075035fe8c225b1f8705": {
        "bytes": 791,
        "sha256": "06995826ee20d1e72e21e5d6a4b022894666bc604d9ab9309cbae7326463e9ae",
    },
    "ff106e7980ed90f478f059e267251d8d79bef941bdad2609bd6565d1e49f6abd": {
        "bytes": 791,
        "sha256": "44756e395dbc4a8e1fb46963b6e4c592aa5843a44a29a7486ce404d097ae6b12",
    },
}
V3_REPORTS_SIDECAR_CONTRACTS = {
    "1ab7a72642942b70768fe43648949501487dd144f4d0bcdd9b874fdc73a7bb3d": {
        "bytes": 836,
        "sha256": "ea11d9213cc61a68ccc74381fde01fecb3f75f3b2bf4aca388a51ade45e63de9",
    },
    "0813da178f484a75f1bc0bd702e19ba41cabe3c0f7977077a16f56c7fca46bf2": {
        "bytes": 839,
        "sha256": "73b3ff60b4dd83d895b823bd7df62d6283c4515361e71976e27e22344eb6349e",
    },
}

# A translated Base is never admitted by weakening the normal promotable=True
# contract.  It must present one explicitly reviewed, byte-exact admission
# receipt whose bindings are re-opened below.  Future translated candidates
# require their own entry rather than inheriting a wildcard.
V3_TRANSLATION_ADMISSION_CONTRACTS = {
    "50d09c1742eb53964823089ed1615b50726e5c95172e48bbc5ef0dc885b68dc7": {
        "release_id": "reddit_voc_release_20260810_g5_local_candidate_v2",
        "base_version": "reddit_voc_site_snapshot_20260810_g4t_merged_v1",
        "base_manifest_sha256": "dc2fab3c3478d6769fe5fed4f63deea7f403507c2d5fb6006a28dd75d16bb07a",
        "current_release_sha256": "0fff0406ac280c041189dd9a335aa1c55ef8ea111809c87977fe21cca8f15046",
        "post_sidecar_sha256": "fb4b1bc532bd4538affcc33d25cfc96c5a27e0ecd7740f2120408a7c263921ff",
        "comment_sidecar_sha256": "ab6bc9be9a075f07dea9451e8f7da9c471596e501f2b28666dc5689a3127c9c4",
        "translation_reuse_sha256": "7fc4c404db90b8f45a9b7e5cfe9f353db64ba9b14536dbcda4db0cf0f513925c",
    }
}

# The stock case catalog is immutable.  New content is admitted only through
# approvedDelta and is independently bound by the index and current-release.
CASE_STOCK_CONTRACTS = {
    "seed": {
        "version": "case_seed_bundled_v1",
        "count": 38,
        "contentSha256": "372fa672767ed2585300cd1d47141b6189d3d6784b98c4bc8a69074db5ba48a7",
    },
    "legacyUnverified": {
        "version": "legacy_unverified_bundled_v1",
        "count": 12,
        "contentSha256": "9d09b10949eb3790b34507d13dcbddcaf5fcd6e9f81e96dddd7e12ef86691de2",
    },
}

FORBIDDEN_KEYS = {
    "biz_action",
    "business_impact",
    "dataset_id",
    "default_priority",
    "dept_owner",
    "dictionary_default_priority",
    "run_id",
    "source_occurrences",
    "strategy_package",
    "suggested_action",
}
FORBIDDEN_AUTHOR_KEYS = {"author", "author_name", "username"}
FORBIDDEN_MARKERS = (
    b"poc_token",
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"/Users/",
    b"DDDD.pem",
    b"VITE_USE_MOCK",
)
UNRESOLVED_CSS_DIRECTIVE = re.compile(
    rb"@(tailwind\s+(?:base|components|utilities)|apply(?:\s|;))",
    re.IGNORECASE,
)
REQUIRED_COMPILED_UTILITIES = {
    "flex": re.compile(rb"\.flex\s*\{[^}]*display\s*:\s*flex(?:[;}])"),
    "grid": re.compile(rb"\.grid\s*\{[^}]*display\s*:\s*grid(?:[;}])"),
    "hidden": re.compile(rb"\.hidden\s*\{[^}]*display\s*:\s*none(?:[;}])"),
}


class AuditError(ValueError):
    """A public release contract failed closed."""


@dataclass(frozen=True)
class AuditContract:
    allowed_data_files: frozenset[PurePosixPath]
    public_json_files: frozenset[PurePosixPath]
    public_ndjson_files: frozenset[PurePosixPath]
    release_id: str


class _StylesheetLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "link":
            return
        values = {key.lower(): value for key, value in attrs}
        rel = values.get("rel") or ""
        if "stylesheet" not in rel.lower().split():
            return
        href = values.get("href")
        if not href:
            raise AuditError("stylesheet link is missing href")
        self.hrefs.append(href)


@dataclass(frozen=True)
class FixedAuxiliaryProjectionContract:
    root: PurePosixPath
    manifest_bytes: int
    manifest_sha256: str
    manifest_schema: str
    data_name: str
    data_bytes: int
    data_sha256: str
    data_schema: str
    requires_source_snapshot: bool = True
    expected_source_snapshot_id: str | None = None


V3_FIXED_AUXILIARY_PROJECTIONS = (
    FixedAuxiliaryProjectionContract(
        root=PurePosixPath(
            "data/reddit-voc/reddit_voc_casebook_20260716_public_a1"
        ),
        manifest_bytes=1094,
        manifest_sha256=(
            "8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126"
        ),
        manifest_schema="reddit_voc_governance_casebook_public_manifest_v1",
        data_name="casebook.json",
        data_bytes=2954,
        data_sha256=(
            "5ad81e7af5f9744332baacd0a87ac947f1097894f4ef27c6aab692b0f90b249c"
        ),
        data_schema="reddit_voc_governance_casebook_public_v1",
        requires_source_snapshot=False,
        expected_source_snapshot_id="reddit_add_data_20260715_v1",
    ),
    FixedAuxiliaryProjectionContract(
        root=PurePosixPath(
            "data/reddit-voc/reddit_voc_brand_health_20260719_center_refresh_003"
        ),
        manifest_bytes=997,
        manifest_sha256=(
            "a162120439ba80b2444f15ffbd46f1e7cd3d900ff4801f6947faaf10c243ec86"
        ),
        manifest_schema="reddit_voc_brand_health_public_manifest_v1",
        data_name="brand-health.json",
        data_bytes=1991,
        data_sha256=(
            "aede5f9eaa7b931a90fe9295baa32fed853d3f3619ca1eb5dfd9e0159d122f31"
        ),
        data_schema="reddit_voc_brand_health_public_v1",
        requires_source_snapshot=False,
        expected_source_snapshot_id="reddit_voc_center_20260718_v3_canonical_v2",
    ),
    FixedAuxiliaryProjectionContract(
        root=PurePosixPath(
            "data/reddit-voc/reddit_voc_quarter_insights_20260719_center_refresh_003"
        ),
        manifest_bytes=2575,
        manifest_sha256=(
            "fd27b784e5ad31219bfc8e62a1b5ca1e1284c839227d95fef8cb2eb28c991867"
        ),
        manifest_schema="reddit_voc_quarter_insights_public_manifest_v1",
        data_name="quarter-insights.json",
        data_bytes=40483,
        data_sha256=(
            "9c5c13917e3bcda5bd59ef9ad51a1e0a64f3b5aaeadd1eabebfb34111ab85941"
        ),
        data_schema="reddit_voc_quarter_insights_public_v1",
        requires_source_snapshot=False,
        expected_source_snapshot_id="reddit_voc_center_20260718_v3_canonical_v2",
    ),
    FixedAuxiliaryProjectionContract(
        root=PurePosixPath(
            "data/reddit-voc/reddit_voc_v2-business-activation-e229fbf2901862918997"
        ),
        manifest_bytes=643,
        manifest_sha256=(
            "0d48918c6e7498d8dd930d255bee28f96437154be013c5f639b5d61227d34865"
        ),
        manifest_schema="reddit_voc_v2_business_activation_public_manifest_v1",
        data_name="activation.json",
        data_bytes=5173,
        data_sha256=(
            "4960eed64bd910778849de70798aaa9222edfc1d633e862c7028ca0c5cb254b0"
        ),
        data_schema="reddit_voc_v2_business_activation_public_v1",
        requires_source_snapshot=False,
    ),
)


def walk_json(value: Any, location: str = "$") -> Iterator[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            yield child_location, key, child
            yield from walk_json(child, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(child, f"{location}[{index}]")


def _load_json_value(path: Path, label: str) -> Any:
    if not path.is_file() or path.is_symlink():
        raise AuditError(f"{label} is missing or unsafe: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not valid UTF-8 JSON") from exc
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    value = _load_json_value(path, label)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AuditError(f"{label} must be a JSON object")
    return value


def _file_sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise AuditError(f"manifest-bound file is missing or unsafe: {path.name}")
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise AuditError(f"{label} field contract mismatch")


def _require_identifier(value: Any, prefix: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or SAFE_IDENTIFIER.fullmatch(value) is None
        or not value.startswith(prefix)
    ):
        raise AuditError(f"{label} is not a safe expected identifier")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise AuditError(f"{label} is not a SHA-256 digest")
    return value


def _safe_relative_json(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise AuditError(f"{label} must be a relative JSON path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix != ".json"
    ):
        raise AuditError(f"{label} is not a safe relative JSON path")
    return relative


def _safe_manifest_file(value: Any, label: str, suffixes: set[str]) -> PurePosixPath:
    if not isinstance(value, str):
        raise AuditError(f"{label} must be a relative file path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.suffix.lower() not in suffixes
    ):
        raise AuditError(f"{label} is not an allowed relative file path")
    return relative


def _expected_manifest_path(key: str, version: str) -> PurePosixPath:
    if key == "base":
        return PurePosixPath("data/reddit-voc", version, "manifest-public.json")
    if key in {"insights", "reports"}:
        return PurePosixPath("data/reddit-voc", version, "public", "manifest.json")
    if key == "personas":
        return PurePosixPath("data/reddit-voc", version, "manifest.json")
    raise AssertionError(key)


def _validate_file_contract(
    path: Path,
    contract: Any,
    label: str,
    *,
    allow_rows: bool = False,
) -> None:
    if not isinstance(contract, dict):
        raise AuditError(f"{label} must be a file contract")
    allowed_keys = {"bytes", "sha256", "media_type", "width", "height"}
    if allow_rows:
        allowed_keys.add("rows")
    if not {"bytes", "sha256"}.issubset(contract) or not set(contract).issubset(
        allowed_keys
    ):
        raise AuditError(f"{label} field contract mismatch")
    size = contract.get("bytes")
    expected_sha = _require_sha256(contract.get("sha256"), f"{label}.sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise AuditError(f"{label}.bytes is invalid")
    media_type = contract.get("media_type")
    if media_type is not None and media_type not in {
        "application/json",
        "application/x-ndjson",
        "image/svg+xml",
    }:
        raise AuditError(f"{label}.media_type is invalid")
    rows = contract.get("rows")
    if rows is not None and (
        not allow_rows
        or not isinstance(rows, int)
        or isinstance(rows, bool)
        or rows < 0
    ):
        raise AuditError(f"{label}.rows is invalid")
    for dimension in ("width", "height"):
        value = contract.get(dimension)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
        ):
            raise AuditError(f"{label}.{dimension} is invalid")
    if not path.is_file() or path.is_symlink():
        raise AuditError(f"manifest-bound public file is missing or unsafe: {path.name}")
    stat = path.stat()
    if stat.st_size != size or _file_sha256(path) != expected_sha:
        raise AuditError(f"manifest-bound public file contract mismatch: {path.name}")


def _manifest_files(
    dist: Path,
    manifest: dict[str, Any],
    root_relative: PurePosixPath,
    *,
    label: str,
    suffixes: set[str],
    allow_rows: bool = False,
) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise AuditError(f"{label}.files must be a non-empty object")
    allowed: set[PurePosixPath] = set()
    json_files: set[PurePosixPath] = set()
    for raw_relative, file_contract in files.items():
        relative = _safe_manifest_file(
            raw_relative, f"{label}.files path", suffixes
        )
        full_relative = root_relative / relative
        _validate_file_contract(
            dist.joinpath(*full_relative.parts),
            file_contract,
            f"{label}.files",
            allow_rows=allow_rows,
        )
        allowed.add(full_relative)
        if relative.suffix == ".json":
            json_files.add(full_relative)
    return allowed, json_files


def _validate_projection_manifest(
    manifest: dict[str, Any], version: str, label: str
) -> None:
    if manifest.get("dataset_version") != version:
        raise AuditError(f"{label}.dataset_version does not match current-release")
    projection = manifest.get("projection")
    if not isinstance(projection, dict) or projection.get("audience") != "public_ui":
        raise AuditError(f"{label} is not a public UI projection")


def _validate_v3_static_boundaries(value: Any, label: str) -> None:
    if not isinstance(value, dict) or any(
        value.get(key) is not expected
        for key, expected in V3_STATIC_BOUNDARIES.items()
    ):
        raise AuditError(f"{label} static side-effect boundaries are unsafe")


def _validate_v3_coverage(
    manifest: dict[str, Any],
    *,
    label: str,
    source_snapshot_id: str,
    require_fixture_only_false: bool = True,
) -> None:
    comparison_contract_proven = manifest.get("comparison_contract_proven")
    if type(comparison_contract_proven) is not bool:
        raise AuditError(f"{label} comparison contract state is invalid")
    expected_basis = (
        "owner_attested_dataset_scope_window"
        if comparison_contract_proven
        else "not_owner_attested"
    )
    expected_completeness = 100 if comparison_contract_proven else None
    if (
        manifest.get("completeness_percent") != expected_completeness
        or manifest.get("comparison_contract_basis")
        != expected_basis
        or (
            require_fixture_only_false
            and manifest.get("fixture_only") is not False
        )
    ):
        raise AuditError(f"{label} comparison contract is invalid")
    attestation = manifest.get("coverage_attestation")
    attestation_sha = manifest.get("data_owner_coverage_attestation_sha256")
    if comparison_contract_proven:
        if (
            not isinstance(attestation, dict)
            or attestation.get("attestation_basis")
            != "data_owner_declaration"
            or attestation.get("completeness_percent") != 100
            or attestation.get("evidence_class")
            != "owner_attested_not_crawler_proof"
            or attestation.get("source_snapshot_id") != source_snapshot_id
        ):
            raise AuditError(f"{label} coverage attestation is invalid")
        _require_sha256(
            attestation_sha,
            f"{label} coverage attestation SHA-256",
        )
    elif attestation is not None or attestation_sha is not None:
        raise AuditError(f"{label} unattested coverage binding is invalid")
    elif manifest.get("comparison_unavailable_reason_codes") != [
        "historical_collection_coverage_not_owner_attested_complete"
    ]:
        raise AuditError(f"{label} unattested comparison reason is invalid")


def _validate_v3_manifest(
    manifest: dict[str, Any], *, key: str, version: str, translated_base: bool = False
) -> str:
    label = f"{key} V3 public manifest"
    if manifest.get("schema_version") != V3_MANIFEST_SCHEMAS[key]:
        raise AuditError(f"{label} schema mismatch")
    version_field = "snapshot_id" if key == "personas" else "dataset_version"
    if manifest.get(version_field) != version:
        raise AuditError(f"{label}.{version_field} does not match current-release")
    if translated_base:
        if key != "base":
            raise AuditError("translation admission can apply only to the Base dataset")
        if (
            manifest.get("promotable") is not False
            or manifest.get("status") != "validated_local_translation_candidate"
            or manifest.get("consumption_status")
            != "eligible_for_frontend_candidate_consumption"
        ):
            raise AuditError("translated Base candidate state is invalid")
        expected_boundaries = {**V3_STATIC_BOUNDARIES, "provider_call": True}
        if manifest.get("boundaries") != expected_boundaries:
            raise AuditError("translated Base side-effect provenance is invalid")
        translations = manifest.get("translations")
        coverage = translations.get("coverage") if isinstance(translations, dict) else None
        composition = translations.get("composition") if isinstance(translations, dict) else None
        if (
            not isinstance(translations, dict)
            or translations.get("schema_version") != "reddit_voc_translation_extension_v1"
            or translations.get("quality_gate") != "deterministic_contract_v1"
            or translations.get("semantic_validation") != "not_run"
            or translations.get("independent_human_review") is not False
            or not isinstance(coverage, dict)
            or coverage.get("translated_items") != 29306
            or coverage.get("hash_bound_nonempty_fields") != 28345
            or coverage.get("empty_source_fields") != 961
            or coverage.get("comments_status") != "complete"
            or coverage.get("post_translation_status") != "complete"
            or not isinstance(composition, dict)
            or composition.get("translation_reuse_validation_sha256")
            != V3_TRANSLATION_ADMISSION_CONTRACTS[
                "50d09c1742eb53964823089ed1615b50726e5c95172e48bbc5ef0dc885b68dc7"
            ]["translation_reuse_sha256"]
        ):
            raise AuditError("translated Base extension contract is invalid")
    else:
        if manifest.get("promotable") is not True:
            raise AuditError(f"{label} is not promotable")
        _validate_v3_static_boundaries(manifest.get("boundaries"), label)

    if key == "personas":
        if (
            manifest.get("status") != "candidate_built"
            or manifest.get("consumption_status")
            != "eligible_for_downstream_consumption"
        ):
            raise AuditError("personas V3 public consumption status is invalid")
        upstream = manifest.get("upstream")
        if (
            not isinstance(upstream, dict)
            or upstream.get("consumption_status")
            != "eligible_for_downstream_consumption"
            or upstream.get("promotable") is not True
        ):
            raise AuditError("personas V3 upstream is not consumable")
        source_snapshot_id = manifest.get("governed_signal_source_snapshot_id")
    else:
        if translated_base:
            source_snapshot_id = manifest.get("source_snapshot_id")
        elif (
            manifest.get("status") != "validated_candidate"
            or manifest.get("privacy_safe_projection") is not True
        ):
            raise AuditError(f"{label} validation/privacy status is invalid")
        if not translated_base:
            expected_consumption = (
                "eligible_for_current_release_candidate_binding"
                if key == "base"
                else "eligible_for_frontend_candidate_consumption"
            )
            if manifest.get("consumption_status") != expected_consumption:
                raise AuditError(f"{label} consumption status is invalid")
            source_snapshot_id = manifest.get("source_snapshot_id")
        if key in {"insights", "reports"}:
            if manifest.get("independent_validation_status") != "passed":
                raise AuditError(f"{label} independent validation did not pass")
            _validate_v3_coverage(
                manifest, label=label, source_snapshot_id=str(source_snapshot_id)
            )
            files = manifest.get("files")
            embedded = files.get("validation-receipt.json") if isinstance(files, dict) else None
            if (
                not isinstance(embedded, dict)
                or embedded.get("sha256") != manifest.get("validation_receipt_sha256")
            ):
                raise AuditError(f"{label} embedded receipt binding mismatch")
        elif "comparison_contract_proven" in manifest:
            _validate_v3_coverage(
                manifest,
                label=label,
                source_snapshot_id=str(source_snapshot_id),
                require_fixture_only_false=False,
            )
            expected_base_basis = (
                "data_owner_declaration"
                if manifest["comparison_contract_proven"]
                else "not_owner_attested"
            )
            if manifest.get("completeness_basis") != expected_base_basis:
                raise AuditError("base V3 completeness basis is invalid")
        elif (
            manifest.get("completeness_percent") != 100
            or manifest.get("completeness_basis")
            != "data_owner_declaration"
        ):
            raise AuditError("legacy base V3 completeness contract is invalid")

    if not isinstance(source_snapshot_id, str) or not source_snapshot_id:
        raise AuditError(f"{label} source snapshot is missing")
    return source_snapshot_id


def _require_v3_exact_files(
    manifest: dict[str, Any], key: str, *, translated_base: bool = False
) -> None:
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise AuditError(f"{key} V3 public files contract mismatch")
    paths = set(files)
    if key != "reports" or paths == set(V3_REPORTS_FILES):
        expected = (
            V3_TRANSLATED_BASE_FILES
            if key == "base" and translated_base
            else V3_EXPECTED_FILES[key]
        )
        if paths != set(expected):
            raise AuditError(f"{key} V3 public files contract mismatch")
        return
    history_paths = paths - set(V3_REPORTS_HISTORY_BOOTSTRAP_FILES)
    counts = {"daily": 0, "weekly": 0, "monthly": 0}
    for path in history_paths:
        match = re.fullmatch(r"history/(daily|weekly|monthly)/[0-9_-]+\.json", path)
        if match is None:
            raise AuditError("reports V3 public files contract mismatch")
        counts[match.group(1)] += 1
    comparison_contract_proven = manifest.get("comparison_contract_proven") is True
    history_report_count = manifest.get("history_report_count")
    if history_report_count not in (
        {38} if comparison_contract_proven else {0, 38}
    ):
        raise AuditError("reports V3 history access state is invalid")
    expected_counts = (
        {"daily": 14, "weekly": 12, "monthly": 12}
        if history_report_count
        else {"daily": 0, "weekly": 0, "monthly": 0}
    )
    if (
        not V3_REPORTS_HISTORY_BOOTSTRAP_FILES.issubset(paths)
        or counts != expected_counts
        or len(paths)
        != len(V3_REPORTS_HISTORY_BOOTSTRAP_FILES) + sum(expected_counts.values())
    ):
        raise AuditError("reports V3 public files contract mismatch")


def _validate_v3_embedded_receipt(
    receipt: dict[str, Any], *, key: str, manifest: dict[str, Any]
) -> None:
    expected_schema = f"reddit_voc_{key}_validation_receipt_v3"
    if (
        receipt.get("schema_version") != expected_schema
        or receipt.get("status") != "passed_candidate_only"
        or receipt.get("promotable") is not True
        or receipt.get("deterministic_full_byte_replay") is not True
        or receipt.get("bundle_manifest_sha256")
        != manifest.get("lineage_manifest_sha256")
        or receipt.get("completeness_percent")
        != manifest.get("completeness_percent")
        or receipt.get("comparison_contract_proven")
        is not manifest.get("comparison_contract_proven")
        or receipt.get("comparison_contract_basis")
        != manifest.get("comparison_contract_basis")
    ):
        raise AuditError(f"{key} V3 embedded validation receipt is invalid")
    _validate_v3_static_boundaries(
        receipt.get("boundaries"), f"{key} V3 embedded validation receipt"
    )


def _validate_v3_insights_bundle(
    dist: Path,
    root: PurePosixPath,
    version: str,
    manifest: dict[str, Any],
    source_snapshot_id: str,
) -> None:
    insights = _load_json(dist.joinpath(*(root / "insights.json").parts), "V3 insights")
    if (
        insights.get("schema_version") != "reddit_voc_insights_public_v3"
        or insights.get("dataset_version") != version
        or insights.get("privacy_safe_projection") is not True
    ):
        raise AuditError("V3 insights public data identity is invalid")
    source = insights.get("source")
    if not isinstance(source, dict) or source.get("source_snapshot_id") != source_snapshot_id:
        raise AuditError("V3 insights source snapshot mismatch")
    _validate_v3_coverage(
        insights, label="V3 insights public data", source_snapshot_id=source_snapshot_id
    )
    _validate_v3_static_boundaries(
        insights.get("boundaries"), "V3 insights public data"
    )
    receipt = _load_json(
        dist.joinpath(*(root / "validation-receipt.json").parts),
        "V3 insights embedded validation receipt",
    )
    _validate_v3_embedded_receipt(receipt, key="insights", manifest=manifest)


def _validate_v3_reports_bundle(
    dist: Path,
    root: PurePosixPath,
    version: str,
    manifest: dict[str, Any],
    source_snapshot_id: str,
) -> None:
    manifest_files = manifest.get("files")
    history_enabled = (
        isinstance(manifest_files, dict)
        and "business-history-index.json" in manifest_files
    )
    comparison_contract_proven = manifest.get("comparison_contract_proven") is True
    expected_history_count = manifest.get("history_report_count")
    if expected_history_count not in (
        {38} if comparison_contract_proven else {0, 38}
    ):
        raise AuditError("V3 reports history access state is invalid")
    expected_business_count = 3 + expected_history_count
    index = _load_json(
        dist.joinpath(*(root / "report-index.json").parts), "V3 public report index"
    )
    if (
        index.get("schema_version") != "reddit_voc_report_index_v3"
        or index.get("dataset_version") != version
        or index.get("business_entry_count")
        != (expected_business_count if history_enabled else 3)
        or (
            history_enabled
            and (
                index.get("current_entry_count") != 3
                or index.get("history_entry_count") != expected_history_count
                or index.get("business_history_index_path")
                != "business-history-index.json"
            )
        )
    ):
        raise AuditError("V3 public report index identity is invalid")
    reports = index.get("reports")
    if not isinstance(reports, dict) or set(reports) != {"daily", "weekly", "monthly"}:
        raise AuditError("V3 public report index periods mismatch")
    _validate_v3_coverage(
        index,
        label="V3 public report index",
        source_snapshot_id=source_snapshot_id,
        require_fixture_only_false=False,
    )
    for grain in ("daily", "weekly", "monthly"):
        entry = reports.get(grain)
        current_name = f"current/{grain}.json"
        archive_name = f"archive/{grain}.json"
        if (
            not isinstance(entry, dict)
            or entry.get("grain") != grain
            or entry.get("artifact_path") != current_name
        ):
            raise AuditError(f"V3 public report index {grain} entry mismatch")
        expected_current_role = (
            "latest_complete_calendar_period"
            if comparison_contract_proven
            else "latest_closed_calendar_period_unattested"
        )
        for relative_name, expected_role in (
            (current_name, expected_current_role),
            (archive_name, "internal_comparison_archive"),
        ):
            report = _load_json(
                dist.joinpath(*(root / relative_name).parts), f"V3 {grain} report"
            )
            source = report.get("source")
            if (
                report.get("schema_version") != "reddit_voc_report_v3"
                or report.get("grain") != grain
                or report.get("artifact_role") != expected_role
                or not isinstance(source, dict)
                or source.get("source_snapshot_id") != source_snapshot_id
            ):
                raise AuditError(f"V3 {grain} report identity mismatch")
            if relative_name == current_name and report.get(
                "comparison_archive_path"
            ) != archive_name:
                raise AuditError(f"V3 {grain} report archive linkage mismatch")
            _validate_v3_coverage(
                report,
                label=f"V3 {grain} report",
                source_snapshot_id=source_snapshot_id,
            )
            _validate_v3_static_boundaries(
                report.get("boundaries"), f"V3 {grain} report"
            )
    if history_enabled:
        if (
            manifest.get("report_count") != 6 + expected_history_count
            or manifest.get("history_report_count") != expected_history_count
            or manifest.get("business_entry_count") != expected_business_count
            or "reddit_voc_business_history_index_v1"
            not in manifest.get("contract_extensions", [])
        ):
            raise AuditError("V3 reports history manifest contract is invalid")
        history_index = _load_json(
            dist.joinpath(*(root / "business-history-index.json").parts),
            "V3 business history index",
        )
        if (
            history_index.get("schema_version")
            != "reddit_voc_business_history_index_v1"
            or history_index.get("dataset_version") != version
            or history_index.get("limits")
            != {"daily": 14, "weekly": 12, "monthly": 12}
            or history_index.get("history_entry_count") != expected_history_count
            or history_index.get("total_business_entry_count")
            != expected_business_count
            or history_index.get("order") != "newest_first"
            or history_index.get("latest_complete_period_excluded") is not True
        ):
            raise AuditError("V3 business history index identity is invalid")
        history_source = history_index.get("source")
        if (
            history_index.get("coverage_attestation")
            != index.get("coverage_attestation")
            or history_index.get("data_owner_coverage_attestation_sha256")
            != index.get("data_owner_coverage_attestation_sha256")
            or not isinstance(history_source, dict)
            or history_source.get("source_snapshot_id") != source_snapshot_id
        ):
            raise AuditError("V3 business history lineage is invalid")
        history_reports = history_index.get("reports")
        if not isinstance(history_reports, dict) or set(history_reports) != {
            "daily",
            "weekly",
            "monthly",
        }:
            raise AuditError("V3 business history index periods mismatch")
        bound_paths: set[str] = set()
        bound_period_ids: set[str] = set()
        for grain, expected_count in (
            {"daily": 14, "weekly": 12, "monthly": 12}
            if expected_history_count
            else {"daily": 0, "weekly": 0, "monthly": 0}
        ).items():
            entries = history_reports[grain]
            current_period = reports[grain].get("period")
            if (
                not isinstance(entries, list)
                or len(entries) != expected_count
                or not isinstance(current_period, dict)
                or not isinstance(current_period.get("start"), str)
            ):
                raise AuditError("V3 business history sequence is invalid")
            expected_end = current_period["start"]
            for entry in entries:
                period = entry.get("period") if isinstance(entry, dict) else None
                path = entry.get("artifact_path") if isinstance(entry, dict) else None
                record = manifest_files.get(path) if isinstance(path, str) else None
                try:
                    start_date = date.fromisoformat(period.get("start", ""))
                    end_date = date.fromisoformat(period.get("end", ""))
                except (AttributeError, TypeError, ValueError):
                    start_date = end_date = None
                expected_period_id = (
                    f"{grain}:{start_date.isoformat()}:{end_date.isoformat()}"
                    if start_date is not None and end_date is not None
                    else None
                )
                expected_path = None
                valid_span = False
                if start_date is not None and end_date is not None:
                    if grain == "daily":
                        valid_span = end_date == start_date + timedelta(days=1)
                        expected_path = f"history/daily/{start_date.isoformat()}.json"
                    elif grain == "weekly":
                        valid_span = end_date == start_date + timedelta(days=7)
                        inclusive_end = end_date - timedelta(days=1)
                        expected_path = (
                            f"history/weekly/{start_date.isoformat()}_"
                            f"{inclusive_end.isoformat()}.json"
                        )
                    else:
                        expected_month_end = date(
                            start_date.year + (1 if start_date.month == 12 else 0),
                            1 if start_date.month == 12 else start_date.month + 1,
                            1,
                        )
                        valid_span = start_date.day == 1 and end_date == expected_month_end
                        expected_path = f"history/monthly/{start_date:%Y-%m}.json"
                if (
                    not isinstance(period, dict)
                    or entry.get("grain") != grain
                    or entry.get("entry_label")
                    != (
                        "历史完整周期"
                        if comparison_contract_proven
                        else "历史已观测周期（覆盖未证明）"
                    )
                    or period.get("grain") != grain
                    or period.get("is_complete") is not True
                    or period.get("end") != expected_end
                    or not isinstance(period.get("start"), str)
                    or period.get("start") >= period.get("end", "")
                    or not isinstance(period.get("period_id"), str)
                    or period.get("period_id") != expected_period_id
                    or not valid_span
                    or not isinstance(path, str)
                    or re.fullmatch(rf"history/{grain}/[0-9_-]+\.json", path)
                    is None
                    or path != expected_path
                    or path in bound_paths
                    or period["period_id"] in bound_period_ids
                    or not isinstance(record, dict)
                    or record.get("sha256") != entry.get("artifact_sha256")
                ):
                    raise AuditError("V3 business history sequence is invalid")
                historical = _load_json(
                    dist.joinpath(*(root / path).parts), f"V3 historical {grain} report"
                )
                source = historical.get("source")
                if (
                    historical.get("schema_version") != "reddit_voc_report_v3"
                    or historical.get("artifact_role")
                    != (
                        "historical_complete_calendar_period"
                        if comparison_contract_proven
                        else "historical_observed_calendar_period_unattested"
                    )
                    or historical.get("business_entry_visible") is not True
                    or historical.get("entry_label")
                    != (
                        "历史完整周期"
                        if comparison_contract_proven
                        else "历史已观测周期（覆盖未证明）"
                    )
                    or historical.get("grain") != grain
                    or historical.get("period") != period
                    or "comparison_archive_path" in historical
                    or not isinstance(source, dict)
                    or source.get("source_snapshot_id") != source_snapshot_id
                ):
                    raise AuditError("V3 historical report identity mismatch")
                _validate_v3_coverage(
                    historical,
                    label=f"V3 historical {grain} report",
                    source_snapshot_id=source_snapshot_id,
                )
                _validate_v3_static_boundaries(
                    historical.get("boundaries"), f"V3 historical {grain} report"
                )
                bound_paths.add(path)
                bound_period_ids.add(period["period_id"])
                expected_end = period["start"]
        expected_paths = set(V3_REPORTS_HISTORY_BOOTSTRAP_FILES) | bound_paths
        if set(manifest_files) != expected_paths:
            raise AuditError("reports V3 public files contract mismatch")
    receipt = _load_json(
        dist.joinpath(*(root / "validation-receipt.json").parts),
        "V3 reports embedded validation receipt",
    )
    _validate_v3_embedded_receipt(receipt, key="reports", manifest=manifest)
    if history_enabled and (
        receipt.get("report_count") != 6 + expected_history_count
        or receipt.get("history_report_count") != expected_history_count
        or receipt.get("business_entry_count") != expected_business_count
    ):
        raise AuditError("reports V3 history receipt counts are invalid")


def _validate_v3_persona_bundle(
    dist: Path, root: PurePosixPath, version: str
) -> None:
    identities = {
        "personas.json": "reddit_voc_personas_v3",
        "persona-tags.json": "reddit_voc_persona_cohort_assignments_v1",
        "persona-atomic-catalog.json": "reddit_voc_persona_atomic_catalog_v1",
        "persona-cohort-bridge.json": "reddit_voc_persona_cohort_bridge_v1",
    }
    for name, schema in identities.items():
        value = _load_json(dist.joinpath(*(root / name).parts), f"V3 persona {name}")
        if value.get("schema_version") != schema or value.get("snapshot_id") != version:
            raise AuditError(f"V3 persona artifact identity mismatch: {name}")
    personas = _load_json(
        dist.joinpath(*(root / "personas.json").parts), "V3 personas"
    )
    if personas.get("persona_cohort_count") != 8:
        raise AuditError("V3 persona cohort count must be eight")


def _v3_insights_sidecar(
    dist: Path,
    insights_root: PurePosixPath,
    *,
    manifest_sha256: str,
) -> PurePosixPath | None:
    contract = V3_INSIGHTS_SIDECAR_CONTRACTS.get(manifest_sha256)
    if contract is None:
        return None
    relative = insights_root / V3_INSIGHTS_SIDECAR_NAME
    path = dist.joinpath(*relative.parts)
    if not path.is_file() or path.is_symlink():
        raise AuditError("reviewed V3 insights public validation sidecar is missing")
    if (
        path.stat().st_size != contract["bytes"]
        or _file_sha256(path) != contract["sha256"]
    ):
        raise AuditError("reviewed V3 insights public validation sidecar mismatch")
    return relative


def _v3_reports_sidecar(
    dist: Path,
    reports_root: PurePosixPath,
    *,
    manifest_sha256: str,
) -> PurePosixPath | None:
    contract = V3_REPORTS_SIDECAR_CONTRACTS.get(manifest_sha256)
    if contract is None:
        return None
    relative = reports_root / V3_INSIGHTS_SIDECAR_NAME
    path = dist.joinpath(*relative.parts)
    if not path.is_file() or path.is_symlink():
        raise AuditError("reviewed V3 reports public validation sidecar is missing")
    if (
        path.stat().st_size != contract["bytes"]
        or _file_sha256(path) != contract["sha256"]
    ):
        raise AuditError("reviewed V3 reports public validation sidecar mismatch")
    return relative


def _validate_v3_fixed_auxiliary_projections(
    dist: Path, *, source_snapshot_id: str
) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    allowed: set[PurePosixPath] = set()
    public_json: set[PurePosixPath] = set()
    for contract in V3_FIXED_AUXILIARY_PROJECTIONS:
        manifest_relative = contract.root / "manifest.json"
        data_relative = contract.root / contract.data_name
        manifest_path = dist.joinpath(*manifest_relative.parts)
        data_path = dist.joinpath(*data_relative.parts)
        for path, expected_bytes, expected_sha, label in (
            (
                manifest_path,
                contract.manifest_bytes,
                contract.manifest_sha256,
                "manifest",
            ),
            (data_path, contract.data_bytes, contract.data_sha256, "data"),
        ):
            if not path.is_file() or path.is_symlink():
                raise AuditError(
                    f"fixed V3 auxiliary projection {label} is missing or unsafe: "
                    f"{contract.root.name}"
                )
            if path.stat().st_size != expected_bytes or _file_sha256(path) != expected_sha:
                raise AuditError(
                    f"fixed V3 auxiliary projection {label} contract mismatch: "
                    f"{contract.root.name}"
                )

        manifest = _load_json(manifest_path, "fixed V3 auxiliary manifest")
        data = _load_json(data_path, "fixed V3 auxiliary data")
        files = manifest.get("files")
        manifest_identities = {
            value
            for value in (
                manifest.get("projection_id"),
                manifest.get("dataset_version"),
            )
            if value is not None
        }
        manifest_source = manifest.get("source_snapshot_id")
        if manifest_source is None:
            source = manifest.get("source")
            manifest_source = (
                source.get("source_snapshot_id") if isinstance(source, dict) else None
            )
        if (
            manifest.get("schema_version") != contract.manifest_schema
            or manifest.get("status") != "ready"
            or (
                contract.requires_source_snapshot
                and manifest_source != source_snapshot_id
            )
            or (
                contract.expected_source_snapshot_id is not None
                and manifest_source != contract.expected_source_snapshot_id
            )
            or manifest_identities != {contract.root.name}
            or not isinstance(files, dict)
            or set(files) != {contract.data_name}
        ):
            raise AuditError(
                f"fixed V3 auxiliary manifest identity mismatch: {contract.root.name}"
            )
        _validate_file_contract(
            data_path,
            files[contract.data_name],
            f"fixed V3 auxiliary {contract.root.name}",
        )
        data_source = data.get("source_snapshot_id")
        if data_source is None:
            source = data.get("source")
            data_source = source.get("snapshot_id") if isinstance(source, dict) else None
            if data_source is None and isinstance(source, dict):
                data_source = source.get("source_snapshot_id")
        data_identities = {
            value
            for value in (data.get("projection_id"), data.get("dataset_version"))
            if value is not None
        }
        if (
            data.get("schema_version") != contract.data_schema
            or data_identities != {contract.root.name}
            or (
                contract.requires_source_snapshot and data_source != source_snapshot_id
            )
            or (
                contract.expected_source_snapshot_id is not None
                and data_source != contract.expected_source_snapshot_id
            )
            or data.get("boundaries") != manifest.get("boundaries")
        ):
            raise AuditError(
                f"fixed V3 auxiliary data identity mismatch: {contract.root.name}"
            )
        _validate_v3_static_boundaries(
            manifest.get("boundaries"),
            f"fixed V3 auxiliary {contract.root.name}",
        )
        boundaries = manifest.get("boundaries")
        if contract.data_name == "casebook.json":
            if (
                not isinstance(boundaries, dict)
                or boundaries.get("pii_removed") is not True
                or boundaries.get("external_navigation") is not False
                or boundaries.get("action_display_mode") != "suggestion_only"
                or boundaries.get("brand_control_confirmed") is not False
                or boundaries.get("robot_attribution_confirmed") is not False
            ):
                raise AuditError("fixed V3 casebook safety boundaries are invalid")
        elif contract.data_name == "brand-health.json":
            if (
                not isinstance(boundaries, dict)
                or boundaries.get("pii_removed") is not True
                or boundaries.get("contains_authors") is not False
                or boundaries.get("contains_entity_ids") is not False
                or boundaries.get("contains_source_text") is not False
                or boundaries.get("overall_score_derived_from_axes") is not False
            ):
                raise AuditError("fixed V3 brand-health safety boundaries are invalid")
        elif contract.data_name == "activation.json":
            counts = data.get("business_counts")
            bindings = data.get("artifact_bindings")
            checks = data.get("checks")
            if (
                boundaries != V3_STATIC_BOUNDARIES
                or data.get("status") != "validated_local_business_data"
                or not isinstance(counts, dict)
                or counts.get("posts") != 3494
                or counts.get("stored_comments") != 27158
                or counts.get("linked_comments") != 20205
                or counts.get("unresolved_parent_comments") != 6943
                or counts.get("quarantined_comments") != 10
                or not isinstance(bindings, dict)
                or len(bindings) != 26
                or any(
                    not isinstance(binding, dict)
                    or set(binding) != {"schema_version", "sha256"}
                    or SHA256.fullmatch(str(binding.get("sha256", ""))) is None
                    for binding in bindings.values()
                )
                or not isinstance(checks, dict)
                or not checks
                or any(value is not True for value in checks.values())
            ):
                raise AuditError("fixed V3 business-activation contract is invalid")
        elif (
            not isinstance(boundaries, dict)
            or boundaries.get("author_fields_excluded") is not True
            or boundaries.get("private_paths_excluded") is not True
            or boundaries.get("source_text_excluded") is not True
            or boundaries.get("automation_comments_are_not_brand_attribution") is not True
            or boundaries.get("brand_bot_attribution_confirmed") is not False
            or boundaries.get("counts_are_content_entities_not_users") is not True
            or boundaries.get("case_references_are_method_only") is not True
            or boundaries.get("market_share_supported") is not False
            or boundaries.get("population_share_supported") is not False
        ):
            raise AuditError("fixed V3 quarter-insights safety boundaries are invalid")
        allowed.update({manifest_relative, data_relative})
        public_json.update({manifest_relative, data_relative})
    return allowed, public_json


def _validate_v3_pointer_auxiliary_projections(
    dist: Path,
    *,
    datasets: dict[str, Any],
    source_snapshot_id: str,
) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    """Validate the daily V2 auxiliary projections selected by the pointer."""

    contracts = {
        "brand_health": (
            "reddit_voc_brand_health_",
            "reddit_voc_brand_health_public_manifest_v1",
            "brand-health.json",
            "reddit_voc_brand_health_public_v1",
        ),
        "quarter_insights": (
            "reddit_voc_quarter_insights_",
            "reddit_voc_quarter_insights_public_manifest_v1",
            "quarter-insights.json",
            "reddit_voc_quarter_insights_public_v1",
        ),
        "casebook": (
            "reddit_voc_casebook_",
            "reddit_voc_governance_casebook_public_manifest_v1",
            "casebook.json",
            "reddit_voc_governance_casebook_public_v1",
        ),
    }
    allowed: set[PurePosixPath] = set()
    public_json: set[PurePosixPath] = set()
    for name in V2_AUXILIARY_DATASET_KEYS:
        binding = datasets.get(name)
        if not isinstance(binding, dict):
            raise AuditError(f"current-release {name} binding is invalid")
        _require_exact_keys(
            binding,
            {
                "dataset_version",
                "manifest_path",
                "public_manifest_sha256",
                "lineage_manifest_sha256",
            },
            f"current-release datasets.{name}",
        )
        prefix, manifest_schema, data_name, data_schema = contracts[name]
        version = _require_identifier(
            binding.get("dataset_version"), prefix, f"{name} dataset version"
        )
        manifest_relative = PurePosixPath(
            "data/reddit-voc", version, "manifest.json"
        )
        if (
            binding.get("manifest_path") != manifest_relative.as_posix()
            or binding.get("lineage_manifest_sha256")
            != binding.get("public_manifest_sha256")
        ):
            raise AuditError(f"current-release {name} manifest binding mismatch")
        manifest_path = dist.joinpath(*manifest_relative.parts)
        public_sha = _require_sha256(
            binding.get("public_manifest_sha256"),
            f"{name} public manifest SHA-256",
        )
        if _file_sha256(manifest_path) != public_sha:
            raise AuditError(f"current-release {name} manifest SHA-256 mismatch")
        if (
            name == "casebook"
            and public_sha
            != "8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126"
        ):
            raise AuditError("casebook stock manifest is not the reviewed projection")

        manifest = _load_json(manifest_path, f"{name} public manifest")
        identity = manifest.get("dataset_version") or manifest.get("projection_id")
        files = manifest.get("files")
        if (
            manifest.get("schema_version") != manifest_schema
            or manifest.get("status") != "ready"
            or identity != version
            or not isinstance(files, dict)
            or set(files) != {data_name}
        ):
            raise AuditError(f"{name} public manifest contract mismatch")
        data_relative = manifest_relative.parent / data_name
        data_path = dist.joinpath(*data_relative.parts)
        _validate_file_contract(
            data_path, files[data_name], f"{name} public data"
        )
        data = _load_json(data_path, f"{name} public data")
        data_identity = data.get("dataset_version") or data.get("projection_id")
        if (
            data.get("schema_version") != data_schema
            or data_identity != version
            or data.get("boundaries") != manifest.get("boundaries")
        ):
            raise AuditError(f"{name} public data contract mismatch")

        manifest_source = manifest.get("source_snapshot_id")
        if manifest_source is None and isinstance(manifest.get("source"), dict):
            manifest_source = manifest["source"].get("source_snapshot_id")
        data_source = data.get("source_snapshot_id")
        if data_source is None and isinstance(data.get("source"), dict):
            data_source = (
                data["source"].get("snapshot_id")
                or data["source"].get("source_snapshot_id")
            )
        if name != "casebook" and (
            manifest_source != source_snapshot_id
            or data_source != source_snapshot_id
        ):
            raise AuditError(f"{name} source snapshot mismatch")

        boundaries = manifest.get("boundaries")
        _validate_v3_static_boundaries(boundaries, f"{name} public projection")
        if name == "casebook":
            if (
                not isinstance(boundaries, dict)
                or boundaries.get("pii_removed") is not True
                or boundaries.get("external_navigation") is not False
                or boundaries.get("action_display_mode") != "suggestion_only"
                or boundaries.get("brand_control_confirmed") is not False
                or boundaries.get("robot_attribution_confirmed") is not False
            ):
                raise AuditError("casebook safety boundaries are invalid")
        elif name == "brand_health":
            if (
                not isinstance(boundaries, dict)
                or boundaries.get("pii_removed") is not True
                or boundaries.get("contains_authors") is not False
                or boundaries.get("contains_entity_ids") is not False
                or boundaries.get("contains_source_text") is not False
                or boundaries.get("overall_score_derived_from_axes") is not False
            ):
                raise AuditError("brand-health safety boundaries are invalid")
        elif (
            not isinstance(boundaries, dict)
            or boundaries.get("author_fields_excluded") is not True
            or boundaries.get("private_paths_excluded") is not True
            or boundaries.get("source_text_excluded") is not True
            or boundaries.get("automation_comments_are_not_brand_attribution")
            is not True
            or boundaries.get("brand_bot_attribution_confirmed") is not False
            or boundaries.get("counts_are_content_entities_not_users") is not True
            or boundaries.get("case_references_are_method_only") is not True
            or boundaries.get("market_share_supported") is not False
            or boundaries.get("population_share_supported") is not False
        ):
            raise AuditError("quarter-insights safety boundaries are invalid")
        allowed.update({manifest_relative, data_relative})
        public_json.update({manifest_relative, data_relative})
    return allowed, public_json


def _validate_reports_index(
    dist: Path,
    reports_root: PurePosixPath,
    manifest_files: set[PurePosixPath],
    reports_version: str,
) -> set[PurePosixPath]:
    index_relative = reports_root / "report-index.json"
    if index_relative not in manifest_files:
        raise AuditError("reports manifest does not bind report-index.json")
    index = _load_json(
        dist.joinpath(*index_relative.parts), "public report index"
    )
    if index.get("dataset_version") != reports_version:
        raise AuditError("public report index dataset_version mismatch")
    referenced = {index_relative}
    for collection in ("current", "archive"):
        group = index.get(collection)
        if not isinstance(group, dict):
            raise AuditError(f"public report index.{collection} must be an object")
        missing = {"daily", "weekly", "monthly"} - set(group)
        if missing:
            raise AuditError(
                f"public report index.{collection} is missing required periods"
            )
        for period, entry in group.items():
            if not isinstance(period, str) or not isinstance(entry, dict):
                raise AuditError(f"public report index.{collection} is invalid")
            path = _safe_relative_json(
                entry.get("path"), f"public report index.{collection}.{period}.path"
            )
            full = reports_root / path
            if full not in manifest_files:
                raise AuditError("public report index references an unbound report")
            report = _load_json(dist.joinpath(*full.parts), "public report")
            identity = report.get("identity")
            if (
                not isinstance(identity, dict)
                or identity.get("dataset_version") != reports_version
            ):
                raise AuditError("public report identity dataset_version mismatch")
            referenced.add(full)
    return referenced


def _validate_persona_boundaries(manifest: dict[str, Any]) -> None:
    boundaries = manifest.get("boundaries")
    required = {
        "author_level_personas": False,
        "counts_are_content_entities_not_users": True,
        "derived_from_reddit_media": False,
        "identity_claim": False,
        "public_author_identifiers": False,
        "real_user_image": False,
        "synthetic_avatars": True,
    }
    if not isinstance(boundaries, dict) or any(
        boundaries.get(key) is not value for key, value in required.items()
    ):
        raise AuditError("persona public-safety boundaries are incomplete")


def _validate_v3_persona_boundaries(manifest: dict[str, Any]) -> None:
    boundaries = manifest.get("boundaries")
    required = {
        "author_level_personas": False,
        "counts_are_content_entities_not_users": True,
        "demographics_supported": False,
        "population_share_supported": False,
        "real_user_images": False,
    }
    if not isinstance(boundaries, dict) or any(
        boundaries.get(key) is not value for key, value in required.items()
    ):
        raise AuditError("persona V3 public-safety boundaries are incomplete")


def _validate_linkage(
    manifest: dict[str, Any],
    *,
    label: str,
    base_version: str,
    base_lineage_sha: str,
    insights_version: str | None = None,
    insights_lineage_sha: str | None = None,
) -> None:
    if manifest.get("base_dataset_version") != base_version:
        raise AuditError(f"{label} base dataset linkage mismatch")
    if manifest.get("base_manifest_sha256") != base_lineage_sha:
        raise AuditError(f"{label} base manifest lineage mismatch")
    if insights_version is not None:
        if manifest.get("insights_dataset_version") != insights_version:
            raise AuditError(f"{label} insights dataset linkage mismatch")
        if manifest.get("insights_manifest_sha256") != insights_lineage_sha:
            raise AuditError(f"{label} insights manifest lineage mismatch")


def _validate_cases(
    dist: Path,
    cases_binding: dict[str, Any],
) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    _require_exact_keys(
        cases_binding,
        {
            "dataset_version",
            "manifest_path",
            "public_manifest_sha256",
            "index_path",
            "index_sha256",
            "stock_content_preserved",
            "approved_delta_count",
        },
        "current-release.cases",
    )
    version = _require_identifier(
        cases_binding.get("dataset_version"), "case_catalog_", "cases dataset_version"
    )
    if cases_binding.get("manifest_path") != str(CASE_MANIFEST_PATH):
        raise AuditError("current-release cases manifest path mismatch")
    if cases_binding.get("index_path") != str(CASE_INDEX_PATH):
        raise AuditError("current-release cases index path mismatch")
    if cases_binding.get("stock_content_preserved") is not True:
        raise AuditError("current-release does not preserve case stock content")
    delta_count = cases_binding.get("approved_delta_count")
    if not isinstance(delta_count, int) or isinstance(delta_count, bool) or delta_count < 0:
        raise AuditError("current-release approved case delta count is invalid")

    manifest_path = dist.joinpath(*CASE_MANIFEST_PATH.parts)
    index_path = dist.joinpath(*CASE_INDEX_PATH.parts)
    expected_manifest_sha = _require_sha256(
        cases_binding.get("public_manifest_sha256"), "cases public manifest SHA-256"
    )
    expected_index_sha = _require_sha256(
        cases_binding.get("index_sha256"), "cases index SHA-256"
    )
    if _file_sha256(manifest_path) != expected_manifest_sha:
        raise AuditError("cases public manifest SHA-256 mismatch")
    if _file_sha256(index_path) != expected_index_sha:
        raise AuditError("cases index SHA-256 mismatch")

    manifest = _load_json(manifest_path, "cases public manifest")
    index = _load_json(index_path, "cases public index")
    if manifest.get("datasetVersion") != version or index.get("datasetVersion") != version:
        raise AuditError("cases dataset version mismatch")
    for key, expected in CASE_STOCK_CONTRACTS.items():
        actual = manifest.get(key)
        if not isinstance(actual, dict) or any(
            actual.get(field) != expected_value
            for field, expected_value in expected.items()
        ):
            raise AuditError(f"case stock contract changed: {key}")
    provenance = manifest.get("provenance")
    if (
        not isinstance(provenance, dict)
        or provenance.get("networkSearch") is not False
        or provenance.get("process") != "manual_seed_plus_approved_static_delta"
    ):
        raise AuditError("case provenance is not the approved static-delta process")
    approved = manifest.get("approvedDelta")
    rows = index.get("approvedDelta")
    if not isinstance(approved, dict) or not isinstance(rows, list):
        raise AuditError("approved case delta contract is invalid")
    compact_rows = json.dumps(
        rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if (
        approved.get("count") != delta_count
        or len(rows) != delta_count
        or approved.get("contentSha256") != sha256(compact_rows).hexdigest()
    ):
        raise AuditError("approved case delta count or content hash mismatch")
    index_contract = manifest.get("index")
    if (
        not isinstance(index_contract, dict)
        or index_contract.get("path") != f"/{CASE_INDEX_PATH}"
        or index_contract.get("sha256") != expected_index_sha
    ):
        raise AuditError("cases manifest-to-index linkage mismatch")
    return (
        {CASE_MANIFEST_PATH, CASE_INDEX_PATH},
        {CASE_MANIFEST_PATH, CASE_INDEX_PATH},
    )


def discover_contract(
    dist: Path,
    *,
    base_version: str,
    insights_version: str,
    reports_version: str,
    personas_version: str,
    current_release_path: str,
    translation_admission_receipt: Path | None = None,
) -> AuditContract:
    expected_versions = {
        "base": _require_identifier(base_version, VERSION_PREFIXES["base"], "base version"),
        "insights": _require_identifier(
            insights_version, VERSION_PREFIXES["insights"], "insights version"
        ),
        "reports": _require_identifier(
            reports_version, VERSION_PREFIXES["reports"], "reports version"
        ),
        "personas": _require_identifier(
            personas_version, VERSION_PREFIXES["personas"], "personas version"
        ),
    }
    current_relative = _safe_relative_json(
        current_release_path, "current-release path"
    )
    if current_relative != CURRENT_RELEASE_PATH:
        raise AuditError("current-release must use the reviewed runtime path")
    current = _load_json(
        dist.joinpath(*current_relative.parts), "current-release pointer"
    )
    current_schema = current.get("schema_version")
    current_v2 = current_schema == "reddit_voc_current_release_v2"
    _require_exact_keys(
        current,
        {
            "schema_version",
            "release_id",
            "generated_at_utc",
            "datasets",
            "cases",
            "boundaries",
            *(("freshness",) if current_v2 else ()),
        },
        "current-release",
    )
    if current_schema not in {
        "reddit_voc_current_release_v1",
        "reddit_voc_current_release_v2",
    }:
        raise AuditError("unsupported current-release schema")
    release_id = _require_identifier(
        current.get("release_id"), "reddit_voc_release_", "current-release release_id"
    )
    generated_at = current.get("generated_at_utc")
    if not isinstance(generated_at, str) or UTC_TIMESTAMP.fullmatch(generated_at) is None:
        raise AuditError("current-release generated_at_utc is invalid")
    datasets = current.get("datasets")
    expected_dataset_keys = set(DATASET_KEYS)
    if current_v2:
        expected_dataset_keys.update(V2_AUXILIARY_DATASET_KEYS)
    if not isinstance(datasets, dict) or set(datasets) != expected_dataset_keys:
        raise AuditError("current-release datasets field contract mismatch")
    if current_v2:
        freshness = current.get("freshness")
        if (
            not isinstance(freshness, dict)
            or freshness.get("status") not in {"complete", "partial"}
            or freshness.get("timezone") != "Asia/Shanghai"
            or not isinstance(freshness.get("center_snapshot_id"), str)
            or not freshness.get("center_snapshot_id")
        ):
            raise AuditError("current-release freshness contract mismatch")
    boundaries = current.get("boundaries")
    if not isinstance(boundaries, dict):
        raise AuditError("current-release boundaries must be an object")
    _require_exact_keys(
        boundaries,
        {
            "case_gallery_stock_preserved",
            "collector_isolation_required",
            "login_required",
        },
        "current-release boundaries",
    )
    if (
        boundaries.get("case_gallery_stock_preserved") is not True
        or boundaries.get("collector_isolation_required") is not True
        or boundaries.get("login_required") is not False
    ):
        raise AuditError("current-release access/isolation boundaries are unsafe")

    bindings: dict[str, dict[str, Any]] = {}
    manifests: dict[str, dict[str, Any]] = {}
    manifest_shas: dict[str, str] = {}
    allowed: set[PurePosixPath] = {current_relative}
    public_json: set[PurePosixPath] = {current_relative}
    public_ndjson: set[PurePosixPath] = set()
    for key in DATASET_KEYS:
        binding = datasets.get(key)
        if not isinstance(binding, dict):
            raise AuditError(f"current-release dataset binding is invalid: {key}")
        _require_exact_keys(
            binding,
            {
                "dataset_version",
                "manifest_path",
                "public_manifest_sha256",
                "lineage_manifest_sha256",
            },
            f"current-release datasets.{key}",
        )
        version = _require_identifier(
            binding.get("dataset_version"), VERSION_PREFIXES[key], f"{key} dataset version"
        )
        if version != expected_versions[key]:
            raise AuditError(f"explicit {key} version does not match current-release")
        manifest_relative = _expected_manifest_path(key, version)
        if binding.get("manifest_path") != str(manifest_relative):
            raise AuditError(f"current-release {key} manifest path mismatch")
        public_sha = _require_sha256(
            binding.get("public_manifest_sha256"), f"{key} public manifest SHA-256"
        )
        _require_sha256(
            binding.get("lineage_manifest_sha256"), f"{key} lineage manifest SHA-256"
        )
        manifest_path = dist.joinpath(*manifest_relative.parts)
        actual_manifest_sha = _file_sha256(manifest_path)
        if actual_manifest_sha != public_sha:
            raise AuditError(f"current-release {key} public manifest SHA-256 mismatch")
        manifest = _load_json(manifest_path, f"{key} public manifest")
        bindings[key] = binding
        manifests[key] = manifest
        manifest_shas[key] = actual_manifest_sha
        allowed.add(manifest_relative)
        public_json.add(manifest_relative)

    translated_base_admitted = False
    if translation_admission_receipt is not None:
        admission_path = translation_admission_receipt.resolve()
        if admission_path.is_symlink() or not admission_path.is_file():
            raise AuditError("translation admission receipt is missing or unsafe")
        admission_sha = _file_sha256(admission_path)
        admission_contract = V3_TRANSLATION_ADMISSION_CONTRACTS.get(admission_sha)
        if admission_contract is None:
            raise AuditError("translation admission receipt is not reviewed")
        admission = _load_json(admission_path, "translation admission receipt")
        translations = admission.get("translations")
        admission_inputs = admission.get("admission_inputs")
        translation_reuse = (
            admission_inputs.get("translation_reuse")
            if isinstance(admission_inputs, dict)
            else None
        )
        current_sha = _file_sha256(dist.joinpath(*current_relative.parts))
        if (
            admission.get("schema_version")
            != "reddit_voc_p2e_g5_local_public_candidate_admission_v1"
            or admission.get("status") != "admitted_local_public_candidate"
            or admission.get("admitted") is not True
            or admission.get("release_id") != admission_contract["release_id"]
            or release_id != admission_contract["release_id"]
            or expected_versions["base"] != admission_contract["base_version"]
            or manifest_shas["base"] != admission_contract["base_manifest_sha256"]
            or current_sha != admission_contract["current_release_sha256"]
            or not isinstance(translations, dict)
            or translations.get("complete") is not True
            or translations.get("missing_translation_fields") != 0
            or translations.get("invalid_existing_fields") != 0
            or translations.get("post_sidecar_sha256")
            != admission_contract["post_sidecar_sha256"]
            or translations.get("comment_sidecar_sha256")
            != admission_contract["comment_sidecar_sha256"]
            or not isinstance(translation_reuse, dict)
            or translation_reuse.get("sha256")
            != admission_contract["translation_reuse_sha256"]
        ):
            raise AuditError("translation admission receipt binding is invalid")
        translated_base_admitted = True

    exact_v3 = {
        key: manifests[key].get("schema_version") == V3_MANIFEST_SCHEMAS[key]
        for key in DATASET_KEYS
    }
    if any(exact_v3.values()) and not all(exact_v3.values()):
        raise AuditError("V3 coordinated release requires all four V3 datasets")
    is_v3 = all(exact_v3.values())
    if not is_v3 and any(
        isinstance(manifests[key].get("schema_version"), str)
        and str(manifests[key].get("schema_version")).endswith("_v3")
        for key in DATASET_KEYS
    ):
        raise AuditError("unsupported or mixed V3 public manifest schema")

    source_snapshot_ids: dict[str, str] = {}
    if is_v3:
        for key in DATASET_KEYS:
            translated_base = key == "base" and translated_base_admitted
            _require_v3_exact_files(
                manifests[key], key, translated_base=translated_base
            )
            source_snapshot_ids[key] = _validate_v3_manifest(
                manifests[key],
                key=key,
                version=expected_versions[key],
                translated_base=translated_base,
            )
        if len(set(source_snapshot_ids.values())) != 1:
            raise AuditError("V3 coordinated release source snapshot mismatch")
        insights_comparison_state = (
            manifests["insights"].get("comparison_contract_proven"),
            manifests["insights"].get("comparison_contract_basis"),
            manifests["insights"].get("completeness_percent"),
            manifests["insights"].get("data_owner_coverage_attestation_sha256"),
        )
        reports_comparison_state = (
            manifests["reports"].get("comparison_contract_proven"),
            manifests["reports"].get("comparison_contract_basis"),
            manifests["reports"].get("completeness_percent"),
            manifests["reports"].get("data_owner_coverage_attestation_sha256"),
        )
        if insights_comparison_state != reports_comparison_state:
            raise AuditError("V3 coordinated comparison contract mismatch")
        if "comparison_contract_proven" in manifests["base"]:
            base_comparison_state = (
                manifests["base"].get("comparison_contract_proven"),
                manifests["base"].get("comparison_contract_basis"),
                manifests["base"].get("completeness_percent"),
                manifests["base"].get(
                    "data_owner_coverage_attestation_sha256"
                ),
            )
            if base_comparison_state != insights_comparison_state:
                raise AuditError("V3 coordinated base comparison contract mismatch")
        elif insights_comparison_state[:3] != (
            True,
            "owner_attested_dataset_scope_window",
            100,
        ):
            raise AuditError(
                "legacy V3 base cannot bind an unattested coordinated release"
            )
        for key in ("base", "insights", "reports"):
            if (
                bindings[key].get("lineage_manifest_sha256")
                != manifests[key].get("lineage_manifest_sha256")
            ):
                raise AuditError(f"V3 {key} pointer lineage mismatch")
        if (
            bindings["personas"].get("lineage_manifest_sha256")
            != manifest_shas["personas"]
        ):
            raise AuditError("V3 personas pointer lineage mismatch")
    else:
        for key in DATASET_KEYS:
            if key != "personas":
                _validate_projection_manifest(
                    manifests[key], expected_versions[key], f"{key} public manifest"
                )
            elif manifests[key].get("dataset_version") != expected_versions[key]:
                raise AuditError("personas public manifest dataset_version mismatch")

    base_root = PurePosixPath("data/reddit-voc", expected_versions["base"])
    base_files, base_json = _manifest_files(
        dist,
        manifests["base"],
        base_root,
        label="base public manifest",
        suffixes={".json"},
    )
    required_base = {base_root / name for name in V3_BASE_FILES}
    if not required_base.issubset(base_files):
        raise AuditError("base public projection is missing a required browser artifact")
    privacy = manifests["base"].get("privacy")
    if not isinstance(privacy, dict) or privacy.get("author_display") != "suppressed":
        raise AuditError("base public manifest does not suppress author display")
    if is_v3 and privacy.get("stable_pseudonym_exposed") is not False:
        raise AuditError("base V3 public manifest exposes stable pseudonyms")

    insights_root = PurePosixPath(
        "data/reddit-voc", expected_versions["insights"], "public"
    )
    insights_files, insights_json = _manifest_files(
        dist,
        manifests["insights"],
        insights_root,
        label="insights public manifest",
        suffixes={".json"},
    )
    if is_v3:
        _validate_v3_insights_bundle(
            dist,
            insights_root,
            expected_versions["insights"],
            manifests["insights"],
            source_snapshot_ids["insights"],
        )
        sidecar = _v3_insights_sidecar(
            dist,
            insights_root,
            manifest_sha256=manifest_shas["insights"],
        )
        if sidecar is not None:
            insights_files.add(sidecar)
            insights_json.add(sidecar)
    elif not {
        insights_root / "insights.json",
        insights_root / "semantic-audit.json",
    }.issubset(insights_files):
        raise AuditError("insights public projection is incomplete")

    reports_root = PurePosixPath(
        "data/reddit-voc", expected_versions["reports"], "public"
    )
    reports_files, reports_json = _manifest_files(
        dist,
        manifests["reports"],
        reports_root,
        label="reports public manifest",
        suffixes={".json"},
    )
    if is_v3:
        _validate_v3_reports_bundle(
            dist,
            reports_root,
            expected_versions["reports"],
            manifests["reports"],
            source_snapshot_ids["reports"],
        )
        reports_sidecar = _v3_reports_sidecar(
            dist,
            reports_root,
            manifest_sha256=manifest_shas["reports"],
        )
        if reports_sidecar is not None:
            reports_files.add(reports_sidecar)
            reports_json.add(reports_sidecar)
    else:
        _validate_reports_index(
            dist, reports_root, reports_files, expected_versions["reports"]
        )

    personas_root = PurePosixPath(
        "data/reddit-voc", expected_versions["personas"]
    )
    persona_files, persona_json = _manifest_files(
        dist,
        manifests["personas"],
        personas_root,
        label="personas public manifest",
        suffixes={".json", ".jsonl", ".svg"} if is_v3 else {".json", ".svg"},
        allow_rows=is_v3,
    )
    if not {
        personas_root / "personas.json",
        personas_root / "persona-tags.json",
    }.issubset(persona_files):
        raise AuditError("personas public dataset is incomplete")
    for relative in persona_files:
        local = relative.relative_to(personas_root)
        if local.suffix == ".svg" and (
            len(local.parts) != 2 or local.parts[0] != "assets"
        ):
            raise AuditError("persona SVG assets must remain below assets/")
    if is_v3:
        _validate_v3_persona_boundaries(manifests["personas"])
        _validate_v3_persona_bundle(
            dist, personas_root, expected_versions["personas"]
        )
        public_ndjson.update(
            relative for relative in persona_files if relative.suffix == ".jsonl"
        )
    else:
        _validate_persona_boundaries(manifests["personas"])

    if not is_v3:
        base_lineage = bindings["base"]["lineage_manifest_sha256"]
        insights_lineage = bindings["insights"]["lineage_manifest_sha256"]
        _validate_linkage(
            manifests["insights"],
            label="insights public manifest",
            base_version=expected_versions["base"],
            base_lineage_sha=base_lineage,
        )
        _validate_linkage(
            manifests["reports"],
            label="reports public manifest",
            base_version=expected_versions["base"],
            base_lineage_sha=base_lineage,
            insights_version=expected_versions["insights"],
            insights_lineage_sha=insights_lineage,
        )
        _validate_linkage(
            manifests["personas"],
            label="personas public manifest",
            base_version=expected_versions["base"],
            base_lineage_sha=base_lineage,
            insights_version=expected_versions["insights"],
            insights_lineage_sha=insights_lineage,
        )

    cases_binding = current.get("cases")
    if not isinstance(cases_binding, dict):
        raise AuditError("current-release cases binding must be an object")
    case_files, case_json = _validate_cases(dist, cases_binding)
    auxiliary_files: set[PurePosixPath] = set()
    auxiliary_json: set[PurePosixPath] = set()
    if is_v3:
        if current_v2:
            auxiliary_files, auxiliary_json = (
                _validate_v3_pointer_auxiliary_projections(
                    dist,
                    datasets=datasets,
                    source_snapshot_id=source_snapshot_ids["base"],
                )
            )
        else:
            auxiliary_files, auxiliary_json = _validate_v3_fixed_auxiliary_projections(
                dist, source_snapshot_id=source_snapshot_ids["base"]
            )
    allowed.update(
        base_files
        | insights_files
        | reports_files
        | persona_files
        | case_files
        | auxiliary_files
    )
    public_json.update(
        base_json
        | insights_json
        | reports_json
        | persona_json
        | case_json
        | auxiliary_json
    )
    return AuditContract(
        allowed_data_files=frozenset(allowed),
        public_json_files=frozenset(public_json),
        public_ndjson_files=frozenset(public_ndjson),
        release_id=release_id,
    )


def _walk_files_no_symlinks(root: Path) -> Iterator[Path]:
    if not root.is_dir() or root.is_symlink():
        raise AuditError(f"data directory is missing or unsafe: {root.name}")
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            path = base / name
            if path.is_symlink():
                raise AuditError(f"data bundle must not contain symlinks: {path.name}")
        for name in file_names:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise AuditError(f"data bundle file is unsafe: {path.name}")
            yield path


def _actual_data_files(dist: Path) -> set[PurePosixPath]:
    actual: set[PurePosixPath] = set()
    root = dist / "data"
    for path in _walk_files_no_symlinks(root):
        actual.add(PurePosixPath(path.relative_to(dist).as_posix()))
    return actual


def prepare_dist(dist: Path, contract: AuditContract) -> None:
    """Remove stale/private data copies from the disposable build directory."""

    actual = _actual_data_files(dist)
    for relative in sorted(actual - set(contract.allowed_data_files)):
        dist.joinpath(*relative.parts).unlink()
    data_root = dist / "data"
    for directory, _names, _files in os.walk(data_root, topdown=False):
        path = Path(directory)
        if path != data_root:
            try:
                path.rmdir()
            except OSError:
                pass


def _audit_compiled_stylesheets(dist: Path) -> None:
    """Reject a Vite dist whose Tailwind directives were shipped uncompiled."""

    index = dist / "index.html"
    assets = dist / "assets"
    if not index.exists() and not assets.exists():
        # Data-contract unit fixtures intentionally omit the application shell.
        return
    if index.is_symlink() or not index.is_file() or assets.is_symlink() or not assets.is_dir():
        raise AuditError("application shell or assets directory is missing or unsafe")
    try:
        parser = _StylesheetLinkParser()
        parser.feed(index.read_text(encoding="utf-8"))
        parser.close()
    except (OSError, UnicodeDecodeError) as exc:
        raise AuditError("application index is not readable UTF-8 HTML") from exc
    if not parser.hrefs:
        raise AuditError("application index does not reference a compiled stylesheet")

    payloads: list[bytes] = []
    for href in parser.hrefs:
        if any(token in href for token in ("?", "#", "://")):
            raise AuditError("stylesheet href must bind one immutable local asset")
        relative = PurePosixPath(href.lstrip("/"))
        if (
            len(relative.parts) != 2
            or relative.parts[0] != "assets"
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.suffix.lower() != ".css"
        ):
            raise AuditError("stylesheet href is outside the reviewed assets shape")
        path = dist.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            raise AuditError("referenced stylesheet is missing or unsafe")
        payload = path.read_bytes()
        if not payload:
            raise AuditError("referenced stylesheet is empty")
        if UNRESOLVED_CSS_DIRECTIVE.search(payload):
            raise AuditError("unresolved Tailwind directive remained in production CSS")
        payloads.append(payload)

    compiled = b"\n".join(payloads)
    missing = [
        name
        for name, pattern in REQUIRED_COMPILED_UTILITIES.items()
        if pattern.search(compiled) is None
    ]
    if missing:
        raise AuditError(
            "compiled CSS is missing required layout utilities: " + ",".join(missing)
        )


def audit_dist(dist: Path, contract: AuditContract) -> None:
    actual = _actual_data_files(dist)
    expected = set(contract.allowed_data_files)
    if actual != expected:
        raise AuditError(
            "public data allowlist mismatch; private, stale, missing, or unbound files remain"
        )

    _audit_compiled_stylesheets(dist)

    assets = dist / "assets"
    if assets.is_dir():
        mock_report_chunks = sorted(assets.glob("reportEngine-*.js"))
        if mock_report_chunks:
            raise AuditError("legacy mock report engine remained in production dist")

    for path in dist.rglob("*"):
        if path.is_symlink():
            raise AuditError("dist must not contain symlinks")
        if not path.is_file():
            continue
        relative_path = path.relative_to(dist)
        if path.name.startswith(".env") or path.suffix.lower() in {
            ".key",
            ".pem",
            ".p12",
            ".pfx",
        }:
            raise AuditError(f"credential-like file in dist: {relative_path.name}")
        payload = path.read_bytes()
        for marker in FORBIDDEN_MARKERS:
            if marker in payload:
                raise AuditError(
                    f"forbidden build marker remained in dist file: {relative_path.name}"
                )

    def audit_public_value(data: Any, relative: PurePosixPath, row: int | None = None) -> None:
        row_label = "" if row is None else f":line {row}"
        for location, key, value in walk_json(data):
            if key in FORBIDDEN_KEYS or key in FORBIDDEN_AUTHOR_KEYS:
                raise AuditError(
                    f"forbidden public field at {relative}{row_label}:{location}"
                )
            if key == "author_pseudonym" and value is not None:
                raise AuditError(
                    f"public author linkage remained at {relative}{row_label}:{location}"
                )

    for relative in sorted(contract.public_json_files):
        data = _load_json_value(
            dist.joinpath(*relative.parts), "public JSON artifact"
        )
        audit_public_value(data, relative)

    for relative in sorted(contract.public_ndjson_files):
        path = dist.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise AuditError(f"public NDJSON artifact is missing or unsafe: {path.name}")
        try:
            with path.open("r", encoding="utf-8") as stream:
                for row_number, line in enumerate(stream, start=1):
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise AuditError(
                            f"public NDJSON artifact is invalid at {relative}:line {row_number}"
                        ) from exc
                    if not isinstance(value, dict):
                        raise AuditError(
                            f"public NDJSON row must be an object at {relative}:line {row_number}"
                        )
                    audit_public_value(value, relative, row_number)
        except (OSError, UnicodeDecodeError) as exc:
            raise AuditError(f"public NDJSON artifact is not readable UTF-8: {relative}") from exc


def _resolved_dist(path: Path) -> Path:
    if path.is_symlink():
        raise AuditError(f"dist must not be a symlink: {path}")
    dist = path.resolve()
    if not dist.is_dir():
        raise AuditError(f"dist must be a regular directory: {dist}")
    return dist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--insights-version", required=True)
    parser.add_argument("--reports-version", required=True)
    parser.add_argument("--personas-version", required=True)
    parser.add_argument(
        "--current-release-path", default=str(CURRENT_RELEASE_PATH)
    )
    parser.add_argument(
        "--translation-admission-receipt",
        type=Path,
        help="exact reviewed G5 receipt required for a translated non-promotable Base",
    )
    parser.add_argument(
        "--prepare-dist",
        action="store_true",
        help="remove only unbound files below dist/data before the audit",
    )
    args = parser.parse_args()
    try:
        dist = _resolved_dist(args.dist)
        contract = discover_contract(
            dist,
            base_version=args.base_version,
            insights_version=args.insights_version,
            reports_version=args.reports_version,
            personas_version=args.personas_version,
            current_release_path=args.current_release_path,
            translation_admission_receipt=args.translation_admission_receipt,
        )
        if args.prepare_dist:
            prepare_dist(dist, contract)
        audit_dist(dist, contract)
    except AuditError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "dist_public_projection_audit=passed "
        f"release_id={contract.release_id} "
        f"prepared={str(args.prepare_dist).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
