from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


V2_PROFILE_SCHEMA_VERSION = "momcozy_reddit_search_profile_v2_candidate"
V2_PROFILE_STATUS = "reviewed_candidate_not_activated"
V2_GROUPS = (
    "owner_alias_gap",
    "momcozy_model_gap",
    "official_catalog_aliases",
    "governed_competitors",
    "category_anchors",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_KEYS = frozenset(
    (
        "candidate_groups",
        "candidate_term_count",
        "competitor_term_bindings",
        "delta_term_count",
        "delta_terms",
        "execution_contract",
        "generated_on",
        "legacy_frozen_run",
        "official_product_term_bindings",
        "schema_version",
        "source_dictionary",
        "source_official_catalog",
        "status",
    )
)


class BackfillProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedV2SearchProfile:
    path: Path
    sha256: str
    candidate_terms: tuple[str, ...]
    delta_terms: tuple[str, ...]
    groups: dict[str, tuple[str, ...]]
    legacy_run_id: str


def load_v2_search_profile(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> ValidatedV2SearchProfile:
    profile_path = Path(path)
    try:
        raw = profile_path.read_bytes()
    except OSError as exc:
        raise BackfillProfileError("v2_profile_unreadable") from exc
    digest = sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or _SHA256_PATTERN.fullmatch(
            expected_sha256
        ) is None:
            raise BackfillProfileError("v2_profile_expected_sha256_invalid")
        if digest != expected_sha256:
            raise BackfillProfileError("v2_profile_sha256_mismatch")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise BackfillProfileError("v2_profile_json_invalid") from exc
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise BackfillProfileError("v2_profile_fields_invalid")
    if value["schema_version"] != V2_PROFILE_SCHEMA_VERSION:
        raise BackfillProfileError("v2_profile_schema_invalid")
    if value["status"] != V2_PROFILE_STATUS:
        raise BackfillProfileError("v2_profile_status_invalid")

    groups = _validated_groups(value["candidate_groups"])
    candidate_terms = tuple(term for group in V2_GROUPS for term in groups[group])
    if len(candidate_terms) != len(set(candidate_terms)):
        raise BackfillProfileError("v2_profile_candidate_terms_duplicate")
    if value["candidate_term_count"] != len(candidate_terms):
        raise BackfillProfileError("v2_profile_candidate_term_count_invalid")

    delta_terms = _validated_terms(value["delta_terms"], "v2_profile_delta_terms")
    if value["delta_term_count"] != len(delta_terms):
        raise BackfillProfileError("v2_profile_delta_term_count_invalid")
    if not set(delta_terms).issubset(candidate_terms):
        raise BackfillProfileError("v2_profile_delta_terms_not_candidates")

    legacy_terms, legacy_run_id = _validated_legacy_run(value["legacy_frozen_run"])
    if tuple(term for term in candidate_terms if term not in legacy_terms) != delta_terms:
        raise BackfillProfileError("v2_profile_delta_terms_not_exact")
    _validate_execution_contract(value["execution_contract"])
    _validate_term_bindings(
        value["competitor_term_bindings"],
        groups["governed_competitors"],
        "v2_profile_competitor_bindings",
        required_key="brand",
    )
    _validate_term_bindings(
        value["official_product_term_bindings"],
        groups["official_catalog_aliases"],
        "v2_profile_official_bindings",
        required_key="family_id",
    )
    _validate_source(value["source_dictionary"], "v2_profile_dictionary_source")
    _validate_source(value["source_official_catalog"], "v2_profile_catalog_source")
    if not isinstance(value["generated_on"], str) or not value["generated_on"]:
        raise BackfillProfileError("v2_profile_generated_on_invalid")

    return ValidatedV2SearchProfile(
        path=profile_path,
        sha256=digest,
        candidate_terms=candidate_terms,
        delta_terms=delta_terms,
        groups=groups,
        legacy_run_id=legacy_run_id,
    )


def _validated_groups(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict) or set(value) != set(V2_GROUPS):
        raise BackfillProfileError("v2_profile_groups_invalid")
    return {
        group: _validated_terms(value[group], f"v2_profile_group_{group}")
        for group in V2_GROUPS
    }


def _validated_terms(value: Any, reason: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(term, str) or not term.strip() for term in value)
        or len(value) != len(set(value))
    ):
        raise BackfillProfileError(f"{reason}_invalid")
    return tuple(value)


def _validated_legacy_run(value: Any) -> tuple[set[str], str]:
    required = {
        "distinct_semantic_term_count",
        "immutable",
        "run_id",
        "term_count",
        "terms",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BackfillProfileError("v2_profile_legacy_run_invalid")
    terms = _validated_terms(value["terms"], "v2_profile_legacy_terms")
    if (
        value["immutable"] is not True
        or not isinstance(value["run_id"], str)
        or not value["run_id"]
        or value["term_count"] != len(terms)
        or not isinstance(value["distinct_semantic_term_count"], int)
    ):
        raise BackfillProfileError("v2_profile_legacy_run_invalid")
    return set(terms), value["run_id"]


def _validate_execution_contract(value: Any) -> None:
    required = {
        "git_push_authorized",
        "live_send",
        "new_run_required",
        "pre_provider_order",
        "production_merge_authorized",
        "provider_authorization_required",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value["git_push_authorized"] is not False
        or value["live_send"] is not False
        or value["new_run_required"] is not True
        or value["production_merge_authorized"] is not False
        or value["provider_authorization_required"] is not True
        or not isinstance(value["pre_provider_order"], list)
        or not value["pre_provider_order"]
        or any(not isinstance(item, str) or not item for item in value["pre_provider_order"])
    ):
        raise BackfillProfileError("v2_profile_execution_contract_invalid")


def _validate_term_bindings(
    value: Any,
    expected_terms: tuple[str, ...],
    reason: str,
    *,
    required_key: str,
) -> None:
    if not isinstance(value, list) or len(value) != len(expected_terms):
        raise BackfillProfileError(f"{reason}_invalid")
    terms: list[str] = []
    for binding in value:
        if (
            not isinstance(binding, dict)
            or not isinstance(binding.get("term"), str)
            or not binding["term"]
            or not isinstance(binding.get(required_key), str)
            or not binding[required_key]
        ):
            raise BackfillProfileError(f"{reason}_invalid")
        terms.append(binding["term"])
    if tuple(terms) != expected_terms:
        raise BackfillProfileError(f"{reason}_terms_invalid")


def _validate_source(value: Any, reason: str) -> None:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("path"), str)
        or not value["path"]
        or _SHA256_PATTERN.fullmatch(str(value.get("sha256", ""))) is None
    ):
        raise BackfillProfileError(f"{reason}_invalid")
