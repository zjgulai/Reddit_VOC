from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tarfile
import unittest

from reddit_voc import backfill_cli
from reddit_voc.keywords import keyword_rules_sha256, keyword_rules_snapshot
from reddit_voc.search_config import (
    DEFAULT_REVIEWED_SUBREDDITS,
    DEFAULT_TIKHUB_SEARCH_TERMS,
)
from reddit_voc.time_window import historical_natural_day_window


class BackfillContractTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]
    historical_source_archive = (
        root
        / "config/backfill/archive/momcozy-backfill-reviewed-files-20260711.tar.gz"
    )

    @staticmethod
    def canonical_bytes(value: object) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )

    def test_window_is_beijing_left_closed_right_open(self):
        window = historical_natural_day_window(
            start_date=date(2025, 1, 1),
            end_date_inclusive=date(2026, 7, 11),
            effective_end_utc=datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(window.start_utc.isoformat(), "2024-12-31T16:00:00+00:00")
        self.assertEqual(window.end_utc.isoformat(), "2026-07-11T04:17:09+00:00")
        self.assertTrue(window.contains_utc(window.start_utc))
        self.assertFalse(window.contains_utc(window.end_utc))

    def test_effective_end_cannot_exceed_requested_end(self):
        with self.assertRaisesRegex(ValueError, "effective_end_utc exceeds requested end"):
            historical_natural_day_window(
                start_date=date(2025, 1, 1),
                end_date_inclusive=date(2026, 7, 11),
                effective_end_utc=datetime(2026, 7, 12, tzinfo=timezone.utc),
            )

    def test_runtime_rules_have_a_stable_hash(self):
        self.assertEqual(keyword_rules_snapshot()["brands"]["Momcozy"][0], "momcozy")
        self.assertIn('"wearable pump"', DEFAULT_TIKHUB_SEARCH_TERMS)
        self.assertEqual(len(keyword_rules_sha256()), 64)

    def test_search_terms_are_the_exact_immutable_daily_contract(self):
        self.assertIsInstance(DEFAULT_TIKHUB_SEARCH_TERMS, tuple)
        self.assertEqual(
            DEFAULT_TIKHUB_SEARCH_TERMS,
            (
                "Momcozy",
                "momcozy",
                '"Momcozy"',
                '"momcozy"',
                '"mom cozy"',
                '"Momcozy M5"',
                '"Momcozy S12"',
                '"Momcozy M9"',
                '"Momcozy KleanPal"',
                '"Momcozy bottle washer"',
                '"Momcozy baby carrier"',
                '"Momcozy PureHug"',
                '"wearable pump"',
                '"breast pump"',
                '"bottle washer"',
            ),
        )

    def test_reviewed_release_bundle_is_exact_canonical_and_self_consistent(self):
        baseline_path = self.root / backfill_cli.SEED_BASELINE_RELATIVE_PATH
        cursor_path = self.root / backfill_cli.COMMENT_CURSOR_RELATIVE_PATH
        manifest_path = self.root / backfill_cli.RELEASE_MANIFEST_RELATIVE_PATH

        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        self.assertEqual(baseline_path.read_bytes(), self.canonical_bytes(baseline))
        self.assertEqual(
            set(baseline),
            {
                "schema_version",
                "files_total",
                "files_imported",
                "files_outside_window",
                "files_excluded",
                "files_duplicate",
                "parse_errors",
                "threads",
                "comments",
                "analyses",
                "coverage_full",
                "coverage_partial",
                "coverage_post_only",
                "source_inventory_sha256",
                "known_partial_post_ids_sha256",
                "reviewed_search_terms_sha256",
                "reviewed_subreddits",
                "reviewed_subreddits_sha256",
                "baseline_sha256",
            },
        )
        self.assertEqual(
            {
                key: baseline[key]
                for key in (
                    "files_total",
                    "files_imported",
                    "files_outside_window",
                    "files_excluded",
                    "files_duplicate",
                    "parse_errors",
                    "threads",
                    "comments",
                    "analyses",
                    "coverage_full",
                    "coverage_partial",
                    "coverage_post_only",
                )
            },
            {
                "files_total": 55,
                "files_imported": 48,
                "files_outside_window": 7,
                "files_excluded": 0,
                "files_duplicate": 0,
                "parse_errors": 0,
                "threads": 48,
                "comments": 1894,
                "analyses": 1942,
                "coverage_full": 45,
                "coverage_partial": 3,
                "coverage_post_only": 0,
            },
        )
        self.assertEqual(
            baseline["source_inventory_sha256"],
            "af39a40c8ed657f440f9db6595d5f4e8e4a26164f43ffa78373215b40b3e881b",
        )
        self.assertEqual(
            baseline["known_partial_post_ids_sha256"],
            "1664b77cb94992959a0dc638d25580aad41aa65e8665462490c78d5220532769",
        )
        self.assertEqual(
            baseline["reviewed_subreddits"], list(DEFAULT_REVIEWED_SUBREDDITS)
        )
        self.assertEqual(
            baseline["reviewed_search_terms_sha256"],
            backfill_cli._canonical_sha256(list(DEFAULT_TIKHUB_SEARCH_TERMS)),
        )
        self.assertEqual(
            baseline["reviewed_subreddits_sha256"],
            backfill_cli._canonical_sha256(list(DEFAULT_REVIEWED_SUBREDDITS)),
        )
        semantic_baseline = dict(baseline)
        baseline_sha = semantic_baseline.pop("baseline_sha256")
        self.assertEqual(
            baseline_sha, backfill_cli._canonical_sha256(semantic_baseline)
        )
        self.assertEqual(
            baseline_sha,
            "982c3ba2ef3d21963a99ed7d587308c36dc145159b9ba559181ebef5bb1072cf",
        )

        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        self.assertEqual(cursor_path.read_bytes(), self.canonical_bytes(cursor))
        self.assertEqual(
            cursor,
            {
                "schema_version": "tikhub_comment_cursor_contract_v1",
                "cursor_path": [
                    "data",
                    "postInfoById",
                    "commentForest",
                    "pageInfo",
                    "endCursor",
                ],
                "cursor_schema_sha256": (
                    backfill_cli.REVIEWED_COMMENT_CURSOR_SCHEMA_SHA256
                ),
            },
        )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_path.read_bytes(), self.canonical_bytes(manifest))
        self.assertEqual(
            set(manifest),
            {
                "schema_version",
                "run_id",
                "seed_baseline",
                "reviewed_files_sha256",
            },
        )
        self.assertEqual(
            manifest["schema_version"], "momcozy_backfill_release_manifest_v1"
        )
        self.assertEqual(
            manifest["run_id"], "backfill_momcozy_20250101_20260711"
        )
        reviewed = manifest["reviewed_files_sha256"]
        self.assertEqual(set(reviewed), set(backfill_cli.RELEASE_REVIEWED_PATHS))
        self.assertNotIn(backfill_cli.RELEASE_MANIFEST_RELATIVE_PATH, reviewed)
        with tarfile.open(self.historical_source_archive, mode="r:gz") as archive:
            members = archive.getmembers()
            self.assertEqual({member.name for member in members}, set(reviewed))
            for member in members:
                with self.subTest(relative_path=member.name):
                    self.assertTrue(member.isfile())
                    self.assertNotIn(
                        Path(member.name).suffix.lower(), {".env", ".pem", ".key"}
                    )
                    extracted = archive.extractfile(member)
                    self.assertIsNotNone(extracted)
                    self.assertEqual(
                        sha256(extracted.read()).hexdigest(), reviewed[member.name]
                    )
        self.assertEqual(
            manifest["seed_baseline"],
            {
                "relative_path": backfill_cli.SEED_BASELINE_RELATIVE_PATH,
                "sha256": reviewed[backfill_cli.SEED_BASELINE_RELATIVE_PATH],
            },
        )


if __name__ == "__main__":
    unittest.main()
