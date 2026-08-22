from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Mapping


BASE36_ID = re.compile(r"^[a-z0-9]+$")


class CanonicalIdentityError(ValueError):
    """A Reddit identity is missing, malformed, or internally inconsistent."""


class CommentState(StrEnum):
    LINKED = "linked"
    UNRESOLVED_PARENT = "unresolved_parent"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class CanonicalParent:
    entity_type: str
    bare_id: str
    fullname: str


def _canonical_bare_id(value: str, *, prefix: str, label: str) -> str:
    if not isinstance(value, str):
        raise CanonicalIdentityError(f"{label} identity must be a string")
    raw = value.strip()
    if not raw.isascii():
        raise CanonicalIdentityError(f"invalid {label} identity")
    text = raw.lower()
    if text.startswith(prefix):
        text = text[len(prefix) :]
    elif text.startswith(("t1_", "t3_")):
        raise CanonicalIdentityError(f"{label} identity namespace mismatch")
    if BASE36_ID.fullmatch(text) is None:
        raise CanonicalIdentityError(f"invalid {label} identity")
    return text


def canonical_post_id(value: str) -> str:
    return _canonical_bare_id(value, prefix="t3_", label="post")


def canonical_comment_id(value: str) -> str:
    return _canonical_bare_id(value, prefix="t1_", label="comment")


def canonical_post_fullname(value: str) -> str:
    return f"t3_{canonical_post_id(value)}"


def canonical_comment_fullname(value: str) -> str:
    return f"t1_{canonical_comment_id(value)}"


def canonical_entity_id(entity_type: str, value: str) -> str:
    if not isinstance(entity_type, str):
        raise CanonicalIdentityError("entity type must be a string")
    normalized_type = entity_type.strip()
    if not normalized_type.isascii():
        raise CanonicalIdentityError("unsupported entity type")
    normalized_type = normalized_type.lower()
    if normalized_type == "post":
        return canonical_post_fullname(value)
    if normalized_type == "comment":
        return canonical_comment_fullname(value)
    raise CanonicalIdentityError("unsupported entity type")


def canonical_parent_id(value: str) -> CanonicalParent:
    if not isinstance(value, str):
        raise CanonicalIdentityError("parent identity must be a string")
    raw = value.strip()
    if not raw.isascii():
        raise CanonicalIdentityError("invalid parent identity")
    text = raw.lower()
    if text.startswith("t3_"):
        bare_id = canonical_post_id(text)
        return CanonicalParent("post", bare_id, f"t3_{bare_id}")
    if text.startswith("t1_"):
        bare_id = canonical_comment_id(text)
        return CanonicalParent("comment", bare_id, f"t1_{bare_id}")
    raise CanonicalIdentityError("parent identity requires t3_ or t1_ fullname")


def assert_comment_root_consistency(
    post_id: str,
    parent_id: str,
    *,
    comment_id: str | None = None,
    comment_post_ids: Mapping[str, str] | None = None,
    comment_parent_ids: Mapping[str, str] | None = None,
) -> CanonicalParent:
    canonical_root = canonical_post_id(post_id)
    immediate_parent = canonical_parent_id(parent_id)
    if immediate_parent.entity_type == "post":
        if immediate_parent.bare_id != canonical_root:
            raise CanonicalIdentityError("root parent mismatch")
        return immediate_parent

    if (
        comment_id is None
        or comment_post_ids is None
        or comment_parent_ids is None
    ):
        raise CanonicalIdentityError("nested parent context required")

    current_comment = canonical_comment_id(comment_id)
    visited = {current_comment}
    parent = immediate_parent
    while parent.entity_type == "comment":
        parent_comment = parent.bare_id
        if parent_comment in visited:
            raise CanonicalIdentityError("comment parent cycle")
        visited.add(parent_comment)

        declared_post = _comment_mapping_value(
            comment_post_ids,
            parent_comment,
            label="nested parent post",
        )
        if canonical_post_id(declared_post) != canonical_root:
            raise CanonicalIdentityError("nested parent cross-thread mismatch")
        parent_pointer = _comment_mapping_value(
            comment_parent_ids,
            parent_comment,
            label="nested parent link",
        )
        parent = canonical_parent_id(parent_pointer)

    if parent.bare_id != canonical_root:
        raise CanonicalIdentityError("root parent mismatch")
    return immediate_parent


def _comment_mapping_value(
    mapping: Mapping[str, str],
    bare_comment_id: str,
    *,
    label: str,
) -> str:
    fullname = f"t1_{bare_comment_id}"
    values = [mapping[key] for key in (bare_comment_id, fullname) if key in mapping]
    if not values:
        raise CanonicalIdentityError(f"{label} missing")
    if len(set(values)) != 1:
        raise CanonicalIdentityError(f"{label} conflict")
    value = values[0]
    if not isinstance(value, str):
        raise CanonicalIdentityError(f"{label} must be a string")
    return value
