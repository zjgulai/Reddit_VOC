from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import unittest

from reddit_voc.v3_explicit_automation import (
    ExplicitAutomationError,
    canonical_json_bytes,
    classify_explicit_automation,
    load_explicit_automation_policy,
    organic_exclusion_map,
    parse_explicit_automation_policy,
)
from reddit_voc.v3_metric_eligibility import organic_exclusion_reason


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/analytics/reddit-voc-explicit-automation-v1.json"
BASE_COMMENTS_PATH = (
    ROOT
    / "tmp/reddit-voc-plan-a1-20260715/base-a2"
    / "reddit_voc_site_snapshot_20260715_candidate_a2/comments.json"
)
V3_COMMENTS_PATH = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
    / "canonical-candidate-a1/comments.jsonl"
)
V3_VOCS_PATH = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
    / "voc-facts-candidate-a1/vocs.jsonl"
)
V3_ELIGIBILITY_PATH = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
    / "voc-facts-candidate-a1/metric-eligibility.jsonl"
)


def _policy() -> dict[str, object]:
    return {
        "audit_indicator_ids": ["RV-CI-01"],
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
        "canonical_retention": True,
        "commercial_attribution": "not_inferred",
        "deterministic_rules": [
            {
                "max_disclosure_gap_code_points": 16,
                "quoted_line_behavior": "held",
                "required_match_ids": [
                    "self_disclosed_bot",
                    "automatic_action_disclosure",
                    "moderator_contact_disclosure",
                    "moderator_contact_link",
                ],
                "rule_id": "reddit_automation_footer_v1",
                "same_paragraph": True,
            },
            {
                "required_bot_detection_status": "known_from_archive_author",
                "required_is_bot": True,
                "rule_id": "trusted_upstream_bot_state_v1",
            },
        ],
        "exclude_indicator_families": ["RV-BR", "RV-IN", "RV-PS"],
        "excluded_reason": "explicit_automation",
        "fallback_text_fields": ["body", "comment_body", "source_text"],
        "held_signal_rules": ["single_disclosure", "quoted_disclosure"],
        "matcher_version": "explicit_bot_disclosure_regex_audit_v1",
        "patterns": [
            {"match_id": "self_disclosed_bot", "regex": r"\bi am a bot\b"},
            {
                "match_id": "automatic_action_disclosure",
                "regex": r"\bthis action was performed automatically\b",
            },
            {
                "match_id": "moderator_contact_disclosure",
                "regex": r"\bcontact the moderators of this subreddit\b",
            },
            {
                "match_id": "moderator_contact_link",
                "regex": r"/message/compose/\?to=/r/",
            },
        ],
        "policy_version": "reddit_voc_explicit_automation_20260716_v1",
        "schema_version": "reddit_voc_explicit_automation_policy_v1",
        "text_field_by_record_authority": {
            "governed_base": "body",
            "workbook_net_new": "source_text",
        },
    }


def _footer() -> str:
    return (
        "I am a bot, and this action was performed automatically. "
        "Please [contact the moderators of this subreddit]"
        "(/message/compose/?to=/r/test) if needed."
    )


def _jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


class ExplicitAutomationTests(unittest.TestCase):
    def test_policy_is_canonical_and_frozen(self) -> None:
        raw = POLICY_PATH.read_bytes()
        value = json.loads(raw)
        self.assertEqual(raw, canonical_json_bytes(value) + b"\n")
        policy = load_explicit_automation_policy(POLICY_PATH)
        self.assertEqual(
            policy.matcher_version, "explicit_bot_disclosure_regex_audit_v1"
        )
        self.assertEqual(policy.excluded_reason, "explicit_automation")

    def test_explicit_automation_is_retained_but_metric_ineligible(self) -> None:
        comments = json.loads(BASE_COMMENTS_PATH.read_text(encoding="utf-8"))
        rows = classify_explicit_automation(
            comments,
            policy=load_explicit_automation_policy(POLICY_PATH),
        )

        self.assertEqual(sum(row.detected for row in rows), 540)
        self.assertEqual(sum(row.automation_determined for row in rows), 541)
        self.assertEqual(sum(row.was_already_excluded for row in rows), 113)
        self.assertEqual(
            sum(row.detected and row.was_already_excluded for row in rows),
            112,
        )
        self.assertEqual(sum(row.newly_excluded for row in rows), 428)
        self.assertEqual(
            sum(row.was_already_excluded or row.newly_excluded for row in rows),
            541,
        )
        self.assertTrue(all(row.canonical_retained for row in rows))
        self.assertTrue(
            all(
                row.requires_organic_exclusion
                and row.excluded_reason == "explicit_automation"
                and row.evidence_spans
                for row in rows
                if row.detected
            )
        )

    def test_nested_canonical_record_uses_body_local_span_and_hash(self) -> None:
        body = f"Prefix: {_footer()} Suffix."
        rows = classify_explicit_automation(
            [
                {
                    "canonical_reddit_id": "t1_abc123",
                    "canonical_identity_state": "canonical_identity",
                    "comment_state": "linked",
                    "entity_type": "comment",
                    "record_authority": "governed_base",
                    "schema_version": "reddit_voc_canonical_comment_v1",
                    "record": {
                        "body": body,
                        "comment_id": "t1_abc123",
                        "include_in_voc_metrics": True,
                        "is_bot": None,
                    },
                }
            ],
            policy=parse_explicit_automation_policy(_policy()),
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.detected)
        self.assertTrue(row.automation_determined)
        self.assertTrue(row.newly_excluded)
        span = row.evidence_spans[0]
        self.assertEqual(span.field, "body")
        self.assertEqual(body[span.start : span.end], "I am a bot")
        self.assertEqual(
            span.evidence_text_sha256,
            sha256("I am a bot".encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("body", row.as_dict())
        self.assertNotIn("metric_eligible", row.as_dict())

    def test_single_disclosure_is_held_and_word_boundaries_reject_noise(self) -> None:
        rows = classify_explicit_automation(
            [
                {"comment_id": "t1_1", "body": "This action was manual."},
                {"comment_id": "t1_2", "body": "xI am a botany fan."},
                {"comment_id": "t1_3", "body": "I AM A BOT, beep."},
            ],
            policy=parse_explicit_automation_policy(_policy()),
        )
        self.assertEqual([row.detected for row in rows], [False, False, True])
        self.assertEqual(rows[2].classification_status, "held")
        self.assertFalse(rows[2].requires_organic_exclusion)

    def test_workbook_source_text_and_full_canonical_conservation(self) -> None:
        rows = classify_explicit_automation(
            _jsonl(V3_COMMENTS_PATH),
            policy=load_explicit_automation_policy(POLICY_PATH),
        )
        excluded = organic_exclusion_map(rows)

        self.assertEqual(sum(row.detected for row in rows), 914)
        self.assertEqual(len(excluded), 915)
        self.assertEqual(sum(row.was_already_excluded for row in rows), 113)
        self.assertEqual(sum(row.newly_excluded for row in rows), 802)
        self.assertEqual(
            sum(row.was_already_excluded or row.newly_excluded for row in rows),
            len(excluded),
        )
        self.assertEqual(
            sum(
                row.requires_organic_exclusion and row.comment_state == "linked"
                for row in rows
            ),
            742,
        )
        self.assertEqual(
            sum(
                row.requires_organic_exclusion
                and row.comment_state == "unresolved_parent"
                for row in rows
            ),
            173,
        )
        self.assertEqual(
            sum(
                row.automation_determined
                and row.record_authority == "workbook_net_new"
                and row.text_field == "source_text"
                for row in rows
            ),
            374,
        )

        voc_ids = {row["canonical_entity_id"] for row in _jsonl(V3_VOCS_PATH)}
        self.assertEqual(len(set(excluded) & voc_ids), 737)
        accounting = {
            bucket: sum(
                row.classification_accounting_bucket == bucket for row in rows
            )
            for bucket in {
                "already_excluded_disclosure",
                "newly_excluded_disclosure",
                "upstream_known_bot_only",
            }
        }
        self.assertEqual(
            accounting,
            {
                "already_excluded_disclosure": 112,
                "newly_excluded_disclosure": 802,
                "upstream_known_bot_only": 1,
            },
        )
        self.assertEqual(sum(accounting.values()), len(excluded))

        eligible_before = 0
        eligible_after = 0
        for eligibility in _jsonl(V3_ELIGIBILITY_PATH):
            if (
                eligibility["metric_member_id"] not in excluded
                or eligibility["metric_family"] not in {"RV-BR", "RV-IN", "RV-PS"}
            ):
                continue
            if eligibility["status"] == "eligible":
                eligible_before += 1
                if (
                    organic_exclusion_reason(
                        metric_member_id=eligibility["metric_member_id"],
                        metric_family=eligibility["metric_family"],
                        organic_exclusions=excluded,
                    )
                    is None
                ):
                    eligible_after += 1
        self.assertEqual(eligible_before, 10_304)
        self.assertEqual(eligible_after, 0)

    def test_upstream_known_bot_is_excluded_without_disclosure(self) -> None:
        row = classify_explicit_automation(
            [
                {
                    "comment_id": "t1_knownbot",
                    "body": "A deterministic service response.",
                    "is_bot": True,
                    "bot_detection_status": "known_from_archive_author",
                    "include_in_voc_metrics": False,
                }
            ],
            policy=parse_explicit_automation_policy(_policy()),
        )[0]
        self.assertFalse(row.detected)
        self.assertTrue(row.automation_determined)
        self.assertTrue(row.requires_organic_exclusion)
        self.assertEqual(row.excluded_reason, "explicit_automation")
        self.assertIn("upstream_known_bot", row.reason_codes)

    def test_non_automation_exclusion_is_not_misattributed(self) -> None:
        row = classify_explicit_automation(
            [
                {
                    "comment_id": "t1_deleted",
                    "body": "[deleted]",
                    "include_in_voc_metrics": False,
                    "is_bot": False,
                }
            ],
            policy=parse_explicit_automation_policy(_policy()),
        )[0]
        self.assertFalse(row.requires_organic_exclusion)
        self.assertIsNone(row.excluded_reason)

    def test_footer_requires_one_paragraph_and_governed_order(self) -> None:
        policy = parse_explicit_automation_policy(_policy())
        cross_paragraph = (
            "I am a bot, and this action was performed automatically.\n\n"
            "Please contact the moderators of this subreddit "
            "(/message/compose/?to=/r/test)."
        )
        reversed_contact = (
            "Contact the moderators of this subreddit "
            "(/message/compose/?to=/r/test). I am a bot, and this action "
            "was performed automatically."
        )
        rows = classify_explicit_automation(
            [
                {"comment_id": "t1_cross", "body": cross_paragraph},
                {"comment_id": "t1_reverse", "body": reversed_contact},
            ],
            policy=policy,
        )
        self.assertEqual([row.detected for row in rows], [True, True])
        self.assertTrue(all(row.classification_status == "held" for row in rows))
        self.assertTrue(all(not row.requires_organic_exclusion for row in rows))

    def test_formal_canonical_input_contract_fails_closed(self) -> None:
        policy = parse_explicit_automation_policy(_policy())

        def canonical_row() -> dict[str, object]:
            return {
                "canonical_reddit_id": "t1_contract",
                "canonical_identity_state": "canonical_identity",
                "comment_state": "linked",
                "entity_type": "comment",
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_comment_v1",
                "record": {
                    "body": "ordinary",
                    "comment_id": "t1_contract",
                },
            }

        invalid_authority = canonical_row()
        invalid_authority["record_authority"] = "unknown"
        with self.assertRaisesRegex(ExplicitAutomationError, "not governed"):
            classify_explicit_automation([invalid_authority], policy=policy)

        invalid_state = canonical_row()
        invalid_state["comment_state"] = "arbitrary"
        with self.assertRaisesRegex(ExplicitAutomationError, "state"):
            classify_explicit_automation([invalid_state], policy=policy)

        identity_mismatch = canonical_row()
        identity_mismatch["record"] = {
            "body": "ordinary",
            "comment_id": "t1_other",
        }
        with self.assertRaisesRegex(ExplicitAutomationError, "identity mismatch"):
            classify_explicit_automation([identity_mismatch], policy=policy)

        missing_text = canonical_row()
        missing_text["record"] = {"comment_id": "t1_contract"}
        with self.assertRaisesRegex(ExplicitAutomationError, "field body is missing"):
            classify_explicit_automation([missing_text], policy=policy)

        untrusted_workbook_bot = canonical_row()
        untrusted_workbook_bot["record_authority"] = "workbook_net_new"
        untrusted_workbook_bot["record"] = {
            "comment_id": "t1_contract",
            "source_text": "ordinary",
            "is_bot": True,
            "bot_detection_status": "known_from_archive_author",
        }
        with self.assertRaisesRegex(ExplicitAutomationError, "not governed"):
            classify_explicit_automation([untrusted_workbook_bot], policy=policy)

    def test_output_is_sorted_and_duplicate_entities_fail_closed(self) -> None:
        policy = parse_explicit_automation_policy(_policy())
        rows = classify_explicit_automation(
            [
                {"comment_id": "t1_z", "body": "ordinary"},
                {"comment_id": "t1_a", "body": "ordinary"},
            ],
            policy=policy,
        )
        self.assertEqual(
            [row.canonical_entity_id for row in rows], ["t1_a", "t1_z"]
        )
        with self.assertRaisesRegex(ExplicitAutomationError, "duplicate"):
            classify_explicit_automation(
                [
                    {"comment_id": "t1_a", "body": "one"},
                    {"comment_id": "t1_a", "body": "two"},
                ],
                policy=policy,
            )

    def test_policy_rejects_unregistered_regex_or_boundary_drift(self) -> None:
        value = _policy()
        value["patterns"] = [
            {"match_id": "broad_bot", "regex": "bot"},
        ]
        with self.assertRaisesRegex(ExplicitAutomationError, "patterns"):
            parse_explicit_automation_policy(value)

        value = _policy()
        value["boundaries"] = dict(value["boundaries"])
        value["boundaries"]["provider_call"] = True
        with self.assertRaisesRegex(ExplicitAutomationError, "boundaries"):
            parse_explicit_automation_policy(value)


if __name__ == "__main__":
    unittest.main()
