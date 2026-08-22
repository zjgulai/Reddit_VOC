"""Provider-free closed-set atomic signal facts for Reddit VOC V3.

The matcher emits evidence-bound ``reddit_voc_atomic_fact_v2`` rows.  It does
not call a model or promote legacy lexical matches unless a frozen registry
explicitly approves the exact phrase.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from reddit_voc.v3_canonical_identity import (
    CanonicalIdentityError,
    canonical_comment_fullname,
    canonical_comment_id,
    canonical_post_fullname,
    canonical_post_id,
)


DIM_TAG_SHA256 = "22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14"
PRODUCT_ENTITY_LEDGER_SHA256 = (
    "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab"
)
CLOSED_SET_REGISTRY_SHA256 = (
    "35efdc71543f128acc96f9e30d1788d1e78972b042f64e369d01c43fd5723d71"
)
FACT_SCHEMA_VERSION = "reddit_voc_atomic_fact_v2"
NORMALIZER_VERSION = "source_token_span_v1"
RESOURCE_SCHEMA_VERSION = "reddit_voc_closed_set_signal_registry_v1"
EXPECTED_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
CLOSED_SET_FACT_TYPES = (
    "entity_brand_fact",
    "entity_product_fact",
    "entity_sentiment_fact",
    "entity_problem_fact",
    "entity_tag_fact",
)
FACT_TYPES = frozenset(CLOSED_SET_FACT_TYPES)
DECISION_STATUSES = frozenset({"promoted", "held"})
DIM_TAG_HEADERS = (
    "tag_id",
    "name_cn",
    "name_en",
    "definition",
    "aipl_node",
    "theme",
    "sentiment",
    "proxy_nps_role",
    "keywords_en",
    "dept_owner",
    "default_priority",
    "risk_level",
    "source_type",
    "tag_scope",
    "product_line",
    "voc_category",
    "spu_id",
    "sat_indicator_code",
    "sat_indicator_name",
    "diagnosis_topic",
    "consumer_card",
    "business_impact",
    "consumer_phrases",
    "story_lines",
    "strategy_package",
    "biz_action",
    "problem_type",
    "intent_type",
)
TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*", re.IGNORECASE)


class ClosedSetFactError(ValueError):
    """A closed-set resource, input VOC, or fact is not governed."""


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
        raise ClosedSetFactError(
            "value is not canonical JSON serializable"
        ) from exc


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ClosedSetFactError(f"{label} must be a non-empty string")
    return value


def _phrase_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).translate(
        str.maketrans({"’": "'", "‘": "'", "`": "'"})
    )
    return tuple(match.group(0).casefold() for match in TOKEN.finditer(normalized))


@dataclass(frozen=True)
class _SourceToken:
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class _PhraseSpec:
    phrase: str
    tokens: tuple[str, ...]
    fact_type: str
    canonical_value: str
    rule_id: str
    rule_source: str
    attributes: tuple[tuple[str, object], ...]
    negation_sensitive: bool
    approved_for_promotion: bool


@dataclass(frozen=True)
class _FieldSource:
    field: str
    text: str
    evidence_scope: str
    evidence_source_entity_id: str


@dataclass(frozen=True)
class _Candidate:
    fact_type: str
    canonical_value: str
    attributes: tuple[tuple[str, object], ...]
    field: str
    start: int
    end: int
    token_start: int
    token_end: int
    evidence_scope: str
    evidence_source_entity_id: str
    decision_status: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ClosedSetFact:
    fact_id: str
    canonical_entity_id: str
    voc_id: str
    voc_type: str
    fact_type: str
    canonical_value: str
    attributes: dict[str, object]
    evidence_field: str
    evidence_start: int
    evidence_end: int
    evidence_text_sha256: str
    evidence_scope: str
    evidence_source_entity_id: str
    context_evidence_refs: tuple[str, ...]
    decision_status: str
    reason_codes: tuple[str, ...]
    dictionary_release_id: str
    matcher_version: str
    normalizer_version: str
    source_snapshot_id: str
    created_at: str
    schema_version: str = FACT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "attributes": dict(self.attributes),
            "canonical_entity_id": self.canonical_entity_id,
            "canonical_value": self.canonical_value,
            "context_evidence_refs": list(self.context_evidence_refs),
            "created_at": self.created_at,
            "decision_status": self.decision_status,
            "dictionary_release_id": self.dictionary_release_id,
            "evidence_end": self.evidence_end,
            "evidence_field": self.evidence_field,
            "evidence_scope": self.evidence_scope,
            "evidence_source_entity_id": self.evidence_source_entity_id,
            "evidence_start": self.evidence_start,
            "evidence_text_sha256": self.evidence_text_sha256,
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "matcher_version": self.matcher_version,
            "normalizer_version": self.normalizer_version,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "source_snapshot_id": self.source_snapshot_id,
            "voc_id": self.voc_id,
            "voc_type": self.voc_type,
        }


@dataclass(frozen=True)
class ClosedSetResources:
    registry_sha256: str
    dim_tag_sha256: str
    product_entity_ledger_sha256: str
    registry_version: str
    matcher_version: str
    dictionary_release_id: str
    negation_tokens: frozenset[str]
    context_window_chars: int
    category_phrases: tuple[tuple[str, ...], ...]
    momcozy_brand_specs: tuple[_PhraseSpec, ...]
    comparison_brand_specs: tuple[_PhraseSpec, ...]
    product_specs: tuple[_PhraseSpec, ...]
    semantic_specs: tuple[_PhraseSpec, ...]
    tag_specs: tuple[_PhraseSpec, ...]
    tag_phrase_owner_count: dict[tuple[str, ...], int]
    approved_tag_phrases: frozenset[tuple[str, tuple[str, ...]]]


def _read_json(path: Path, *, label: str, expected_sha256: str) -> dict[str, Any]:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise ClosedSetFactError(f"{label} is unreadable") from exc
    if _sha(payload) != expected_sha256:
        raise ClosedSetFactError(f"{label} SHA-256 is invalid")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosedSetFactError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ClosedSetFactError(f"{label} must be an object")
    return value


def _validated_rule_rows(
    value: object,
    *,
    label: str,
    fact_type: str,
    topic_kind_required: bool = False,
) -> tuple[_PhraseSpec, ...]:
    if not isinstance(value, list):
        raise ClosedSetFactError(f"{label} must be a list")
    result: list[_PhraseSpec] = []
    seen_rules: set[str] = set()
    seen_pairs: set[tuple[str, tuple[str, ...]]] = set()
    for row in value:
        expected = {
            "canonical_value",
            "negation_sensitive",
            "phrases",
            "rule_id",
        }
        if topic_kind_required:
            expected.add("topic_kind")
        if not isinstance(row, Mapping) or set(row) != expected:
            raise ClosedSetFactError(f"{label} rule fields are invalid")
        rule_id = _string(row.get("rule_id"), f"{label} rule ID")
        canonical_value = _string(
            row.get("canonical_value"), f"{label} canonical value"
        )
        phrases = row.get("phrases")
        negation_sensitive = row.get("negation_sensitive")
        if (
            rule_id in seen_rules
            or not isinstance(phrases, list)
            or not phrases
            or phrases != sorted(set(phrases))
            or any(not isinstance(item, str) or not item for item in phrases)
            or type(negation_sensitive) is not bool
        ):
            raise ClosedSetFactError(f"{label} rule is invalid")
        seen_rules.add(rule_id)
        attributes: dict[str, object] = {
            "rule_id": rule_id,
            "rule_source": "closed_set_registry",
        }
        if topic_kind_required:
            topic_kind = row.get("topic_kind")
            if topic_kind not in {"scenario", "topic"}:
                raise ClosedSetFactError(f"{label} topic kind is invalid")
            attributes["signal_kind"] = topic_kind
        for phrase in phrases:
            tokens = _phrase_tokens(phrase)
            key = (canonical_value, tokens)
            if not tokens or key in seen_pairs:
                raise ClosedSetFactError(f"{label} phrase is invalid or duplicate")
            seen_pairs.add(key)
            result.append(
                _PhraseSpec(
                    phrase=phrase,
                    tokens=tokens,
                    fact_type=fact_type,
                    canonical_value=canonical_value,
                    rule_id=rule_id,
                    rule_source="closed_set_registry",
                    attributes=tuple(sorted(attributes.items())),
                    negation_sensitive=bool(negation_sensitive),
                    approved_for_promotion=True,
                )
            )
    return tuple(result)


def _load_tags(
    path: Path,
    promotion_rows: object,
) -> tuple[
    tuple[_PhraseSpec, ...],
    dict[tuple[str, ...], int],
    frozenset[tuple[str, tuple[str, ...]]],
]:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise ClosedSetFactError("tag dictionary is unreadable") from exc
    if _sha(payload) != DIM_TAG_SHA256:
        raise ClosedSetFactError("tag dictionary SHA-256 is invalid")
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ClosedSetFactError("tag dictionary CSV is invalid") from exc
    if tuple(reader.fieldnames or ()) != DIM_TAG_HEADERS or len(rows) != 2346:
        raise ClosedSetFactError("tag dictionary shape is invalid")
    by_id: dict[str, dict[str, str]] = {}
    tag_keywords: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {}
    owners: dict[tuple[str, ...], set[str]] = {}
    for row in rows:
        tag_id = _string(row.get("tag_id"), "tag ID")
        if tag_id in by_id:
            raise ClosedSetFactError("tag dictionary contains duplicate IDs")
        try:
            keywords = json.loads(row["keywords_en"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ClosedSetFactError("tag keywords are invalid JSON") from exc
        if (
            not isinstance(keywords, list)
            or not keywords
            or any(not isinstance(item, str) or not item for item in keywords)
            or len(keywords) != len(set(keywords))
        ):
            raise ClosedSetFactError("tag keyword list is invalid")
        specs: list[tuple[str, tuple[str, ...]]] = []
        seen_tokens: set[tuple[str, ...]] = set()
        for phrase in keywords:
            tokens = _phrase_tokens(phrase)
            if not tokens:
                raise ClosedSetFactError("tag normalized keyword is empty")
            if tokens in seen_tokens:
                continue
            seen_tokens.add(tokens)
            specs.append((phrase, tokens))
            owners.setdefault(tokens, set()).add(tag_id)
        by_id[tag_id] = dict(row)
        tag_keywords[tag_id] = tuple(specs)

    if not isinstance(promotion_rows, list):
        raise ClosedSetFactError("tag promotion rules are invalid")
    approved: set[tuple[str, tuple[str, ...]]] = set()
    for promotion in promotion_rows:
        if not isinstance(promotion, Mapping) or set(promotion) != {
            "negation_sensitive",
            "phrases",
            "rule_id",
            "tag_id",
        }:
            raise ClosedSetFactError("tag promotion rule fields are invalid")
        tag_id = _string(promotion.get("tag_id"), "promoted tag ID")
        rule_id = _string(promotion.get("rule_id"), "tag promotion rule ID")
        phrases = promotion.get("phrases")
        if (
            tag_id not in by_id
            or type(promotion.get("negation_sensitive")) is not bool
            or not isinstance(phrases, list)
            or not phrases
            or phrases != sorted(set(phrases))
        ):
            raise ClosedSetFactError("tag promotion rule is invalid")
        known = {tokens for _, tokens in tag_keywords[tag_id]}
        for phrase in phrases:
            if not isinstance(phrase, str):
                raise ClosedSetFactError("tag promotion phrase is invalid")
            tokens = _phrase_tokens(phrase)
            if tokens not in known or (tag_id, tokens) in approved:
                raise ClosedSetFactError(
                    "tag promotion phrase is not bound to the dictionary"
                )
            approved.add((tag_id, tokens))

    specs: list[_PhraseSpec] = []
    for tag_id, keywords in tag_keywords.items():
        row = by_id[tag_id]
        for phrase, tokens in keywords:
            promoted = (tag_id, tokens) in approved
            specs.append(
                _PhraseSpec(
                    phrase=phrase,
                    tokens=tokens,
                    fact_type="entity_tag_fact",
                    canonical_value=tag_id,
                    rule_id=(
                        "tag_dictionary_approved_phrase_v1"
                        if promoted
                        else "tag_dictionary_lexical_candidate_v1"
                    ),
                    rule_source="dim_tag_v6.3_final",
                    attributes=tuple(
                        sorted(
                            {
                                "intent_type": row["intent_type"],
                                "name_en": row["name_en"],
                                "problem_type": row["problem_type"],
                                "promotion_approved": promoted,
                                "rule_source": "dim_tag_v6.3_final",
                                "sentiment": row["sentiment"],
                                "signal_kind": "voc_tag",
                                "tag_id": tag_id,
                            }.items()
                        )
                    ),
                    negation_sensitive=True,
                    approved_for_promotion=promoted,
                )
            )
    specs.sort(key=lambda spec: (spec.tokens, spec.canonical_value))
    return (
        tuple(specs),
        {tokens: len(tag_ids) for tokens, tag_ids in owners.items()},
        frozenset(approved),
    )


def load_closed_set_resources(
    *,
    dim_tag_path: Path,
    product_entity_ledger_path: Path,
    registry_path: Path,
) -> ClosedSetResources:
    registry = _read_json(
        registry_path,
        label="closed-set registry",
        expected_sha256=CLOSED_SET_REGISTRY_SHA256,
    )
    if Path(registry_path).read_bytes() != canonical_json_bytes(registry) + b"\n":
        raise ClosedSetFactError("closed-set registry is not canonical JSON")
    expected_registry_keys = {
        "bindings",
        "boundaries",
        "matcher_version",
        "negation_tokens",
        "problem_rules",
        "registry_version",
        "schema_version",
        "sentiment_rules",
        "tag_promotion_rules",
        "topic_rules",
    }
    bindings = registry.get("bindings")
    negation_tokens = registry.get("negation_tokens")
    if (
        set(registry) != expected_registry_keys
        or registry.get("schema_version") != RESOURCE_SCHEMA_VERSION
        or registry.get("boundaries") != EXPECTED_BOUNDARIES
        or bindings
        != {
            "dim_tag_sha256": DIM_TAG_SHA256,
            "product_entity_ledger_sha256": PRODUCT_ENTITY_LEDGER_SHA256,
        }
        or not isinstance(negation_tokens, list)
        or negation_tokens != sorted(set(negation_tokens))
        or any(
            not isinstance(item, str) or len(_phrase_tokens(item)) != 1
            for item in negation_tokens
        )
    ):
        raise ClosedSetFactError("closed-set registry contract is invalid")
    registry_version = _string(
        registry.get("registry_version"), "closed-set registry version"
    )
    matcher_version = _string(
        registry.get("matcher_version"), "closed-set matcher version"
    )

    ledger = _read_json(
        product_entity_ledger_path,
        label="product entity ledger",
        expected_sha256=PRODUCT_ENTITY_LEDGER_SHA256,
    )
    if (
        ledger.get("schema_version") != "momcozy_product_entity_ledger_v1"
        or not isinstance(ledger.get("brand"), Mapping)
        or not isinstance(ledger.get("comparison_brand_aliases"), list)
        or not isinstance(ledger.get("categories"), list)
        or not isinstance(ledger.get("families"), list)
        or not isinstance(ledger.get("exact_spu_ledger"), list)
        or type(ledger.get("context_window_chars")) is not int
        or not 1 <= ledger["context_window_chars"] <= 512
    ):
        raise ClosedSetFactError("product entity ledger contract is invalid")

    tag_specs, tag_owner_count, approved_tags = _load_tags(
        dim_tag_path, registry.get("tag_promotion_rules")
    )
    sentiment_specs = _validated_rule_rows(
        registry.get("sentiment_rules"),
        label="sentiment",
        fact_type="entity_sentiment_fact",
    )
    problem_specs = _validated_rule_rows(
        registry.get("problem_rules"),
        label="problem",
        fact_type="entity_problem_fact",
    )
    topic_specs = _validated_rule_rows(
        registry.get("topic_rules"),
        label="topic",
        fact_type="entity_tag_fact",
        topic_kind_required=True,
    )

    brand = ledger["brand"]
    if set(brand) != {"aliases", "brand_id"} or brand.get("brand_id") != "momcozy":
        raise ClosedSetFactError("product ledger focal brand is invalid")
    focal_aliases = brand.get("aliases")
    comparison_aliases = ledger.get("comparison_brand_aliases")
    if (
        not isinstance(focal_aliases, list)
        or len(focal_aliases) != len(set(focal_aliases))
        or not isinstance(comparison_aliases, list)
        or len(comparison_aliases) != len(set(comparison_aliases))
    ):
        raise ClosedSetFactError("product ledger brand aliases are invalid")

    def brand_spec(alias: str, *, focal: bool) -> _PhraseSpec:
        tokens = _phrase_tokens(alias)
        if not tokens:
            raise ClosedSetFactError("product ledger brand alias is invalid")
        return _PhraseSpec(
            phrase=alias,
            tokens=tokens,
            fact_type="entity_brand_fact",
            canonical_value="momcozy" if focal else "competitor",
            rule_id="governed_brand_alias_v1",
            rule_source="momcozy_product_entity_ledger",
            attributes=tuple(
                sorted(
                    {
                        "brand_id": "momcozy" if focal else alias.casefold(),
                        "brand_role": "focal" if focal else "competitor",
                        "matched_alias": alias,
                        "rule_source": "momcozy_product_entity_ledger",
                    }.items()
                )
            ),
            negation_sensitive=False,
            approved_for_promotion=True,
        )

    momcozy_specs = tuple(brand_spec(alias, focal=True) for alias in focal_aliases)
    competitor_specs = tuple(
        brand_spec(alias, focal=False) for alias in comparison_aliases
    )

    category_by_id: dict[str, tuple[tuple[str, ...], ...]] = {}
    category_phrases: list[tuple[str, ...]] = []
    for category in ledger["categories"]:
        if not isinstance(category, Mapping) or set(category) != {
            "category_id",
            "context_terms",
            "name_cn",
            "name_en",
        }:
            raise ClosedSetFactError("product category is invalid")
        category_id = _string(category.get("category_id"), "product category ID")
        terms = category.get("context_terms")
        if (
            category_id in category_by_id
            or not isinstance(terms, list)
            or not terms
            or len(terms) != len(set(terms))
        ):
            raise ClosedSetFactError("product category context is invalid")
        normalized_terms = tuple(_phrase_tokens(term) for term in terms)
        if any(not tokens for tokens in normalized_terms):
            raise ClosedSetFactError("product category context term is invalid")
        category_by_id[category_id] = normalized_terms
        category_phrases.extend(normalized_terms)

    spu_by_family: dict[str, Mapping[str, Any]] = {}
    for row in ledger["exact_spu_ledger"]:
        if not isinstance(row, Mapping):
            raise ClosedSetFactError("exact SPU ledger row is invalid")
        family_id = _string(row.get("family_id"), "SPU family ID")
        if family_id in spu_by_family:
            raise ClosedSetFactError("exact SPU family is duplicate")
        if (
            type(row.get("publish_exact_spu")) is not bool
            or row.get("mapping_status")
            not in {"approved_for_publication", "verified_blocked"}
        ):
            raise ClosedSetFactError("exact SPU governance state is invalid")
        spu_by_family[family_id] = row

    product_specs: list[_PhraseSpec] = []
    seen_families: set[str] = set()
    for family in ledger["families"]:
        if not isinstance(family, Mapping) or set(family) != {
            "aliases",
            "category_id",
            "family_id",
            "family_only_reason",
            "name_cn",
            "name_en",
        }:
            raise ClosedSetFactError("product family is invalid")
        family_id = _string(family.get("family_id"), "product family ID")
        category_id = _string(family.get("category_id"), "product family category")
        aliases = family.get("aliases")
        if (
            family_id in seen_families
            or category_id not in category_by_id
            or not isinstance(aliases, list)
            or not aliases
        ):
            raise ClosedSetFactError("product family contract is invalid")
        seen_families.add(family_id)
        spu = spu_by_family.get(family_id)
        publish_spu = bool(spu and spu.get("publish_exact_spu") is True)
        canonical_value = (
            f"spu:{spu['spu_id']}" if publish_spu else f"family:{family_id}"
        )
        for alias in aliases:
            if not isinstance(alias, Mapping) or set(alias) != {"match_type", "value"}:
                raise ClosedSetFactError("product family alias is invalid")
            alias_value = _string(alias.get("value"), "product family alias")
            match_type = alias.get("match_type")
            if match_type not in {"strong_name", "contextual_alias"}:
                raise ClosedSetFactError("product alias match type is invalid")
            tokens = _phrase_tokens(alias_value)
            if not tokens:
                raise ClosedSetFactError("product family alias has no tokens")
            product_specs.append(
                _PhraseSpec(
                    phrase=alias_value,
                    tokens=tokens,
                    fact_type="entity_product_fact",
                    canonical_value=canonical_value,
                    rule_id="governed_product_alias_v1",
                    rule_source="momcozy_product_entity_ledger",
                    attributes=tuple(
                        sorted(
                            {
                                "category_id": category_id,
                                "exact_spu_mapping_status": (
                                    spu.get("mapping_status") if spu else "unmapped"
                                ),
                                "family_id": family_id,
                                "family_only_reason": family.get(
                                    "family_only_reason"
                                ),
                                "match_type": match_type,
                                "matched_alias": alias_value,
                                "rule_source": "momcozy_product_entity_ledger",
                            }.items()
                        )
                    ),
                    negation_sensitive=False,
                    approved_for_promotion=match_type == "strong_name",
                )
            )

    dictionary_release_id = (
        f"dim_tag_v6.3_final@{DIM_TAG_SHA256};"
        f"momcozy_product_entity_ledger@{PRODUCT_ENTITY_LEDGER_SHA256};"
        f"closed_set_registry@{CLOSED_SET_REGISTRY_SHA256}"
    )
    return ClosedSetResources(
        registry_sha256=CLOSED_SET_REGISTRY_SHA256,
        dim_tag_sha256=DIM_TAG_SHA256,
        product_entity_ledger_sha256=PRODUCT_ENTITY_LEDGER_SHA256,
        registry_version=registry_version,
        matcher_version=matcher_version,
        dictionary_release_id=dictionary_release_id,
        negation_tokens=frozenset(negation_tokens),
        context_window_chars=int(ledger["context_window_chars"]),
        category_phrases=tuple(sorted(set(category_phrases))),
        momcozy_brand_specs=momcozy_specs,
        comparison_brand_specs=competitor_specs,
        product_specs=tuple(product_specs),
        semantic_specs=tuple((*sentiment_specs, *problem_specs, *topic_specs)),
        tag_specs=tag_specs,
        tag_phrase_owner_count=tag_owner_count,
        approved_tag_phrases=approved_tags,
    )


def _voc(value: object) -> Mapping[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise ClosedSetFactError("VOC must be an object")
    return value


def _validate_voc(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    if row.get("schema_version") != "reddit_voc_fielded_voc_v1":
        raise ClosedSetFactError("VOC schema is unsupported")
    if row.get("analysis_text_status") != "ready":
        raise ClosedSetFactError("VOC analysis text is not ready")
    voc_id = _string(row.get("voc_id"), "VOC ID")
    voc_type = _string(row.get("voc_type"), "VOC type")
    canonical_entity_id = _string(
        row.get("canonical_entity_id"), "canonical entity ID"
    )
    raw_post_id = _string(row.get("post_id"), "post ID")
    raw_thread_id = _string(row.get("thread_id"), "thread ID")
    try:
        post_id = canonical_post_id(raw_post_id)
    except CanonicalIdentityError as exc:
        raise ClosedSetFactError("VOC post identity is invalid") from exc
    if raw_post_id != post_id or raw_thread_id != post_id:
        raise ClosedSetFactError("VOC post/thread identity mismatch")
    if voc_type == "post_voc":
        if not voc_id.startswith("post:"):
            raise ClosedSetFactError("post VOC namespace is invalid")
        voc_post_id = voc_id.removeprefix("post:")
        if (
            voc_post_id != post_id
            or canonical_entity_id != canonical_post_fullname(post_id)
            or row.get("comment_id") is not None
        ):
            raise ClosedSetFactError("post VOC identity mismatch")
    elif voc_type == "comment_context_voc":
        if not voc_id.startswith("comment:"):
            raise ClosedSetFactError("comment VOC namespace is invalid")
        raw_comment_id = _string(row.get("comment_id"), "comment ID")
        try:
            comment_id = canonical_comment_id(raw_comment_id)
        except CanonicalIdentityError as exc:
            raise ClosedSetFactError("comment VOC identity is invalid") from exc
        if (
            voc_id != f"comment:{comment_id}"
            or canonical_entity_id != canonical_comment_fullname(comment_id)
            or row.get("comment_context_id") != f"{post_id}:{comment_id}"
        ):
            raise ClosedSetFactError("comment VOC identity mismatch")
    else:
        raise ClosedSetFactError("VOC type is unsupported")
    fields = row.get("analysis_fields")
    if not isinstance(fields, Mapping) or set(fields) != {
        "current_comment_body",
        "post_body",
        "post_title",
    }:
        raise ClosedSetFactError("VOC analysis fields are invalid")
    if any(not isinstance(fields[name], str) for name in fields):
        raise ClosedSetFactError("VOC analysis field must be text")
    return voc_id, voc_type, canonical_entity_id, post_id


def _created_at(value: object) -> str:
    text = _string(value, "created at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClosedSetFactError("created at must be ISO-8601") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.microsecond != 0
        or text != parsed.isoformat(timespec="seconds")
    ):
        raise ClosedSetFactError("created at must be canonical UTC seconds")
    return text


def _source_tokens(text: str) -> tuple[_SourceToken, ...]:
    normalized = unicodedata.normalize("NFKC", text).translate(
        str.maketrans({"’": "'", "‘": "'", "`": "'"})
    )
    if normalized != text:
        # Offset-preserving normalization is intentionally fail-closed.  The
        # source span can still be processed by a later governed normalizer.
        return ()
    return tuple(
        _SourceToken(match.group(0).casefold(), match.start(), match.end())
        for match in TOKEN.finditer(text)
    )


@lru_cache(maxsize=16)
def _spec_index(
    specs: tuple[_PhraseSpec, ...],
) -> dict[str, tuple[_PhraseSpec, ...]]:
    grouped: dict[str, list[_PhraseSpec]] = {}
    for spec in specs:
        grouped.setdefault(spec.tokens[0], []).append(spec)
    return {
        token: tuple(
            sorted(
                values,
                key=lambda spec: (-len(spec.tokens), spec.canonical_value, spec.phrase),
            )
        )
        for token, values in grouped.items()
    }


def _occurrences(
    field: _FieldSource,
    specs: Sequence[_PhraseSpec],
) -> tuple[tuple[_PhraseSpec, int, int, int, int], ...]:
    tokens = _source_tokens(field.text)
    if not tokens:
        return ()
    index = _spec_index(tuple(specs))
    result: list[tuple[_PhraseSpec, int, int, int, int]] = []
    for token_index, token in enumerate(tokens):
        for spec in index.get(token.value, ()):
            end_index = token_index + len(spec.tokens)
            if end_index > len(tokens):
                continue
            if tuple(item.value for item in tokens[token_index:end_index]) != spec.tokens:
                continue
            result.append(
                (
                    spec,
                    tokens[token_index].start,
                    tokens[end_index - 1].end,
                    token_index,
                    end_index,
                )
            )
    return tuple(result)


def _negated(
    text: str,
    tokens: Sequence[_SourceToken],
    token_start: int,
    negations: frozenset[str],
) -> bool:
    lower = max(0, token_start - 3)
    for index in range(token_start - 1, lower - 1, -1):
        between = text[tokens[index].end : tokens[token_start].start]
        if re.search(r"[.!?\n]", between):
            break
        if tokens[index].value in negations:
            return True
    return False


def _fields(
    row: Mapping[str, Any],
    *,
    allow_comment_context: bool,
) -> tuple[_FieldSource, ...]:
    fields = row["analysis_fields"]
    entity_id = str(row["canonical_entity_id"])
    if row["voc_type"] == "post_voc":
        return tuple(
            _FieldSource(name, fields[name], "direct", entity_id)
            for name in ("post_title", "post_body")
            if fields[name]
        )
    current = (
        _FieldSource(
            "current_comment_body",
            fields["current_comment_body"],
            "direct",
            entity_id,
        ),
    )
    if not allow_comment_context:
        return tuple(field for field in current if field.text)
    parent_id = f"t3_{row['post_id']}"
    return tuple(
        field
        for field in (
            *current,
            _FieldSource("post_title", fields["post_title"], "cross_context", parent_id),
            _FieldSource("post_body", fields["post_body"], "cross_context", parent_id),
        )
        if field.text
    )


def _has_context(
    field: _FieldSource,
    *,
    start: int,
    end: int,
    resources: ClosedSetResources,
) -> bool:
    left = max(0, start - resources.context_window_chars)
    right = min(len(field.text), end + resources.context_window_chars)
    window = field.text[left:right]
    window_tokens = tuple(token.value for token in _source_tokens(window))
    if not window_tokens:
        return False
    phrases = (*resources.category_phrases, *(
        spec.tokens for spec in resources.momcozy_brand_specs
    ))
    for phrase in phrases:
        size = len(phrase)
        if any(window_tokens[index : index + size] == phrase for index in range(len(window_tokens) - size + 1)):
            return True
    return False


def _candidate_from_occurrence(
    field: _FieldSource,
    occurrence: tuple[_PhraseSpec, int, int, int, int],
    *,
    resources: ClosedSetResources,
    entity_kind: bool = False,
) -> _Candidate:
    spec, start, end, token_start, token_end = occurrence
    status = "promoted" if spec.approved_for_promotion else "held"
    reasons: set[str] = {
        "closed_set_exact_phrase"
        if status == "promoted"
        else "legacy_dictionary_lexical_unvalidated"
    }
    source_tokens = _source_tokens(field.text)
    if len(spec.tokens) == 1 and not entity_kind:
        status = "held"
        reasons.add("single_token_ambiguous")
    if (
        spec.rule_source == "dim_tag_v6.3_final"
        and resources.tag_phrase_owner_count.get(spec.tokens, 0) > 1
        and not spec.approved_for_promotion
    ):
        status = "held"
        reasons.add("shared_phrase_ambiguous")
    if (
        spec.negation_sensitive
        and _negated(
            field.text,
            source_tokens,
            token_start,
            resources.negation_tokens,
        )
    ):
        status = "held"
        reasons.add("negated_evidence")
    attributes = dict(spec.attributes)
    attributes.update(
        {
            "dim_tag_sha256": resources.dim_tag_sha256,
            "matched_phrase": spec.phrase,
            "product_entity_ledger_sha256": resources.product_entity_ledger_sha256,
            "registry_sha256": resources.registry_sha256,
            "rule_id": spec.rule_id,
            "rule_source": spec.rule_source,
        }
    )
    return _Candidate(
        fact_type=spec.fact_type,
        canonical_value=spec.canonical_value,
        attributes=tuple(sorted(attributes.items())),
        field=field.field,
        start=start,
        end=end,
        token_start=token_start,
        token_end=token_end,
        evidence_scope=field.evidence_scope,
        evidence_source_entity_id=field.evidence_source_entity_id,
        decision_status=status,
        reason_codes=tuple(sorted(reasons)),
    )


def _replace_decision(
    candidate: _Candidate,
    reason: str,
) -> _Candidate:
    return replace(
        candidate,
        decision_status="held",
        reason_codes=tuple(sorted(set(candidate.reason_codes) | {reason})),
    )


def _resolve_candidates(candidates: Iterable[_Candidate]) -> tuple[_Candidate, ...]:
    rows = list(candidates)
    # Prefer the longest governed alias when one entity alias nests another at
    # the same source position (for example Philips Avent / Avent).
    entity_types = {"entity_brand_fact", "entity_product_fact"}
    retained: list[_Candidate] = []
    for candidate in sorted(
        rows,
        key=lambda row: (
            row.field,
            row.start,
            -(row.end - row.start),
            row.fact_type,
            row.canonical_value,
        ),
    ):
        if candidate.fact_type in entity_types and any(
            prior.fact_type == candidate.fact_type
            and prior.field == candidate.field
            and prior.evidence_source_entity_id
            == candidate.evidence_source_entity_id
            and prior.start <= candidate.start
            and prior.end >= candidate.end
            and (prior.start, prior.end) != (candidate.start, candidate.end)
            for prior in retained
        ):
            continue
        retained.append(candidate)

    exact_groups: dict[tuple[str, str, int, int], list[int]] = {}
    for index, candidate in enumerate(retained):
        exact_groups.setdefault(
            (candidate.fact_type, candidate.field, candidate.start, candidate.end),
            [],
        ).append(index)
    replacements: dict[int, _Candidate] = {}
    for indexes in exact_groups.values():
        values = {retained[index].canonical_value for index in indexes}
        if len(values) > 1:
            approved = [
                index
                for index in indexes
                if dict(retained[index].attributes).get("promotion_approved")
                is True
            ]
            if len(approved) == 1:
                for index in indexes:
                    if index == approved[0]:
                        continue
                    replacements[index] = _replace_decision(
                        retained[index], "registry_resolved_shared_phrase"
                    )
            else:
                for index in indexes:
                    replacements[index] = _replace_decision(
                        retained[index], "semantic_conflict"
                    )

    sentiment_by_field: dict[str, list[int]] = {}
    for index, candidate in enumerate(retained):
        if candidate.fact_type == "entity_sentiment_fact":
            sentiment_by_field.setdefault(candidate.field, []).append(index)
    for indexes in sentiment_by_field.values():
        if len({retained[index].canonical_value for index in indexes}) > 1:
            for index in indexes:
                replacements[index] = _replace_decision(
                    replacements.get(index, retained[index]),
                    "sentiment_conflict",
                )

    deduplicated: dict[tuple[object, ...], _Candidate] = {}
    for index, candidate in enumerate(retained):
        value = replacements.get(index, candidate)
        key = (
            value.fact_type,
            value.canonical_value,
            value.field,
            value.start,
            value.end,
            value.evidence_source_entity_id,
        )
        previous = deduplicated.get(key)
        if previous is None:
            deduplicated[key] = value
        elif previous.attributes != value.attributes:
            deduplicated[key] = _replace_decision(
                previous, "duplicate_rule_conflict"
            )
    return tuple(
        sorted(
            deduplicated.values(),
            key=lambda row: (
                row.fact_type,
                row.canonical_value,
                row.field,
                row.start,
                row.end,
            ),
        )
    )


def _fact_id(fact: ClosedSetFact) -> str:
    payload = fact.as_dict()
    payload.pop("fact_id")
    return _sha(canonical_json_bytes(payload))


def build_closed_set_facts(
    voc: object,
    *,
    resources: ClosedSetResources,
    source_snapshot_id: str,
    created_at: str,
) -> tuple[ClosedSetFact, ...]:
    if not isinstance(resources, ClosedSetResources):
        raise ClosedSetFactError("closed-set resources are invalid")
    row = _voc(voc)
    voc_id, voc_type, entity_id, _post_id = _validate_voc(row)
    source_snapshot_id = _string(source_snapshot_id, "source snapshot ID")
    created_at = _created_at(created_at)
    candidates: list[_Candidate] = []

    entity_fields = _fields(row, allow_comment_context=True)
    for field in entity_fields:
        for occurrence in _occurrences(field, resources.momcozy_brand_specs):
            candidates.append(
                _candidate_from_occurrence(
                    field, occurrence, resources=resources, entity_kind=True
                )
            )
        for occurrence in _occurrences(field, resources.comparison_brand_specs):
            candidate = _candidate_from_occurrence(
                field, occurrence, resources=resources, entity_kind=True
            )
            spec = occurrence[0]
            if len(spec.tokens) == 1 and not _has_context(
                field,
                start=occurrence[1],
                end=occurrence[2],
                resources=resources,
            ):
                candidate = _replace_decision(
                    candidate, "single_token_entity_requires_context"
                )
            candidates.append(candidate)
        for occurrence in _occurrences(field, resources.product_specs):
            candidate = _candidate_from_occurrence(
                field, occurrence, resources=resources, entity_kind=True
            )
            spec = occurrence[0]
            if not spec.approved_for_promotion:
                if _has_context(
                    field,
                    start=occurrence[1],
                    end=occurrence[2],
                    resources=resources,
                ):
                    candidate = replace(
                        candidate,
                        decision_status="promoted",
                        reason_codes=("contextual_product_alias_with_context",),
                    )
                else:
                    candidate = _replace_decision(
                        candidate, "contextual_product_alias_requires_context"
                    )
            candidates.append(candidate)

    current_only_fields = _fields(row, allow_comment_context=False)
    semantic_by_type = {
        "entity_sentiment_fact": current_only_fields,
        "entity_problem_fact": current_only_fields,
        "entity_tag_fact": entity_fields,
    }
    for spec in resources.semantic_specs:
        for field in semantic_by_type[spec.fact_type]:
            for occurrence in _occurrences(field, (spec,)):
                candidates.append(
                    _candidate_from_occurrence(
                        field, occurrence, resources=resources
                    )
                )

    for field in current_only_fields:
        for occurrence in _occurrences(field, resources.tag_specs):
            candidates.append(
                _candidate_from_occurrence(
                    field, occurrence, resources=resources
                )
            )

    facts: list[ClosedSetFact] = []
    fields = row["analysis_fields"]
    for candidate in _resolve_candidates(candidates):
        evidence = fields[candidate.field][candidate.start : candidate.end]
        if not evidence:
            raise ClosedSetFactError("closed-set evidence is empty")
        evidence_hash = _sha(evidence.encode("utf-8"))
        context_refs: tuple[str, ...] = ()
        if candidate.evidence_scope == "cross_context":
            context_refs = (
                _sha(
                    canonical_json_bytes(
                        {
                            "end": candidate.end,
                            "evidence_field": candidate.field,
                            "evidence_source_entity_id": candidate.evidence_source_entity_id,
                            "evidence_text_sha256": evidence_hash,
                            "start": candidate.start,
                        }
                    )
                ),
            )
        fact = ClosedSetFact(
            fact_id="",
            canonical_entity_id=entity_id,
            voc_id=voc_id,
            voc_type=voc_type,
            fact_type=candidate.fact_type,
            canonical_value=candidate.canonical_value,
            attributes=dict(candidate.attributes),
            evidence_field=candidate.field,
            evidence_start=candidate.start,
            evidence_end=candidate.end,
            evidence_text_sha256=evidence_hash,
            evidence_scope=candidate.evidence_scope,
            evidence_source_entity_id=candidate.evidence_source_entity_id,
            context_evidence_refs=context_refs,
            decision_status=candidate.decision_status,
            reason_codes=candidate.reason_codes,
            dictionary_release_id=resources.dictionary_release_id,
            matcher_version=resources.matcher_version,
            normalizer_version=NORMALIZER_VERSION,
            source_snapshot_id=source_snapshot_id,
            created_at=created_at,
        )
        facts.append(replace(fact, fact_id=_fact_id(fact)))
    if len({fact.fact_id for fact in facts}) != len(facts):
        raise ClosedSetFactError("duplicate closed-set fact ID")
    facts.sort(
        key=lambda fact: (
            fact.voc_id,
            fact.fact_type,
            fact.canonical_value,
            fact.evidence_field,
            fact.evidence_start,
            fact.fact_id,
        )
    )
    return tuple(facts)


def materialize_closed_set_facts(
    vocs: Iterable[object],
    *,
    resources: ClosedSetResources,
    source_snapshot_id: str,
    created_at: str,
) -> tuple[ClosedSetFact, ...]:
    facts: list[ClosedSetFact] = []
    seen_vocs: set[str] = set()
    for raw in vocs:
        row = _voc(raw)
        voc_id = _string(row.get("voc_id"), "VOC ID")
        if voc_id in seen_vocs:
            raise ClosedSetFactError("duplicate closed-set VOC ID")
        seen_vocs.add(voc_id)
        facts.extend(
            build_closed_set_facts(
                row,
                resources=resources,
                source_snapshot_id=source_snapshot_id,
                created_at=created_at,
            )
        )
    if len({fact.fact_id for fact in facts}) != len(facts):
        raise ClosedSetFactError("duplicate materialized closed-set fact ID")
    facts.sort(key=lambda fact: (fact.voc_id, fact.fact_type, fact.fact_id))
    return tuple(facts)


def canonical_closed_set_fact_jsonl_bytes(
    facts: Iterable[ClosedSetFact],
) -> bytes:
    values = tuple(facts)
    if any(not isinstance(fact, ClosedSetFact) for fact in values):
        raise ClosedSetFactError("closed-set JSONL input is invalid")
    if len({fact.fact_id for fact in values}) != len(values):
        raise ClosedSetFactError("duplicate closed-set fact ID")
    ordered = sorted(values, key=lambda fact: (fact.voc_id, fact.fact_type, fact.fact_id))
    return b"".join(
        canonical_json_bytes(fact.as_dict()) + b"\n" for fact in ordered
    )


def group_closed_set_fact_tables(
    facts: Iterable[ClosedSetFact],
) -> dict[str, tuple[ClosedSetFact, ...]]:
    """Return the stable five-table partition consumed by the facts orchestrator."""
    grouped: dict[str, list[ClosedSetFact]] = {
        fact_type: [] for fact_type in CLOSED_SET_FACT_TYPES
    }
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, ClosedSetFact) or fact.fact_type not in grouped:
            raise ClosedSetFactError("closed-set fact partition input is invalid")
        if fact.fact_id in seen:
            raise ClosedSetFactError("duplicate closed-set fact partition ID")
        seen.add(fact.fact_id)
        grouped[fact.fact_type].append(fact)
    return {
        fact_type: tuple(
            sorted(rows, key=lambda fact: (fact.voc_id, fact.fact_id))
        )
        for fact_type, rows in grouped.items()
    }


def promoted_signal_facts_by_id(
    facts: Iterable[ClosedSetFact],
) -> dict[str, ClosedSetFact]:
    result: dict[str, ClosedSetFact] = {}
    for fact in facts:
        if not isinstance(fact, ClosedSetFact):
            raise ClosedSetFactError("closed-set signal registry input is invalid")
        if fact.decision_status != "promoted":
            continue
        if fact.fact_id in result:
            raise ClosedSetFactError("duplicate promoted signal fact ID")
        result[fact.fact_id] = fact
    return dict(sorted(result.items()))


def signal_evidence_refs(
    facts: Iterable[ClosedSetFact],
) -> tuple[dict[str, object], ...]:
    refs = [
        {
            "canonical_value": fact.canonical_value,
            "end": fact.evidence_end,
            "evidence_field": fact.evidence_field,
            "evidence_text_sha256": fact.evidence_text_sha256,
            "fact_type": fact.fact_type,
            "source_fact_id": fact.fact_id,
            "source_snapshot_id": fact.source_snapshot_id,
            "start": fact.evidence_start,
        }
        for fact in facts
        if isinstance(fact, ClosedSetFact) and fact.decision_status == "promoted"
    ]
    refs.sort(
        key=lambda row: (
            str(row["source_fact_id"]),
            str(row["fact_type"]),
            str(row["canonical_value"]),
        )
    )
    return tuple(refs)
