from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import unittest

from reddit_voc.v3_atomic_facts import (
    ATOMIC_FACT_SCHEMA_VERSION,
    ATOMIC_FACT_TYPES,
    DEFAULT_DICTIONARY_RELEASE_ID,
    DEFAULT_MATCHER_VERSION,
    FULL_CORPUS_ATOMIC_FACT_MATCHER_IMPLEMENTED,
    IMPLEMENTATION_SCOPE,
    NORMALIZER_VERSION,
    AtomicFact,
    AtomicFactError,
    build_atomic_facts,
    build_external_reference_atomic_facts,
    canonical_atomic_fact_jsonl_bytes,
    canonical_json_bytes,
    governance_regression_coverage,
    group_atomic_fact_tables,
    validate_atomic_facts,
    validate_external_reference_atomic_facts,
)


ROOT = Path(__file__).resolve().parents[1]
VOCS_PATH = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
    / "voc-facts-candidate-a1/vocs.jsonl"
)
GOVERNANCE_VOC_IDS = {
    "post:1kkvihg",
    "post:1l2aofi",
    "post:1n2q1do",
    "post:1o1pqox",
    "comment:mrxlcx3",
    "comment:mrxqx1g",
    "comment:mrxu2ve",
}
SOURCE_SNAPSHOT_ID = "reddit_add_data_20260715_v1"
CREATED_AT = "2026-07-16T00:00:00+00:00"
EXTERNAL_POST_BODY = (
    "Just a heads up that Momcozy is at it again in the community, using AI bots "
    "and bogus accounts to shill their products. Thanks to those that have been "
    "reporting them, the accounts have been banned, but to be frank it is an "
    "alarming number. Please continue to report suspicious content."
)


def _external_snapshot() -> dict[str, object]:
    return {
        "canonical_task4_row": False,
        "flair_text": "MOD RANT/ANNOUNCEMENT ETC",
        "pii_fields_collected": False,
        "post_body": EXTERNAL_POST_BODY,
        "reddit_post_id": "1u2gvn4",
        "schema_version": "reddit_voc_external_public_post_snapshot_v1",
        "source_role": "external_public_reference_noncanonical",
        "subreddit": "ExclusivelyPumping",
        "title": "Momcozy is at it again",
    }


def _governance_vocs() -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for line in VOCS_PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["voc_id"] in GOVERNANCE_VOC_IDS:
            values[row["voc_id"]] = row
    return values


def _facts(voc: dict[str, object]):
    return build_atomic_facts(
        voc,
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        created_at=CREATED_AT,
    )


def _validate(
    facts: list[AtomicFact] | tuple[AtomicFact, ...],
    vocs: dict[str, dict[str, object]],
) -> None:
    validate_atomic_facts(
        facts,
        vocs,
        source_snapshot_id=SOURCE_SNAPSHOT_ID,
        created_at=CREATED_AT,
    )


def _reforge(fact: AtomicFact, **changes: object) -> AtomicFact:
    candidate = replace(fact, fact_id="", **changes)
    payload = candidate.as_dict()
    payload.pop("fact_id")
    return replace(
        candidate,
        fact_id=sha256(canonical_json_bytes(payload)).hexdigest(),
    )


def _promoted(facts, canonical_value: str) -> bool:
    return any(
        fact.canonical_value == canonical_value
        and fact.decision_status == "promoted"
        for fact in facts
    )


class AtomicFactsTests(unittest.TestCase):
    def test_module_scope_is_fixed_governance_regression_only(self) -> None:
        self.assertEqual(
            IMPLEMENTATION_SCOPE,
            "fixed_governance_regression_only",
        )
        self.assertFalse(FULL_CORPUS_ATOMIC_FACT_MATCHER_IMPLEMENTED)

    def test_keep_coming_back_is_not_consumer_repurchase(self) -> None:
        facts = _facts(_governance_vocs()["post:1kkvihg"])
        self.assertFalse(_promoted(facts, "explicit_recommendation"))
        self.assertTrue(_promoted(facts, "integrity_allegation"))
        self.assertTrue(_promoted(facts, "moderation_warning"))
        self.assertFalse(_promoted(facts, "consumer_trust_impact"))
        rejected = [
            fact for fact in facts if fact.canonical_value == "repurchase_signal"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].decision_status, "rejected")
        self.assertIn("speaker_target_mismatch", rejected[0].reason_codes)

    def test_governance_set_has_four_replayable_roots_and_one_missing_root(self) -> None:
        vocs = _governance_vocs()
        coverage = governance_regression_coverage(vocs.values())
        self.assertEqual(
            coverage,
            {
                "available_root_voc_ids": [
                    "post:1kkvihg",
                    "post:1l2aofi",
                    "post:1n2q1do",
                    "post:1o1pqox",
                ],
                "incomplete_root_voc_ids": [],
                "missing_root_voc_ids": ["post:1u2gvn4"],
                "status_by_root_voc_id": {
                    "post:1kkvihg": "replayable",
                    "post:1l2aofi": "replayable",
                    "post:1n2q1do": "replayable",
                    "post:1o1pqox": "replayable",
                    "post:1u2gvn4": "canonical_root_missing",
                },
            },
        )

    def test_governance_coverage_requires_evidence_replay(self) -> None:
        vocs = _governance_vocs()
        tampered = deepcopy(vocs)
        tampered["post:1kkvihg"]["analysis_fields"]["post_body"] = (
            tampered["post:1kkvihg"]["analysis_fields"]["post_body"].replace(
                "Momcozy sends employees/planted users in here",
                "Momcozy was discussed in here",
            )
        )
        coverage = governance_regression_coverage(tampered.values())
        self.assertEqual(
            coverage["status_by_root_voc_id"]["post:1kkvihg"],
            "evidence_incomplete",
        )
        self.assertNotIn(
            "post:1kkvihg",
            coverage["available_root_voc_ids"],
        )
        self.assertIn(
            "post:1kkvihg",
            coverage["incomplete_root_voc_ids"],
        )

    def test_external_reference_facts_use_complete_body_exact_spans(self) -> None:
        snapshot = _external_snapshot()
        facts = build_external_reference_atomic_facts(
            snapshot,
            source_snapshot_id="case-reference:test",
            created_at=CREATED_AT,
        )
        expected = {
            "ai_bot_allegation": (
                68,
                75,
                "d03ff60fe383cde89873086a0d81fab507df453c8d4dda8026997a8244dd8078",
            ),
            "bogus_account_allegation": (
                80,
                94,
                "239e8fc4e3a21c6385bd8639b6251be571bc2fef27db7bf30d0dd2370251e1d3",
            ),
            "account_ban_action": (
                171,
                196,
                "f1b944e0807b4572d5610e2c73358516dbdccdadd85c52014cccd4524994c2d5",
            ),
        }
        self.assertEqual(len(facts), 3)
        for fact in facts:
            self.assertEqual(fact.evidence_field, "post_body")
            self.assertEqual(
                (
                    fact.evidence_start,
                    fact.evidence_end,
                    fact.evidence_text_sha256,
                ),
                expected[fact.canonical_value],
            )
        validate_external_reference_atomic_facts(
            facts,
            snapshot,
            source_snapshot_id="case-reference:test",
            created_at=CREATED_AT,
        )
        coverage = governance_regression_coverage(
            _governance_vocs().values(), external_references=[snapshot]
        )
        self.assertEqual(
            coverage["status_by_root_voc_id"]["post:1u2gvn4"],
            "replayable_external_reference",
        )
        tampered = deepcopy(snapshot)
        tampered["post_body"] = str(tampered["post_body"]).replace(
            "AI bots", "automated accounts"
        )
        with self.assertRaises(AtomicFactError):
            build_external_reference_atomic_facts(
                tampered,
                source_snapshot_id="case-reference:test",
                created_at=CREATED_AT,
            )

    def test_fixed_comment_facts_use_current_body_exact_spans(self) -> None:
        vocs = _governance_vocs()
        expected = {
            "comment:mrxlcx3": {
                "integrity_allegation": (
                    28,
                    72,
                    "a65ac5e4d1ce6f6f17a378c9cddc17221834dd84f4e688b97645b0ce14ab6cb6",
                )
            },
            "comment:mrxqx1g": {
                "past_purchase_decision": (
                    27,
                    75,
                    "feb1b2e7b7dc370e5ded6bdb055030adf5deef537e0edf6377907d29561ab6f2",
                ),
                "consumer_trust_impact": (
                    88,
                    116,
                    "0d2450d8248ade89d4448914d60b363d753f885f79db421ec709476159a003ac",
                ),
            },
            "comment:mrxu2ve": {
                "consumer_trust_impact": (
                    62,
                    156,
                    "7aa000f5ff5c22b226f0623a4f6f6cf3b5aaa61ee058b3dbc1c83ce0afb5feed",
                ),
                "purchase_avoidance": (
                    158,
                    205,
                    "f0c88f4cb924a7ef65067ce7c98b5e9b7378aff28186ec1c6af2ec2f568efbf5",
                ),
            },
        }
        for voc_id, facts_expected in expected.items():
            facts = _facts(vocs[voc_id])
            by_value = {
                fact.canonical_value: fact
                for fact in facts
                if fact.canonical_value in facts_expected
            }
            self.assertEqual(set(by_value), set(facts_expected))
            for value, (start, end, digest) in facts_expected.items():
                fact = by_value[value]
                self.assertEqual(fact.decision_status, "promoted")
                self.assertEqual(fact.evidence_field, "current_comment_body")
                self.assertEqual((fact.evidence_start, fact.evidence_end), (start, end))
                self.assertEqual(fact.evidence_text_sha256, digest)
            if voc_id == "comment:mrxlcx3":
                self.assertFalse(_promoted(facts, "consumer_trust_impact"))

    def test_parent_only_integrity_text_does_not_create_comment_fact(self) -> None:
        fixture = {
            "analysis_fields": {
                "current_comment_body": "Which size should I choose?",
                "post_body": "The moderator alleges fake reviews and planted users.",
                "post_title": "Warning",
            },
            "analysis_text_status": "ready",
            "canonical_entity_id": "t1_fixture",
            "comment_id": "fixture",
            "comment_context_id": "root:fixture",
            "context_status": "ready",
            "metric_distinct_key": "fixture",
            "post_id": "root",
            "schema_version": "reddit_voc_fielded_voc_v1",
            "thread_id": "root",
            "voc_id": "comment:fixture",
            "voc_type": "comment_context_voc",
        }
        facts = _facts(fixture)
        self.assertFalse(_promoted(facts, "integrity_allegation"))
        self.assertTrue(
            all(fact.evidence_field == "current_comment_body" for fact in facts)
        )

    def test_voc_identity_spoofs_are_rejected(self) -> None:
        vocs = _governance_vocs()
        post_cases = {
            "canonical_entity_id": ("canonical_entity_id", "t3_spoof"),
            "post_id": ("post_id", "spoof"),
            "thread_id": ("thread_id", "spoof"),
            "metric_distinct_key": ("metric_distinct_key", "spoof"),
            "schema_version": ("schema_version", "reddit_voc_fielded_voc_v2"),
        }
        for label, (field, value) in post_cases.items():
            with self.subTest(voc_type="post", field=label):
                spoof = deepcopy(vocs["post:1kkvihg"])
                spoof[field] = value
                with self.assertRaises(AtomicFactError):
                    _facts(spoof)

        comment_cases = {
            "canonical_entity_id": ("canonical_entity_id", "t1_spoof"),
            "comment_id": ("comment_id", "spoof"),
            "post_id": ("post_id", "spoof"),
            "thread_id": ("thread_id", "spoof"),
            "metric_distinct_key": ("metric_distinct_key", "spoof"),
            "comment_context_id": ("comment_context_id", "spoof:spoof"),
            "schema_version": ("schema_version", "reddit_voc_fielded_voc_v2"),
        }
        for label, (field, value) in comment_cases.items():
            with self.subTest(voc_type="comment", field=label):
                spoof = deepcopy(vocs["comment:mrxqx1g"])
                spoof[field] = value
                with self.assertRaises(AtomicFactError):
                    _facts(spoof)

    def test_behavior_observations_are_integrity_signals_not_dictionary_tags(self) -> None:
        facts = tuple(
            fact
            for voc in _governance_vocs().values()
            for fact in _facts(voc)
        )
        observations = {
            "repurchase_signal",
            "past_purchase_decision",
            "purchase_avoidance",
        }
        matched = [fact for fact in facts if fact.canonical_value in observations]
        self.assertEqual({fact.canonical_value for fact in matched}, observations)
        self.assertTrue(
            all(fact.fact_type == "integrity_signal_fact" for fact in matched)
        )
        self.assertFalse(any(fact.fact_type == "entity_tag_fact" for fact in facts))

        integrity_allegations = [
            fact
            for fact in facts
            if fact.canonical_value
            in {"integrity_allegation", "fake_review_allegation"}
        ]
        self.assertTrue(integrity_allegations)
        self.assertTrue(
            all(fact.attributes.get("signal_class") == "I1" for fact in integrity_allegations)
        )
        self.assertTrue(
            all(
                fact.attributes.get("event_aggregation_required") is True
                for fact in integrity_allegations
            )
        )
        commercial = [
            fact
            for fact in facts
            if fact.canonical_value == "creator_payment_allegation"
        ]
        self.assertEqual(len(commercial), 1)
        self.assertEqual(
            commercial[0].attributes.get("commercial_confidence_level"),
            "C1",
        )

    def test_fact_id_covers_semantics_and_provenance(self) -> None:
        fact = next(
            item
            for item in _facts(_governance_vocs()["post:1o1pqox"])
            if item.canonical_value == "creator_payment_allegation"
        )
        mutations = (
            {"attributes": {"commercial_confidence_level": "C3"}},
            {"canonical_value": "confirmed_improper_intervention"},
            {"decision_status": "held"},
            {"reason_codes": ("different_reason",)},
            {"dictionary_release_id": "dictionary@other"},
            {"matcher_version": "matcher_other"},
            {"normalizer_version": "normalizer_other"},
            {"source_snapshot_id": "snapshot_other"},
            {"created_at": "2026-07-16T00:00:01+00:00"},
            {"schema_version": "reddit_voc_atomic_fact_other"},
            {"evidence_scope": "context"},
        )
        for changes in mutations:
            with self.subTest(changes=changes):
                self.assertNotEqual(_reforge(fact, **changes).fact_id, fact.fact_id)

    def test_semantic_attribute_and_provenance_tampering_is_rejected(self) -> None:
        voc = _governance_vocs()["post:1o1pqox"]
        facts = list(_facts(voc))
        commercial_index = next(
            index
            for index, fact in enumerate(facts)
            if fact.canonical_value == "creator_payment_allegation"
        )
        integrity_index = next(
            index
            for index, fact in enumerate(facts)
            if fact.canonical_value == "integrity_allegation"
        )
        cases = (
            (
                commercial_index,
                {"attributes": {"commercial_confidence_level": "C3"}},
                "do not match",
            ),
            (
                integrity_index,
                {"attributes": {"signal_class": "I4"}},
                "do not match",
            ),
            (
                commercial_index,
                {"dictionary_release_id": "dictionary@other"},
                "provenance",
            ),
            (
                commercial_index,
                {"source_snapshot_id": "snapshot_other"},
                "provenance",
            ),
            (
                commercial_index,
                {"matcher_version": "matcher_other"},
                "provenance",
            ),
            (
                commercial_index,
                {"normalizer_version": "normalizer_other"},
                "provenance",
            ),
            (
                commercial_index,
                {"created_at": "2026-07-16T00:00:01+00:00"},
                "provenance",
            ),
            (
                commercial_index,
                {"schema_version": "reddit_voc_atomic_fact_other"},
                "schema",
            ),
            (
                commercial_index,
                {"reason_codes": ("fabricated_reason",)},
                "do not match",
            ),
        )
        for index, changes, message in cases:
            with self.subTest(changes=changes):
                tampered = list(facts)
                tampered[index] = _reforge(tampered[index], **changes)
                with self.assertRaisesRegex(AtomicFactError, message):
                    _validate(tampered, {str(voc["voc_id"]): voc})

    def test_arbitrary_promoted_integrity_conclusion_is_rejected(self) -> None:
        voc = _governance_vocs()["post:1o1pqox"]
        facts = list(_facts(voc))
        index = next(
            index
            for index, fact in enumerate(facts)
            if fact.canonical_value == "creator_payment_allegation"
        )
        facts[index] = _reforge(
            facts[index],
            fact_type="integrity_signal_fact",
            canonical_value="confirmed_improper_intervention",
            attributes={
                "brand_attribution": "confirmed",
                "integrity_level": "I4",
            },
            decision_status="promoted",
        )
        with self.assertRaisesRegex(AtomicFactError, "do not match"):
            _validate(facts, {str(voc["voc_id"]): voc})

    def test_nine_tables_stable_bytes_and_tamper_replay(self) -> None:
        vocs = _governance_vocs()
        facts = tuple(
            fact
            for voc_id in sorted(vocs, reverse=True)
            for fact in _facts(vocs[voc_id])
        )
        tables = group_atomic_fact_tables(facts)
        self.assertEqual(set(tables), set(ATOMIC_FACT_TYPES))
        payload = canonical_atomic_fact_jsonl_bytes(facts)
        reversed_payload = canonical_atomic_fact_jsonl_bytes(reversed(facts))
        self.assertEqual(payload, reversed_payload)
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(len({fact.fact_id for fact in facts}), len(facts))
        _validate(facts, vocs)

        tampered = deepcopy(vocs)
        original = tampered["comment:mrxqx1g"]["analysis_fields"][
            "current_comment_body"
        ]
        tampered["comment:mrxqx1g"]["analysis_fields"][
            "current_comment_body"
        ] = original.replace("legitimacy", "validity")
        with self.assertRaisesRegex(AtomicFactError, "evidence"):
            _validate(facts, tampered)

        self.assertEqual(
            sha256(payload).hexdigest(),
            sha256(reversed_payload).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
