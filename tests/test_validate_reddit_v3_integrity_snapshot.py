from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_integrity_snapshot import (
    BOUNDARIES,
    EVENT_ROOT_SCHEMA,
    OBSERVATION_SCHEMA,
    IntegritySnapshotError,
    canonical_json_bytes,
    canonical_json_document,
    canonical_jsonl,
    load_frozen_governed_inputs,
    _validate_observation,
)
from scripts.build_reddit_v3_integrity_snapshot import build_formal_candidate
from scripts.validate_reddit_v3_integrity_snapshot import (
    validate_integrity_snapshot,
    write_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/analytics/reddit-voc-content-integrity-v1.json"
REAL_GOVERNED_ROOT = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/governed-signals-candidate-a1"
)
REAL_GOVERNED_RECEIPT = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/governed-signals-validation-a1/receipt.json"
)
POST_IDS = ("1kkvihg", "1l2aofi", "1n2q1do", "1o1pqox", "1u2gvn4")


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _fact(
    entity_id: str,
    *,
    fact_type: str = "integrity_signal_fact",
    canonical_value: str = "governed_integrity_observation",
    attributes: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "attributes": attributes or {},
        "canonical_entity_id": entity_id,
        "canonical_value": canonical_value,
        "decision_status": "promoted",
        "fact_type": fact_type,
        "schema_version": "reddit_voc_atomic_fact_v2",
        **extra,
    }
    return {**row, "fact_id": _sha(canonical_json_bytes(row))}


def _observation(
    entity_id: str,
    evidence_id: str | list[str],
    *,
    cluster_key: str | None,
    **classification: object,
) -> dict[str, object]:
    evidence_ids = sorted([evidence_id] if isinstance(evidence_id, str) else evidence_id)
    if "signal_types" in classification:
        classification["signal_types"] = sorted(classification["signal_types"])
    return {
        "classification_input": {
            "entity_id": entity_id,
            "evidence_ids": evidence_ids,
            **classification,
        },
        "cluster_key": cluster_key,
        "entity_id": entity_id,
        "evidence_ids": evidence_ids,
        "schema_version": OBSERVATION_SCHEMA,
    }


def _contract(payload: bytes) -> dict[str, object]:
    return {
        "bytes": len(payload),
        "rows": len(payload.splitlines()),
        "sha256": _sha(payload),
    }


def _write_upstream(root: Path, *, frozen: bool = True, include_last_root: bool = True) -> Path:
    root.mkdir()
    event_facts = [
        _fact(
            (
                f"external_reddit_post:{post_id}"
                if post_id == "1u2gvn4"
                else f"t3_{post_id}"
            ),
            fact_type="community_governance_fact",
            canonical_value="subreddit_moderator_action",
            attributes={
                "authority": "subreddit_moderator",
                **(
                    {
                        "brand_control_confirmed": False,
                        "source_role": "external_public_reference_noncanonical",
                    }
                    if post_id == "1u2gvn4"
                    else {}
                ),
                "integrity_classification": {
                    "governance_authority": "subreddit_moderator",
                    "public_governance_action": True,
                    "signal_types": ["content"],
                },
            },
            **(
                {
                    "voc_id": "external-post:1u2gvn4",
                    "voc_type": "external_public_reference",
                }
                if post_id == "1u2gvn4"
                else {}
            ),
        )
        for post_id in POST_IDS
    ]
    other_facts = [
        _fact(
            "t1_bot",
            canonical_value="explicit_automation",
            attributes={
                "integrity_classification": {
                    "explicit_automation": True,
                    "signal_types": ["behavior", "content", "link"],
                }
            },
        ),
        _fact(
            "t3_affiliate",
            fact_type="commercial_relation_fact",
            canonical_value="affiliate_disclosure",
            attributes={
                "integrity_classification": {
                    "commercial_disclosure": "affiliate"
                }
            },
        ),
        _fact(
            "t3_affiliate",
            canonical_value="ai_style_signal",
            attributes={
                "integrity_classification": {
                    "ai_style_signal": True,
                    "signal_types": ["content"],
                }
            },
        ),
        _fact(
            "t3_pattern",
            canonical_value="repeated_propagation_pattern",
            attributes={
                "integrity_classification": {
                    "repeated_propagation_pattern": True,
                    "signal_types": ["behavior", "content"],
                }
            },
        ),
        _fact(
            "t3_confirmed",
            fact_type="commercial_relation_fact",
            canonical_value="brand_attribution_confirmed",
            attributes={
                "attribution_provenance_id": "fixture-attribution-review",
                "integrity_classification": {
                    "brand_attribution_confirmed": True
                },
            },
        ),
        _fact(
            "t3_confirmed",
            canonical_value="manual_rule_violation_confirmed",
            attributes={
                "integrity_classification": {
                    "manual_rule_violation_confirmed": True,
                    "signal_types": ["behavior", "content"],
                },
                "review_provenance_id": "fixture-rule-review",
            },
        ),
    ]
    facts = sorted(event_facts + other_facts, key=lambda row: str(row["fact_id"]))
    event_by_entity = {row["canonical_entity_id"]: row for row in event_facts}
    other_by_entity: dict[str, list[dict[str, object]]] = {}
    for row in other_facts:
        other_by_entity.setdefault(str(row["canonical_entity_id"]), []).append(row)
    observations = [
        _observation(
            "t1_bot",
            str(other_by_entity["t1_bot"][0]["fact_id"]),
            cluster_key=None,
            explicit_automation=True,
            signal_types=["content", "behavior", "link"],
        ),
        _observation(
            "t3_affiliate",
            [str(row["fact_id"]) for row in other_by_entity["t3_affiliate"]],
            cluster_key=None,
            ai_style_signal=True,
            commercial_disclosure="affiliate",
            signal_types=["content"],
        ),
        _observation(
            "t3_pattern",
            str(other_by_entity["t3_pattern"][0]["fact_id"]),
            cluster_key="shared-template-a",
            repeated_propagation_pattern=True,
            signal_types=["content", "behavior"],
        ),
        _observation(
            "t3_1kkvihg",
            str(event_by_entity["t3_1kkvihg"]["fact_id"]),
            cluster_key="moderator-event",
            governance_authority="subreddit_moderator",
            public_governance_action=True,
            signal_types=["content"],
        ),
        _observation(
            "t3_confirmed",
            [str(row["fact_id"]) for row in other_by_entity["t3_confirmed"]],
            cluster_key="confirmed-fixture",
            brand_attribution_confirmed=True,
            manual_rule_violation_confirmed=True,
            signal_types=["content", "behavior"],
        ),
    ]
    observations.sort(key=lambda row: str(row["entity_id"]))
    event_roots = [
        {
            "authority": "subreddit_moderator",
            "evidence_id": row["fact_id"],
            "post_id": post_id,
            "schema_version": EVENT_ROOT_SCHEMA,
        }
        for post_id, row in zip(POST_IDS, event_facts, strict=True)
    ]
    if not include_last_root:
        event_roots.pop()
    payloads = {
        "governed-facts.jsonl": canonical_jsonl(facts),
        "integrity-observations.jsonl": canonical_jsonl(observations),
        "event-roots.jsonl": canonical_jsonl(event_roots),
    }
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)
    policy_sha = _sha(POLICY.read_bytes())
    manifest = {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "ready" if frozen else "blocked_pending_atomic_facts",
        "files": {name: _contract(payload) for name, payload in sorted(payloads.items())},
        "policy_sha256": policy_sha,
        "promotable": frozen,
        "schema_version": "reddit_voc_governed_integrity_inputs_manifest_v1",
        "source_snapshot_id": "reddit_voc_integrity_fixture_source_v1",
        "status": "frozen" if frozen else "candidate_built",
    }
    manifest_payload = canonical_json_document(manifest)
    (root / "manifest.json").write_bytes(manifest_payload)
    receipt = {
        "boundaries": dict(BOUNDARIES),
        "consumption_status": "ready" if frozen else "blocked_pending_atomic_facts",
        "promotable": frozen,
        "schema_version": "reddit_voc_governed_integrity_inputs_validation_receipt_v1",
        "status": "passed",
        "upstream_manifest_sha256": _sha(manifest_payload),
    }
    receipt_path = root.parent / f"{root.name}-receipt.json"
    receipt_path.write_bytes(canonical_json_document(receipt))
    return receipt_path


class IntegritySnapshotValidationTests(unittest.TestCase):
    def _build(self, temporary: str) -> tuple[Path, Path, Path, str]:
        base = Path(temporary)
        upstream = base / "upstream"
        receipt = _write_upstream(upstream)
        output = base / "integrity-candidate"
        result = build_formal_candidate(
            upstream_root=upstream,
            upstream_receipt_path=receipt,
            policy_path=POLICY,
            output_dir=output,
            snapshot_id="reddit_voc_integrity_fixture_candidate_v1",
            generated_at_utc="2026-07-16T00:00:00+00:00",
        )
        return upstream, receipt, output, str(result["integrity_manifest_sha256"])

    def test_snapshot_replays_all_levels_fixed_event_lifecycle_and_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream, upstream_receipt, output, manifest_sha = self._build(temporary)
            result = validate_integrity_snapshot(
                snapshot_dir=output,
                expected_manifest_sha256=manifest_sha,
                upstream_root=upstream,
                upstream_receipt_path=upstream_receipt,
                policy_path=POLICY,
            )
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["promotable"])
            self.assertEqual(
                result["level_counts"],
                {
                    "C0": 2,
                    "C1": 1,
                    "C2": 1,
                    "C3": 1,
                    "I0": 1,
                    "I1": 1,
                    "I2": 1,
                    "I3": 1,
                    "I4": 1,
                },
            )
            event = json.loads((output / "event-dossiers.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event["post_ids"], list(POST_IDS))
            self.assertEqual(
                (event["commercial_relation"], event["integrity_level"]),
                ("C2", "I3"),
            )
            self.assertEqual(event["governance_authority"], "subreddit_moderator")
            self.assertFalse(event["brand_control_confirmed"])
            sensitivity = json.loads((output / "sensitivity.json").read_text(encoding="utf-8"))
            self.assertEqual(sensitivity["raw_observed_metric_eligible_entity_count"], 4)
            self.assertEqual(sensitivity["qualified_organic_entity_count"], 3)
            self.assertEqual(sensitivity["c3_i4_excluded_entity_count"], 1)
            self.assertEqual(
                sensitivity["explicit_automation_baseline_excluded_entity_count"], 1
            )
            lifecycle = json.loads((output / "lifecycle.json").read_text(encoding="utf-8"))
            self.assertIn("unanswered", lifecycle["response_transitions"])
            self.assertIn("queued", lifecycle["review_transitions"])
            receipt_path = Path(temporary) / "validation" / "receipt.json"
            self.assertEqual(write_receipt(receipt_path, result), "created")
            self.assertEqual(write_receipt(receipt_path, result), "no_change")

    def test_semantic_tamper_fails_even_if_attacker_rehashes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream, upstream_receipt, output, _manifest_sha = self._build(temporary)
            event_path = output / "event-dossiers.jsonl"
            event = json.loads(event_path.read_text(encoding="utf-8"))
            event["integrity_level"] = "I4"
            payload = canonical_jsonl([event])
            event_path.write_bytes(payload)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["event-dossiers.jsonl"].update(
                {"bytes": len(payload), "rows": 1, "sha256": _sha(payload)}
            )
            manifest_payload = canonical_json_document(manifest)
            manifest_path.write_bytes(manifest_payload)
            with self.assertRaisesRegex(IntegritySnapshotError, "semantic replay"):
                validate_integrity_snapshot(
                    snapshot_dir=output,
                    expected_manifest_sha256=_sha(manifest_payload),
                    upstream_root=upstream,
                    upstream_receipt_path=upstream_receipt,
                    policy_path=POLICY,
                )

    def test_blocked_upstream_and_missing_fifth_root_fail_closed(self) -> None:
        for frozen, include_last_root, message in (
            (False, True, "not frozen and promotable"),
            (True, False, "incomplete"),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                upstream = Path(temporary) / "upstream"
                receipt = _write_upstream(
                    upstream, frozen=frozen, include_last_root=include_last_root
                )
                with self.assertRaisesRegex(IntegritySnapshotError, message):
                    load_frozen_governed_inputs(
                        upstream_root=upstream,
                        upstream_receipt_path=receipt,
                        policy_path=POLICY,
                    )

    def test_affiliate_registry_relation_does_not_claim_brand_control(self) -> None:
        from reddit_voc.v3_content_integrity import classify_integrity

        result = classify_integrity(
            {
                "affiliate_registry_bound": True,
                "entity_id": "t3_affiliate_registry",
                "evidence_ids": ["fact"],
                "signal_types": ["link"],
            }
        )
        self.assertEqual(result.commercial_relation, "C3")
        self.assertFalse(result.brand_control_confirmed)
        self.assertNotEqual(result.integrity_level, "I4")

    def test_self_signed_observation_cannot_elevate_unrelated_fact(self) -> None:
        fact = _fact("t3_unrelated")
        observation = _observation(
            "t3_unrelated",
            str(fact["fact_id"]),
            cluster_key="attacker-cluster",
            brand_attribution_confirmed=True,
            manual_rule_violation_confirmed=True,
            signal_types=["behavior", "content"],
        )
        with self.assertRaisesRegex(IntegritySnapshotError, "do not replay"):
            _validate_observation(observation, {str(fact["fact_id"]): fact})

    def test_real_governed_signal_a1_fails_closed_on_missing_fifth_root(self) -> None:
        with self.assertRaisesRegex(
            IntegritySnapshotError, "post:1u2gvn4"
        ):
            load_frozen_governed_inputs(
                upstream_root=REAL_GOVERNED_ROOT,
                upstream_receipt_path=REAL_GOVERNED_RECEIPT,
                policy_path=POLICY,
            )


if __name__ == "__main__":
    unittest.main()
