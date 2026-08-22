import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scripts.build_reddit_tag_repair_snapshot as repair_builder
from scripts.build_reddit_tag_repair_snapshot import build, write_snapshot
from scripts.validate_reddit_tag_repair_snapshot import validate


ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT = ROOT / "data/processed/reddit_voc_site_snapshot_20260714"
POLICY = ROOT / "config/tagging/reddit-semantic-predicates-v1.json"
LEGACY_SAMPLE = ROOT / "docs/analysis/reddit-tag-semantic-audit-20260714/review-sample.json"
LEGACY_DECISIONS = ROOT / "docs/analysis/reddit-tag-semantic-audit-20260714/review-decisions.json"
REPAIR_DECISIONS = ROOT / "docs/analysis/reddit-tag-repair-20260714/review-decisions.json"


def _build_fixture():
    return build(
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        review_decisions_path=None,
    )


def test_builds_three_state_repair_review_package(tmp_path: Path) -> None:
    artifacts = _build_fixture()
    assignments = artifacts["assignments"]
    regression = artifacts["regression-audit"]
    sample = artifacts["review-sample"]
    challenges = artifacts["challenge-cases"]

    assert assignments["summary"]["lexical_candidates"] == 243
    assert set(assignments["summary"]["by_status"]) == {
        "confirmed",
        "rejected",
        "needs_review",
    }
    assert sum(assignments["summary"]["by_status"].values()) == 243
    assert regression["summary"]["legacy_held_samples"] == 80
    assert regression["summary"]["in_scope_samples"] == 40

    legacy_ids = {
        row["audit_id"]
        for tag in json.loads(LEGACY_SAMPLE.read_text(encoding="utf-8"))["tags"]
        for row in tag["samples"]
    }
    new_ids = {
        row["audit_id"] for tag in sample["tags"] for row in tag["samples"]
    }
    assert new_ids.isdisjoint(legacy_ids)
    assert all(tag["sample_count"] == len(tag["samples"]) for tag in sample["tags"])
    assert all(tag["challenge_count"] >= 20 for tag in challenges["tags"])

    output_dir = tmp_path / "repair"
    write_snapshot(output_dir, artifacts)
    receipt = validate(output_dir, BASE_SNAPSHOT, POLICY, LEGACY_SAMPLE, LEGACY_DECISIONS)
    assert receipt["status"] == "passed_review_pending"
    assert all(receipt["checks"].values())
    assert receipt["production_unchanged"] is True
    assert receipt["provider_call"] is False
    assert receipt["database_write"] is False


def test_pending_output_is_byte_stable(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_manifest = write_snapshot(first, _build_fixture())
    second_manifest = write_snapshot(second, _build_fixture())

    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    for name in first_manifest["files"]:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_complete_review_is_validated_and_underpowered_tags_remain_held(
    tmp_path: Path,
) -> None:
    artifacts = build(
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        review_decisions_path=REPAIR_DECISIONS,
    )
    audit = artifacts["semantic-audit"]

    assert audit["review_status"] == "complete"
    assert audit["summary"]["status"] == "completed_no_new_promotions"
    assert audit["summary"]["promoted_tag_ids"] == []
    assert set(audit["summary"]["held_tag_ids"]) == {
        "L2-PUMP-016",
        "L0-CHL-003",
        "L2-PUMP-030",
        "L2-PUMP-007",
    }
    assert all(
        tag["promotion_status"] == "held_after_repair" for tag in audit["tags"]
    )

    output_dir = tmp_path / "complete-repair"
    write_snapshot(output_dir, artifacts)
    receipt = validate(
        output_dir,
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        REPAIR_DECISIONS,
    )
    assert receipt["status"] == "passed"
    assert receipt["review_status"] == "complete"


def test_output_is_byte_stable_across_hash_seeds(tmp_path: Path) -> None:
    outputs = []
    for seed in ("1", "2"):
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

    manifest = json.loads((outputs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert (outputs[0] / "manifest.json").read_bytes() == (
        outputs[1] / "manifest.json"
    ).read_bytes()
    for name in manifest["files"]:
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()


def test_validator_rejects_rehashed_assignment_tampering(tmp_path: Path) -> None:
    output_dir = tmp_path / "repair"
    write_snapshot(output_dir, _build_fixture())
    assignments_path = output_dir / "assignments.json"
    assignments = json.loads(assignments_path.read_text(encoding="utf-8"))
    original_status = assignments["assignments"][0]["predicate_status"]
    assignments["assignments"][0]["predicate_status"] = (
        "rejected" if original_status == "confirmed" else "confirmed"
    )
    assignments_path.write_text(
        json.dumps(assignments, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["assignments.json"] = {
        "bytes": assignments_path.stat().st_size,
        "sha256": hashlib.sha256(assignments_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="assignment recomputation mismatch"):
        validate(output_dir, BASE_SNAPSHOT, POLICY, LEGACY_SAMPLE, LEGACY_DECISIONS)


def test_validator_is_independent_from_builder_and_catches_systematic_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validator_source = (
        ROOT / "scripts/validate_reddit_tag_repair_snapshot.py"
    ).read_text(encoding="utf-8")
    assert "build_reddit_tag_repair_snapshot" not in validator_source

    monkeypatch.setattr(
        repair_builder,
        "_stable_rank",
        lambda policy_version, tag_id, entity_type, entity_id: "0" * 64,
    )
    output_dir = tmp_path / "systematically-wrong-repair"
    write_snapshot(output_dir, _build_fixture())

    with pytest.raises(ValueError, match="assignment recomputation mismatch"):
        validate(output_dir, BASE_SNAPSHOT, POLICY, LEGACY_SAMPLE, LEGACY_DECISIONS)


def test_every_reviewed_sample_requires_an_explicit_override_in_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incomplete_decisions = json.loads(REPAIR_DECISIONS.read_text(encoding="utf-8"))
    missing_audit_id = next(
        iter(incomplete_decisions["tag_reviews"]["L2-PUMP-016"]["overrides"])
    )
    del incomplete_decisions["tag_reviews"]["L2-PUMP-016"]["overrides"][
        missing_audit_id
    ]
    incomplete_path = tmp_path / "incomplete-review-decisions.json"
    incomplete_path.write_text(
        json.dumps(
            incomplete_decisions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="repair review decisions missing explicit overrides",
    ):
        repair_builder.build(
            BASE_SNAPSHOT,
            POLICY,
            LEGACY_SAMPLE,
            LEGACY_DECISIONS,
            review_decisions_path=incomplete_path,
        )

    original_semantic_audit = repair_builder._semantic_audit

    def buggy_default_substitution(**kwargs):
        substituted = json.loads(json.dumps(kwargs["review_decisions"]))
        for sampled_tag in kwargs["review_sample"]["tags"]:
            tag_review = substituted["tag_reviews"][sampled_tag["tag_id"]]
            for sample in sampled_tag["samples"]:
                tag_review["overrides"].setdefault(
                    sample["audit_id"], tag_review["default_decision"]
                )
        kwargs["review_decisions"] = substituted
        return original_semantic_audit(**kwargs)

    monkeypatch.setattr(
        repair_builder, "_semantic_audit", buggy_default_substitution
    )
    output_dir = tmp_path / "buggy-default-substitution"
    buggy_artifacts = repair_builder.build(
        BASE_SNAPSHOT,
        POLICY,
        LEGACY_SAMPLE,
        LEGACY_DECISIONS,
        review_decisions_path=incomplete_path,
    )
    write_snapshot(output_dir, buggy_artifacts)

    with pytest.raises(
        ValueError,
        match="repair review decisions missing explicit overrides",
    ):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            POLICY,
            LEGACY_SAMPLE,
            LEGACY_DECISIONS,
            incomplete_path,
        )


def test_validator_cli_runs_without_pythonpath(tmp_path: Path) -> None:
    output_dir = tmp_path / "repair"
    write_snapshot(output_dir, _build_fixture())
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/validate_reddit_tag_repair_snapshot.py"),
            "--repair-dir",
            str(output_dir),
            "--snapshot-dir",
            str(BASE_SNAPSHOT),
            "--policy",
            str(POLICY),
            "--legacy-sample",
            str(LEGACY_SAMPLE),
            "--legacy-decisions",
            str(LEGACY_DECISIONS),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "passed_review_pending"
    assert receipt["checks"]["independent_recomputation"] is True
