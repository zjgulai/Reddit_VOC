from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import html
from html.entities import html5 as HTML5_ENTITIES
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata


PERSONA_DICTIONARY_SHA256 = (
    "279b313509141eb0f7432040818e261178fd9f75ec67a947a0cb9e6211799b1e"
)
PERSONA_DICTIONARY_HEADERS = (
    "persona_id",
    "persona_name",
    "dimension",
    "sub_dimension",
    "definition",
    "keywords",
    "semantic_pattern",
    "confidence_rules",
    "aip_likelihood",
    "lifecycle_stage",
    "hit_rate_tier",
)
PERSONA_ID = re.compile(r"^PER-(WHO|WHY|WHAT|WHEN|HOW|EMOTION|TECH)-\d{3}$")
TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
HTML_CHARREF = re.compile(
    r"&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)"
)
MATCHER_VERSION = "persona_atomic_match_v1"
PREPROCESSOR_VERSION = "persona_text_preprocess_v1"
FACT_SCHEMA_VERSION = "reddit_voc_persona_atomic_fact_v1"
ASSIGNMENT_SCHEMA_VERSION = "reddit_voc_persona_cohort_assignment_v1"
PRONOUNS = frozenset({"i", "me", "my", "mine", "we", "our"})
FIELD_ORDER = {"post_title": 0, "post_body": 1, "current_comment_body": 2}
EVIDENCE_SCOPE_ORDER = {
    "post_title": 0,
    "post_body": 1,
    "current_comment_body": 2,
    "cross_context": 3,
}
TRIGGER_REQUIREMENT_TO_SIGNAL = {
    "required_brand_roles_any": "brand_roles",
    "required_problem_ids_any": "problem_ids",
    "required_scenario_ids_any": "scenario_ids",
    "required_topic_ids_any": "topic_ids",
    "required_voc_tag_ids_any": "voc_tag_ids",
}
TRIGGER_PATH_KEYS = frozenset(
    {"path_id", "requires_bridge_match", *TRIGGER_REQUIREMENT_TO_SIGNAL}
)
SIGNAL_FACT_TYPES = {
    "brand_roles": frozenset({"entity_brand_fact"}),
    "problem_ids": frozenset({"entity_problem_fact"}),
    "scenario_ids": frozenset({"entity_tag_fact"}),
    "topic_ids": frozenset({"entity_tag_fact"}),
    "voc_tag_ids": frozenset({"entity_tag_fact"}),
}
SIGNAL_EVIDENCE_REF_KEYS = frozenset(
    {
        "canonical_value",
        "end",
        "evidence_field",
        "evidence_text_sha256",
        "fact_type",
        "source_fact_id",
        "source_snapshot_id",
        "start",
    }
)
GOVERNED_SIGNAL_FACT_KEYS = frozenset(
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
REDDIT_BARE_ID = re.compile(r"^[a-z0-9]+$")
WHITESPACE_CODEPOINTS = frozenset(
    {
        "\t",
        "\n",
        "\v",
        "\f",
        "\r",
        " ",
        "\u0085",
        "\u00a0",
        "\u1680",
        "\u2000",
        "\u2001",
        "\u2002",
        "\u2003",
        "\u2004",
        "\u2005",
        "\u2006",
        "\u2007",
        "\u2008",
        "\u2009",
        "\u200a",
        "\u2028",
        "\u2029",
        "\u202f",
        "\u205f",
        "\u3000",
    }
)
BRAND_ALIASES = (
    "momcozy",
    "spectra",
    "medela",
    "elvie",
    "willow",
    "eufy",
    "lansinoh",
)
PLATFORM_ALIASES = ("reddit", "amazon", "tiktok", "facebook", "instagram")
TECH_PERSONA_IDS = frozenset({"PER-TECH-001", "PER-TECH-002", "PER-TECH-003"})


class PersonaInferenceError(ValueError):
    """The persona dictionary, evidence or cohort inference is not governed."""


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
        raise PersonaInferenceError(
            "value is not canonical JSON serializable"
        ) from exc


@dataclass(frozen=True)
class PersonaDefinition:
    persona_id: str
    persona_name: str
    dimension: str
    sub_dimension: str
    definition: str
    keywords: tuple[str, ...]
    semantic_pattern: str
    lifecycle_stage: str
    hit_rate_tier: str


@dataclass(frozen=True)
class _KeywordSpec:
    dictionary_keyword: str
    normalized_keyword: str
    tokens: tuple[str, ...]
    shared: bool
    acronym: bool


@dataclass(frozen=True)
class PersonaDictionary:
    definitions: tuple[PersonaDefinition, ...]
    keyword_specs: dict[str, tuple[_KeywordSpec, ...]]
    shared_keywords: frozenset[str]
    keyword_instance_count: int
    unique_keyword_count: int
    template_keyword_count: int
    sha256: str

    @property
    def by_id(self) -> dict[str, PersonaDefinition]:
        return {row.persona_id: row for row in self.definitions}


@dataclass(frozen=True)
class PersonaEvidenceSpan:
    field: str
    start: int
    end: int
    normalized_keyword: str
    dictionary_keyword: str
    evidence_hash: str
    evidence_class: str

    def as_dict(self) -> dict[str, object]:
        return {
            "dictionary_keyword": self.dictionary_keyword,
            "end": self.end,
            "evidence_class": self.evidence_class,
            "evidence_hash": self.evidence_hash,
            "field": self.field,
            "normalized_keyword": self.normalized_keyword,
            "start": self.start,
        }


@dataclass(frozen=True)
class PersonaAtomicFact:
    fact_id: str
    voc_id: str
    canonical_entity_id: str
    source_entity_type: str
    voc_type: str
    persona_id: str
    decision_status: str
    confidence: Decimal
    evidence_class: str
    matched_keywords: tuple[str, ...]
    evidence_spans: tuple[PersonaEvidenceSpan, ...]
    decision_reason_codes: tuple[str, ...]
    dictionary_sha256: str
    matcher_version: str
    preprocessor_version: str
    snapshot_id: str
    schema_version: str = FACT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "canonical_entity_id": self.canonical_entity_id,
            "confidence": format(self.confidence, ".2f"),
            "decision_reason_codes": list(self.decision_reason_codes),
            "decision_status": self.decision_status,
            "dictionary_sha256": self.dictionary_sha256,
            "evidence_class": self.evidence_class,
            "evidence_spans": [span.as_dict() for span in self.evidence_spans],
            "fact_id": self.fact_id,
            "matched_keywords": list(self.matched_keywords),
            "matcher_version": self.matcher_version,
            "persona_id": self.persona_id,
            "preprocessor_version": self.preprocessor_version,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "source_entity_type": self.source_entity_type,
            "voc_id": self.voc_id,
            "voc_type": self.voc_type,
        }


@dataclass(frozen=True)
class PersonaCohortDefinition:
    cohort_id: str
    name_cn: str
    definition: str
    persona_tag_ids: tuple[str, ...]
    trigger_paths: tuple[dict[str, object], ...]
    avatar: dict[str, object]


@dataclass(frozen=True)
class PersonaCohortConfig:
    config_version: str
    config_sha256: str
    dictionary_sha256: str
    cohorts: tuple[PersonaCohortDefinition, ...]
    unbridged_persona_tag_ids: tuple[str, ...]
    availability_thresholds: dict[str, int]


@dataclass(frozen=True)
class PersonaCohortAssignment:
    assignment_id: str
    entity_id: str
    source_entity_type: str
    voc_type: str
    voc_id: str
    thread_id: str
    parent_post_id: str
    cohort_id: str
    persona_tag_ids: tuple[str, ...]
    voc_tag_ids: tuple[str, ...]
    scope: str
    evidence_scope: tuple[str, ...]
    evidence_grade: str
    source_stratum: str
    snapshot_id: str
    schema_version: str = ASSIGNMENT_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "cohort_id": self.cohort_id,
            "entity_id": self.entity_id,
            "evidence_grade": self.evidence_grade,
            "evidence_scope": list(self.evidence_scope),
            "parent_post_id": self.parent_post_id,
            "persona_tag_ids": list(self.persona_tag_ids),
            "schema_version": self.schema_version,
            "scope": self.scope,
            "snapshot_id": self.snapshot_id,
            "source_entity_type": self.source_entity_type,
            "source_stratum": self.source_stratum,
            "thread_id": self.thread_id,
            "voc_id": self.voc_id,
            "voc_tag_ids": list(self.voc_tag_ids),
            "voc_type": self.voc_type,
        }


@dataclass(frozen=True)
class _NormalizedText:
    text: str
    source_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _Token:
    text: str
    normalized_start: int
    normalized_end: int
    source_start: int
    source_end: int
    segment: int


@dataclass(frozen=True)
class _Candidate:
    persona_id: str
    spec: _KeywordSpec
    field: str
    start: int
    end: int
    token_start_index: int
    token_end_index: int
    evidence_class: str
    evidence_hash: str


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PersonaInferenceError(f"{label} must be a non-empty string")
    return value


def _simple_normalize(value: str) -> str:
    value = html.unescape(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "`": "'"}))
    value = value.casefold()
    return " ".join(token.group(0) for token in TOKEN.finditer(value))


def _expand_keyword(value: str) -> tuple[str, ...]:
    if "[brand]" in value:
        return tuple(value.replace("[brand]", alias) for alias in BRAND_ALIASES)
    if "[platform]" in value:
        return tuple(value.replace("[platform]", alias) for alias in PLATFORM_ALIASES)
    return (value,)


def load_persona_dictionary(path: Path) -> PersonaDictionary:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise PersonaInferenceError("persona dictionary is unreadable") from exc
    digest = sha256(payload).hexdigest()
    if digest != PERSONA_DICTIONARY_SHA256:
        raise PersonaInferenceError("persona dictionary SHA is invalid")
    try:
        text = payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PersonaInferenceError("persona dictionary CSV is invalid") from exc
    if tuple(reader.fieldnames or ()) != PERSONA_DICTIONARY_HEADERS:
        raise PersonaInferenceError("persona dictionary headers are invalid")
    if len(rows) != 82:
        raise PersonaInferenceError("persona dictionary row count is invalid")

    definitions: list[PersonaDefinition] = []
    keyword_owners: dict[str, set[str]] = defaultdict(set)
    raw_keywords_by_id: dict[str, tuple[str, ...]] = {}
    seen_ids: set[str] = set()
    template_count = 0
    keyword_instances = 0
    for row in rows:
        persona_id = _string(row.get("persona_id"), "persona ID")
        match = PERSONA_ID.fullmatch(persona_id)
        if match is None or persona_id in seen_ids:
            raise PersonaInferenceError("persona dictionary ID is invalid or duplicate")
        seen_ids.add(persona_id)
        dimension = _string(row.get("dimension"), "persona dimension")
        if match.group(1) != dimension:
            raise PersonaInferenceError("persona dictionary dimension mismatch")
        try:
            keywords_value = json.loads(row["keywords"])
            confidence_rules = json.loads(row["confidence_rules"])
            aip_likelihood = json.loads(row["aip_likelihood"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise PersonaInferenceError("persona dictionary JSON is invalid") from exc
        if (
            not isinstance(keywords_value, list)
            or not keywords_value
            or any(not isinstance(item, str) or not item for item in keywords_value)
            or confidence_rules != {"直接陈述": "A", "行为暗示": "B"}
            or not isinstance(aip_likelihood, Mapping)
        ):
            raise PersonaInferenceError("persona dictionary evidence contract is invalid")
        keywords = tuple(keywords_value)
        keyword_instances += len(keywords)
        template_count += sum("[" in item or "]" in item for item in keywords)
        for keyword in keywords:
            normalized = _simple_normalize(keyword)
            if not normalized:
                raise PersonaInferenceError("persona dictionary keyword has zero tokens")
            keyword_owners[normalized].add(persona_id)
        raw_keywords_by_id[persona_id] = keywords
        definitions.append(
            PersonaDefinition(
                persona_id=persona_id,
                persona_name=_string(row.get("persona_name"), "persona name"),
                dimension=dimension,
                sub_dimension=_string(
                    row.get("sub_dimension"), "persona sub-dimension"
                ),
                definition=_string(row.get("definition"), "persona definition"),
                keywords=keywords,
                semantic_pattern=_string(
                    row.get("semantic_pattern"), "persona semantic pattern"
                ),
                lifecycle_stage=_string(
                    row.get("lifecycle_stage"), "persona lifecycle stage"
                ),
                hit_rate_tier=_string(
                    row.get("hit_rate_tier"), "persona hit-rate tier"
                ),
            )
        )
    definitions.sort(key=lambda row: row.persona_id)
    shared = frozenset(
        keyword for keyword, owners in keyword_owners.items() if len(owners) > 1
    )
    if (
        keyword_instances != 454
        or len(keyword_owners) != 425
        or len(shared) != 28
        or template_count != 5
    ):
        raise PersonaInferenceError("persona dictionary summary is invalid")

    keyword_specs: dict[str, tuple[_KeywordSpec, ...]] = {}
    for definition in definitions:
        specs: list[_KeywordSpec] = []
        seen_specs: set[tuple[str, str]] = set()
        for raw_keyword in raw_keywords_by_id[definition.persona_id]:
            raw_normalized = _simple_normalize(raw_keyword)
            is_shared = raw_normalized in shared
            acronym = raw_keyword.isascii() and raw_keyword.isupper() and any(
                character.isalpha() for character in raw_keyword
            )
            for expanded in _expand_keyword(raw_keyword):
                normalized = _simple_normalize(expanded)
                tokens = tuple(normalized.split())
                key = (raw_keyword, normalized)
                if key in seen_specs:
                    continue
                seen_specs.add(key)
                specs.append(
                    _KeywordSpec(
                        dictionary_keyword=raw_keyword,
                        normalized_keyword=normalized,
                        tokens=tokens,
                        shared=is_shared,
                        acronym=acronym,
                    )
                )
        specs.sort(
            key=lambda spec: (
                -len(spec.tokens),
                spec.normalized_keyword,
                spec.dictionary_keyword,
            )
        )
        keyword_specs[definition.persona_id] = tuple(specs)
    return PersonaDictionary(
        definitions=tuple(definitions),
        keyword_specs=keyword_specs,
        shared_keywords=shared,
        keyword_instance_count=keyword_instances,
        unique_keyword_count=len(keyword_owners),
        template_keyword_count=template_count,
        sha256=digest,
    )


def _mask_range(characters: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if characters[index] not in {"\n", "\r"}:
            characters[index] = " "


def _mask_markup(source: str) -> str:
    characters = list(source)
    offset = 0
    in_fence = False
    fence_character = ""
    fence_length = 0
    for line in source.splitlines(keepends=True):
        stripped = line.lstrip()
        marker_match = re.match(r"(`{3,}|~{3,})", stripped)
        if in_fence:
            _mask_range(characters, offset, offset + len(line))
            marker = marker_match.group(1) if marker_match else ""
            marker_remainder = stripped[len(marker) :].strip() if marker else ""
            if (
                marker
                and marker[0] == fence_character
                and len(marker) >= fence_length
                and not marker_remainder
            ):
                in_fence = False
                fence_character = ""
                fence_length = 0
        elif marker_match:
            in_fence = True
            fence_character = marker_match.group(1)[0]
            fence_length = len(marker_match.group(1))
            _mask_range(characters, offset, offset + len(line))
        elif stripped.startswith(">"):
            _mask_range(characters, offset, offset + len(line))
        offset += len(line)
    masked = "".join(characters)
    characters = list(masked)
    line_offset = 0
    for line in masked.splitlines(keepends=True):
        line_body = line.rstrip("\r\n")
        runs = list(re.finditer(r"`+", line_body))
        index = 0
        while index < len(runs):
            opening = runs[index]
            closing_index = next(
                (
                    candidate_index
                    for candidate_index in range(index + 1, len(runs))
                    if len(runs[candidate_index].group(0))
                    == len(opening.group(0))
                ),
                None,
            )
            if closing_index is None:
                index += 1
                continue
            closing = runs[closing_index]
            _mask_range(
                characters,
                line_offset + opening.start(),
                line_offset + closing.end(),
            )
            index = closing_index + 1
        line_offset += len(line)
    inline_masked = "".join(characters)
    for match in URL.finditer(inline_masked):
        _mask_range(characters, match.start(), match.end())
    return "".join(characters)


def _decode_html5_with_spans(source: str) -> _NormalizedText:
    output: list[str] = []
    spans: list[tuple[int, int]] = []
    position = 0
    for match in HTML_CHARREF.finditer(source):
        for index in range(position, match.start()):
            output.append(source[index])
            spans.append((index, index + 1))
        raw = match.group(0)
        body = match.group(1)
        if body.startswith("#"):
            replacement = html.unescape(raw)
            output.extend(replacement)
            spans.extend([(match.start(), match.end())] * len(replacement))
        else:
            entity_key = body if body in HTML5_ENTITIES else None
            if entity_key is None:
                for length in range(len(body) - 1, 1, -1):
                    if body[:length] in HTML5_ENTITIES:
                        entity_key = body[:length]
                        break
            if entity_key is None:
                for index in range(match.start(), match.end()):
                    output.append(source[index])
                    spans.append((index, index + 1))
            else:
                replacement = HTML5_ENTITIES[entity_key]
                entity_end = match.start() + 1 + len(entity_key)
                output.extend(replacement)
                spans.extend([(match.start(), entity_end)] * len(replacement))
                for index in range(entity_end, match.end()):
                    output.append(source[index])
                    spans.append((index, index + 1))
        position = match.end()
    for index in range(position, len(source)):
        output.append(source[index])
        spans.append((index, index + 1))
    return _NormalizedText(text="".join(output), source_spans=tuple(spans))


def _append_normalized(
    output: list[str],
    spans: list[tuple[int, int]],
    value: str,
    source_start: int,
    source_end: int,
) -> None:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(
        str.maketrans({"’": "'", "‘": "'", "`": "'"})
    ).casefold()
    for character in normalized:
        output.append(" " if character in WHITESPACE_CODEPOINTS else character)
        spans.append((source_start, source_end))


def _normalize_source(source: str, *, mask_markup: bool) -> _NormalizedText:
    decoded = _decode_html5_with_spans(source)
    prepared = _mask_markup(decoded.text) if mask_markup else decoded.text
    output: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(prepared):
        source_start, source_end = decoded.source_spans[index]
        _append_normalized(
            output,
            spans,
            character,
            source_start,
            source_end,
        )
    return _NormalizedText(text="".join(output), source_spans=tuple(spans))


def _tokens(value: _NormalizedText) -> tuple[_Token, ...]:
    segment_by_position: list[int] = []
    segment = 0
    for character in value.text:
        segment_by_position.append(segment)
        if character in {".", "!", "?", "\n"}:
            segment += 1
    result: list[_Token] = []
    for match in TOKEN.finditer(value.text):
        source_start = value.source_spans[match.start()][0]
        source_end = value.source_spans[match.end() - 1][1]
        result.append(
            _Token(
                text=match.group(0),
                normalized_start=match.start(),
                normalized_end=match.end(),
                source_start=source_start,
                source_end=source_end,
                segment=segment_by_position[match.start()],
            )
        )
    return tuple(result)


def _voc(value: object) -> Mapping[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        raise PersonaInferenceError("persona VOC must be an object")
    return value


def _validate_voc_identity(
    row: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    voc_id = _string(row.get("voc_id"), "VOC ID")
    voc_type = _string(row.get("voc_type"), "VOC type")
    entity_id = _string(row.get("canonical_entity_id"), "canonical entity ID")
    post_id = _string(row.get("post_id"), "parent post ID")
    if REDDIT_BARE_ID.fullmatch(post_id) is None:
        raise PersonaInferenceError("persona VOC post identity is invalid")
    if voc_type == "post_voc":
        source_entity_type = "post"
        expected_voc_id = f"post:{post_id}"
        expected_entity_id = f"t3_{post_id}"
    elif voc_type == "comment_context_voc":
        source_entity_type = "comment"
        comment_id = _string(row.get("comment_id"), "comment ID")
        if REDDIT_BARE_ID.fullmatch(comment_id) is None:
            raise PersonaInferenceError("persona VOC comment identity is invalid")
        expected_voc_id = f"comment:{comment_id}"
        expected_entity_id = f"t1_{comment_id}"
    else:
        raise PersonaInferenceError("persona VOC type is unsupported")
    if voc_id != expected_voc_id or entity_id != expected_entity_id:
        raise PersonaInferenceError("persona VOC identity mismatch")
    return voc_id, voc_type, entity_id, source_entity_type


def _persona_fields(voc: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    fields = voc.get("analysis_fields")
    if not isinstance(fields, Mapping):
        raise PersonaInferenceError("persona VOC analysis fields are invalid")
    voc_type = _string(voc.get("voc_type"), "VOC type")
    names = (
        ("post_title", "post_body")
        if voc_type == "post_voc"
        else ("current_comment_body",)
        if voc_type == "comment_context_voc"
        else ()
    )
    if not names:
        raise PersonaInferenceError("persona VOC type is unsupported")
    result: list[tuple[str, str]] = []
    for name in names:
        text = fields.get(name, "")
        if not isinstance(text, str):
            raise PersonaInferenceError(f"persona VOC {name} must be a string")
        result.append((name, text))
    return tuple(result)


def _candidate_evidence_class(
    spec: _KeywordSpec,
    tokens: Sequence[_Token],
    start_index: int,
    end_index: int,
) -> str:
    if len(spec.tokens) >= 2 or spec.acronym:
        return "A"
    segment = tokens[start_index].segment
    low = max(0, start_index - 4)
    high = min(len(tokens), end_index + 4)
    if any(
        token.segment == segment and token.text in PRONOUNS
        for token in tokens[low:high]
    ):
        return "A"
    return "B"


def _find_candidates(
    *,
    persona_id: str,
    specs: Sequence[_KeywordSpec],
    field: str,
    source: str,
    tokens: Sequence[_Token],
) -> list[_Candidate]:
    result: list[_Candidate] = []
    token_texts = tuple(token.text for token in tokens)
    for spec in specs:
        width = len(spec.tokens)
        if width == 0 or width > len(tokens):
            continue
        for index in range(0, len(tokens) - width + 1):
            if token_texts[index : index + width] != spec.tokens:
                continue
            selected = tokens[index : index + width]
            if len({token.segment for token in selected}) != 1:
                continue
            start = selected[0].source_start
            end = selected[-1].source_end
            substring = source[start:end]
            evidence_hash = sha256(
                f"{field}\x1f{start}\x1f{end}\x1f{substring}".encode("utf-8")
            ).hexdigest()
            result.append(
                _Candidate(
                    persona_id=persona_id,
                    spec=spec,
                    field=field,
                    start=start,
                    end=end,
                    token_start_index=index,
                    token_end_index=index + width,
                    evidence_class=_candidate_evidence_class(
                        spec, tokens, index, index + width
                    ),
                    evidence_hash=evidence_hash,
                )
            )
    return result


def _resolve_candidates(values: Sequence[_Candidate]) -> tuple[_Candidate, ...]:
    earliest_by_keyword: dict[str, _Candidate] = {}
    for candidate in values:
        keyword = candidate.spec.normalized_keyword
        existing = earliest_by_keyword.get(keyword)
        candidate_order = (
            FIELD_ORDER[candidate.field],
            candidate.start,
            candidate.end,
            candidate.spec.dictionary_keyword,
        )
        if existing is None or candidate_order < (
            FIELD_ORDER[existing.field],
            existing.start,
            existing.end,
            existing.spec.dictionary_keyword,
        ):
            earliest_by_keyword[keyword] = candidate
    ordered = sorted(
        earliest_by_keyword.values(),
        key=lambda row: (
            -len(row.spec.tokens),
            -(row.end - row.start),
            row.spec.normalized_keyword,
            FIELD_ORDER[row.field],
            row.start,
            row.end,
        ),
    )
    selected: list[_Candidate] = []
    keywords: set[str] = set()
    for candidate in ordered:
        if candidate.spec.normalized_keyword in keywords:
            continue
        if any(
            candidate.field == existing.field
            and candidate.start < existing.end
            and existing.start < candidate.end
            for existing in selected
        ):
            continue
        selected.append(candidate)
        keywords.add(candidate.spec.normalized_keyword)
    selected.sort(
        key=lambda row: (
            FIELD_ORDER[row.field],
            row.start,
            row.end,
            row.spec.normalized_keyword,
        )
    )
    return tuple(selected)


def _confidence(evidence_class: str, distinct_keywords: int) -> Decimal:
    value = Decimal("0.80") if evidence_class == "A" else Decimal("0.60")
    if distinct_keywords >= 2:
        value += Decimal("0.10")
    if distinct_keywords >= 3:
        value += Decimal("0.05")
    return min(value, Decimal("0.95")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _fact_identity_payload(fact: PersonaAtomicFact) -> dict[str, object]:
    value = fact.as_dict()
    value.pop("fact_id")
    return value


def _refresh_fact_id(fact: PersonaAtomicFact) -> PersonaAtomicFact:
    placeholder = replace(fact, fact_id="")
    return replace(
        placeholder,
        fact_id=sha256(canonical_json_bytes(_fact_identity_payload(placeholder))).hexdigest(),
    )


def _validate_persona_fact_static(
    fact: PersonaAtomicFact,
    *,
    expected_dictionary_sha256: str | None = None,
    expected_persona_ids: set[str] | None = None,
) -> None:
    if not isinstance(fact, PersonaAtomicFact):
        raise PersonaInferenceError("persona fact input is invalid")
    if fact.voc_type == "post_voc" and fact.source_entity_type == "post":
        voc_prefix = "post:"
        entity_prefix = "t3_"
    elif (
        fact.voc_type == "comment_context_voc"
        and fact.source_entity_type == "comment"
    ):
        voc_prefix = "comment:"
        entity_prefix = "t1_"
    else:
        raise PersonaInferenceError("persona fact source identity is invalid")
    if (
        not isinstance(fact.voc_id, str)
        or not fact.voc_id.startswith(voc_prefix)
        or REDDIT_BARE_ID.fullmatch(fact.voc_id[len(voc_prefix) :]) is None
        or fact.canonical_entity_id
        != f"{entity_prefix}{fact.voc_id[len(voc_prefix) :]}"
    ):
        raise PersonaInferenceError("persona fact source identity is invalid")
    if (
        fact.schema_version != FACT_SCHEMA_VERSION
        or fact.matcher_version != MATCHER_VERSION
        or fact.preprocessor_version != PREPROCESSOR_VERSION
        or fact.dictionary_sha256 != (
            expected_dictionary_sha256 or PERSONA_DICTIONARY_SHA256
        )
    ):
        raise PersonaInferenceError("persona fact provenance is invalid")
    if (
        not isinstance(fact.persona_id, str)
        or PERSONA_ID.fullmatch(fact.persona_id) is None
        or (
            expected_persona_ids is not None
            and fact.persona_id not in expected_persona_ids
        )
        or fact.decision_status not in {"promoted", "held"}
        or fact.evidence_class not in {"A", "B"}
        or not isinstance(fact.confidence, Decimal)
        or not fact.confidence.is_finite()
        or not Decimal("0.00") <= fact.confidence <= Decimal("0.95")
    ):
        raise PersonaInferenceError("persona fact decision is invalid")
    if (
        not isinstance(fact.evidence_spans, tuple)
        or not fact.evidence_spans
        or not isinstance(fact.matched_keywords, tuple)
        or not isinstance(fact.decision_reason_codes, tuple)
        or not fact.decision_reason_codes
        or any(
            not isinstance(reason, str) or not reason
            for reason in fact.decision_reason_codes
        )
        or fact.decision_reason_codes
        != tuple(sorted(set(fact.decision_reason_codes)))
    ):
        raise PersonaInferenceError("persona fact evidence contract is invalid")
    for span in fact.evidence_spans:
        if (
            not isinstance(span, PersonaEvidenceSpan)
            or span.field not in FIELD_ORDER
            or type(span.start) is not int
            or type(span.end) is not int
            or span.start < 0
            or span.end <= span.start
            or not isinstance(span.normalized_keyword, str)
            or not span.normalized_keyword
            or not isinstance(span.dictionary_keyword, str)
            or not span.dictionary_keyword
            or span.evidence_class not in {"A", "B"}
            or not isinstance(span.evidence_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", span.evidence_hash) is None
        ):
            raise PersonaInferenceError("persona fact evidence span is invalid")
    if (
        fact.matched_keywords
        != tuple(span.normalized_keyword for span in fact.evidence_spans)
        or fact.evidence_class
        != ("A" if any(span.evidence_class == "A" for span in fact.evidence_spans) else "B")
        or not isinstance(fact.snapshot_id, str)
        or not fact.snapshot_id
        or not isinstance(fact.fact_id, str)
        or re.fullmatch(r"[0-9a-f]{64}", fact.fact_id) is None
        or _refresh_fact_id(fact).fact_id != fact.fact_id
    ):
        raise PersonaInferenceError("persona fact identity hash is invalid")


def _validate_persona_fact_against_voc(
    fact: PersonaAtomicFact,
    *,
    row: Mapping[str, Any],
    expected_dictionary_sha256: str,
    expected_persona_ids: set[str],
) -> None:
    _validate_persona_fact_static(
        fact,
        expected_dictionary_sha256=expected_dictionary_sha256,
        expected_persona_ids=expected_persona_ids,
    )
    voc_id, voc_type, entity_id, source_entity_type = _validate_voc_identity(row)
    if (
        fact.voc_id != voc_id
        or fact.voc_type != voc_type
        or fact.canonical_entity_id != entity_id
        or fact.source_entity_type != source_entity_type
    ):
        raise PersonaInferenceError("persona cohort fact identity is invalid")
    source_by_field = dict(_persona_fields(row))
    for span in fact.evidence_spans:
        source = source_by_field.get(span.field)
        if source is None or span.end > len(source):
            raise PersonaInferenceError("persona fact evidence scope is invalid")
        substring = source[span.start : span.end]
        expected_hash = sha256(
            f"{span.field}\x1f{span.start}\x1f{span.end}\x1f{substring}".encode(
                "utf-8"
            )
        ).hexdigest()
        if (
            expected_hash != span.evidence_hash
            or _simple_normalize(substring) != span.normalized_keyword
        ):
            raise PersonaInferenceError("persona fact evidence hash is invalid")


def infer_persona_facts(
    voc: object,
    *,
    dictionary: PersonaDictionary,
    snapshot_id: str,
) -> tuple[PersonaAtomicFact, ...]:
    if not isinstance(dictionary, PersonaDictionary):
        raise PersonaInferenceError("persona dictionary input is invalid")
    row = _voc(voc)
    (
        voc_id,
        voc_type,
        canonical_entity_id,
        source_entity_type,
    ) = _validate_voc_identity(row)
    snapshot_id = _string(snapshot_id, "snapshot ID")
    fields = _persona_fields(row)
    tokenized_fields = tuple(
        (field, source, _tokens(_normalize_source(source, mask_markup=True)))
        for field, source in fields
    )
    facts: list[PersonaAtomicFact] = []
    for definition in dictionary.definitions:
        candidates: list[_Candidate] = []
        for field, source, field_tokens in tokenized_fields:
            candidates.extend(
                _find_candidates(
                    persona_id=definition.persona_id,
                    specs=dictionary.keyword_specs[definition.persona_id],
                    field=field,
                    source=source,
                    tokens=field_tokens,
                )
            )
        retained = _resolve_candidates(candidates)
        if not retained:
            continue
        evidence_class = (
            "A" if any(row.evidence_class == "A" for row in retained) else "B"
        )
        distinct_keywords = len(
            {row.spec.normalized_keyword for row in retained}
        )
        confidence = _confidence(evidence_class, distinct_keywords)
        reasons: list[str] = []
        if all(row.spec.shared for row in retained):
            reasons.append("ambiguous_shared_keyword")
        if evidence_class == "B":
            reasons.append("weak_single_keyword")
        decision_status = "held" if reasons or confidence < Decimal("0.80") else "promoted"
        if not reasons:
            reasons.append("evidence_threshold_met")
        spans = tuple(
            PersonaEvidenceSpan(
                field=candidate.field,
                start=candidate.start,
                end=candidate.end,
                normalized_keyword=candidate.spec.normalized_keyword,
                dictionary_keyword=candidate.spec.dictionary_keyword,
                evidence_hash=candidate.evidence_hash,
                evidence_class=candidate.evidence_class,
            )
            for candidate in retained
        )
        fact = PersonaAtomicFact(
            fact_id="",
            voc_id=voc_id,
            canonical_entity_id=canonical_entity_id,
            source_entity_type=source_entity_type,
            voc_type=voc_type,
            persona_id=definition.persona_id,
            decision_status=decision_status,
            confidence=confidence,
            evidence_class=evidence_class,
            matched_keywords=tuple(
                span.normalized_keyword for span in spans
            ),
            evidence_spans=spans,
            decision_reason_codes=tuple(sorted(set(reasons))),
            dictionary_sha256=dictionary.sha256,
            matcher_version=MATCHER_VERSION,
            preprocessor_version=PREPROCESSOR_VERSION,
            snapshot_id=snapshot_id,
        )
        facts.append(_refresh_fact_id(fact))

    tech = sorted(
        [fact for fact in facts if fact.persona_id in TECH_PERSONA_IDS],
        key=lambda fact: (-fact.confidence, fact.persona_id),
    )
    if len(tech) >= 2:
        conflict = tech[0].confidence - tech[1].confidence < Decimal("0.15")
        replacements: dict[str, PersonaAtomicFact] = {}
        for index, fact in enumerate(tech):
            if conflict:
                reason = "exclusive_conflict"
            elif index > 0:
                reason = "exclusive_lower_rank"
            else:
                continue
            updated = replace(
                fact,
                fact_id="",
                decision_status="held",
                decision_reason_codes=tuple(
                    sorted(set(fact.decision_reason_codes) | {reason})
                ),
            )
            replacements[fact.persona_id] = _refresh_fact_id(updated)
        facts = [replacements.get(fact.persona_id, fact) for fact in facts]
    facts.sort(key=lambda fact: (fact.voc_id, fact.persona_id, fact.decision_status))
    return tuple(facts)


def canonical_persona_fact_jsonl_bytes(
    facts: Iterable[PersonaAtomicFact],
) -> bytes:
    values = list(facts)
    for fact in values:
        _validate_persona_fact_static(fact)
    if len({fact.fact_id for fact in values}) != len(values):
        raise PersonaInferenceError("duplicate persona fact ID")
    if len({(fact.voc_id, fact.persona_id) for fact in values}) != len(values):
        raise PersonaInferenceError("duplicate persona fact key")
    values.sort(key=lambda fact: (fact.voc_id, fact.persona_id, fact.decision_status))
    return b"".join(canonical_json_bytes(fact.as_dict()) + b"\n" for fact in values)


def _validated_trigger_path(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != TRIGGER_PATH_KEYS:
        raise PersonaInferenceError("persona cohort trigger path is invalid")
    path_id = value.get("path_id")
    requires_bridge = value.get("requires_bridge_match")
    if (
        not isinstance(path_id, str)
        or re.fullmatch(r"[a-z][a-z0-9_]*", path_id) is None
        or type(requires_bridge) is not bool
    ):
        raise PersonaInferenceError("persona cohort trigger path is invalid")
    normalized: dict[str, object] = {
        "path_id": path_id,
        "requires_bridge_match": requires_bridge,
    }
    has_signal_requirement = False
    for required_name in TRIGGER_REQUIREMENT_TO_SIGNAL:
        required = value.get(required_name)
        if (
            not isinstance(required, list)
            or any(not isinstance(item, str) or not item for item in required)
            or required != sorted(set(required))
        ):
            raise PersonaInferenceError("persona cohort trigger path is invalid")
        normalized[required_name] = list(required)
        has_signal_requirement = has_signal_requirement or bool(required)
    if not requires_bridge and not has_signal_requirement:
        raise PersonaInferenceError("persona cohort trigger path is empty")
    return normalized


def load_persona_cohort_config(
    path: Path,
    *,
    dictionary: PersonaDictionary,
) -> PersonaCohortConfig:
    try:
        payload = Path(path).read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonaInferenceError("persona cohort config is unreadable") from exc
    expected_payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if payload != expected_payload:
        raise PersonaInferenceError("persona cohort config is not canonical JSON")
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version")
        != "reddit_voc_persona_cohort_config_v1"
    ):
        raise PersonaInferenceError("persona cohort config schema is invalid")
    binding = value.get("dictionary_binding")
    if (
        not isinstance(binding, Mapping)
        or binding.get("sha256") != dictionary.sha256
        or binding.get("row_count") != len(dictionary.definitions)
    ):
        raise PersonaInferenceError("persona cohort dictionary binding is invalid")
    raw_cohorts = value.get("cohorts")
    if not isinstance(raw_cohorts, list) or len(raw_cohorts) != 8:
        raise PersonaInferenceError("persona cohort count is invalid")
    known_ids = set(dictionary.by_id)
    cohorts: list[PersonaCohortDefinition] = []
    edge_count = 0
    bridged: set[str] = set()
    seen_cohorts: set[str] = set()
    for raw in raw_cohorts:
        if not isinstance(raw, Mapping):
            raise PersonaInferenceError("persona cohort row is invalid")
        cohort_id = _string(raw.get("cohort_id"), "cohort ID")
        if re.fullmatch(r"[a-z][a-z0-9_]+", cohort_id) is None or cohort_id in seen_cohorts:
            raise PersonaInferenceError("persona cohort ID is invalid or duplicate")
        seen_cohorts.add(cohort_id)
        persona_ids = raw.get("persona_tag_ids")
        if (
            not isinstance(persona_ids, list)
            or not persona_ids
            or persona_ids != sorted(set(persona_ids))
            or not set(persona_ids) <= known_ids
        ):
            raise PersonaInferenceError("persona cohort bridge is invalid")
        trigger_paths = raw.get("trigger_paths")
        avatar = raw.get("avatar")
        if (
            not isinstance(trigger_paths, list)
            or not trigger_paths
            or not isinstance(avatar, Mapping)
        ):
            raise PersonaInferenceError("persona cohort trigger or avatar is invalid")
        validated_paths = tuple(_validated_trigger_path(path) for path in trigger_paths)
        path_ids = [str(path["path_id"]) for path in validated_paths]
        if len(path_ids) != len(set(path_ids)):
            raise PersonaInferenceError("persona cohort trigger path is duplicate")
        if (
            avatar.get("synthetic") is not True
            or avatar.get("real_user_image") is not False
            or avatar.get("derived_from_reddit_media") is not False
            or avatar.get("identity_claim") is not False
            or "非真实用户" not in str(avatar.get("alt_text", ""))
        ):
            raise PersonaInferenceError("persona cohort avatar boundary is invalid")
        edge_count += len(persona_ids)
        bridged.update(persona_ids)
        cohorts.append(
            PersonaCohortDefinition(
                cohort_id=cohort_id,
                name_cn=_string(raw.get("name_cn"), "cohort name"),
                definition=_string(raw.get("definition"), "cohort definition"),
                persona_tag_ids=tuple(persona_ids),
                trigger_paths=validated_paths,
                avatar=dict(avatar),
            )
        )
    cohorts.sort(key=lambda row: row.cohort_id)
    unbridged = value.get("unbridged_persona_tag_ids")
    if (
        not isinstance(unbridged, list)
        or unbridged != sorted(set(unbridged))
        or set(unbridged) != known_ids - bridged
        or edge_count != 141
        or len(bridged) != 79
    ):
        raise PersonaInferenceError("persona cohort bridge summary is invalid")
    summary = value.get("bridge_summary")
    if summary != {
        "bridge_edge_count": 141,
        "bridged_persona_tag_count": 79,
        "cohort_count": 8,
        "unbridged_persona_tag_count": 3,
    }:
        raise PersonaInferenceError("persona cohort bridge declared summary is invalid")
    thresholds = value.get("availability_thresholds")
    if thresholds != {
        "directional_sample_min": 10,
        "stable_sample_min": 30,
        "unavailable_below": 10,
    }:
        raise PersonaInferenceError("persona cohort thresholds are invalid")
    return PersonaCohortConfig(
        config_version=_string(value.get("config_version"), "cohort config version"),
        config_sha256=sha256(payload).hexdigest(),
        dictionary_sha256=dictionary.sha256,
        cohorts=tuple(cohorts),
        unbridged_persona_tag_ids=tuple(unbridged),
        availability_thresholds=dict(thresholds),
    )


def _signal_set(signals: Mapping[str, object], name: str) -> set[str]:
    value = signals.get(name, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise PersonaInferenceError(f"persona cohort signal {name} is invalid")
    return set(value)


def validate_governed_signal_fact(
    value: object,
    *,
    registry_fact_id: str,
) -> Mapping[str, object]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if not isinstance(value, Mapping) or set(value) != GOVERNED_SIGNAL_FACT_KEYS:
        raise PersonaInferenceError("governed signal fact schema is invalid")
    fact_id = value.get("fact_id")
    reason_codes = value.get("reason_codes")
    context_refs = value.get("context_evidence_refs")
    attributes = value.get("attributes")
    required_strings = (
        "canonical_entity_id",
        "canonical_value",
        "created_at",
        "dictionary_release_id",
        "evidence_field",
        "evidence_scope",
        "evidence_source_entity_id",
        "evidence_text_sha256",
        "fact_type",
        "matcher_version",
        "normalizer_version",
        "source_snapshot_id",
        "voc_id",
        "voc_type",
    )
    if (
        not isinstance(fact_id, str)
        or fact_id != registry_fact_id
        or re.fullmatch(r"[0-9a-f]{64}", fact_id) is None
        or value.get("schema_version") != "reddit_voc_atomic_fact_v2"
        or value.get("decision_status") != "promoted"
        or not isinstance(attributes, Mapping)
        or not isinstance(context_refs, list)
        or any(not isinstance(item, str) or not item for item in context_refs)
        or not isinstance(reason_codes, list)
        or not reason_codes
        or any(not isinstance(item, str) or not item for item in reason_codes)
        or reason_codes != sorted(set(reason_codes))
        or any(
            not isinstance(value.get(name), str) or not value.get(name)
            for name in required_strings
        )
        or type(value.get("evidence_start")) is not int
        or type(value.get("evidence_end")) is not int
        or value["evidence_start"] < 0
        or value["evidence_end"] <= value["evidence_start"]
        or re.fullmatch(
            r"[0-9a-f]{64}", str(value.get("evidence_text_sha256"))
        )
        is None
    ):
        raise PersonaInferenceError("governed signal fact provenance is invalid")
    identity_payload = dict(value)
    identity_payload.pop("fact_id")
    if sha256(canonical_json_bytes(identity_payload)).hexdigest() != fact_id:
        raise PersonaInferenceError("governed signal fact identity hash is invalid")
    return value


# Kept private at the call site so the evidence validator remains easy to read;
# the public name above is also used by the bound-input loader before inference.
_validated_governed_signal_fact = validate_governed_signal_fact


def _validated_signal_evidence_scope(
    signals: Mapping[str, object],
    *,
    signal_sets: Mapping[str, set[str]],
    row: Mapping[str, Any],
    governed_source_snapshot_id: str | None,
    governed_signal_facts_by_id: Mapping[str, object] | None,
) -> tuple[set[str], tuple[str, ...], tuple[dict[str, object], ...]]:
    raw_refs = signals.get("signal_evidence_refs", [])
    if not isinstance(raw_refs, list):
        raise PersonaInferenceError("persona signal evidence refs are invalid")
    has_signals = any(signal_sets.values())
    if has_signals and not raw_refs:
        raise PersonaInferenceError("persona signals lack evidence refs")
    if raw_refs and not has_signals:
        raise PersonaInferenceError("persona signal evidence refs are unbound")
    if has_signals and (
        not isinstance(governed_signal_facts_by_id, Mapping)
        or not governed_signal_facts_by_id
    ):
        raise PersonaInferenceError("persona signals lack governed fact registry")
    if has_signals and (
        not isinstance(governed_source_snapshot_id, str)
        or not governed_source_snapshot_id
    ):
        raise PersonaInferenceError(
            "persona signals lack governed source snapshot binding"
        )
    if not has_signals and governed_signal_facts_by_id:
        raise PersonaInferenceError("persona governed fact registry is unbound")

    voc_id, voc_type, entity_id, _source_entity_type = _validate_voc_identity(row)
    analysis_fields = row.get("analysis_fields")
    if not isinstance(analysis_fields, Mapping):
        raise PersonaInferenceError("persona VOC analysis fields are invalid")
    declared_pairs = {
        (signal_name, canonical_value)
        for signal_name, values in signal_sets.items()
        for canonical_value in values
    }
    supported_pairs: set[tuple[str, str]] = set()
    seen_fact_ids: set[str] = set()
    canonical_refs: list[dict[str, object]] = []
    derived_scope: set[str] = set()
    has_current_comment_ref = False
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, Mapping) or set(raw_ref) != SIGNAL_EVIDENCE_REF_KEYS:
            raise PersonaInferenceError("persona signal evidence ref schema is invalid")
        source_fact_id = _string(raw_ref.get("source_fact_id"), "source fact ID")
        fact_type = _string(raw_ref.get("fact_type"), "signal fact type")
        canonical_value = _string(
            raw_ref.get("canonical_value"), "signal canonical value"
        )
        evidence_field = _string(
            raw_ref.get("evidence_field"), "signal evidence field"
        )
        evidence_hash = _string(
            raw_ref.get("evidence_text_sha256"), "signal evidence hash"
        )
        source_snapshot_id = _string(
            raw_ref.get("source_snapshot_id"), "signal source snapshot ID"
        )
        start = raw_ref.get("start")
        end = raw_ref.get("end")
        if (
            re.fullmatch(r"[0-9a-f]{64}", source_fact_id) is None
            or source_fact_id in seen_fact_ids
            or re.fullmatch(r"[0-9a-f]{64}", evidence_hash) is None
            or type(start) is not int
            or type(end) is not int
            or start < 0
            or end <= start
        ):
            raise PersonaInferenceError("persona signal evidence ref provenance is invalid")
        if source_snapshot_id != governed_source_snapshot_id:
            raise PersonaInferenceError(
                "persona signal evidence source snapshot binding is invalid"
            )
        seen_fact_ids.add(source_fact_id)
        canonical_refs.append(dict(raw_ref))
        governed_fact = _validated_governed_signal_fact(
            governed_signal_facts_by_id.get(source_fact_id),
            registry_fact_id=source_fact_id,
        )
        if (
            governed_fact.get("voc_id") != voc_id
            or governed_fact.get("voc_type") != voc_type
            or governed_fact.get("canonical_entity_id") != entity_id
            or governed_fact.get("fact_type") != fact_type
            or governed_fact.get("canonical_value") != canonical_value
            or governed_fact.get("evidence_field") != evidence_field
            or governed_fact.get("evidence_start") != start
            or governed_fact.get("evidence_end") != end
            or governed_fact.get("evidence_text_sha256") != evidence_hash
            or governed_fact.get("source_snapshot_id") != source_snapshot_id
        ):
            raise PersonaInferenceError("persona signal fact join is invalid")
        source = analysis_fields.get(evidence_field)
        if not isinstance(source, str) or end > len(source):
            raise PersonaInferenceError("persona signal evidence span is invalid")
        substring = source[start:end]
        if (
            not substring.strip()
            or sha256(substring.encode("utf-8")).hexdigest() != evidence_hash
        ):
            raise PersonaInferenceError("persona signal evidence replay is invalid")

        matching_pairs = {
            (signal_name, canonical_value)
            for signal_name, allowed_fact_types in SIGNAL_FACT_TYPES.items()
            if fact_type in allowed_fact_types
            and canonical_value in signal_sets[signal_name]
        }
        if voc_type == "post_voc":
            if evidence_field not in {"post_title", "post_body"}:
                raise PersonaInferenceError("post signal evidence scope is invalid")
            if (
                governed_fact.get("evidence_source_entity_id") != entity_id
                or governed_fact.get("evidence_scope") != "direct"
            ):
                raise PersonaInferenceError("post signal fact evidence source is invalid")
            derived_scope.add(evidence_field)
        else:
            if evidence_field == "current_comment_body":
                if (
                    governed_fact.get("evidence_source_entity_id") != entity_id
                    or governed_fact.get("evidence_scope") != "direct"
                ):
                    raise PersonaInferenceError(
                        "comment signal fact evidence source is invalid"
                    )
                has_current_comment_ref = True
                derived_scope.add("current_comment_body")
            elif evidence_field in {"post_title", "post_body"}:
                expected_parent_entity_id = f"t3_{row['post_id']}"
                if (
                    governed_fact.get("evidence_source_entity_id")
                    != expected_parent_entity_id
                    or governed_fact.get("evidence_scope") != "cross_context"
                ):
                    raise PersonaInferenceError(
                        "comment context signal fact source is invalid"
                    )
                matching_pairs = {
                    pair
                    for pair in matching_pairs
                    if pair[0] in {"brand_roles", "topic_ids"}
                }
                derived_scope.add("cross_context")
            else:
                raise PersonaInferenceError("comment signal evidence scope is invalid")
        if not matching_pairs:
            raise PersonaInferenceError("persona signal evidence ref is unbound")
        supported_pairs.update(matching_pairs)

    if declared_pairs != supported_pairs:
        raise PersonaInferenceError("persona signal value lacks evidence ref")
    if has_signals and voc_type == "comment_context_voc" and not has_current_comment_ref:
        raise PersonaInferenceError("comment signal lacks current-body evidence ref")

    declared_scope = signals.get("evidence_scope", [])
    if not isinstance(declared_scope, list) or any(
        item not in EVIDENCE_SCOPE_ORDER for item in declared_scope
    ):
        raise PersonaInferenceError("persona cohort evidence scope is invalid")
    if declared_scope and set(declared_scope) != derived_scope:
        raise PersonaInferenceError("persona cohort evidence scope does not match refs")
    if not raw_refs and declared_scope:
        raise PersonaInferenceError("persona cohort evidence scope lacks refs")
    canonical_refs.sort(
        key=lambda value: (
            str(value["source_fact_id"]),
            str(value["fact_type"]),
            str(value["canonical_value"]),
            str(value["evidence_field"]),
            int(value["start"]),
            int(value["end"]),
        )
    )
    return derived_scope, tuple(sorted(seen_fact_ids)), tuple(canonical_refs)


def _path_matches(
    path: Mapping[str, object],
    *,
    bridge_matches: set[str],
    signal_sets: Mapping[str, set[str]],
) -> bool:
    validated = _validated_trigger_path(path)
    if validated["requires_bridge_match"] is True and not bridge_matches:
        return False
    for required_name, signal_name in TRIGGER_REQUIREMENT_TO_SIGNAL.items():
        required = validated[required_name]
        assert isinstance(required, list)
        if required and not set(required) & signal_sets[signal_name]:
            return False
    return True


def build_cohort_assignments(
    voc: object,
    *,
    facts: Iterable[PersonaAtomicFact],
    config: PersonaCohortConfig,
    signals: Mapping[str, object],
    explicit_automation: bool = False,
    governed_signal_facts_by_id: Mapping[str, object] | None = None,
    governed_source_snapshot_id: str | None = None,
) -> tuple[PersonaCohortAssignment, ...]:
    if type(explicit_automation) is not bool:
        raise PersonaInferenceError("explicit automation flag is invalid")
    if explicit_automation:
        return ()
    if not isinstance(config, PersonaCohortConfig) or not isinstance(signals, Mapping):
        raise PersonaInferenceError("persona cohort input is invalid")
    if (
        config.dictionary_sha256 != PERSONA_DICTIONARY_SHA256
        or re.fullmatch(r"[0-9a-f]{64}", config.config_sha256) is None
    ):
        raise PersonaInferenceError("persona cohort config provenance is invalid")
    row = _voc(voc)
    voc_id, voc_type, entity_id, source_entity_type = _validate_voc_identity(row)
    post_id = _string(row.get("post_id"), "parent post ID")
    thread_id = row.get("thread_id") or f"t3_{post_id}"
    thread_id = _string(thread_id, "thread ID")
    known_persona_ids = set(config.unbridged_persona_tag_ids)
    known_persona_ids.update(
        persona_id
        for cohort in config.cohorts
        for persona_id in cohort.persona_tag_ids
    )
    fact_values = list(facts)
    for fact in fact_values:
        _validate_persona_fact_against_voc(
            fact,
            row=row,
            expected_dictionary_sha256=config.dictionary_sha256,
            expected_persona_ids=known_persona_ids,
        )
    if (
        len({fact.fact_id for fact in fact_values}) != len(fact_values)
        or len({fact.persona_id for fact in fact_values}) != len(fact_values)
    ):
        raise PersonaInferenceError("duplicate persona cohort fact")
    promoted = {
        fact.persona_id: fact
        for fact in fact_values
        if fact.decision_status == "promoted"
    }
    signal_sets = {
        name: _signal_set(signals, name)
        for name in (
            "brand_roles",
            "problem_ids",
            "scenario_ids",
            "topic_ids",
            "voc_tag_ids",
        )
    }
    scope = signals.get("scope", "category_context")
    if scope not in {"momcozy_direct", "momcozy_multi", "category_context"}:
        raise PersonaInferenceError("persona cohort scope is invalid")
    source_stratum = signals.get("source_stratum", "governed_v3_voc")
    source_stratum = _string(source_stratum, "persona source stratum")
    snapshot_ids = {fact.snapshot_id for fact in fact_values}
    declared_snapshot = signals.get("snapshot_id")
    if declared_snapshot is not None:
        declared_snapshot = _string(declared_snapshot, "snapshot ID")
    snapshot_id = (
        next(iter(snapshot_ids))
        if len(snapshot_ids) == 1
        else _string(declared_snapshot, "snapshot ID")
        if not snapshot_ids
        else ""
    )
    if not snapshot_id or (
        declared_snapshot is not None and declared_snapshot != snapshot_id
    ):
        raise PersonaInferenceError("persona cohort snapshot binding is invalid")
    (
        signal_evidence_fields,
        governed_signal_fact_ids,
        signal_evidence_refs,
    ) = _validated_signal_evidence_scope(
        signals,
        signal_sets=signal_sets,
        row=row,
        governed_source_snapshot_id=governed_source_snapshot_id,
        governed_signal_facts_by_id=governed_signal_facts_by_id,
    )
    assignments: list[PersonaCohortAssignment] = []
    for cohort in config.cohorts:
        bridge_matches = set(cohort.persona_tag_ids) & set(promoted)
        if not any(
            _path_matches(
                path,
                bridge_matches=bridge_matches,
                signal_sets=signal_sets,
            )
            for path in cohort.trigger_paths
        ):
            continue
        evidence_fields = {
            span.field
            for persona_id in bridge_matches
            for span in promoted[persona_id].evidence_spans
        }
        evidence_fields.update(signal_evidence_fields)
        if not evidence_fields:
            raise PersonaInferenceError("persona cohort lacks evidence scope")
        if (
            voc_type == "comment_context_voc"
            and "current_comment_body" not in evidence_fields
        ):
            if "cross_context" in evidence_fields:
                raise PersonaInferenceError(
                    "persona cohort cross-context evidence requires current-body evidence"
                )
            raise PersonaInferenceError("comment cohort lacks current-body evidence")
        evidence_scope = tuple(
            sorted(evidence_fields, key=EVIDENCE_SCOPE_ORDER.__getitem__)
        )
        persona_fact_ids = tuple(
            sorted(promoted[persona_id].fact_id for persona_id in bridge_matches)
        )
        assignment_identity = {
            "cohort_config_sha256": config.config_sha256,
            "cohort_id": cohort.cohort_id,
            "evidence_scope": list(evidence_scope),
            "governed_signal_fact_ids": list(governed_signal_fact_ids),
            "persona_fact_ids": list(persona_fact_ids),
            "schema_version": "reddit_voc_persona_cohort_assignment_id_v2",
            "scope": scope,
            "signal_evidence_refs": list(signal_evidence_refs),
            "snapshot_id": snapshot_id,
            "source_stratum": source_stratum,
            "voc_id": voc_id,
            "voc_tag_ids": sorted(signal_sets["voc_tag_ids"]),
        }
        assignment_id = sha256(canonical_json_bytes(assignment_identity)).hexdigest()
        assignments.append(
            PersonaCohortAssignment(
                assignment_id=assignment_id,
                entity_id=entity_id,
                source_entity_type=source_entity_type,
                voc_type=voc_type,
                voc_id=voc_id,
                thread_id=thread_id,
                parent_post_id=post_id,
                cohort_id=cohort.cohort_id,
                persona_tag_ids=tuple(sorted(bridge_matches)),
                voc_tag_ids=tuple(sorted(signal_sets["voc_tag_ids"])),
                scope=str(scope),
                evidence_scope=evidence_scope,
                evidence_grade=(
                    "promoted_tag_evidence"
                    if bridge_matches
                    else "governed_rule_observation"
                ),
                source_stratum=source_stratum,
                snapshot_id=snapshot_id,
            )
        )
    assignments.sort(key=lambda row: (row.voc_id, row.cohort_id))
    return tuple(assignments)
