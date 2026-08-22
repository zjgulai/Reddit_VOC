from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_v3_personas_snapshot import (
    PersonaBuildCliError,
    _validate_automation_classification_state,
    load_bound_governed_persona_signals,
    load_bound_persona_inputs,
)
from reddit_voc.v3_persona_inference import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
FACTS_DIR = RUN_ROOT / "voc-facts-candidate-a2"
FACTS_RECEIPT = RUN_ROOT / "voc-facts-validation-a2/receipt.json"
REFERENCE_MANIFEST = ROOT / "data/reference/reddit-voc-v3/manifest.json"
FACTS_SHA = "4a0b43f664cc8bd2cf0fbd63d0428aaeadec1a6b405a066123250e4f90675b77"
FACTS_RECEIPT_SHA = (
    "ff6ee119c5861cfad50d256caebaf3600564013b6069b97d047e9197c90eb61f"
)
REFERENCE_SHA = "f899cd2fcb4562b70255515a4ec7c3280060f7e1027e694dd8cd9264f3994bcf"
GOVERNED_MANIFEST = RUN_ROOT / "governed-signals-candidate-a1/manifest.json"
GOVERNED_RECEIPT = RUN_ROOT / "governed-signals-validation-a1/receipt.json"
GOVERNED_MANIFEST_SHA = (
    "44c66b198f3dc33873036912c239f89d28fabe36ed2aaacc5662c7686dd4c24a"
)
GOVERNED_RECEIPT_SHA = (
    "135d9f4a78dd772f5feae193783d98f78969d8b68d3cf6bf2b368f6fee98d9db"
)


class PersonaV3CliBindingTests(unittest.TestCase):
    def _bound_kwargs(self) -> dict[str, object]:
        return {
            "facts_dir": FACTS_DIR,
            "expected_facts_manifest_sha256": FACTS_SHA,
            "facts_validation_receipt_path": FACTS_RECEIPT,
            "expected_facts_validation_receipt_sha256": FACTS_RECEIPT_SHA,
            "reference_manifest_path": REFERENCE_MANIFEST,
            "expected_reference_manifest_sha256": REFERENCE_SHA,
            "allow_blocked_upstream_candidate": True,
        }

    def test_real_a2_reopens_and_reconciles_737_automation_vocs(self) -> None:
        (
            vocs,
            automation_vocs,
            facts_sha,
            receipt_sha,
            automation_classifications_sha,
            automation_classification_rows,
            reference_sha,
            upstream_status,
            upstream_promotable,
        ) = load_bound_persona_inputs(
            facts_dir=FACTS_DIR,
            expected_facts_manifest_sha256=FACTS_SHA,
            facts_validation_receipt_path=FACTS_RECEIPT,
            expected_facts_validation_receipt_sha256=FACTS_RECEIPT_SHA,
            reference_manifest_path=REFERENCE_MANIFEST,
            expected_reference_manifest_sha256=REFERENCE_SHA,
            allow_blocked_upstream_candidate=True,
        )
        self.assertEqual(len(vocs), 23586)
        self.assertEqual(len(automation_vocs), 737)
        self.assertEqual(facts_sha, FACTS_SHA)
        self.assertEqual(receipt_sha, FACTS_RECEIPT_SHA)
        self.assertEqual(
            automation_classifications_sha,
            "980b6485bdaae1855b9406308982bb4ce067acc92044ed7492f7a7f72f39422d",
        )
        self.assertEqual(automation_classification_rows, 27148)
        self.assertEqual(reference_sha, REFERENCE_SHA)
        self.assertEqual(upstream_status, "blocked_pending_atomic_facts")
        self.assertFalse(upstream_promotable)

    def test_blocked_upstream_requires_explicit_candidate_flag(self) -> None:
        with self.assertRaisesRegex(PersonaBuildCliError, "blocked"):
            load_bound_persona_inputs(
                facts_dir=FACTS_DIR,
                expected_facts_manifest_sha256=FACTS_SHA,
                facts_validation_receipt_path=FACTS_RECEIPT,
                expected_facts_validation_receipt_sha256=FACTS_RECEIPT_SHA,
                reference_manifest_path=REFERENCE_MANIFEST,
                expected_reference_manifest_sha256=REFERENCE_SHA,
                allow_blocked_upstream_candidate=False,
            )

    def test_true_automation_cannot_claim_not_detected_state(self) -> None:
        classifications = FACTS_DIR / "automation-classifications.jsonl"
        determined: dict[str, object] | None = None
        with classifications.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("automation_determined") is True:
                    determined = row
                    break
        self.assertIsNotNone(determined)
        assert determined is not None
        determined["classification_status"] = "not_detected"
        determined["classification_accounting_bucket"] = "not_automation"
        determined["reason_codes"] = ["no_automation_signal"]
        with self.assertRaisesRegex(PersonaBuildCliError, "state"):
            _validate_automation_classification_state(determined)

    def test_unaccounted_booleans_do_not_masquerade_as_zero(self) -> None:
        receipt = json.loads(FACTS_RECEIPT.read_text(encoding="utf-8"))
        receipt["unaccounted_eligibility_members"] = False
        receipt["unaccounted_vocs"] = False
        payload = canonical_json_bytes(receipt) + b"\n"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_bytes(payload)
            kwargs = self._bound_kwargs()
            kwargs["facts_validation_receipt_path"] = path
            kwargs["expected_facts_validation_receipt_sha256"] = sha256(
                payload
            ).hexdigest()
            with self.assertRaisesRegex(PersonaBuildCliError, "binding"):
                load_bound_persona_inputs(**kwargs)

    def _governed_kwargs(self) -> dict[str, object]:
        return {
            "manifest_path": GOVERNED_MANIFEST,
            "expected_manifest_sha256": GOVERNED_MANIFEST_SHA,
            "validation_receipt_path": GOVERNED_RECEIPT,
            "expected_validation_receipt_sha256": GOVERNED_RECEIPT_SHA,
            "expected_facts_manifest_sha256": FACTS_SHA,
            "expected_facts_validation_receipt_sha256": FACTS_RECEIPT_SHA,
        }

    def test_real_governed_signals_are_bound_and_comment_safe(self) -> None:
        bound = load_bound_governed_persona_signals(**self._governed_kwargs())
        self.assertEqual(bound.source_snapshot_id, "reddit_add_data_20260715_v1")
        self.assertEqual(
            bound.snapshot_id,
            "reddit_voc_governed_signals_20260716_candidate_a1",
        )
        self.assertEqual(bound.consumption_status, "eligible_for_downstream_consumption")
        self.assertTrue(bound.promotable)
        self.assertGreater(bound.loaded_promoted_fact_count, 0)
        self.assertGreater(bound.injected_voc_count, 0)
        self.assertEqual(
            bound.loaded_promoted_fact_count,
            bound.injected_fact_count + bound.dropped_comment_fact_count,
        )
        self.assertGreater(bound.dropped_comment_voc_count, 0)
        for voc_id, signals in bound.signals_by_voc_id.items():
            if not voc_id.startswith("comment:"):
                continue
            refs = signals["signal_evidence_refs"]
            self.assertTrue(
                any(
                    ref["evidence_field"] == "current_comment_body"
                    for ref in refs
                )
            )
            registry = bound.facts_by_voc_id[voc_id]
            for ref in refs:
                if ref["evidence_field"] == "current_comment_body":
                    continue
                fact = registry[ref["source_fact_id"]]
                self.assertEqual(fact["evidence_scope"], "cross_context")
                if fact["fact_type"] == "entity_tag_fact":
                    self.assertEqual(fact["attributes"]["signal_kind"], "topic")
                else:
                    self.assertEqual(fact["fact_type"], "entity_brand_fact")

    def test_governed_receipt_bool_unaccounted_fails_closed(self) -> None:
        receipt = json.loads(GOVERNED_RECEIPT.read_text(encoding="utf-8"))
        receipt["unaccounted_facts"] = False
        receipt["unaccounted_vocs"] = False
        payload = (
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_bytes(payload)
            kwargs = self._governed_kwargs()
            kwargs["validation_receipt_path"] = path
            kwargs["expected_validation_receipt_sha256"] = sha256(payload).hexdigest()
            with self.assertRaisesRegex(PersonaBuildCliError, "binding"):
                load_bound_governed_persona_signals(**kwargs)


if __name__ == "__main__":
    unittest.main()
