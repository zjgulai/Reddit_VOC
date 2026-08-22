from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_casebook import CasebookError, build_reference_registry
from reddit_voc.v3_case_reference_registry import (
    build_case_reference_documents,
    canonical_json_document,
    load_case_reference_policy,
    load_external_public_capture,
    sha256_bytes,
    write_case_reference_registry,
)
from reddit_voc.v3_case_reference_registry_validator import (
    CaseReferenceRegistryValidationError,
    validate_case_reference_registry,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/cases/reddit-voc-case-reference-policy-v1.json"
CAPTURE = ROOT / "config/cases/reddit-voc-external-reference-1u2gvn4-v1.json"


def _reference(reference_id: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "canonical_url": f"https://example.com/{reference_id}",
        "content_hash": f"sha256:{reference_id[0] * 64}",
        "http_status": 200,
        "last_verified_at": "2026-07-15",
        "provenance": "manual_url_verification",
        "redirect_count": 0,
        "reference_id": reference_id,
        "review_reason": "verified_topic_match",
        "source_kind": "curated_seed",
        "theme_match": True,
        "verification_status": "verified",
    }
    value.update(changes)
    return value


class CaseReferenceRegistryTests(unittest.TestCase):
    def test_verified_recent_seed_and_delta_are_default_eligible(self) -> None:
        result = build_reference_registry(
            [
                _reference("a-seed"),
                _reference("b-delta", source_kind="approved_delta"),
            ],
            as_of=date(2026, 7, 16),
        )
        self.assertEqual(result.default_eligible_count, 2)
        self.assertTrue(all(row.default_eligible for row in result.references))

    def test_legacy_stale_failed_and_apple_500_are_retained_but_not_default(self) -> None:
        result = build_reference_registry(
            [
                _reference("a-legacy", source_kind="legacy_unverified"),
                _reference("b-old", last_verified_at="2026-05-01"),
                _reference("c-apple", http_status=500, verification_status="pending"),
            ],
            as_of=date(2026, 7, 16),
        )
        self.assertEqual(len(result.references), 3)
        self.assertEqual(result.default_eligible_count, 0)
        self.assertEqual(result.references[1].verification_status, "stale")

    def test_three_key_duplicate_and_non_https_verified_reference_fail_closed(self) -> None:
        duplicate = _reference("b", canonical_url="https://example.com/a")
        with self.assertRaisesRegex(CasebookError, "duplicate"):
            build_reference_registry(
                [_reference("a"), duplicate], as_of=date(2026, 7, 16)
            )
        with self.assertRaisesRegex(CasebookError, "HTTPS"):
            build_reference_registry(
                [_reference("a", canonical_url="http://example.com/a")],
                as_of=date(2026, 7, 16),
            )

    def test_external_registry_replays_complete_body_and_detects_tamper(self) -> None:
        policy, policy_sha = load_case_reference_policy(POLICY)
        capture, capture_sha = load_external_public_capture(CAPTURE, policy=policy)
        self.assertIn("accounts have been banned", capture["post_body"])
        self.assertNotIn("body_evidence_excerpt", capture)
        with tempfile.TemporaryDirectory() as directory:
            registry_root = Path(directory) / "registry"
            documents = build_case_reference_documents(
                captures=[capture],
                capture_sha256s=[capture_sha],
                policy=policy,
                policy_sha256=policy_sha,
                as_of=date(2026, 7, 16),
                registry_id="test-case-reference-registry",
                generated_at="2026-07-16T06:30:00+00:00",
            )
            write_case_reference_registry(registry_root, documents)
            manifest_sha = sha256_bytes(
                (registry_root / "manifest.json").read_bytes()
            )
            receipt = validate_case_reference_registry(
                registry_root=registry_root,
                expected_manifest_sha256=manifest_sha,
                policy_path=POLICY,
                capture_path=CAPTURE,
            )
            self.assertEqual(receipt["status"], "passed")
            self.assertTrue(receipt["full_byte_independent_replay"])
            snapshot_path = registry_root / "external-public-snapshots.jsonl"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["post_body"] = snapshot["post_body"].replace(
                "AI bots", "automated accounts"
            )
            snapshot_path.write_bytes(canonical_json_document(snapshot))
            with self.assertRaises(CaseReferenceRegistryValidationError):
                validate_case_reference_registry(
                    registry_root=registry_root,
                    expected_manifest_sha256=manifest_sha,
                    policy_path=POLICY,
                    capture_path=CAPTURE,
                )


if __name__ == "__main__":
    unittest.main()
