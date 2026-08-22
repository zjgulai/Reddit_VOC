from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.v3_metric_eligibility import (
    MetricEligibilityError,
    canonical_json_bytes,
    load_metric_eligibility_policy,
    materialize_metric_eligibility,
    organic_exclusion_reason,
    parse_metric_eligibility_policy,
    summarize_metric_eligibility,
    validate_subset_contract,
)
from reddit_voc.v3_voc_facts import materialize_vocs


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/analytics/reddit-voc-metric-eligibility-v1.json"


def _post(post_id: str, *, text: str = "A post") -> dict[str, object]:
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": f"t3_{post_id}",
        "entity_type": "post",
        "post_id": post_id,
        "record": {
            "allowed_metric_families": ["momcozy_internal_single_period"],
            "blocked_uses": ["trend"],
            "canonical_reddit_id": f"t3_{post_id}",
            "entity_type": "post",
            "post_id": post_id,
            "source_snapshot_id": "full-range",
            "source_text": text,
            "source_url": f"https://www.reddit.com/r/test/comments/{post_id}/title/",
        },
        "record_authority": "workbook_net_new",
        "schema_version": "reddit_voc_canonical_post_v1",
    }


def _comment(comment_id: str, *, post_id: str = "p1") -> dict[str, object]:
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": f"t1_{comment_id}",
        "comment_state": "linked",
        "entity_type": "comment",
        "immediate_parent_resolution": "fixture",
        "post_id": post_id,
        "record": {
            "body": "A linked comment",
            "comment_id": f"t1_{comment_id}",
            "parent_id": f"t3_{post_id}",
            "permalink": (
                f"https://www.reddit.com/r/test/comments/{post_id}/title/{comment_id}/"
            ),
            "post_id": post_id,
            "reddit_id": f"t1_{comment_id}",
        },
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_comment_v1",
    }


def _minimal_policy() -> dict[str, object]:
    return {
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
        "comparison_sides": [
            "raw_observed",
            "qualified_organic",
            "momcozy",
        ],
        "indicators": [
            {
                "comparison_sides": ["raw_observed", "qualified_organic"],
                "metric_family": "RV-BR",
                "reddit_indicator_id": "RV-BR-02",
                "required_source_use": "momcozy_internal_single_period",
                "text_required": True,
                "voc_types": ["post_voc", "comment_context_voc"],
            },
            {
                "comparison_sides": ["momcozy"],
                "metric_family": "RV-PS",
                "reddit_indicator_id": "RV-PS-02",
                "required_source_use": "momcozy_internal_single_period",
                "text_required": True,
                "voc_types": ["post_voc"],
            },
        ],
        "policy_version": "fixture_policy_v1",
        "schema_version": "reddit_voc_metric_eligibility_policy_v1",
    }


class MetricEligibilityTests(unittest.TestCase):
    def test_policy_file_is_canonical_and_covers_registered_indicator_sides(self) -> None:
        raw = POLICY_PATH.read_bytes()
        value = json.loads(raw)
        self.assertEqual(raw, canonical_json_bytes(value) + b"\n")

        policy = load_metric_eligibility_policy(POLICY_PATH)
        ids = {item.reddit_indicator_id for item in policy.indicators}
        self.assertEqual(len(ids), 26)
        self.assertIn("RV-BR-01", ids)
        self.assertIn("RV-CI-07", ids)

    def test_one_row_per_indicator_side_and_entity(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        vocs = materialize_vocs([_post("p2"), _post("p1")], [])

        rows = materialize_metric_eligibility(
            vocs,
            policy,
            period="snapshot:fixture",
            scope="all",
        )

        self.assertEqual(len(rows), 6)
        keys = [row.primary_key for row in rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(
            {
                (row.reddit_indicator_id, row.comparison_side, row.metric_member_id)
                for row in rows
            },
            {
                (indicator, side, f"t3_{post_id}")
                for indicator, sides in {
                    "RV-BR-02": ("raw_observed", "qualified_organic"),
                    "RV-PS-02": ("momcozy",),
                }.items()
                for side in sides
                for post_id in ("p1", "p2")
            },
        )

    def test_explicit_automation_excludes_only_organic_metric_families(self) -> None:
        policy_value = _minimal_policy()
        policy_value["indicators"].append(
            {
                "comparison_sides": ["raw_observed"],
                "metric_family": "RV-CI",
                "reddit_indicator_id": "RV-CI-01",
                "required_source_use": "momcozy_internal_single_period",
                "text_required": True,
                "voc_types": ["comment_context_voc"],
            }
        )
        policy = parse_metric_eligibility_policy(policy_value)
        vocs = materialize_vocs([_post("p1")], [_comment("c1")])
        rows = materialize_metric_eligibility(
            vocs,
            policy,
            period="snapshot:fixture",
            scope="all",
            organic_exclusions={"t1_c1": "explicit_automation"},
        )

        comment_rows = [row for row in rows if row.metric_member_id == "t1_c1"]
        self.assertTrue(
            all(
                row.status == "excluded"
                and "explicit_automation" in row.reason_codes
                for row in comment_rows
                if row.metric_family == "RV-BR"
            )
        )
        self.assertTrue(
            all(
                row.status == "eligible"
                and "explicit_automation" not in row.reason_codes
                for row in comment_rows
                if row.metric_family == "RV-CI"
            )
        )
        self.assertEqual(
            organic_exclusion_reason(
                metric_member_id="t1_c1",
                metric_family="RV-CI",
                organic_exclusions={"t1_c1": "explicit_automation"},
            ),
            None,
        )

    def test_streaming_summary_matches_materialized_rows_and_hashes_identities(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        vocs = materialize_vocs([_post("p1")], [_comment("c1")])
        memberships = {
            ("RV-BR-02", "raw_observed", "t1_c1"): {
                "denominator_member": True,
                "numerator_member": False,
                "membership_role": "nonnegative_sentiment",
            },
            ("RV-BR-02", "raw_observed", "t3_p1"): {
                "denominator_member": True,
                "numerator_member": True,
                "membership_role": "negative_sentiment",
            },
        }

        rows = materialize_metric_eligibility(
            vocs,
            policy,
            period="snapshot:fixture",
            scope="all",
            memberships=memberships,
        )
        summary = summarize_metric_eligibility(
            reversed(vocs),
            policy,
            period="snapshot:fixture",
            scope="all",
            memberships=memberships,
        )

        eligible_ids = sorted(
            {row.metric_member_id for row in rows if row.status == "eligible"}
        )
        self.assertEqual(
            summary,
            {
                "membership_rows": len(rows),
                "eligible_rows": sum(row.status == "eligible" for row in rows),
                "excluded_rows": sum(row.status == "excluded" for row in rows),
                "denominator_true_rows": sum(
                    row.denominator_member is True for row in rows
                ),
                "numerator_true_rows": sum(row.numerator_member is True for row in rows),
                "distinct_eligible_post_vocs": 1,
                "distinct_eligible_comment_context_vocs": 1,
                "distinct_eligible_voc_facts": 2,
                "eligible_identity_lf_sha256": sha256(
                    "".join(f"{value}\n" for value in eligible_ids).encode("ascii")
                ).hexdigest(),
                "period": "snapshot:fixture",
                "scope": "all",
            },
        )
        self.assertEqual(
            set(summary),
            {
                "membership_rows",
                "eligible_rows",
                "excluded_rows",
                "denominator_true_rows",
                "numerator_true_rows",
                "distinct_eligible_post_vocs",
                "distinct_eligible_comment_context_vocs",
                "distinct_eligible_voc_facts",
                "eligible_identity_lf_sha256",
                "period",
                "scope",
            },
        )

    def test_streaming_summary_reuses_fail_closed_membership_path(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        vocs = materialize_vocs([_post("p1")], [])
        invalid_membership = {
            ("RV-BR-02", "raw_observed", "t3_missing"): {
                "denominator_member": True,
                "numerator_member": False,
                "membership_role": "nonnegative_sentiment",
            }
        }

        with self.assertRaisesRegex(
            MetricEligibilityError, "membership override has no eligible policy row"
        ):
            summarize_metric_eligibility(
                vocs,
                policy,
                period="p",
                scope="s",
                memberships=invalid_membership,
            )

    def test_brand_side_is_explicitly_excluded_until_brand_routing(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        voc = materialize_vocs([_post("p1")], [])[0]

        rows = materialize_metric_eligibility(voc and [voc], policy, period="p", scope="s")
        momcozy = next(row for row in rows if row.comparison_side == "momcozy")

        self.assertEqual(momcozy.status, "excluded")
        self.assertEqual(momcozy.reason_codes, ("brand_routing_pending",))
        self.assertFalse(momcozy.denominator_member)
        self.assertEqual(momcozy.numerator_member, "not_applicable")

    def test_source_use_and_text_requirements_are_fail_closed(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        blocked = _post("p1", text="A post")
        blocked["record"]["allowed_metric_families"] = []
        voc = materialize_vocs([blocked], [])[0]

        rows = materialize_metric_eligibility([voc], policy, period="p", scope="s")
        raw = next(row for row in rows if row.comparison_side == "raw_observed")

        self.assertEqual(raw.status, "excluded")
        self.assertEqual(
            raw.reason_codes,
            ("source_use_not_allowed",),
        )

    def test_metric_sets_obey_subset_contract_and_tamper_fails(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        vocs = materialize_vocs([_post("p1"), _post("p2")], [])
        memberships = {
            ("RV-BR-02", "raw_observed", "t3_p1"): {
                "denominator_member": True,
                "numerator_member": True,
                "membership_role": "negative_sentiment",
            },
            ("RV-BR-02", "raw_observed", "t3_p2"): {
                "denominator_member": True,
                "numerator_member": False,
                "membership_role": "nonnegative_sentiment",
            },
        }

        rows = materialize_metric_eligibility(
            vocs,
            policy,
            period="p",
            scope="s",
            memberships=memberships,
        )
        validate_subset_contract(rows)

        payloads = [row.as_dict() for row in rows]
        target = next(
            row
            for row in payloads
            if row["reddit_indicator_id"] == "RV-BR-02"
            and row["comparison_side"] == "raw_observed"
            and row["metric_member_id"] == "t3_p2"
        )
        target["denominator_member"] = False
        target["numerator_member"] = True
        with self.assertRaisesRegex(MetricEligibilityError, "numerator.*denominator"):
            validate_subset_contract(payloads)

    def test_subset_groups_do_not_mix_member_types(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        row = materialize_metric_eligibility(
            materialize_vocs([_post("p1")], []),
            policy,
            period="p",
            scope="s",
        )[0].as_dict()
        row["denominator_member"] = False
        row["numerator_member"] = True
        thread = dict(row)
        thread["metric_member_type"] = "thread"
        thread["metric_member_id"] = "thread:p1"
        thread["denominator_member"] = True
        thread["numerator_member"] = False

        with self.assertRaisesRegex(MetricEligibilityError, "numerator.*denominator"):
            validate_subset_contract([row, thread])

    def test_non_entity_member_cannot_impersonate_reddit_entity(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        row = materialize_metric_eligibility(
            materialize_vocs([_post("p1")], []),
            policy,
            period="p",
            scope="s",
        )[0].as_dict()
        row["metric_member_type"] = "thread"
        with self.assertRaisesRegex(MetricEligibilityError, "impersonate"):
            validate_subset_contract([row])

    def test_ledger_rejects_metric_family_and_required_text_field_tamper(self) -> None:
        policy = parse_metric_eligibility_policy(_minimal_policy())
        row = materialize_metric_eligibility(
            materialize_vocs([_post("p1")], []),
            policy,
            period="p",
            scope="s",
        )[0].as_dict()
        row["metric_family"] = "RV-PS"
        with self.assertRaisesRegex(MetricEligibilityError, "metric family"):
            validate_subset_contract([row])

        row["metric_family"] = "RV-BR"
        row["anchor_source"] = ""
        with self.assertRaisesRegex(MetricEligibilityError, "anchor source"):
            validate_subset_contract([row])

    def test_policy_rejects_duplicate_indicator_and_noncanonical_file(self) -> None:
        duplicate = _minimal_policy()
        duplicate["indicators"] = [
            duplicate["indicators"][0],
            duplicate["indicators"][0],
        ]
        with self.assertRaisesRegex(MetricEligibilityError, "duplicate indicator"):
            parse_metric_eligibility_policy(duplicate)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(_minimal_policy(), indent=2), encoding="utf-8")
            with self.assertRaisesRegex(MetricEligibilityError, "canonical JSON"):
                load_metric_eligibility_policy(path)


if __name__ == "__main__":
    unittest.main()
