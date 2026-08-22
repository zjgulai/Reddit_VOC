"""Independent replay and completeness validator for V3 closed-set facts.

This module deliberately does not import ``v3_closed_set_facts``.  It reads
the three frozen resources itself, rebuilds the match-key inventory, and
validates every semantic fact identity and evidence span.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata


DIM_TAG_SHA256 = "22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14"
PRODUCT_ENTITY_LEDGER_SHA256 = (
    "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab"
)
CLOSED_SET_REGISTRY_SHA256 = (
    "35efdc71543f128acc96f9e30d1788d1e78972b042f64e369d01c43fd5723d71"
)
FACT_KEYS = frozenset(
    {
        "attributes",
        "canonical_entity_id",
        "canonical_value",
        "context_evidence_refs",
        "created_at",
        "decision_status",
        "dictionary_release_id",
        "evidence_end",
        "evidence_field",
        "evidence_scope",
        "evidence_source_entity_id",
        "evidence_start",
        "evidence_text_sha256",
        "fact_id",
        "fact_type",
        "matcher_version",
        "normalizer_version",
        "reason_codes",
        "schema_version",
        "source_snapshot_id",
        "voc_id",
        "voc_type",
    }
)
FACT_TYPES = frozenset(
    {
        "entity_brand_fact",
        "entity_product_fact",
        "entity_sentiment_fact",
        "entity_problem_fact",
        "entity_tag_fact",
    }
)
TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*", re.IGNORECASE)
HELD_REASONS = frozenset(
    {
        "contextual_product_alias_requires_context",
        "duplicate_rule_conflict",
        "legacy_dictionary_lexical_unvalidated",
        "negated_evidence",
        "registry_resolved_shared_phrase",
        "semantic_conflict",
        "sentiment_conflict",
        "shared_phrase_ambiguous",
        "single_token_ambiguous",
        "single_token_entity_requires_context",
    }
)


class ClosedSetFactValidationError(ValueError):
    """A closed-set fact bundle fails independent reproduction."""


@dataclass(frozen=True)
class _ExpectedCandidate:
    voc_id: str
    fact_type: str
    canonical_value: str
    field: str
    start: int
    end: int
    source_entity: str
    scope: str
    decision_status: str
    reason_codes: tuple[str, ...]
    promotion_approved: bool
    rule_signature: tuple[object, ...]

    @property
    def fact_key(self) -> tuple[object, ...]:
        return (
            self.voc_id,
            self.fact_type,
            self.canonical_value,
            self.field,
            self.start,
            self.end,
            self.source_entity,
            self.scope,
        )


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ClosedSetFactValidationError(
            "value is not canonical JSON serializable"
        ) from exc


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).translate(
        str.maketrans({"’": "'", "‘": "'", "`": "'"})
    )
    return tuple(match.group(0).casefold() for match in TOKEN.finditer(normalized))


def _source_tokens(value: str) -> tuple[tuple[str, int, int], ...]:
    normalized = unicodedata.normalize("NFKC", value).translate(
        str.maketrans({"’": "'", "‘": "'", "`": "'"})
    )
    if normalized != value:
        return ()
    return tuple(
        (match.group(0).casefold(), match.start(), match.end())
        for match in TOKEN.finditer(value)
    )


def _read_json(path: Path, expected_sha: str, label: str) -> dict[str, Any]:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosedSetFactValidationError(f"{label} is unreadable") from exc
    if _sha(payload) != expected_sha or not isinstance(value, dict):
        raise ClosedSetFactValidationError(f"{label} binding is invalid")
    return value


def _occurrences(
    text: str,
    phrase_tokens: Sequence[str],
) -> tuple[tuple[int, int], ...]:
    source = _source_tokens(text)
    if not source or not phrase_tokens:
        return ()
    size = len(phrase_tokens)
    result: list[tuple[int, int]] = []
    for index in range(len(source) - size + 1):
        if tuple(row[0] for row in source[index : index + size]) == tuple(
            phrase_tokens
        ):
            result.append((source[index][1], source[index + size - 1][2]))
    return tuple(result)


def _first_token_index(
    rows: Iterable[tuple[tuple[str, ...], object]],
) -> dict[str, tuple[tuple[tuple[str, ...], object], ...]]:
    """Create an immutable phrase index independent from the production matcher."""
    result: dict[str, list[tuple[tuple[str, ...], object]]] = {}
    for phrase, payload in rows:
        if not phrase:
            raise ClosedSetFactValidationError("empty indexed phrase")
        result.setdefault(phrase[0], []).append((phrase, payload))
    return {
        token: tuple(
            sorted(values, key=lambda row: (-len(row[0]), repr(row[1]), row[0]))
        )
        for token, values in result.items()
    }


def _indexed_occurrences(
    text: str,
    index: Mapping[str, Sequence[tuple[tuple[str, ...], object]]],
) -> tuple[tuple[object, int, int], ...]:
    """Tokenize one source field once, then replay every governed phrase."""
    source = _source_tokens(text)
    if not source:
        return ()
    result: list[tuple[object, int, int]] = []
    for token_index, token in enumerate(source):
        for phrase, payload in index.get(token[0], ()):
            end_index = token_index + len(phrase)
            if end_index > len(source):
                continue
            if tuple(row[0] for row in source[token_index:end_index]) != phrase:
                continue
            result.append((payload, token[1], source[end_index - 1][2]))
    return tuple(result)


def _fact_mapping(value: object) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise ClosedSetFactValidationError("fact must be an object")
    return dict(value)


def _voc_mapping(value: object) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise ClosedSetFactValidationError("VOC must be an object")
    row = dict(value)
    if (
        row.get("schema_version") != "reddit_voc_fielded_voc_v1"
        or row.get("analysis_text_status") != "ready"
        or row.get("voc_type") not in {"post_voc", "comment_context_voc"}
        or not isinstance(row.get("voc_id"), str)
        or not isinstance(row.get("canonical_entity_id"), str)
        or not isinstance(row.get("post_id"), str)
        or row.get("thread_id") != row.get("post_id")
        or not isinstance(row.get("analysis_fields"), Mapping)
        or set(row["analysis_fields"])
        != {"current_comment_body", "post_body", "post_title"}
        or any(
            not isinstance(value, str)
            for value in row["analysis_fields"].values()
        )
    ):
        raise ClosedSetFactValidationError("VOC contract is invalid")
    if row["voc_type"] == "post_voc":
        post_id = row["post_id"]
        if (
            row["voc_id"] != f"post:{post_id}"
            or row["canonical_entity_id"] != f"t3_{post_id}"
        ):
            raise ClosedSetFactValidationError("post VOC identity is invalid")
    else:
        comment_id = row.get("comment_id")
        if (
            not isinstance(comment_id, str)
            or row["voc_id"] != f"comment:{comment_id}"
            or row["canonical_entity_id"] != f"t1_{comment_id}"
            or row.get("comment_context_id")
            != f"{row['post_id']}:{comment_id}"
        ):
            raise ClosedSetFactValidationError("comment VOC identity is invalid")
    return row


def _load_reference_index(
    *,
    dim_tag_path: Path,
    product_entity_ledger_path: Path,
    registry_path: Path,
) -> dict[str, Any]:
    registry = _read_json(
        registry_path, CLOSED_SET_REGISTRY_SHA256, "closed-set registry"
    )
    if Path(registry_path).read_bytes() != _canonical(registry) + b"\n":
        raise ClosedSetFactValidationError(
            "closed-set registry is not canonical JSON"
        )
    ledger = _read_json(
        product_entity_ledger_path,
        PRODUCT_ENTITY_LEDGER_SHA256,
        "product entity ledger",
    )
    try:
        tag_payload = Path(dim_tag_path).read_bytes()
        reader = csv.DictReader(
            io.StringIO(tag_payload.decode("utf-8-sig"), newline="")
        )
        tag_rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ClosedSetFactValidationError("tag dictionary is unreadable") from exc
    if _sha(tag_payload) != DIM_TAG_SHA256 or len(tag_rows) != 2346:
        raise ClosedSetFactValidationError("tag dictionary binding is invalid")

    tag_phrases: dict[tuple[str, tuple[str, ...]], str] = {}
    phrase_owners: dict[tuple[str, ...], set[str]] = {}
    tag_rows_by_id: dict[str, dict[str, str]] = {}
    for row in tag_rows:
        tag_id = row.get("tag_id")
        if not isinstance(tag_id, str) or not tag_id or tag_id in tag_rows_by_id:
            raise ClosedSetFactValidationError("tag dictionary identity is invalid")
        try:
            phrases = json.loads(row["keywords_en"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ClosedSetFactValidationError("tag keywords are invalid") from exc
        if not isinstance(phrases, list):
            raise ClosedSetFactValidationError("tag keywords are invalid")
        for phrase in phrases:
            if not isinstance(phrase, str) or not phrase:
                raise ClosedSetFactValidationError("tag phrase is invalid")
            normalized = _tokens(phrase)
            if not normalized:
                raise ClosedSetFactValidationError("tag phrase has no tokens")
            tag_phrases.setdefault((tag_id, normalized), phrase)
            phrase_owners.setdefault(normalized, set()).add(tag_id)
        tag_rows_by_id[tag_id] = dict(row)

    approved_tags: set[tuple[str, tuple[str, ...]]] = set()
    for rule in registry.get("tag_promotion_rules", []):
        if not isinstance(rule, Mapping):
            raise ClosedSetFactValidationError("tag promotion rule is invalid")
        tag_id = rule.get("tag_id")
        for phrase in rule.get("phrases", []):
            key = (str(tag_id), _tokens(str(phrase)))
            if key not in tag_phrases:
                raise ClosedSetFactValidationError(
                    "tag promotion is not dictionary-bound"
                )
            approved_tags.add(key)

    semantic: dict[
        tuple[str, str, tuple[str, ...]], dict[str, Any]
    ] = {}
    for registry_name, fact_type in (
        ("sentiment_rules", "entity_sentiment_fact"),
        ("problem_rules", "entity_problem_fact"),
        ("topic_rules", "entity_tag_fact"),
    ):
        for rule in registry.get(registry_name, []):
            if not isinstance(rule, Mapping):
                raise ClosedSetFactValidationError("semantic rule is invalid")
            for phrase in rule.get("phrases", []):
                key = (
                    fact_type,
                    str(rule.get("canonical_value")),
                    _tokens(str(phrase)),
                )
                if key in semantic or not key[2]:
                    raise ClosedSetFactValidationError(
                        "semantic phrase is duplicate or empty"
                    )
                semantic[key] = dict(rule)

    brand_specs: list[tuple[str, str, tuple[str, ...], str]] = []
    brand = ledger.get("brand")
    if not isinstance(brand, Mapping):
        raise ClosedSetFactValidationError("focal brand ledger is invalid")
    for alias in brand.get("aliases", []):
        brand_specs.append(("momcozy", str(alias), _tokens(str(alias)), "focal"))
    for alias in ledger.get("comparison_brand_aliases", []):
        brand_specs.append(
            ("competitor", str(alias), _tokens(str(alias)), "competitor")
        )

    exact_spu = {
        str(row["family_id"]): row
        for row in ledger.get("exact_spu_ledger", [])
        if isinstance(row, Mapping)
    }
    product_specs: list[dict[str, Any]] = []
    for family in ledger.get("families", []):
        if not isinstance(family, Mapping):
            raise ClosedSetFactValidationError("product family is invalid")
        family_id = str(family.get("family_id"))
        spu = exact_spu.get(family_id)
        canonical_value = (
            f"spu:{spu['spu_id']}"
            if spu and spu.get("publish_exact_spu") is True
            else f"family:{family_id}"
        )
        for alias in family.get("aliases", []):
            if not isinstance(alias, Mapping):
                raise ClosedSetFactValidationError("product alias is invalid")
            product_specs.append(
                {
                    "alias": str(alias.get("value")),
                    "canonical_value": canonical_value,
                    "family_id": family_id,
                    "match_type": alias.get("match_type"),
                    "tokens": _tokens(str(alias.get("value"))),
                }
            )

    category_phrases = tuple(
        _tokens(str(term))
        for category in ledger.get("categories", [])
        if isinstance(category, Mapping)
        for term in category.get("context_terms", [])
    )
    negation_tokens = registry.get("negation_tokens")
    if (
        not isinstance(negation_tokens, list)
        or negation_tokens != sorted(set(negation_tokens))
        or any(
            not isinstance(value, str) or len(_tokens(value)) != 1
            for value in negation_tokens
        )
    ):
        raise ClosedSetFactValidationError("negation token registry is invalid")
    brand_match_index = _first_token_index(
        (phrase, (canonical, alias, phrase, role))
        for canonical, alias, phrase, role in brand_specs
    )
    product_match_index = _first_token_index(
        (row["tokens"], row) for row in product_specs
    )
    semantic_match_index = _first_token_index(
        (phrase, (fact_type, canonical, phrase, rule))
        for (fact_type, canonical, phrase), rule in semantic.items()
    )
    tag_match_index = _first_token_index(
        (phrase, (tag_id, phrase, raw_phrase))
        for (tag_id, phrase), raw_phrase in tag_phrases.items()
    )
    return {
        "approved_tags": approved_tags,
        "brand_specs": tuple(brand_specs),
        "category_phrases": category_phrases,
        "context_window_chars": ledger.get("context_window_chars"),
        "matcher_version": registry.get("matcher_version"),
        "negation_tokens": frozenset(negation_tokens),
        "momcozy_phrases": tuple(
            tokens for value, _alias, tokens, _role in brand_specs if value == "momcozy"
        ),
        "phrase_owners": phrase_owners,
        "product_specs": tuple(product_specs),
        "semantic": semantic,
        "tag_phrases": tag_phrases,
        "tag_rows": tag_rows_by_id,
        "brand_match_index": brand_match_index,
        "product_match_index": product_match_index,
        "semantic_match_index": semantic_match_index,
        "tag_match_index": tag_match_index,
    }


def _field_inventory(
    row: Mapping[str, Any],
    *,
    cross_context: bool,
) -> tuple[tuple[str, str, str, str], ...]:
    fields = row["analysis_fields"]
    entity_id = str(row["canonical_entity_id"])
    if row["voc_type"] == "post_voc":
        return tuple(
            (name, fields[name], "direct", entity_id)
            for name in ("post_title", "post_body")
            if fields[name]
        )
    current = (
        "current_comment_body",
        fields["current_comment_body"],
        "direct",
        entity_id,
    )
    result = [current] if current[1] else []
    if cross_context:
        parent = f"t3_{row['post_id']}"
        result.extend(
            (name, fields[name], "cross_context", parent)
            for name in ("post_title", "post_body")
            if fields[name]
        )
    return tuple(result)


def _negated_at_span(
    text: str,
    start: int,
    negations: frozenset[str],
) -> bool:
    source = _source_tokens(text)
    token_start = next(
        (index for index, (_value, token_start, _end) in enumerate(source) if token_start == start),
        None,
    )
    if token_start is None:
        raise ClosedSetFactValidationError("expected phrase is not token-bound")
    lower = max(0, token_start - 3)
    for index in range(token_start - 1, lower - 1, -1):
        between = text[source[index][2] : source[token_start][1]]
        if re.search(r"[.!?\n]", between):
            break
        if source[index][0] in negations:
            return True
    return False


def _base_expected_candidate(
    *,
    row: Mapping[str, Any],
    field: str,
    text: str,
    scope: str,
    source_entity: str,
    start: int,
    end: int,
    fact_type: str,
    canonical_value: str,
    phrase: tuple[str, ...],
    approved_for_promotion: bool,
    entity_kind: bool,
    negation_sensitive: bool,
    rule_source: str,
    promotion_approved: bool,
    rule_signature: tuple[object, ...],
    index: Mapping[str, Any],
) -> _ExpectedCandidate:
    status = "promoted" if approved_for_promotion else "held"
    reasons = {
        "closed_set_exact_phrase"
        if approved_for_promotion
        else "legacy_dictionary_lexical_unvalidated"
    }
    if len(phrase) == 1 and not entity_kind:
        status = "held"
        reasons.add("single_token_ambiguous")
    if (
        rule_source == "dim_tag_v6.3_final"
        and len(index["phrase_owners"].get(phrase, ())) > 1
        and not approved_for_promotion
    ):
        status = "held"
        reasons.add("shared_phrase_ambiguous")
    if negation_sensitive and _negated_at_span(
        text,
        start,
        index["negation_tokens"],
    ):
        status = "held"
        reasons.add("negated_evidence")
    return _ExpectedCandidate(
        voc_id=str(row["voc_id"]),
        fact_type=fact_type,
        canonical_value=canonical_value,
        field=field,
        start=start,
        end=end,
        source_entity=source_entity,
        scope=scope,
        decision_status=status,
        reason_codes=tuple(sorted(reasons)),
        promotion_approved=promotion_approved,
        rule_signature=rule_signature,
    )


def _hold_expected(
    candidate: _ExpectedCandidate,
    reason: str,
) -> _ExpectedCandidate:
    return replace(
        candidate,
        decision_status="held",
        reason_codes=tuple(sorted(set(candidate.reason_codes) | {reason})),
    )


def _resolve_expected_candidates(
    candidates: Iterable[_ExpectedCandidate],
) -> dict[tuple[object, ...], tuple[str, tuple[str, ...]]]:
    retained: list[_ExpectedCandidate] = []
    entity_types = {"entity_brand_fact", "entity_product_fact"}
    for candidate in sorted(
        candidates,
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
            and prior.source_entity == candidate.source_entity
            and prior.start <= candidate.start
            and prior.end >= candidate.end
            and (prior.start, prior.end) != (candidate.start, candidate.end)
            for prior in retained
        ):
            continue
        retained.append(candidate)

    exact_groups: dict[tuple[str, str, int, int], list[int]] = {}
    for candidate_index, candidate in enumerate(retained):
        exact_groups.setdefault(
            (
                candidate.fact_type,
                candidate.field,
                candidate.start,
                candidate.end,
            ),
            [],
        ).append(candidate_index)
    replacements: dict[int, _ExpectedCandidate] = {}
    for indexes in exact_groups.values():
        values = {retained[index].canonical_value for index in indexes}
        if len(values) <= 1:
            continue
        approved = [
            index for index in indexes if retained[index].promotion_approved
        ]
        if len(approved) == 1:
            for index in indexes:
                if index != approved[0]:
                    replacements[index] = _hold_expected(
                        retained[index], "registry_resolved_shared_phrase"
                    )
        else:
            for index in indexes:
                replacements[index] = _hold_expected(
                    retained[index], "semantic_conflict"
                )

    sentiment_by_field: dict[str, list[int]] = {}
    for candidate_index, candidate in enumerate(retained):
        if candidate.fact_type == "entity_sentiment_fact":
            sentiment_by_field.setdefault(candidate.field, []).append(
                candidate_index
            )
    for indexes in sentiment_by_field.values():
        if len({retained[index].canonical_value for index in indexes}) > 1:
            for index in indexes:
                replacements[index] = _hold_expected(
                    replacements.get(index, retained[index]),
                    "sentiment_conflict",
                )

    deduplicated: dict[
        tuple[object, ...], _ExpectedCandidate
    ] = {}
    for candidate_index, candidate in enumerate(retained):
        value = replacements.get(candidate_index, candidate)
        key = (
            value.fact_type,
            value.canonical_value,
            value.field,
            value.start,
            value.end,
            value.source_entity,
        )
        previous = deduplicated.get(key)
        if previous is None:
            deduplicated[key] = value
        elif previous.rule_signature != value.rule_signature:
            deduplicated[key] = _hold_expected(
                previous, "duplicate_rule_conflict"
            )
    return {
        candidate.fact_key: (
            candidate.decision_status,
            candidate.reason_codes,
        )
        for candidate in deduplicated.values()
    }


def _expected_decisions(
    vocs: Mapping[str, dict[str, Any]],
    index: Mapping[str, Any],
) -> dict[tuple[object, ...], tuple[str, tuple[str, ...]]]:
    expected: dict[tuple[object, ...], tuple[str, tuple[str, ...]]] = {}
    for row in vocs.values():
        candidates: list[_ExpectedCandidate] = []
        context_fields = _field_inventory(row, cross_context=True)
        current_fields = _field_inventory(row, cross_context=False)
        for field, text, scope, source_entity in context_fields:
            for payload, start, end in _indexed_occurrences(
                text, index["brand_match_index"]
            ):
                canonical, alias, phrase, role = payload
                candidate = _base_expected_candidate(
                    row=row,
                    field=field,
                    text=text,
                    scope=scope,
                    source_entity=source_entity,
                    start=start,
                    end=end,
                    fact_type="entity_brand_fact",
                    canonical_value=canonical,
                    phrase=phrase,
                    approved_for_promotion=True,
                    entity_kind=True,
                    negation_sensitive=False,
                    rule_source="momcozy_product_entity_ledger",
                    promotion_approved=False,
                    rule_signature=(
                        "momcozy_product_entity_ledger",
                        "governed_brand_alias_v1",
                        alias,
                        role,
                    ),
                    index=index,
                )
                if (
                    canonical == "competitor"
                    and len(phrase) == 1
                    and not _has_context(text, start, end, index)
                ):
                    candidate = _hold_expected(
                        candidate,
                        "single_token_entity_requires_context",
                    )
                candidates.append(candidate)
            for product, start, end in _indexed_occurrences(
                text, index["product_match_index"]
            ):
                contextual = product["match_type"] == "contextual_alias"
                candidate = _base_expected_candidate(
                    row=row,
                    field=field,
                    text=text,
                    scope=scope,
                    source_entity=source_entity,
                    start=start,
                    end=end,
                    fact_type="entity_product_fact",
                    canonical_value=product["canonical_value"],
                    phrase=product["tokens"],
                    approved_for_promotion=not contextual,
                    entity_kind=True,
                    negation_sensitive=False,
                    rule_source="momcozy_product_entity_ledger",
                    promotion_approved=False,
                    rule_signature=(
                        "momcozy_product_entity_ledger",
                        "governed_product_alias_v1",
                        product["family_id"],
                        product["alias"],
                        product["match_type"],
                    ),
                    index=index,
                )
                if contextual:
                    if _has_context(text, start, end, index):
                        candidate = replace(
                            candidate,
                            decision_status="promoted",
                            reason_codes=(
                                "contextual_product_alias_with_context",
                            ),
                        )
                    else:
                        candidate = _hold_expected(
                            candidate,
                            "contextual_product_alias_requires_context",
                        )
                candidates.append(candidate)

        for field, text, scope, source_entity in context_fields:
            for payload, start, end in _indexed_occurrences(
                text, index["semantic_match_index"]
            ):
                fact_type, canonical, phrase, rule = payload
                if fact_type != "entity_tag_fact" and (
                    row["voc_type"] == "comment_context_voc"
                    and field != "current_comment_body"
                ):
                    continue
                candidates.append(
                    _base_expected_candidate(
                        row=row,
                        field=field,
                        text=text,
                        scope=scope,
                        source_entity=source_entity,
                        start=start,
                        end=end,
                        fact_type=fact_type,
                        canonical_value=canonical,
                        phrase=phrase,
                        approved_for_promotion=True,
                        entity_kind=False,
                        negation_sensitive=rule.get("negation_sensitive") is True,
                        rule_source="closed_set_registry",
                        promotion_approved=False,
                        rule_signature=(
                            "closed_set_registry",
                            rule.get("rule_id"),
                            rule.get("topic_kind"),
                            phrase,
                        ),
                        index=index,
                    )
                )
        for field, text, scope, source_entity in current_fields:
            for payload, start, end in _indexed_occurrences(
                text, index["tag_match_index"]
            ):
                tag_id, phrase, raw_phrase = payload
                approved = (tag_id, phrase) in index["approved_tags"]
                candidates.append(
                    _base_expected_candidate(
                        row=row,
                        field=field,
                        text=text,
                        scope=scope,
                        source_entity=source_entity,
                        start=start,
                        end=end,
                        fact_type="entity_tag_fact",
                        canonical_value=tag_id,
                        phrase=phrase,
                        approved_for_promotion=approved,
                        entity_kind=False,
                        negation_sensitive=True,
                        rule_source="dim_tag_v6.3_final",
                        promotion_approved=approved,
                        rule_signature=(
                            "dim_tag_v6.3_final",
                            tag_id,
                            raw_phrase,
                            approved,
                        ),
                        index=index,
                    )
                )
        resolved = _resolve_expected_candidates(candidates)
        if set(expected) & set(resolved):
            raise ClosedSetFactValidationError("expected fact key is duplicate")
        expected.update(resolved)
    return expected


def _has_context(
    text: str,
    start: int,
    end: int,
    index: Mapping[str, Any],
) -> bool:
    window_size = index["context_window_chars"]
    if type(window_size) is not int:
        raise ClosedSetFactValidationError("context window is invalid")
    window = text[max(0, start - window_size) : min(len(text), end + window_size)]
    phrases = (*index["category_phrases"], *index["momcozy_phrases"])
    return any(_occurrences(window, phrase) for phrase in phrases)


def validate_closed_set_facts(
    facts: Iterable[object],
    vocs: Iterable[object] | Mapping[str, object],
    *,
    dim_tag_path: Path,
    product_entity_ledger_path: Path,
    registry_path: Path,
    source_snapshot_id: str,
    created_at: str,
) -> dict[str, int]:
    index = _load_reference_index(
        dim_tag_path=dim_tag_path,
        product_entity_ledger_path=product_entity_ledger_path,
        registry_path=registry_path,
    )
    if isinstance(vocs, Mapping):
        raw_vocs = list(vocs.values())
    else:
        raw_vocs = list(vocs)
    by_voc: dict[str, dict[str, Any]] = {}
    for raw in raw_vocs:
        row = _voc_mapping(raw)
        voc_id = str(row["voc_id"])
        if voc_id in by_voc:
            raise ClosedSetFactValidationError("duplicate validation VOC")
        by_voc[voc_id] = row
    expected_decisions = _expected_decisions(by_voc, index)

    dictionary_release = (
        f"dim_tag_v6.3_final@{DIM_TAG_SHA256};"
        f"momcozy_product_entity_ledger@{PRODUCT_ENTITY_LEDGER_SHA256};"
        f"closed_set_registry@{CLOSED_SET_REGISTRY_SHA256}"
    )
    observed_keys: set[tuple[object, ...]] = set()
    seen_ids: set[str] = set()
    promoted = 0
    held = 0
    promoted_sentiments: dict[tuple[str, str], set[str]] = {}
    rows = [_fact_mapping(raw) for raw in facts]
    for fact in rows:
        if set(fact) != FACT_KEYS:
            raise ClosedSetFactValidationError("closed-set fact schema is invalid")
        fact_id = fact.get("fact_id")
        reasons = fact.get("reason_codes")
        attributes = fact.get("attributes")
        if (
            not isinstance(fact_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", fact_id) is None
            or fact_id in seen_ids
            or fact.get("schema_version") != "reddit_voc_atomic_fact_v2"
            or fact.get("fact_type") not in FACT_TYPES
            or fact.get("decision_status") not in {"promoted", "held"}
            or not isinstance(reasons, list)
            or not reasons
            or reasons != sorted(set(reasons))
            or not isinstance(attributes, Mapping)
            or fact.get("dictionary_release_id") != dictionary_release
            or fact.get("matcher_version") != index["matcher_version"]
            or fact.get("normalizer_version") != "source_token_span_v1"
            or fact.get("source_snapshot_id") != source_snapshot_id
            or fact.get("created_at") != created_at
        ):
            raise ClosedSetFactValidationError("closed-set fact provenance is invalid")
        seen_ids.add(fact_id)
        identity = dict(fact)
        identity.pop("fact_id")
        if _sha(_canonical(identity)) != fact_id:
            raise ClosedSetFactValidationError("closed-set fact ID is invalid")
        voc = by_voc.get(str(fact.get("voc_id")))
        if (
            voc is None
            or fact.get("voc_type") != voc["voc_type"]
            or fact.get("canonical_entity_id") != voc["canonical_entity_id"]
        ):
            raise ClosedSetFactValidationError("closed-set fact VOC join is invalid")
        field = fact.get("evidence_field")
        start = fact.get("evidence_start")
        end = fact.get("evidence_end")
        fields = voc["analysis_fields"]
        if (
            field not in fields
            or type(start) is not int
            or type(end) is not int
            or start < 0
            or end <= start
            or end > len(fields[field])
        ):
            raise ClosedSetFactValidationError("closed-set evidence span is invalid")
        substring = fields[field][start:end]
        if _sha(substring.encode("utf-8")) != fact.get("evidence_text_sha256"):
            raise ClosedSetFactValidationError("closed-set evidence hash is invalid")
        if (
            attributes.get("registry_sha256") != CLOSED_SET_REGISTRY_SHA256
            or attributes.get("dim_tag_sha256") != DIM_TAG_SHA256
            or attributes.get("product_entity_ledger_sha256")
            != PRODUCT_ENTITY_LEDGER_SHA256
            or _tokens(str(attributes.get("matched_phrase", "")))
            != _tokens(substring)
        ):
            raise ClosedSetFactValidationError("closed-set resource binding is invalid")

        scope = fact.get("evidence_scope")
        source_entity = fact.get("evidence_source_entity_id")
        refs = fact.get("context_evidence_refs")
        if voc["voc_type"] == "post_voc":
            expected_scope = "direct"
            expected_source = voc["canonical_entity_id"]
            if field not in {"post_title", "post_body"}:
                raise ClosedSetFactValidationError("post fact scope is invalid")
        elif field == "current_comment_body":
            expected_scope = "direct"
            expected_source = voc["canonical_entity_id"]
        else:
            expected_scope = "cross_context"
            expected_source = f"t3_{voc['post_id']}"
            if fact["fact_type"] not in {
                "entity_brand_fact",
                "entity_product_fact",
                "entity_tag_fact",
            }:
                raise ClosedSetFactValidationError(
                    "comment semantic fact inherited parent evidence"
                )
        if scope != expected_scope or source_entity != expected_source:
            raise ClosedSetFactValidationError("closed-set evidence source is invalid")
        if expected_scope == "direct":
            if refs != []:
                raise ClosedSetFactValidationError("direct fact has context refs")
        else:
            expected_ref = _sha(
                _canonical(
                    {
                        "end": end,
                        "evidence_field": field,
                        "evidence_source_entity_id": expected_source,
                        "evidence_text_sha256": fact["evidence_text_sha256"],
                        "start": start,
                    }
                )
            )
            if refs != [expected_ref]:
                raise ClosedSetFactValidationError("cross-context ref is invalid")

        source = attributes.get("rule_source")
        phrase = _tokens(str(attributes.get("matched_phrase")))
        canonical_value = str(fact.get("canonical_value"))
        fact_type = str(fact.get("fact_type"))
        if source == "closed_set_registry":
            rule = index["semantic"].get((fact_type, canonical_value, phrase))
            if rule is None:
                raise ClosedSetFactValidationError("registry fact is not governed")
        elif source == "dim_tag_v6.3_final":
            key = (canonical_value, phrase)
            if key not in index["tag_phrases"]:
                raise ClosedSetFactValidationError("tag fact is not dictionary-bound")
            if field != "current_comment_body" and voc["voc_type"] == "comment_context_voc":
                raise ClosedSetFactValidationError("comment tag inherited parent evidence")
            if fact["decision_status"] == "promoted" and key not in index["approved_tags"]:
                raise ClosedSetFactValidationError("legacy lexical tag was promoted")
        elif source == "momcozy_product_entity_ledger":
            if fact_type == "entity_brand_fact":
                matches = [
                    row
                    for row in index["brand_specs"]
                    if row[0] == canonical_value and row[2] == phrase
                ]
                if not matches:
                    raise ClosedSetFactValidationError("brand fact is not ledger-bound")
                if (
                    canonical_value == "competitor"
                    and len(phrase) == 1
                    and fact["decision_status"] == "promoted"
                    and not _has_context(fields[field], start, end, index)
                ):
                    raise ClosedSetFactValidationError(
                        "single-token competitor lacks context"
                    )
            elif fact_type == "entity_product_fact":
                matches = [
                    row
                    for row in index["product_specs"]
                    if row["canonical_value"] == canonical_value
                    and row["tokens"] == phrase
                ]
                if not matches:
                    raise ClosedSetFactValidationError("product fact is not ledger-bound")
                if (
                    all(row["match_type"] == "contextual_alias" for row in matches)
                    and fact["decision_status"] == "promoted"
                    and not _has_context(fields[field], start, end, index)
                ):
                    raise ClosedSetFactValidationError(
                        "contextual product lacks context"
                    )
            else:
                raise ClosedSetFactValidationError("ledger fact type is invalid")
        else:
            raise ClosedSetFactValidationError("closed-set rule source is invalid")

        fact_key = (
            fact["voc_id"],
            fact_type,
            canonical_value,
            field,
            start,
            end,
            source_entity,
            scope,
        )
        expected_decision = expected_decisions.get(fact_key)
        if expected_decision is not None and expected_decision != (
            fact["decision_status"],
            tuple(reasons),
        ):
            raise ClosedSetFactValidationError(
                "closed-set fact decision or reasons do not reproduce"
            )
        if fact_key in observed_keys:
            raise ClosedSetFactValidationError("duplicate closed-set fact key")

        if fact["decision_status"] == "promoted":
            promoted += 1
            if fact_type == "entity_sentiment_fact":
                promoted_sentiments.setdefault((fact["voc_id"], field), set()).add(
                    canonical_value
                )
        else:
            held += 1
            if not set(reasons) & HELD_REASONS:
                raise ClosedSetFactValidationError("held fact lacks held reason")
        observed_keys.add(fact_key)

    if any(len(values) > 1 for values in promoted_sentiments.values()):
        raise ClosedSetFactValidationError("conflicting sentiment was promoted")
    expected = set(expected_decisions)
    if observed_keys != expected:
        raise ClosedSetFactValidationError(
            "closed-set fact keys do not reproduce the governed phrase inventory"
        )
    return {
        "fact_rows": len(rows),
        "held_rows": held,
        "promoted_rows": promoted,
        "unaccounted_fact_keys": 0,
    }
