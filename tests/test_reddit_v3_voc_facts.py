from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from reddit_voc.v3_voc_facts import (
    VocFactError,
    canonical_json_bytes,
    materialize_comment_voc,
    materialize_voc_materialization,
    materialize_vocs,
)
import scripts.build_reddit_v3_voc_facts as facts_builder
from scripts.build_reddit_v3_voc_facts import build_voc_fact_bundle
import scripts.validate_reddit_v3_voc_facts as facts_validator
from scripts.validate_reddit_v3_voc_facts import (
    VocFactValidationError,
    validate_voc_fact_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = ROOT / "tmp/reddit-voc-v3"
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _post(
    post_id: str = "p1",
    *,
    title: str = "Parent title",
    body: str = "Parent body",
    author: str = "parent-author",
    permalink: str | None = None,
) -> dict[str, object]:
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": f"t3_{post_id}",
        "entity_type": "post",
        "post_id": post_id,
        "record": {
            "author": author,
            "content": body,
            "permalink": permalink
            or f"https://www.reddit.com/r/test/comments/{post_id}/parent/",
            "post_id": post_id,
            "reddit_id": f"t3_{post_id}",
            "sentiment": "negative",
            "persona": "pregnant_parent",
            "title": title,
        },
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_post_v1",
    }


def _comment(
    comment_id: str,
    *,
    post_id: str = "p1",
    body: str = "Which size?",
    author: str = "comment-author",
    state: str = "linked",
    parent_id: str | None = None,
    permalink: str | None = None,
) -> dict[str, object]:
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": f"t1_{comment_id}",
        "comment_state": state,
        "entity_type": "comment",
        "immediate_parent_resolution": "fixture",
        "post_id": post_id,
        "record": {
            "author": author,
            "body": body,
            "comment_id": f"t1_{comment_id}",
            "parent_id": parent_id or f"t3_{post_id}",
            "permalink": permalink
            or f"https://www.reddit.com/r/test/comments/{post_id}/parent/{comment_id}/",
            "post_id": post_id,
            "reddit_id": f"t1_{comment_id}",
        },
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_comment_v1",
    }


class VocFactTests(unittest.TestCase):
    def test_one_post_and_n_comments_make_one_plus_n_vocs(self) -> None:
        rows = materialize_vocs([_post()], [_comment("c3"), _comment("c1"), _comment("c2")])

        self.assertEqual(
            [row.voc_id for row in rows],
            ["post:p1", "comment:c1", "comment:c2", "comment:c3"],
        )
        self.assertEqual(len({row.metric_distinct_key for row in rows}), 4)

    def test_parent_persona_sentiment_and_author_do_not_cross_into_comment(self) -> None:
        row = materialize_comment_voc(_post(), _comment("c1"))

        self.assertEqual(
            row.analysis_fields,
            {
                "current_comment_body": "Which size?",
                "post_body": "Parent body",
                "post_title": "Parent title",
            },
        )
        self.assertEqual(row.author, "comment-author")
        self.assertEqual(row.author_scope, "current_comment_author_only")
        self.assertEqual(
            row.evidence_scope["sentiment_problem_severity_recommendation_persona"],
            ["current_comment_body"],
        )
        rendered = row.as_dict()
        self.assertNotIn("persona", rendered)
        self.assertNotIn("sentiment", rendered)
        self.assertNotEqual(row.author, _post()["record"]["author"])

    def test_current_comment_pseudonym_does_not_inherit_parent_pseudonym(self) -> None:
        parent = _post()
        parent["record"]["author"] = None
        parent["record"]["author_pseudonym"] = "anon_parent"
        comment = _comment("c1", author=None)
        comment["record"]["author_pseudonym"] = "anon_comment"

        row = materialize_comment_voc(parent, comment)

        self.assertIsNone(row.author)
        self.assertEqual(row.author_pseudonym, "anon_comment")
        self.assertNotEqual(row.author_pseudonym, parent["record"]["author_pseudonym"])

    def test_unresolved_and_quarantined_comments_make_no_comment_context_voc(self) -> None:
        rows = materialize_vocs(
            [_post()],
            [
                _comment("linked"),
                _comment("orphan", state="unresolved_parent"),
                _comment("quarantine", state="quarantined"),
            ],
        )

        self.assertEqual([row.voc_id for row in rows], ["post:p1", "comment:linked"])

    def test_incomplete_post_comment_and_parent_context_are_canonical_only_debt(self) -> None:
        empty_parent = _post("p2", title="", body="")
        materialization = materialize_voc_materialization(
            [_post(), empty_parent],
            [
                _comment("empty", body=""),
                _comment("contextless", post_id="p2", body="I have content"),
                _comment("orphan", post_id="missing", state="unresolved_parent"),
            ],
        )

        self.assertEqual([row.voc_id for row in materialization.vocs], ["post:p1"])
        self.assertEqual(
            {
                row.canonical_entity_id: row.reason_codes
                for row in materialization.exclusions
            },
            {
                "t1_contextless": ("root_post_context_incomplete",),
                "t1_empty": ("analysis_text_incomplete",),
                "t1_orphan": ("unresolved_parent",),
                "t3_p2": ("analysis_text_incomplete",),
            },
        )

    def test_comment_parent_post_id_conflict_fails_closed(self) -> None:
        with self.assertRaisesRegex(VocFactError, "parent.*mismatch"):
            materialize_vocs([_post()], [_comment("c1", parent_id="t3_other")])

    def test_comment_permalink_root_conflict_fails_closed(self) -> None:
        materialization = materialize_voc_materialization(
            [_post()],
            [
                _comment(
                    "c1",
                    permalink="https://www.reddit.com/r/test/comments/other/parent/c1/",
                )
            ],
        )
        self.assertEqual([row.voc_id for row in materialization.vocs], ["post:p1"])
        self.assertEqual(
            materialization.exclusions[0].reason_codes,
            ("source_url_identity_conflict",),
        )

    def test_comment_permalink_comment_id_conflict_fails_closed(self) -> None:
        materialization = materialize_voc_materialization(
            [_post()],
            [
                _comment(
                    "c1",
                    permalink="https://www.reddit.com/r/test/comments/p1/parent/other/",
                )
            ],
        )
        self.assertEqual([row.voc_id for row in materialization.vocs], ["post:p1"])
        self.assertEqual(
            materialization.exclusions[0].reason_codes,
            ("source_url_identity_conflict",),
        )

    def test_comment_permalink_without_comment_identity_fails_closed(self) -> None:
        materialization = materialize_voc_materialization(
            [_post()],
            [
                _comment(
                    "c1",
                    permalink="https://www.reddit.com/r/test/comments/p1/parent/",
                )
            ],
        )
        self.assertEqual([row.voc_id for row in materialization.vocs], ["post:p1"])
        self.assertEqual(
            materialization.exclusions[0].reason_codes,
            ("source_url_identity_conflict",),
        )

    def test_post_url_variants_do_not_override_canonical_identity(self) -> None:
        variants = (
            "https://www.reddit.com/r/csakmamik/comments/p1/mellszívó/",
            "https://www.reddit.com/r/csakmamik/comments/p1/mellsz%C3%ADv%C3%B3/",
            "https://www.reddit.com/gallery/p1",
            "https://i.redd.it/media-object.jpeg",
            "https://www.amazon.com/example-product",
        )
        for url in variants:
            with self.subTest(url=url):
                rows = materialize_vocs([_post(permalink=url)], [])
                self.assertEqual([row.voc_id for row in rows], ["post:p1"])

    def test_post_url_identity_conflict_is_explicit_exclusion_debt(self) -> None:
        materialization = materialize_voc_materialization(
            [
                _post(
                    permalink=(
                        "https://www.reddit.com/r/test/comments/other/parent/"
                    )
                )
            ],
            [],
        )

        self.assertEqual(materialization.vocs, ())
        self.assertEqual(
            materialization.exclusions[0].as_dict(),
            {
                "canonical_entity_id": "t3_p1",
                "comment_id": None,
                "entity_type": "post",
                "intended_voc_type": "post_voc",
                "post_id": "p1",
                "reason_codes": ["source_url_identity_conflict"],
                "schema_version": "reddit_voc_voc_exclusion_v1",
            },
        )

    def test_parent_url_conflict_does_not_contaminate_linked_comment_voc(self) -> None:
        parent = _post(
            permalink="https://www.reddit.com/r/test/comments/other/parent/"
        )
        materialization = materialize_voc_materialization(
            [parent],
            [_comment("c1")],
        )

        self.assertEqual(
            [row.voc_id for row in materialization.vocs],
            ["comment:c1"],
        )
        self.assertEqual(
            [row.canonical_entity_id for row in materialization.exclusions],
            ["t3_p1"],
        )
        expected, exclusions, _ = facts_validator._expected_materialization(
            [parent],
            [_comment("c1")],
            [],
            [],
        )
        self.assertEqual([row["voc_id"] for row in expected], ["comment:c1"])
        self.assertEqual(
            exclusions[0]["reason_codes"],
            ["source_url_identity_conflict"],
        )

    def test_soft_url_conflict_cannot_hide_later_hard_invalid_url(self) -> None:
        post = _post(
            permalink="https://www.reddit.com/r/test/comments/other/parent/"
        )
        post["record"]["source_url"] = (
            "//evil.example/r/test/comments/p1/parent/"
        )

        with self.assertRaisesRegex(VocFactError, "URL is invalid"):
            materialize_voc_materialization([post], [])
        with self.assertRaisesRegex(VocFactValidationError, "URL is invalid"):
            facts_validator._expected_materialization([post], [], [], [])

    def test_url_path_and_host_bypasses_fail_closed_in_both_implementations(self) -> None:
        invalid_urls = (
            "https://www.amazon.com/%2e%2e/product",
            "https://i.redd.it/%2F.jpeg",
            "https://i.redd.it/%00.jpeg",
            "https://redd.it/p%31",
            "https://www.reddit.com./r/test/comments/p1/parent/",
            "https://www.reddit.com/r/test/comments/p1/parent/other/c1/",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                post = _post(permalink=url)
                with self.assertRaisesRegex(VocFactError, "URL"):
                    materialize_voc_materialization([post], [])
                with self.assertRaisesRegex(VocFactValidationError, "URL"):
                    facts_validator._expected_materialization([post], [], [], [])

    def test_quarantine_url_conflict_is_explicit_debt_not_batch_failure(self) -> None:
        quarantine = _comment(
            "quarantine",
            post_id="missing",
            state="quarantined",
            permalink=(
                "https://www.reddit.com/r/test/comments/other/parent/quarantine/"
            ),
        )
        quarantine["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        quarantine["record"]["missing_post_id"] = "missing"

        materialization = materialize_voc_materialization(
            [_post()],
            [],
            quarantine=[quarantine],
        )
        self.assertEqual(
            materialization.exclusions[0].reason_codes,
            ("quarantined", "source_url_identity_conflict"),
        )
        _, exclusions, _ = facts_validator._expected_materialization(
            [_post()],
            [],
            [quarantine],
            [],
        )
        self.assertEqual(
            exclusions[0]["reason_codes"],
            ["quarantined", "source_url_identity_conflict"],
        )

    def test_url_conflict_preserves_other_comment_debt_reasons(self) -> None:
        parent = _post(title="", body="")
        comment = _comment(
            "c1",
            body="",
            permalink=(
                "https://www.reddit.com/r/test/comments/other/parent/c1/"
            ),
        )
        materialization = materialize_voc_materialization([parent], [comment])
        by_id = {
            row.canonical_entity_id: row.reason_codes
            for row in materialization.exclusions
        }
        self.assertEqual(
            by_id["t1_c1"],
            (
                "analysis_text_incomplete",
                "root_post_context_incomplete",
                "source_url_identity_conflict",
            ),
        )
        _, exclusions, _ = facts_validator._expected_materialization(
            [parent],
            [comment],
            [],
            [],
        )
        validator_by_id = {
            row["canonical_entity_id"]: row["reason_codes"]
            for row in exclusions
        }
        self.assertEqual(validator_by_id["t1_c1"], list(by_id["t1_c1"]))

    def test_protocol_relative_external_url_and_percent_encoded_ids_fail_closed(self) -> None:
        with self.assertRaisesRegex(VocFactError, "URL is invalid"):
            materialize_vocs(
                [_post()],
                [
                    _comment(
                        "c1",
                        permalink="//evil.example/r/test/comments/p1/parent/c1/",
                    )
                ],
            )

    def test_top_level_and_url_identities_require_exact_canonical_lowercase(self) -> None:
        uppercase_fullname = _post()
        uppercase_fullname["canonical_reddit_id"] = "T3_P1"
        with self.assertRaisesRegex(VocFactError, "post identity mismatch"):
            materialize_vocs([uppercase_fullname], [])

        uppercase_post_id = _post()
        uppercase_post_id["post_id"] = "P1"
        with self.assertRaisesRegex(VocFactError, "post identity mismatch"):
            materialize_vocs([uppercase_post_id], [])

        uppercase_comment = _comment("c1")
        uppercase_comment["canonical_reddit_id"] = "T1_C1"
        with self.assertRaisesRegex(VocFactError, "comment identity mismatch"):
            materialize_vocs([_post()], [uppercase_comment])

        uppercase_url_post = _comment(
            "c1",
            permalink="https://www.reddit.com/r/test/comments/P1/parent/c1/",
        )
        with self.assertRaisesRegex(VocFactError, "not canonical lowercase"):
            materialize_vocs([_post()], [uppercase_url_post])

        uppercase_url_comment = _comment(
            "c1",
            permalink="https://www.reddit.com/r/test/comments/p1/parent/C1/",
        )
        with self.assertRaisesRegex(VocFactError, "not canonical lowercase"):
            materialize_vocs([_post()], [uppercase_url_comment])

        quarantine = _comment("quarantine", state="quarantined")
        quarantine["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        quarantine["canonical_reddit_id"] = "T1_QUARANTINE"
        quarantine["record"]["missing_post_id"] = "p1"
        with self.assertRaisesRegex(
            VocFactError, "quarantined comment identity mismatch"
        ):
            materialize_voc_materialization(
                [_post()],
                [],
                quarantine=[quarantine],
            )

    def test_quarantine_self_parent_and_root_mismatch_fail_closed(self) -> None:
        self_parent = _comment(
            "quarantine",
            post_id="missing",
            state="quarantined",
        )
        self_parent["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        self_parent["record"]["missing_post_id"] = "missing"
        self_parent["record"]["parent_id"] = "t1_quarantine"
        with self.assertRaisesRegex(VocFactError, "parent cycle"):
            materialize_voc_materialization(
                [_post()],
                [],
                quarantine=[self_parent],
            )
        with self.assertRaisesRegex(VocFactValidationError, "parent cycle"):
            facts_validator._expected_materialization(
                [_post()],
                [],
                [self_parent],
                [],
            )

        root_mismatch = _comment(
            "quarantine",
            post_id="missing",
            state="quarantined",
        )
        root_mismatch["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        root_mismatch["record"]["missing_post_id"] = "missing"
        root_mismatch["record"]["parent_id"] = "t3_other"
        with self.assertRaisesRegex(VocFactError, "parent post mismatch"):
            materialize_voc_materialization(
                [_post()],
                [],
                quarantine=[root_mismatch],
            )
        with self.assertRaisesRegex(VocFactValidationError, "parent post mismatch"):
            facts_validator._expected_materialization(
                [_post()],
                [],
                [root_mismatch],
                [],
            )

    def test_quarantine_parent_graph_cycles_and_cross_thread_links_fail_closed(self) -> None:
        first = _comment(
            "q1",
            post_id="missing",
            state="quarantined",
            parent_id="t1_q2",
        )
        second = _comment(
            "q2",
            post_id="missing",
            state="quarantined",
            parent_id="t1_q1",
        )
        for row in (first, second):
            row["schema_version"] = "reddit_voc_canonical_quarantine_v1"
            row["record"]["missing_post_id"] = "missing"

        with self.assertRaisesRegex(VocFactError, "parent cycle"):
            materialize_voc_materialization(
                [_post()],
                [],
                quarantine=[first, second],
            )
        with self.assertRaisesRegex(VocFactValidationError, "parent cycle"):
            facts_validator._expected_materialization(
                [_post()],
                [],
                [first, second],
                [],
            )

        cross_thread = _comment(
            "q3",
            post_id="missing",
            state="quarantined",
            parent_id="t1_c1",
        )
        cross_thread["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        cross_thread["record"]["missing_post_id"] = "missing"
        linked = _comment("c1")

        with self.assertRaisesRegex(VocFactError, "crosses canonical root threads"):
            materialize_voc_materialization(
                [_post()],
                [linked],
                quarantine=[cross_thread],
            )
        with self.assertRaisesRegex(
            VocFactValidationError, "crosses root threads"
        ):
            facts_validator._expected_materialization(
                [_post()],
                [linked],
                [cross_thread],
                [],
            )

    def test_quarantine_root_must_be_absent_from_canonical_posts(self) -> None:
        quarantine = _comment("quarantine", state="quarantined")
        quarantine["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        quarantine["record"]["missing_post_id"] = "p1"

        with self.assertRaisesRegex(VocFactError, "unexpectedly exists"):
            materialize_voc_materialization(
                [_post()],
                [],
                quarantine=[quarantine],
            )
        with self.assertRaisesRegex(VocFactValidationError, "unexpectedly exists"):
            facts_validator._expected_materialization(
                [_post()],
                [],
                [quarantine],
                [],
            )
        with self.assertRaisesRegex(VocFactError, "raw identity"):
            materialize_vocs(
                [_post()],
                [
                    _comment(
                        "c1",
                        permalink="https://www.reddit.com/r/test/comments/p1/parent/c%31/",
                    )
                ],
            )

    def test_known_nested_parent_cycle_fails_closed(self) -> None:
        with self.assertRaisesRegex(VocFactError, "parent cycle"):
            materialize_vocs(
                [_post()],
                [
                    _comment("c1", parent_id="t1_c2"),
                    _comment("c2", parent_id="t1_c1"),
                ],
            )

    def test_combined_thread_mapping_is_supported_without_changing_grain(self) -> None:
        rows = materialize_vocs({"post": _post(), "comments": [_comment("c1")]})
        self.assertEqual([row.voc_id for row in rows], ["post:p1", "comment:c1"])

    def test_missing_parent_and_duplicate_identity_fail_closed(self) -> None:
        with self.assertRaisesRegex(VocFactError, "root post is missing"):
            materialize_vocs([_post()], [_comment("c1", post_id="p2")])
        with self.assertRaisesRegex(VocFactError, "duplicate canonical post"):
            materialize_vocs([_post(), _post()], [])

    def test_workbook_payload_keeps_original_fields_separate(self) -> None:
        post = _post()
        post["record"] = {
            "canonical_reddit_id": "t3_p1",
            "entity_type": "post",
            "event_time_precision": "day",
            "post_id": "p1",
            "source_calendar_date": "2026-07-15",
            "source_summary": "derived summary is not original body",
            "source_text": "Workbook title",
            "source_url": "https://www.reddit.com/r/test/comments/p1/workbook_title/",
            "source_snapshot_id": "full-range",
            "source_timezone_status": "unknown",
            "allowed_metric_families": ["momcozy_internal_single_period"],
            "blocked_uses": ["trend"],
        }
        comment = _comment("c1")
        comment["record"] = {
            "canonical_reddit_id": "t1_c1",
            "comment_id": "t1_c1",
            "entity_type": "comment",
            "event_time_precision": "day",
            "post_id": "p1",
            "source_calendar_date": "2026-07-15",
            "source_summary": "derived summary",
            "source_text": "Workbook comment body",
            "source_url": "https://www.reddit.com/r/test/comments/p1/workbook_title/c1/",
            "source_snapshot_id": "full-range",
            "source_timezone_status": "unknown",
            "allowed_metric_families": ["momcozy_internal_single_period"],
            "blocked_uses": ["trend"],
        }

        rows = materialize_vocs([post], [comment])

        self.assertEqual(rows[0].analysis_fields["post_title"], "Workbook title")
        self.assertEqual(rows[0].analysis_fields["post_body"], "")
        self.assertEqual(rows[1].analysis_fields["current_comment_body"], "Workbook comment body")
        self.assertEqual(rows[0].event_time_precision, "day")
        self.assertEqual(rows[0].source_calendar_date, "2026-07-15")
        self.assertIsNone(rows[0].event_created_at_utc)
        self.assertNotIn("derived summary", json.dumps([row.as_dict() for row in rows]))

    def test_event_time_contract_rejects_fabricated_or_timezone_free_instants(self) -> None:
        day = _post()
        day["record"]["event_time_precision"] = "day"
        day["record"]["source_calendar_date"] = "2026-07-15"
        day["record"]["source_timezone_status"] = "unknown"
        day["record"]["created_at_utc"] = "2026-07-15T00:00:00Z"
        with self.assertRaisesRegex(VocFactError, "day-precision.*instant"):
            materialize_vocs([day], [])

        instant = _post()
        instant["record"]["event_time_precision"] = "instant"
        instant["record"]["created_at_utc"] = "2026-07-15T00:00:00"
        with self.assertRaisesRegex(VocFactError, "timezone-aware"):
            materialize_vocs([instant], [])

    def test_canonical_json_is_stable_utf8_and_rejects_nonfinite(self) -> None:
        self.assertEqual(
            canonical_json_bytes({"z": "妈妈", "a": 1}),
            b'{"a":1,"z":"\xe5\xa6\x88\xe5\xa6\x88"}',
        )
        with self.assertRaises(VocFactError):
            canonical_json_bytes({"value": float("nan")})

    def test_fixture_candidate_builds_then_independent_validator_recomputes_and_rejects_tamper(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(prefix="voc-facts-fixture-", dir=PRIVATE_ROOT) as directory:
            root = Path(directory)
            root.chmod(0o700)
            canonical_root = root / "canonical"
            canonical_root.mkdir(mode=0o700)
            automation_footer = (
                "I am a bot, and this action was performed automatically. "
                "Please contact the moderators of this subreddit "
                "(/message/compose/?to=/r/test)."
            )
            documents = {
                "comments.jsonl": [
                    _comment("c1", body=automation_footer),
                    _comment(
                        "orphan",
                        post_id="missing",
                        state="unresolved_parent",
                        body=automation_footer,
                    ),
                ],
                "conflict-ledger.jsonl": [],
                "posts.jsonl": [_post()],
                "provenance-ledger.jsonl": [],
                "quarantine.jsonl": [],
                "unresolved-parent-ledger.jsonl": [
                    {
                        "canonical_reddit_id": "t1_orphan",
                        "comment_state": "unresolved_parent",
                        "post_id": "missing",
                        "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                    }
                ],
            }
            bindings: dict[str, dict[str, object]] = {}
            for name, rows in documents.items():
                payload = _jsonl(rows)
                _write_private(canonical_root / name, payload)
                bindings[name] = {
                    "bytes": len(payload),
                    "rows": len(rows),
                    "sha256": _sha(payload),
                }
            counts = {
                "comments_jsonl": 2,
                "linked_comments": 1,
                "posts": 1,
                "quarantined_comments": 0,
                "stored_comments": 2,
                "unresolved_parent_comments": 1,
            }
            inputs = {
                "base_lineage_manifest_sha256": "1" * 64,
                "base_public_manifest_sha256": "2" * 64,
                "source_manifest_sha256": "3" * 64,
                "workbook_import_manifest_sha256": "4" * 64,
                "workbook_import_validation_receipt_sha256": "5" * 64,
            }
            source_row_accounting = {
                "layer_separation": "source_row_terminal_disposition_is_not_canonical_entity_state",
                "source_rows": 3,
                "terminal_outcomes": {"net_new_text_ready": 2, "unresolved_parent": 1},
            }
            canonical_manifest = {
                "boundaries": BOUNDARIES,
                "canonical_counts": counts,
                "consumption_status": "blocked_pending_independent_validation",
                "dataset_id": "fixture_canonical_v1",
                "files": bindings,
                "governed_base_parent_lineage_debt": {
                    "linked_definition": "post_id_resolves_to_canonical_post_not_complete_immediate_parent_chain",
                    "missing_immediate_parent_id": 0,
                    "missing_parent_comment_entity": 0,
                    "nested_links_whose_parent_record_lacks_immediate_parent_id": 0,
                    "workbook_unresolved_parent_separate": True,
                },
                "independent_validation_status": "pending",
                "inputs": inputs,
                "promotable": False,
                "schema_version": "reddit_voc_canonical_snapshot_manifest_v1",
                "source_row_accounting": source_row_accounting,
                "state_contract": {
                    "canonical_identity": True,
                    "comment_states": ["linked", "unresolved_parent", "quarantined"],
                    "states_mutually_exclusive": True,
                },
                "status": "candidate_built",
                "validation_receipt_sha256": None,
            }
            canonical_manifest_payload = canonical_json_bytes(canonical_manifest) + b"\n"
            _write_private(canonical_root / "manifest.json", canonical_manifest_payload)

            receipt_parent = root / "canonical-validation"
            receipt_parent.mkdir(mode=0o700)
            canonical_receipt = {
                "boundaries": BOUNDARIES,
                "bundle_manifest_sha256": _sha(canonical_manifest_payload),
                "canonical_counts": counts,
                "consumption_status": "blocked_pending_voc_facts",
                "inputs": inputs,
                "promotable": False,
                "schema_version": "reddit_voc_canonical_snapshot_validation_receipt_v1",
                "source_row_accounting": {
                    "source_rows": source_row_accounting["source_rows"],
                    "terminal_outcomes": source_row_accounting["terminal_outcomes"],
                },
                "status": "passed",
                "unaccounted_canonical_identities": 0,
                "unaccounted_foreign_keys": 0,
            }
            canonical_receipt_path = receipt_parent / "receipt.json"
            canonical_receipt_payload = canonical_json_bytes(canonical_receipt) + b"\n"
            _write_private(canonical_receipt_path, canonical_receipt_payload)

            policy_path = ROOT / "config/analytics/reddit-voc-metric-eligibility-v1.json"
            policy_sha = _sha(policy_path.read_bytes())
            output_root = root / "voc-candidate"
            built = build_voc_fact_bundle(
                canonical_root=canonical_root,
                canonical_manifest_sha256=_sha(canonical_manifest_payload),
                canonical_validation_receipt=canonical_receipt_path,
                canonical_validation_receipt_sha256=_sha(canonical_receipt_payload),
                eligibility_policy_path=policy_path,
                eligibility_policy_sha256=policy_sha,
                period="snapshot:fixture",
                scope="all",
                output_root=output_root,
                project_root=ROOT,
            )

            facts_receipt_parent = root / "voc-validation"
            facts_receipt_parent.mkdir(mode=0o700)
            facts_receipt_path = facts_receipt_parent / "receipt.json"
            receipt = validate_voc_fact_bundle(
                bundle_root=output_root,
                expected_manifest_sha256=str(built["manifest_sha256"]),
                canonical_root=canonical_root,
                expected_canonical_manifest_sha256=_sha(canonical_manifest_payload),
                canonical_validation_receipt=canonical_receipt_path,
                expected_canonical_validation_receipt_sha256=_sha(canonical_receipt_payload),
                eligibility_policy_path=policy_path,
                expected_eligibility_policy_sha256=policy_sha,
                project_root=ROOT,
                receipt_path=facts_receipt_path,
            )
            self.assertEqual(receipt.counts["post_vocs"], 1)
            self.assertEqual(receipt.counts["comment_context_vocs"], 1)
            self.assertEqual(stat.S_IMODE(output_root.stat().st_mode), 0o700)
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output_root.iterdir())
            )
            self.assertEqual(stat.S_IMODE(facts_receipt_path.stat().st_mode), 0o600)
            self.assertEqual(
                facts_receipt_path.read_bytes(),
                canonical_json_bytes(receipt.as_dict()) + b"\n",
            )
            self.assertEqual([path.name for path in facts_receipt_parent.iterdir()], ["receipt.json"])

            automation_policy_path = (
                ROOT
                / "config/analytics/reddit-voc-explicit-automation-v1.json"
            )
            automation_policy_sha = _sha(automation_policy_path.read_bytes())
            a2_output_root = root / "voc-candidate-a2"
            a2_built = build_voc_fact_bundle(
                canonical_root=canonical_root,
                canonical_manifest_sha256=_sha(canonical_manifest_payload),
                canonical_validation_receipt=canonical_receipt_path,
                canonical_validation_receipt_sha256=_sha(
                    canonical_receipt_payload
                ),
                eligibility_policy_path=policy_path,
                eligibility_policy_sha256=policy_sha,
                automation_policy_path=automation_policy_path,
                automation_policy_sha256=automation_policy_sha,
                period="snapshot:fixture",
                scope="all",
                output_root=a2_output_root,
                project_root=ROOT,
            )
            a2_receipt_parent = root / "voc-validation-a2"
            a2_receipt_parent.mkdir(mode=0o700)
            a2_receipt_path = a2_receipt_parent / "receipt.json"
            a2_receipt = validate_voc_fact_bundle(
                bundle_root=a2_output_root,
                expected_manifest_sha256=str(a2_built["manifest_sha256"]),
                canonical_root=canonical_root,
                expected_canonical_manifest_sha256=_sha(
                    canonical_manifest_payload
                ),
                canonical_validation_receipt=canonical_receipt_path,
                expected_canonical_validation_receipt_sha256=_sha(
                    canonical_receipt_payload
                ),
                eligibility_policy_path=policy_path,
                expected_eligibility_policy_sha256=policy_sha,
                automation_policy_path=automation_policy_path,
                expected_automation_policy_sha256=automation_policy_sha,
                project_root=ROOT,
                receipt_path=a2_receipt_path,
            )
            self.assertEqual(a2_receipt.counts["automation_total"], 2)
            self.assertEqual(a2_receipt.counts["automation_voc"], 1)
            self.assertEqual(a2_receipt.counts["automation_non_voc"], 1)
            self.assertEqual(
                a2_receipt.counts["automation_non_voc_unresolved"], 1
            )
            self.assertEqual(
                a2_receipt.counts["effective_eligible_automation_rows"], 0
            )
            self.assertGreater(
                a2_receipt.counts[
                    "effective_business_rows_excluded_by_automation"
                ],
                0,
            )
            self.assertEqual(
                set(path.name for path in a2_output_root.iterdir()),
                facts_builder.OUTPUT_FILES_A2,
            )
            self.assertEqual(
                a2_receipt.schema_version,
                "reddit_voc_voc_facts_validation_receipt_v2",
            )
            classification_path = (
                a2_output_root / "automation-classifications.jsonl"
            )
            classification_rows = [
                json.loads(line)
                for line in classification_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            classification_rows[0]["classification_status"] = "not_detected"
            tampered_classification_payload = _jsonl(classification_rows)
            _write_private(
                classification_path, tampered_classification_payload
            )
            a2_manifest_path = a2_output_root / "manifest.json"
            a2_manifest = json.loads(a2_manifest_path.read_text(encoding="utf-8"))
            a2_manifest["files"]["automation-classifications.jsonl"] = {
                "bytes": len(tampered_classification_payload),
                "rows": len(classification_rows),
                "sha256": _sha(tampered_classification_payload),
            }
            rebound_a2_manifest_payload = canonical_json_bytes(a2_manifest) + b"\n"
            _write_private(a2_manifest_path, rebound_a2_manifest_payload)
            with self.assertRaisesRegex(
                VocFactValidationError,
                "automation classifications do not reproduce",
            ):
                validate_voc_fact_bundle(
                    bundle_root=a2_output_root,
                    expected_manifest_sha256=_sha(rebound_a2_manifest_payload),
                    canonical_root=canonical_root,
                    expected_canonical_manifest_sha256=_sha(
                        canonical_manifest_payload
                    ),
                    canonical_validation_receipt=canonical_receipt_path,
                    expected_canonical_validation_receipt_sha256=_sha(
                        canonical_receipt_payload
                    ),
                    eligibility_policy_path=policy_path,
                    expected_eligibility_policy_sha256=policy_sha,
                    automation_policy_path=automation_policy_path,
                    expected_automation_policy_sha256=automation_policy_sha,
                    project_root=ROOT,
                )

            eligibility_path = output_root / "metric-eligibility.jsonl"
            rows = [json.loads(line) for line in eligibility_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["reason_codes"] = ["tampered"]
            eligibility_payload = _jsonl(rows)
            _write_private(eligibility_path, eligibility_payload)
            output_manifest_path = output_root / "manifest.json"
            output_manifest = json.loads(output_manifest_path.read_text(encoding="utf-8"))
            output_manifest["files"]["metric-eligibility.jsonl"] = {
                "bytes": len(eligibility_payload),
                "rows": len(rows),
                "sha256": _sha(eligibility_payload),
            }
            rebound_manifest_payload = canonical_json_bytes(output_manifest) + b"\n"
            _write_private(output_manifest_path, rebound_manifest_payload)
            with self.assertRaisesRegex(VocFactValidationError, "eligibility ledger mismatch"):
                validate_voc_fact_bundle(
                    bundle_root=output_root,
                    expected_manifest_sha256=_sha(rebound_manifest_payload),
                    canonical_root=canonical_root,
                    expected_canonical_manifest_sha256=_sha(canonical_manifest_payload),
                    canonical_validation_receipt=canonical_receipt_path,
                    expected_canonical_validation_receipt_sha256=_sha(canonical_receipt_payload),
                    eligibility_policy_path=policy_path,
                    expected_eligibility_policy_sha256=policy_sha,
                    project_root=ROOT,
                )

    def test_independent_validator_rejects_duplicate_and_invalid_skipped_comment_before_filtering(self) -> None:
        post = _post()
        linked = _comment("c1")
        with self.assertRaisesRegex(VocFactValidationError, "duplicate"):
            facts_validator._expected_materialization(
                [post],
                [linked, linked],
                [],
                [],
            )

        unresolved = _comment(
            "orphan",
            post_id="missing",
            state="unresolved_parent",
            permalink="//evil.example/r/test/comments/missing/parent/orphan/",
        )
        with self.assertRaisesRegex(VocFactValidationError, "URL is invalid"):
            facts_validator._expected_materialization(
                [post],
                [unresolved],
                [],
                [
                    {
                        "canonical_reddit_id": "t1_orphan",
                        "comment_state": "unresolved_parent",
                        "post_id": "missing",
                        "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                    }
                ],
            )

        quarantined = _comment(
            "quarantine",
            post_id="missing",
            state="quarantined",
        )
        quarantined["schema_version"] = "reddit_voc_canonical_quarantine_v1"
        quarantined["record"]["missing_post_id"] = "missing"
        quarantined["record"]["permalink"] = (
            "//evil.example/r/test/comments/missing/parent/quarantine/"
        )
        with self.assertRaisesRegex(VocFactValidationError, "URL is invalid"):
            facts_validator._expected_materialization(
                [post],
                [],
                [quarantined],
                [],
            )

    def test_independent_validator_recomputes_canonical_state_counts(self) -> None:
        post = _post()
        linked = _comment("c1")
        unresolved = _comment("orphan", post_id="missing", state="unresolved_parent")
        _, exclusions, counts = facts_validator._expected_materialization(
            [post],
            [linked, unresolved],
            [],
            [
                {
                    "canonical_reddit_id": "t1_orphan",
                    "comment_state": "unresolved_parent",
                    "post_id": "missing",
                    "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                }
            ],
        )
        self.assertEqual(
            counts,
            {
                "comments_jsonl": 2,
                "linked_comments": 1,
                "posts": 1,
                "quarantined_comments": 0,
                "stored_comments": 2,
                "unresolved_parent_comments": 1,
            },
        )
        self.assertEqual(exclusions[0]["canonical_entity_id"], "t1_orphan")

    def test_receipt_parent_fsync_failure_never_publishes_target(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(
            prefix="voc-receipt-fsync-", dir=PRIVATE_ROOT
        ) as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            target = parent / "receipt.json"
            real_fsync = os.fsync

            def fail_directory_fsync(descriptor: int) -> None:
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise OSError("injected parent fsync failure")
                real_fsync(descriptor)

            with mock.patch.object(
                facts_validator.os,
                "fsync",
                side_effect=fail_directory_fsync,
            ):
                with self.assertRaisesRegex(
                    VocFactValidationError, "publish failed"
                ):
                    facts_validator._write_receipt(
                        target,
                        {"status": "passed"},
                        ROOT,
                    )

            self.assertFalse(target.exists())
            blocker = parent / ".receipt.json.uncommitted"
            self.assertTrue(blocker.is_file())
            self.assertEqual(stat.S_IMODE(blocker.stat().st_mode), 0o600)

    def test_receipt_no_replace_preserves_existing_target(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(
            prefix="voc-receipt-existing-", dir=PRIVATE_ROOT
        ) as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            target = parent / "receipt.json"
            _write_private(target, b"foreign-target\n")

            with self.assertRaisesRegex(
                VocFactValidationError, "already exists"
            ):
                facts_validator._write_receipt(
                    target,
                    {"status": "passed"},
                    ROOT,
                )

            self.assertEqual(target.read_bytes(), b"foreign-target\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(
                len(list(parent.glob(".receipt.json.*.staging"))),
                1,
            )
            self.assertTrue((parent / ".receipt.json.uncommitted").is_file())

    def test_receipt_replacement_race_never_invalidates_foreign_target(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(
            prefix="voc-receipt-replacement-", dir=PRIVATE_ROOT
        ) as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            target = parent / "receipt.json"
            real_rename = facts_validator._rename_noreplace

            def replace_after_publish(
                parent_fd: int,
                source: str,
                destination: str,
            ) -> None:
                real_rename(parent_fd, source, destination)
                os.rename(
                    destination,
                    ".receipt.json.owned-inode",
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                foreign_fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    os.fchmod(foreign_fd, 0o600)
                    os.write(foreign_fd, b"foreign-replacement\n")
                    os.fsync(foreign_fd)
                finally:
                    os.close(foreign_fd)

            with mock.patch.object(
                facts_validator,
                "_rename_noreplace",
                side_effect=replace_after_publish,
            ):
                with self.assertRaisesRegex(
                    VocFactValidationError, "ownership changed"
                ):
                    facts_validator._write_receipt(
                        target,
                        {"status": "passed"},
                        ROOT,
                    )

            self.assertEqual(target.read_bytes(), b"foreign-replacement\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            owned_inode = parent / ".receipt.json.owned-inode"
            self.assertGreater(owned_inode.stat().st_size, 0)
            self.assertEqual(stat.S_IMODE(owned_inode.stat().st_mode), 0o600)
            self.assertTrue((parent / ".receipt.json.uncommitted").is_file())

    def test_post_rename_failure_keeps_blocker_even_when_compensation_io_fails(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(
            prefix="voc-receipt-commit-gate-", dir=PRIVATE_ROOT
        ) as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            target = parent / "receipt.json"
            real_fsync = os.fsync
            real_fchmod = os.fchmod
            directory_fsyncs = 0
            fchmod_calls = 0

            def fail_post_rename_parent_fsync(descriptor: int) -> None:
                nonlocal directory_fsyncs
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    directory_fsyncs += 1
                    if directory_fsyncs >= 3:
                        raise OSError("persistent post-rename parent fsync failure")
                real_fsync(descriptor)

            def fail_any_compensation_fchmod(descriptor: int, mode: int) -> None:
                nonlocal fchmod_calls
                fchmod_calls += 1
                if fchmod_calls > 2:
                    raise OSError("injected compensation fchmod failure")
                real_fchmod(descriptor, mode)

            with (
                mock.patch.object(
                    facts_validator.os,
                    "fsync",
                    side_effect=fail_post_rename_parent_fsync,
                ),
                mock.patch.object(
                    facts_validator.os,
                    "fchmod",
                    side_effect=fail_any_compensation_fchmod,
                ),
                mock.patch.object(
                    facts_validator.os,
                    "ftruncate",
                    side_effect=OSError("injected compensation truncate failure"),
                ),
            ):
                with self.assertRaisesRegex(
                    VocFactValidationError, "publish failed"
                ):
                    facts_validator._write_receipt(
                        target,
                        {"status": "passed"},
                        ROOT,
                    )

            self.assertEqual(
                target.read_bytes(),
                canonical_json_bytes({"status": "passed"}) + b"\n",
            )
            blocker = parent / ".receipt.json.uncommitted"
            self.assertTrue(blocker.is_file())
            self.assertEqual(stat.S_IMODE(blocker.stat().st_mode), 0o600)
            with self.assertRaisesRegex(
                VocFactValidationError, "uncommitted receipt marker"
            ):
                facts_validator._read_private_receipt(
                    target,
                    project_root=ROOT,
                    label="fixture receipt",
                )
            with self.assertRaisesRegex(
                facts_builder.VocFactBuildError, "uncommitted receipt marker"
            ):
                facts_builder._read_private_receipt(
                    target,
                    project_root=ROOT,
                    label="fixture receipt",
                )

    def test_receipt_rejects_symlinked_private_ancestor_without_side_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="voc-receipt-project-") as project_dir:
            with tempfile.TemporaryDirectory(prefix="voc-receipt-outside-") as outside_dir:
                project = Path(project_dir)
                outside = Path(outside_dir)
                sentinel = outside / "sentinel"
                sentinel.write_bytes(b"unchanged")
                (project / "tmp").symlink_to(outside, target_is_directory=True)
                target = project / "tmp/reddit-voc-v3/receipts/receipt.json"

                with self.assertRaisesRegex(
                    VocFactValidationError, "directory chain is unavailable"
                ):
                    facts_validator._write_receipt(
                        target,
                        {"status": "passed"},
                        project,
                    )

                self.assertEqual(set(path.name for path in outside.iterdir()), {"sentinel"})
                self.assertEqual(sentinel.read_bytes(), b"unchanged")

    def test_candidate_parent_fsync_failure_never_publishes_target(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(
            prefix="voc-candidate-fsync-", dir=PRIVATE_ROOT
        ) as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            target = parent / "candidate"
            parent_identity = (parent.stat().st_dev, parent.stat().st_ino)
            real_fsync = os.fsync

            def fail_parent_fsync(descriptor: int) -> None:
                metadata = os.fstat(descriptor)
                if (metadata.st_dev, metadata.st_ino) == parent_identity:
                    raise OSError("injected candidate parent fsync failure")
                real_fsync(descriptor)

            payloads = {name: b"" for name in facts_builder.OUTPUT_FILES}
            with mock.patch.object(
                facts_builder.os,
                "fsync",
                side_effect=fail_parent_fsync,
            ):
                with self.assertRaisesRegex(
                    facts_builder.VocFactBuildError,
                    "unable to publish",
                ):
                    facts_builder._write_candidate(target, payloads, ROOT)

            self.assertFalse(target.exists())
            stages = list(parent.glob(".candidate.*.staging"))
            self.assertEqual(len(stages), 1)
            self.assertEqual(
                set(path.name for path in stages[0].iterdir()),
                {".publish-failed"},
            )

    def test_candidate_no_replace_preserves_existing_target(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(
            prefix="voc-candidate-existing-", dir=PRIVATE_ROOT
        ) as directory:
            parent = Path(directory)
            parent.chmod(0o700)
            target = parent / "candidate"
            target.mkdir(mode=0o700)
            sentinel = target / "foreign"
            _write_private(sentinel, b"unchanged")
            payloads = {name: b"" for name in facts_builder.OUTPUT_FILES}

            with self.assertRaisesRegex(
                facts_builder.VocFactBuildError,
                "already exists",
            ):
                facts_builder._write_candidate(target, payloads, ROOT)

            self.assertEqual(sentinel.read_bytes(), b"unchanged")
            self.assertEqual(set(path.name for path in target.iterdir()), {"foreign"})

    def test_candidate_rejects_symlinked_private_ancestor_without_side_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="voc-candidate-project-") as project_dir:
            with tempfile.TemporaryDirectory(prefix="voc-candidate-outside-") as outside_dir:
                project = Path(project_dir)
                outside = Path(outside_dir)
                sentinel = outside / "sentinel"
                sentinel.write_bytes(b"unchanged")
                (project / "tmp").symlink_to(outside, target_is_directory=True)
                target = project / "tmp/reddit-voc-v3/output/candidate"
                payloads = {name: b"" for name in facts_builder.OUTPUT_FILES}

                with self.assertRaisesRegex(
                    facts_builder.VocFactBuildError,
                    "directory chain is unavailable",
                ):
                    facts_builder._write_candidate(target, payloads, project)

                self.assertEqual(set(path.name for path in outside.iterdir()), {"sentinel"})
                self.assertEqual(sentinel.read_bytes(), b"unchanged")

    def test_candidate_and_receipt_paths_cannot_overlap_canonical_inputs(self) -> None:
        canonical_root = PRIVATE_ROOT / "boundary-canonical"
        canonical_receipt = PRIVATE_ROOT / "boundary-receipt.json"
        policy_path = ROOT / "config/analytics/reddit-voc-metric-eligibility-v1.json"
        policy_sha = _sha(policy_path.read_bytes())

        with self.assertRaisesRegex(
            facts_builder.VocFactBuildError,
            "must not overlap",
        ):
            build_voc_fact_bundle(
                canonical_root=canonical_root,
                canonical_manifest_sha256="1" * 64,
                canonical_validation_receipt=canonical_receipt,
                canonical_validation_receipt_sha256="2" * 64,
                eligibility_policy_path=policy_path,
                eligibility_policy_sha256=policy_sha,
                period="snapshot:boundary",
                scope="all",
                output_root=canonical_root / "voc-output",
                project_root=ROOT,
            )

        with self.assertRaisesRegex(
            VocFactValidationError,
            "receipt must not overlap the canonical bundle",
        ):
            validate_voc_fact_bundle(
                bundle_root=PRIVATE_ROOT / "boundary-voc-output",
                expected_manifest_sha256="3" * 64,
                canonical_root=canonical_root,
                expected_canonical_manifest_sha256="1" * 64,
                canonical_validation_receipt=canonical_receipt,
                expected_canonical_validation_receipt_sha256="2" * 64,
                eligibility_policy_path=policy_path,
                expected_eligibility_policy_sha256=policy_sha,
                project_root=ROOT,
                receipt_path=canonical_root / "facts-receipt.json",
            )


if __name__ == "__main__":
    unittest.main()
