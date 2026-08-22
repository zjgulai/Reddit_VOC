from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable


EXPECTED_COLUMNS = (
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

KNOWN_SCOPES = {
    "L0-通用",
    "L1-品线专属",
    "L2-品类专属",
    "L2-SPU专属",
}
KNOWN_SENTIMENTS = {"正向", "中性", "负向"}
NEGATION_TOKENS = {
    "not",
    "never",
    "no",
    "cannot",
    "can't",
    "cant",
    "isn't",
    "isnt",
    "wasn't",
    "wasnt",
    "doesn't",
    "doesnt",
    "didn't",
    "didnt",
    "hardly",
    "barely",
}
SCOPE_RANK = {
    "L0-通用": 0,
    "L1-品线专属": 1,
    "L2-品类专属": 2,
    "L2-SPU专属": 3,
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@lru_cache(maxsize=None)
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(_normalize(phrase)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.I)


def _is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 64) : start]
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", prefix.casefold())[-4:]
    return any(token in NEGATION_TOKENS for token in tokens)


def _brand_keyword_is_alias(rule: "TagRule", phrase: str) -> bool:
    canonical = re.sub(r"[^a-z0-9]", "", _normalize(rule.name_en))
    candidate = re.sub(r"[^a-z0-9]", "", phrase)
    return len(candidate) >= 4 and (
        candidate in canonical or canonical in candidate
    )


def _confirmation_gate(rule: "TagRule", phrase: str) -> tuple[bool, str | None]:
    if rule.theme == "品牌提及":
        if _brand_keyword_is_alias(rule, phrase):
            return True, None
        return False, "brand_keyword_is_not_brand_alias"
    tokens = re.findall(r"[a-z0-9]+", phrase)
    if len(tokens) < 2:
        return False, "single_token_keyword"
    return True, None


@dataclass(frozen=True)
class TagRule:
    tag_id: str
    name_cn: str
    name_en: str
    sentiment: str
    theme: str
    tag_scope: str
    product_line: str
    voc_category: str
    spu_id: str
    keywords: tuple[str, ...]
    fields: tuple[tuple[str, str], ...]

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = dict(self.fields)
        record["keywords_en"] = list(self.keywords)
        return record


class TagDictionary:
    """Validated deterministic matcher for the governed VOC tag dictionary.

    Only unambiguous keyword phrases become provisional lexical rule matches. Shared phrases are
    retained as candidates so downstream metrics never silently choose between
    conflicting dictionary rows.
    """

    def __init__(self, rules: Iterable[TagRule], *, version: str) -> None:
        self.rules = tuple(rules)
        self.version = version
        self.by_id = {rule.tag_id: rule for rule in self.rules}
        if len(self.by_id) != len(self.rules):
            raise ValueError("tag_id must be unique")
        self.model_spu_aliases = self._derive_model_spu_aliases()
        self._selection_cache: dict[
            tuple[str, str, tuple[str, ...]], tuple[TagRule, ...]
        ] = {}
        self._phrase_rule_cache: dict[
            tuple[str, str, tuple[str, ...]], dict[str, tuple[TagRule, ...]]
        ] = {}

    @classmethod
    def from_csv(cls, path: Path, *, version: str | None = None) -> "TagDictionary":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
                raise ValueError(
                    "tag dictionary columns do not match the governed v6.3 contract"
                )
            rows = list(reader)

        rules: list[TagRule] = []
        for line_number, row in enumerate(rows, start=2):
            blank = [column for column in EXPECTED_COLUMNS if not (row[column] or "").strip()]
            if blank:
                raise ValueError(
                    f"tag dictionary line {line_number} has blank fields: {blank}"
                )
            try:
                keyword_value = json.loads(row["keywords_en"])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"tag dictionary line {line_number} keywords_en is invalid JSON"
                ) from exc
            if not isinstance(keyword_value, list) or not keyword_value or not all(
                isinstance(item, str) and item.strip() for item in keyword_value
            ):
                raise ValueError(
                    f"tag dictionary line {line_number} keywords_en must be a non-empty string list"
                )
            if row["tag_scope"] not in KNOWN_SCOPES:
                raise ValueError(
                    f"tag dictionary line {line_number} has unknown tag_scope"
                )
            if row["sentiment"] not in KNOWN_SENTIMENTS:
                raise ValueError(
                    f"tag dictionary line {line_number} has unknown sentiment"
                )
            keywords = tuple(
                dict.fromkeys(
                    normalized
                    for item in keyword_value
                    if (normalized := _normalize(item))
                )
            )
            rules.append(
                TagRule(
                    tag_id=row["tag_id"].strip(),
                    name_cn=row["name_cn"].strip(),
                    name_en=row["name_en"].strip(),
                    sentiment=row["sentiment"].strip(),
                    theme=row["theme"].strip(),
                    tag_scope=row["tag_scope"].strip(),
                    product_line=row["product_line"].strip(),
                    voc_category=row["voc_category"].strip(),
                    spu_id=row["spu_id"].strip(),
                    keywords=keywords,
                    fields=tuple((column, row[column].strip()) for column in EXPECTED_COLUMNS),
                )
            )
        return cls(rules, version=version or path.stem)

    def _derive_model_spu_aliases(self) -> dict[str, str]:
        candidates: dict[str, set[str]] = defaultdict(set)
        for rule in self.rules:
            if rule.tag_scope != "L2-SPU专属":
                continue
            match = re.fullmatch(r"([A-Za-z]+\d+)\s+吸奶器", rule.voc_category)
            if match:
                candidates[match.group(1).casefold()].add(rule.spu_id)
        aliases: dict[str, str] = {}
        for alias, spu_ids in candidates.items():
            if len(spu_ids) != 1:
                raise ValueError(f"model alias {alias} maps to multiple SPU ids")
            aliases[alias] = next(iter(spu_ids))
        return dict(sorted(aliases.items()))

    def detect_spu_ids(self, text: str) -> list[str]:
        normalized = _normalize(text)
        detected = [
            spu_id
            for alias, spu_id in self.model_spu_aliases.items()
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized)
        ]
        return sorted(set(detected))

    def select_rules(
        self,
        *,
        product_line: str,
        voc_category: str,
        spu_ids: Iterable[str] = (),
    ) -> tuple[TagRule, ...]:
        normalized_spu_ids = tuple(sorted(set(spu_ids)))
        cache_key = (product_line, voc_category, normalized_spu_ids)
        cached = self._selection_cache.get(cache_key)
        if cached is not None:
            return cached
        selected_spu_ids = set(normalized_spu_ids)
        selected: list[TagRule] = []
        for rule in self.rules:
            if rule.tag_scope == "L0-通用":
                selected.append(rule)
            elif (
                rule.tag_scope == "L1-品线专属"
                and rule.product_line == product_line
            ):
                selected.append(rule)
            elif (
                rule.tag_scope == "L2-品类专属"
                and rule.product_line == product_line
                and rule.voc_category == voc_category
            ):
                selected.append(rule)
            elif rule.tag_scope == "L2-SPU专属" and rule.spu_id in selected_spu_ids:
                selected.append(rule)
        result = tuple(selected)
        self._selection_cache[cache_key] = result
        return result

    @staticmethod
    def _normalize_contexts(
        contexts: Iterable[tuple[str, str, Iterable[str]]],
    ) -> list[tuple[str, str, tuple[str, ...]]]:
        normalized = sorted(
            {
                (
                    product_line.strip(),
                    voc_category.strip(),
                    tuple(
                        sorted(
                            {
                                value.strip()
                                for value in spu_ids
                                if isinstance(value, str) and value.strip()
                            }
                        )
                    ),
                )
                for product_line, voc_category, spu_ids in contexts
            }
        )
        return normalized or [("", "", ())]

    def select_rules_for_contexts(
        self,
        contexts: Iterable[tuple[str, str, Iterable[str]]],
    ) -> tuple[TagRule, ...]:
        normalized_contexts = self._normalize_contexts(contexts)
        selected = {
            rule.tag_id: rule
            for product_line, voc_category, spu_ids in normalized_contexts
            for rule in self.select_rules(
                product_line=product_line,
                voc_category=voc_category,
                spu_ids=spu_ids,
            )
        }
        return tuple(selected[tag_id] for tag_id in sorted(selected))

    def _phrase_rules(
        self,
        *,
        product_line: str,
        voc_category: str,
        spu_ids: Iterable[str],
    ) -> dict[str, tuple[TagRule, ...]]:
        normalized_spu_ids = tuple(sorted(set(spu_ids)))
        cache_key = (product_line, voc_category, normalized_spu_ids)
        cached = self._phrase_rule_cache.get(cache_key)
        if cached is not None:
            return cached
        phrase_rules: dict[str, list[TagRule]] = defaultdict(list)
        for rule in self.select_rules(
            product_line=product_line,
            voc_category=voc_category,
            spu_ids=normalized_spu_ids,
        ):
            for phrase in rule.keywords:
                phrase_rules[phrase].append(rule)
        result = {
            phrase: tuple(candidate_rules)
            for phrase, candidate_rules in phrase_rules.items()
        }
        self._phrase_rule_cache[cache_key] = result
        return result

    def extract(
        self,
        text: str,
        *,
        product_line: str,
        voc_category: str,
        spu_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        normalized_text = _normalize(text)
        if spu_ids is None:
            selected_spu_ids = self.detect_spu_ids(normalized_text)
            spu_binding_mode = "dictionary_alias_legacy"
        else:
            selected_spu_ids = sorted(
                {
                    value.strip()
                    for value in spu_ids
                    if isinstance(value, str) and value.strip()
                }
            )
            spu_binding_mode = "governed_explicit"
        rules = self.select_rules(
            product_line=product_line,
            voc_category=voc_category,
            spu_ids=selected_spu_ids,
        )
        phrase_rules = self._phrase_rules(
            product_line=product_line,
            voc_category=voc_category,
            spu_ids=selected_spu_ids,
        )

        evidence_by_tag: dict[str, list[str]] = defaultdict(list)
        ambiguous: list[dict[str, Any]] = []
        negated: list[dict[str, Any]] = []
        low_specificity: list[dict[str, Any]] = []
        for phrase, candidate_rules in sorted(phrase_rules.items()):
            if phrase not in normalized_text:
                continue
            match = _phrase_pattern(phrase).search(normalized_text)
            if not match:
                continue
            candidate_ids = sorted({rule.tag_id for rule in candidate_rules})
            if _is_negated(normalized_text, match.start()):
                negated.append(
                    {"keyword": phrase, "candidate_tag_ids": candidate_ids}
                )
            elif len(candidate_ids) > 1:
                ambiguous.append(
                    {
                        "keyword": phrase,
                        "candidate_tag_ids": candidate_ids,
                        "candidate_sentiments": sorted(
                            {rule.sentiment for rule in candidate_rules}
                        ),
                    }
                )
            else:
                rule = candidate_rules[0]
                confirmed, reason = _confirmation_gate(rule, phrase)
                if confirmed:
                    evidence_by_tag[candidate_ids[0]].append(phrase)
                else:
                    low_specificity.append(
                        {
                            "keyword": phrase,
                            "candidate_tag_ids": candidate_ids,
                            "reason": reason,
                        }
                    )

        matches: list[dict[str, Any]] = []
        for tag_id, evidence in evidence_by_tag.items():
            rule = self.by_id[tag_id]
            unique_evidence = sorted(set(evidence), key=lambda item: (-len(item), item))
            matches.append(
                {
                    "tag_id": tag_id,
                    "tag_scope": rule.tag_scope,
                    "tag_sentiment": rule.sentiment,
                    "evidence_keywords": unique_evidence,
                    "evidence_count": len(unique_evidence),
                    "match_strength": "high" if len(unique_evidence) >= 2 else "medium",
                    "validation_status": "lexical_rule_match_unvalidated",
                }
            )
        matches.sort(
            key=lambda item: (
                -SCOPE_RANK[item["tag_scope"]],
                -item["evidence_count"],
                item["tag_id"],
            )
        )
        tag_ids = [item["tag_id"] for item in matches]
        brand_tag_ids = [
            tag_id for tag_id in tag_ids if self.by_id[tag_id].theme == "品牌提及"
        ]
        aspect_tag_ids = [
            tag_id for tag_id in tag_ids if self.by_id[tag_id].theme != "品牌提及"
        ]
        return {
            "dictionary_version": self.version,
            "context": {
                "product_line": product_line,
                "voc_category": voc_category,
                "detected_spu_ids": selected_spu_ids,
                "spu_binding_mode": spu_binding_mode,
            },
            "eligible_rule_count": len(rules),
            "tag_ids": tag_ids,
            "aspect_tag_ids": aspect_tag_ids,
            "brand_tag_ids": brand_tag_ids,
            "matches": matches,
            "ambiguous_keyword_matches": ambiguous,
            "negated_keyword_matches": negated,
            "low_specificity_keyword_matches": low_specificity,
            "semantic_validation_status": "not_run",
        }

    def extract_for_contexts(
        self,
        text: str,
        *,
        contexts: Iterable[tuple[str, str, Iterable[str]]],
    ) -> dict[str, Any]:
        """Extract tags under one or more governed product contexts.

        SPU IDs are always explicit in this path; the legacy naked-model alias
        detector is never consulted. An empty context list intentionally
        exposes only L0 rules.
        """

        normalized_contexts = self._normalize_contexts(contexts)

        results = [
            self.extract(
                text,
                product_line=product_line,
                voc_category=voc_category,
                spu_ids=spu_ids,
            )
            for product_line, voc_category, spu_ids in normalized_contexts
        ]
        eligible_rules = {
            rule.tag_id for rule in self.select_rules_for_contexts(normalized_contexts)
        }

        evidence_by_tag: dict[str, set[str]] = defaultdict(set)
        match_by_tag: dict[str, dict[str, Any]] = {}
        for result in results:
            for match in result["matches"]:
                tag_id = str(match["tag_id"])
                match_by_tag[tag_id] = dict(match)
                evidence_by_tag[tag_id].update(match["evidence_keywords"])

        phrase_to_tags: dict[str, set[str]] = defaultdict(set)
        for tag_id, phrases in evidence_by_tag.items():
            for phrase in phrases:
                phrase_to_tags[phrase].add(tag_id)
        cross_context_ambiguous = {
            phrase: tag_ids
            for phrase, tag_ids in phrase_to_tags.items()
            if len(tag_ids) > 1
        }
        for phrase, tag_ids in cross_context_ambiguous.items():
            for tag_id in tag_ids:
                evidence_by_tag[tag_id].discard(phrase)

        matches: list[dict[str, Any]] = []
        for tag_id, evidence in evidence_by_tag.items():
            if not evidence:
                continue
            match = match_by_tag[tag_id]
            ordered_evidence = sorted(evidence, key=lambda value: (-len(value), value))
            match["evidence_keywords"] = ordered_evidence
            match["evidence_count"] = len(ordered_evidence)
            match["match_strength"] = (
                "high" if len(ordered_evidence) >= 2 else "medium"
            )
            matches.append(match)
        matches.sort(
            key=lambda item: (
                -SCOPE_RANK[item["tag_scope"]],
                -item["evidence_count"],
                item["tag_id"],
            )
        )

        def merged_candidates(field: str) -> list[dict[str, Any]]:
            values: dict[str, dict[str, Any]] = {}
            for result in results:
                for item in result[field]:
                    key = json.dumps(
                        item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )
                    values[key] = item
            return [values[key] for key in sorted(values)]

        ambiguous = merged_candidates("ambiguous_keyword_matches")
        ambiguous.extend(
            {
                "keyword": phrase,
                "candidate_tag_ids": sorted(tag_ids),
                "candidate_sentiments": sorted(
                    {self.by_id[tag_id].sentiment for tag_id in tag_ids}
                ),
                "reason": "cross_product_context_collision",
            }
            for phrase, tag_ids in sorted(cross_context_ambiguous.items())
        )
        ambiguous.sort(
            key=lambda item: (
                str(item.get("keyword") or ""),
                tuple(item.get("candidate_tag_ids") or ()),
            )
        )
        tag_ids = [str(item["tag_id"]) for item in matches]
        brand_tag_ids = [
            tag_id for tag_id in tag_ids if self.by_id[tag_id].theme == "品牌提及"
        ]
        aspect_tag_ids = [
            tag_id for tag_id in tag_ids if self.by_id[tag_id].theme != "品牌提及"
        ]
        return {
            "dictionary_version": self.version,
            "context": {
                "resolution_mode": "governed_product_bindings",
                "contexts": [
                    {
                        "product_line": product_line,
                        "voc_category": voc_category,
                        "spu_ids": list(spu_ids),
                    }
                    for product_line, voc_category, spu_ids in normalized_contexts
                ],
                "detected_spu_ids": sorted(
                    {
                        spu_id
                        for _, _, spu_ids in normalized_contexts
                        for spu_id in spu_ids
                    }
                ),
                "spu_binding_mode": "governed_explicit",
            },
            "eligible_rule_count": len(eligible_rules),
            "tag_ids": tag_ids,
            "aspect_tag_ids": aspect_tag_ids,
            "brand_tag_ids": brand_tag_ids,
            "matches": matches,
            "ambiguous_keyword_matches": ambiguous,
            "negated_keyword_matches": merged_candidates(
                "negated_keyword_matches"
            ),
            "low_specificity_keyword_matches": merged_candidates(
                "low_specificity_keyword_matches"
            ),
            "semantic_validation_status": "not_run",
        }

    def profile(self, *, product_line: str, voc_category: str) -> dict[str, Any]:
        base_rules = self.select_rules(
            product_line=product_line,
            voc_category=voc_category,
        )
        supported_spu_ids = sorted(set(self.model_spu_aliases.values()))
        executable_rules = self.select_rules(
            product_line=product_line,
            voc_category=voc_category,
            spu_ids=supported_spu_ids,
        )
        phrase_rules: dict[str, list[TagRule]] = defaultdict(list)
        for rule in base_rules:
            for phrase in rule.keywords:
                phrase_rules[phrase].append(rule)
        shared = {
            phrase: rules
            for phrase, rules in phrase_rules.items()
            if len({rule.tag_id for rule in rules}) > 1
        }
        polarity_conflicts = {
            phrase: rules
            for phrase, rules in shared.items()
            if len({rule.sentiment for rule in rules}) > 1
        }
        return {
            "dictionary_version": self.version,
            "row_count": len(self.rules),
            "column_count": len(EXPECTED_COLUMNS),
            "tag_ids_unique": len(self.by_id) == len(self.rules),
            "scope_counts": dict(
                sorted(Counter(rule.tag_scope for rule in self.rules).items())
            ),
            "sentiment_counts": dict(
                sorted(Counter(rule.sentiment for rule in self.rules).items())
            ),
            "base_context": {
                "product_line": product_line,
                "voc_category": voc_category,
                "eligible_rule_count": len(base_rules),
                "scope_counts": dict(
                    sorted(Counter(rule.tag_scope for rule in base_rules).items())
                ),
                "unique_keyword_count": len(phrase_rules),
                "shared_keyword_count": len(shared),
                "cross_sentiment_keyword_count": len(polarity_conflicts),
            },
            "supported_model_spu_aliases": self.model_spu_aliases,
            "executable_rule_count_with_supported_spu": len(executable_rules),
            "excluded_unscoped_l2_rule_count": sum(
                rule.tag_scope == "L2-品类专属"
                and rule.product_line == "total"
                and rule.voc_category == "total"
                for rule in self.rules
            ),
            "cross_sentiment_keywords": [
                {
                    "keyword": phrase,
                    "tag_ids": sorted({rule.tag_id for rule in rules}),
                    "sentiments": sorted({rule.sentiment for rule in rules}),
                }
                for phrase, rules in sorted(polarity_conflicts.items())
            ],
            "matching_policy": {
                "rule_match": "exact normalized phrase mapped to one eligible tag",
                "shared_phrase": "candidate only; excluded from rule tag metrics",
                "negated_phrase": "candidate only; excluded from rule tag metrics",
                "single_token_phrase": "candidate only unless it is a verified brand alias",
                "brand_phrase": "rule-matched only when keyword is a lexical alias of the governed brand name",
                "consumer_phrases_used": False,
                "dictionary_sentiment_overrides_entity_sentiment": False,
                "semantic_validation_run": False,
                "spu_rule_gate": "only model aliases explicitly mapped by dictionary metadata",
            },
        }

    def executable_dictionary_records(
        self, *, product_line: str, voc_category: str
    ) -> list[dict[str, Any]]:
        rules = self.select_rules(
            product_line=product_line,
            voc_category=voc_category,
            spu_ids=set(self.model_spu_aliases.values()),
        )
        return [rule.to_record() for rule in sorted(rules, key=lambda item: item.tag_id)]

    def executable_dictionary_records_for_contexts(
        self,
        contexts: Iterable[tuple[str, str, Iterable[str]]],
    ) -> list[dict[str, Any]]:
        return [
            rule.to_record() for rule in self.select_rules_for_contexts(contexts)
        ]
