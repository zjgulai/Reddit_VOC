from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.backfill_profile import BackfillProfileError, load_v2_search_profile


class V2SearchProfileTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]
    profile_path = root / "config/backfill/momcozy-search-profile-v2-candidate-20260714.json"
    profile_sha256 = "38706378f42c6648fe43bb50f60947863816363d65714f16a3092f40d91b604d"

    def test_reviewed_profile_is_hash_pinned_and_preserves_legacy_isolation(self):
        profile = load_v2_search_profile(
            self.profile_path, expected_sha256=self.profile_sha256
        )

        self.assertEqual(profile.sha256, self.profile_sha256)
        self.assertEqual(profile.legacy_run_id, "backfill_momcozy_20250101_20260711")
        self.assertEqual(len(profile.candidate_terms), 75)
        self.assertEqual(len(profile.delta_terms), 69)
        self.assertEqual(profile.delta_terms[0], '"mcozy"')
        self.assertEqual(profile.delta_terms[-1], '"white noise machine"')
        self.assertNotIn('"Momcozy M5"', profile.delta_terms)
        self.assertEqual(len(set(profile.candidate_terms)), 75)

    def test_hash_mismatch_fails_closed(self):
        with self.assertRaisesRegex(
            BackfillProfileError, r"\Av2_profile_sha256_mismatch\Z"
        ):
            load_v2_search_profile(self.profile_path, expected_sha256="0" * 64)

    def test_unknown_top_level_field_fails_closed(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            value = json.loads(self.profile_path.read_text(encoding="utf-8"))
            value["unreviewed"] = True
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(
                BackfillProfileError, r"\Av2_profile_fields_invalid\Z"
            ):
                load_v2_search_profile(path)

    def test_delta_drift_fails_closed(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            value = json.loads(self.profile_path.read_text(encoding="utf-8"))
            value["delta_terms"][0] = '"not-reviewed"'
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(
                BackfillProfileError, r"\Av2_profile_delta_terms_not_candidates\Z"
            ):
                load_v2_search_profile(path)

    def test_expected_hash_must_be_lowercase_sha256(self):
        with self.assertRaisesRegex(
            BackfillProfileError, r"\Av2_profile_expected_sha256_invalid\Z"
        ):
            load_v2_search_profile(self.profile_path, expected_sha256="bad")

        self.assertEqual(
            sha256(self.profile_path.read_bytes()).hexdigest(), self.profile_sha256
        )


if __name__ == "__main__":
    unittest.main()
