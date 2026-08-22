from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from typing import Any, Iterable, Mapping, Sequence, cast
from urllib.parse import unquote, urlsplit

from reddit_voc.v3_canonical_identity import (
    CanonicalIdentityError,
    canonical_comment_fullname,
    canonical_comment_id,
    canonical_parent_id,
    canonical_post_fullname,
    canonical_post_id,
)


VOC_SCHEMA_VERSION = "reddit_voc_fielded_voc_v1"
LINKED = "linked"
NON_VOC_COMMENT_STATES = {"quarantined", "unresolved_parent"}
FLOATING_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class VocFactError(ValueError):
    """A canonical entity cannot safely become a fielded VOC."""


class VocEvidenceIdentityConflict(VocFactError):
    """A source link contradicts the separately governed canonical identity."""


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
        raise VocFactError("value is not canonical JSON serializable") from exc


@dataclass(frozen=True)
class VocRecord:
    voc_id: str
    voc_type: str
    canonical_entity_id: str
    post_id: str
    comment_id: str | None
    comment_context_id: str | None
    thread_id: str
    metric_distinct_key: str
    analysis_fields: dict[str, str]
    author: str | None
    author_pseudonym: str | None
    author_scope: str
    evidence_scope: dict[str, list[str]]
    analysis_text_status: str
    context_status: str
    record_authority: str
    anchor_source: str
    source_policy: dict[str, object]
    event_created_at_utc: str | None
    event_time_precision: str | None
    source_calendar_date: str | None
    source_timezone_status: str | None
    schema_version: str = VOC_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "analysis_fields": dict(self.analysis_fields),
            "analysis_text_status": self.analysis_text_status,
            "anchor_source": self.anchor_source,
            "author": self.author,
            "author_pseudonym": self.author_pseudonym,
            "author_scope": self.author_scope,
            "canonical_entity_id": self.canonical_entity_id,
            "comment_context_id": self.comment_context_id,
            "comment_id": self.comment_id,
            "context_status": self.context_status,
            "evidence_scope": {
                key: list(value) for key, value in self.evidence_scope.items()
            },
            "event_created_at_utc": self.event_created_at_utc,
            "event_time_precision": self.event_time_precision,
            "metric_distinct_key": self.metric_distinct_key,
            "post_id": self.post_id,
            "record_authority": self.record_authority,
            "schema_version": self.schema_version,
            "source_calendar_date": self.source_calendar_date,
            "source_policy": dict(self.source_policy),
            "source_timezone_status": self.source_timezone_status,
            "thread_id": self.thread_id,
            "voc_id": self.voc_id,
            "voc_type": self.voc_type,
        }


@dataclass(frozen=True)
class VocExclusion:
    canonical_entity_id: str
    entity_type: str
    post_id: str | None
    comment_id: str | None
    intended_voc_type: str
    reason_codes: tuple[str, ...]
    schema_version: str = "reddit_voc_voc_exclusion_v1"

    def as_dict(self) -> dict[str, object]:
        return {
            "canonical_entity_id": self.canonical_entity_id,
            "comment_id": self.comment_id,
            "entity_type": self.entity_type,
            "intended_voc_type": self.intended_voc_type,
            "post_id": self.post_id,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class VocMaterialization:
    vocs: tuple[VocRecord, ...]
    exclusions: tuple[VocExclusion, ...]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocFactError(f"{label} must be an object")
    return value


def _record(row: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    return _mapping(row.get("record"), f"{label} record")


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise VocFactError(f"{label} must be a string or null")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise VocFactError(f"{label} must be a string")
    return value


def _authors(record: Mapping[str, Any], label: str) -> tuple[str | None, str | None]:
    return (
        _optional_text(record.get("author"), f"{label} author"),
        _optional_text(record.get("author_pseudonym"), f"{label} author pseudonym"),
    )


def _first_text(record: Mapping[str, Any], names: Sequence[str]) -> str:
    for name in names:
        if name in record and record[name] is not None:
            value = record[name]
            if not isinstance(value, str):
                raise VocFactError(f"{name} must be a string")
            return value
    return ""


def _strict_string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise VocFactError(f"{label} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item in result:
            raise VocFactError(f"{label} contains an invalid or duplicate value")
        result.append(item)
    return result


def _identity_candidate(
    record: Mapping[str, Any],
    names: Sequence[str],
    canonicalize: Any,
    expected: str,
    label: str,
) -> None:
    for name in names:
        value = record.get(name)
        if value is None:
            continue
        try:
            observed = canonicalize(value)
        except CanonicalIdentityError as exc:
            raise VocFactError(f"{label} identity is invalid") from exc
        if observed != expected:
            raise VocFactError(f"{label} identity mismatch")


def _url_identity(value: str, *, label: str) -> tuple[str | None, str | None]:
    if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise VocFactError(f"{label} URL is invalid")
    parsed = urlsplit(value)
    reddit_web = False
    reddit_short = False
    if parsed.scheme:
        hostname = parsed.hostname
        try:
            port = parsed.port
        except ValueError as exc:
            raise VocFactError(f"{label} URL is invalid") from exc
        if (
            parsed.scheme.lower() != "https"
            or hostname is None
            or not hostname.isascii()
            or hostname.endswith(".")
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
        ):
            raise VocFactError(f"{label} URL is invalid")
        lowered_hostname = hostname.lower()
        reddit_web = lowered_hostname == "reddit.com" or lowered_hostname.endswith(
            ".reddit.com"
        )
        reddit_short = lowered_hostname == "redd.it"
    elif parsed.netloc or not value.startswith("/"):
        raise VocFactError(f"{label} URL is invalid")
    else:
        reddit_web = True

    decoded_parts: list[str] = []
    parts: list[str] = []
    raw_parts: list[str] = []
    for raw_part in parsed.path.split("/"):
        if not raw_part:
            continue
        if re.search(r"%(?![0-9A-Fa-f]{2})", raw_part):
            raise VocFactError(f"{label} URL path is invalid")
        try:
            decoded = unquote(raw_part, errors="strict")
        except UnicodeDecodeError as exc:
            raise VocFactError(f"{label} URL path is invalid") from exc
        if (
            decoded in {".", ".."}
            or "/" in decoded
            or "\\" in decoded
            or any(ord(character) < 32 or ord(character) == 127 for character in decoded)
        ):
            raise VocFactError(f"{label} URL path is invalid")
        raw_parts.append(raw_part)
        decoded_parts.append(decoded)
        parts.append(decoded.casefold())

    if reddit_short:
        if len(parts) != 1:
            raise VocFactError(f"{label} URL path is invalid")
        if "%" in raw_parts[0]:
            raise VocFactError(f"{label} URL raw identity is percent-encoded")
        try:
            post_id = canonical_post_id(parts[0])
        except CanonicalIdentityError as exc:
            raise VocFactError(f"{label} URL post identity is invalid") from exc
        if decoded_parts[0] != post_id:
            raise VocFactError(f"{label} URL post identity is not canonical lowercase")
        return post_id, None

    if not reddit_web:
        return None, None
    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        marker = 2
    elif len(parts) >= 2 and parts[0] == "comments":
        marker = 0
    elif len(parts) == 2 and parts[0] == "gallery":
        if "%" in raw_parts[1]:
            raise VocFactError(f"{label} URL raw identity is percent-encoded")
        try:
            post_id = canonical_post_id(parts[1])
        except CanonicalIdentityError as exc:
            raise VocFactError(f"{label} URL post identity is invalid") from exc
        if decoded_parts[1] != post_id:
            raise VocFactError(f"{label} URL post identity is not canonical lowercase")
        return post_id, None
    else:
        raise VocFactError(f"{label} URL comments path is missing")
    if any("%" in raw_parts[index] for index in (marker, marker + 1)):
        raise VocFactError(f"{label} URL raw identity is percent-encoded")
    try:
        post_id = canonical_post_id(parts[marker + 1])
    except (CanonicalIdentityError, IndexError) as exc:
        raise VocFactError(f"{label} URL post identity is invalid") from exc
    if decoded_parts[marker + 1] != post_id:
        raise VocFactError(f"{label} URL post identity is not canonical lowercase")
    tail = parts[marker + 2 :]
    comment_id: str | None = None
    if len(tail) > 2:
        raise VocFactError(f"{label} URL comments path is invalid")
    if len(tail) >= 2:
        if "%" in raw_parts[-1]:
            raise VocFactError(f"{label} URL raw identity is percent-encoded")
        try:
            comment_id = canonical_comment_id(tail[-1])
        except CanonicalIdentityError as exc:
            raise VocFactError(f"{label} URL comment identity is invalid") from exc
        if decoded_parts[-1] != comment_id:
            raise VocFactError(
                f"{label} URL comment identity is not canonical lowercase"
            )
    return post_id, comment_id


def _url_candidates(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for name in ("permalink", "source_url"):
        value = record.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise VocFactError(f"{name} must be a non-empty string")
        candidates.append((name, value))
    occurrences = record.get("source_occurrences")
    if occurrences is not None:
        if not isinstance(occurrences, list):
            raise VocFactError("source_occurrences must be an array")
        for ordinal, occurrence in enumerate(occurrences, start=1):
            item = _mapping(occurrence, f"source occurrence {ordinal}")
            value = item.get("source_url")
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise VocFactError("source occurrence URL must be a non-empty string")
            candidates.append((f"source occurrence {ordinal}", value))
    return candidates


def _validate_urls(
    record: Mapping[str, Any],
    *,
    post_id: str,
    comment_id: str | None,
) -> None:
    first_conflict: str | None = None
    for label, value in _url_candidates(record):
        url_post_id, url_comment_id = _url_identity(value, label=label)
        if url_post_id is None:
            if comment_id is not None:
                first_conflict = first_conflict or (
                    f"{label} URL comment identity is missing"
                )
            continue
        if url_post_id != post_id:
            first_conflict = first_conflict or (
                f"{label} URL post identity mismatch"
            )
            continue
        if comment_id is None:
            if url_comment_id is not None:
                first_conflict = first_conflict or (
                    f"{label} URL unexpectedly identifies a comment"
                )
        elif url_comment_id is None:
            first_conflict = first_conflict or (
                f"{label} URL comment identity is missing"
            )
        elif url_comment_id != comment_id:
            first_conflict = first_conflict or (
                f"{label} URL comment identity mismatch"
            )
    if first_conflict is not None:
        raise VocEvidenceIdentityConflict(first_conflict)


def _record_authority(row: Mapping[str, Any]) -> str:
    value = row.get("record_authority")
    if value not in {"governed_base", "workbook_net_new"}:
        raise VocFactError("record authority is missing")
    return str(value)


def _source_metadata(
    row: Mapping[str, Any], record: Mapping[str, Any]
) -> tuple[
    str,
    dict[str, object],
    str | None,
    str | None,
    str | None,
    str | None,
]:
    authority = _record_authority(row)
    snapshot = record.get("source_snapshot_id")
    if snapshot is not None and (not isinstance(snapshot, str) or not snapshot):
        raise VocFactError("source snapshot identity is invalid")
    anchor = snapshot if isinstance(snapshot, str) else authority
    allowed_value = record.get("effective_allowed_metric_families")
    if allowed_value is None:
        allowed_value = record.get("allowed_metric_families")
    allowed = _strict_string_list(allowed_value, "allowed metric families")
    blocked = _strict_string_list(record.get("blocked_uses"), "blocked uses")
    source_policy: dict[str, object] = {
        "allowed_metric_families": allowed if allowed_value is not None else None,
        "blocked_uses": blocked,
        "governed_base_default": authority == "governed_base" and allowed_value is None,
    }
    calendar_date = _optional_text(record.get("source_calendar_date"), "source calendar date")
    precision = _optional_text(record.get("event_time_precision"), "event time precision")
    timezone_status = _optional_text(record.get("source_timezone_status"), "source timezone status")
    created_candidates = [
        value
        for value in (
            _optional_text(record.get("event_created_at_utc"), "event created timestamp"),
            _optional_text(record.get("created_at_utc"), "created timestamp"),
        )
        if value is not None
    ]
    if len(set(created_candidates)) > 1:
        raise VocFactError("event timestamp candidates conflict")
    created = created_candidates[0] if created_candidates else None
    if precision is None:
        if created is not None:
            precision = "instant"
        elif calendar_date is not None:
            precision = "day"
    if precision is None:
        if timezone_status is not None:
            raise VocFactError("timezone status requires an event time")
        return anchor, source_policy, None, None, None, None
    if precision not in {"instant", "hour", "day"}:
        raise VocFactError("event time precision is unsupported")
    if precision == "day":
        if created is not None:
            raise VocFactError("day-precision event may not contain an instant timestamp")
        if (
            calendar_date is None
            or FLOATING_DATE.fullmatch(calendar_date) is None
        ):
            raise VocFactError("day-precision event requires a literal calendar date")
        try:
            date.fromisoformat(calendar_date)
        except ValueError as exc:
            raise VocFactError("day-precision event date is invalid") from exc
        if timezone_status not in {None, "unknown"}:
            raise VocFactError("day-precision event timezone status must be unknown")
        return anchor, source_policy, None, precision, calendar_date, "unknown"
    if created is None:
        raise VocFactError("instant/hour event requires a timestamp")
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VocFactError("event timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VocFactError("instant/hour event timestamp must be timezone-aware")
    if calendar_date is not None:
        raise VocFactError("instant/hour event may not contain a floating calendar date")
    if timezone_status == "unknown":
        raise VocFactError("aware event timestamp cannot have unknown timezone status")
    return (
        anchor,
        source_policy,
        created,
        precision,
        None,
        timezone_status or "known_from_aware_instant",
    )


def _post_identity(
    row: Mapping[str, Any], *, validate_evidence_urls: bool = True
) -> tuple[str, str, Mapping[str, Any]]:
    if row.get("canonical_identity_state") != "canonical_identity":
        raise VocFactError("post is not a canonical identity")
    if row.get("entity_type") != "post":
        raise VocFactError("post entity type is invalid")
    if row.get("schema_version") != "reddit_voc_canonical_post_v1":
        raise VocFactError("post schema is invalid")
    _record_authority(row)
    raw_canonical_id = _required_text(
        row.get("canonical_reddit_id"), "post canonical identity"
    )
    raw_post_id = _required_text(row.get("post_id"), "post identity")
    try:
        canonical_id = canonical_post_fullname(raw_canonical_id)
        post_id = canonical_post_id(raw_post_id)
    except CanonicalIdentityError as exc:
        raise VocFactError("post identity is invalid") from exc
    if (
        raw_canonical_id != canonical_id
        or raw_post_id != post_id
        or canonical_id != f"t3_{post_id}"
    ):
        raise VocFactError("post identity mismatch")
    record = _record(row, "post")
    _identity_candidate(
        record,
        ("post_id", "reddit_id", "canonical_reddit_id"),
        canonical_post_id,
        post_id,
        "post record",
    )
    _identity_candidate(record, ("thread_id",), canonical_post_id, post_id, "post thread")
    if validate_evidence_urls:
        _validate_urls(record, post_id=post_id, comment_id=None)
    return canonical_id, post_id, record


def _comment_identity(
    row: Mapping[str, Any], *, validate_evidence_urls: bool = True
) -> tuple[str, str, str, Mapping[str, Any]]:
    if row.get("canonical_identity_state") != "canonical_identity":
        raise VocFactError("comment is not a canonical identity")
    if row.get("entity_type") != "comment":
        raise VocFactError("comment entity type is invalid")
    if row.get("schema_version") != "reddit_voc_canonical_comment_v1":
        raise VocFactError("comment schema is invalid")
    _record_authority(row)
    raw_canonical_id = _required_text(
        row.get("canonical_reddit_id"), "comment canonical identity"
    )
    raw_post_id = _required_text(
        row.get("post_id"), "comment post identity"
    )
    try:
        canonical_id = canonical_comment_fullname(raw_canonical_id)
        comment_id = canonical_comment_id(raw_canonical_id)
        post_id = canonical_post_id(raw_post_id)
    except CanonicalIdentityError as exc:
        raise VocFactError("comment identity is invalid") from exc
    if raw_canonical_id != canonical_id or raw_post_id != post_id:
        raise VocFactError("comment identity mismatch")
    record = _record(row, "comment")
    _identity_candidate(
        record,
        ("comment_id", "reddit_id", "canonical_reddit_id"),
        canonical_comment_id,
        comment_id,
        "comment record",
    )
    _identity_candidate(record, ("post_id",), canonical_post_id, post_id, "comment root")
    _identity_candidate(record, ("thread_id",), canonical_post_id, post_id, "comment thread")
    if validate_evidence_urls:
        _validate_urls(record, post_id=post_id, comment_id=comment_id)
    return canonical_id, comment_id, post_id, record


def materialize_post_voc(row: Mapping[str, Any]) -> VocRecord:
    canonical_id, post_id, record = _post_identity(_mapping(row, "post"))
    title = _first_text(record, ("title", "source_text"))
    body = _first_text(record, ("content", "selftext", "body"))
    author, author_pseudonym = _authors(record, "post")
    (
        anchor,
        source_policy,
        event_created_at_utc,
        event_time_precision,
        calendar_date,
        timezone_status,
    ) = _source_metadata(
        row, record
    )
    return VocRecord(
        voc_id=f"post:{post_id}",
        voc_type="post_voc",
        canonical_entity_id=canonical_id,
        post_id=post_id,
        comment_id=None,
        comment_context_id=None,
        thread_id=post_id,
        metric_distinct_key=post_id,
        analysis_fields={
            "current_comment_body": "",
            "post_body": body,
            "post_title": title,
        },
        author=author,
        author_pseudonym=author_pseudonym,
        author_scope="post_author_only",
        evidence_scope={
            "brand_category_product_topic_coreference": ["post_title", "post_body"],
            "sentiment_problem_severity_recommendation_persona": ["post_title", "post_body"],
        },
        analysis_text_status="ready" if title.strip() or body.strip() else "incomplete",
        context_status="not_applicable",
        record_authority=_record_authority(row),
        anchor_source=anchor,
        source_policy=source_policy,
        event_created_at_utc=event_created_at_utc,
        event_time_precision=event_time_precision,
        source_calendar_date=calendar_date,
        source_timezone_status=timezone_status,
    )


def materialize_comment_voc(
    parent_post: Mapping[str, Any],
    comment: Mapping[str, Any],
    *,
    validate_evidence_urls: bool = True,
) -> VocRecord:
    _, post_id, parent_record = _post_identity(
        _mapping(parent_post, "parent post"),
        validate_evidence_urls=False,
    )
    canonical_id, comment_id, comment_post_id, record = _comment_identity(
        _mapping(comment, "comment"),
        validate_evidence_urls=validate_evidence_urls,
    )
    if comment.get("comment_state") != LINKED:
        raise VocFactError("only linked comments can form comment-context VOC")
    if comment_post_id != post_id:
        raise VocFactError("comment root post is missing or mismatched")
    raw_parent = record.get("parent_id")
    if raw_parent is not None:
        try:
            parent = canonical_parent_id(raw_parent)
        except CanonicalIdentityError as exc:
            raise VocFactError("comment parent identity is invalid") from exc
        if parent.entity_type == "post" and parent.bare_id != post_id:
            raise VocFactError("comment parent post mismatch")

    post_title = _first_text(parent_record, ("title", "source_text"))
    post_body = _first_text(parent_record, ("content", "selftext", "body"))
    comment_body = _first_text(record, ("body", "source_text", "content"))
    author, author_pseudonym = _authors(record, "comment")
    (
        anchor,
        source_policy,
        event_created_at_utc,
        event_time_precision,
        calendar_date,
        timezone_status,
    ) = _source_metadata(
        comment, record
    )
    return VocRecord(
        voc_id=f"comment:{comment_id}",
        voc_type="comment_context_voc",
        canonical_entity_id=canonical_id,
        post_id=post_id,
        comment_id=comment_id,
        comment_context_id=f"{post_id}:{comment_id}",
        thread_id=post_id,
        metric_distinct_key=comment_id,
        analysis_fields={
            "current_comment_body": comment_body,
            "post_body": post_body,
            "post_title": post_title,
        },
        author=author,
        author_pseudonym=author_pseudonym,
        author_scope="current_comment_author_only",
        evidence_scope={
            "brand_category_product_topic_coreference": [
                "post_title",
                "post_body",
                "current_comment_body",
            ],
            "sentiment_problem_severity_recommendation_persona": [
                "current_comment_body"
            ],
        },
        analysis_text_status="ready" if comment_body.strip() else "incomplete",
        context_status=(
            "ready" if post_title.strip() or post_body.strip() else "incomplete"
        ),
        record_authority=_record_authority(comment),
        anchor_source=anchor,
        source_policy=source_policy,
        event_created_at_utc=event_created_at_utc,
        event_time_precision=event_time_precision,
        source_calendar_date=calendar_date,
        source_timezone_status=timezone_status,
    )


def _coerce_collections(
    posts: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    comments: Iterable[Mapping[str, Any]] | None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    if comments is None and isinstance(posts, Mapping):
        combined = cast(Mapping[str, Any], posts)
        if "posts" in combined:
            post_values: object = combined.get("posts", [])
            comment_values: object = combined.get("comments", [])
        elif "post" in combined:
            post_value = combined.get("post")
            post_values = [] if post_value is None else [post_value]
            comment_values = combined.get("comments", [])
        else:
            raise VocFactError("combined VOC input requires posts and comments")
    else:
        post_values = posts
        comment_values = [] if comments is None else comments
    if isinstance(post_values, (str, bytes, Mapping)) or not isinstance(post_values, Iterable):
        raise VocFactError("posts must be an array")
    if isinstance(comment_values, (str, bytes, Mapping)) or not isinstance(comment_values, Iterable):
        raise VocFactError("comments must be an array")
    return (
        [_mapping(row, "post") for row in post_values],
        [_mapping(row, "comment") for row in comment_values],
    )


def _quarantine_identity(
    row: Mapping[str, Any],
) -> tuple[str, str, str, str | None]:
    if row.get("canonical_identity_state") != "canonical_identity":
        raise VocFactError("quarantined comment is not a canonical identity")
    if row.get("entity_type") != "comment":
        raise VocFactError("quarantined comment entity type is invalid")
    if row.get("schema_version") != "reddit_voc_canonical_quarantine_v1":
        raise VocFactError("quarantined comment schema is invalid")
    if row.get("comment_state") != "quarantined":
        raise VocFactError("quarantined comment state is invalid")
    _record_authority(row)
    raw_canonical_id = _required_text(
        row.get("canonical_reddit_id"),
        "quarantined comment canonical identity",
    )
    try:
        canonical_id = canonical_comment_fullname(raw_canonical_id)
        comment_id = canonical_comment_id(raw_canonical_id)
    except CanonicalIdentityError as exc:
        raise VocFactError("quarantined comment identity is invalid") from exc
    if raw_canonical_id != canonical_id:
        raise VocFactError("quarantined comment identity mismatch")
    record = _record(row, "quarantined comment")
    _identity_candidate(
        record,
        ("comment_id", "reddit_id", "canonical_reddit_id"),
        canonical_comment_id,
        comment_id,
        "quarantined comment record",
    )
    try:
        missing_post = canonical_post_id(
            _required_text(
                record.get("missing_post_id"),
                "quarantined comment root identity",
            )
        )
    except CanonicalIdentityError as exc:
        raise VocFactError("quarantined comment root identity is invalid") from exc
    raw_parent = record.get("parent_id")
    comment_parent_id: str | None = None
    if raw_parent is not None:
        try:
            parent = canonical_parent_id(
                _required_text(raw_parent, "quarantined comment parent identity")
            )
        except CanonicalIdentityError as exc:
            raise VocFactError(
                "quarantined comment parent identity is invalid"
            ) from exc
        if parent.fullname == canonical_id:
            raise VocFactError("quarantined comment parent cycle")
        if parent.entity_type == "post" and parent.bare_id != missing_post:
            raise VocFactError("quarantined comment parent post mismatch")
        if parent.entity_type == "comment":
            comment_parent_id = parent.fullname
    return canonical_id, comment_id, missing_post, comment_parent_id


def materialize_voc_materialization(
    posts: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    comments: Iterable[Mapping[str, Any]] | None = None,
    *,
    quarantine: Iterable[Mapping[str, Any]] = (),
) -> VocMaterialization:
    post_rows, comment_rows = _coerce_collections(posts, comments)
    post_map: dict[str, Mapping[str, Any]] = {}
    post_vocs: list[VocRecord] = []
    exclusions: list[VocExclusion] = []
    for row in post_rows:
        canonical_id, post_id, record = _post_identity(
            row, validate_evidence_urls=False
        )
        if post_id in post_map:
            raise VocFactError("duplicate canonical post identity")
        post_map[post_id] = row
        try:
            _validate_urls(record, post_id=post_id, comment_id=None)
        except VocEvidenceIdentityConflict:
            reasons: list[str] = []
            title = _first_text(record, ("title", "source_text"))
            body = _first_text(record, ("content", "selftext", "body"))
            if not title.strip() and not body.strip():
                reasons.append("analysis_text_incomplete")
            reasons.append("source_url_identity_conflict")
            exclusions.append(
                VocExclusion(
                    canonical_entity_id=canonical_id,
                    entity_type="post",
                    post_id=post_id,
                    comment_id=None,
                    intended_voc_type="post_voc",
                    reason_codes=tuple(reasons),
                )
            )
            continue
        voc = materialize_post_voc(row)
        if voc.analysis_text_status == "ready":
            post_vocs.append(voc)
        else:
            exclusions.append(
                VocExclusion(
                    canonical_entity_id=voc.canonical_entity_id,
                    entity_type="post",
                    post_id=voc.post_id,
                    comment_id=None,
                    intended_voc_type="post_voc",
                    reason_codes=("analysis_text_incomplete",),
                )
            )

    comment_map: dict[str, tuple[Mapping[str, Any], str, Mapping[str, Any]]] = {}
    comment_url_conflicts: set[str] = set()
    for row in comment_rows:
        canonical_id, comment_id, post_id, record = _comment_identity(
            row, validate_evidence_urls=False
        )
        if canonical_id in comment_map:
            raise VocFactError("duplicate canonical comment identity")
        try:
            _validate_urls(record, post_id=post_id, comment_id=comment_id)
        except VocEvidenceIdentityConflict:
            comment_url_conflicts.add(canonical_id)
        comment_map[canonical_id] = (row, post_id, record)

    known_parent_links: dict[str, str] = {}
    for canonical_id, (_, post_id, record) in comment_map.items():
        raw_parent = record.get("parent_id")
        if raw_parent is None:
            continue
        try:
            parent = canonical_parent_id(raw_parent)
        except CanonicalIdentityError as exc:
            raise VocFactError("comment parent identity is invalid") from exc
        if parent.entity_type == "post":
            if parent.bare_id != post_id:
                raise VocFactError("comment parent post mismatch")
        elif parent.entity_type == "comment":
            if (
                parent.fullname in comment_map
                and comment_map[parent.fullname][1] != post_id
            ):
                raise VocFactError("comment nested parent crosses threads")
            known_parent_links[canonical_id] = parent.fullname
        if parent.fullname == canonical_id:
            raise VocFactError("comment parent cycle")

    visit_state: dict[str, int] = {}

    def visit(comment_id: str) -> None:
        state = visit_state.get(comment_id, 0)
        if state == 1:
            raise VocFactError("comment parent cycle")
        if state == 2:
            return
        visit_state[comment_id] = 1
        parent_id = known_parent_links.get(comment_id)
        if parent_id is not None:
            visit(parent_id)
        visit_state[comment_id] = 2

    for canonical_id in comment_map:
        visit(canonical_id)

    comment_vocs: list[VocRecord] = []
    for canonical_id in sorted(comment_map):
        row, post_id, _ = comment_map[canonical_id]
        state = row.get("comment_state")
        if state in NON_VOC_COMMENT_STATES:
            reasons = [state]
            if canonical_id in comment_url_conflicts:
                reasons.append("source_url_identity_conflict")
            exclusions.append(
                VocExclusion(
                    canonical_entity_id=canonical_id,
                    entity_type="comment",
                    post_id=post_id,
                    comment_id=canonical_comment_id(canonical_id),
                    intended_voc_type="comment_context_voc",
                    reason_codes=tuple(reasons),
                )
            )
            continue
        if state != LINKED:
            raise VocFactError("comment state is unsupported")
        parent_post = post_map.get(post_id)
        if parent_post is None:
            raise VocFactError("comment root post is missing")
        voc = materialize_comment_voc(
            parent_post,
            row,
            validate_evidence_urls=False,
        )
        reasons: list[str] = []
        if voc.analysis_text_status != "ready":
            reasons.append("analysis_text_incomplete")
        if voc.context_status != "ready":
            reasons.append("root_post_context_incomplete")
        if canonical_id in comment_url_conflicts:
            reasons.append("source_url_identity_conflict")
        if reasons:
            exclusions.append(
                VocExclusion(
                    canonical_entity_id=voc.canonical_entity_id,
                    entity_type="comment",
                    post_id=voc.post_id,
                    comment_id=voc.comment_id,
                    intended_voc_type="comment_context_voc",
                    reason_codes=tuple(reasons),
                )
            )
        else:
            comment_vocs.append(voc)

    if isinstance(quarantine, (str, bytes, Mapping)) or not isinstance(quarantine, Iterable):
        raise VocFactError("quarantine must be an array")
    known_comment_ids = set(comment_map)
    quarantine_map: dict[str, tuple[str, str, str | None]] = {}
    quarantine_url_conflicts: set[str] = set()
    for raw in quarantine:
        row = _mapping(raw, "quarantined comment")
        canonical_id, comment_id, missing_post_id, parent_id = _quarantine_identity(
            row
        )
        if canonical_id in known_comment_ids:
            raise VocFactError("quarantined comment overlaps canonical comments")
        if missing_post_id in post_map:
            raise VocFactError(
                "quarantined comment missing root unexpectedly exists"
            )
        try:
            _validate_urls(
                _record(row, "quarantined comment"),
                post_id=missing_post_id,
                comment_id=comment_id,
            )
        except VocEvidenceIdentityConflict:
            quarantine_url_conflicts.add(canonical_id)
        known_comment_ids.add(canonical_id)
        quarantine_map[canonical_id] = (comment_id, missing_post_id, parent_id)

    combined_roots = {
        canonical_id: post_id
        for canonical_id, (_, post_id, _) in comment_map.items()
    }
    combined_roots.update(
        {
            canonical_id: missing_post_id
            for canonical_id, (_, missing_post_id, _) in quarantine_map.items()
        }
    )
    combined_parent_links = dict(known_parent_links)
    combined_parent_links.update(
        {
            canonical_id: parent_id
            for canonical_id, (_, _, parent_id) in quarantine_map.items()
            if parent_id is not None
        }
    )
    for child_id, parent_id in combined_parent_links.items():
        if (
            parent_id in combined_roots
            and combined_roots[parent_id] != combined_roots[child_id]
        ):
            raise VocFactError("comment parent crosses canonical root threads")

    combined_visit_state: dict[str, int] = {}

    def visit_combined(comment_id: str) -> None:
        state = combined_visit_state.get(comment_id, 0)
        if state == 1:
            raise VocFactError("comment parent cycle")
        if state == 2:
            return
        combined_visit_state[comment_id] = 1
        parent_id = combined_parent_links.get(comment_id)
        if parent_id in combined_roots:
            visit_combined(parent_id)
        combined_visit_state[comment_id] = 2

    for canonical_id in combined_roots:
        visit_combined(canonical_id)

    for canonical_id in sorted(quarantine_map):
        comment_id, missing_post_id, _ = quarantine_map[canonical_id]
        reasons = ["quarantined"]
        if canonical_id in quarantine_url_conflicts:
            reasons.append("source_url_identity_conflict")
        exclusions.append(
            VocExclusion(
                canonical_entity_id=canonical_id,
                entity_type="comment",
                post_id=missing_post_id,
                comment_id=comment_id,
                intended_voc_type="comment_context_voc",
                reason_codes=tuple(reasons),
            )
        )

    post_vocs.sort(key=lambda row: row.canonical_entity_id)
    comment_vocs.sort(key=lambda row: row.canonical_entity_id)
    result = [*post_vocs, *comment_vocs]
    voc_ids = [row.voc_id for row in result]
    if len(voc_ids) != len(set(voc_ids)):
        raise VocFactError("duplicate VOC identity")
    exclusions.sort(key=lambda row: row.canonical_entity_id)
    exclusion_ids = [row.canonical_entity_id for row in exclusions]
    if len(exclusion_ids) != len(set(exclusion_ids)):
        raise VocFactError("duplicate VOC exclusion identity")
    if {row.canonical_entity_id for row in result} & set(exclusion_ids):
        raise VocFactError("VOC and exclusion identity sets overlap")
    return VocMaterialization(tuple(result), tuple(exclusions))


def materialize_vocs(
    posts: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    comments: Iterable[Mapping[str, Any]] | None = None,
) -> list[VocRecord]:
    return list(materialize_voc_materialization(posts, comments).vocs)
