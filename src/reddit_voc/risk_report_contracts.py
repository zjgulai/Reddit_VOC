"""Deterministic Momcozy risk command-center and report contracts.

This module consumes already-enriched, privacy-minimized snapshot records.  It
never copies post/comment text or author fields into its output.  Comparisons
are fail-closed: observations may still be emitted, but deltas are null unless
the supplied coverage ledger proves the two windows comparable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import html
import re
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo


TIMEZONE_NAME = "Asia/Shanghai"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
PERIODS = ("daily", "weekly", "monthly")
PRIORITIES = ("P0", "P1", "P2", "P3")
BRAND_BINDINGS = {
    "momcozy_sentence_bound",
    "momcozy_entity_reviewed",
    "competitor_sentence_bound",
    "multi_brand_context",
    "brand_unbound",
}
MOMCOZY_BINDINGS = {
    "momcozy_sentence_bound",
    "momcozy_entity_reviewed",
}
COMMENT_COVERAGE = {
    "post_only",
    "observed_first_page",
    "thread_complete",
}
SENTIMENTS = ("positive", "neutral", "negative")
COMPARISON_STATUSES = {
    "comparable",
    "provisional_observed_sample",
    "unavailable",
}
LEGACY_INSIGHTS_FIELDS = (
    "headline",
    "signals",
    "reference_dimensions",
    "held_tags",
)
THEME_EVIDENCE_REF_LIMIT = 20

Period = Literal["daily", "weekly", "monthly"]
EntityType = Literal["post", "comment"]
MetricName = Literal["observed_count", "negative_evidence_share"]
ComparisonStatus = Literal[
    "comparable", "provisional_observed_sample", "unavailable"
]


class InputContractError(ValueError):
    """Raised when the enriched snapshot cannot support the contract safely."""

    def __init__(
        self,
        message: str,
        *,
        missing_fields: Iterable[str] = (),
        invalid_fields: Iterable[str] = (),
    ) -> None:
        self.missing_fields = tuple(sorted(set(missing_fields)))
        self.invalid_fields = tuple(sorted(set(invalid_fields)))
        details: list[str] = []
        if self.missing_fields:
            details.append(f"missing={list(self.missing_fields)}")
        if self.invalid_fields:
            details.append(f"invalid={list(self.invalid_fields)}")
        suffix = f" ({'; '.join(details)})" if details else ""
        super().__init__(message + suffix)


@dataclass(frozen=True)
class PeriodWindow:
    start_utc: datetime
    end_utc: datetime
    start_local: datetime
    end_local: datetime

    def __post_init__(self) -> None:
        if self.start_utc.tzinfo is None or self.end_utc.tzinfo is None:
            raise ValueError("period windows must be timezone-aware")
        if self.start_utc >= self.end_utc:
            raise ValueError("period window must be non-empty")

    @property
    def key(self) -> tuple[str, str]:
        return (_iso_utc(self.start_utc), _iso_utc(self.end_utc))

    def to_record(self) -> dict[str, object]:
        return {
            "start_utc": _iso_utc(self.start_utc),
            "end_utc": _iso_utc(self.end_utc),
            "start_local": self.start_local.isoformat(),
            "end_local": self.end_local.isoformat(),
            "timezone": TIMEZONE_NAME,
            "interval": "half_open",
            "is_closed": True,
        }


@dataclass(frozen=True)
class PeriodWindowSet:
    current: PeriodWindow
    previous: PeriodWindow
    year_over_year: PeriodWindow
    trend: tuple[PeriodWindow, ...]


@dataclass(frozen=True)
class _Entity:
    entity_type: EntityType
    entity_id: str
    post_id: str
    event_created_at_utc: datetime
    subreddit: str
    permalink: str | None
    brand_binding: str
    brand_names: tuple[str, ...]
    product_bindings: tuple[dict[str, object], ...]
    sentiment: str
    topic: str | None
    pain_points: tuple[str, ...]
    tag_ids: tuple[str, ...]
    tag_brand_bindings: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _RiskFact:
    entity: _Entity
    tag_id: str
    rule: dict[str, object]
    brand_binding: str


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise InputContractError(
            "datetime input contract failed", invalid_fields=[field]
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputContractError(
            "datetime input contract failed", invalid_fields=[field]
        ) from exc
    if parsed.tzinfo is None:
        raise InputContractError(
            "datetime input contract failed", invalid_fields=[field]
        )
    return parsed.astimezone(timezone.utc)


def _local_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=TIMEZONE)


def _window_from_local(start: datetime, end: datetime) -> PeriodWindow:
    return PeriodWindow(
        start_utc=start.astimezone(timezone.utc),
        end_utc=end.astimezone(timezone.utc),
        start_local=start,
        end_local=end,
    )


def _shift_year(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # Feb 29 compares to the last valid day of February.
        return value.replace(year=value.year + years, day=28)


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + (value.month - 1) + months
    year, month_zero = divmod(absolute, 12)
    return date(year, month_zero + 1, 1)


def _daily_window(value: date) -> PeriodWindow:
    start = _local_midnight(value)
    return _window_from_local(start, start + timedelta(days=1))


def _weekly_window(start_date: date) -> PeriodWindow:
    start = _local_midnight(start_date)
    return _window_from_local(start, start + timedelta(days=7))


def _monthly_window(month_start: date) -> PeriodWindow:
    start = _local_midnight(month_start)
    end = _local_midnight(_add_months(month_start, 1))
    return _window_from_local(start, end)


def build_period_windows(as_of_utc: datetime) -> dict[Period, PeriodWindowSet]:
    """Return latest fully closed local day/week/month and comparison windows."""

    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    local_date = as_of_utc.astimezone(TIMEZONE).date()

    daily_date = local_date - timedelta(days=1)
    daily_current = _daily_window(daily_date)
    daily_previous = _daily_window(daily_date - timedelta(days=1))
    daily_yoy = _daily_window(_shift_year(daily_date, -1))
    daily_trend = tuple(
        _daily_window(daily_date - timedelta(days=offset))
        for offset in reversed(range(14))
    )

    current_week_start = local_date - timedelta(days=local_date.weekday())
    weekly_start = current_week_start - timedelta(days=7)
    weekly_current = _weekly_window(weekly_start)
    weekly_previous = _weekly_window(weekly_start - timedelta(days=7))
    weekly_yoy = _weekly_window(weekly_start - timedelta(days=364))
    weekly_trend = tuple(
        _weekly_window(weekly_start - timedelta(days=7 * offset))
        for offset in reversed(range(13))
    )

    current_month_start = local_date.replace(day=1)
    monthly_start = _add_months(current_month_start, -1)
    monthly_current = _monthly_window(monthly_start)
    monthly_previous = _monthly_window(_add_months(monthly_start, -1))
    monthly_yoy = _monthly_window(_shift_year(monthly_start, -1))
    monthly_trend = tuple(
        _monthly_window(_add_months(monthly_start, -offset))
        for offset in reversed(range(12))
    )

    return {
        "daily": PeriodWindowSet(
            current=daily_current,
            previous=daily_previous,
            year_over_year=daily_yoy,
            trend=daily_trend,
        ),
        "weekly": PeriodWindowSet(
            current=weekly_current,
            previous=weekly_previous,
            year_over_year=weekly_yoy,
            trend=weekly_trend,
        ),
        "monthly": PeriodWindowSet(
            current=monthly_current,
            previous=monthly_previous,
            year_over_year=monthly_yoy,
            trend=monthly_trend,
        ),
    }


def _normalise_brand(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _is_momcozy_name(value: str) -> bool:
    return _normalise_brand(value) in {"momcozy", "mcozy"}


def _has_momcozy_sentence_binding(
    source_text: str,
    evidence_keywords: Sequence[str],
) -> bool:
    """Bind only when a governed Momcozy alias and tag evidence share a sentence."""

    aliases = ("momcozy", "mcozy")
    keywords = tuple(
        keyword.casefold().strip() for keyword in evidence_keywords if keyword.strip()
    )
    if not keywords:
        return False
    sentences = re.split(
        r"(?<=[.!?])\s+|\n+", html.unescape(source_text).casefold()
    )
    return any(
        any(alias in sentence for alias in aliases)
        and any(keyword in sentence for keyword in keywords)
        for sentence in sentences
        if sentence.strip()
    )


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InputContractError(
            "object input contract failed", invalid_fields=[field]
        )
    return cast(dict[str, object], value)


def _string_list(value: object, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise InputContractError(
            "list input contract failed", invalid_fields=[field]
        )
    if not allow_empty and not value:
        raise InputContractError(
            "list input contract failed", invalid_fields=[field]
        )
    output: list[str] = []
    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            raise InputContractError(
                "list input contract failed",
                invalid_fields=[f"{field}[{index}]"],
            )
        output.append(cast(str, item).strip())
    return output


def _validate_product_binding(value: object, *, field: str) -> dict[str, object]:
    binding = _mapping(value, field=field)
    required = {
        "brand_id",
        "category",
        "product_family",
        "exact_spu",
        "binding_level",
        "governance_status",
    }
    missing = [f"{field}.{name}" for name in sorted(required - set(binding))]
    if missing:
        raise InputContractError(
            "product binding input contract failed", missing_fields=missing
        )
    if not _is_non_empty_string(binding["brand_id"]):
        raise InputContractError(
            "product binding input contract failed",
            invalid_fields=[f"{field}.brand_id"],
        )
    category = _mapping(binding["category"], field=f"{field}.category")
    for key in ("id", "name_en", "name_cn"):
        if not _is_non_empty_string(category.get(key)):
            raise InputContractError(
                "product binding input contract failed",
                invalid_fields=[f"{field}.category.{key}"],
            )
    level = binding["binding_level"]
    governance = binding["governance_status"]
    if level not in {"category", "product_family", "spu_exact"}:
        raise InputContractError(
            "product binding input contract failed",
            invalid_fields=[f"{field}.binding_level"],
        )
    if governance not in {
        "category_only",
        "exact_spu_approved",
        "family_only",
        "taxonomy_blocked",
    }:
        raise InputContractError(
            "product binding input contract failed",
            invalid_fields=[f"{field}.governance_status"],
        )
    family_value = binding["product_family"]
    exact = binding["exact_spu"]
    if level == "category":
        if governance != "category_only" or family_value is not None or exact is not None:
            raise InputContractError(
                "category-only publication gate failed",
                invalid_fields=[f"{field}.product_family"],
            )
    else:
        if not isinstance(family_value, dict):
            raise InputContractError(
                "product family binding gate failed",
                invalid_fields=[f"{field}.product_family"],
            )
        family = _mapping(family_value, field=f"{field}.product_family")
        for key in ("id", "name_en", "name_cn"):
            if not _is_non_empty_string(family.get(key)):
                raise InputContractError(
                    "product binding input contract failed",
                    invalid_fields=[f"{field}.product_family.{key}"],
                )
    if level == "spu_exact":
        if governance != "exact_spu_approved" or not isinstance(exact, dict):
            raise InputContractError(
                "exact SPU publication gate failed",
                invalid_fields=[f"{field}.exact_spu"],
            )
        exact_mapping = _mapping(exact, field=f"{field}.exact_spu")
        for key in ("spu_id", "spu_name"):
            if not _is_non_empty_string(exact_mapping.get(key)):
                raise InputContractError(
                    "exact SPU publication gate failed",
                    invalid_fields=[f"{field}.exact_spu.{key}"],
                )
    elif level == "product_family" and exact is not None:
        raise InputContractError(
            "family-only binding cannot publish exact SPU",
            invalid_fields=[f"{field}.exact_spu"],
        )
    return binding


def _record_missing_fields(
    record: Mapping[str, object],
    *,
    prefix: str,
    is_post: bool,
) -> list[str]:
    required = {
        "event_created_at_utc",
        "brand_binding",
        "mentioned_brands",
        "product_bindings",
        "analysis",
        "tagging",
    }
    required.add("post_id" if is_post else "comment_id")
    if is_post:
        required.update(
            {"subreddit", "comment_coverage_status", "title", "content"}
        )
    else:
        required.update({"post_id", "include_in_voc_metrics", "body"})
    return [f"{prefix}.{field}" for field in sorted(required - set(record))]


def _validate_base_identity(value: Mapping[str, object]) -> None:
    missing = [
        field
        for field in ("dataset_version", "manifest_sha256", "generated_at_utc")
        if field not in value
    ]
    if missing:
        raise InputContractError(
            "base identity input contract failed",
            missing_fields=[f"base_identity.{field}" for field in missing],
        )
    if not _is_non_empty_string(value["dataset_version"]):
        raise InputContractError(
            "base identity input contract failed",
            invalid_fields=["base_identity.dataset_version"],
        )
    manifest_sha = value["manifest_sha256"]
    if not isinstance(manifest_sha, str) or re.fullmatch(r"[0-9a-f]{64}", manifest_sha) is None:
        raise InputContractError(
            "base identity input contract failed",
            invalid_fields=["base_identity.manifest_sha256"],
        )
    _parse_utc(value["generated_at_utc"], field="base_identity.generated_at_utc")


def _tag_rules(tag_dictionary: Mapping[str, object]) -> dict[str, dict[str, object]]:
    raw_rules = tag_dictionary.get("rules")
    if not isinstance(raw_rules, list):
        raise InputContractError(
            "tag dictionary input contract failed",
            invalid_fields=["tag_dictionary.rules"],
        )
    required = {
        "tag_id",
        "name_cn",
        "name_en",
        "theme",
        "sentiment",
        "default_priority",
        "risk_level",
        "problem_type",
        "intent_type",
        "story_lines",
        "business_impact",
        "dept_owner",
        "biz_action",
    }
    rules: dict[str, dict[str, object]] = {}
    for index, value in enumerate(raw_rules):
        rule = _mapping(value, field=f"tag_dictionary.rules[{index}]")
        missing = required - set(rule)
        if missing:
            raise InputContractError(
                "tag dictionary input contract failed",
                missing_fields=[
                    f"tag_dictionary.rules[{index}].{field}"
                    for field in sorted(missing)
                ],
            )
        tag_id = rule["tag_id"]
        if not _is_non_empty_string(tag_id):
            raise InputContractError(
                "tag dictionary input contract failed",
                invalid_fields=[f"tag_dictionary.rules[{index}].tag_id"],
            )
        tag_id_string = cast(str, tag_id)
        if tag_id_string in rules:
            raise InputContractError(
                "tag dictionary input contract failed",
                invalid_fields=[f"duplicate_tag_id:{tag_id_string}"],
            )
        rules[tag_id_string] = rule
    return rules


def _semantic_sets(
    semantic_governance: Mapping[str, object],
    *,
    rules: Mapping[str, object],
) -> tuple[set[str], set[str], str]:
    version = semantic_governance.get("governance_version")
    if not _is_non_empty_string(version):
        raise InputContractError(
            "semantic governance input contract failed",
            invalid_fields=["semantic_governance.governance_version"],
        )
    promoted = set(
        _string_list(
            semantic_governance.get("promoted_tag_ids"),
            field="semantic_governance.promoted_tag_ids",
            allow_empty=True,
        )
    )
    held = set(
        _string_list(
            semantic_governance.get("held_tag_ids"),
            field="semantic_governance.held_tag_ids",
            allow_empty=True,
        )
    )
    if promoted & held:
        raise InputContractError(
            "semantic governance input contract failed",
            invalid_fields=["semantic_governance.promoted_and_held_overlap"],
        )
    unknown = sorted((promoted | held) - set(rules))
    if unknown:
        raise InputContractError(
            "semantic governance input contract failed",
            invalid_fields=[f"semantic_governance.unknown_tag_id:{item}" for item in unknown],
        )
    return promoted, held, cast(str, version)


def _validate_risk_policy(
    value: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    required = {
        "schema_version",
        "policy_version",
        "status",
        "minimum_observed_entities",
        "minimum_distinct_posts",
        "minimum_communities",
        "minimum_brand_binding_rate",
    }
    missing = required - set(value)
    if missing:
        raise InputContractError(
            "risk theme gate policy input contract failed",
            missing_fields=[f"risk_gate_policy.{field}" for field in sorted(missing)],
        )
    if value["schema_version"] != "reddit_voc_risk_theme_gate_policy_v1":
        raise InputContractError(
            "risk theme gate policy input contract failed",
            invalid_fields=["risk_gate_policy.schema_version"],
        )
    if value["status"] not in {"frozen", "draft"}:
        raise InputContractError(
            "risk theme gate policy input contract failed",
            invalid_fields=["risk_gate_policy.status"],
        )
    if not _is_non_empty_string(value["policy_version"]):
        raise InputContractError(
            "risk theme gate policy input contract failed",
            invalid_fields=["risk_gate_policy.policy_version"],
        )
    for field in (
        "minimum_observed_entities",
        "minimum_distinct_posts",
        "minimum_communities",
    ):
        item = value[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise InputContractError(
                "risk theme gate policy input contract failed",
                invalid_fields=[f"risk_gate_policy.{field}"],
            )
    rate = value["minimum_brand_binding_rate"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
        raise InputContractError(
            "risk theme gate policy input contract failed",
            invalid_fields=["risk_gate_policy.minimum_brand_binding_rate"],
        )
    return dict(value)


def _normalise_entity_records(
    posts: Sequence[Mapping[str, object]],
    comments: Sequence[Mapping[str, object]],
    *,
    rules: Mapping[str, dict[str, object]],
    promoted_tag_ids: set[str],
) -> tuple[list[_Entity], dict[str, str]]:
    missing: list[str] = []
    invalid: list[str] = []
    for index, record in enumerate(posts):
        missing.extend(
            _record_missing_fields(record, prefix=f"posts[{index}]", is_post=True)
        )
    for index, record in enumerate(comments):
        required_comment_fields = _record_missing_fields(
            record, prefix=f"comments[{index}]", is_post=False
        )
        if record.get("include_in_voc_metrics") is False:
            optional_for_excluded = {
                f"comments[{index}].brand_binding",
                f"comments[{index}].mentioned_brands",
                f"comments[{index}].product_bindings",
                f"comments[{index}].analysis",
                f"comments[{index}].tagging",
                f"comments[{index}].body",
            }
            required_comment_fields = [
                field for field in required_comment_fields if field not in optional_for_excluded
            ]
        missing.extend(required_comment_fields)
    if missing:
        raise InputContractError(
            "enriched snapshot fields are missing", missing_fields=missing
        )

    post_metadata: dict[str, tuple[str, str, str | None]] = {}
    post_coverage: dict[str, str] = {}
    seen_post_ids: set[str] = set()
    seen_comment_ids: set[str] = set()
    entities: list[_Entity] = []

    def normalise_common(
        record: Mapping[str, object],
        *,
        prefix: str,
        entity_type: EntityType,
        entity_id: str,
        post_id: str,
        subreddit: str,
        permalink: str | None,
        source_text: str,
    ) -> _Entity | None:
        brand_binding = record["brand_binding"]
        if brand_binding not in BRAND_BINDINGS:
            invalid.append(f"{prefix}.brand_binding")
            return None
        try:
            mentioned_brands = tuple(
                _string_list(
                    record["mentioned_brands"],
                    field=f"{prefix}.mentioned_brands",
                    allow_empty=True,
                )
            )
        except InputContractError as exc:
            invalid.extend(exc.invalid_fields)
            return None
        raw_products = record["product_bindings"]
        raw_has_momcozy_product = isinstance(raw_products, list) and any(
            isinstance(product, dict) and product.get("brand_id") == "momcozy"
            for product in raw_products
        )
        has_momcozy_mention = any(
            _is_momcozy_name(name) for name in mentioned_brands
        )
        has_other_mention = any(
            not _is_momcozy_name(name) for name in mentioned_brands
        )
        if brand_binding in MOMCOZY_BINDINGS and not any(
            (has_momcozy_mention, raw_has_momcozy_product)
        ):
            invalid.append(
                f"{prefix}.mentioned_brands:momcozy_binding_without_momcozy"
            )
        if brand_binding == "competitor_sentence_bound" and (
            not mentioned_brands
            or has_momcozy_mention
            or raw_has_momcozy_product
        ):
            invalid.append(
                f"{prefix}.mentioned_brands:invalid_competitor_binding"
            )
        if brand_binding == "multi_brand_context" and (
            not (has_momcozy_mention or raw_has_momcozy_product)
            or not has_other_mention
        ):
            invalid.append(
                f"{prefix}.mentioned_brands:multi_brand_requires_momcozy_and_comparator"
            )
        if brand_binding == "brand_unbound" and mentioned_brands:
            invalid.append(
                f"{prefix}.mentioned_brands:brand_unbound_requires_empty_names"
            )

        if not isinstance(raw_products, list):
            invalid.append(f"{prefix}.product_bindings")
            return None
        products: list[dict[str, object]] = []
        for product_index, product in enumerate(raw_products):
            try:
                products.append(
                    _validate_product_binding(
                        product,
                        field=f"{prefix}.product_bindings[{product_index}]",
                    )
                )
            except InputContractError as exc:
                missing.extend(exc.missing_fields)
                invalid.extend(exc.invalid_fields)

        analysis_value = record["analysis"]
        if not isinstance(analysis_value, dict):
            invalid.append(f"{prefix}.analysis")
            return None
        analysis = cast(dict[str, object], analysis_value)
        sentiment = analysis.get("sentiment_label")
        if sentiment not in SENTIMENTS:
            invalid.append(f"{prefix}.analysis.sentiment_label")
            return None
        topic_value = analysis.get("topic")
        topic = cast(str, topic_value).strip() if _is_non_empty_string(topic_value) else None
        pain_points_value = analysis.get("pain_points", [])
        try:
            pain_points = tuple(
                _string_list(
                    pain_points_value,
                    field=f"{prefix}.analysis.pain_points",
                    allow_empty=True,
                )
            )
        except InputContractError as exc:
            invalid.extend(exc.invalid_fields)
            return None

        tagging_value = record["tagging"]
        if not isinstance(tagging_value, dict):
            invalid.append(f"{prefix}.tagging")
            return None
        matches = cast(dict[str, object], tagging_value).get("matches")
        if not isinstance(matches, list):
            invalid.append(f"{prefix}.tagging.matches")
            return None
        tag_ids: list[str] = []
        tag_brand_bindings: list[tuple[str, str]] = []
        for match_index, match_value in enumerate(matches):
            if not isinstance(match_value, dict):
                invalid.append(f"{prefix}.tagging.matches[{match_index}]")
                continue
            match = cast(dict[str, object], match_value)
            tag_id = match.get("tag_id")
            if not _is_non_empty_string(tag_id):
                invalid.append(f"{prefix}.tagging.matches[{match_index}].tag_id")
                continue
            tag_id_string = cast(str, tag_id)
            if tag_id_string not in rules:
                invalid.append(
                    f"{prefix}.tagging.matches[{match_index}].unknown_tag_id:{tag_id_string}"
                )
                continue
            tag_ids.append(tag_id_string)
            raw_keywords = match.get("evidence_keywords", [])
            try:
                evidence_keywords = _string_list(
                    raw_keywords,
                    field=f"{prefix}.tagging.matches[{match_index}].evidence_keywords",
                    allow_empty=True,
                )
            except InputContractError as exc:
                invalid.extend(exc.invalid_fields)
                continue
            if tag_id_string in promoted_tag_ids and not evidence_keywords:
                invalid.append(
                    f"{prefix}.tagging.matches[{match_index}].evidence_keywords:"
                    "promoted_tag_requires_evidence"
                )
                continue
            tag_binding = cast(str, brand_binding)
            if _has_momcozy_sentence_binding(source_text, evidence_keywords):
                tag_binding = "momcozy_sentence_bound"
            elif tag_binding == "momcozy_sentence_bound":
                # Entity-level claims never substitute for tag-grain sentence
                # evidence. Keep the governed entity attribution, but downgrade
                # the relation accurately.
                tag_binding = "momcozy_entity_reviewed"
            tag_brand_bindings.append((tag_id_string, tag_binding))
        try:
            created = _parse_utc(
                record["event_created_at_utc"],
                field=f"{prefix}.event_created_at_utc",
            )
        except InputContractError as exc:
            invalid.extend(exc.invalid_fields)
            return None
        return _Entity(
            entity_type=entity_type,
            entity_id=entity_id,
            post_id=post_id,
            event_created_at_utc=created,
            subreddit=subreddit,
            permalink=permalink,
            brand_binding=cast(str, brand_binding),
            brand_names=mentioned_brands,
            product_bindings=tuple(products),
            sentiment=cast(str, sentiment),
            topic=topic,
            pain_points=pain_points,
            tag_ids=tuple(dict.fromkeys(tag_ids)),
            tag_brand_bindings=tuple(dict.fromkeys(tag_brand_bindings)),
        )

    for index, record in enumerate(posts):
        prefix = f"posts[{index}]"
        post_id_value = record["post_id"]
        subreddit_value = record["subreddit"]
        coverage_value = record["comment_coverage_status"]
        if not _is_non_empty_string(post_id_value):
            invalid.append(f"{prefix}.post_id")
            continue
        if not _is_non_empty_string(subreddit_value):
            invalid.append(f"{prefix}.subreddit")
            continue
        if coverage_value not in COMMENT_COVERAGE:
            invalid.append(f"{prefix}.comment_coverage_status")
            continue
        if not isinstance(record["title"], str) or not isinstance(
            record["content"], str
        ):
            invalid.append(f"{prefix}.title_or_content")
            continue
        post_id = cast(str, post_id_value)
        if post_id in seen_post_ids:
            invalid.append(f"duplicate_post_id:{post_id}")
            continue
        seen_post_ids.add(post_id)
        permalink_value = record.get("permalink")
        permalink = (
            cast(str, permalink_value).strip()
            if _is_non_empty_string(permalink_value)
            else None
        )
        post_metadata[post_id] = (cast(str, subreddit_value), cast(str, coverage_value), permalink)
        post_coverage[post_id] = cast(str, coverage_value)
        entity = normalise_common(
            record,
            prefix=prefix,
            entity_type="post",
            entity_id=post_id,
            post_id=post_id,
            subreddit=cast(str, subreddit_value),
            permalink=permalink,
            source_text=(
                f"{record['title']}\n{record['content']}"
                if isinstance(record["title"], str)
                and isinstance(record["content"], str)
                else ""
            ),
        )
        if entity is not None:
            entities.append(entity)

    for index, record in enumerate(comments):
        prefix = f"comments[{index}]"
        comment_id_value = record["comment_id"]
        post_id_value = record["post_id"]
        include = record["include_in_voc_metrics"]
        if not _is_non_empty_string(comment_id_value):
            invalid.append(f"{prefix}.comment_id")
            continue
        if not _is_non_empty_string(post_id_value):
            invalid.append(f"{prefix}.post_id")
            continue
        if not isinstance(include, bool):
            invalid.append(f"{prefix}.include_in_voc_metrics")
            continue
        comment_id = cast(str, comment_id_value)
        post_id = cast(str, post_id_value)
        if comment_id in seen_comment_ids:
            invalid.append(f"duplicate_comment_id:{comment_id}")
            continue
        seen_comment_ids.add(comment_id)
        if post_id not in post_metadata:
            invalid.append(f"{prefix}.post_id:orphan_comment")
            continue
        if not include:
            continue
        if not isinstance(record["body"], str):
            invalid.append(f"{prefix}.body")
            continue
        subreddit, coverage, permalink = post_metadata[post_id]
        if coverage == "post_only":
            invalid.append(f"{prefix}.post_id:included_comment_on_post_only_thread")
            continue
        entity = normalise_common(
            record,
            prefix=prefix,
            entity_type="comment",
            entity_id=comment_id,
            post_id=post_id,
            subreddit=subreddit,
            permalink=permalink,
            source_text=(record["body"] if isinstance(record["body"], str) else ""),
        )
        if entity is not None:
            entities.append(entity)

    if missing or invalid:
        raise InputContractError(
            "enriched snapshot input contract failed",
            missing_fields=missing,
            invalid_fields=invalid,
        )
    return entities, post_coverage


def _validate_coverage_ledger(
    value: Mapping[str, object] | None,
) -> tuple[dict[tuple[str, str], dict[str, object]], str | None]:
    if value is None:
        return {}, None
    if value.get("schema_version") != "reddit_voc_period_coverage_ledger_v1":
        raise InputContractError(
            "coverage ledger input contract failed",
            invalid_fields=["coverage_ledger.schema_version"],
        )
    ledger_version = value.get("ledger_version")
    if not _is_non_empty_string(ledger_version):
        raise InputContractError(
            "coverage ledger input contract failed",
            invalid_fields=["coverage_ledger.ledger_version"],
        )
    windows = value.get("windows")
    if not isinstance(windows, list):
        raise InputContractError(
            "coverage ledger input contract failed",
            invalid_fields=["coverage_ledger.windows"],
        )
    required = {
        "start_utc",
        "end_utc",
        "is_closed",
        "query_profile_version",
        "source_set_version",
        "tag_dictionary_version",
        "product_catalog_version",
        "event_time_coverage",
        "search_has_next_truncates_window",
        "hydration_policy_version",
        "comment_coverage_status",
        "schema_drift",
        "id_conflicts",
        "source_missing",
        "recent_partition",
    }
    output: dict[tuple[str, str], dict[str, object]] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for index, raw in enumerate(windows):
        prefix = f"coverage_ledger.windows[{index}]"
        if not isinstance(raw, dict):
            invalid.append(prefix)
            continue
        row = cast(dict[str, object], raw)
        missing.extend(f"{prefix}.{field}" for field in sorted(required - set(row)))
        if required - set(row):
            continue
        try:
            start = _parse_utc(row["start_utc"], field=f"{prefix}.start_utc")
            end = _parse_utc(row["end_utc"], field=f"{prefix}.end_utc")
        except InputContractError as exc:
            invalid.extend(exc.invalid_fields)
            continue
        if start >= end:
            invalid.append(f"{prefix}.window")
            continue
        for field in (
            "is_closed",
            "search_has_next_truncates_window",
            "schema_drift",
            "source_missing",
            "recent_partition",
        ):
            if not isinstance(row[field], bool):
                invalid.append(f"{prefix}.{field}")
        for field in (
            "query_profile_version",
            "source_set_version",
            "tag_dictionary_version",
            "product_catalog_version",
            "hydration_policy_version",
        ):
            if not _is_non_empty_string(row[field]):
                invalid.append(f"{prefix}.{field}")
        if row["event_time_coverage"] not in {"complete", "partial", "unavailable"}:
            invalid.append(f"{prefix}.event_time_coverage")
        if row["comment_coverage_status"] not in {
            "thread_complete",
            "observed_first_page",
            "post_only",
            "mixed",
        }:
            invalid.append(f"{prefix}.comment_coverage_status")
        id_conflicts = row["id_conflicts"]
        if isinstance(id_conflicts, bool) or not isinstance(id_conflicts, int) or id_conflicts < 0:
            invalid.append(f"{prefix}.id_conflicts")
        key = (_iso_utc(start), _iso_utc(end))
        if key in output:
            invalid.append(f"{prefix}.duplicate_window")
        output[key] = row
    if missing or invalid:
        raise InputContractError(
            "coverage ledger input contract failed",
            missing_fields=missing,
            invalid_fields=invalid,
        )
    return output, cast(str, ledger_version)


def _in_window(entity: _Entity, window: PeriodWindow) -> bool:
    return window.start_utc <= entity.event_created_at_utc < window.end_utc


def _window_entities(
    entities: Sequence[_Entity], window: PeriodWindow
) -> list[_Entity]:
    return [entity for entity in entities if _in_window(entity, window)]


def _is_momcozy_entity(entity: _Entity) -> bool:
    return entity.brand_binding in MOMCOZY_BINDINGS


def _unique_entities(entities: Iterable[_Entity]) -> list[_Entity]:
    output: dict[tuple[str, str], _Entity] = {}
    for entity in entities:
        output[(entity.entity_type, entity.entity_id)] = entity
    return list(output.values())


def _negative_share(entities: Iterable[_Entity]) -> dict[str, object]:
    unique = _unique_entities(entities)
    numerator = sum(entity.sentiment == "negative" for entity in unique)
    denominator = len(unique)
    return {
        "metric": "negative_momcozy_observed_entities_over_classified_momcozy_observed_entities",
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
        "value_status": "observed" if denominator else "denominator_zero",
    }


def _observed_count(entities: Iterable[_Entity]) -> dict[str, object]:
    count = len(_unique_entities(entities))
    return {
        "metric": "momcozy_brand_bound_observed_entity_count",
        "value": count,
        "unit": "observed_entity",
        "value_status": "observed",
    }


def _metric_value(
    entities: Iterable[_Entity], metric_name: MetricName
) -> dict[str, object]:
    if metric_name == "observed_count":
        return _observed_count(entities)
    return _negative_share(entities)


def _momcozy_share_by_type(entities: Sequence[_Entity]) -> dict[str, object]:
    result: dict[str, object] = {
        entity_type: _negative_share(
            entity
            for entity in entities
            if entity.entity_type == entity_type and _is_momcozy_entity(entity)
        )
        for entity_type in ("post", "comment")
    }
    result["combined"] = {
        "supported": False,
        "reason": "posts_and_comments_are_separate_entities_no_weighting_contract",
        "value": None,
    }
    return result


def _sentiment_summary(entities: Iterable[_Entity]) -> dict[str, object]:
    unique = _unique_entities(entities)
    counts = Counter(entity.sentiment for entity in unique)
    denominator = len(unique)
    return {
        "denominator": denominator,
        "counts": {sentiment: counts[sentiment] for sentiment in SENTIMENTS},
        "shares": {
            sentiment: {
                "numerator": counts[sentiment],
                "denominator": denominator,
                "value": (
                    round(counts[sentiment] / denominator, 6)
                    if denominator
                    else None
                ),
            }
            for sentiment in SENTIMENTS
        },
    }


def _risk_facts(
    entities: Sequence[_Entity],
    rules: Mapping[str, dict[str, object]],
) -> list[_RiskFact]:
    facts: list[_RiskFact] = []
    for entity in entities:
        tag_bindings = dict(entity.tag_brand_bindings)
        for tag_id in entity.tag_ids:
            rule = rules[tag_id]
            rule_sentiment = str(rule["sentiment"]).casefold()
            if entity.sentiment != "negative" and rule_sentiment not in {
                "negative",
                "负向",
                "消极",
            }:
                continue
            facts.append(
                _RiskFact(
                    entity=entity,
                    tag_id=tag_id,
                    rule=rule,
                    brand_binding=tag_bindings[tag_id],
                )
            )
    return facts


def _is_momcozy_fact(fact: _RiskFact) -> bool:
    return fact.brand_binding in MOMCOZY_BINDINGS


def _entity_key(entity: _Entity) -> tuple[str, str]:
    return (entity.entity_type, entity.entity_id)


def _product_scope_ids(bindings: Iterable[dict[str, object]]) -> dict[str, list[str]]:
    output: dict[str, set[str]] = {
        "category": set(),
        "product_family": set(),
        "spu_exact": set(),
    }
    for binding in bindings:
        category = cast(dict[str, object], binding["category"])
        output["category"].add(cast(str, category["id"]))
        family_value = binding["product_family"]
        if isinstance(family_value, dict):
            family = cast(dict[str, object], family_value)
            output["product_family"].add(cast(str, family["id"]))
        if (
            binding["binding_level"] == "spu_exact"
            and binding["governance_status"] == "exact_spu_approved"
        ):
            exact = cast(dict[str, object], binding["exact_spu"])
            output["spu_exact"].add(cast(str, exact["spu_id"]))
    return {level: sorted(values) for level, values in output.items()}


def _build_risk_themes(
    facts: Sequence[_RiskFact],
    *,
    promoted_tag_ids: set[str],
    risk_gate_policy: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    by_tag: dict[str, list[_RiskFact]] = defaultdict(list)
    for fact in facts:
        by_tag[fact.tag_id].append(fact)
    themes: list[dict[str, object]] = []
    for tag_id, tag_facts in by_tag.items():
        momcozy_facts = [
            fact for fact in tag_facts if _is_momcozy_fact(fact)
        ]
        if not momcozy_facts:
            continue
        unique_momcozy = {
            _entity_key(fact.entity): fact.entity for fact in momcozy_facts
        }
        unique_all = {_entity_key(fact.entity) for fact in tag_facts}
        distinct_posts = {fact.entity.post_id for fact in momcozy_facts}
        communities = {
            fact.entity.subreddit
            for fact in momcozy_facts
            if fact.entity.subreddit.casefold() != "unknown"
        }
        binding_rate = (
            len(unique_momcozy) / len(unique_all) if unique_all else 0.0
        )
        rule = tag_facts[0].rule
        binding_counts = Counter(fact.brand_binding for fact in tag_facts)
        dictionary_priority = str(rule["default_priority"])
        reason_codes: list[str] = []
        if risk_gate_policy is None:
            reason_codes.append("risk_theme_gate_policy_missing")
        elif risk_gate_policy["status"] != "frozen":
            reason_codes.append("risk_theme_gate_policy_not_frozen")
        if tag_id not in promoted_tag_ids:
            reason_codes.append("semantic_tag_not_promoted")
        if dictionary_priority not in PRIORITIES:
            reason_codes.append("dictionary_default_priority_unsupported")
        if risk_gate_policy is not None:
            if len(unique_momcozy) < cast(
                int, risk_gate_policy["minimum_observed_entities"]
            ):
                reason_codes.append("minimum_observed_entities_not_met")
            if len(distinct_posts) < cast(
                int, risk_gate_policy["minimum_distinct_posts"]
            ):
                reason_codes.append("minimum_distinct_posts_not_met")
            if len(communities) < cast(
                int, risk_gate_policy["minimum_communities"]
            ):
                reason_codes.append("minimum_communities_not_met")
            minimum_binding_rate = cast(
                float | int, risk_gate_policy["minimum_brand_binding_rate"]
            )
            if binding_rate < float(minimum_binding_rate):
                reason_codes.append("minimum_brand_binding_rate_not_met")
        passed = not reason_codes
        observed_post_ids = {
            entity.entity_id
            for entity in unique_momcozy.values()
            if entity.entity_type == "post"
        }
        observed_comment_ids = {
            entity.entity_id
            for entity in unique_momcozy.values()
            if entity.entity_type == "comment"
        }
        product_bindings = [
            binding
            for entity in unique_momcozy.values()
            for binding in entity.product_bindings
        ]
        event_times = sorted(
            entity.event_created_at_utc for entity in unique_momcozy.values()
        )
        ordered_evidence = sorted(
            unique_momcozy.values(),
            key=lambda entity: (
                -entity.event_created_at_utc.timestamp(),
                0 if entity.entity_type == "post" else 1,
                entity.entity_id,
            ),
        )
        evidence_refs = [
            {
                "entity_type": entity.entity_type,
                "entity_id": entity.entity_id,
                "post_id": entity.post_id,
                "event_created_at_utc": _iso_utc(entity.event_created_at_utc),
                "subreddit": entity.subreddit,
                "permalink": entity.permalink,
                "brand_binding": dict(entity.tag_brand_bindings)[tag_id],
            }
            for entity in ordered_evidence[:THEME_EVIDENCE_REF_LIMIT]
        ]
        themes.append(
            {
                "risk_theme_id": tag_id,
                "tag_id": tag_id,
                "name_cn": rule["name_cn"],
                "name_en": rule["name_en"],
                "theme": rule["theme"],
                "risk_level": rule["risk_level"],
                "dictionary_default_priority": dictionary_priority,
                "effective_priority": dictionary_priority if passed else "insufficient",
                "evidence_gate": {
                    "status": "passed" if passed else "insufficient",
                    "policy_version": (
                        risk_gate_policy["policy_version"]
                        if risk_gate_policy is not None
                        else None
                    ),
                    "reason_codes": sorted(reason_codes),
                    "semantic_status": (
                        "promoted" if tag_id in promoted_tag_ids else "provisional"
                    ),
                },
                "observed_entities": {
                    "post": len(observed_post_ids),
                    "comment": len(observed_comment_ids),
                },
                "distinct_posts": len(distinct_posts),
                "communities": len(communities),
                "brand_binding_rate": round(binding_rate, 6),
                "brand_binding_counts": {
                    binding: binding_counts[binding]
                    for binding in sorted(BRAND_BINDINGS)
                },
                "sentence_bound_rate": round(
                    binding_counts["momcozy_sentence_bound"]
                    / len(unique_momcozy),
                    6,
                ),
                "event_window": {
                    "first_utc": _iso_utc(event_times[0]),
                    "last_utc": _iso_utc(event_times[-1]),
                },
                "evidence_refs": evidence_refs,
                "evidence_ref_count_total": len(ordered_evidence),
                "evidence_refs_truncated": (
                    len(ordered_evidence) > THEME_EVIDENCE_REF_LIMIT
                ),
                "product_scope_ids": _product_scope_ids(product_bindings),
                "problem_type": rule["problem_type"],
                "intent_type": rule["intent_type"],
                "story_line": rule["story_lines"],
                "business_impact": rule["business_impact"],
                "dept_owner": rule["dept_owner"],
                "suggested_action": rule["biz_action"],
                "action_state": "recommendation_only",
            }
        )
    priority_rank = {priority: index for index, priority in enumerate(PRIORITIES)}
    priority_rank["insufficient"] = len(PRIORITIES)
    return sorted(
        themes,
        key=lambda row: (
            priority_rank[cast(str, row["effective_priority"])],
            cast(str, row["risk_theme_id"]),
        ),
    )


def _scope_reference(
    binding: Mapping[str, object], level: str
) -> tuple[str, str, str] | None:
    if level == "category":
        category = cast(dict[str, object], binding["category"])
        return (
            cast(str, category["id"]),
            cast(str, category["name_en"]),
            cast(str, category["name_cn"]),
        )
    if level == "product_family":
        family_value = binding["product_family"]
        if not isinstance(family_value, dict):
            return None
        family = cast(dict[str, object], family_value)
        return (
            cast(str, family["id"]),
            cast(str, family["name_en"]),
            cast(str, family["name_cn"]),
        )
    if level == "spu_exact":
        if (
            binding["binding_level"] != "spu_exact"
            or binding["governance_status"] != "exact_spu_approved"
        ):
            return None
        exact = cast(dict[str, object], binding["exact_spu"])
        return (
            cast(str, exact["spu_id"]),
            cast(str, exact["spu_name"]),
            cast(str, exact["spu_name"]),
        )
    raise ValueError(f"unsupported product scope level: {level}")


def _build_product_analysis(
    entities: Sequence[_Entity],
    *,
    facts: Sequence[_RiskFact],
    themes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    momcozy = [entity for entity in entities if _is_momcozy_entity(entity)]
    bound_keys = {
        _entity_key(entity) for entity in momcozy if entity.product_bindings
    }
    all_keys = {_entity_key(entity) for entity in momcozy}
    priority_by_tag = {
        cast(str, theme["tag_id"]): cast(str, theme["effective_priority"])
        for theme in themes
    }
    fact_tags_by_entity: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fact in facts:
        if _is_momcozy_fact(fact):
            fact_tags_by_entity[_entity_key(fact.entity)].add(fact.tag_id)

    levels: dict[str, list[dict[str, object]]] = {}
    for level in ("category", "product_family", "spu_exact"):
        grouped: dict[
            str, tuple[tuple[str, str, str], dict[tuple[str, str], _Entity]]
        ] = {}
        for entity in momcozy:
            for binding in entity.product_bindings:
                reference = _scope_reference(binding, level)
                if reference is None:
                    continue
                scope_id = reference[0]
                if scope_id not in grouped:
                    grouped[scope_id] = (reference, {})
                grouped[scope_id][1][_entity_key(entity)] = entity
        entries: list[dict[str, object]] = []
        for scope_id, (reference, entity_map) in grouped.items():
            scoped_entities = list(entity_map.values())
            priority_counts: Counter[str] = Counter()
            for entity_key in entity_map:
                for tag_id in fact_tags_by_entity[entity_key]:
                    priority_counts[priority_by_tag.get(tag_id, "insufficient")] += 1
            entries.append(
                {
                    "scope_id": scope_id,
                    "scope_name_en": reference[1],
                    "scope_name_cn": reference[2],
                    "binding_level": level,
                    "metrics": _momcozy_share_by_type(scoped_entities),
                    "risk_priority_assignments": {
                        priority: priority_counts[priority]
                        for priority in (*PRIORITIES, "insufficient")
                    },
                }
            )
        levels[level] = sorted(entries, key=lambda row: cast(str, row["scope_id"]))

    bindings = [binding for entity in momcozy for binding in entity.product_bindings]
    return {
        "schema_version": "reddit_voc_product_analysis_v1",
        "decision_subject": "momcozy",
        "scope_order": ["category", "product_family", "spu_exact"],
        "category": levels["category"],
        "product_family": levels["product_family"],
        "spu_exact": levels["spu_exact"],
        "coverage": {
            "momcozy_observed_entities": len(all_keys),
            "bound_entities": len(bound_keys),
            "unbound_entities": len(all_keys - bound_keys),
            "binding_rate": round(len(bound_keys) / len(all_keys), 6) if all_keys else None,
            "binding_count": len(bindings),
            "family_only_bindings": sum(
                binding["governance_status"] == "family_only" for binding in bindings
            ),
            "category_only_bindings": sum(
                binding["governance_status"] == "category_only" for binding in bindings
            ),
            "taxonomy_blocked_bindings": sum(
                binding["governance_status"] == "taxonomy_blocked" for binding in bindings
            ),
            "exact_spu_release_rule": "exact_spu_approved_only",
        },
        "interpretation_boundary": (
            "multi_product_entities_can_appear_in_more_than_one_scope_"
            "but_each_entity_is_deduplicated_within_a_scope"
        ),
    }


def _product_scope_catalog(
    entities: Sequence[_Entity],
) -> dict[str, dict[str, tuple[str, str, str]]]:
    catalog: dict[str, dict[str, tuple[str, str, str]]] = {
        "category": {},
        "product_family": {},
        "spu_exact": {},
    }
    for entity in entities:
        if not _is_momcozy_entity(entity):
            continue
        for binding in entity.product_bindings:
            for level in ("category", "product_family", "spu_exact"):
                reference = _scope_reference(binding, level)
                if reference is not None:
                    catalog[level].setdefault(reference[0], reference)
    return catalog


def _entities_for_product_scope(
    entities: Sequence[_Entity], *, level: str, scope_id: str
) -> list[_Entity]:
    output: dict[tuple[str, str], _Entity] = {}
    for entity in entities:
        if not _is_momcozy_entity(entity):
            continue
        if any(
            (reference := _scope_reference(binding, level)) is not None
            and reference[0] == scope_id
            for binding in entity.product_bindings
        ):
            output[_entity_key(entity)] = entity
    return list(output.values())


def _product_metric_observations(
    entities: Sequence[_Entity],
    *,
    coverage: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        entity_type: {
            metric_name: _gated_metric_observation(
                entities,
                entity_type=cast(EntityType, entity_type),
                metric_name=cast(MetricName, metric_name),
                coverage=coverage,
            )
            for metric_name in ("observed_count", "negative_evidence_share")
        }
        for entity_type in ("post", "comment")
    }


def _product_metric_comparisons(
    *,
    current_entities: Sequence[_Entity],
    baseline_entities: Sequence[_Entity],
    current_coverage: Mapping[str, object] | None,
    baseline_coverage: Mapping[str, object] | None,
    comparison_type: str,
) -> dict[str, object]:
    return {
        entity_type: {
            metric_name: _period_comparison(
                current_entities=current_entities,
                baseline_entities=baseline_entities,
                current_coverage=current_coverage,
                baseline_coverage=baseline_coverage,
                entity_type=cast(EntityType, entity_type),
                comparison_type=comparison_type,
                metric_name=cast(MetricName, metric_name),
            )
            for metric_name in ("observed_count", "negative_evidence_share")
        }
        for entity_type in ("post", "comment")
    }


def _product_scope_trend(
    *,
    entities: Sequence[_Entity],
    level: str,
    scope_id: str,
    windows: Sequence[PeriodWindow],
    coverage_index: Mapping[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    points: list[dict[str, object]] = []
    adjacent: list[dict[str, object]] = []
    previous_window: PeriodWindow | None = None
    previous_entities: list[_Entity] = []
    for window in windows:
        window_entities = _entities_for_product_scope(
            _window_entities(entities, window),
            level=level,
            scope_id=scope_id,
        )
        coverage = _coverage_for_window(coverage_index, window)
        point: dict[str, object] = {
            "window": window.to_record(),
            "metrics": _product_metric_observations(
                window_entities,
                coverage=coverage,
            ),
            "coverage_status": (
                coverage["event_time_coverage"]
                if coverage is not None
                else "coverage_missing"
            ),
        }
        if previous_window is None:
            point["change_from_previous"] = None
        else:
            change = _product_metric_comparisons(
                current_entities=window_entities,
                baseline_entities=previous_entities,
                current_coverage=coverage,
                baseline_coverage=_coverage_for_window(
                    coverage_index, previous_window
                ),
                comparison_type="trend_period_over_period",
            )
            point["change_from_previous"] = change
            adjacent.extend(
                cast(
                    dict[str, object],
                    cast(dict[str, object], entity_metrics)[metric_name],
                )
                for entity_metrics in change.values()
                for metric_name in ("observed_count", "negative_evidence_share")
            )
        points.append(point)
        previous_window = window
        previous_entities = window_entities
    return {
        "point_count": len(points),
        "points": points,
        "direction_claim_supported": bool(adjacent)
        and all(
            comparison["comparison_status"] == "comparable"
            for comparison in adjacent
        ),
    }


def _build_product_period_analysis(
    *,
    entities: Sequence[_Entity],
    period: Period,
    window_set: PeriodWindowSet,
    coverage_index: Mapping[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    relevant_windows = (
        window_set.current,
        window_set.previous,
        window_set.year_over_year,
        *window_set.trend,
    )
    relevant_entities = _unique_entities(
        entity
        for window in relevant_windows
        for entity in _window_entities(entities, window)
    )
    catalog = _product_scope_catalog(relevant_entities)
    current_all = _window_entities(entities, window_set.current)
    previous_all = _window_entities(entities, window_set.previous)
    yoy_all = _window_entities(entities, window_set.year_over_year)
    current_coverage = _coverage_for_window(coverage_index, window_set.current)
    levels: dict[str, list[dict[str, object]]] = {}
    for level in ("category", "product_family", "spu_exact"):
        rows: list[dict[str, object]] = []
        for scope_id, reference in sorted(catalog[level].items()):
            current_entities = _entities_for_product_scope(
                current_all, level=level, scope_id=scope_id
            )
            previous_entities = _entities_for_product_scope(
                previous_all, level=level, scope_id=scope_id
            )
            yoy_entities = _entities_for_product_scope(
                yoy_all, level=level, scope_id=scope_id
            )
            rows.append(
                {
                    "scope_id": scope_id,
                    "scope_name_en": reference[1],
                    "scope_name_cn": reference[2],
                    "binding_level": level,
                    "current": _product_metric_observations(
                        current_entities,
                        coverage=current_coverage,
                    ),
                    "period_comparisons": {
                        "previous_period": _product_metric_comparisons(
                            current_entities=current_entities,
                            baseline_entities=previous_entities,
                            current_coverage=current_coverage,
                            baseline_coverage=_coverage_for_window(
                                coverage_index, window_set.previous
                            ),
                            comparison_type={
                                "daily": "day_over_day",
                                "weekly": "week_over_week",
                                "monthly": "month_over_month",
                            }[period],
                        ),
                        "year_over_year": _product_metric_comparisons(
                            current_entities=current_entities,
                            baseline_entities=yoy_entities,
                            current_coverage=current_coverage,
                            baseline_coverage=_coverage_for_window(
                                coverage_index, window_set.year_over_year
                            ),
                            comparison_type="year_over_year",
                        ),
                    },
                    "trend": _product_scope_trend(
                        entities=entities,
                        level=level,
                        scope_id=scope_id,
                        windows=window_set.trend,
                        coverage_index=coverage_index,
                    ),
                }
            )
        levels[level] = rows
    return {
        "schema_version": "reddit_voc_product_period_metrics_v1",
        "decision_subject": "momcozy",
        "period": period,
        "scope_order": ["category", "product_family", "spu_exact"],
        "category": levels["category"],
        "product_family": levels["product_family"],
        "spu_exact": levels["spu_exact"],
        "metric_definitions": {
            "observed_count": (
                "momcozy_brand_bound_observed_entities_by_entity_type"
            ),
            "negative_evidence_share": (
                "negative_over_classified_momcozy_brand_bound_observed_"
                "entities_by_entity_type"
            ),
        },
        "interpretation_boundary": (
            "posts_and_comments_are_separate;multi_product_entities_can_"
            "appear_in_multiple_scopes;zero_is_emitted_only_when_window_"
            "coverage_supports_zero_otherwise_value_is_null_with_reason"
        ),
    }


def _competitor_brand_groups(
    entities: Sequence[_Entity],
) -> tuple[dict[str, dict[tuple[str, str], _Entity]], dict[str, str]]:
    grouped: dict[str, dict[tuple[str, str], _Entity]] = defaultdict(dict)
    display_names: dict[str, str] = {}
    for entity in entities:
        if entity.brand_binding != "competitor_sentence_bound":
            continue
        for brand in entity.brand_names:
            if _is_momcozy_name(brand):
                continue
            key = _normalise_brand(brand)
            grouped[key][_entity_key(entity)] = entity
            display_names.setdefault(key, brand)
    return grouped, display_names


def _competitor_metric(
    entities: Iterable[_Entity], metric_name: MetricName
) -> dict[str, object]:
    unique = _unique_entities(entities)
    if metric_name == "observed_count":
        return {
            "metric": "competitor_brand_bound_observed_entity_count",
            "value": len(unique),
            "unit": "observed_entity",
            "value_status": "observed",
        }
    numerator = sum(entity.sentiment == "negative" for entity in unique)
    denominator = len(unique)
    return {
        "metric": "negative_competitor_observed_entities_over_classified_competitor_observed_entities",
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
        "value_status": "observed" if denominator else "denominator_zero",
    }


def _competitor_null_metric(metric_name: MetricName) -> dict[str, object]:
    if metric_name == "observed_count":
        return {
            "metric": "competitor_brand_bound_observed_entity_count",
            "value": None,
            "unit": "observed_entity",
            "value_status": "unavailable",
        }
    return {
        "metric": "negative_competitor_observed_entities_over_classified_competitor_observed_entities",
        "numerator": None,
        "denominator": None,
        "value": None,
        "value_status": "unavailable",
    }


def _competitor_period_comparison(
    *,
    current_entities: Sequence[_Entity],
    baseline_entities: Sequence[_Entity],
    current_coverage: Mapping[str, object] | None,
    baseline_coverage: Mapping[str, object] | None,
    entity_type: EntityType,
    comparison_type: str,
    metric_name: MetricName,
) -> dict[str, object]:
    status, reasons = _comparison_gate(
        current_coverage, baseline_coverage, entity_type=entity_type
    )
    current_rows = [
        entity for entity in current_entities if entity.entity_type == entity_type
    ]
    baseline_rows = [
        entity for entity in baseline_entities if entity.entity_type == entity_type
    ]
    current = _competitor_metric(current_rows, metric_name)
    current_observed = bool(current_rows)
    baseline_observed = bool(baseline_rows)
    if (
        current_coverage is not None
        and current_coverage["event_time_coverage"] != "complete"
        and not current_observed
    ):
        status = "unavailable"
        reasons.append("current_observation_absent_under_incomplete_coverage")
        current = _competitor_null_metric(metric_name)
    if (
        baseline_coverage is not None
        and baseline_coverage["event_time_coverage"] != "complete"
        and not baseline_observed
    ):
        status = "unavailable"
        reasons.append("baseline_observation_absent_under_incomplete_coverage")
    baseline = (
        None
        if baseline_coverage is None
        or (
            baseline_coverage["event_time_coverage"] != "complete"
            and not baseline_observed
        )
        else _competitor_metric(baseline_rows, metric_name)
    )
    absolute_delta: float | None = None
    relative_delta: float | None = None
    delta_reason: str | None = None
    if status != "unavailable" and baseline is not None:
        current_value = current["value"]
        baseline_value = baseline["value"]
        if current_value is None:
            delta_reason = "current_denominator_zero"
        elif baseline_value is None:
            delta_reason = "baseline_denominator_zero"
        else:
            current_number = float(cast(float | int, current_value))
            baseline_number = float(cast(float | int, baseline_value))
            absolute_delta = round(current_number - baseline_number, 6)
            if baseline_number == 0:
                delta_reason = "baseline_value_zero_relative_delta_undefined"
            else:
                relative_delta = round(absolute_delta / baseline_number, 6)
    elif status == "unavailable":
        delta_reason = "comparison_gate_unavailable"
    return {
        "metric_name": metric_name,
        "comparison_type": comparison_type,
        "entity_type": entity_type,
        "comparison_status": status,
        "reason_codes": sorted(set(reasons)),
        "current": current,
        "baseline": baseline,
        "absolute_delta": absolute_delta,
        "relative_delta": relative_delta,
        "delta_reason": delta_reason,
        "direction_claim_supported": status == "comparable"
        and absolute_delta is not None,
    }


def _ranked_competitor_dimension(
    values: Iterable[str], *, field: str, limit: int = 5
) -> list[dict[str, object]]:
    counts = Counter(value for value in values if value)
    return [
        {field: value, "observed_entities": count}
        for value, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[:limit]
    ]


def _competitor_context(
    entities: Sequence[_Entity],
    *,
    previous_entities: Sequence[_Entity] | None = None,
    year_over_year_entities: Sequence[_Entity] | None = None,
    current_coverage: Mapping[str, object] | None = None,
    previous_coverage: Mapping[str, object] | None = None,
    year_over_year_coverage: Mapping[str, object] | None = None,
    previous_comparison_type: str | None = None,
) -> list[dict[str, object]]:
    grouped, display_names = _competitor_brand_groups(entities)
    previous_grouped, _ = _competitor_brand_groups(previous_entities or [])
    yoy_grouped, _ = _competitor_brand_groups(year_over_year_entities or [])
    output: list[dict[str, object]] = []
    for key, entity_map in grouped.items():
        competitor_entities = list(entity_map.values())
        previous_brand_entities = list(previous_grouped.get(key, {}).values())
        yoy_brand_entities = list(yoy_grouped.get(key, {}).values())
        row: dict[str, object] = {
                "brand_id": key,
                "brand_name": display_names[key],
                "comparison_role": "same_observed_sample_context",
                "negative_evidence_share": {
                    entity_type: _competitor_metric(
                        (
                            entity
                            for entity in competitor_entities
                            if entity.entity_type == entity_type
                        ),
                        metric_name="negative_evidence_share",
                    )
                    for entity_type in ("post", "comment")
                },
                "observed_count": {
                    entity_type: _competitor_metric(
                        (
                            entity
                            for entity in competitor_entities
                            if entity.entity_type == entity_type
                        ),
                        metric_name="observed_count",
                    )
                    for entity_type in ("post", "comment")
                },
                "top_topics": _ranked_competitor_dimension(
                    (entity.topic or "unclassified" for entity in competitor_entities),
                    field="topic",
                ),
                "top_pain_points": _ranked_competitor_dimension(
                    (
                        pain_point
                        for entity in competitor_entities
                        for pain_point in set(entity.pain_points)
                    ),
                    field="pain_point",
                ),
                "top_communities": _ranked_competitor_dimension(
                    (entity.subreddit for entity in competitor_entities),
                    field="subreddit",
                ),
                "top_risk_tags": _ranked_competitor_dimension(
                    (
                        tag_id
                        for entity in competitor_entities
                        for tag_id in set(entity.tag_ids)
                    ),
                    field="tag_id",
                ),
                "product_scope_ids": {
                    "category": [],
                    "product_family": [],
                    "spu_exact": [],
                },
                "product_taxonomy": {
                    "status": "unavailable_no_competitor_taxonomy",
                    "category": [],
                    "product_family": [],
                    "spu_exact": [],
                    "reason_code": "competitor_product_catalog_not_governed",
                },
                "interpretation_boundary": (
                    "comparison_is_not_market_share_sov_penetration_or_sales"
                ),
            }
        if previous_entities is not None and year_over_year_entities is not None:
            comparison_groups: dict[str, object] = {}
            for label, baseline_rows, baseline_coverage, comparison_type in (
                (
                    "previous_period",
                    previous_brand_entities,
                    previous_coverage,
                    previous_comparison_type or "period_over_period",
                ),
                (
                    "year_over_year",
                    yoy_brand_entities,
                    year_over_year_coverage,
                    "year_over_year",
                ),
            ):
                comparison_groups[label] = {
                    metric_name: {
                        entity_type: _competitor_period_comparison(
                            current_entities=competitor_entities,
                            baseline_entities=baseline_rows,
                            current_coverage=current_coverage,
                            baseline_coverage=baseline_coverage,
                            entity_type=cast(EntityType, entity_type),
                            comparison_type=comparison_type,
                            metric_name=cast(MetricName, metric_name),
                        )
                        for entity_type in ("post", "comment")
                    }
                    for metric_name in (
                        "observed_count",
                        "negative_evidence_share",
                    )
                }
            previous = cast(
                dict[str, dict[str, dict[str, object]]],
                comparison_groups["previous_period"],
            )
            row["period_comparisons"] = comparison_groups
            row["trend"] = {
                "basis": "current_vs_previous_period",
                "direction_claim_supported": all(
                    comparison["comparison_status"] == "comparable"
                    and comparison["direction_claim_supported"] is True
                    for metric in previous.values()
                    for comparison in metric.values()
                ),
                "comparisons": previous,
            }
        output.append(row)
    return sorted(output, key=lambda row: cast(str, row["brand_id"]))


def _coverage_hard_reasons(row: Mapping[str, object], *, side: str) -> list[str]:
    reasons: list[str] = []
    if row["is_closed"] is not True:
        reasons.append(f"{side}_window_not_closed")
    if row["event_time_coverage"] == "unavailable":
        reasons.append(f"{side}_event_time_coverage_unavailable")
    if row["source_missing"] is True:
        reasons.append(f"{side}_source_missing")
    if row["schema_drift"] is True:
        reasons.append(f"{side}_schema_drift")
    if cast(int, row["id_conflicts"]) > 0:
        reasons.append(f"{side}_id_conflicts")
    if row["recent_partition"] is True:
        reasons.append(f"{side}_recent_partition")
    return reasons


def _comparison_gate(
    current: Mapping[str, object] | None,
    baseline: Mapping[str, object] | None,
    *,
    entity_type: EntityType,
) -> tuple[ComparisonStatus, list[str]]:
    if current is None or baseline is None:
        reasons: list[str] = []
        if current is None:
            reasons.append("current_coverage_missing")
        if baseline is None:
            reasons.append("baseline_coverage_missing")
        return "unavailable", reasons
    unavailable = _coverage_hard_reasons(current, side="current")
    unavailable.extend(_coverage_hard_reasons(baseline, side="baseline"))
    for field in (
        "query_profile_version",
        "source_set_version",
        "tag_dictionary_version",
        "product_catalog_version",
    ):
        if current[field] != baseline[field]:
            unavailable.append(f"{field}_mismatch")
    if entity_type == "comment" and (
        current["hydration_policy_version"] != baseline["hydration_policy_version"]
    ):
        unavailable.append("hydration_policy_version_mismatch")
    if unavailable:
        return "unavailable", sorted(set(unavailable))
    provisional: list[str] = []
    if current["event_time_coverage"] != "complete" or baseline[
        "event_time_coverage"
    ] != "complete":
        provisional.append("event_time_coverage_partial")
    if current["search_has_next_truncates_window"] is True or baseline[
        "search_has_next_truncates_window"
    ] is True:
        provisional.append("search_has_next_truncates_window")
    if entity_type == "comment" and (
        current["comment_coverage_status"] != "thread_complete"
        or baseline["comment_coverage_status"] != "thread_complete"
    ):
        provisional.append("comment_coverage_not_thread_complete")
    if provisional:
        return "provisional_observed_sample", sorted(set(provisional))
    return "comparable", []


def _share_for_type(
    entities: Sequence[_Entity], entity_type: EntityType
) -> dict[str, object]:
    return _metric_for_type(
        entities, entity_type=entity_type, metric_name="negative_evidence_share"
    )


def _metric_for_type(
    entities: Sequence[_Entity],
    *,
    entity_type: EntityType,
    metric_name: MetricName,
) -> dict[str, object]:
    return _metric_value(
        (
            entity
            for entity in entities
            if entity.entity_type == entity_type and _is_momcozy_entity(entity)
        ),
        metric_name,
    )


def _null_metric(metric_name: MetricName) -> dict[str, object]:
    if metric_name == "observed_count":
        return {
            "metric": "momcozy_brand_bound_observed_entity_count",
            "value": None,
            "unit": "observed_entity",
            "value_status": "unavailable",
        }
    return {
        "metric": (
            "negative_momcozy_observed_entities_over_classified_"
            "momcozy_observed_entities"
        ),
        "numerator": None,
        "denominator": None,
        "value": None,
        "value_status": "unavailable",
    }


def _period_comparison(
    *,
    current_entities: Sequence[_Entity],
    baseline_entities: Sequence[_Entity],
    current_coverage: Mapping[str, object] | None,
    baseline_coverage: Mapping[str, object] | None,
    entity_type: EntityType,
    comparison_type: str,
    metric_name: MetricName = "negative_evidence_share",
) -> dict[str, object]:
    status, reasons = _comparison_gate(
        current_coverage, baseline_coverage, entity_type=entity_type
    )
    current = _metric_for_type(
        current_entities,
        entity_type=entity_type,
        metric_name=metric_name,
    )
    current_observed = any(
        entity.entity_type == entity_type and _is_momcozy_entity(entity)
        for entity in current_entities
    )
    baseline_observed = any(
        entity.entity_type == entity_type and _is_momcozy_entity(entity)
        for entity in baseline_entities
    )
    if (
        current_coverage is not None
        and current_coverage["event_time_coverage"] != "complete"
        and not current_observed
    ):
        status = "unavailable"
        reasons.append("current_observation_absent_under_incomplete_coverage")
        current = _null_metric(metric_name)
    if (
        baseline_coverage is not None
        and baseline_coverage["event_time_coverage"] != "complete"
        and not baseline_observed
    ):
        status = "unavailable"
        reasons.append("baseline_observation_absent_under_incomplete_coverage")
    reasons = sorted(set(reasons))
    baseline = None
    if baseline_coverage is not None and not (
        baseline_coverage["event_time_coverage"] != "complete"
        and not baseline_observed
    ):
        baseline = _metric_for_type(
            baseline_entities,
            entity_type=entity_type,
            metric_name=metric_name,
        )
    absolute_delta: float | None = None
    relative_delta: float | None = None
    delta_reason: str | None = None
    if status != "unavailable" and baseline is not None:
        current_value = current["value"]
        baseline_value = baseline["value"]
        if current_value is None:
            delta_reason = "current_denominator_zero"
        elif baseline_value is None:
            delta_reason = "baseline_denominator_zero"
        else:
            current_number = float(cast(float | int, current_value))
            baseline_number = float(cast(float | int, baseline_value))
            absolute_delta = round(current_number - baseline_number, 6)
            if baseline_number == 0:
                delta_reason = "baseline_value_zero_relative_delta_undefined"
            else:
                relative_delta = round(
                    absolute_delta / baseline_number, 6
                )
    elif status == "unavailable":
        delta_reason = "comparison_gate_unavailable"
    return {
        "metric_name": metric_name,
        "comparison_type": comparison_type,
        "entity_type": entity_type,
        "comparison_status": status,
        "reason_codes": reasons,
        "current": current,
        "baseline": baseline,
        "absolute_delta": absolute_delta,
        "relative_delta": relative_delta,
        "delta_reason": delta_reason,
        "direction_claim_supported": status == "comparable" and absolute_delta is not None,
    }


def _observation_gate(
    coverage: Mapping[str, object] | None,
    *,
    entity_type: EntityType,
    observed: bool,
) -> tuple[ComparisonStatus, list[str]]:
    if coverage is None:
        return "unavailable", ["coverage_missing"]
    hard_reasons = _coverage_hard_reasons(coverage, side="current")
    if hard_reasons:
        return "unavailable", sorted(set(hard_reasons))
    provisional: list[str] = []
    if coverage["event_time_coverage"] != "complete":
        provisional.append("event_time_coverage_partial")
    if coverage["search_has_next_truncates_window"] is True:
        provisional.append("search_has_next_truncates_window")
    if (
        entity_type == "comment"
        and coverage["comment_coverage_status"] != "thread_complete"
    ):
        provisional.append("comment_coverage_not_thread_complete")
    if provisional and not observed:
        provisional.append("observation_absent_under_incomplete_coverage")
        return "unavailable", sorted(set(provisional))
    if provisional:
        return "provisional_observed_sample", sorted(set(provisional))
    return "comparable", []


def _gated_metric_observation(
    entities: Sequence[_Entity],
    *,
    entity_type: EntityType,
    metric_name: MetricName,
    coverage: Mapping[str, object] | None,
) -> dict[str, object]:
    observed = any(
        entity.entity_type == entity_type and _is_momcozy_entity(entity)
        for entity in entities
    )
    status, reasons = _observation_gate(
        coverage,
        entity_type=entity_type,
        observed=observed,
    )
    metric = (
        _null_metric(metric_name)
        if status == "unavailable"
        else _metric_for_type(
            entities,
            entity_type=entity_type,
            metric_name=metric_name,
        )
    )
    return {
        **metric,
        "observation_status": status,
        "reason_codes": reasons,
    }


def _gated_momcozy_metric_by_type(
    entities: Sequence[_Entity],
    *,
    metric_name: MetricName,
    coverage: Mapping[str, object] | None,
) -> dict[str, object]:
    result: dict[str, object] = {
        entity_type: _gated_metric_observation(
            entities,
            entity_type=cast(EntityType, entity_type),
            metric_name=metric_name,
            coverage=coverage,
        )
        for entity_type in ("post", "comment")
    }
    result["combined"] = {
        "supported": False,
        "reason": "posts_and_comments_are_separate_entities_no_weighting_contract",
        "value": None,
    }
    return result


def _coverage_for_window(
    coverage_index: Mapping[tuple[str, str], dict[str, object]],
    window: PeriodWindow,
) -> dict[str, object] | None:
    return coverage_index.get(window.key)


def _timeline(
    entities: Sequence[_Entity],
    window: PeriodWindow,
    *,
    period: Period,
) -> list[dict[str, object]]:
    delta = timedelta(hours=1) if period == "daily" else timedelta(days=1)
    output: list[dict[str, object]] = []
    start = window.start_utc
    while start < window.end_utc:
        end = min(start + delta, window.end_utc)
        bucket = [
            entity
            for entity in entities
            if start <= entity.event_created_at_utc < end
        ]
        post_count = sum(entity.entity_type == "post" for entity in bucket)
        comment_count = sum(entity.entity_type == "comment" for entity in bucket)
        sentiment = Counter(entity.sentiment for entity in bucket)
        output.append(
            {
                "bucket_start_utc": _iso_utc(start),
                "bucket_end_utc": _iso_utc(end),
                "bucket_start_local": start.astimezone(TIMEZONE).isoformat(),
                "posts": post_count,
                "voc_comments": comment_count,
                "observed_entities": post_count + comment_count,
                "sentiment_counts": {
                    label: sentiment[label] for label in SENTIMENTS
                },
            }
        )
        start = end
    return output


def _communities(entities: Sequence[_Entity]) -> list[dict[str, object]]:
    grouped: dict[str, list[_Entity]] = defaultdict(list)
    for entity in entities:
        grouped[entity.subreddit].append(entity)
    output: list[dict[str, object]] = []
    for subreddit, rows in grouped.items():
        posts = [entity for entity in rows if entity.entity_type == "post"]
        comments = [entity for entity in rows if entity.entity_type == "comment"]
        output.append(
            {
                "subreddit": subreddit,
                "posts": len(posts),
                "voc_comments": len(comments),
                "observed_entities": len(rows),
                "sentiment_counts": dict(Counter(entity.sentiment for entity in rows)),
                "negative_share": {
                    "numerator": sum(entity.sentiment == "negative" for entity in rows),
                    "denominator": len(rows),
                    "value": round(
                        sum(entity.sentiment == "negative" for entity in rows) / len(rows),
                        6,
                    ),
                },
            }
        )
    return sorted(output, key=lambda row: (-cast(int, row["observed_entities"]), cast(str, row["subreddit"])))


def _topics(entities: Sequence[_Entity]) -> list[dict[str, object]]:
    posts = [entity for entity in entities if entity.entity_type == "post"]
    counts = Counter(entity.topic or "unclassified" for entity in posts)
    return [
        {
            "topic": topic,
            "post_entities": count,
            "share": {
                "numerator": count,
                "denominator": len(posts),
                "value": round(count / len(posts), 6) if posts else None,
            },
        }
        for topic, count in counts.most_common()
    ]


def _pain_points(entities: Sequence[_Entity]) -> list[dict[str, object]]:
    post_counts: Counter[str] = Counter()
    comment_counts: Counter[str] = Counter()
    for entity in entities:
        target = post_counts if entity.entity_type == "post" else comment_counts
        target.update(set(entity.pain_points))
    denominator = len(entities)
    values = set(post_counts) | set(comment_counts)
    return [
        {
            "pain_point": pain_point,
            "post_entities": post_counts[pain_point],
            "comment_entities": comment_counts[pain_point],
            "total_entities": post_counts[pain_point] + comment_counts[pain_point],
            "share": {
                "numerator": post_counts[pain_point] + comment_counts[pain_point],
                "denominator": denominator,
                "value": (
                    round(
                        (post_counts[pain_point] + comment_counts[pain_point])
                        / denominator,
                        6,
                    )
                    if denominator
                    else None
                ),
            },
        }
        for pain_point in sorted(
            values,
            key=lambda item: (-(post_counts[item] + comment_counts[item]), item),
        )
    ]


def _brand_mentions(entities: Sequence[_Entity]) -> list[dict[str, object]]:
    posts = [entity for entity in entities if entity.entity_type == "post"]
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for entity in posts:
        for brand in set(entity.brand_names):
            key = _normalise_brand(brand)
            counts[key] += 1
            display.setdefault(key, brand)
    return [
        {
            "brand": display[key],
            "sample_mention_posts": count,
            "sample_mention_share": {
                "numerator": count,
                "denominator": len(posts),
                "value": round(count / len(posts), 6) if posts else None,
            },
            "metric_label": "sample_mention_posts",
        }
        for key, count in counts.most_common()
    ]


def _shift_period_window(
    period: Period, window: PeriodWindow, offset: int
) -> PeriodWindow:
    start_date = window.start_local.date()
    if period == "daily":
        return _daily_window(start_date + timedelta(days=offset))
    if period == "weekly":
        return _weekly_window(start_date + timedelta(days=7 * offset))
    return _monthly_window(_add_months(start_date.replace(day=1), offset))


def _window_set_from_current(
    period: Period, current: PeriodWindow
) -> PeriodWindowSet:
    previous = _shift_period_window(period, current, -1)
    if period == "daily":
        yoy = _daily_window(_shift_year(current.start_local.date(), -1))
        trend = tuple(
            _shift_period_window(period, current, -offset)
            for offset in reversed(range(14))
        )
    elif period == "weekly":
        yoy = _weekly_window(current.start_local.date() - timedelta(days=364))
        trend = tuple(
            _shift_period_window(period, current, -offset)
            for offset in reversed(range(13))
        )
    else:
        yoy = _monthly_window(_shift_year(current.start_local.date(), -1))
        trend = tuple(
            _shift_period_window(period, current, -offset)
            for offset in reversed(range(12))
        )
    return PeriodWindowSet(
        current=current,
        previous=previous,
        year_over_year=yoy,
        trend=trend,
    )


def required_report_windows(as_of_utc: datetime) -> tuple[PeriodWindow, ...]:
    """Return every distinct window needed by current and archive booklets."""

    report_windows = build_period_windows(as_of_utc)
    unique: dict[tuple[str, str], PeriodWindow] = {}
    for period in PERIODS:
        typed_period = cast(Period, period)
        current = report_windows[typed_period]
        archive = _window_set_from_current(typed_period, current.previous)
        for window_set in (current, archive):
            for window in (
                window_set.current,
                window_set.previous,
                window_set.year_over_year,
                *window_set.trend,
            ):
                unique[window.key] = window
    return tuple(
        sorted(unique.values(), key=lambda window: (window.start_utc, window.end_utc))
    )


def _overall_comparison_status(comparisons: Iterable[Mapping[str, object]]) -> str:
    statuses = {cast(str, item["comparison_status"]) for item in comparisons}
    if "unavailable" in statuses:
        return "unavailable"
    if "provisional_observed_sample" in statuses:
        return "provisional_observed_sample"
    return "comparable"


def _trend_contract(
    entities: Sequence[_Entity],
    windows: Sequence[PeriodWindow],
    *,
    period: Period,
    coverage_index: Mapping[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    points: list[dict[str, object]] = []
    adjacent_negative: list[dict[str, object]] = []
    adjacent_volume: list[dict[str, object]] = []
    previous_window: PeriodWindow | None = None
    previous_entities: list[_Entity] = []
    for window in windows:
        current_entities = _window_entities(entities, window)
        current_coverage = _coverage_for_window(coverage_index, window)
        negative_observations = {
            entity_type: _gated_metric_observation(
                current_entities,
                entity_type=cast(EntityType, entity_type),
                metric_name="negative_evidence_share",
                coverage=current_coverage,
            )
            for entity_type in ("post", "comment")
        }
        volume_observations = {
            entity_type: _gated_metric_observation(
                current_entities,
                entity_type=cast(EntityType, entity_type),
                metric_name="observed_count",
                coverage=current_coverage,
            )
            for entity_type in ("post", "comment")
        }
        point: dict[str, object] = {
            "window": window.to_record(),
            # Legacy aliases remain negative-evidence-share observations.
            "post": negative_observations["post"],
            "comment": negative_observations["comment"],
            "negative_evidence_share": negative_observations,
            "observed_count": volume_observations,
            "coverage_status": (
                current_coverage["event_time_coverage"]
                if current_coverage is not None
                else "coverage_missing"
            ),
        }
        if previous_window is None:
            point["change_from_previous"] = None
            point["observed_count_change_from_previous"] = None
        else:
            negative_change = {
                entity_type: _period_comparison(
                    current_entities=current_entities,
                    baseline_entities=previous_entities,
                    current_coverage=current_coverage,
                    baseline_coverage=_coverage_for_window(
                        coverage_index, previous_window
                    ),
                    entity_type=cast(EntityType, entity_type),
                    comparison_type="trend_period_over_period",
                )
                for entity_type in ("post", "comment")
            }
            volume_change = {
                entity_type: _period_comparison(
                    current_entities=current_entities,
                    baseline_entities=previous_entities,
                    current_coverage=current_coverage,
                    baseline_coverage=_coverage_for_window(
                        coverage_index, previous_window
                    ),
                    entity_type=cast(EntityType, entity_type),
                    comparison_type="trend_period_over_period",
                    metric_name="observed_count",
                )
                for entity_type in ("post", "comment")
            }
            point["change_from_previous"] = negative_change
            point["observed_count_change_from_previous"] = volume_change
            adjacent_negative.extend(negative_change.values())
            adjacent_volume.extend(volume_change.values())
        points.append(point)
        previous_window = window
        previous_entities = current_entities
    negative_direction_supported = bool(adjacent_negative) and all(
        item["comparison_status"] == "comparable"
        for item in adjacent_negative
    )
    volume_direction_supported = bool(adjacent_volume) and all(
        item["comparison_status"] == "comparable" for item in adjacent_volume
    )
    return {
        "period": period,
        "point_count": len(points),
        "points": points,
        "direction_claim_supported": (
            negative_direction_supported and volume_direction_supported
        ),
        "direction_claim_supported_by_metric": {
            "negative_evidence_share": negative_direction_supported,
            "observed_count": volume_direction_supported,
        },
        "interpretation_boundary": (
            "trend_points_are_observations;direction_requires_all_adjacent_"
            "comparisons_to_be_comparable"
        ),
    }


def _report_display_name(period: Period, collection: str, window: PeriodWindow) -> str:
    local_start = window.start_local.date()
    local_end = (window.end_local - timedelta(microseconds=1)).date()
    prefix = {"daily": "日报", "weekly": "周报", "monthly": "月报"}[period]
    suffix = "当前闭合期" if collection == "current" else "归档"
    if period == "daily":
        span = local_start.isoformat()
    elif period == "weekly":
        span = f"{local_start.isoformat()} 至 {local_end.isoformat()}"
    else:
        span = local_start.strftime("%Y-%m")
    return f"{prefix} · {suffix} · {span}"


def _archive_path(period: Period, window: PeriodWindow) -> str:
    start = window.start_local.date()
    end = (window.end_local - timedelta(microseconds=1)).date()
    if period == "daily":
        return f"archive/daily-{start.isoformat()}.json"
    if period == "weekly":
        return f"archive/weekly-{start.isoformat()}_{end.isoformat()}.json"
    return f"archive/monthly-{start.strftime('%Y-%m')}.json"


def _build_report(
    *,
    period: Period,
    collection: str,
    window_set: PeriodWindowSet,
    entities: Sequence[_Entity],
    rules: Mapping[str, dict[str, object]],
    promoted_tag_ids: set[str],
    risk_gate_policy: Mapping[str, object] | None,
    coverage_index: Mapping[tuple[str, str], dict[str, object]],
    reports_dataset_version: str,
    as_of_utc: datetime,
    base_identity: Mapping[str, object],
) -> dict[str, object]:
    current_entities = _window_entities(entities, window_set.current)
    previous_entities = _window_entities(entities, window_set.previous)
    yoy_entities = _window_entities(entities, window_set.year_over_year)
    current_coverage = _coverage_for_window(coverage_index, window_set.current)
    comparisons: dict[str, dict[str, dict[str, object]]] = {
        "previous_period": {
            entity_type: _period_comparison(
                current_entities=current_entities,
                baseline_entities=previous_entities,
                current_coverage=current_coverage,
                baseline_coverage=_coverage_for_window(
                    coverage_index, window_set.previous
                ),
                entity_type=entity_type,
                comparison_type={
                    "daily": "day_over_day",
                    "weekly": "week_over_week",
                    "monthly": "month_over_month",
                }[period],
            )
            for entity_type in ("post", "comment")
        },
        "year_over_year": {
            entity_type: _period_comparison(
                current_entities=current_entities,
                baseline_entities=yoy_entities,
                current_coverage=current_coverage,
                baseline_coverage=_coverage_for_window(
                    coverage_index, window_set.year_over_year
                ),
                entity_type=entity_type,
                comparison_type="year_over_year",
            )
            for entity_type in ("post", "comment")
        },
    }
    observed_count_comparisons: dict[
        str, dict[str, dict[str, object]]
    ] = {
        "previous_period": {
            entity_type: _period_comparison(
                current_entities=current_entities,
                baseline_entities=previous_entities,
                current_coverage=current_coverage,
                baseline_coverage=_coverage_for_window(
                    coverage_index, window_set.previous
                ),
                entity_type=cast(EntityType, entity_type),
                comparison_type={
                    "daily": "day_over_day",
                    "weekly": "week_over_week",
                    "monthly": "month_over_month",
                }[period],
                metric_name="observed_count",
            )
            for entity_type in ("post", "comment")
        },
        "year_over_year": {
            entity_type: _period_comparison(
                current_entities=current_entities,
                baseline_entities=yoy_entities,
                current_coverage=current_coverage,
                baseline_coverage=_coverage_for_window(
                    coverage_index, window_set.year_over_year
                ),
                entity_type=cast(EntityType, entity_type),
                comparison_type="year_over_year",
                metric_name="observed_count",
            )
            for entity_type in ("post", "comment")
        },
    }
    all_comparisons: list[dict[str, object]] = [
        comparison
        for metric_groups in (comparisons, observed_count_comparisons)
        for group in metric_groups.values()
        for comparison in group.values()
    ]
    facts = _risk_facts(current_entities, rules)
    themes = _build_risk_themes(
        facts,
        promoted_tag_ids=promoted_tag_ids,
        risk_gate_policy=risk_gate_policy,
    )
    posts = [entity for entity in current_entities if entity.entity_type == "post"]
    comments = [
        entity for entity in current_entities if entity.entity_type == "comment"
    ]
    report_id = (
        f"{collection}-{period}-"
        f"{window_set.current.start_local.date().isoformat()}"
    )
    coverage_status = (
        cast(str, current_coverage["event_time_coverage"])
        if current_coverage is not None
        else "coverage_missing"
    )
    return {
        "schema_version": "reddit_voc_report_v1",
        "contract_extension": "reddit_voc_risk_report_v2",
        "identity": {
            "dataset_version": reports_dataset_version,
            "report_id": report_id,
            "period": period,
            "window_mode": "calendar_closed",
            "display_name": _report_display_name(
                period, collection, window_set.current
            ),
        },
        "window": {
            **window_set.current.to_record(),
            "as_of_utc": _iso_utc(as_of_utc),
            "bucket_grain": "hour" if period == "daily" else "day",
            "coverage_status": coverage_status,
            "comparison_status": _overall_comparison_status(all_comparisons),
        },
        "headline": {
            "posts": len(posts),
            "voc_comments": len(comments),
            "observed_entities": len(current_entities),
            "post_sentiment": _sentiment_summary(posts),
            "comment_sentiment": _sentiment_summary(comments),
            "quarantined_comments_in_base_snapshot": base_identity.get(
                "quarantined_comments"
            ),
            "quarantined_comments_counted": 0,
        },
        "observed_timeline": _timeline(
            current_entities, window_set.current, period=period
        ),
        "communities": _communities(current_entities),
        "topics": _topics(current_entities),
        "pain_points": _pain_points(current_entities),
        "brand_mentions": _brand_mentions(current_entities),
        # Kept for old consumers. New risk evidence is ID-only and lives in the
        # command-center contract; no raw excerpt is copied here.
        "promoted_signals": [],
        "attention_items": [],
        "evidence_posts": [],
        "capabilities": {
            "supported": [
                "observed_entity_counts",
                "momcozy_negative_evidence_share",
                "momcozy_observed_count",
                "governed_risk_priority",
                "category_product_family_spu_analysis",
                "category_product_family_spu_period_metrics",
            ],
            "conditionally_supported": [
                "period_comparison_when_coverage_gate_passes",
                "trend_direction_when_all_adjacent_gates_pass",
            ],
            "unsupported": [
                "market_share",
                "sov",
                "sales_conversion",
                "roi",
                "nps",
                "response_time",
                "action_completion_rate",
            ],
        },
        "interpretation_boundaries": {
            "counts_are_observed_entities_not_users": True,
            "comments_use_own_event_created_at_window": True,
            "posts_and_comments_separate_by_default": True,
            "combined_view_supported": False,
            "brand_metric_label": "sample_brand_bound_observed_entities",
            "market_share_supported": False,
            "roi_supported": False,
            "nps_supported": False,
            "trend_claim_supported": all(
                item["comparison_status"] == "comparable"
                for item in all_comparisons
            ),
            "momcozy_specific_requires_controlled_binding": True,
            "competitors_are_context_only": True,
            "legacy_brand_binding_mapping_applied": False,
        },
        "runtime_boundaries": {
            "delivery_mode": "versioned_static_snapshot",
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "webhook_send": False,
            "deploy": False,
            "schedule_change": False,
        },
        "momcozy_metrics": {
            "observed_count": _gated_momcozy_metric_by_type(
                current_entities,
                metric_name="observed_count",
                coverage=current_coverage,
            ),
            "negative_evidence_share": _gated_momcozy_metric_by_type(
                current_entities,
                metric_name="negative_evidence_share",
                coverage=current_coverage,
            ),
            "risk_theme_count": len(themes),
            "high_priority_risk_theme_count": (
                sum(
                    theme["effective_priority"] in {"P0", "P1"}
                    for theme in themes
                )
                if risk_gate_policy is not None
                and risk_gate_policy["status"] == "frozen"
                else None
            ),
        },
        "risk_themes": themes,
        "product_analysis": _build_product_analysis(
            current_entities, facts=facts, themes=themes
        ),
        "product_period_analysis": _build_product_period_analysis(
            entities=entities,
            period=period,
            window_set=window_set,
            coverage_index=coverage_index,
        ),
        "competitor_context": _competitor_context(
            current_entities,
            previous_entities=previous_entities,
            year_over_year_entities=yoy_entities,
            current_coverage=current_coverage,
            previous_coverage=_coverage_for_window(
                coverage_index, window_set.previous
            ),
            year_over_year_coverage=_coverage_for_window(
                coverage_index, window_set.year_over_year
            ),
            previous_comparison_type={
                "daily": "day_over_day",
                "weekly": "week_over_week",
                "monthly": "month_over_month",
            }[period],
        ),
        "period_comparisons": comparisons,
        "observed_count_comparisons": observed_count_comparisons,
        "trend": _trend_contract(
            entities,
            window_set.trend,
            period=period,
            coverage_index=coverage_index,
        ),
    }


def _report_descriptor(path: str, report: Mapping[str, object]) -> dict[str, object]:
    identity = cast(dict[str, object], report["identity"])
    window = cast(dict[str, object], report["window"])
    headline = cast(dict[str, object], report["headline"])
    return {
        "report_id": identity["report_id"],
        "period": identity["period"],
        "window_mode": identity["window_mode"],
        "display_name": identity["display_name"],
        "path": path,
        "start_utc": window["start_utc"],
        "end_utc": window["end_utc"],
        "coverage_status": window["coverage_status"],
        "comparison_status": window["comparison_status"],
        "posts": headline["posts"],
        "voc_comments": headline["voc_comments"],
    }


def _build_reports_bundle(
    *,
    entities: Sequence[_Entity],
    rules: Mapping[str, dict[str, object]],
    promoted_tag_ids: set[str],
    risk_gate_policy: Mapping[str, object] | None,
    coverage_index: Mapping[tuple[str, str], dict[str, object]],
    reports_dataset_version: str,
    as_of_utc: datetime,
    base_identity: Mapping[str, object],
) -> dict[str, object]:
    windows = build_period_windows(as_of_utc)
    current: dict[str, dict[str, object]] = {}
    archive: dict[str, dict[str, object]] = {}
    by_path: dict[str, dict[str, object]] = {}
    current_descriptors: dict[str, dict[str, object]] = {}
    archive_descriptors: dict[str, dict[str, object]] = {}
    for period in PERIODS:
        typed_period = cast(Period, period)
        current_report = _build_report(
            period=typed_period,
            collection="current",
            window_set=windows[typed_period],
            entities=entities,
            rules=rules,
            promoted_tag_ids=promoted_tag_ids,
            risk_gate_policy=risk_gate_policy,
            coverage_index=coverage_index,
            reports_dataset_version=reports_dataset_version,
            as_of_utc=as_of_utc,
            base_identity=base_identity,
        )
        archive_window_set = _window_set_from_current(
            typed_period, windows[typed_period].previous
        )
        archive_report = _build_report(
            period=typed_period,
            collection="archive",
            window_set=archive_window_set,
            entities=entities,
            rules=rules,
            promoted_tag_ids=promoted_tag_ids,
            risk_gate_policy=risk_gate_policy,
            coverage_index=coverage_index,
            reports_dataset_version=reports_dataset_version,
            as_of_utc=as_of_utc,
            base_identity=base_identity,
        )
        current_path = f"current/{period}.json"
        archive_path = _archive_path(typed_period, archive_window_set.current)
        current[period] = current_report
        archive[period] = archive_report
        by_path[current_path] = current_report
        by_path[archive_path] = archive_report
        current_descriptors[period] = _report_descriptor(
            current_path, current_report
        )
        archive_descriptors[period] = _report_descriptor(
            archive_path, archive_report
        )
    return {
        "schema_version": "reddit_voc_report_booklets_v2",
        "dataset_version": reports_dataset_version,
        "index": {
            "schema_version": "reddit_voc_report_index_v1",
            "contract_extension": "reddit_voc_report_index_v2",
            "dataset_version": reports_dataset_version,
            "as_of_utc": _iso_utc(as_of_utc),
            "timezone": TIMEZONE_NAME,
            "current": current_descriptors,
            "archive": archive_descriptors,
        },
        "current": current,
        "archive": archive,
        "by_path": by_path,
    }


def _closed_rolling_30_day_window(as_of_utc: datetime) -> PeriodWindow:
    local_end = _local_midnight(as_of_utc.astimezone(TIMEZONE).date())
    return _window_from_local(local_end - timedelta(days=30), local_end)


def _command_center(
    *,
    entities: Sequence[_Entity],
    rules: Mapping[str, dict[str, object]],
    promoted_tag_ids: set[str],
    risk_gate_policy: Mapping[str, object] | None,
    reports: Mapping[str, object],
    as_of_utc: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    command_window = _closed_rolling_30_day_window(as_of_utc)
    command_entities = _window_entities(entities, command_window)
    facts = _risk_facts(command_entities, rules)
    themes = _build_risk_themes(
        facts,
        promoted_tag_ids=promoted_tag_ids,
        risk_gate_policy=risk_gate_policy,
    )
    product_analysis = _build_product_analysis(
        command_entities, facts=facts, themes=themes
    )
    high_priority_value: int | None
    if risk_gate_policy is not None and risk_gate_policy["status"] == "frozen":
        high_priority_value = sum(
            theme["effective_priority"] in {"P0", "P1"} for theme in themes
        )
        high_priority_status = "governed"
    else:
        high_priority_value = None
        high_priority_status = "unavailable_unfrozen_evidence_threshold"
    priority_counts = Counter(
        cast(str, theme["effective_priority"]) for theme in themes
    )
    reports_current = cast(dict[str, object], reports["current"])
    daily = cast(dict[str, object], reports_current["daily"])
    daily_comparisons = cast(dict[str, object], daily["period_comparisons"])
    return (
        {
            "schema_version": "reddit_voc_risk_command_center_v1",
            "decision_subject": {
                "brand_id": "momcozy",
                "brand_role": "primary",
                "competitors_role": "comparison_context_only",
            },
            "window": {
                **command_window.to_record(),
                "window_mode": "rolling_30_closed_days",
            },
            "primary_kpis": {
                "high_priority_risk_themes": {
                    "value": high_priority_value,
                    "status": high_priority_status,
                    "included_priorities": ["P0", "P1"],
                    "unit": "distinct_governed_risk_theme",
                },
                "negative_evidence_share": _momcozy_share_by_type(command_entities),
                "risk_momentum": {
                    "source_report": "daily",
                    "previous_period": daily_comparisons["previous_period"],
                    "year_over_year": daily_comparisons["year_over_year"],
                    "interpretation_boundary": (
                        "direction_is_supported_only_when_comparison_status_is_comparable"
                    ),
                },
            },
            "priority_distribution": {
                priority: priority_counts[priority]
                for priority in (*PRIORITIES, "insufficient")
            },
            "risk_themes": themes,
            "competitor_context": _competitor_context(command_entities),
            "evidence_boundaries": {
                "default_priority_inherited_from_dictionary": True,
                "risk_level_to_priority_mapping_applied": False,
                "arbitrary_score_supported": False,
                "posts_and_comments_separate_by_default": True,
                "combined_view_supported": False,
                "actions_are_recommendations_only": True,
            },
        },
        product_analysis,
    )


def _control_evidence(
    *,
    base_identity: Mapping[str, object],
    coverage_ledger_version: str | None,
    semantic_governance_version: str,
    risk_gate_policy: Mapping[str, object] | None,
) -> dict[str, object]:
    source_cutoffs = base_identity.get("source_cutoffs")
    safe_cutoffs = (
        deepcopy(source_cutoffs)
        if isinstance(source_cutoffs, dict)
        and all(isinstance(key, str) for key in source_cutoffs)
        else None
    )
    return {
        "schema_version": "reddit_voc_control_evidence_v1",
        "evidence_level": "offline_snapshot_contract_build",
        "base_dataset_version": base_identity["dataset_version"],
        "base_manifest_sha256": base_identity["manifest_sha256"],
        "base_generated_at_utc": base_identity["generated_at_utc"],
        "source_cutoffs": safe_cutoffs,
        "semantic_governance_version": semantic_governance_version,
        "coverage_ledger_version": coverage_ledger_version,
        "risk_gate_policy_version": (
            risk_gate_policy["policy_version"]
            if risk_gate_policy is not None
            else None
        ),
        "risk_gate_policy_status": (
            risk_gate_policy["status"] if risk_gate_policy is not None else "missing"
        ),
        "recommendations_only": True,
        "external_action_ledger_available": False,
        "action_completion_supported": False,
        "release_switch_executed": False,
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "deploy": False,
    }


def build_contract_bundle(
    *,
    posts: Sequence[Mapping[str, object]],
    comments: Sequence[Mapping[str, object]],
    tag_dictionary: Mapping[str, object],
    semantic_governance: Mapping[str, object],
    base_identity: Mapping[str, object],
    insights_dataset_version: str,
    reports_dataset_version: str,
    as_of_utc: datetime,
    coverage_ledger: Mapping[str, object] | None,
    risk_gate_policy: Mapping[str, object] | None,
    legacy_insights: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build A/B/C analytical contracts from privacy-minimized records.

    ``legacy_insights`` is an optional compatibility carrier.  Only the four
    historical UI fields are copied; no legacy raw evidence or runtime claim is
    imported into the new decision contract.
    """

    if as_of_utc.tzinfo is None:
        raise InputContractError(
            "build identity input contract failed", invalid_fields=["as_of_utc"]
        )
    if not _is_non_empty_string(insights_dataset_version):
        raise InputContractError(
            "build identity input contract failed",
            invalid_fields=["insights_dataset_version"],
        )
    if not _is_non_empty_string(reports_dataset_version):
        raise InputContractError(
            "build identity input contract failed",
            invalid_fields=["reports_dataset_version"],
        )
    _validate_base_identity(base_identity)
    rules = _tag_rules(tag_dictionary)
    promoted, held, semantic_version = _semantic_sets(
        semantic_governance, rules=rules
    )
    policy = _validate_risk_policy(risk_gate_policy)
    entities, post_coverage = _normalise_entity_records(
        posts,
        comments,
        rules=rules,
        promoted_tag_ids=promoted,
    )
    coverage_index, coverage_version = _validate_coverage_ledger(coverage_ledger)
    reports = _build_reports_bundle(
        entities=entities,
        rules=rules,
        promoted_tag_ids=promoted,
        risk_gate_policy=policy,
        coverage_index=coverage_index,
        reports_dataset_version=reports_dataset_version,
        as_of_utc=as_of_utc.astimezone(timezone.utc),
        base_identity=base_identity,
    )
    command, product_analysis = _command_center(
        entities=entities,
        rules=rules,
        promoted_tag_ids=promoted,
        risk_gate_policy=policy,
        reports=reports,
        as_of_utc=as_of_utc.astimezone(timezone.utc),
    )
    control = _control_evidence(
        base_identity=base_identity,
        coverage_ledger_version=coverage_version,
        semantic_governance_version=semantic_version,
        risk_gate_policy=policy,
    )
    insights: dict[str, object] = {
        "schema_version": "reddit_voc_insights_v2",
        "dataset_version": insights_dataset_version,
        "base_dataset_version": base_identity["dataset_version"],
        "generated_at_utc": _iso_utc(as_of_utc),
    }
    if legacy_insights is None:
        insights.update(
            {
                "headline": {
                    "status": "unavailable",
                    "reason": "legacy_insights_not_supplied",
                },
                "signals": [],
                "reference_dimensions": {},
                "held_tags": [],
            }
        )
        legacy_status = "not_supplied"
    else:
        missing_legacy = [
            field for field in LEGACY_INSIGHTS_FIELDS if field not in legacy_insights
        ]
        if missing_legacy:
            raise InputContractError(
                "legacy insights compatibility contract failed",
                missing_fields=[
                    f"legacy_insights.{field}" for field in missing_legacy
                ],
            )
        for field in LEGACY_INSIGHTS_FIELDS:
            insights[field] = deepcopy(legacy_insights[field])
        compatibility_contract = legacy_insights.get("compatibility_contract")
        legacy_status = (
            compatibility_contract.get("status")
            if isinstance(compatibility_contract, Mapping)
            else "preserved_fields_only"
        )

    legacy_interpretation = (
        legacy_insights.get("interpretation_boundaries", {})
        if legacy_insights is not None
        else {}
    )
    legacy_boundaries = (
        legacy_insights.get("boundaries", {})
        if legacy_insights is not None
        else {}
    )
    insights.update(
        {
            "interpretation_boundaries": {
                **(
                    deepcopy(legacy_interpretation)
                    if isinstance(legacy_interpretation, dict)
                    else {}
                ),
                "market_share_supported": False,
                "roi_supported": False,
                "nps_supported": False,
                "response_time_supported": False,
                "posts_and_comments_separate_by_default": True,
                "combined_view_supported": False,
                "competitors_are_context_only": True,
                "consumer_card_is_reference_not_user_identity": True,
            },
            "boundaries": {
                **(
                    deepcopy(legacy_boundaries)
                    if isinstance(legacy_boundaries, dict)
                    else {}
                ),
                "scope": "momcozy_risk_command_center_and_report_booklets",
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "live_send": False,
                "deploy": False,
            },
            "legacy_compatibility": {
                "status": legacy_status,
                "preserved_fields": list(LEGACY_INSIGHTS_FIELDS),
                "legacy_brand_binding_mapping_applied": False,
                **(
                    deepcopy(dict(compatibility_contract))
                    if legacy_insights is not None
                    and isinstance(
                        legacy_insights.get("compatibility_contract"), Mapping
                    )
                    else {}
                ),
            },
            "input_contract": {
                "status": "passed",
                "required_event_time_field": "event_created_at_utc",
                "brand_binding_values": sorted(BRAND_BINDINGS),
                "post_count": sum(entity.entity_type == "post" for entity in entities),
                "comment_count": sum(
                    entity.entity_type == "comment" for entity in entities
                ),
                "comment_coverage_counts": dict(
                    sorted(Counter(post_coverage.values()).items())
                ),
                "promoted_tag_ids": sorted(promoted),
                "held_tag_ids": sorted(held),
            },
            "risk_command_center": command,
            "product_analysis": product_analysis,
            "report_booklets": {
                "schema_version": reports["schema_version"],
                "dataset_version": reports_dataset_version,
                "timezone": TIMEZONE_NAME,
                "index": deepcopy(reports["index"]),
            },
            "control_evidence": control,
        }
    )
    return {
        "schema_version": "reddit_voc_risk_report_contract_bundle_v1",
        "insights": insights,
        "reports": reports,
    }
