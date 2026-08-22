import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.build_reddit_tag_repair_snapshot import build, write_snapshot
from scripts.validate_reddit_tag_repair_snapshot import validate


ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT = ROOT / "data/processed/reddit_voc_site_snapshot_20260714"
POLICY = ROOT / "config/tagging/reddit-semantic-predicates-v2.json"
LEGACY_SAMPLE = ROOT / "docs/analysis/reddit-tag-semantic-audit-20260714/review-sample.json"
LEGACY_DECISIONS = ROOT / "docs/analysis/reddit-tag-semantic-audit-20260714/review-decisions.json"
PRIOR_REPAIR = ROOT / "data/processed/reddit_voc_tag_repair_20260714"
DEVELOPMENT_EVIDENCE = (
    ROOT / "docs/analysis/reddit-tag-repair-v2-20260714/development-evidence.json"
)
REVIEW_DECISIONS = (
    ROOT / "docs/analysis/reddit-tag-repair-v2-20260714/review-decisions.json"
)


def _build_pending():
    return build(
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        review_decisions_path=None,
        prior_repair_dir=PRIOR_REPAIR,
        development_evidence_path=DEVELOPMENT_EVIDENCE,
    )


def _ids(path: Path, collection: str) -> set[str]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    field = "samples" if collection == "review" else "cases"
    return {
        row["audit_id"]
        for tag in artifact["tags"]
        for row in tag[field]
    }


def test_v2_review_sample_excludes_every_development_evidence_set(
    tmp_path: Path,
) -> None:
    artifacts = _build_pending()
    manifest = artifacts["manifest"]
    sample = artifacts["review-sample"]
    selected = {
        row["audit_id"] for tag in sample["tags"] for row in tag["samples"]
    }

    legacy = _ids(LEGACY_SAMPLE, "review")
    prior_review = _ids(PRIOR_REPAIR / "review-sample.json", "review")
    prior_challenges = _ids(PRIOR_REPAIR / "challenge-cases.json", "challenge")
    prior_assignments = json.loads(
        (PRIOR_REPAIR / "assignments.json").read_text(encoding="utf-8")
    )["assignments"]
    prior_needs_review = {
        row["audit_id"]
        for row in prior_assignments
        if row["predicate_status"] == "needs_review"
    }

    assert selected.isdisjoint(legacy)
    assert selected.isdisjoint(prior_review)
    assert selected.isdisjoint(prior_challenges)
    assert selected.isdisjoint(prior_needs_review)
    assert manifest["dataset_version"] == "reddit_voc_tag_repair_20260714_v2"
    assert manifest["prior_repair_manifest_sha256"] == hashlib.sha256(
        (PRIOR_REPAIR / "manifest.json").read_bytes()
    ).hexdigest()
    assert manifest["development_evidence_sha256"] == hashlib.sha256(
        DEVELOPMENT_EVIDENCE.read_bytes()
    ).hexdigest()
    assert sample["method"]["development_evidence_overlap_allowed"] is False

    output_dir = tmp_path / "repair-v2"
    write_snapshot(output_dir, artifacts)
    receipt = validate(
        output_dir,
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        prior_repair_dir=PRIOR_REPAIR,
        development_evidence_path=DEVELOPMENT_EVIDENCE,
    )
    assert receipt["status"] == "passed_review_pending"
    assert receipt["checks"]["development_evidence_zero_overlap"] is True


def test_v2_builder_rejects_tampered_development_evidence(tmp_path: Path) -> None:
    evidence = json.loads(DEVELOPMENT_EVIDENCE.read_text(encoding="utf-8"))
    evidence["reviewed_assignment_count"] = 91
    tampered = tmp_path / "development-evidence.json"
    tampered.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(ValueError, match="development evidence reviewed count mismatch"):
        build(
            BASE_SNAPSHOT,
            POLICY,
            LEGACY_SAMPLE,
            LEGACY_DECISIONS,
            review_decisions_path=None,
            prior_repair_dir=PRIOR_REPAIR,
            development_evidence_path=tampered,
        )


def test_v2_complete_audit_holds_all_tags_when_no_unseen_positive_remains(
    tmp_path: Path,
) -> None:
    artifacts = build(
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        review_decisions_path=REVIEW_DECISIONS,
        prior_repair_dir=PRIOR_REPAIR,
        development_evidence_path=DEVELOPMENT_EVIDENCE,
    )
    audit = artifacts["semantic-audit"]

    assert audit["review_status"] == "complete"
    assert audit["summary"]["status"] == "completed_no_new_promotions"
    assert audit["summary"]["reviewed_assignments"] == 0
    assert audit["summary"]["promoted_tag_ids"] == []
    assert set(audit["summary"]["held_tag_ids"]) == {
        "L2-PUMP-016",
        "L0-CHL-003",
        "L2-PUMP-030",
        "L2-PUMP-007",
    }
    assert all(
        tag["fresh_confirmed_candidates"] == 0
        and tag["promotion_status"] == "held_after_repair"
        for tag in audit["tags"]
    )

    output_dir = tmp_path / "complete-v2"
    write_snapshot(output_dir, artifacts)
    receipt = validate(
        output_dir,
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        REVIEW_DECISIONS,
        prior_repair_dir=PRIOR_REPAIR,
        development_evidence_path=DEVELOPMENT_EVIDENCE,
    )
    assert receipt["status"] == "passed"
    assert receipt["review_status"] == "complete"
    assert receipt["checks"]["development_evidence_zero_overlap"] is True


def test_v2_pending_output_is_byte_stable_across_hash_seeds(
    tmp_path: Path,
) -> None:
    outputs = []
    for seed in ("11", "29"):
        output_dir = tmp_path / f"seed-{seed}"
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_reddit_tag_repair_snapshot.py"),
                "--snapshot-dir",
                str(BASE_SNAPSHOT),
                "--policy",
                str(POLICY),
                "--legacy-sample",
                str(LEGACY_SAMPLE),
                "--legacy-decisions",
                str(LEGACY_DECISIONS),
                "--prior-repair-dir",
                str(PRIOR_REPAIR),
                "--development-evidence",
                str(DEVELOPMENT_EVIDENCE),
                "--output-dir",
                str(output_dir),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(output_dir)

    manifest = json.loads(
        (outputs[0] / "manifest.json").read_text(encoding="utf-8")
    )
    assert (outputs[0] / "manifest.json").read_bytes() == (
        outputs[1] / "manifest.json"
    ).read_bytes()
    for filename in manifest["files"]:
        assert (outputs[0] / filename).read_bytes() == (
            outputs[1] / filename
        ).read_bytes()
