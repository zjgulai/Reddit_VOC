"""Build and validate the PII-free public projection of the V3 governance casebook."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from reddit_voc.v3_casebook_snapshot import (
    BOUNDARIES,
    CANONICAL_ROOT_IDS,
    EVIDENCE_ONLY_COMMENT_IDS,
    EXTERNAL_REFERENCE_ID,
    OUTPUT_FILES,
    canonical_json_document,
    sha256_bytes,
)


PUBLIC_MANIFEST_SCHEMA = "reddit_voc_governance_casebook_public_manifest_v1"
PUBLIC_CASEBOOK_SCHEMA = "reddit_voc_governance_casebook_public_v1"
PUBLIC_FILES = ("casebook.json",)
NEUTRAL_TITLE = "Momcozy 社区信任与疑似非自然推广治理事件"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PUBLIC_BOUNDARIES = {
    **BOUNDARIES,
    "action_display_mode": "suggestion_only",
    "brand_control_confirmed": False,
    "external_navigation": False,
    "pii_removed": True,
    "robot_attribution_confirmed": False,
}


class CasebookPublicProjectionError(ValueError):
    """The private source or public projection violates the fixed contract."""


def _sha_file(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CasebookPublicProjectionError(f"unreadable file: {path}") from exc


def _read_json(path: Path, label: str, *, canonical: bool = False) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise CasebookPublicProjectionError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CasebookPublicProjectionError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or (canonical and canonical_json_document(value) != payload):
        raise CasebookPublicProjectionError(f"{label} is not canonical JSON")
    return value, payload


def _read_jsonl(path: Path, label: str) -> tuple[dict[str, Any], ...]:
    try:
        if path.is_symlink() or not path.is_file():
            raise CasebookPublicProjectionError(f"{label} must be a regular file")
        payload = path.read_bytes()
    except OSError as exc:
        raise CasebookPublicProjectionError(f"{label} is unreadable") from exc
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CasebookPublicProjectionError(f"{label} row {ordinal} is invalid") from exc
        if not isinstance(row, dict):
            raise CasebookPublicProjectionError(f"{label} row {ordinal} must be an object")
        rows.append(row)
    return tuple(rows)


def _file_contract(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "media_type": "application/json",
        "sha256": sha256_bytes(payload),
    }


def _validate_private_sources(
    *,
    casebook_root: Path,
    expected_casebook_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if SHA256_RE.fullmatch(expected_casebook_manifest_sha256) is None:
        raise CasebookPublicProjectionError("expected casebook manifest SHA-256 is invalid")
    if SHA256_RE.fullmatch(expected_receipt_sha256) is None:
        raise CasebookPublicProjectionError("expected receipt SHA-256 is invalid")
    root = Path(casebook_root)
    expected_entries = {"manifest.json", *OUTPUT_FILES}
    if root.is_symlink() or not root.is_dir() or {entry.name for entry in root.iterdir()} != expected_entries:
        raise CasebookPublicProjectionError("private casebook contains undeclared entries")
    manifest, manifest_payload = _read_json(root / "manifest.json", "private manifest")
    receipt, receipt_payload = _read_json(Path(receipt_path), "private receipt")
    if sha256_bytes(manifest_payload) != expected_casebook_manifest_sha256:
        raise CasebookPublicProjectionError("private manifest SHA-256 mismatch")
    if sha256_bytes(receipt_payload) != expected_receipt_sha256:
        raise CasebookPublicProjectionError("private receipt SHA-256 mismatch")
    if (
        manifest.get("schema_version") != "reddit_voc_governance_casebook_manifest_v1"
        or manifest.get("lifecycle_status") != "review_required"
        or manifest.get("actions_display_mode") != "suggestion_only"
        or manifest.get("counts", {}).get("case_dossiers") != 1
        or manifest.get("counts", {}).get("event_assessments") != 1
        or manifest.get("counts", {}).get("action_monitoring_rows") != 0
        or manifest.get("counts", {}).get("canonical_roots") != 4
        or manifest.get("counts", {}).get("evidence_only_comments") != 16
        or manifest.get("counts", {}).get("external_references") != 1
        or manifest.get("boundaries") != BOUNDARIES
    ):
        raise CasebookPublicProjectionError("private manifest lifecycle or counts are invalid")
    if (
        receipt.get("schema_version") != "reddit_voc_governance_casebook_validation_receipt_v1"
        or receipt.get("status") != "passed"
        or receipt.get("promotable") is not True
        or receipt.get("full_byte_independent_replay") is not True
        or receipt.get("lifecycle_status") != "review_required"
        or receipt.get("casebook_manifest_sha256") != expected_casebook_manifest_sha256
        or receipt.get("boundaries") != BOUNDARIES
    ):
        raise CasebookPublicProjectionError("private validation receipt is ineligible")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != set(OUTPUT_FILES):
        raise CasebookPublicProjectionError("private manifest files contract is invalid")
    for name in OUTPUT_FILES:
        contract = files.get(name)
        path = root / name
        payload = path.read_bytes()
        if (
            not isinstance(contract, Mapping)
            or contract.get("sha256") != sha256_bytes(payload)
            or contract.get("bytes") != len(payload)
            or contract.get("rows") != len(payload.splitlines())
        ):
            raise CasebookPublicProjectionError(f"private {name} file contract mismatch")

    dossiers = _read_jsonl(root / "case-dossiers.jsonl", "private dossiers")
    assessments = _read_jsonl(root / "event-assessments.jsonl", "private assessments")
    ledger = _read_jsonl(root / "action-monitoring-ledger.jsonl", "private action ledger")
    external_facts = _read_jsonl(root / "external-governance-facts.jsonl", "private external facts")
    if len(dossiers) != 1 or len(assessments) != 1 or ledger or len(external_facts) != 3:
        raise CasebookPublicProjectionError("private casebook rows are invalid")
    dossier = dossiers[0]
    assessment = assessments[0]
    if (
        dossier.get("case_id") != assessment.get("case_id")
        or dossier.get("brand_scope") != "momcozy"
        or dossier.get("lifecycle_status") != "review_required"
        or assessment.get("commercial_relation") != "C2"
        or assessment.get("integrity_level") != "I3"
        or assessment.get("brand_control_confirmed") is not False
        or assessment.get("governance_authority") != "subreddit_moderator"
        or assessment.get("assertion_status") != "subreddit_moderator_public_allegation"
        or assessment.get("publication_boundary") != "risk_observation_not_brand_attribution"
        or tuple(assessment.get("canonical_root_ids", ())) != CANONICAL_ROOT_IDS
        or tuple(assessment.get("evidence_only_comment_ids", ())) != EVIDENCE_ONLY_COMMENT_IDS
        or assessment.get("external_reference_id") != EXTERNAL_REFERENCE_ID
    ):
        raise CasebookPublicProjectionError("private case assessment semantics are invalid")
    return manifest, receipt, dossier, assessment


def _public_casebook(
    *,
    projection_id: str,
    manifest: Mapping[str, Any],
    dossier: Mapping[str, Any],
    assessment: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = {
        "canonical_post_ids": [f"t3_{value}" for value in CANONICAL_ROOT_IDS],
        "evidence_comment_ids": [f"t1_{value}" for value in EVIDENCE_ONLY_COMMENT_IDS],
        "external_reference_ids": [f"external_reddit_post:{EXTERNAL_REFERENCE_ID}"],
    }
    stages = [
        {
            "id": "insight",
            "items": ["社区管理员公开指控构成社区信任风险信号", "当前证据只支持风险观察，不支持品牌归因"],
            "label": "洞察",
            "status": "evidence_backed",
            "summary": "识别疑似非自然推广与社区信任受损的治理事件链。",
        },
        {
            "id": "evidence",
            "items": ["4 条规范父帖", "16 条证据评论", "1 条非规范外部公开参考"],
            "label": "证据",
            "status": "review_required",
            "summary": "证据按规范帖子、证据评论和外部参考分层保留。",
        },
        {
            "id": "action",
            "items": ["暂停高风险社区推广动作并复核账号与供应商流程", "建立社区规则、披露义务与人工审批清单"],
            "label": "行动",
            "status": "suggestion_only",
            "summary": "建议方案：行动台账为空，以下内容仅为待审批建议。",
        },
        {
            "id": "monitor",
            "items": ["持续监测管理员处置、账号关联信号与重复文案", "监测社区负面扩散和规则违规复发"],
            "label": "监测",
            "status": "suggestion_only",
            "summary": "建议方案：监测口径尚未写入正式行动台账。",
        },
        {
            "id": "review",
            "items": ["由品牌、合规与社区运营共同完成事实复核", "复盘后再决定是否进入已确认案例库"],
            "label": "复盘",
            "status": "review_required",
            "summary": "当前案例保持待复核，不形成机器人或品牌控制归因。",
        },
    ]
    return {
        "boundaries": dict(PUBLIC_BOUNDARIES),
        "dossiers": [
            {
                "assessment": {
                    "assertion_status": assessment["assertion_status"],
                    "brand_control_confirmed": False,
                    "commercial_relation": "C2",
                    "governance_authority": "subreddit_moderator",
                    "integrity_level": "I3",
                    "publication_boundary": "risk_observation_not_brand_attribution",
                },
                "brand_scope": "Momcozy",
                "business_question": dossier["business_question"],
                "case_id": dossier["case_id"],
                "evidence": evidence,
                "lifecycle_status": "review_required",
                "product_scope": dossier["product_scope"],
                "review_due_at": dossier["review_due_at"],
                "stages": stages,
                "title": NEUTRAL_TITLE,
            }
        ],
        "generated_at": manifest["generated_at"],
        "projection_id": projection_id,
        "schema_version": PUBLIC_CASEBOOK_SCHEMA,
        "source_casebook_id": manifest["casebook_id"],
        "source_snapshot_id": manifest["source_snapshot_id"],
    }


def build_public_projection(
    *,
    casebook_root: Path,
    expected_casebook_manifest_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    output_root: Path,
    projection_id: str,
) -> dict[str, object]:
    if not projection_id.strip():
        raise CasebookPublicProjectionError("projection_id is required")
    manifest, _, dossier, assessment = _validate_private_sources(
        casebook_root=casebook_root,
        expected_casebook_manifest_sha256=expected_casebook_manifest_sha256,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
    )
    casebook = _public_casebook(
        projection_id=projection_id,
        manifest=manifest,
        dossier=dossier,
        assessment=assessment,
    )
    casebook_payload = canonical_json_document(casebook)
    public_manifest = {
        "boundaries": dict(PUBLIC_BOUNDARIES),
        "counts": {
            "canonical_posts": 4,
            "case_dossiers": 1,
            "evidence_comments": 16,
            "external_references": 1,
        },
        "files": {"casebook.json": _file_contract(casebook_payload)},
        "generated_at": manifest["generated_at"],
        "lifecycle_status": "review_required",
        "projection_id": projection_id,
        "schema_version": PUBLIC_MANIFEST_SCHEMA,
        "source_casebook_id": manifest["casebook_id"],
        "source_casebook_manifest_sha256": expected_casebook_manifest_sha256,
        "source_receipt_sha256": expected_receipt_sha256,
        "source_snapshot_id": manifest["source_snapshot_id"],
        "status": "ready",
    }
    manifest_payload = canonical_json_document(public_manifest)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    declared = {"manifest.json", *PUBLIC_FILES}
    extras = {entry.name for entry in output.iterdir()} - declared
    if extras:
        raise CasebookPublicProjectionError("public output contains undeclared entries")
    (output / "casebook.json").write_bytes(casebook_payload)
    (output / "manifest.json").write_bytes(manifest_payload)
    return {
        "casebook_sha256": sha256_bytes(casebook_payload),
        "manifest_sha256": sha256_bytes(manifest_payload),
        "output_root": str(output.resolve()),
        "status": "built",
    }


def validate_public_projection(
    *, public_root: Path, expected_manifest_sha256: str
) -> dict[str, object]:
    if SHA256_RE.fullmatch(expected_manifest_sha256) is None:
        raise CasebookPublicProjectionError("expected public manifest SHA-256 is invalid")
    root = Path(public_root)
    if root.is_symlink() or not root.is_dir() or {entry.name for entry in root.iterdir()} != {"manifest.json", *PUBLIC_FILES}:
        raise CasebookPublicProjectionError("public projection contains undeclared entries")
    manifest, manifest_payload = _read_json(root / "manifest.json", "public manifest", canonical=True)
    casebook, casebook_payload = _read_json(root / "casebook.json", "public casebook", canonical=True)
    contract = manifest.get("files", {}).get("casebook.json")
    if (
        sha256_bytes(manifest_payload) != expected_manifest_sha256
        or manifest.get("schema_version") != PUBLIC_MANIFEST_SCHEMA
        or manifest.get("status") != "ready"
        or manifest.get("lifecycle_status") != "review_required"
        or manifest.get("boundaries") != PUBLIC_BOUNDARIES
        or not isinstance(contract, Mapping)
        or contract != _file_contract(casebook_payload)
        or casebook.get("schema_version") != PUBLIC_CASEBOOK_SCHEMA
        or casebook.get("projection_id") != manifest.get("projection_id")
        or casebook.get("boundaries") != PUBLIC_BOUNDARIES
    ):
        raise CasebookPublicProjectionError("public projection manifest contract mismatch")
    dossiers = casebook.get("dossiers")
    dossier = dossiers[0] if isinstance(dossiers, list) and len(dossiers) == 1 else None
    if not isinstance(dossier, Mapping):
        raise CasebookPublicProjectionError("public dossier count is invalid")
    assessment = dossier.get("assessment")
    evidence = dossier.get("evidence")
    stages = dossier.get("stages")
    if (
        dossier.get("title") != NEUTRAL_TITLE
        or dossier.get("lifecycle_status") != "review_required"
        or not isinstance(assessment, Mapping)
        or assessment.get("commercial_relation") != "C2"
        or assessment.get("integrity_level") != "I3"
        or assessment.get("brand_control_confirmed") is not False
        or not isinstance(evidence, Mapping)
        or evidence.get("canonical_post_ids") != [f"t3_{value}" for value in CANONICAL_ROOT_IDS]
        or evidence.get("evidence_comment_ids") != [f"t1_{value}" for value in EVIDENCE_ONLY_COMMENT_IDS]
        or evidence.get("external_reference_ids") != [f"external_reddit_post:{EXTERNAL_REFERENCE_ID}"]
        or not isinstance(stages, list)
        or [stage.get("label") for stage in stages if isinstance(stage, Mapping)] != ["洞察", "证据", "行动", "监测", "复盘"]
        or not any("建议方案" in str(stage.get("summary", "")) for stage in stages if isinstance(stage, Mapping))
    ):
        raise CasebookPublicProjectionError("public dossier semantics are invalid")
    serialized = casebook_payload.decode("utf-8")
    if "http://" in serialized or "https://" in serialized or '"author"' in serialized or '"username"' in serialized:
        raise CasebookPublicProjectionError("public projection leaks navigation or identity data")
    return {
        "casebook_sha256": sha256_bytes(casebook_payload),
        "manifest_sha256": sha256_bytes(manifest_payload),
        "status": "passed",
    }
