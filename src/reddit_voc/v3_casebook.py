"""Verified reference, dossier, and offline action-ledger contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Mapping, Sequence
from urllib.parse import urlsplit


REFERENCE_SOURCE_KINDS = frozenset(
    {"curated_seed", "legacy_unverified", "approved_delta"}
)
VERIFICATION_STATUSES = frozenset({"verified", "pending", "rejected", "stale"})
DEFAULT_SOURCE_KINDS = frozenset({"curated_seed", "approved_delta"})
VERIFICATION_TTL_DAYS = 30
DOSSIER_TRANSITIONS = {
    "observed": frozenset({"candidate"}),
    "candidate": frozenset({"review_required", "rejected"}),
    "review_required": frozenset({"approved", "rejected"}),
    "approved": frozenset({"monitoring"}),
    "monitoring": frozenset({"review_due"}),
    "review_due": frozenset({"closed", "monitoring"}),
    "closed": frozenset({"reopened"}),
    "reopened": frozenset({"review_required"}),
    "rejected": frozenset(),
}
ACTION_TRANSITIONS = {
    "proposed": frozenset({"approved", "rejected"}),
    "approved": frozenset({"monitoring"}),
    "monitoring": frozenset({"review_due"}),
    "review_due": frozenset({"completed", "monitoring"}),
    "completed": frozenset(),
    "rejected": frozenset(),
}
SHA256 = re.compile(r"[0-9a-f]{64}")
CONTENT_HASH = re.compile(r"sha256:[0-9a-f]{64}")
FIXED_CANONICAL_ROOT_IDS = (
    "1kkvihg",
    "1l2aofi",
    "1n2q1do",
    "1o1pqox",
)


class CasebookError(ValueError):
    """A case reference or lifecycle transition is not governed."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise CasebookError(f"{label} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CasebookError(f"{label} is invalid") from exc


def _utc(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CasebookError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CasebookError(f"{label} must be UTC")
    return value


@dataclass(frozen=True)
class CaseReference:
    reference_id: str
    source_kind: str
    verification_status: str
    review_reason: str
    verification_policy_version: str
    default_eligible: bool
    canonical_url: str
    content_hash: str
    last_verified_at: str
    provenance: str

    def as_dict(self) -> dict[str, object]:
        return {
            "canonical_url": self.canonical_url,
            "content_hash": self.content_hash,
            "default_eligible": self.default_eligible,
            "last_verified_at": self.last_verified_at,
            "provenance": self.provenance,
            "reference_id": self.reference_id,
            "review_reason": self.review_reason,
            "source_kind": self.source_kind,
            "verification_policy_version": self.verification_policy_version,
            "verification_status": self.verification_status,
        }


@dataclass(frozen=True)
class CaseReferenceRegistry:
    references: tuple[CaseReference, ...]
    default_eligible_count: int
    content_sha256: str
    policy_version: str = "reddit-voc-case-reference-2026-07-16.v1"


@dataclass(frozen=True)
class CaseDossier:
    case_id: str
    case_identity_key: str
    case_version: int
    business_question: str
    lifecycle_status: str
    brand_scope: str
    product_scope: str
    event_or_risk_theme_id: str
    period_policy: str
    insight_ref: str
    snapshot_sha256: str
    evidence_refs: tuple[str, ...]
    reference_case_ids: tuple[str, ...]
    created_at: str
    review_due_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "brand_scope": self.brand_scope,
            "business_question": self.business_question,
            "case_id": self.case_id,
            "case_identity_key": self.case_identity_key,
            "case_version": self.case_version,
            "created_at": self.created_at,
            "event_or_risk_theme_id": self.event_or_risk_theme_id,
            "evidence_refs": list(self.evidence_refs),
            "insight_ref": self.insight_ref,
            "lifecycle_status": self.lifecycle_status,
            "period_policy": self.period_policy,
            "product_scope": self.product_scope,
            "reference_case_ids": list(self.reference_case_ids),
            "review_due_at": self.review_due_at,
            "snapshot_sha256": self.snapshot_sha256,
        }


def build_reference_registry(
    rows: Sequence[Mapping[str, object]], *, as_of: date
) -> CaseReferenceRegistry:
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise CasebookError("case reference as-of date is invalid")
    references: list[CaseReference] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise CasebookError("case reference row is invalid")
        reference_id = row.get("reference_id")
        source_kind = row.get("source_kind")
        status = row.get("verification_status")
        canonical_url = row.get("canonical_url")
        content_hash = row.get("content_hash")
        review_reason = row.get("review_reason")
        provenance = row.get("provenance")
        if (
            not isinstance(reference_id, str)
            or not reference_id
            or source_kind not in REFERENCE_SOURCE_KINDS
            or status not in VERIFICATION_STATUSES
            or not isinstance(canonical_url, str)
            or not canonical_url
            or not isinstance(content_hash, str)
            or CONTENT_HASH.fullmatch(content_hash) is None
            or not isinstance(review_reason, str)
            or not review_reason
            or not isinstance(provenance, str)
            or not provenance
        ):
            raise CasebookError("case reference contract is invalid")
        verified_on = _date(row.get("last_verified_at"), "last verified date")
        parts = urlsplit(canonical_url)
        http_status = row.get("http_status")
        redirects = row.get("redirect_count")
        theme_match = row.get("theme_match")
        if (
            type(http_status) is not int
            or type(redirects) is not int
            or redirects < 0
            or type(theme_match) is not bool
        ):
            raise CasebookError("case reference verification evidence is invalid")
        if status == "verified" and parts.scheme != "https":
            raise CasebookError("verified case reference must use HTTPS")
        if status == "verified" and (
            not 200 <= http_status < 300 or redirects > 5 or not theme_match
        ):
            raise CasebookError("verified case reference lacks verification evidence")
        if reference_id.casefold() in seen_ids or canonical_url.casefold() in seen_urls or content_hash in seen_hashes:
            raise CasebookError("case reference three-key duplicate")
        seen_ids.add(reference_id.casefold())
        seen_urls.add(canonical_url.casefold())
        seen_hashes.add(content_hash)

        age_days = (as_of - verified_on).days
        if age_days < 0:
            raise CasebookError("case reference verification date is in the future")
        effective_status = "stale" if status == "verified" and age_days > VERIFICATION_TTL_DAYS else status
        effective_reason = "verification_ttl_expired" if effective_status == "stale" and status == "verified" else review_reason
        default_eligible = (
            effective_status == "verified"
            and source_kind in DEFAULT_SOURCE_KINDS
            and age_days <= VERIFICATION_TTL_DAYS
            and parts.scheme == "https"
            and 200 <= http_status < 300
            and redirects <= 5
            and theme_match
        )
        references.append(
            CaseReference(
                reference_id=reference_id,
                source_kind=str(source_kind),
                verification_status=str(effective_status),
                review_reason=str(effective_reason),
                verification_policy_version="reddit-voc-case-reference-2026-07-16.v1",
                default_eligible=default_eligible,
                canonical_url=canonical_url,
                content_hash=content_hash,
                last_verified_at=verified_on.isoformat(),
                provenance=provenance,
            )
        )
    payload = [row.as_dict() for row in references]
    return CaseReferenceRegistry(
        references=tuple(references),
        default_eligible_count=sum(row.default_eligible for row in references),
        content_sha256=sha256(_canonical(payload)).hexdigest(),
    )


def build_momcozy_governance_dossier(
    *,
    canonical_root_ids: Sequence[str],
    external_reference_id: str,
    evidence_only_comment_ids: Sequence[str],
    insight_ref: str,
    snapshot_sha256: str,
    created_at: str,
    review_due_at: str,
) -> CaseDossier:
    if tuple(canonical_root_ids) != FIXED_CANONICAL_ROOT_IDS:
        raise CasebookError("canonical Momcozy governance roots are invalid")
    if external_reference_id != "1u2gvn4":
        raise CasebookError("external Momcozy governance reference is invalid")
    if (
        len(evidence_only_comment_ids) != 16
        or len(set(evidence_only_comment_ids)) != 16
        or any(not isinstance(value, str) or not value for value in evidence_only_comment_ids)
    ):
        raise CasebookError("evidence-only Momcozy comments are invalid")
    if not isinstance(insight_ref, str) or not insight_ref:
        raise CasebookError("case insight reference is invalid")
    if SHA256.fullmatch(snapshot_sha256) is None:
        raise CasebookError("case snapshot SHA is invalid")
    created_at = _utc(created_at, "case creation time")
    review_due_at = _utc(review_due_at, "case review time")
    if datetime.fromisoformat(review_due_at) <= datetime.fromisoformat(created_at):
        raise CasebookError("case review time must follow creation")
    identity_dimensions = {
        "brand_scope": "momcozy",
        "event_or_risk_theme_id": "community_trust_non_organic_promotion",
        "period_policy": "event_chain_2025_05_to_2026_06",
        "product_scope": "all_momcozy",
    }
    case_identity_key = sha256(_canonical(identity_dimensions)).hexdigest()
    evidence_refs = tuple(
        [*(f"post:{post_id}" for post_id in FIXED_CANONICAL_ROOT_IDS)]
        + [f"comment:{comment_id}" for comment_id in evidence_only_comment_ids]
    )
    case_id = sha256(
        _canonical({"case_identity_key": case_identity_key, "case_version": 1})
    ).hexdigest()
    return CaseDossier(
        case_id=case_id,
        case_identity_key=case_identity_key,
        case_version=1,
        business_question="如何修复 Momcozy 在 Reddit 社区中的信任风险并防止不规范推广？",
        lifecycle_status="review_required",
        brand_scope="momcozy",
        product_scope="all_momcozy",
        event_or_risk_theme_id="community_trust_non_organic_promotion",
        period_policy="event_chain_2025_05_to_2026_06",
        insight_ref=insight_ref,
        snapshot_sha256=snapshot_sha256,
        evidence_refs=evidence_refs,
        reference_case_ids=(external_reference_id,),
        created_at=created_at,
        review_due_at=review_due_at,
    )


def transition_dossier(current: str, target: str) -> str:
    if current not in DOSSIER_TRANSITIONS or target not in DOSSIER_TRANSITIONS:
        raise CasebookError("case dossier lifecycle state is invalid")
    if target not in DOSSIER_TRANSITIONS[current]:
        raise CasebookError("case dossier lifecycle transition is invalid")
    return target


def transition_action(
    action: Mapping[str, object],
    target: str,
    *,
    evidence: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(action, Mapping):
        raise CasebookError("action ledger input is invalid")
    current = action.get("approval_status")
    action_id = action.get("action_id")
    if current not in ACTION_TRANSITIONS or not isinstance(action_id, str) or not action_id:
        raise CasebookError("action ledger state is invalid")
    if target not in ACTION_TRANSITIONS or target not in ACTION_TRANSITIONS[current]:
        raise CasebookError("action ledger transition is invalid")
    result = dict(action)
    if target == "completed":
        required = {
            "evidence_sha256",
            "outcome_evidence_refs",
            "provenance",
            "reviewer_role",
        }
        if not isinstance(evidence, Mapping) or not required <= set(evidence):
            raise CasebookError("action completion requires ledger provenance")
        refs = evidence.get("outcome_evidence_refs")
        if (
            SHA256.fullmatch(str(evidence.get("evidence_sha256"))) is None
            or not isinstance(refs, list)
            or not refs
            or any(not isinstance(value, str) or not value for value in refs)
            or not isinstance(evidence.get("provenance"), str)
            or not evidence.get("provenance")
            or not isinstance(evidence.get("reviewer_role"), str)
            or not evidence.get("reviewer_role")
        ):
            raise CasebookError("action completion requires ledger provenance")
        result["completion_evidence"] = dict(evidence)
    result["approval_status"] = target
    return result
