from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Collection, Iterable, Mapping, Sequence
import unicodedata


POLICY_SCHEMA_VERSION = "reddit_voc_semantic_predicate_policy_v1"
DEFAULT_REPAIR_DATASET_VERSION = "reddit_voc_tag_repair_20260714_v1"
TARGET_TAG_IDS = {
    "L2-PUMP-016",
    "L0-CHL-003",
    "L2-PUMP-030",
    "L2-PUMP-007",
}
ALLOWED_STATUSES = {"confirmed", "rejected", "needs_review"}
EVALUATORS = {
    "flange_fit_negative_outcome",
    "explicit_product_price_value",
    "momcozy_output_comparison",
    "active_accessory_purchase_intent",
}
NEGATIONS = {
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
}


def _normalize(value: str) -> str:
    value = html.unescape(value)
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("’", "'").replace("‘", "'")
    return " ".join(value.split())


def _phrase_present(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize(phrase)
    pattern = re.escape(normalized_phrase).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text) is not None


def _has_any(text: str, phrases: Iterable[str]) -> bool:
    return any(_phrase_present(text, phrase) for phrase in phrases)


def _term_is_negated(
    text: str,
    phrase: str,
    negations: Collection[str] = NEGATIONS,
) -> bool:
    normalized_phrase = _normalize(phrase)
    pattern = re.escape(normalized_phrase).replace(r"\ ", r"\s+")
    for match in re.finditer(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text):
        prefix = text[max(0, match.start() - 72) : match.start()]
        tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", prefix)[-4:]
        if not any(token in negations for token in tokens):
            return False
    return True


def _has_affirmed_any(
    text: str,
    phrases: Iterable[str],
    negations: Collection[str] = NEGATIONS,
) -> bool:
    return any(
        _phrase_present(text, phrase)
        and not _term_is_negated(text, phrase, negations)
        for phrase in phrases
    )


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str
    normalized: str


@dataclass(frozen=True)
class PredicatePolicy:
    schema_version: str
    policy_version: str
    repair_dataset_version: str
    base_dataset_version: str
    base_manifest_sha256: str
    dictionary_version: str
    dictionary_sha256: str
    target_tag_ids: tuple[str, ...]
    predicates: Mapping[str, Mapping[str, Any]]
    boundaries: Mapping[str, Any]


@dataclass(frozen=True)
class PredicateResult:
    tag_id: str
    status: str
    reason_code: str
    evidence_keywords: tuple[str, ...]
    sentence_indexes: tuple[int, ...]
    evidence_sentences: tuple[str, ...]
    predicate_version: str

    def to_record(self) -> dict[str, Any]:
        return {
            "tag_id": self.tag_id,
            "predicate_status": self.status,
            "reason_code": self.reason_code,
            "evidence_keywords": list(self.evidence_keywords),
            "sentence_indexes": list(self.sentence_indexes),
            "evidence_sentences": list(self.evidence_sentences),
            "predicate_version": self.predicate_version,
        }


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            frozen[key] = _freeze_mapping(item)
        elif isinstance(item, list):
            frozen[key] = tuple(item)
        else:
            frozen[key] = item
    return MappingProxyType(frozen)


def load_policy(
    path: Path,
    *,
    expected_base_manifest_sha256: str,
    expected_dictionary_sha256: str,
) -> PredicatePolicy:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ValueError("predicate policy schema mismatch")
    if raw.get("base_manifest_sha256") != expected_base_manifest_sha256:
        raise ValueError("predicate policy base manifest sha256 mismatch")
    if raw.get("dictionary_sha256") != expected_dictionary_sha256:
        raise ValueError("predicate policy dictionary sha256 mismatch")
    target_ids = tuple(raw.get("target_tag_ids", ()))
    if set(target_ids) != TARGET_TAG_IDS or len(target_ids) != len(TARGET_TAG_IDS):
        raise ValueError("predicate policy target tag set mismatch")
    predicates = raw.get("predicates")
    if not isinstance(predicates, dict) or set(predicates) != TARGET_TAG_IDS:
        raise ValueError("predicate policy definition set mismatch")
    for tag_id, definition in predicates.items():
        if definition.get("evaluator") not in EVALUATORS:
            raise ValueError(f"unknown predicate evaluator: {tag_id}")
    boundaries = raw.get("boundaries")
    if not isinstance(boundaries, dict):
        raise ValueError("predicate policy boundaries missing")
    expected_false = ("dictionary_mutated", "provider_call", "database_write", "live_send")
    if boundaries.get("production_unchanged") is not True or any(
        boundaries.get(name) is not False for name in expected_false
    ):
        raise ValueError("predicate policy side-effect boundary mismatch")
    if boundaries.get("independent_human_review") is not False:
        raise ValueError("predicate policy human-review boundary mismatch")
    return PredicatePolicy(
        schema_version=raw["schema_version"],
        policy_version=str(raw["policy_version"]),
        repair_dataset_version=str(
            raw.get("repair_dataset_version", DEFAULT_REPAIR_DATASET_VERSION)
        ),
        base_dataset_version=str(raw["base_dataset_version"]),
        base_manifest_sha256=str(raw["base_manifest_sha256"]),
        dictionary_version=str(raw["dictionary_version"]),
        dictionary_sha256=str(raw["dictionary_sha256"]),
        target_tag_ids=target_ids,
        predicates=_freeze_mapping(predicates),
        boundaries=_freeze_mapping(boundaries),
    )


def _sentences(text: str) -> tuple[Sentence, ...]:
    decoded = html.unescape(text)
    parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", decoded)
        if part.strip()
    ]
    return tuple(
        Sentence(index=index, text=part, normalized=_normalize(part))
        for index, part in enumerate(parts)
    )


def _evidence_sentence_indexes(
    sentences: Sequence[Sentence], evidence_keywords: Sequence[str]
) -> tuple[int, ...]:
    return tuple(
        sentence.index
        for sentence in sentences
        if any(_phrase_present(sentence.normalized, keyword) for keyword in evidence_keywords)
    )


def _result(
    *,
    tag_id: str,
    status: str,
    reason_code: str,
    evidence_keywords: tuple[str, ...],
    indexes: Iterable[int],
    sentences: Sequence[Sentence],
    policy: PredicatePolicy,
) -> PredicateResult:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid predicate status: {status}")
    unique_indexes = tuple(sorted(set(indexes)))
    by_index = {sentence.index: sentence for sentence in sentences}
    return PredicateResult(
        tag_id=tag_id,
        status=status,
        reason_code=reason_code,
        evidence_keywords=evidence_keywords,
        sentence_indexes=unique_indexes,
        evidence_sentences=tuple(by_index[index].text for index in unique_indexes),
        predicate_version=policy.policy_version,
    )


def _flange_fit(
    definition: Mapping[str, Any],
    sentences: Sequence[Sentence],
    evidence_indexes: tuple[int, ...],
) -> tuple[str, str, tuple[int, ...]]:
    negations = NEGATIONS | set(definition.get("additional_negations", ()))
    direct = definition["direct_failure_phrases"]
    anatomy = definition["anatomy_phrases"]
    fit_subjects = definition["fit_subject_phrases"]
    outcomes = definition["negative_outcome_phrases"]
    positive = definition["positive_fit_phrases"]
    resolved = definition["resolved_or_correct_fit_phrases"]
    suspicion = definition["suspicion_phrases"]
    material = definition["material_preference_phrases"]
    context_indexes = {
        nearby
        for index in evidence_indexes
        for nearby in (index - 1, index, index + 1)
        if 0 <= nearby < len(sentences)
    }
    contexts = [sentences[index] for index in sorted(context_indexes)]
    review_context_indexes = {
        nearby
        for index in evidence_indexes
        for nearby in (index - 2, index - 1, index, index + 1, index + 2)
        if 0 <= nearby < len(sentences)
    }
    review_contexts = [
        sentences[index] for index in sorted(review_context_indexes)
    ]
    if any(
        _has_affirmed_any(sentence.normalized, direct, negations)
        for sentence in contexts
    ):
        indexes = tuple(
            sentence.index
            for sentence in contexts
            if _has_affirmed_any(sentence.normalized, direct, negations)
        )
        return "confirmed", "explicit_flange_size_or_fit_failure", indexes
    anatomy_sentences = [sentence for sentence in contexts if _has_any(sentence.normalized, anatomy)]
    subject_sentences = [sentence for sentence in contexts if _has_any(sentence.normalized, fit_subjects)]
    if not subject_sentences:
        return "needs_review", "flange_subject_binding_incomplete", evidence_indexes
    if anatomy_sentences and all(_is_question(sentence) for sentence in anatomy_sentences):
        return (
            "needs_review",
            "elastic_anatomy_question_without_self_binding",
            tuple(sentence.index for sentence in anatomy_sentences),
        )
    if any(_has_any(sentence.normalized, suspicion) for sentence in anatomy_sentences):
        return (
            "needs_review",
            "suspected_fit_issue_without_confirmed_outcome",
            tuple(sentence.index for sentence in anatomy_sentences),
        )
    if any(_has_any(sentence.normalized, material) for sentence in review_contexts):
        return (
            "needs_review",
            "material_preference_without_size_mismatch",
            tuple(
                sentence.index
                for sentence in review_contexts
                if _has_any(sentence.normalized, material)
            ),
        )
    resolved_indexes = tuple(
        sentence.index
        for sentence in contexts
        if _has_affirmed_any(sentence.normalized, resolved, negations)
    )
    if resolved_indexes:
        return (
            "rejected",
            "resolved_or_correct_fit_counterevidence",
            resolved_indexes,
        )
    negative_indexes = tuple(
        sentence.index
        for sentence in contexts
        if _has_affirmed_any(sentence.normalized, outcomes, negations)
    )
    if negative_indexes:
        positive_indexes = tuple(
            sentence.index
            for sentence in contexts
            if _has_affirmed_any(sentence.normalized, positive, negations)
        )
        if positive_indexes:
            return (
                "needs_review",
                "mixed_positive_and_negative_fit_outcomes",
                tuple(sorted(set(negative_indexes) | set(positive_indexes))),
            )
        return "confirmed", "elastic_fit_negative_outcome", negative_indexes
    if any(_has_any(sentence.normalized, positive) for sentence in contexts):
        return (
            "rejected",
            "elastic_anatomy_without_negative_mismatch",
            tuple(sentence.index for sentence in anatomy_sentences),
        )
    return (
        "rejected",
        "elastic_anatomy_without_negative_mismatch",
        tuple(sentence.index for sentence in subject_sentences),
    )


def _is_question(sentence: Sentence) -> bool:
    if "?" in sentence.text:
        return True
    if re.search(
        r"\b(?:whether|asked if|asking if|wonder(?:ing)? if|debating if|debating whether)\b",
        sentence.normalized,
    ):
        return True
    return re.match(
        r"^(?:is|are|was|were|do|does|did|can|could|should|would|has|have)\b",
        sentence.normalized,
    ) is not None


def _value_claim_modality(
    sentence: Sentence, phrases: Iterable[str]
) -> str:
    """Classify the strongest value assertion in a sentence.

    Contrastive clauses are evaluated separately so a modal setup such as
    "may seem expensive, but ... definitely worth it" does not suppress the
    later unconditional assertion. Commas intentionally do not split clauses:
    an initial ``if`` clause still governs its consequent.
    """

    text = sentence.normalized
    boundaries = [0]
    boundaries.extend(
        match.end()
        for match in re.finditer(r"[;!?]|\b(?:but|however|yet)\b", text)
    )
    boundaries.append(len(text))
    modes: list[str] = []
    for phrase in phrases:
        normalized_phrase = _normalize(phrase)
        pattern = re.escape(normalized_phrase).replace(r"\ ", r"\s+")
        for match in re.finditer(
            rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text
        ):
            if _term_is_negated(text, phrase):
                continue
            clause_start = max(
                boundary for boundary in boundaries if boundary <= match.start()
            )
            clause_end = min(
                boundary for boundary in boundaries if boundary >= match.end()
            )
            clause = text[clause_start:clause_end]
            if re.search(r"\b(?:if|whether)\b", clause):
                modes.append("conditional")
                continue
            phrase_start = match.start() - clause_start
            prefix = clause[max(0, phrase_start - 72) : phrase_start]
            suffix = clause[match.end() - clause_start : match.end() - clause_start + 32]
            if re.search(r"\b(?:may|might|maybe|perhaps|possibly)\b", prefix + suffix):
                modes.append("modal")
                continue
            modes.append("unconditional")
    if "unconditional" in modes:
        return "unconditional"
    if "conditional" in modes:
        return "conditional"
    if "modal" in modes:
        return "modal"
    return "absent"


def _explicit_value(
    definition: Mapping[str, Any],
    sentences: Sequence[Sentence],
    evidence_indexes: tuple[int, ...],
    parent_sentences: Sequence[Sentence] = (),
) -> tuple[str, str, tuple[int, ...]]:
    value_phrases = definition["value_phrases"]
    support_indexes = {
        sentence.index
        for sentence in sentences
        if _has_any(sentence.normalized, value_phrases)
        or _has_any(sentence.normalized, definition["strong_value_phrases"])
    }
    indexes = tuple(sorted(set(evidence_indexes) | support_indexes))
    candidates = [sentences[index] for index in indexes]
    non_questions = [sentence for sentence in candidates if not _is_question(sentence)]
    if not non_questions:
        return "rejected", "question_not_assertion", indexes
    affirmed = [
        sentence
        for sentence in non_questions
        if _has_affirmed_any(sentence.normalized, value_phrases)
        or _has_affirmed_any(sentence.normalized, definition["strong_value_phrases"])
    ]
    if not affirmed:
        return "rejected", "negated_or_non_product_value", indexes
    hearsay_terms = definition.get("hearsay_terms", ())
    hearsay_indexes = tuple(
        sentence.index
        for sentence in affirmed
        if _has_any(sentence.normalized, hearsay_terms)
    )
    if hearsay_indexes:
        affirmed = [
            sentence
            for sentence in affirmed
            if sentence.index not in hearsay_indexes
        ]
        if not affirmed:
            return "rejected", "hearsay_value_claim", hearsay_indexes
    claim_modes = {
        sentence.index: _value_claim_modality(
            sentence,
            (*value_phrases, *definition["strong_value_phrases"]),
        )
        for sentence in affirmed
    }
    unconditional = [
        sentence
        for sentence in affirmed
        if claim_modes[sentence.index] == "unconditional"
    ]
    if not unconditional:
        if any(mode == "conditional" for mode in claim_modes.values()):
            return "rejected", "conditional_value_claim", tuple(
                sentence.index for sentence in affirmed
            )
        if any(mode == "modal" for mode in claim_modes.values()):
            return "needs_review", "modal_value_claim", tuple(
                sentence.index for sentence in affirmed
            )
    affirmed = unconditional
    context_window = int(definition.get("context_window_sentences", 1))
    price_grounded: list[Sentence] = []
    for sentence in affirmed:
        adjacent = " ".join(
            sentences[index].normalized
            for index in range(
                max(0, sentence.index - context_window),
                min(len(sentences), sentence.index + context_window + 1),
            )
        )
        has_explicit_price = _has_any(
            adjacent, definition["explicit_price_terms"]
        ) or re.search(
            r"(?:[$£€]\s*\d|\b\d+(?:\.\d+)?\s*(?:usd|dollars?)\b)",
            adjacent,
        )
        if (
            _has_any(sentence.normalized, definition["non_product_terms"])
            and not has_explicit_price
        ):
            continue
        price_grounded.append(sentence)
    if not price_grounded:
        return "rejected", "non_price_value_context", tuple(
            sentence.index for sentence in affirmed
        )
    affirmed = price_grounded
    if all(
        _phrase_present(sentence.normalized, "great deal")
        and not _has_any(sentence.normalized, definition["strong_value_phrases"])
        for sentence in affirmed
    ):
        return "rejected", "discount_only_without_value_assertion", tuple(
            sentence.index for sentence in affirmed
        )
    usable = []
    parent_grounded = []
    parent_product_context = (
        bool(definition.get("allow_parent_product_grounding"))
        and any(
            _has_any(sentence.normalized, definition["product_terms"])
            for sentence in parent_sentences
        )
    )
    for sentence in affirmed:
        adjacent = " ".join(
            sentences[index].normalized
            for index in range(
                max(0, sentence.index - context_window),
                min(len(sentences), sentence.index + context_window + 1),
            )
        )
        has_product = _has_any(adjacent, definition["product_terms"])
        has_value_context = _has_any(adjacent, definition["price_or_value_terms"])
        strong = _has_any(sentence.normalized, definition["strong_value_phrases"])
        percent_worth = re.search(r"\b\d{2,}%\s*worth it\b", sentence.normalized) is not None
        if has_product and (has_value_context or strong or percent_worth):
            usable.append(sentence)
        elif parent_product_context and (has_value_context or strong or percent_worth):
            parent_grounded.append(sentence)
    if usable:
        return (
            "confirmed",
            "explicit_product_price_value_assertion",
            tuple(sentence.index for sentence in usable),
        )
    if parent_grounded:
        return (
            "confirmed",
            "explicit_product_value_with_parent_grounding",
            tuple(sentence.index for sentence in parent_grounded),
        )
    if all(_has_any(sentence.normalized, definition["non_product_terms"]) for sentence in affirmed):
        return "rejected", "negated_or_non_product_value", tuple(
            sentence.index for sentence in affirmed
        )
    return "needs_review", "value_subject_or_price_context_missing", tuple(
        sentence.index for sentence in affirmed
    )


def _nearest_prior_alias(
    sentence: str, position: int, aliases: Sequence[str]
) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for alias in aliases:
        normalized_alias = _normalize(alias)
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])", sentence):
            if match.start() > position:
                continue
            candidate = (match.start(), normalized_alias)
            if best is None or candidate[0] > best[0]:
                best = candidate
    return best


def _momcozy_comparison(
    definition: Mapping[str, Any],
    sentences: Sequence[Sentence],
    evidence_indexes: tuple[int, ...],
) -> tuple[str, str, tuple[int, ...]]:
    momcozy = definition["momcozy_aliases"]
    competitors = definition["competitor_aliases"]
    metrics = definition["metric_terms"]
    positive = definition["equal_or_better_phrases"]
    worse = definition["worse_phrases"]
    relevant = [sentences[index] for index in evidence_indexes]
    has_momcozy_anywhere = any(_has_any(sentence.normalized, momcozy) for sentence in sentences)
    has_competitor_anywhere = any(_has_any(sentence.normalized, competitors) for sentence in sentences)
    if not has_momcozy_anywhere and has_competitor_anywhere:
        return "rejected", "wrong_brand_comparison", evidence_indexes
    if not has_momcozy_anywhere or not has_competitor_anywhere:
        return "needs_review", "comparison_binding_incomplete", evidence_indexes
    for sentence in relevant:
        normalized = sentence.normalized
        if not _has_any(normalized, metrics):
            continue
        has_momcozy = _has_any(normalized, momcozy)
        has_competitor = _has_any(normalized, competitors)
        if has_momcozy and _has_any(normalized, worse):
            mom_position = min(
                normalized.find(alias)
                for alias in momcozy
                if normalized.find(alias) >= 0
            )
            worse_positions = [normalized.find(phrase) for phrase in worse if normalized.find(phrase) >= 0]
            if worse_positions and mom_position <= min(worse_positions):
                return "rejected", "momcozy_not_equal_or_better", (sentence.index,)
        phrase_positions = [
            normalized.find(phrase)
            for phrase in positive
            if normalized.find(phrase) >= 0
        ]
        if not phrase_positions:
            continue
        phrase_position = min(phrase_positions)
        nearest_momcozy = _nearest_prior_alias(normalized, phrase_position, momcozy)
        nearest_competitor = _nearest_prior_alias(normalized, phrase_position, competitors)
        if has_momcozy and has_competitor:
            if nearest_momcozy and (
                not nearest_competitor or nearest_momcozy[0] > nearest_competitor[0]
            ):
                return "confirmed", "momcozy_output_equal_or_better", (sentence.index,)
            if _phrase_present(normalized, "equal output") and nearest_momcozy:
                return "confirmed", "momcozy_output_equal_or_better", (sentence.index,)
        if nearest_competitor and not nearest_momcozy:
            return "rejected", "wrong_brand_comparison", (sentence.index,)
    if definition.get("allow_adjacent_subject_binding"):
        implicit_phrases = definition.get(
            "implicit_subject_comparison_phrases", ()
        )
        for sentence in relevant:
            if sentence.index <= 0:
                continue
            previous = sentences[sentence.index - 1]
            normalized = sentence.normalized
            if (
                _has_any(previous.normalized, momcozy)
                and not _has_any(normalized, momcozy)
                and _has_any(normalized, competitors)
                and _has_any(normalized, metrics)
                and _has_affirmed_any(normalized, implicit_phrases)
                and not _has_any(normalized, worse)
                and re.search(r"\b(?:i|i'm|im|my|we|our)\b", normalized)
            ):
                return (
                    "confirmed",
                    "momcozy_output_equal_or_better_adjacent_binding",
                    (previous.index, sentence.index),
                )
    return "needs_review", "comparison_direction_incomplete", evidence_indexes


def _accessory_intent(
    definition: Mapping[str, Any],
    sentences: Sequence[Sentence],
    evidence_indexes: tuple[int, ...],
) -> tuple[str, str, tuple[int, ...]]:
    relevant = [sentences[index] for index in evidence_indexes]
    for sentence in relevant:
        normalized = sentence.normalized
        if _has_any(normalized, definition["insurance_or_free_phrases"]):
            return "rejected", "insurance_or_free_supply", (sentence.index,)
        if _has_any(normalized, definition["advice_to_other_phrases"]):
            return "rejected", "advice_to_other", (sentence.index,)
        if _has_any(normalized, definition["past_purchase_phrases"]):
            return "rejected", "past_accessory_purchase", (sentence.index,)
        if _has_any(normalized, definition["availability_phrases"]):
            if not _has_any(normalized, definition["active_intent_phrases"]):
                return "needs_review", "availability_without_purchase_intent", (sentence.index,)
        has_intent = _has_any(normalized, definition["active_intent_phrases"])
        has_accessory = _has_any(normalized, definition["accessory_terms"])
        third_party_subject = re.search(
            r"\bmy\s+(?:friend|sister|brother|partner|wife|husband|coworker|colleague)\b"
            r".{0,70}\b(?:need|needs|want|wants|plan|plans|consider|considers)\b",
            normalized,
        ) is not None
        if third_party_subject and has_accessory:
            return "needs_review", "purchase_subject_binding_incomplete", (sentence.index,)
        first_person_subject = re.search(
            r"\b(?:i|i'm|im|we|we're|were)\b.{0,90}"
            r"(?:need to|get|buy|order|looking for|want to|plan to|planning to|consider buying|considering buying|have to)",
            normalized,
        ) is not None or re.search(r"\bwhere (?:can|do) i\b", normalized) is not None
        if first_person_subject and has_intent and has_accessory:
            return "confirmed", "active_accessory_purchase_intent", (sentence.index,)
        if (
            definition.get("allow_first_person_discourse_binding")
            and has_intent
            and has_accessory
            and re.search(r"\b(?:i|i'm|im|my|we|our)\b", normalized)
        ):
            return (
                "confirmed",
                "active_accessory_purchase_intent_discourse_bound",
                (sentence.index,),
            )
        if has_intent and has_accessory:
            return "needs_review", "purchase_subject_binding_incomplete", (sentence.index,)
    return "rejected", "accessory_mention_without_active_intent", evidence_indexes


def evaluate_assignment(
    *,
    tag_id: str,
    text: str,
    evidence_keywords: Sequence[str],
    policy: PredicatePolicy,
    brand_tag_ids: Sequence[str] = (),
    detected_spu_ids: Sequence[str] = (),
    parent_text: str | None = None,
) -> PredicateResult:
    del brand_tag_ids, detected_spu_ids
    if tag_id not in policy.predicates:
        raise ValueError(f"tag is not governed by predicate policy: {tag_id}")
    normalized_keywords = tuple(
        dict.fromkeys(_normalize(keyword) for keyword in evidence_keywords if _normalize(keyword))
    )
    if not normalized_keywords:
        raise ValueError(f"lexical evidence is empty: {tag_id}")
    sentences = _sentences(text)
    evidence_indexes = _evidence_sentence_indexes(sentences, normalized_keywords)
    if not evidence_indexes:
        return _result(
            tag_id=tag_id,
            status="needs_review",
            reason_code="lexical_evidence_not_located",
            evidence_keywords=normalized_keywords,
            indexes=(),
            sentences=sentences,
            policy=policy,
        )
    definition = policy.predicates[tag_id]
    evaluator = definition["evaluator"]
    if evaluator == "flange_fit_negative_outcome":
        status, reason, indexes = _flange_fit(definition, sentences, evidence_indexes)
    elif evaluator == "explicit_product_price_value":
        status, reason, indexes = _explicit_value(
            definition,
            sentences,
            evidence_indexes,
            _sentences(parent_text) if parent_text else (),
        )
    elif evaluator == "momcozy_output_comparison":
        status, reason, indexes = _momcozy_comparison(definition, sentences, evidence_indexes)
    elif evaluator == "active_accessory_purchase_intent":
        status, reason, indexes = _accessory_intent(definition, sentences, evidence_indexes)
    else:
        raise ValueError(f"unknown predicate evaluator: {evaluator}")
    return _result(
        tag_id=tag_id,
        status=status,
        reason_code=reason,
        evidence_keywords=normalized_keywords,
        indexes=indexes,
        sentences=sentences,
        policy=policy,
    )
