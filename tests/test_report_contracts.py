from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from reddit_voc.report_contracts import (
    AttemptBudget,
    canonical_json_bytes,
    load_and_validate_schema,
    load_regular_json,
    load_report_schema_assets,
    load_translation_terms_document,
    read_regular_utf8,
    sha256_hex,
    validate_schema_instance,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "config"


def _zero_usage() -> dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "total_tokens": 0,
    }


def _valid_manifest() -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema_version": "daily-translation-manifest-v1",
        "manifest_id": "manifest-20260713",
        "run_id": "daily_collect_20260713_0700",
        "provider": "deepseek",
        "requested_model": "deepseek-v4-flash",
        "prompt_version": digest,
        "validator_prompt_version": "b" * 64,
        "translation_cache_key": "c" * 64,
        "validator_cache_key": "d" * 64,
        "translation_output_sha256": "e" * 64,
        "validator_output_sha256": "f" * 64,
        "translation_input_fingerprint": "1" * 64,
        "report_input_fingerprint": "2" * 64,
        "status": "complete",
        "provider_call": False,
        "translation_provider_call": False,
        "translation_provider_attempt_made": False,
        "translation_phase_attempt_made": False,
        "semantic_validation_phase_attempt_made": False,
        "translation_reused": False,
        "semantic_validation_reused": False,
        "request_count": 0,
        "retry_count": 0,
        "duration_ms": 0,
        "usage": _zero_usage(),
        "responses": [],
        "counts": {
            "posts": 0,
            "titles": 0,
            "bodies": 0,
            "comments": 0,
            "items": 0,
        },
        "items": [],
        "provider_authorization_id": None,
    }


def _valid_attempt() -> dict[str, object]:
    return {
        "schema_version": "daily-translation-attempt-v1",
        "attempt_id": "attempt-20260713",
        "run_id": "daily_collect_20260713_0700",
        "status": "blocked",
        "stage": "translation",
        "reason_codes": ["translation_schema_invalid"],
        "provider_call": False,
        "translation_provider_call": False,
        "translation_provider_attempt_made": False,
        "translation_phase_attempt_made": False,
        "semantic_validation_phase_attempt_made": False,
        "request_count": 0,
        "retry_count": 0,
        "duration_ms": 0,
        "usage": _zero_usage(),
        "responses": [],
        "counts": {"posts": 1, "items": 1},
        "items": [
            {
                "stable_id": "post:abc:title",
                "input_sha256": "a" * 64,
                "status": "blocked",
                "error_codes": ["translation_schema_invalid"],
            }
        ],
        "provider_authorization_id": None,
    }


def _valid_index() -> dict[str, object]:
    return {
        "schema_version": "daily-prepared-bundle-index-v1",
        "artifact_version_id": "20260713T000000000000Z-" + "a" * 32,
        "entries": [
            {
                "scope": "private",
                "relative_path": "manifests/translation.json",
                "byte_size": 2,
                "sha256": "a" * 64,
            },
            {
                "scope": "public",
                "relative_path": "daily-detail.csv",
                "byte_size": 3,
                "sha256": "b" * 64,
            },
        ],
    }


class CanonicalJsonTests(unittest.TestCase):
    def test_canonical_json_bytes_are_stable_utf8(self) -> None:
        value = {"z": 1, "中文": "值", "a": [True, None]}
        expected = '{"a":[true,null],"z":1,"中文":"值"}'.encode("utf-8")
        self.assertEqual(canonical_json_bytes(value), expected)
        self.assertEqual(sha256_hex(expected), __import__("hashlib").sha256(expected).hexdigest())

    def test_canonical_json_rejects_non_finite_numbers(self) -> None:
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})


class TrustedAssetTests(unittest.TestCase):
    def test_regular_utf8_and_json_reject_symlink_duplicate_keys_and_bad_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "good.json"
            good.write_text('{"a":1}\n', encoding="utf-8")
            self.assertEqual(read_regular_utf8(trusted_root=root, path=good), '{"a":1}\n')
            self.assertEqual(load_regular_json(trusted_root=root, path=good), {"a": 1})

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
                load_regular_json(trusted_root=root, path=duplicate)

            bad_utf8 = root / "bad.json"
            bad_utf8.write_bytes(b"\xff")
            with self.assertRaisesRegex(ValueError, "invalid_utf8"):
                read_regular_utf8(trusted_root=root, path=bad_utf8)

            symlink = root / "linked.json"
            symlink.symlink_to(good.name)
            with self.assertRaisesRegex(ValueError, "not_regular_file"):
                load_regular_json(trusted_root=root, path=symlink)

    def test_trusted_reader_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "trusted"
            root.mkdir()
            outside = parent / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "path_outside_trusted_root"):
                load_regular_json(trusted_root=root, path=root / ".." / "outside.json")


class MinimalSchemaTests(unittest.TestCase):
    def test_minimal_schema_subset_and_bool_number_rejection(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["count", "name", "optional"],
            "properties": {
                "count": {"type": "integer", "minimum": 0},
                "name": {"type": "string", "minLength": 1, "pattern": "^[a-z]+$"},
                "optional": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        }
        validate_schema_instance(schema=schema, value={"count": 0, "name": "ok", "optional": None})
        for bad in [
            {"count": True, "name": "ok", "optional": None},
            {"count": 0, "name": "", "optional": None},
            {"count": 0, "name": "OK", "optional": None},
            {"count": 0, "name": "ok", "optional": None, "extra": 1},
        ]:
            with self.assertRaises(ValueError):
                validate_schema_instance(schema=schema, value=bad)

    def test_schema_rejects_unsupported_keywords_and_unions(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_schema_keyword"):
            validate_schema_instance(schema={"type": "string", "maxLength": 3}, value="x")
        with self.assertRaisesRegex(ValueError, "unsupported_type_union"):
            validate_schema_instance(schema={"type": ["integer", "null"]}, value=None)

    def test_schema_loader_rejects_unknown_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "schema.json"
            path.write_text(
                json.dumps(
                    {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "$id": "unknown-schema-v1",
                        "type": "object",
                        "required": [],
                        "properties": {},
                        "additionalProperties": False,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown_schema_version"):
                load_and_validate_schema(trusted_root=root, schema_path=path, value={})


class CommittedAssetTests(unittest.TestCase):
    def test_prompts_and_terms_are_versioned_and_strict(self) -> None:
        translation_prompt = read_regular_utf8(
            trusted_root=CONFIG_ROOT,
            path=CONFIG_ROOT / "prompts" / "deepseek-translation-v1.txt",
        )
        validator_prompt = read_regular_utf8(
            trusted_root=CONFIG_ROOT,
            path=CONFIG_ROOT / "prompts" / "deepseek-semantic-validator-v1.txt",
        )
        self.assertIn("json", translation_prompt)
        self.assertIn("json", validator_prompt)
        self.assertIn('{"translations":[{"id":"post:abc:title","zh":"中文译文"}]}', translation_prompt)
        self.assertIn(
            '{"verdicts":[{"id":"post:abc:title","meaning_preserved":true',
            validator_prompt,
        )

        terms = load_translation_terms_document(config_root=CONFIG_ROOT)
        self.assertEqual(
            set(terms),
            {
                "schema_version",
                "preserve_exact",
                "case_sensitive_terms",
                "case_insensitive_terms",
                "model_patterns",
                "unit_patterns",
                "allow_source_equal_patterns",
                "source_signal_rules",
            },
        )
        self.assertEqual(terms["schema_version"], "translation-terms-v1")
        self.assertEqual(set(terms["source_signal_rules"]), {"negation", "comparison", "sentiment"})
        for key in [
            "preserve_exact",
            "case_sensitive_terms",
            "case_insensitive_terms",
            "model_patterns",
            "unit_patterns",
            "allow_source_equal_patterns",
        ]:
            values = terms[key]
            self.assertEqual(values, sorted(set(values)))
        for key in ["negation", "comparison", "sentiment"]:
            values = terms["source_signal_rules"][key]
            self.assertEqual(values, sorted(set(values)))
        for key in ["model_patterns", "unit_patterns", "allow_source_equal_patterns"]:
            for pattern in terms[key]:
                re.compile(pattern)

    def test_terms_loader_rejects_unknown_keys_duplicates_and_bad_regex(self) -> None:
        valid = {
            "schema_version": "translation-terms-v1",
            "preserve_exact": [],
            "case_sensitive_terms": [],
            "case_insensitive_terms": [],
            "model_patterns": [],
            "unit_patterns": [],
            "allow_source_equal_patterns": [],
            "source_signal_rules": {"negation": [], "comparison": [], "sentiment": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "translation_terms.json").write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(load_translation_terms_document(config_root=root), valid)

            unknown = {**valid, "unknown": []}
            (root / "translation_terms.json").write_text(json.dumps(unknown), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "translation_terms_keys_invalid"):
                load_translation_terms_document(config_root=root)

            duplicate = {**valid, "preserve_exact": ["Momcozy", "Momcozy"]}
            (root / "translation_terms.json").write_text(json.dumps(duplicate), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "translation_terms_not_sorted_unique"):
                load_translation_terms_document(config_root=root)

            bad_regex = {**valid, "model_patterns": ["["]}
            (root / "translation_terms.json").write_text(json.dumps(bad_regex), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "translation_terms_invalid_regex"):
                load_translation_terms_document(config_root=root)

    def test_committed_schemas_accept_exact_instances_and_reject_drift(self) -> None:
        assets = load_report_schema_assets(config_root=CONFIG_ROOT)
        fixtures = [
            (assets.manifest_schema, _valid_manifest()),
            (assets.attempt_schema, _valid_attempt()),
            (assets.bundle_index_schema, _valid_index()),
        ]
        self.assertEqual(
            set(assets.sha256_by_name),
            {
                "daily-translation-manifest-v1.schema.json",
                "daily-translation-attempt-v1.schema.json",
                "daily-prepared-bundle-index-v1.schema.json",
            },
        )
        for schema, fixture in fixtures:
            validate_schema_instance(schema=schema, value=fixture)
            with self.assertRaises(ValueError):
                validate_schema_instance(schema=schema, value={**fixture, "unexpected": True})
            missing = dict(fixture)
            missing.pop(next(iter(schema["required"])))
            with self.assertRaises(ValueError):
                validate_schema_instance(schema=schema, value=missing)

        wrong = _valid_manifest()
        wrong["request_count"] = True
        with self.assertRaises(ValueError):
            validate_schema_instance(schema=assets.manifest_schema, value=wrong)

        unsorted_index = _valid_index()
        unsorted_index["entries"] = list(reversed(unsorted_index["entries"]))
        with self.assertRaisesRegex(ValueError, "bundle_index_entries_not_sorted"):
            validate_schema_instance(schema=assets.bundle_index_schema, value=unsorted_index)

        self_index = _valid_index()
        self_index["entries"][0]["relative_path"] = "daily-prepared-bundle-index-v1.schema.json"
        with self.assertRaisesRegex(ValueError, "bundle_index_lists_itself"):
            validate_schema_instance(schema=assets.bundle_index_schema, value=self_index)


class AttemptBudgetTests(unittest.TestCase):
    def test_attempt_budget_reserves_before_use_and_caps_at_100(self) -> None:
        reservations: list[tuple[int, str]] = []

        def sink(*, sequence: int, phase: str) -> None:
            reservations.append((sequence, phase))

        budget = AttemptBudget(max_attempts=2, reservation_sink=sink)
        self.assertEqual(budget.reserve("translation"), 1)
        self.assertEqual(budget.reserve("semantic_validation"), 2)
        self.assertEqual(budget.used, 2)
        self.assertEqual(reservations, [(1, "translation"), (2, "semantic_validation")])
        with self.assertRaisesRegex(RuntimeError, "attempt_budget_exhausted"):
            budget.reserve("translation")

        for invalid in [0, 101]:
            with self.assertRaises(ValueError):
                AttemptBudget(max_attempts=invalid)


if __name__ == "__main__":
    unittest.main()
