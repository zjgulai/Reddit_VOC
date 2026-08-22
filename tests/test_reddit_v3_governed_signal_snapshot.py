from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_closed_set_facts import load_closed_set_resources
from reddit_voc.v3_governed_signal_inputs import (
    GovernedSignalInputs,
    canonical_json_bytes,
    load_formal_governed_signal_inputs,
    sha256_bytes,
)
from reddit_voc.v3_governed_signal_snapshot import (
    FACT_TABLE_FILES,
    write_governed_signal_snapshot,
)
from reddit_voc.v3_governed_signal_snapshot_validator import (
    GovernedSignalValidationError,
    validate_governed_signal_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
FACTS_PARENT = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
FACTS_ROOT = FACTS_PARENT / "voc-facts-candidate-a2"
FACTS_RECEIPT = FACTS_PARENT / "voc-facts-validation-a2/receipt.json"
BRIDGED_FACTS_PARENT = (
    ROOT / "tmp/reddit-voc-v3/candidate-orchestration/v3-source-bridge-001"
)
BRIDGED_FACTS_ROOT = BRIDGED_FACTS_PARENT / "voc-facts"
BRIDGED_FACTS_RECEIPT = BRIDGED_FACTS_PARENT / "voc-facts-validation/receipt.json"
DIM_TAG = ROOT / "dim_tag_v6.3_final.csv"
PRODUCT_LEDGER = (
    ROOT / "config/product_entities/momcozy-product-entity-ledger-v1.json"
)
REGISTRY = (
    ROOT / "config/analytics/reddit-voc-closed-set-signal-registry-v1.json"
)
CREATED_AT = "2026-07-16T00:00:00+00:00"


def _post(text: str, post_id: str) -> dict[str, object]:
    return {
        "analysis_fields": {
            "current_comment_body": "",
            "post_body": text,
            "post_title": "",
        },
        "analysis_text_status": "ready",
        "canonical_entity_id": f"t3_{post_id}",
        "comment_context_id": None,
        "comment_id": None,
        "metric_distinct_key": post_id,
        "post_id": post_id,
        "schema_version": "reddit_voc_fielded_voc_v1",
        "thread_id": post_id,
        "voc_id": f"post:{post_id}",
        "voc_type": "post_voc",
    }


def _bound_fixture_vocs() -> list[dict[str, object]]:
    wanted = {"post:1kkvihg", "post:1o1pqox"}
    result: list[dict[str, object]] = []
    with (FACTS_ROOT / "vocs.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["voc_id"] in wanted:
                result.append(row)
    if {row["voc_id"] for row in result} != wanted:
        raise AssertionError("governance fixture VOCs are unavailable")
    result.append(
        _post(
            "Momcozy M6 breast pump works great but has weak suction. "
            "I highly recommend it.",
            "organicfixture",
        )
    )
    result.append(_post("I am a bot and this action was automatic.", "botfixture"))
    return result


class GovernedSignalSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resources = load_closed_set_resources(
            dim_tag_path=DIM_TAG,
            product_entity_ledger_path=PRODUCT_LEDGER,
            registry_path=REGISTRY,
        )
        cls.formal_inputs = load_formal_governed_signal_inputs(
            facts_root=FACTS_ROOT,
            facts_receipt_path=FACTS_RECEIPT,
            dim_tag_path=DIM_TAG,
            product_entity_ledger_path=PRODUCT_LEDGER,
            registry_path=REGISTRY,
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vocs = _bound_fixture_vocs()
        self.inputs = GovernedSignalInputs(
            vocs=tuple(self.vocs),
            automation_voc_ids=frozenset({"post:botfixture"}),
            input_bindings={
                "fixture_sha256": "0" * 64,
            },
            source_snapshot_id="reddit_add_data_20260715_v1",
        )

    def build(self, name: str = "candidate") -> Path:
        output = self.root / name
        write_governed_signal_snapshot(
            vocs=self.inputs.vocs,
            automation_voc_ids=self.inputs.automation_voc_ids,
            resources=self.resources,
            input_bindings=self.inputs.input_bindings,
            source_snapshot_id=self.inputs.source_snapshot_id,
            snapshot_id="fixture-snapshot",
            created_at=CREATED_AT,
            output_root=output,
        )
        return output

    def validate(self, snapshot: Path) -> dict[str, object]:
        return validate_governed_signal_snapshot(
            snapshot_root=snapshot,
            inputs=self.inputs,
            dim_tag_path=DIM_TAG,
            product_entity_ledger_path=PRODUCT_LEDGER,
            registry_path=REGISTRY,
        )

    def test_formal_inputs_exact_bind_a2_and_exclude_737_before_facts(self) -> None:
        self.assertEqual(len(self.formal_inputs.vocs), 23_586)
        self.assertEqual(len(self.formal_inputs.automation_voc_ids), 737)
        self.assertEqual(len(self.formal_inputs.organic_vocs), 22_849)

    def test_formal_inputs_accept_explicit_sha_bound_bridge_facts(self) -> None:
        manifest_sha256 = sha256_bytes(
            (BRIDGED_FACTS_ROOT / "manifest.json").read_bytes()
        )
        receipt_sha256 = sha256_bytes(BRIDGED_FACTS_RECEIPT.read_bytes())
        inputs = load_formal_governed_signal_inputs(
            facts_root=BRIDGED_FACTS_ROOT,
            facts_receipt_path=BRIDGED_FACTS_RECEIPT,
            dim_tag_path=DIM_TAG,
            product_entity_ledger_path=PRODUCT_LEDGER,
            registry_path=REGISTRY,
            facts_manifest_sha256=manifest_sha256,
            facts_receipt_sha256=receipt_sha256,
        )
        self.assertEqual(len(inputs.vocs), 23_586)
        self.assertEqual(len(inputs.automation_voc_ids), 737)
        self.assertEqual(
            inputs.input_bindings["facts_manifest_sha256"], manifest_sha256
        )
        self.assertEqual(
            inputs.input_bindings["facts_receipt_sha256"], receipt_sha256
        )

    def test_eight_tables_are_written_and_independently_replayable(self) -> None:
        snapshot = self.build()
        self.assertEqual(
            {path.name for path in snapshot.iterdir()},
            {"manifest.json", *FACT_TABLE_FILES.values()},
        )
        manifest = json.loads((snapshot / "manifest.json").read_text())
        self.assertEqual(manifest["counts"]["total_vocs"], 4)
        self.assertEqual(manifest["counts"]["automation_excluded_vocs"], 1)
        self.assertEqual(manifest["counts"]["organic_vocs"], 3)
        for fact_type in FACT_TABLE_FILES:
            self.assertGreater(manifest["table_rows"][fact_type], 0)
        for filename in FACT_TABLE_FILES.values():
            self.assertNotIn(b"post:botfixture", (snapshot / filename).read_bytes())
        receipt = self.validate(snapshot)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(
            receipt["consumption_status"],
            "eligible_for_downstream_consumption",
        )
        self.assertIs(receipt["promotable"], True)
        self.assertEqual(receipt["validated_tables"], 8)

    def test_validator_rejects_file_tamper_before_replay(self) -> None:
        snapshot = self.build()
        target = snapshot / "entity-brand-facts.jsonl"
        target.write_bytes(target.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(
            GovernedSignalValidationError, "file contract"
        ):
            self.validate(snapshot)

    def test_validator_rejects_resigned_missing_fact(self) -> None:
        snapshot = self.build()
        target = snapshot / "entity-brand-facts.jsonl"
        lines = target.read_bytes().splitlines(keepends=True)
        removed = json.loads(lines[0])
        payload = b"".join(lines[1:])
        target.write_bytes(payload)
        manifest = json.loads((snapshot / "manifest.json").read_text())
        contract = manifest["files"][target.name]
        contract.update(
            {
                "bytes": len(payload),
                "rows": contract["rows"] - 1,
                "sha256": sha256_bytes(payload),
            }
        )
        manifest["table_rows"]["entity_brand_fact"] -= 1
        manifest["counts"]["fact_rows"] -= 1
        manifest["counts"][f"{removed['decision_status']}_facts"] -= 1
        (snapshot / "manifest.json").write_bytes(
            canonical_json_bytes(manifest) + b"\n"
        )
        with self.assertRaises(Exception):
            self.validate(snapshot)

    def test_validator_rejects_undeclared_entry(self) -> None:
        snapshot = self.build()
        (snapshot / "extra.jsonl").write_bytes(b"")
        with self.assertRaisesRegex(
            GovernedSignalValidationError, "undeclared"
        ):
            self.validate(snapshot)

    def test_output_is_deterministic_across_voc_order(self) -> None:
        first = self.build("first")
        second = self.root / "second"
        write_governed_signal_snapshot(
            vocs=reversed(self.inputs.vocs),
            automation_voc_ids=self.inputs.automation_voc_ids,
            resources=self.resources,
            input_bindings=self.inputs.input_bindings,
            source_snapshot_id=self.inputs.source_snapshot_id,
            snapshot_id="fixture-snapshot",
            created_at=CREATED_AT,
            output_root=second,
        )
        for name in {"manifest.json", *FACT_TABLE_FILES.values()}:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
