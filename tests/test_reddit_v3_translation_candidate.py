from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reddit_voc.report_contracts import AttemptBudget, AttemptEvidence, TokenUsage
from reddit_voc.translation_pipeline import load_translation_runtime_assets
from scripts.build_reddit_v3_translation_candidate import (
    TranslationCandidateError,
    _append_jsonl,
    _load_api_key,
    _request_with_split,
    build_translation_items,
    run,
)
from scripts.validate_reddit_v3_translation_candidate import validate_candidate
from scripts.stage_reddit_v3_translation_preview import stage_preview


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class _Completion:
    def __init__(self, *, content: str, sequence: int) -> None:
        usage = TokenUsage(20, 10, 0, 20, 30)
        self.request_id = f"test-request-{sequence}"
        self.model = "deepseek-v4-flash"
        self.system_fingerprint = "fixture"
        self.finish_reason = "stop"
        self.content = content
        self.usage = usage
        self.attempts = (
            AttemptEvidence(
                sequence=sequence,
                phase="translation",
                http_status=200,
                outcome="success",
                retryable=False,
                duration_ms=1,
                response_id=self.request_id,
                actual_model=self.model,
                system_fingerprint=self.system_fingerprint,
                finish_reason=self.finish_reason,
                usage=usage,
            ),
        )


class _FakeClient:
    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        translations = [
            {"id": item["id"], "zh": f"中文翻译：{item['source_text']}"}
            for item in user_payload["items"]
        ]
        return _Completion(
            content=json.dumps({"translations": translations}, ensure_ascii=False),
            sequence=sequence,
        )


class _SplitFailureClient:
    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        items = user_payload["items"]
        if len(items) == 1 and items[0]["item_type"] == "title":
            translations = [
                {"id": items[0]["id"], "zh": f"中文翻译：{items[0]['source_text']}"}
            ]
        else:
            translations = [
                {"id": item["id"], "zh": item["source_text"]} for item in items
            ]
        return _Completion(
            content=json.dumps({"translations": translations}, ensure_ascii=False),
            sequence=sequence,
        )


class _PartialSalvageClient:
    def __init__(self) -> None:
        self.requested_ids: list[tuple[str, ...]] = []

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        items = user_payload["items"]
        self.requested_ids.append(tuple(item["id"] for item in items))
        translations = [
            {
                "id": item["id"],
                "zh": (
                    f"中文翻译：{item['source_text']}"
                    if item["item_type"] == "title"
                    else item["source_text"]
                ),
            }
            for item in items
        ]
        return _Completion(
            content=json.dumps({"translations": translations}, ensure_ascii=False),
            sequence=sequence,
        )


class _RecoveringPartialSalvageClient:
    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        items = user_payload["items"]
        translations = [
            {
                "id": item["id"],
                "zh": (
                    f"中文翻译：{item['source_text']}"
                    if len(items) == 1 or index == 0
                    else item["source_text"]
                ),
            }
            for index, item in enumerate(items)
        ]
        return _Completion(
            content=json.dumps({"translations": translations}, ensure_ascii=False),
            sequence=sequence,
        )


class _PlaceholderFallbackClient:
    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        item = user_payload["items"][0]
        source = item["source_text"]
        translated = (
            "中文但占位符被改变"
            if "[[RVOC_P_" in source
            else "Momcozy M5 很好"
        )
        return _Completion(
            content=json.dumps(
                {"translations": [{"id": item["id"], "zh": translated}]},
                ensure_ascii=False,
            ),
            sequence=sequence,
        )


class _RedditUnavailablePlaceholderRetryClient:
    def __init__(self) -> None:
        self.calls = 0
        self.sources: list[str] = []

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.calls += 1
        item = user_payload["items"][0]
        self.sources.append(item["source_text"])
        translated = item["source_text"] if self.calls == 1 else "已移除"
        return _Completion(
            content=json.dumps(
                {"translations": [{"id": item["id"], "zh": translated}]},
                ensure_ascii=False,
            ),
            sequence=sequence,
        )


class _ProtectedRawProtectedRetryClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.calls += 1
        item = user_payload["items"][0]
        source = item["source_text"]
        if self.calls == 1:
            translated = "中文但改坏了保护标记"
        elif self.calls == 2:
            translated = "中文但遗漏了受保护实体"
        else:
            translated = f"中文翻译：{source}"
        return _Completion(
            content=json.dumps(
                {"translations": [{"id": item["id"], "zh": translated}]},
                ensure_ascii=False,
            ),
            sequence=sequence,
        )


class _ChunkedFallbackClient:
    def __init__(self) -> None:
        self.calls = 0
        self.final_batch_size = 0

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.calls += 1
        items = user_payload["items"]
        if self.calls in {1, 3}:
            translations = [
                {"id": item["id"], "zh": "中文但改坏了保护标记"}
                for item in items
            ]
        elif self.calls == 2:
            translations = [
                {"id": item["id"], "zh": "中文但遗漏了受保护实体"}
                for item in items
            ]
        else:
            self.final_batch_size = len(items)
            translations = [
                {"id": item["id"], "zh": f"中文翻译：{item['source_text']}"}
                for item in items
            ]
        return _Completion(
            content=json.dumps({"translations": translations}, ensure_ascii=False),
            sequence=sequence,
        )


class _SlangSourceEqualRetryClient:
    def __init__(self) -> None:
        self.sources: list[str] = []

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        item = user_payload["items"][0]
        self.sources.append(item["source_text"])
        translated = (
            item["source_text"]
            if len(self.sources) == 1
            else "Momcozy 搞什么鬼 😩"
        )
        return _Completion(
            content=json.dumps(
                {"translations": [{"id": item["id"], "zh": translated}]},
                ensure_ascii=False,
            ),
            sequence=sequence,
        )


class _OpaqueLinkFormattingClient:
    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        item = user_payload["items"][0]
        return _Completion(
            content=json.dumps(
                {
                    "translations": [
                        {
                            "id": item["id"],
                            "zh": "https://www.babylist.com/store/sale",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            sequence=sequence,
        )


class _NormalizedSourceEqualRetryClient:
    def __init__(self, translated: str) -> None:
        self.translated = translated
        self.sources: list[str] = []

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        item = user_payload["items"][0]
        self.sources.append(item["source_text"])
        translated = item["source_text"] if len(self.sources) == 1 else self.translated
        return _Completion(
            content=json.dumps(
                {"translations": [{"id": item["id"], "zh": translated}]},
                ensure_ascii=False,
            ),
            sequence=sequence,
        )


class _SingleInvalidJsonRetryClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.calls += 1
        if self.calls == 1:
            content = "not-json"
        else:
            item = user_payload["items"][0]
            content = json.dumps(
                {
                    "translations": [
                        {"id": item["id"], "zh": "这是一条有效的中文翻译。"}
                    ]
                },
                ensure_ascii=False,
            )
        return _Completion(content=content, sequence=sequence)


class _InvalidJsonThenChunkedClient:
    def __init__(self) -> None:
        self.calls = 0
        self.final_batch_size = 0

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.calls += 1
        items = user_payload["items"]
        if self.calls <= 2:
            content = "not-json"
        else:
            self.final_batch_size = len(items)
            content = json.dumps(
                {
                    "translations": [
                        {
                            "id": item["id"],
                            "zh": f"中文翻译：{item['source_text']}",
                        }
                        for item in items
                    ]
                },
                ensure_ascii=False,
            )
        return _Completion(content=content, sequence=sequence)


class _ProtectedThenRawChunkedClient:
    def __init__(self) -> None:
        self.calls = 0
        self.final_batch_size = 0

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.calls += 1
        items = user_payload["items"]
        if self.calls in {1, 3, 4}:
            translations = [
                {"id": item["id"], "zh": "中文但改坏了保护标记"}
                for item in items
            ]
        elif self.calls == 2:
            translations = [
                {"id": item["id"], "zh": "中文但遗漏受保护实体"}
                for item in items
            ]
        else:
            self.final_batch_size = len(items)
            translations = [
                {"id": item["id"], "zh": f"中文翻译：{item['source_text']}"}
                for item in items
            ]
        return _Completion(
            content=json.dumps({"translations": translations}, ensure_ascii=False),
            sequence=sequence,
        )


class RedditV3TranslationCandidateTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        posts = [
            {
                "post_id": "p1",
                "title": "Momcozy pump review 2",
                "content": "I like Momcozy 2 times.",
            }
        ]
        comments = [
            {
                "comment_id": "c1",
                "post_id": "p1",
                "body": "Momcozy is better than model 2.",
            }
        ]
        payloads = {
            "posts-public.json": posts,
            "comments-public.json": comments,
            "aggregates-public.json": {},
            "tag-dictionary-public.json": {},
        }
        for name, value in payloads.items():
            (source / name).write_text(
                json.dumps(value, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        manifest = {
            "schema_version": "reddit_voc_site_snapshot_manifest_v3",
            "dataset_version": "reddit_voc_site_snapshot_fixture_source",
            "generated_at_utc": "2026-08-09T00:00:00Z",
            "status": "validated_candidate",
            "artifact_stage": "public_candidate",
            "consumption_status": "eligible_for_current_release_candidate_binding",
            "promotable": True,
            "provider_call": False,
            "all_checks_passed": True,
            "production_unchanged": True,
            "database_write": False,
            "remote_write": False,
            "deploy": False,
            "live_send": False,
            "boundaries": {
                "database_write": False,
                "deploy": False,
                "live_send": False,
                "production_unchanged": True,
                "provider_call": False,
                "remote_write": False,
            },
            "canonical_counts": {"posts": 1, "linked_comments": 1},
            "files": {
                name: {"bytes": (source / name).stat().st_size, "sha256": _sha(source / name)}
                for name in payloads
            },
        }
        (source / "manifest-public.json").write_text(
            json.dumps(manifest, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return source

    def _args(self, root: Path, source: Path, *, authorize: bool) -> argparse.Namespace:
        return argparse.Namespace(
            source_root=source,
            work_root=root / "work",
            output_root=root / "candidate",
            dataset_version="reddit_voc_site_snapshot_fixture_zh_deepseek",
            provider_authorization_id="reddit_voc_p2d2_translation_20260809",
            generated_at_utc="2026-08-09T14:00:00Z",
            include_comments=True,
            allow_partial_comments=False,
            partial_comments_reason=None,
            authorize_provider_call=authorize,
            batch_size=24,
            max_source_chars=24000,
            max_provider_requests=100,
            request_timeout_seconds=60.0,
            api_key_file=None,
            workers=1,
        )

    def test_builds_hash_bound_translation_sidecars_and_reuses_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            args = self._args(root, source, authorize=True)
            result = run(args, client=_FakeClient())
            self.assertEqual(result["status"], "complete")
            self.assertTrue(result["provider_call"])
            manifest = json.loads((args.output_root / "manifest-public.json").read_text())
            self.assertTrue(manifest["provider_call"])
            self.assertFalse(manifest["promotable"])
            self.assertEqual(manifest["translations"]["coverage"]["translated_items"], 3)
            self.assertEqual(manifest["translations"]["coverage"]["comments_status"], "complete")
            post_sidecar = json.loads(
                (args.output_root / "post-translations-public.json").read_text()
            )
            comment_sidecar = json.loads(
                (args.output_root / "comment-translations-public.json").read_text()
            )
            self.assertIn("中文翻译", post_sidecar["items"][0]["title_zh"])
            self.assertIn("中文翻译", comment_sidecar["items"][0]["zh"])
            for name in (
                "post-translations-public.json",
                "comment-translations-public.json",
            ):
                self.assertEqual(manifest["files"][name]["sha256"], _sha(args.output_root / name))
            validation = validate_candidate(
                source_root=source,
                candidate_root=args.output_root,
                checkpoint_path=args.work_root / "translations-checkpoint.jsonl",
                attempt_log_path=args.work_root / "provider-attempts.jsonl",
                expected_authorization_id=args.provider_authorization_id,
            )
            self.assertEqual(validation["status"], "passed_local_candidate_only")
            self.assertEqual(validation["translated_items"], 3)
            self.assertTrue(
                validation["checks"]["deterministic_translation_gate_passed"]
            )
            self.assertTrue(validation["checks"]["complete_comment_coverage"])

    def test_builds_explicit_partial_comment_candidate_from_complete_posts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            args = self._args(root, source, authorize=True)
            args.include_comments = False
            args.output_root = root / "post-only-candidate"
            first = run(args, client=_FakeClient())
            self.assertEqual(first["status"], "complete")

            first_attempt = json.loads(
                (args.work_root / "provider-attempts.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            _append_jsonl(
                args.work_root / "provider-attempts.jsonl",
                {
                    "schema_version": first_attempt["schema_version"],
                    "provider_authorization_id": first_attempt[
                        "provider_authorization_id"
                    ],
                    "source_manifest_sha256": first_attempt[
                        "source_manifest_sha256"
                    ],
                    "translation_prompt_sha256": first_attempt[
                        "translation_prompt_sha256"
                    ],
                    "translation_terms_sha256": first_attempt[
                        "translation_terms_sha256"
                    ],
                    "sequence": 999,
                    "phase": "translation",
                    "http_status": 402,
                    "outcome": "http_status_402",
                    "retryable": False,
                    "duration_ms": 1,
                    "response_id": None,
                    "actual_model": "deepseek-v4-flash",
                    "system_fingerprint": None,
                    "finish_reason": None,
                    "usage": None,
                },
            )

            args.include_comments = True
            args.authorize_provider_call = False
            args.output_root = root / "partial-candidate"
            args.allow_partial_comments = True
            args.partial_comments_reason = "provider_http_402_balance_blocked"
            result = run(args)
            self.assertEqual(result["status"], "complete_post_coverage_partial_comments")
            self.assertEqual(result["comments_translated"], 0)
            self.assertEqual(result["comments_total"], 1)

            manifest = json.loads((args.output_root / "manifest-public.json").read_text())
            coverage = manifest["translations"]["coverage"]
            self.assertEqual(coverage["posts"], 1)
            self.assertEqual(coverage["comments"], 0)
            self.assertEqual(coverage["comments_total"], 1)
            self.assertEqual(coverage["comments_status"], "partial")
            self.assertEqual(
                coverage["comments_unavailable_reason"],
                "provider_http_402_balance_blocked",
            )
            validation = validate_candidate(
                source_root=source,
                candidate_root=args.output_root,
                checkpoint_path=args.work_root / "translations-checkpoint.jsonl",
                attempt_log_path=args.work_root / "provider-attempts.jsonl",
                expected_authorization_id=args.provider_authorization_id,
            )
            self.assertTrue(validation["checks"]["complete_post_coverage"])
            self.assertFalse(validation["checks"]["complete_comment_coverage"])

    def test_independent_validator_rejects_tampered_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            args = self._args(root, source, authorize=True)
            run(args, client=_FakeClient())
            sidecar_path = args.output_root / "post-translations-public.json"
            sidecar = json.loads(sidecar_path.read_text())
            sidecar["items"][0]["title_zh"] = "被篡改"
            sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False) + "\n")
            with self.assertRaisesRegex(
                TranslationCandidateError,
                "file_(bytes|sha256)_mismatch:post-translations-public.json",
            ):
                validate_candidate(
                    source_root=source,
                    candidate_root=args.output_root,
                    checkpoint_path=args.work_root / "translations-checkpoint.jsonl",
                    attempt_log_path=args.work_root / "provider-attempts.jsonl",
                    expected_authorization_id=args.provider_authorization_id,
                )

    def test_stages_an_isolated_preview_without_mutating_source_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            args = self._args(root, source, authorize=True)
            run(args, client=_FakeClient())
            validation = validate_candidate(
                source_root=source,
                candidate_root=args.output_root,
                checkpoint_path=args.work_root / "translations-checkpoint.jsonl",
                attempt_log_path=args.work_root / "provider-attempts.jsonl",
                expected_authorization_id=args.provider_authorization_id,
            )
            validation_path = root / "translation-validation.json"
            validation_path.write_text(
                json.dumps(validation, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            source_stage = root / "source-stage"
            pointer_path = source_stage / "public/data/reddit-voc/current-release.json"
            pointer_path.parent.mkdir(parents=True)
            source_manifest_sha = _sha(source / "manifest-public.json")
            pointer = {
                "schema_version": "reddit_voc_current_release_v2",
                "release_id": "reddit_voc_release_source_fixture",
                "generated_at_utc": "2026-08-09T13:00:00Z",
                "datasets": {
                    "base": {
                        "dataset_version": "reddit_voc_site_snapshot_fixture_source",
                        "manifest_path": "data/reddit-voc/reddit_voc_site_snapshot_fixture_source/manifest-public.json",
                        "public_manifest_sha256": source_manifest_sha,
                        "lineage_manifest_sha256": "a" * 64,
                    }
                },
            }
            pointer_path.write_text(json.dumps(pointer) + "\n", encoding="utf-8")
            source_base = (
                source_stage
                / "public/data/reddit-voc/reddit_voc_site_snapshot_fixture_source"
            )
            source_base.mkdir(parents=True)
            (source_base / "source-marker.txt").write_text("unchanged", encoding="utf-8")
            preview_root = root / "preview-stage"

            receipt = stage_preview(
                source_stage_root=source_stage,
                candidate_root=args.output_root,
                validation_receipt_path=validation_path,
                output_stage_root=preview_root,
                release_id="reddit_voc_release_translation_preview_fixture",
                generated_at_utc="2026-08-09T15:00:00Z",
            )

            preview_pointer = json.loads(
                (
                    preview_root / "public/data/reddit-voc/current-release.json"
                ).read_text()
            )
            self.assertEqual(receipt["status"], "staged_local_preview_only")
            self.assertEqual(
                preview_pointer["datasets"]["base"]["dataset_version"],
                args.dataset_version,
            )
            self.assertEqual(
                json.loads(pointer_path.read_text())["release_id"],
                "reddit_voc_release_source_fixture",
            )
            self.assertTrue(
                (
                    preview_root
                    / "public/data/reddit-voc"
                    / args.dataset_version
                    / "post-translations-public.json"
                ).is_file()
            )

    def test_missing_credential_blocks_before_provider_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            args = self._args(root, source, authorize=True)
            with patch.dict("os.environ", {}, clear=True):
                result = run(args)
            self.assertEqual(result["status"], "blocked_provider_credential_missing")
            self.assertFalse(result["provider_call"])
            self.assertFalse(args.output_root.exists())

    def test_api_key_file_must_be_owner_only_and_is_not_returned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "deepseek.key"
            key_path.write_text("fixture-secret\n", encoding="utf-8")
            key_path.chmod(0o644)
            with self.assertRaisesRegex(
                TranslationCandidateError,
                "deepseek_credential_file_permissions_unsafe",
            ):
                _load_api_key(key_path)
            key_path.chmod(0o600)
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(_load_api_key(key_path), "fixture-secret")

    def test_split_persists_successful_half_before_later_single_item_failure(self) -> None:
        posts = [
            {
                "post_id": "split",
                "title": "A useful pump",
                "content": "This sentence must be translated.",
            }
        ]
        items = build_translation_items(posts, [], include_comments=False)
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        with self.assertRaises(Exception):
            _request_with_split(
                client=_SplitFailureClient(),
                assets=load_translation_runtime_assets(
                    Path(__file__).resolve().parents[1] / "config"
                ),
                items=items,
                budget=AttemptBudget(max_attempts=10),
                timeout_seconds=60.0,
                on_error=errors.append,
                on_success=lambda translations, _completion: successes.append(
                    translations
                ),
            )

        self.assertEqual(len(successes), 1)
        self.assertEqual(set(successes[0]), {"post:split:title"})
        self.assertGreaterEqual(len(errors), 2)

    def test_batch_failure_salvages_valid_items_and_retries_only_failed_item(self) -> None:
        items = build_translation_items(
            [
                {
                    "post_id": "partial",
                    "title": "A useful pump",
                    "content": "This sentence must be translated.",
                }
            ],
            [],
            include_comments=False,
        )
        client = _PartialSalvageClient()
        partial_successes: list[dict[str, str]] = []

        with self.assertRaises(Exception):
            _request_with_split(
                client=client,
                assets=load_translation_runtime_assets(
                    Path(__file__).resolve().parents[1] / "config"
                ),
                items=items,
                budget=AttemptBudget(max_attempts=3),
                timeout_seconds=60.0,
                on_error=lambda _error: None,
                on_success=lambda _translations, _completion: None,
                on_partial_success=lambda translations, _completion: partial_successes.append(
                    translations
                ),
            )

        self.assertEqual(
            partial_successes,
            [{"post:partial:title": "中文翻译：A useful pump"}],
        )
        self.assertEqual(client.requested_ids[0], tuple(item.stable_id for item in items))
        self.assertTrue(
            all(
                requested == ("post:partial:content",)
                for requested in client.requested_ids[1:]
            )
        )

    def test_validator_binds_checkpoint_rows_from_partial_salvage_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            args = self._args(root, source, authorize=True)
            result = run(args, client=_RecoveringPartialSalvageClient())
            self.assertEqual(result["status"], "complete")
            attempts = [
                json.loads(line)
                for line in (args.work_root / "provider-attempts.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertTrue(
                any("accepted_translation_output_sha256" in row for row in attempts)
            )

            validation = validate_candidate(
                source_root=source,
                candidate_root=args.output_root,
                checkpoint_path=args.work_root / "translations-checkpoint.jsonl",
                attempt_log_path=args.work_root / "provider-attempts.jsonl",
                expected_authorization_id=args.provider_authorization_id,
            )
            self.assertEqual(validation["status"], "passed_local_candidate_only")
            self.assertEqual(validation["translated_items"], 3)

    def test_single_item_placeholder_failure_retries_raw_then_validates_entities(self) -> None:
        items = build_translation_items(
            [{"post_id": "fallback", "title": "Momcozy M5 is good", "content": ""}],
            [],
            include_comments=False,
        )
        title_item = (items[0],)
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=_PlaceholderFallbackClient(),
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=title_item,
            budget=AttemptBudget(max_attempts=3),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(successes, [{"post:fallback:title": "Momcozy M5 很好"}])
        self.assertEqual(len(errors), 1)

    def test_reddit_unavailable_placeholder_source_equal_retries_once(self) -> None:
        items = build_translation_items(
            [{"post_id": "removed", "title": "[removed]", "content": ""}],
            [],
            include_comments=False,
        )
        client = _RedditUnavailablePlaceholderRetryClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[0],),
            budget=AttemptBudget(max_attempts=2),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(successes, [{"post:removed:title": "已移除"}])
        self.assertEqual(client.calls, 2)
        self.assertEqual(
            client.sources,
            [
                "This Reddit content was removed.",
                "This Reddit content was removed.",
            ],
        )
        self.assertEqual(len(errors), 1)

    def test_protected_then_raw_entity_failure_retries_protected_once(self) -> None:
        items = build_translation_items(
            [{"post_id": "retry", "title": "Momcozy M5 is good", "content": ""}],
            [],
            include_comments=False,
        )
        client = _ProtectedRawProtectedRetryClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[0],),
            budget=AttemptBudget(max_attempts=3),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(
            successes,
            [{"post:retry:title": "中文翻译：Momcozy M5 is good"}],
        )
        self.assertEqual(client.calls, 3)
        self.assertEqual(len(errors), 2)

    def test_long_single_item_uses_one_response_chunked_fallback(self) -> None:
        content = (
            "Momcozy M5 costs $99 and works well.\n"
            "Elvie costs $199 and is another option.\n"
            "Read https://example.com/review for details."
        )
        items = build_translation_items(
            [{"post_id": "chunked", "title": "", "content": content}],
            [],
            include_comments=False,
        )
        client = _ChunkedFallbackClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[1],),
            budget=AttemptBudget(max_attempts=4),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(client.calls, 4)
        self.assertEqual(client.final_batch_size, 3)
        self.assertEqual(set(successes[0]), {"post:chunked:content"})
        self.assertIn("Momcozy M5", successes[0]["post:chunked:content"])
        self.assertIn("$199", successes[0]["post:chunked:content"])
        self.assertIn(
            "https://example.com/review",
            successes[0]["post:chunked:content"],
        )
        self.assertEqual(len(errors), 3)

    def test_source_equal_slang_expands_before_one_raw_retry(self) -> None:
        items = build_translation_items(
            [{"post_id": "slang", "title": "wtf momcozy 😩", "content": ""}],
            [],
            include_comments=False,
        )
        client = _SlangSourceEqualRetryClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[0],),
            budget=AttemptBudget(max_attempts=2),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(successes, [{"post:slang:title": "Momcozy 搞什么鬼 😩"}])
        self.assertIn("what the fuck momcozy", client.sources[1].casefold())
        self.assertEqual(len(errors), 1)

    def test_opaque_link_provider_formatting_is_canonicalized_to_source(self) -> None:
        source = (
            "[https://www.babylist.com/store/sale]"
            "(https://www.babylist.com/store/sale)"
        )
        items = build_translation_items(
            [{"post_id": "link", "title": source, "content": ""}],
            [],
            include_comments=False,
        )
        successes: list[dict[str, str]] = []

        _request_with_split(
            client=_OpaqueLinkFormattingClient(),
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[0],),
            budget=AttemptBudget(max_attempts=1),
            timeout_seconds=60.0,
            on_error=lambda error: self.fail(str(error)),
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(successes, [{"post:link:title": source}])

    def test_comparison_and_foreign_source_equal_get_narrow_normalized_retries(self) -> None:
        cases = (
            (
                "Momcozy bm03 vs Infant Optics DXR8 Pro",
                "Momcozy bm03 对比 Infant Optics DXR8 Pro",
                "compared with",
            ),
            ("Boppy deluxe", "Boppy 豪华版", "premium version"),
            ("pjs", "睡衣", "pajamas"),
            ("Bogos binted?", "照片打印了吗？", "photos been printed"),
            ("The titsoon?", "那个黑人？", "Black person"),
            (
                "Yağmur geliyor",
                "雨来了",
                "Translate this non-English text into Simplified Chinese:",
            ),
            ("Prime day", "亚马逊 Prime 会员日", "Amazon Prime Day shopping event"),
            (
                "Theetta case aanallo..",
                "这真是个烂摊子。",
                "Malayalam transliteration",
            ),
            (
                "LA JAX, ESTA DIVINA",
                "JAX 真是太棒了",
                "Spanish text",
            ),
            (
                "Come si può sostituire il Plumbus?",
                "如何替换 Plumbus？",
                "How can the Plumbus be replaced?",
            ),
            (
                "puppe strizzate al largo dei bastioni di orione",
                "在猎户座肩外挤压的乳房",
                "Squeezed breasts off the shoulder of Orion.",
            ),
        )
        assets = load_translation_runtime_assets(
            Path(__file__).resolve().parents[1] / "config"
        )
        for index, (source, translated, expected_override) in enumerate(cases):
            with self.subTest(source=source):
                items = build_translation_items(
                    [
                        {
                            "post_id": f"normalized-{index}",
                            "title": source,
                            "content": "",
                        }
                    ],
                    [],
                    include_comments=False,
                )
                client = _NormalizedSourceEqualRetryClient(translated)
                successes: list[dict[str, str]] = []
                _request_with_split(
                    client=client,
                    assets=assets,
                    items=(items[0],),
                    budget=AttemptBudget(max_attempts=2),
                    timeout_seconds=60.0,
                    on_error=lambda _error: None,
                    on_success=lambda translations, _completion: successes.append(
                        translations
                    ),
                )
                self.assertEqual(list(successes[0].values()), [translated])
                self.assertIn(expected_override, client.sources[1])

    def test_single_invalid_json_retries_once_without_accepting_bad_response(self) -> None:
        items = build_translation_items(
            [{"post_id": "json", "title": "Translate this", "content": ""}],
            [],
            include_comments=False,
        )
        client = _SingleInvalidJsonRetryClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[0],),
            budget=AttemptBudget(max_attempts=2),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(
            successes,
            [{"post:json:title": "这是一条有效的中文翻译。"}],
        )
        self.assertEqual(len(errors), 1)

    def test_repeated_invalid_json_uses_one_response_paragraph_fallback(self) -> None:
        source = (
            "Momcozy M5 costs $99.\n\n"
            "Elvie costs $199.\n\n"
            "See https://example.com/review."
        )
        items = build_translation_items(
            [{"post_id": "json-chunk", "title": "", "content": source}],
            [],
            include_comments=False,
        )
        client = _InvalidJsonThenChunkedClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[1],),
            budget=AttemptBudget(max_attempts=3),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(client.calls, 3)
        self.assertEqual(client.final_batch_size, 3)
        self.assertIn("Momcozy M5", successes[0]["post:json-chunk:content"])
        self.assertIn("$199", successes[0]["post:json-chunk:content"])
        self.assertIn(
            "https://example.com/review",
            successes[0]["post:json-chunk:content"],
        )
        self.assertEqual(len(errors), 2)

    def test_failed_protected_chunks_retry_as_raw_chunks_with_full_validation(self) -> None:
        source = (
            "Momcozy M5 costs $99.\n\n"
            "Elvie costs $199.\n\n"
            "See https://example.com/review."
        )
        items = build_translation_items(
            [{"post_id": "raw-chunks", "title": "", "content": source}],
            [],
            include_comments=False,
        )
        client = _ProtectedThenRawChunkedClient()
        successes: list[dict[str, str]] = []
        errors: list[Exception] = []

        _request_with_split(
            client=client,
            assets=load_translation_runtime_assets(
                Path(__file__).resolve().parents[1] / "config"
            ),
            items=(items[1],),
            budget=AttemptBudget(max_attempts=5),
            timeout_seconds=60.0,
            on_error=errors.append,
            on_success=lambda translations, _completion: successes.append(translations),
        )

        self.assertEqual(client.calls, 5)
        self.assertEqual(client.final_batch_size, 3)
        result = successes[0]["post:raw-chunks:content"]
        self.assertIn("Momcozy M5", result)
        self.assertIn("$199", result)
        self.assertIn("https://example.com/review", result)
        self.assertEqual(len(errors), 4)


if __name__ == "__main__":
    unittest.main()
