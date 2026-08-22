from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_casebook import (
    CasebookError,
    build_momcozy_governance_dossier,
    transition_action,
    transition_dossier,
)
from reddit_voc.v3_case_reference_registry import (
    build_case_reference_documents,
    canonical_json_document as reference_json_document,
    load_case_reference_policy,
    load_external_public_capture,
    sha256_bytes as reference_sha256_bytes,
    write_case_reference_registry,
)
from reddit_voc.v3_case_reference_registry_validator import (
    validate_case_reference_registry,
)
from reddit_voc.v3_casebook_snapshot import (
    build_casebook_documents,
    canonical_json_document,
    sha256_bytes,
    write_casebook_snapshot,
)
from reddit_voc.v3_casebook_snapshot_validator import (
    CasebookSnapshotValidationError,
    validate_casebook_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
POLICY = ROOT / "config/cases/reddit-voc-case-reference-policy-v1.json"
CAPTURE = ROOT / "config/cases/reddit-voc-external-reference-1u2gvn4-v1.json"


class CasebookTests(unittest.TestCase):
    def test_first_dossier_keeps_external_root_and_16_comments_evidence_only(self) -> None:
        dossier = build_momcozy_governance_dossier(
            canonical_root_ids=["1kkvihg", "1l2aofi", "1n2q1do", "1o1pqox"],
            external_reference_id="1u2gvn4",
            evidence_only_comment_ids=[f"comment-{index:02d}" for index in range(16)],
            insight_ref="storyline:community-trust",
            snapshot_sha256="a" * 64,
            created_at="2026-07-16T00:00:00+00:00",
            review_due_at="2026-07-30T00:00:00+00:00",
        )
        self.assertEqual(dossier.lifecycle_status, "review_required")
        self.assertEqual(len(dossier.evidence_refs), 20)
        self.assertEqual(dossier.reference_case_ids, ("1u2gvn4",))
        self.assertNotIn("post:1u2gvn4", dossier.evidence_refs)

    def test_dossier_lifecycle_cannot_skip_monitoring_or_reopen_directly(self) -> None:
        self.assertEqual(transition_dossier("observed", "candidate"), "candidate")
        with self.assertRaises(CasebookError):
            transition_dossier("approved", "closed")
        self.assertEqual(transition_dossier("closed", "reopened"), "reopened")
        with self.assertRaises(CasebookError):
            transition_dossier("closed", "review_required")

    def test_action_cannot_complete_without_ledger_provenance(self) -> None:
        action = {"approval_status": "review_due", "action_id": "action-1"}
        with self.assertRaisesRegex(CasebookError, "ledger provenance"):
            transition_action(action, "completed", evidence=None)
        completed = transition_action(
            action,
            "completed",
            evidence={
                "evidence_sha256": "b" * 64,
                "outcome_evidence_refs": ["metric:RV-PS-02"],
                "provenance": "offline_reviewer_ledger",
                "reviewer_role": "Insights Owner",
            },
        )
        self.assertEqual(completed["approval_status"], "completed")

    def test_private_casebook_replays_4_plus_1_plus_16_and_detects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_root = root / "registry"
            policy, policy_sha = load_case_reference_policy(POLICY)
            capture, capture_sha = load_external_public_capture(
                CAPTURE, policy=policy
            )
            reference_documents = build_case_reference_documents(
                captures=[capture],
                capture_sha256s=[capture_sha],
                policy=policy,
                policy_sha256=policy_sha,
                as_of=date(2026, 7, 16),
                registry_id="test-case-reference-registry",
                generated_at="2026-07-16T06:30:00+00:00",
            )
            write_case_reference_registry(registry_root, reference_documents)
            reference_manifest_sha = reference_sha256_bytes(
                (registry_root / "manifest.json").read_bytes()
            )
            reference_receipt = validate_case_reference_registry(
                registry_root=registry_root,
                expected_manifest_sha256=reference_manifest_sha,
                policy_path=POLICY,
                capture_path=CAPTURE,
            )
            reference_receipt_path = root / "reference-receipt.json"
            reference_receipt_path.write_bytes(
                reference_json_document(reference_receipt)
            )
            casebook_root = root / "casebook"
            documents = build_casebook_documents(
                reference_registry_root=registry_root,
                reference_receipt_path=reference_receipt_path,
                facts_root=V3_ROOT / "voc-facts-candidate-a2",
                facts_receipt_path=V3_ROOT
                / "voc-facts-validation-a2/receipt.json",
                governed_root=V3_ROOT / "governed-signals-candidate-a1",
                governed_receipt_path=V3_ROOT
                / "governed-signals-validation-a1/receipt.json",
                casebook_id="test-momcozy-governance-casebook",
                generated_at="2026-07-16T07:00:00+00:00",
            )
            write_casebook_snapshot(casebook_root, documents)
            manifest_sha = sha256_bytes(
                (casebook_root / "manifest.json").read_bytes()
            )
            receipt = validate_casebook_snapshot(
                casebook_root=casebook_root,
                expected_manifest_sha256=manifest_sha,
                reference_registry_root=registry_root,
                reference_receipt_path=reference_receipt_path,
                facts_root=V3_ROOT / "voc-facts-candidate-a2",
                facts_receipt_path=V3_ROOT
                / "voc-facts-validation-a2/receipt.json",
                governed_root=V3_ROOT / "governed-signals-candidate-a1",
                governed_receipt_path=V3_ROOT
                / "governed-signals-validation-a1/receipt.json",
            )
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(
                receipt["evidence_accounting"],
                {
                    "canonical_roots": 4,
                    "evidence_only_comments": 16,
                    "external_references": 1,
                    "unaccounted": 0,
                },
            )
            self.assertEqual(receipt["lifecycle_status"], "review_required")
            self.assertEqual(
                (casebook_root / "action-monitoring-ledger.jsonl").read_bytes(),
                b"",
            )
            facts_path = casebook_root / "external-governance-facts.jsonl"
            rows = [
                json.loads(line)
                for line in facts_path.read_text(encoding="utf-8").splitlines()
            ]
            rows[0]["evidence_start"] += 1
            facts_path.write_bytes(
                b"".join(canonical_json_document(row) for row in rows)
            )
            with self.assertRaises(CasebookSnapshotValidationError):
                validate_casebook_snapshot(
                    casebook_root=casebook_root,
                    expected_manifest_sha256=manifest_sha,
                    reference_registry_root=registry_root,
                    reference_receipt_path=reference_receipt_path,
                    facts_root=V3_ROOT / "voc-facts-candidate-a2",
                    facts_receipt_path=V3_ROOT
                    / "voc-facts-validation-a2/receipt.json",
                    governed_root=V3_ROOT / "governed-signals-candidate-a1",
                    governed_receipt_path=V3_ROOT
                    / "governed-signals-validation-a1/receipt.json",
                )


if __name__ == "__main__":
    unittest.main()
