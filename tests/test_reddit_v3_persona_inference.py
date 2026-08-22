from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_persona_inference import (
    PersonaInferenceError,
    build_cohort_assignments,
    canonical_json_bytes,
    canonical_persona_fact_jsonl_bytes,
    infer_persona_facts,
    load_persona_cohort_config,
    load_persona_dictionary,
)


ROOT = Path(__file__).resolve().parents[1]
DICTIONARY_PATH = ROOT / "data/reference/reddit-voc-v3/dim_persona_v1.csv"
COHORT_CONFIG_PATH = (
    ROOT / "config/personas/reddit-voc-persona-cohorts-v3.json"
)
SNAPSHOT_ID = "reddit_add_data_20260715_v1"


def _post(text: str, *, voc_id: str = "post:fixture") -> dict[str, object]:
    post_id = voc_id.split(":", 1)[1]
    return {
        "analysis_fields": {
            "current_comment_body": "",
            "post_body": text,
            "post_title": "",
        },
        "canonical_entity_id": f"t3_{post_id}",
        "comment_id": None,
        "post_id": post_id,
        "thread_id": f"t3_{post_id}",
        "voc_id": voc_id,
        "voc_type": "post_voc",
    }


def _comment(current: str, parent: str) -> dict[str, object]:
    return {
        "analysis_fields": {
            "current_comment_body": current,
            "post_body": parent,
            "post_title": "Parent title",
        },
        "canonical_entity_id": "t1_fixture",
        "comment_id": "fixture",
        "post_id": "root",
        "thread_id": "t3_root",
        "voc_id": "comment:fixture",
        "voc_type": "comment_context_voc",
    }


def _facts(voc: dict[str, object]):
    return infer_persona_facts(
        voc,
        dictionary=load_persona_dictionary(DICTIONARY_PATH),
        snapshot_id=SNAPSHOT_ID,
    )


def _fact_by_id(facts, persona_id: str):
    return next((fact for fact in facts if fact.persona_id == persona_id), None)


def _signal_evidence(
    voc: dict[str, object],
    *,
    fact_type: str,
    canonical_value: str,
    evidence_field: str,
    evidence_text: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    source = voc["analysis_fields"][evidence_field]
    start = source.index(evidence_text)
    end = start + len(evidence_text)
    evidence_hash = sha256(evidence_text.encode("utf-8")).hexdigest()
    is_parent_comment_evidence = (
        voc["voc_type"] == "comment_context_voc"
        and evidence_field in {"post_title", "post_body"}
    )
    fact: dict[str, object] = {
        "attributes": {},
        "canonical_entity_id": voc["canonical_entity_id"],
        "canonical_value": canonical_value,
        "context_evidence_refs": [],
        "created_at": "2026-07-16T00:00:00+00:00",
        "decision_status": "promoted",
        "dictionary_release_id": "fixture-governed-signal-dictionary",
        "evidence_end": end,
        "evidence_field": evidence_field,
        "evidence_scope": (
            "cross_context" if is_parent_comment_evidence else "direct"
        ),
        "evidence_source_entity_id": (
            f"t3_{voc['post_id']}"
            if is_parent_comment_evidence
            else voc["canonical_entity_id"]
        ),
        "evidence_start": start,
        "evidence_text_sha256": evidence_hash,
        "fact_id": "",
        "fact_type": fact_type,
        "matcher_version": "fixture-governed-signal-matcher",
        "normalizer_version": "source_codepoint_v1",
        "reason_codes": ["fixture_governed_signal"],
        "schema_version": "reddit_voc_atomic_fact_v2",
        "source_snapshot_id": SNAPSHOT_ID,
        "voc_id": voc["voc_id"],
        "voc_type": voc["voc_type"],
    }
    identity = dict(fact)
    identity.pop("fact_id")
    fact["fact_id"] = sha256(canonical_json_bytes(identity)).hexdigest()
    ref = {
        "canonical_value": canonical_value,
        "end": end,
        "evidence_field": evidence_field,
        "evidence_text_sha256": evidence_hash,
        "fact_type": fact_type,
        "source_fact_id": fact["fact_id"],
        "source_snapshot_id": SNAPSHOT_ID,
        "start": start,
    }
    return ref, {str(fact["fact_id"]): fact}


class PersonaInferenceTests(unittest.TestCase):
    def test_dictionary_is_exact_82_tag_closed_set(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        self.assertEqual(len(dictionary.definitions), 82)
        self.assertEqual(dictionary.keyword_instance_count, 454)
        self.assertEqual(dictionary.unique_keyword_count, 425)
        self.assertEqual(len(dictionary.shared_keywords), 28)
        self.assertEqual(dictionary.template_keyword_count, 5)
        self.assertEqual(
            dictionary.sha256,
            "279b313509141eb0f7432040818e261178fd9f75ec67a947a0cb9e6211799b1e",
        )

    def test_token_boundaries_and_comment_parent_do_not_infer_persona(self) -> None:
        facts = _facts(_post("A happy previous customer."))
        self.assertIsNone(_fact_by_id(facts, "PER-TECH-001"))
        self.assertIsNone(_fact_by_id(facts, "PER-EMOTION-013"))

        comment_facts = _facts(
            _comment("Which size should I choose?", "I am pregnant with my first baby.")
        )
        self.assertIsNone(_fact_by_id(comment_facts, "PER-WHO-003"))
        self.assertIsNone(_fact_by_id(comment_facts, "PER-WHO-001"))
        self.assertTrue(
            all(
                span.field == "current_comment_body"
                for fact in comment_facts
                for span in fact.evidence_spans
            )
        )

    def test_shared_only_is_held_but_independent_evidence_promotes(self) -> None:
        shared = _facts(_post("my newborn"))
        who001 = _fact_by_id(shared, "PER-WHO-001")
        who008 = _fact_by_id(shared, "PER-WHO-008")
        self.assertEqual(who001.decision_status, "held")
        self.assertEqual(who008.decision_status, "held")
        self.assertIn("ambiguous_shared_keyword", who001.decision_reason_codes)

        corroborated = _facts(_post("my newborn is my first baby"))
        who001 = _fact_by_id(corroborated, "PER-WHO-001")
        self.assertEqual(who001.decision_status, "promoted")
        self.assertEqual(str(who001.confidence), "0.90")
        self.assertEqual(who001.evidence_class, "A")

    def test_tech_mutual_exclusion_is_held_without_margin(self) -> None:
        conflict = _facts(_post("I use the app but don't need app."))
        tech001 = _fact_by_id(conflict, "PER-TECH-001")
        tech002 = _fact_by_id(conflict, "PER-TECH-002")
        self.assertEqual(tech001.decision_status, "held")
        self.assertEqual(tech002.decision_status, "held")
        self.assertIn("exclusive_conflict", tech001.decision_reason_codes)

        decisive = _facts(
            _post("I use the app, bluetooth and wifi, but don't need app.")
        )
        self.assertEqual(
            _fact_by_id(decisive, "PER-TECH-001").decision_status, "promoted"
        )
        self.assertEqual(
            _fact_by_id(decisive, "PER-TECH-002").decision_status, "held"
        )

    def test_normalization_masks_markup_and_replays_source_offsets(self) -> None:
        facts = _facts(_post("I am a new&nbsp;parent with my first\u00a0baby."))
        fact = _fact_by_id(facts, "PER-WHO-001")
        self.assertEqual(fact.decision_status, "promoted")
        evidence = {span.normalized_keyword: span for span in fact.evidence_spans}
        parent = evidence["new parent"]
        source = "I am a new&nbsp;parent with my first\u00a0baby."
        substring = source[parent.start : parent.end]
        self.assertEqual(substring, "new&nbsp;parent")
        self.assertEqual(
            parent.evidence_hash,
            sha256(
                (
                    f"post_body\x1f{parent.start}\x1f{parent.end}\x1f{substring}"
                ).encode("utf-8")
            ).hexdigest(),
        )

        masked = _facts(
            _post(
                "> first baby\n"
                "`new parent`\n"
                "https://example.com/first-baby\n"
                "```\nnewborn\n```"
            )
        )
        self.assertFalse(any(fact.decision_status == "promoted" for fact in masked))

        adversarial_markup = (
            "&gt; first baby and new parent",
            "``first baby and new parent``",
            "&#96;&#96;first baby and new parent&#96;&#96;",
            "https&#58;//example.com/first-baby/new-parent",
            "````\nfirst baby\n```\nnew parent and newborn",
        )
        for source in adversarial_markup:
            with self.subTest(source=source):
                fact = _fact_by_id(_facts(_post(source)), "PER-WHO-001")
                self.assertIsNone(fact)

        semicolonless = "new&nbsp parent"
        fact = _fact_by_id(_facts(_post(semicolonless)), "PER-WHO-001")
        self.assertEqual(fact.decision_status, "promoted")
        self.assertEqual(fact.matched_keywords, ("new parent",))
        self.assertEqual(
            semicolonless[fact.evidence_spans[0].start : fact.evidence_spans[0].end],
            semicolonless,
        )

        repeated = "first baby first&nbsp;baby"
        fact = _fact_by_id(_facts(_post(repeated)), "PER-WHO-001")
        self.assertEqual(fact.evidence_spans[0].start, 0)
        self.assertEqual(
            repeated[fact.evidence_spans[0].start : fact.evidence_spans[0].end],
            "first baby",
        )

    def test_template_expansion_and_b_only_cap_are_deterministic(self) -> None:
        expanded = _fact_by_id(
            _facts(_post("I had a spectra before.")), "PER-WHO-006"
        )
        self.assertEqual(expanded.decision_status, "promoted")
        self.assertEqual(expanded.matched_keywords, ("had a spectra before",))
        self.assertIsNone(
            _fact_by_id(_facts(_post("I had a brand before.")), "PER-WHO-006")
        )

        b_only = _fact_by_id(
            _facts(_post("aesthetic beautiful experience pleasure")),
            "PER-EMOTION-008",
        )
        self.assertEqual(b_only.decision_status, "held")
        self.assertEqual(b_only.evidence_class, "B")
        self.assertEqual(str(b_only.confidence), "0.75")
        self.assertEqual(len(b_only.matched_keywords), 4)

    def test_cohort_trigger_contract_and_automation_boundary(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        config = load_persona_cohort_config(
            COHORT_CONFIG_PATH,
            dictionary=dictionary,
        )
        voc = _post("I am pregnant and building my registry.")
        facts = infer_persona_facts(voc, dictionary=dictionary, snapshot_id=SNAPSHOT_ID)
        assignments = build_cohort_assignments(
            voc,
            facts=facts,
            config=config,
            signals={"topic_ids": [], "voc_tag_ids": []},
        )
        self.assertIn(
            "purchase_decision", {row.cohort_id for row in assignments}
        )

        operations = build_cohort_assignments(
            _post("I am a new parent."),
            facts=_facts(_post("I am a new parent.")),
            config=config,
            signals={"topic_ids": [], "problem_ids": [], "voc_tag_ids": []},
        )
        self.assertNotIn(
            "operations_troubleshooter", {row.cohort_id for row in operations}
        )

        recommendation_voc = _post("ordinary evidence")
        recommendation_ref, recommendation_registry = _signal_evidence(
            recommendation_voc,
            fact_type="entity_tag_fact",
            canonical_value="L0-GEN-103",
            evidence_field="post_body",
            evidence_text="ordinary evidence",
        )
        recommendation = build_cohort_assignments(
            recommendation_voc,
            facts=(),
            config=config,
            signals={
                "evidence_scope": ["post_body"],
                "signal_evidence_refs": [recommendation_ref],
                "snapshot_id": SNAPSHOT_ID,
                "voc_tag_ids": ["L0-GEN-103"],
            },
            governed_signal_facts_by_id=recommendation_registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        self.assertIn(
            "recommendation_expression",
            {row.cohort_id for row in recommendation},
        )
        excluded = build_cohort_assignments(
            voc,
            facts=facts,
            config=config,
            signals={"topic_ids": ["purchase_decision"]},
            explicit_automation=True,
        )
        self.assertEqual(excluded, ())

    def test_comment_cohort_requires_declared_current_body_evidence(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        config = load_persona_cohort_config(
            COHORT_CONFIG_PATH,
            dictionary=dictionary,
        )
        signal = {
            "snapshot_id": SNAPSHOT_ID,
            "voc_tag_ids": ["L0-GEN-103"],
        }
        with self.assertRaisesRegex(PersonaInferenceError, "evidence refs"):
            build_cohort_assignments(
                _comment("", "Parent-only context"),
                facts=(),
                config=config,
                signals=signal,
            )
        parent_only_voc = _comment("", "Parent-only context")
        parent_topic_ref, parent_topic_registry = _signal_evidence(
            parent_only_voc,
            fact_type="entity_tag_fact",
            canonical_value="purchase_decision",
            evidence_field="post_body",
            evidence_text="Parent-only context",
        )
        with self.assertRaisesRegex(PersonaInferenceError, "current-body"):
            build_cohort_assignments(
                parent_only_voc,
                facts=(),
                config=config,
                signals={
                    "evidence_scope": ["cross_context"],
                    "signal_evidence_refs": [parent_topic_ref],
                    "snapshot_id": SNAPSHOT_ID,
                    "topic_ids": ["purchase_decision"],
                },
                governed_signal_facts_by_id=parent_topic_registry,
                governed_source_snapshot_id=SNAPSHOT_ID,
            )

        comment_voc = _comment("I recommend this pump.", "Parent context")
        comment_ref, comment_registry = _signal_evidence(
            comment_voc,
            fact_type="entity_tag_fact",
            canonical_value="L0-GEN-103",
            evidence_field="current_comment_body",
            evidence_text="I recommend this pump.",
        )
        assignments = build_cohort_assignments(
            comment_voc,
            facts=(),
            config=config,
            signals={
                **signal,
                "evidence_scope": ["current_comment_body"],
                "signal_evidence_refs": [comment_ref],
            },
            governed_signal_facts_by_id=comment_registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        recommendation = next(
            row
            for row in assignments
            if row.cohort_id == "recommendation_expression"
        )
        self.assertEqual(recommendation.evidence_scope, ("current_comment_body",))

    def test_signal_values_require_replayable_identity_bound_refs(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        config = load_persona_cohort_config(
            COHORT_CONFIG_PATH,
            dictionary=dictionary,
        )
        voc = _post("Choosing a pump today.", voc_id="post:signal")
        signal = {
            "evidence_scope": ["post_body"],
            "snapshot_id": SNAPSHOT_ID,
            "topic_ids": ["purchase_decision"],
        }
        with self.assertRaisesRegex(PersonaInferenceError, "evidence refs"):
            build_cohort_assignments(
                voc,
                facts=(),
                config=config,
                signals=signal,
            )

        valid_ref, valid_registry = _signal_evidence(
            voc,
            fact_type="entity_tag_fact",
            canonical_value="purchase_decision",
            evidence_field="post_body",
            evidence_text="Choosing a pump today.",
        )
        assignments = build_cohort_assignments(
            voc,
            facts=(),
            config=config,
            signals={**signal, "signal_evidence_refs": [valid_ref]},
            governed_signal_facts_by_id=valid_registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        self.assertIn(
            "purchase_decision", {row.cohort_id for row in assignments}
        )

        with self.assertRaisesRegex(PersonaInferenceError, "governed fact registry"):
            build_cohort_assignments(
                voc,
                facts=(),
                config=config,
                signals={**signal, "signal_evidence_refs": [valid_ref]},
                governed_source_snapshot_id=SNAPSHOT_ID,
            )

        forged_ref = {**valid_ref, "source_fact_id": "0" * 64}
        with self.assertRaisesRegex(PersonaInferenceError, "governed signal fact"):
            build_cohort_assignments(
                voc,
                facts=(),
                config=config,
                signals={**signal, "signal_evidence_refs": [forged_ref]},
                governed_signal_facts_by_id=valid_registry,
                governed_source_snapshot_id=SNAPSHOT_ID,
            )

    def test_assignment_id_changes_when_governed_evidence_changes(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        config = load_persona_cohort_config(
            COHORT_CONFIG_PATH,
            dictionary=dictionary,
        )
        voc = _post(
            "Choosing a pump today. Choosing another pump today.",
            voc_id="post:assignment",
        )
        first_ref, first_registry = _signal_evidence(
            voc,
            fact_type="entity_tag_fact",
            canonical_value="purchase_decision",
            evidence_field="post_body",
            evidence_text="Choosing a pump today.",
        )
        second_ref, second_registry = _signal_evidence(
            voc,
            fact_type="entity_tag_fact",
            canonical_value="purchase_decision",
            evidence_field="post_body",
            evidence_text="Choosing another pump today.",
        )
        common_signals = {
            "evidence_scope": ["post_body"],
            "snapshot_id": SNAPSHOT_ID,
            "topic_ids": ["purchase_decision"],
        }
        first = build_cohort_assignments(
            voc,
            facts=(),
            config=config,
            signals={**common_signals, "signal_evidence_refs": [first_ref]},
            governed_signal_facts_by_id=first_registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        second = build_cohort_assignments(
            voc,
            facts=(),
            config=config,
            signals={**common_signals, "signal_evidence_refs": [second_ref]},
            governed_signal_facts_by_id=second_registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        first_purchase = next(
            row for row in first if row.cohort_id == "purchase_decision"
        )
        second_purchase = next(
            row for row in second if row.cohort_id == "purchase_decision"
        )
        self.assertNotEqual(
            first_purchase.assignment_id,
            second_purchase.assignment_id,
        )

    def test_persona_and_governed_source_snapshot_ids_are_independent(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        config = load_persona_cohort_config(
            COHORT_CONFIG_PATH,
            dictionary=dictionary,
        )
        persona_snapshot_id = "reddit_voc_personas_fixture_a4"
        voc = _post("Choosing a pump today.", voc_id="post:separatelineage")
        ref, registry = _signal_evidence(
            voc,
            fact_type="entity_tag_fact",
            canonical_value="purchase_decision",
            evidence_field="post_body",
            evidence_text="Choosing a pump today.",
        )
        assignments = build_cohort_assignments(
            voc,
            facts=(),
            config=config,
            signals={
                "evidence_scope": ["post_body"],
                "signal_evidence_refs": [ref],
                "snapshot_id": persona_snapshot_id,
                "topic_ids": ["purchase_decision"],
            },
            governed_signal_facts_by_id=registry,
            governed_source_snapshot_id=SNAPSHOT_ID,
        )
        self.assertTrue(assignments)
        self.assertTrue(
            all(row.snapshot_id == persona_snapshot_id for row in assignments)
        )
        with self.assertRaisesRegex(PersonaInferenceError, "source snapshot"):
            build_cohort_assignments(
                voc,
                facts=(),
                config=config,
                signals={
                    "evidence_scope": ["post_body"],
                    "signal_evidence_refs": [ref],
                    "snapshot_id": persona_snapshot_id,
                    "topic_ids": ["purchase_decision"],
                },
                governed_signal_facts_by_id=registry,
                governed_source_snapshot_id=persona_snapshot_id,
            )

    def test_empty_trigger_paths_and_forged_fact_provenance_fail_closed(self) -> None:
        dictionary = load_persona_dictionary(DICTIONARY_PATH)
        config = load_persona_cohort_config(
            COHORT_CONFIG_PATH,
            dictionary=dictionary,
        )
        config_value = json.loads(COHORT_CONFIG_PATH.read_text(encoding="utf-8"))
        empty_path = {
            "path_id": "empty",
            "required_brand_roles_any": [],
            "required_problem_ids_any": [],
            "required_scenario_ids_any": [],
            "required_topic_ids_any": [],
            "required_voc_tag_ids_any": [],
            "requires_bridge_match": False,
        }
        for trigger_path in ({}, empty_path):
            with self.subTest(trigger_path=trigger_path):
                mutated = json.loads(json.dumps(config_value))
                mutated["cohorts"][0]["trigger_paths"] = [trigger_path]
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "cohorts.json"
                    path.write_text(
                        json.dumps(
                            mutated,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        PersonaInferenceError, "trigger path"
                    ):
                        load_persona_cohort_config(path, dictionary=dictionary)

        voc = _post("I am pregnant and building my registry.")
        fact = next(
            row
            for row in infer_persona_facts(
                voc,
                dictionary=dictionary,
                snapshot_id=SNAPSHOT_ID,
            )
            if row.persona_id == "PER-WHO-003"
        )
        forged = replace(fact, dictionary_sha256="0" * 64)
        with self.assertRaisesRegex(PersonaInferenceError, "provenance"):
            build_cohort_assignments(
                voc,
                facts=(forged,),
                config=config,
                signals={},
            )
        with self.assertRaisesRegex(PersonaInferenceError, "duplicate"):
            build_cohort_assignments(
                voc,
                facts=(fact, fact),
                config=config,
                signals={},
            )
        with self.assertRaisesRegex(PersonaInferenceError, "duplicate"):
            canonical_persona_fact_jsonl_bytes((fact, fact))

        mismatched = _post("new parent", voc_id="post:one")
        mismatched["canonical_entity_id"] = "t3_other"
        with self.assertRaisesRegex(PersonaInferenceError, "identity mismatch"):
            infer_persona_facts(
                mismatched,
                dictionary=dictionary,
                snapshot_id=SNAPSHOT_ID,
            )

    def test_fact_bytes_are_input_order_independent(self) -> None:
        facts = _facts(_post("my first baby and new parent experience"))
        self.assertEqual(
            canonical_persona_fact_jsonl_bytes(facts),
            canonical_persona_fact_jsonl_bytes(reversed(facts)),
        )
        with self.assertRaisesRegex(PersonaInferenceError, "dictionary"):
            load_persona_dictionary(ROOT / "dim_tag_v6.3_final.csv")


if __name__ == "__main__":
    unittest.main()
