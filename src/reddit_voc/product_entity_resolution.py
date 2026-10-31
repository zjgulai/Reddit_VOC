from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Literal
import unicodedata

try:  # Python 3.11+
    from typing import Self
except ImportError:  # pragma: no cover - production runs 3.10
    # `typing.Self` arrived in 3.11. Production is 3.10.12 with no
    # typing_extensions installed, so the bare import made this module
    # unimportable there -- which is why the daily pipeline could never have
    # produced product_bindings even once it called the resolver. The
    # annotation is only ever used as `from_ledger(...) -> Self`, and
    # `from __future__ import annotations` keeps it a string, so a TypeVar
    # bound to the class is an exact stand-in.
    from typing import TypeVar

    Self = TypeVar("Self", bound="ProductEntityResolver")  # type: ignore[misc]


RESOLVER_VERSION = "product-entity-resolver-v1"

MatchType = Literal["strong_name", "contextual_alias", "category_context"]
BindingLevel = Literal["category", "product_family", "spu_exact"]
GovernanceStatus = Literal[
    "category_only",
    "exact_spu_approved",
    "family_only",
    "taxonomy_blocked",
]


@dataclass(frozen=True)
class ResolverMetadata:
    resolver_version: str
    ledger_version: str
    ledger_sha256: str

    def to_record(self) -> dict[str, str]:
        return {
            "resolver_version": self.resolver_version,
            "ledger_version": self.ledger_version,
            "ledger_sha256": self.ledger_sha256,
        }


@dataclass(frozen=True)
class EntityReference:
    entity_id: str
    name_en: str
    name_cn: str

    def to_record(self) -> dict[str, str]:
        return {
            "id": self.entity_id,
            "name_en": self.name_en,
            "name_cn": self.name_cn,
        }


@dataclass(frozen=True)
class ExactSpuReference:
    spu_id: str
    spu_name: str

    def to_record(self) -> dict[str, str]:
        return {"spu_id": self.spu_id, "spu_name": self.spu_name}


@dataclass(frozen=True)
class ProductBinding:
    brand_id: str
    category: EntityReference
    product_family: EntityReference | None
    exact_spu: ExactSpuReference | None
    binding_level: BindingLevel
    match_type: MatchType
    matched_alias: str
    governance_status: GovernanceStatus
    governance_reason: str | None

    def to_record(self) -> dict[str, object]:
        return {
            "brand_id": self.brand_id,
            "category": self.category.to_record(),
            "product_family": (
                self.product_family.to_record() if self.product_family else None
            ),
            "exact_spu": self.exact_spu.to_record() if self.exact_spu else None,
            "binding_level": self.binding_level,
            "match_type": self.match_type,
            "matched_alias": self.matched_alias,
            "governance_status": self.governance_status,
            "governance_reason": self.governance_reason,
        }


@dataclass(frozen=True)
class ResolutionResult:
    metadata: ResolverMetadata
    product_bindings: tuple[ProductBinding, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.to_record(),
            "product_bindings": [item.to_record() for item in self.product_bindings],
        }


@dataclass(frozen=True)
class CoverageLedger:
    input_record_count: int
    bound_record_count: int
    unbound_record_count: int
    multi_binding_record_count: int
    binding_count: int
    exact_spu_binding_count: int
    family_only_binding_count: int
    category_only_binding_count: int
    taxonomy_blocked_binding_count: int
    category_binding_counts: tuple[tuple[str, int], ...]
    family_binding_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not self.is_conserved:
            raise ValueError("product entity coverage ledger is not conserved")

    @property
    def is_conserved(self) -> bool:
        return all(
            (
                self.input_record_count
                == self.bound_record_count + self.unbound_record_count,
                self.binding_count
                == self.exact_spu_binding_count
                + self.family_only_binding_count
                + self.category_only_binding_count,
                self.binding_count == sum(dict(self.category_binding_counts).values()),
                self.binding_count
                == sum(dict(self.family_binding_counts).values())
                + self.category_only_binding_count,
                self.multi_binding_record_count <= self.bound_record_count,
                self.taxonomy_blocked_binding_count
                <= self.family_only_binding_count,
            )
        )

    def to_record(self) -> dict[str, object]:
        return {
            "input_record_count": self.input_record_count,
            "bound_record_count": self.bound_record_count,
            "unbound_record_count": self.unbound_record_count,
            "multi_binding_record_count": self.multi_binding_record_count,
            "binding_count": self.binding_count,
            "exact_spu_binding_count": self.exact_spu_binding_count,
            "family_only_binding_count": self.family_only_binding_count,
            "category_only_binding_count": self.category_only_binding_count,
            "taxonomy_blocked_binding_count": self.taxonomy_blocked_binding_count,
            "category_binding_counts": dict(self.category_binding_counts),
            "family_binding_counts": dict(self.family_binding_counts),
            "is_conserved": self.is_conserved,
        }


@dataclass(frozen=True)
class ResolutionBatch:
    metadata: ResolverMetadata
    results: tuple[ResolutionResult, ...]
    coverage: CoverageLedger

    def to_record(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.to_record(),
            "results": [
                {
                    "product_bindings": [
                        binding.to_record() for binding in result.product_bindings
                    ]
                }
                for result in self.results
            ],
            "coverage": self.coverage.to_record(),
        }


@dataclass(frozen=True)
class _AliasRule:
    value: str
    match_type: MatchType
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class _CategoryRule:
    reference: EntityReference
    context_patterns: tuple[tuple[str, re.Pattern[str]], ...]


@dataclass(frozen=True)
class _FamilyRule:
    reference: EntityReference
    category_id: str
    aliases: tuple[_AliasRule, ...]
    family_only_reason: str | None


@dataclass(frozen=True)
class _ExactSpuPolicy:
    spu_id: str
    spu_name: str
    mapping_status: str
    publish_exact_spu: bool
    governance_reason: str | None


@dataclass(frozen=True)
class _FamilyMatch:
    family: _FamilyRule
    selected_alias: _AliasRule
    first_position: int


@dataclass(frozen=True)
class _CategoryMatch:
    category: _CategoryRule
    matched_term: str
    first_position: int


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _compile_phrase(value: str) -> re.Pattern[str]:
    tokens = re.findall(r"[a-z0-9]+", _normalize(value))
    if not tokens:
        raise ValueError("entity alias must contain at least one alphanumeric token")
    body = r"[^a-z0-9]*".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)


def _as_object(value: object, *, location: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{location} must be an object")
    return value


def _as_object_list(value: object, *, location: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{location} must be a list")
    return [
        _as_object(item, location=f"{location}[{index}]")
        for index, item in enumerate(value)
    ]


def _required_string(record: dict[str, object], key: str, *, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(
    record: dict[str, object], key: str, *, location: str
) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{key} must be null or a non-empty string")
    return value.strip()


def _string_list(record: dict[str, object], key: str, *, location: str) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{location}.{key} must be a non-empty list")
    strings: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{location}.{key}[{index}] must be a non-empty string"
            )
        strings.append(item.strip())
    return strings


def _validate_keys(
    record: dict[str, object],
    *,
    allowed: set[str],
    required: set[str],
    location: str,
    subject: str | None = None,
) -> None:
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"{location} missing required fields: {missing}")
    unsupported = sorted(set(record) - allowed)
    if unsupported:
        label = subject or location
        raise ValueError(f"unsupported {label} fields: {unsupported}")


class ProductEntityResolver:
    """Deterministic, governed Momcozy category/family/SPU resolver.

    The resolver never retains or emits source text. Exact SPU output is possible
    only through a publishable entry in ``exact_spu_ledger``.
    """

    def __init__(
        self,
        *,
        metadata: ResolverMetadata,
        brand_id: str,
        brand_patterns: tuple[re.Pattern[str], ...],
        comparison_brand_patterns: tuple[re.Pattern[str], ...],
        context_window_chars: int,
        categories: dict[str, _CategoryRule],
        families: tuple[_FamilyRule, ...],
        exact_spu_policies: dict[str, _ExactSpuPolicy],
    ) -> None:
        self.metadata = metadata
        self._brand_id = brand_id
        self._brand_patterns = brand_patterns
        self._comparison_brand_patterns = comparison_brand_patterns
        self._context_window_chars = context_window_chars
        self._categories = categories
        self._families = families
        self._exact_spu_policies = exact_spu_policies

    @classmethod
    def from_ledger(cls, path: Path) -> Self:
        payload_bytes = path.read_bytes()
        try:
            parsed: object = json.loads(payload_bytes)
        except json.JSONDecodeError as exc:
            raise ValueError("product entity ledger is not valid JSON") from exc
        payload = _as_object(parsed, location="ledger")
        root_fields = {
            "schema_version",
            "ledger_version",
            "source_evidence",
            "brand",
            "comparison_brand_aliases",
            "context_window_chars",
            "categories",
            "families",
            "exact_spu_ledger",
        }
        _validate_keys(
            payload,
            allowed=root_fields,
            required=root_fields,
            location="ledger",
        )
        if _required_string(payload, "schema_version", location="ledger") != (
            "momcozy_product_entity_ledger_v1"
        ):
            raise ValueError("unsupported product entity ledger schema_version")
        ledger_version = _required_string(payload, "ledger_version", location="ledger")

        source_evidence = _as_object(
            payload["source_evidence"], location="ledger.source_evidence"
        )
        if not source_evidence or not all(
            isinstance(value, str) and value.strip()
            for value in source_evidence.values()
        ):
            raise ValueError("ledger.source_evidence must contain non-empty paths")

        brand = _as_object(payload["brand"], location="ledger.brand")
        _validate_keys(
            brand,
            allowed={"brand_id", "aliases"},
            required={"brand_id", "aliases"},
            location="ledger.brand",
        )
        brand_id = _required_string(brand, "brand_id", location="ledger.brand")
        brand_aliases = _string_list(brand, "aliases", location="ledger.brand")
        brand_patterns = tuple(_compile_phrase(alias) for alias in brand_aliases)
        comparison_brand_aliases = _string_list(
            payload,
            "comparison_brand_aliases",
            location="ledger",
        )
        if set(map(_normalize, brand_aliases)) & set(
            map(_normalize, comparison_brand_aliases)
        ):
            raise ValueError("target and comparison brand aliases must not overlap")
        comparison_brand_patterns = tuple(
            _compile_phrase(alias) for alias in comparison_brand_aliases
        )

        context_window_chars = payload["context_window_chars"]
        if (
            isinstance(context_window_chars, bool)
            or not isinstance(context_window_chars, int)
            or context_window_chars < 16
        ):
            raise ValueError("ledger.context_window_chars must be an integer >= 16")

        categories: dict[str, _CategoryRule] = {}
        category_fields = {
            "category_id",
            "name_en",
            "name_cn",
            "context_terms",
        }
        for index, record in enumerate(
            _as_object_list(payload["categories"], location="ledger.categories")
        ):
            location = f"ledger.categories[{index}]"
            _validate_keys(
                record,
                allowed=category_fields,
                required=category_fields,
                location=location,
            )
            category_id = _required_string(record, "category_id", location=location)
            if category_id in categories:
                raise ValueError(f"duplicate category_id: {category_id}")
            reference = EntityReference(
                entity_id=category_id,
                name_en=_required_string(record, "name_en", location=location),
                name_cn=_required_string(record, "name_cn", location=location),
            )
            categories[category_id] = _CategoryRule(
                reference=reference,
                context_patterns=tuple(
                    (term, _compile_phrase(term))
                    for term in _string_list(
                        record, "context_terms", location=location
                    )
                ),
            )
        if not categories:
            raise ValueError("ledger.categories must not be empty")

        families: list[_FamilyRule] = []
        family_ids: set[str] = set()
        family_fields = {
            "family_id",
            "name_en",
            "name_cn",
            "category_id",
            "family_only_reason",
            "aliases",
        }
        alias_fields = {"value", "match_type"}
        for index, record in enumerate(
            _as_object_list(payload["families"], location="ledger.families")
        ):
            location = f"ledger.families[{index}]"
            _validate_keys(
                record,
                allowed=family_fields,
                required=family_fields,
                location=location,
                subject="family",
            )
            family_id = _required_string(record, "family_id", location=location)
            if family_id in family_ids:
                raise ValueError(f"duplicate family_id: {family_id}")
            family_ids.add(family_id)
            category_id = _required_string(record, "category_id", location=location)
            if category_id not in categories:
                raise ValueError(f"unknown category_id for {family_id}: {category_id}")

            aliases: list[_AliasRule] = []
            alias_keys: set[tuple[str, str]] = set()
            for alias_index, alias_record in enumerate(
                _as_object_list(record["aliases"], location=f"{location}.aliases")
            ):
                alias_location = f"{location}.aliases[{alias_index}]"
                _validate_keys(
                    alias_record,
                    allowed=alias_fields,
                    required=alias_fields,
                    location=alias_location,
                )
                value = _required_string(alias_record, "value", location=alias_location)
                raw_match_type = _required_string(
                    alias_record, "match_type", location=alias_location
                )
                if raw_match_type not in {"strong_name", "contextual_alias"}:
                    raise ValueError(f"unsupported alias match_type: {raw_match_type}")
                match_type: MatchType = raw_match_type  # type: ignore[assignment]
                alias_key = (_normalize(value), match_type)
                if alias_key in alias_keys:
                    raise ValueError(f"duplicate alias for {family_id}: {value}")
                alias_keys.add(alias_key)
                aliases.append(
                    _AliasRule(
                        value=value,
                        match_type=match_type,
                        pattern=_compile_phrase(value),
                    )
                )
            if not aliases:
                raise ValueError(f"family {family_id} must define aliases")
            families.append(
                _FamilyRule(
                    reference=EntityReference(
                        entity_id=family_id,
                        name_en=_required_string(record, "name_en", location=location),
                        name_cn=_required_string(record, "name_cn", location=location),
                    ),
                    category_id=category_id,
                    aliases=tuple(aliases),
                    family_only_reason=_optional_string(
                        record, "family_only_reason", location=location
                    ),
                )
            )
        if not families:
            raise ValueError("ledger.families must not be empty")

        exact_spu_policies: dict[str, _ExactSpuPolicy] = {}
        published_spu_ids: set[str] = set()
        exact_fields = {
            "family_id",
            "spu_id",
            "spu_name",
            "mapping_status",
            "publish_exact_spu",
            "governance_reason",
            "evidence",
        }
        for index, record in enumerate(
            _as_object_list(
                payload["exact_spu_ledger"], location="ledger.exact_spu_ledger"
            )
        ):
            location = f"ledger.exact_spu_ledger[{index}]"
            _validate_keys(
                record,
                allowed=exact_fields,
                required=exact_fields,
                location=location,
            )
            family_id = _required_string(record, "family_id", location=location)
            if family_id not in family_ids:
                raise ValueError(f"exact SPU policy references unknown family: {family_id}")
            if family_id in exact_spu_policies:
                raise ValueError(f"duplicate exact SPU policy for family: {family_id}")
            spu_id = _required_string(record, "spu_id", location=location)
            spu_name = _required_string(record, "spu_name", location=location)
            mapping_status = _required_string(
                record, "mapping_status", location=location
            )
            publish_exact_spu = record["publish_exact_spu"]
            if not isinstance(publish_exact_spu, bool):
                raise ValueError(f"{location}.publish_exact_spu must be boolean")
            governance_reason = _optional_string(
                record, "governance_reason", location=location
            )
            _required_string(record, "evidence", location=location)

            if publish_exact_spu:
                if mapping_status != "approved_for_publication":
                    raise ValueError(
                        "publishable exact SPU requires approved_for_publication"
                    )
                if governance_reason is not None:
                    raise ValueError("publishable exact SPU cannot have a block reason")
                if spu_id in published_spu_ids:
                    raise ValueError(f"published exact SPU is not unique: {spu_id}")
                published_spu_ids.add(spu_id)
            elif not governance_reason:
                raise ValueError("blocked exact SPU policy requires governance_reason")

            exact_spu_policies[family_id] = _ExactSpuPolicy(
                spu_id=spu_id,
                spu_name=spu_name,
                mapping_status=mapping_status,
                publish_exact_spu=publish_exact_spu,
                governance_reason=governance_reason,
            )

        for family in families:
            policy = exact_spu_policies.get(family.reference.entity_id)
            if policy is None and not family.family_only_reason:
                raise ValueError(
                    f"family without exact SPU requires family_only_reason: "
                    f"{family.reference.entity_id}"
                )
            if policy and policy.publish_exact_spu and family.family_only_reason:
                raise ValueError(
                    f"publishable family cannot also be family-only: "
                    f"{family.reference.entity_id}"
                )

        metadata = ResolverMetadata(
            resolver_version=RESOLVER_VERSION,
            ledger_version=ledger_version,
            ledger_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )
        return cls(
            metadata=metadata,
            brand_id=brand_id,
            brand_patterns=brand_patterns,
            comparison_brand_patterns=comparison_brand_patterns,
            context_window_chars=context_window_chars,
            categories=categories,
            families=tuple(families),
            exact_spu_policies=exact_spu_policies,
        )

    def _context_is_present(
        self,
        normalized_text: str,
        *,
        match_start: int,
        match_end: int,
        category_id: str,
    ) -> bool:
        window_start = max(0, match_start - self._context_window_chars)
        window_end = min(
            len(normalized_text), match_end + self._context_window_chars
        )
        window = normalized_text[window_start:window_end]
        return any(pattern.search(window) for pattern in self._brand_patterns) or any(
            pattern.search(window)
            for _, pattern in self._categories[category_id].context_patterns
        )

    def _same_controlled_domain(
        self,
        normalized_text: str,
        *,
        brand_start: int,
        brand_end: int,
        category_start: int,
        category_end: int,
    ) -> bool:
        gap_start, gap_end = self._span_gap(
            brand_start,
            brand_end,
            category_start,
            category_end,
        )
        if gap_end - gap_start > self._context_window_chars:
            return False
        between = normalized_text[gap_start:gap_end]
        return re.search(r"[.!?;\n]", between) is None

    @staticmethod
    def _span_gap(
        first_start: int,
        first_end: int,
        second_start: int,
        second_end: int,
    ) -> tuple[int, int]:
        if first_end <= second_start:
            return first_end, second_start
        if second_end <= first_start:
            return second_end, first_start
        return 0, 0

    def _category_is_attributed_to_target_brand(
        self,
        normalized_text: str,
        *,
        category_start: int,
        category_end: int,
        target_brand_spans: list[tuple[int, int]],
        comparison_brand_spans: list[tuple[int, int]],
    ) -> bool:
        target_distances = [
            gap_end - gap_start
            for brand_start, brand_end in target_brand_spans
            if self._same_controlled_domain(
                normalized_text,
                brand_start=brand_start,
                brand_end=brand_end,
                category_start=category_start,
                category_end=category_end,
            )
            for gap_start, gap_end in (
                self._span_gap(
                    brand_start,
                    brand_end,
                    category_start,
                    category_end,
                ),
            )
        ]
        if not target_distances:
            return False
        comparison_distances = [
            gap_end - gap_start
            for brand_start, brand_end in comparison_brand_spans
            if self._same_controlled_domain(
                normalized_text,
                brand_start=brand_start,
                brand_end=brand_end,
                category_start=category_start,
                category_end=category_end,
            )
            for gap_start, gap_end in (
                self._span_gap(
                    brand_start,
                    brand_end,
                    category_start,
                    category_end,
                ),
            )
        ]
        return not comparison_distances or min(target_distances) < min(
            comparison_distances
        )

    def _match_categories(self, normalized_text: str) -> list[_CategoryMatch]:
        brand_spans = [
            (match.start(), match.end())
            for pattern in self._brand_patterns
            for match in pattern.finditer(normalized_text)
        ]
        if not brand_spans:
            return []
        comparison_brand_spans = [
            (match.start(), match.end())
            for pattern in self._comparison_brand_patterns
            for match in pattern.finditer(normalized_text)
        ]

        matches: list[_CategoryMatch] = []
        for category in self._categories.values():
            candidates: list[tuple[str, int]] = []
            for term, pattern in category.context_patterns:
                for category_match in pattern.finditer(normalized_text):
                    if self._category_is_attributed_to_target_brand(
                        normalized_text,
                        category_start=category_match.start(),
                        category_end=category_match.end(),
                        target_brand_spans=brand_spans,
                        comparison_brand_spans=comparison_brand_spans,
                    ):
                        candidates.append((term, category_match.start()))
            if not candidates:
                continue
            selected_term, selected_position = min(
                candidates,
                key=lambda candidate: (
                    candidate[1],
                    -len(candidate[0]),
                    candidate[0].casefold(),
                ),
            )
            matches.append(
                _CategoryMatch(
                    category=category,
                    matched_term=selected_term,
                    first_position=selected_position,
                )
            )
        return matches

    def _match_family(
        self, normalized_text: str, family: _FamilyRule
    ) -> _FamilyMatch | None:
        candidates: list[tuple[_AliasRule, int]] = []
        for alias in family.aliases:
            for match in alias.pattern.finditer(normalized_text):
                if alias.match_type == "strong_name" or self._context_is_present(
                    normalized_text,
                    match_start=match.start(),
                    match_end=match.end(),
                    category_id=family.category_id,
                ):
                    candidates.append((alias, match.start()))
        if not candidates:
            return None
        first_position = min(position for _, position in candidates)
        selected_alias, _ = min(
            candidates,
            key=lambda candidate: (
                0 if candidate[0].match_type == "strong_name" else 1,
                -len(candidate[0].value),
                candidate[1],
                candidate[0].value.casefold(),
            ),
        )
        return _FamilyMatch(
            family=family,
            selected_alias=selected_alias,
            first_position=first_position,
        )

    def _binding_from_match(self, matched: _FamilyMatch) -> ProductBinding:
        family_id = matched.family.reference.entity_id
        policy = self._exact_spu_policies.get(family_id)
        if policy and policy.publish_exact_spu:
            exact_spu = ExactSpuReference(
                spu_id=policy.spu_id,
                spu_name=policy.spu_name,
            )
            binding_level: BindingLevel = "spu_exact"
            governance_status: GovernanceStatus = "exact_spu_approved"
            governance_reason = None
        else:
            exact_spu = None
            binding_level = "product_family"
            governance_reason = (
                policy.governance_reason
                if policy is not None
                else matched.family.family_only_reason
            )
            governance_status = (
                "taxonomy_blocked"
                if governance_reason and governance_reason.startswith("taxonomy_drift_")
                else "family_only"
            )
        return ProductBinding(
            brand_id=self._brand_id,
            category=self._categories[matched.family.category_id].reference,
            product_family=matched.family.reference,
            exact_spu=exact_spu,
            binding_level=binding_level,
            match_type=matched.selected_alias.match_type,
            matched_alias=matched.selected_alias.value,
            governance_status=governance_status,
            governance_reason=governance_reason,
        )

    def _binding_from_category(self, matched: _CategoryMatch) -> ProductBinding:
        return ProductBinding(
            brand_id=self._brand_id,
            category=matched.category.reference,
            product_family=None,
            exact_spu=None,
            binding_level="category",
            match_type="category_context",
            matched_alias=matched.matched_term,
            governance_status="category_only",
            governance_reason=None,
        )

    def resolve(self, text: str) -> ResolutionResult:
        if not isinstance(text, str):
            raise TypeError("product entity source text must be str")
        normalized_text = _normalize(text)
        family_matches = [
            matched
            for family in self._families
            if (matched := self._match_family(normalized_text, family)) is not None
        ]
        family_category_ids = {
            matched.family.category_id for matched in family_matches
        }
        category_matches = [
            matched
            for matched in self._match_categories(normalized_text)
            if matched.category.reference.entity_id not in family_category_ids
        ]
        positioned_bindings = [
            (
                matched.first_position,
                matched.family.reference.entity_id,
                self._binding_from_match(matched),
            )
            for matched in family_matches
        ] + [
            (
                matched.first_position,
                matched.category.reference.entity_id,
                self._binding_from_category(matched),
            )
            for matched in category_matches
        ]
        positioned_bindings.sort(key=lambda item: (item[0], item[1]))
        return ResolutionResult(
            metadata=self.metadata,
            product_bindings=tuple(item[2] for item in positioned_bindings),
        )

    def resolve_many(self, texts: Iterable[str]) -> ResolutionBatch:
        results = tuple(self.resolve(text) for text in texts)
        all_bindings = [
            binding
            for result in results
            for binding in result.product_bindings
        ]
        bound_record_count = sum(bool(result.product_bindings) for result in results)
        exact_spu_binding_count = sum(
            binding.binding_level == "spu_exact" for binding in all_bindings
        )
        family_only_binding_count = sum(
            binding.binding_level == "product_family" for binding in all_bindings
        )
        category_only_binding_count = sum(
            binding.binding_level == "category" for binding in all_bindings
        )
        coverage = CoverageLedger(
            input_record_count=len(results),
            bound_record_count=bound_record_count,
            unbound_record_count=len(results) - bound_record_count,
            multi_binding_record_count=sum(
                len(result.product_bindings) > 1 for result in results
            ),
            binding_count=len(all_bindings),
            exact_spu_binding_count=exact_spu_binding_count,
            family_only_binding_count=family_only_binding_count,
            category_only_binding_count=category_only_binding_count,
            taxonomy_blocked_binding_count=sum(
                binding.governance_status == "taxonomy_blocked"
                for binding in all_bindings
            ),
            category_binding_counts=tuple(
                sorted(
                    Counter(
                        binding.category.entity_id for binding in all_bindings
                    ).items()
                )
            ),
            family_binding_counts=tuple(
                sorted(
                    Counter(
                        binding.product_family.entity_id
                        for binding in all_bindings
                        if binding.product_family is not None
                    ).items()
                )
            ),
        )
        return ResolutionBatch(
            metadata=self.metadata,
            results=results,
            coverage=coverage,
        )
