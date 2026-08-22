from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from reddit_voc.v3_integrity_inputs import (
    IntegrityInputError,
    load_integrity_sources,
)
from reddit_voc.v3_integrity_snapshot import (
    canonical_json_bytes,
    canonical_json_document,
    canonical_jsonl,
    load_frozen_governed_inputs,
)
from scripts.build_reddit_v3_integrity_inputs import build_formal_inputs
from scripts.build_reddit_v3_integrity_snapshot import build_formal_candidate
from scripts.validate_reddit_v3_integrity_inputs import validate_integrity_inputs
from scripts.validate_reddit_v3_integrity_snapshot import validate_integrity_snapshot


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
POLICY = ROOT / "config/analytics/reddit-voc-content-integrity-v1.json"
GOVERNED_ROOT = V3 / "governed-signals-candidate-a1"
GOVERNED_RECEIPT = V3 / "governed-signals-validation-a1/receipt.json"
FACTS_ROOT = V3 / "voc-facts-candidate-a2"
FACTS_RECEIPT = V3 / "voc-facts-validation-a2/receipt.json"
REFERENCE_ROOT = V3 / "case-reference-candidate-a1"
REFERENCE_RECEIPT = V3 / "case-reference-validation-a1/receipt.json"
CASEBOOK_ROOT = V3 / "casebook-candidate-a1"
CASEBOOK_RECEIPT = V3 / "casebook-validation-a1/receipt.json"


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _common_cli() -> list[str]:
    return [
        "--governed-root",
        str(GOVERNED_ROOT),
        "--governed-receipt",
        str(GOVERNED_RECEIPT),
        "--voc-facts-root",
        str(FACTS_ROOT),
        "--voc-facts-receipt",
        str(FACTS_RECEIPT),
        "--reference-root",
        str(REFERENCE_ROOT),
        "--reference-receipt",
        str(REFERENCE_RECEIPT),
        "--casebook-root",
        str(CASEBOOK_ROOT),
        "--casebook-receipt",
        str(CASEBOOK_RECEIPT),
    ]


class IntegrityInputTests(unittest.TestCase):
    def _build_and_validate(self, temporary: str) -> tuple[Path, Path, str]:
        root = Path(temporary)
        output = root / "integrity-input"
        built = build_formal_inputs(
            governed_root=GOVERNED_ROOT,
            governed_receipt_path=GOVERNED_RECEIPT,
            voc_facts_root=FACTS_ROOT,
            voc_facts_receipt_path=FACTS_RECEIPT,
            reference_root=REFERENCE_ROOT,
            reference_receipt_path=REFERENCE_RECEIPT,
            casebook_root=CASEBOOK_ROOT,
            casebook_receipt_path=CASEBOOK_RECEIPT,
            policy_path=POLICY,
            output_root=output,
            input_id="reddit_voc_integrity_inputs_fixture_a1",
            generated_at_utc="2026-07-16T07:40:00+00:00",
        )
        manifest_sha = str(built["input_manifest_sha256"])
        result = validate_integrity_inputs(
            input_root=output,
            expected_manifest_sha256=manifest_sha,
            governed_root=GOVERNED_ROOT,
            governed_receipt_path=GOVERNED_RECEIPT,
            voc_facts_root=FACTS_ROOT,
            voc_facts_receipt_path=FACTS_RECEIPT,
            reference_root=REFERENCE_ROOT,
            reference_receipt_path=REFERENCE_RECEIPT,
            casebook_root=CASEBOOK_ROOT,
            casebook_receipt_path=CASEBOOK_RECEIPT,
            policy_path=POLICY,
        )
        self.assertTrue(result["full_byte_independent_replay"])
        self.assertEqual(result["counts"]["governed_facts"], 12)
        receipt = root / "input-receipt.json"
        receipt.write_bytes(canonical_json_document(result))
        return output, receipt, manifest_sha

    def test_real_sources_freeze_external_boundary_and_complete_integrity_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_root, input_receipt, _ = self._build_and_validate(temporary)
            frozen = load_frozen_governed_inputs(
                upstream_root=input_root,
                upstream_receipt_path=input_receipt,
                policy_path=POLICY,
            )
            self.assertEqual(len(frozen.facts), 12)
            self.assertEqual(len(frozen.observations), 5)
            self.assertEqual(len(frozen.event_roots), 5)
            external_facts = [
                row
                for row in frozen.facts
                if row["canonical_entity_id"] == "external_reddit_post:1u2gvn4"
            ]
            self.assertEqual(len(external_facts), 3)
            self.assertFalse(any(row["canonical_entity_id"] == "t3_1u2gvn4" for row in frozen.facts))
            self.assertFalse(any(row.get("voc_id") == "post:1u2gvn4" for row in frozen.facts))

            candidate = Path(temporary) / "integrity-candidate"
            built = build_formal_candidate(
                upstream_root=input_root,
                upstream_receipt_path=input_receipt,
                policy_path=POLICY,
                output_dir=candidate,
                snapshot_id="reddit_voc_integrity_fixture_candidate_a1",
                generated_at_utc="2026-07-16T07:41:00+00:00",
            )
            validated = validate_integrity_snapshot(
                snapshot_dir=candidate,
                expected_manifest_sha256=str(built["integrity_manifest_sha256"]),
                upstream_root=input_root,
                upstream_receipt_path=input_receipt,
                policy_path=POLICY,
            )
            self.assertEqual(validated["status"], "passed")
            self.assertTrue(validated["semantic_checks"]["fixed_event_c2_i3"])
            event = json.loads(
                (candidate / "event-dossiers.jsonl").read_text(encoding="utf-8")
            )
            self.assertFalse(event["brand_control_confirmed"])
            self.assertEqual(event["lifecycle_status"], "review_required")

    def test_rehashed_input_tamper_fails_full_byte_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_root, _, _ = self._build_and_validate(temporary)
            fact_path = input_root / "governed-facts.jsonl"
            facts = [json.loads(line) for line in fact_path.read_text(encoding="utf-8").splitlines()]
            facts[0]["canonical_value"] = "attacker_rewrite"
            identity = dict(facts[0])
            identity.pop("fact_id")
            facts[0]["fact_id"] = _sha(canonical_json_bytes(identity))
            fact_payload = canonical_jsonl(facts)
            fact_path.write_bytes(fact_payload)
            manifest_path = input_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["governed-facts.jsonl"] = {
                "bytes": len(fact_payload),
                "rows": len(facts),
                "sha256": _sha(fact_payload),
            }
            manifest_payload = canonical_json_document(manifest)
            manifest_path.write_bytes(manifest_payload)
            with self.assertRaisesRegex(IntegrityInputError, "independent replay"):
                validate_integrity_inputs(
                    input_root=input_root,
                    expected_manifest_sha256=_sha(manifest_payload),
                    governed_root=GOVERNED_ROOT,
                    governed_receipt_path=GOVERNED_RECEIPT,
                    voc_facts_root=FACTS_ROOT,
                    voc_facts_receipt_path=FACTS_RECEIPT,
                    reference_root=REFERENCE_ROOT,
                    reference_receipt_path=REFERENCE_RECEIPT,
                    casebook_root=CASEBOOK_ROOT,
                    casebook_receipt_path=CASEBOOK_RECEIPT,
                    policy_path=POLICY,
                )

    def test_resigned_missing_external_fact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            casebook = Path(temporary) / "casebook"
            shutil.copytree(CASEBOOK_ROOT, casebook)
            fact_path = casebook / "external-governance-facts.jsonl"
            rows = [json.loads(line) for line in fact_path.read_text(encoding="utf-8").splitlines()][:-1]
            payload = canonical_jsonl(rows)
            fact_path.write_bytes(payload)
            manifest_path = casebook / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["external-governance-facts.jsonl"].update(
                {"bytes": len(payload), "rows": len(rows), "sha256": _sha(payload)}
            )
            manifest_payload = canonical_json_document(manifest)
            manifest_path.write_bytes(manifest_payload)
            receipt_path = Path(temporary) / "casebook-receipt.json"
            receipt = json.loads(CASEBOOK_RECEIPT.read_text(encoding="utf-8"))
            receipt["casebook_manifest_sha256"] = _sha(manifest_payload)
            receipt_path.write_bytes(canonical_json_document(receipt))
            with self.assertRaisesRegex(IntegrityInputError, "cardinality"):
                load_integrity_sources(
                    governed_root=GOVERNED_ROOT,
                    governed_receipt_path=GOVERNED_RECEIPT,
                    voc_facts_root=FACTS_ROOT,
                    voc_facts_receipt_path=FACTS_RECEIPT,
                    reference_root=REFERENCE_ROOT,
                    reference_receipt_path=REFERENCE_RECEIPT,
                    casebook_root=casebook,
                    casebook_receipt_path=receipt_path,
                )

    def test_build_and_validate_clis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "input"
            build = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_reddit_v3_integrity_inputs.py"),
                    *_common_cli(),
                    "--output",
                    str(output),
                    "--input-id",
                    "reddit_voc_integrity_cli_fixture_a1",
                    "--generated-at-utc",
                    "2026-07-16T07:42:00+00:00",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            built = json.loads(build.stdout)
            receipt = Path(temporary) / "receipt.json"
            validate = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/validate_reddit_v3_integrity_inputs.py"),
                    *_common_cli(),
                    "--input-root",
                    str(output),
                    "--expected-manifest-sha256",
                    built["input_manifest_sha256"],
                    "--receipt",
                    str(receipt),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            validated = json.loads(validate.stdout)
            self.assertEqual(validated["status"], "passed")
            self.assertEqual(validated["receipt_disposition"], "created")


if __name__ == "__main__":
    unittest.main()
