from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_semantic_compatibility import (
    SemanticCompatibilityError,
    build_projection,
    write_projection,
)
from scripts.build_reddit_site_insights import (
    InputContractError,
    normalise_semantic_governance,
    resolve_legacy_compatibility,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _contract(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}


class SemanticCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "base"
        self.audit = self.root / "semantic-audit.json"
        self.ledger = self.root / "candidate-ledger-manifest.json"
        self.receipt = self.root / "candidate-ledger-validation-receipt.json"
        self._write_base()
        self._write_audit()
        self._write_identity_gate()

    @staticmethod
    def _rule(tag_id: str, card: str) -> dict[str, object]:
        return {
            "tag_id": tag_id,
            "name_cn": tag_id,
            "name_en": tag_id,
            "theme": "theme",
            "consumer_card": card,
            "aipl_node": "L1",
            "story_lines": "story",
            "intent_type": "intent",
            "problem_type": "problem",
        }

    @staticmethod
    def _tagging(*tag_ids: str) -> dict[str, object]:
        return {
            "matches": [
                {"tag_id": tag_id, "evidence_keywords": [f"kw-{tag_id}"]}
                for tag_id in tag_ids
            ]
        }

    def _write_base(self) -> None:
        posts = [
            {"post_id": "p1", "tagging": self._tagging("promoted")},
            {"post_id": "p2", "tagging": self._tagging("held")},
        ]
        comments = [
            {
                "comment_id": "c1",
                "post_id": "p1",
                "include_in_voc_metrics": True,
                "tagging": self._tagging("promoted", "held"),
            },
            {
                "comment_id": "c2",
                "post_id": "p2",
                "include_in_voc_metrics": False,
                "tagging": self._tagging("promoted"),
            },
        ]
        dictionary = {
            "dictionary_version": "dictionary-v1",
            "dictionary_sha256": "d" * 64,
            "rules": [self._rule("promoted", "card-a"), self._rule("held", "card-b")],
        }
        for name, value in (
            ("posts.json", posts),
            ("comments.json", comments),
            ("tag-dictionary.json", dictionary),
        ):
            _write(self.base / name, value)
        manifest = {
            "schema_version": "reddit_voc_site_snapshot_manifest_v2",
            "dataset_version": "reddit_voc_site_snapshot_fixture_a2",
            "all_checks_passed": True,
            "files": {
                name: _contract(self.base / name)
                for name in ("posts.json", "comments.json", "tag-dictionary.json")
            },
        }
        _write(self.base / "manifest.json", manifest)

    @staticmethod
    def _sample(tag_id: str, entity_type: str, entity_id: str) -> dict[str, object]:
        return {
            "audit_id": f"{tag_id}:{entity_type}:{entity_id}",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "reddit_id": entity_id,
            "post_id": "p1",
            "subreddit": "fixture",
            "created_at_utc": "2026-07-01T00:00:00Z",
            "evidence_keywords": [f"kw-{tag_id}"],
            "context_excerpt": "reviewed context",
            "review": {
                "label_verdict": "correct",
                "taxonomy_fit": "fit",
                "reason_code": "reviewed",
            },
        }

    def _tag(self, tag_id: str, disposition: str, samples: list[dict[str, object]]) -> dict[str, object]:
        return {
            "tag_id": tag_id,
            "name_cn": tag_id,
            "name_en": tag_id,
            "theme": "theme",
            "promotion_status": disposition,
            "dictionary_reference": {
                "consumer_card": "card-a" if tag_id == "promoted" else "card-b",
                "aipl_node": "L1",
                "story_lines": "story",
                "intent_type": "intent",
                "problem_type": "problem",
            },
            "review_metrics": {"reviewed": len(samples), "label_precision": 1.0},
            "gate_checks": {"sample_count": disposition == "promoted"},
            "governance_review": {"status": "fit" if disposition == "promoted" else "held"},
            "samples": samples,
        }

    def _write_audit(self) -> None:
        promoted_samples = [self._sample("promoted", "post", "p1")]
        held_samples = [
            self._sample("held", "post", "p2"),
            self._sample("held", "comment", "missing-held-comment"),
        ]
        _write(
            self.audit,
            {
                "schema_version": "reddit_voc_tag_semantic_audit_v1",
                "audit_version": "source-audit-v1",
                "base_dataset_version": "old-base",
                "base_manifest_sha256": "a" * 64,
                "dictionary_version": "dictionary-v1",
                "dictionary_sha256": "d" * 64,
                "sample_sha256": "s" * 64,
                "quality_gate": {"required_samples_per_tag": 1},
                "summary": {
                    "audited_tags": 2,
                    "reviewed_assignments": 3,
                    "promoted_tags": 1,
                    "held_tags": 1,
                    "promoted_tag_ids": ["promoted"],
                    "held_tag_ids": ["held"],
                },
                "tags": [
                    self._tag("promoted", "promoted", promoted_samples),
                    self._tag("held", "held", held_samples),
                ],
            },
        )

    def _write_identity_gate(self) -> None:
        base_sha = sha256((self.base / "manifest.json").read_bytes()).hexdigest()
        _write(
            self.ledger,
            {
                "schema_version": "reddit_voc_candidate_ledger_manifest_v2",
                "status": "a2_identity_closed_with_explicit_coverage_debt",
                "inputs": {"candidate_base_manifest_sha256": base_sha},
                "accounting": {"unaccounted_total": 0},
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "remote_write": False,
                "deployment": False,
                "production_merge": False,
                "live_send": False,
            },
        )
        _write(
            self.receipt,
            {
                "schema_version": "reddit_voc_candidate_ledger_validation_receipt_v1",
                "status": "passed",
                "candidate_ledger_manifest_sha256": sha256(self.ledger.read_bytes()).hexdigest(),
                "input_evidence_sha256": "e" * 64,
                "counts": {"unaccounted_total": 0},
                "production_unchanged": True,
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "remote_write": False,
                "deployment": False,
                "production_merge": False,
                "live_send": False,
            },
        )

    def _build(self) -> dict[str, object]:
        return build_projection(
            base_dir=self.base,
            source_audit_path=self.audit,
            expected_source_audit_sha256=sha256(self.audit.read_bytes()).hexdigest(),
            candidate_ledger_manifest_path=self.ledger,
            ledger_validation_receipt_path=self.receipt,
            expected_ledger_validation_receipt_sha256=sha256(self.receipt.read_bytes()).hexdigest(),
        )

    def test_recomputes_current_base_ui_fields_and_keeps_source_review_separate(self) -> None:
        projection = self._build()
        headline = projection["legacy_insights"]["headline"]
        self.assertIsNone(headline["reviewed_assignments"])
        self.assertEqual(headline["source_reviewed_assignments"], 3)
        self.assertEqual(headline["compatible_source_assignments"], 2)
        self.assertEqual(headline["promoted_rule_assignments"], 2)
        self.assertEqual(headline["unique_posts_with_promoted_tags"], 1)
        self.assertEqual(headline["unique_comments_with_promoted_tags"], 1)
        self.assertEqual(projection["compatibility_summary"]["promoted_compatible_assignments"], 1)
        self.assertTrue(projection["compatibility_summary"]["promoted_retention_gate_passed"])
        self.assertEqual(projection["projection_mode"], "governance_projection_no_new_review")

    def test_allows_missing_held_assignment_but_keeps_held(self) -> None:
        projection = self._build()
        summary = projection["compatibility_summary"]
        self.assertEqual(summary["incompatible_or_absent_source_assignments"], 1)
        self.assertEqual(projection["held_tag_ids"], ["held"])
        held = projection["legacy_insights"]["held_tags"][0]
        self.assertEqual(held["matched_entities"], 2)

    def test_rejects_missing_promoted_assignment(self) -> None:
        audit = json.loads(self.audit.read_text(encoding="utf-8"))
        audit["tags"][0]["samples"][0]["entity_id"] = "missing"
        _write(self.audit, audit)
        with self.assertRaisesRegex(
            SemanticCompatibilityError, "promoted_review_assignment_incompatible"
        ):
            self._build()

    def test_rejects_wrong_explicit_receipt_sha(self) -> None:
        with self.assertRaisesRegex(
            SemanticCompatibilityError, "ledger_validation_receipt_sha256_mismatch"
        ):
            build_projection(
                base_dir=self.base,
                source_audit_path=self.audit,
                expected_source_audit_sha256=sha256(self.audit.read_bytes()).hexdigest(),
                candidate_ledger_manifest_path=self.ledger,
                ledger_validation_receipt_path=self.receipt,
                expected_ledger_validation_receipt_sha256="0" * 64,
            )

    def test_rejects_dictionary_drift(self) -> None:
        audit = json.loads(self.audit.read_text(encoding="utf-8"))
        audit["dictionary_sha256"] = "0" * 64
        _write(self.audit, audit)
        with self.assertRaisesRegex(SemanticCompatibilityError, "dictionary_lineage_mismatch"):
            self._build()

    def test_writer_is_immutable_and_private(self) -> None:
        projection = self._build()
        output = self.root / "private" / "semantic-governance.json"
        first = write_projection(output, projection)
        second = write_projection(output, projection)
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(SemanticCompatibilityError, "output_collision"):
            write_projection(output, {**projection, "projection_mode": "tampered"})

    def test_site_builder_accepts_only_embedded_base_bound_legacy_projection(self) -> None:
        projection = self._build()
        normalised = normalise_semantic_governance(
            projection,
            source_sha256="f" * 64,
            source_name="semantic-governance.json",
        )
        base_manifest_path = self.base / "manifest.json"
        base_identity = {
            "dataset_version": "reddit_voc_site_snapshot_fixture_a2",
            "manifest_sha256": sha256(base_manifest_path.read_bytes()).hexdigest(),
        }
        dictionary = json.loads((self.base / "tag-dictionary.json").read_text())
        legacy = resolve_legacy_compatibility(
            normalised,
            base_identity=base_identity,
            tag_dictionary=dictionary,
            explicit_legacy_insights=None,
        )
        self.assertEqual(
            legacy["compatibility_contract"]["status"],
            "current_base_recomputed_governance_projection",
        )
        with self.assertRaisesRegex(InputContractError, "semantic compatibility"):
            resolve_legacy_compatibility(
                normalised,
                base_identity=base_identity,
                tag_dictionary=dictionary,
                explicit_legacy_insights={"headline": {}},
            )


if __name__ == "__main__":
    unittest.main()
