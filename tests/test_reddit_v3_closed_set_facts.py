from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import unittest

from reddit_voc.v3_closed_set_facts import (
    CLOSED_SET_FACT_TYPES,
    CLOSED_SET_REGISTRY_SHA256,
    DIM_TAG_SHA256,
    PRODUCT_ENTITY_LEDGER_SHA256,
    ClosedSetFactError,
    build_closed_set_facts,
    canonical_closed_set_fact_jsonl_bytes,
    group_closed_set_fact_tables,
    load_closed_set_resources,
    materialize_closed_set_facts,
    promoted_signal_facts_by_id,
    signal_evidence_refs,
)
from reddit_voc.v3_closed_set_facts_validator import (
    ClosedSetFactValidationError,
    validate_closed_set_facts,
)
from reddit_voc.v3_persona_inference import (
    build_cohort_assignments,
    load_persona_cohort_config,
    load_persona_dictionary,
)


ROOT = Path(__file__).resolve().parents[1]
DIM_TAG_PATH = ROOT / "dim_tag_v6.3_final.csv"
PRODUCT_LEDGER_PATH = (
    ROOT / "config/product_entities/momcozy-product-entity-ledger-v1.json"
)
REGISTRY_PATH = (
    ROOT / "config/analytics/reddit-voc-closed-set-signal-registry-v1.json"
)
PERSONA_DICTIONARY_PATH = (
    ROOT / "data/reference/reddit-voc-v3/dim_persona_v1.csv"
)
PERSONA_CONFIG_PATH = (
    ROOT / "config/personas/reddit-voc-persona-cohorts-v3.json"
)
REAL_VOC_PATH = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
    / "voc-facts-candidate-a2/vocs.jsonl"
)
SNAPSHOT_ID = "reddit_add_data_20260715_v1"
CREATED_AT = "2026-07-16T00:00:00+00:00"


def _rehash_fact(
    fact: object,
    *,
    decision_status: str,
    reason_codes: list[str],
) -> dict[str, object]:
    row = fact.as_dict()
    row["decision_status"] = decision_status
    row["reason_codes"] = reason_codes
    identity = dict(row)
    identity.pop("fact_id")
    row["fact_id"] = sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return row


def _post(
    text: str,
    *,
    title: str = "",
    post_id: str = "fixture",
) -> dict[str, object]:
    return {
        "analysis_fields": {
            "current_comment_body": "",
            "post_body": text,
            "post_title": title,
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


def _comment(
    current: str,
    *,
    parent_title: str = "",
    parent_body: str = "",
    comment_id: str = "fixture",
    post_id: str = "root",
) -> dict[str, object]:
    return {
        "analysis_fields": {
            "current_comment_body": current,
            "post_body": parent_body,
            "post_title": parent_title,
        },
        "analysis_text_status": "ready",
        "canonical_entity_id": f"t1_{comment_id}",
        "comment_context_id": f"{post_id}:{comment_id}",
        "comment_id": comment_id,
        "metric_distinct_key": comment_id,
        "post_id": post_id,
        "schema_version": "reddit_voc_fielded_voc_v1",
        "thread_id": post_id,
        "voc_id": f"comment:{comment_id}",
        "voc_type": "comment_context_voc",
    }


class ClosedSetFactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resources = load_closed_set_resources(
            dim_tag_path=DIM_TAG_PATH,
            product_entity_ledger_path=PRODUCT_LEDGER_PATH,
            registry_path=REGISTRY_PATH,
        )

    def facts(self, voc: dict[str, object]):
        return build_closed_set_facts(
            voc,
            resources=self.resources,
            source_snapshot_id=SNAPSHOT_ID,
            created_at=CREATED_AT,
        )

    def validate(self, facts, vocs):
        return validate_closed_set_facts(
            facts,
            vocs,
            dim_tag_path=DIM_TAG_PATH,
            product_entity_ledger_path=PRODUCT_LEDGER_PATH,
            registry_path=REGISTRY_PATH,
            source_snapshot_id=SNAPSHOT_ID,
            created_at=CREATED_AT,
        )

    def test_resources_are_exactly_bound_and_five_table_scope_is_explicit(self) -> None:
        self.assertEqual(self.resources.dim_tag_sha256, DIM_TAG_SHA256)
        self.assertEqual(
            self.resources.product_entity_ledger_sha256,
            PRODUCT_ENTITY_LEDGER_SHA256,
        )
        self.assertEqual(
            self.resources.registry_sha256, CLOSED_SET_REGISTRY_SHA256
        )
        self.assertEqual(len(self.resources.tag_specs), 13_946)
        self.assertEqual(len(self.resources.product_specs), 40)
        self.assertEqual(len(self.resources.approved_tag_phrases), 3)
        self.assertEqual(
            set(CLOSED_SET_FACT_TYPES),
            {
                "entity_brand_fact",
                "entity_product_fact",
                "entity_sentiment_fact",
                "entity_problem_fact",
                "entity_tag_fact",
            },
        )

    def test_all_five_fact_types_have_replayable_spans_and_semantic_ids(self) -> None:
        voc = _post(
            "Momcozy M6 breast pump works great but has weak suction. "
            "I highly recommend it and compared with Philips Avent."
        )
        facts = self.facts(voc)
        self.assertEqual({fact.fact_type for fact in facts}, set(CLOSED_SET_FACT_TYPES))
        fields = voc["analysis_fields"]
        for fact in facts:
            substring = fields[fact.evidence_field][
                fact.evidence_start : fact.evidence_end
            ]
            self.assertEqual(
                fact.evidence_text_sha256,
                sha256(substring.encode("utf-8")).hexdigest(),
            )
            identity = fact.as_dict()
            identity.pop("fact_id")
            self.assertEqual(
                fact.fact_id,
                sha256(
                    json.dumps(
                        identity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            )
        receipt = self.validate(facts, [voc])
        self.assertEqual(receipt["fact_rows"], len(facts))
        self.assertEqual(receipt["unaccounted_fact_keys"], 0)

    def test_comment_context_only_flows_to_brand_product_and_topic(self) -> None:
        voc = _comment(
            "My flange hurts and milk leaking. I am very disappointed.",
            parent_title="Momcozy M5 pump compared with Spectra",
            parent_body="It works great but has weak suction.",
        )
        facts = self.facts(voc)
        parent_facts = [fact for fact in facts if fact.evidence_scope == "cross_context"]
        self.assertTrue(parent_facts)
        self.assertTrue(
            all(
                fact.fact_type
                in {"entity_brand_fact", "entity_product_fact", "entity_tag_fact"}
                for fact in parent_facts
            )
        )
        self.assertTrue(
            all(
                fact.evidence_field == "current_comment_body"
                for fact in facts
                if fact.fact_type
                in {"entity_sentiment_fact", "entity_problem_fact"}
            )
        )
        self.assertFalse(
            any(
                fact.fact_type == "entity_sentiment_fact"
                and fact.canonical_value == "positive"
                for fact in facts
            )
        )
        self.assertFalse(
            any(
                fact.fact_type == "entity_problem_fact"
                and fact.canonical_value == "output_supply"
                for fact in facts
            )
        )
        self.validate(facts, [voc])

    def test_legacy_shared_and_single_lexical_matches_stay_held(self) -> None:
        voc = _post("This product is leaking and easy to clean.")
        facts = self.facts(voc)
        tag_facts = [fact for fact in facts if fact.fact_type == "entity_tag_fact"]
        self.assertTrue(tag_facts)
        self.assertFalse(any(fact.decision_status == "promoted" for fact in tag_facts))
        self.assertTrue(
            any("shared_phrase_ambiguous" in fact.reason_codes for fact in tag_facts)
        )
        self.assertTrue(
            any("single_token_ambiguous" in fact.reason_codes for fact in tag_facts)
        )
        self.validate(facts, [voc])

    def test_registered_recommendation_promotes_but_negation_and_conflict_hold(self) -> None:
        promoted_voc = _post("I highly recommend this pump.")
        promoted = self.facts(promoted_voc)
        recommendation = next(
            fact for fact in promoted if fact.canonical_value == "L0-GEN-103"
        )
        self.assertEqual(recommendation.decision_status, "promoted")

        conflict_voc = _post(
            "I do not highly recommend it. It works great, but I am very disappointed."
        )
        conflict = self.facts(conflict_voc)
        negated = next(
            fact for fact in conflict if fact.canonical_value == "L0-GEN-103"
        )
        self.assertEqual(negated.decision_status, "held")
        self.assertIn("negated_evidence", negated.reason_codes)
        sentiment = [
            fact for fact in conflict if fact.fact_type == "entity_sentiment_fact"
        ]
        self.assertTrue(sentiment)
        self.assertTrue(all(fact.decision_status == "held" for fact in sentiment))
        self.assertTrue(
            all("sentiment_conflict" in fact.reason_codes for fact in sentiment)
        )
        self.validate(conflict, [conflict_voc])

    def test_contextual_product_alias_and_spu_governance_fail_closed(self) -> None:
        context_free = self.facts(_post("Has anyone tried M5?"))
        m5 = next(
            fact
            for fact in context_free
            if fact.fact_type == "entity_product_fact"
        )
        self.assertEqual(m5.decision_status, "held")
        self.assertEqual(m5.canonical_value, "family:m5-smart")

        governed = self.facts(
            _post("Momcozy M6 breast pump and Momcozy BM03 baby monitor")
        )
        products = {
            fact.canonical_value: fact
            for fact in governed
            if fact.fact_type == "entity_product_fact"
        }
        self.assertIn("spu:SPU000167", products)
        self.assertEqual(products["spu:SPU000167"].decision_status, "promoted")
        self.assertIn("family:bm03-video-monitor", products)
        self.assertNotIn("spu:SPU000176", products)
        self.validate(governed, [_post("Momcozy M6 breast pump and Momcozy BM03 baby monitor")])

    def test_promoted_fact_rows_exact_join_persona_signal_registry(self) -> None:
        voc = _post("I highly recommend this pump.", post_id="recommend")
        facts = self.facts(voc)
        recommendation = [
            fact
            for fact in facts
            if fact.canonical_value == "L0-GEN-103"
            and fact.decision_status == "promoted"
        ]
        self.assertEqual(len(recommendation), 1)
        registry = promoted_signal_facts_by_id(facts)
        refs = signal_evidence_refs(recommendation)
        dictionary = load_persona_dictionary(PERSONA_DICTIONARY_PATH)
        config = load_persona_cohort_config(
            PERSONA_CONFIG_PATH,
            dictionary=dictionary,
        )
        assignments = build_cohort_assignments(
            voc,
            facts=(),
            config=config,
            signals={
                "evidence_scope": ["post_body"],
                "signal_evidence_refs": list(refs),
                "snapshot_id": SNAPSHOT_ID,
                "voc_tag_ids": ["L0-GEN-103"],
            },
            governed_signal_facts_by_id=registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        self.assertIn(
            "recommendation_expression",
            {row.cohort_id for row in assignments},
        )

    def test_independent_validator_rejects_tamper_and_missing_fact(self) -> None:
        voc = _post("Momcozy M6 breast pump works great and has weak suction.")
        facts = self.facts(voc)
        self.validate(facts, [voc])
        with self.assertRaisesRegex(
            ClosedSetFactValidationError, "fact ID"
        ):
            self.validate((replace(facts[0], fact_id="0" * 64), *facts[1:]), [voc])
        with self.assertRaisesRegex(
            ClosedSetFactValidationError, "do not reproduce"
        ):
            self.validate(facts[:-1], [voc])

    def test_independent_validator_rejects_rehashed_decision_and_reason_tamper(self) -> None:
        promoted_voc = _post("I highly recommend this pump.", post_id="promoted")
        promoted_facts = self.facts(promoted_voc)
        recommendation = next(
            fact
            for fact in promoted_facts
            if fact.canonical_value == "L0-GEN-103"
            and fact.decision_status == "promoted"
        )
        forged_held = _rehash_fact(
            recommendation,
            decision_status="held",
            reason_codes=["negated_evidence"],
        )
        with self.assertRaisesRegex(
            ClosedSetFactValidationError, "decision or reasons"
        ):
            self.validate(
                tuple(
                    forged_held if fact is recommendation else fact
                    for fact in promoted_facts
                ),
                [promoted_voc],
            )

        negated_voc = _post(
            "I do not highly recommend this pump.",
            post_id="negated",
        )
        negated_facts = self.facts(negated_voc)
        negated = next(
            fact
            for fact in negated_facts
            if fact.canonical_value == "L0-GEN-103"
        )
        forged_promoted = _rehash_fact(
            negated,
            decision_status="promoted",
            reason_codes=["closed_set_exact_phrase"],
        )
        with self.assertRaisesRegex(
            ClosedSetFactValidationError, "decision or reasons"
        ):
            self.validate(
                tuple(
                    forged_promoted if fact is negated else fact
                    for fact in negated_facts
                ),
                [negated_voc],
            )

    def test_independent_validator_recomputes_every_governance_decision_class(self) -> None:
        cases = (
            (
                "sentiment_conflict",
                _post(
                    "It works great but I am very disappointed.",
                    post_id="sentimentconflict",
                ),
                lambda fact: fact.fact_type == "entity_sentiment_fact"
                and fact.canonical_value == "positive",
                "held",
                ["closed_set_exact_phrase", "negated_evidence"],
            ),
            (
                "shared_and_single_token",
                _post(
                    "This product is leaking and easy to clean.",
                    post_id="sharedsingle",
                ),
                lambda fact: fact.fact_type == "entity_tag_fact"
                and fact.canonical_value == "L0-GEN-057",
                "held",
                [
                    "legacy_dictionary_lexical_unvalidated",
                    "shared_phrase_ambiguous",
                    "single_token_ambiguous",
                ],
            ),
            (
                "contextual_product_without_context",
                _post("Has anyone tried M5?", post_id="productheld"),
                lambda fact: fact.fact_type == "entity_product_fact",
                "held",
                ["contextual_product_alias_requires_context"],
            ),
            (
                "contextual_product_with_context",
                _post("Momcozy M5 breast pump", post_id="productpromoted"),
                lambda fact: fact.fact_type == "entity_product_fact",
                "promoted",
                ["closed_set_exact_phrase"],
            ),
            (
                "single_token_competitor_without_context",
                _post("Spectra", post_id="competitorheld"),
                lambda fact: fact.fact_type == "entity_brand_fact",
                "held",
                ["single_token_entity_requires_context"],
            ),
            (
                "single_token_competitor_with_context",
                _post("Spectra breast pump", post_id="competitorpromoted"),
                lambda fact: fact.fact_type == "entity_brand_fact",
                "promoted",
                ["contextual_product_alias_with_context"],
            ),
        )
        for label, voc, selector, forged_status, forged_reasons in cases:
            with self.subTest(label=label):
                facts = self.facts(voc)
                target = next(fact for fact in facts if selector(fact))
                forged = _rehash_fact(
                    target,
                    decision_status=forged_status,
                    reason_codes=forged_reasons,
                )
                with self.assertRaisesRegex(
                    ClosedSetFactValidationError,
                    "decision or reasons",
                ):
                    self.validate(
                        tuple(
                            forged if fact is target else fact
                            for fact in facts
                        ),
                        [voc],
                    )

    def test_materialization_partition_and_jsonl_are_deterministic(self) -> None:
        vocs = [
            _post("Momcozy M6 breast pump works great.", post_id="b"),
            _post("I highly recommend it.", post_id="a"),
        ]
        facts = materialize_closed_set_facts(
            vocs,
            resources=self.resources,
            source_snapshot_id=SNAPSHOT_ID,
            created_at=CREATED_AT,
        )
        tables = group_closed_set_fact_tables(facts)
        self.assertEqual(tuple(tables), CLOSED_SET_FACT_TYPES)
        self.assertEqual(
            canonical_closed_set_fact_jsonl_bytes(reversed(facts)),
            canonical_closed_set_fact_jsonl_bytes(facts),
        )
        self.validate(facts, vocs)
        with self.assertRaisesRegex(ClosedSetFactError, "duplicate"):
            materialize_closed_set_facts(
                [vocs[0], vocs[0]],
                resources=self.resources,
                source_snapshot_id=SNAPSHOT_ID,
                created_at=CREATED_AT,
            )

    def test_explicit_automation_is_not_filtered_by_fact_layer(self) -> None:
        voc = _post("Momcozy M6 breast pump works great.")
        voc["explicit_automation"] = True
        facts = self.facts(voc)
        self.assertTrue(facts)
        self.assertTrue(any(fact.decision_status == "promoted" for fact in facts))
        self.validate(facts, [voc])

    def test_small_real_v3_sample_replays_without_full_materialization(self) -> None:
        if not REAL_VOC_PATH.exists():
            self.skipTest("private V3 candidate is unavailable")
        selected = None
        with REAL_VOC_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("voc_id") == "post:13z0mtc":
                    selected = row
                    break
        self.assertIsNotNone(selected)
        facts = self.facts(selected)
        promoted_brands = {
            fact.canonical_value
            for fact in facts
            if fact.fact_type == "entity_brand_fact"
            and fact.decision_status == "promoted"
        }
        self.assertIn("momcozy", promoted_brands)
        self.assertIn("competitor", promoted_brands)
        receipt = self.validate(facts, [selected])
        self.assertEqual(receipt["unaccounted_fact_keys"], 0)


if __name__ == "__main__":
    unittest.main()
