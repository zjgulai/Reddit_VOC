from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reddit_voc.report_contracts import AttemptEvidence


ZERO_TIP = "0" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class ProviderAttemptLedgerTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("reddit_voc.provider_attempt_ledger")
        except ModuleNotFoundError:
            self.fail("provider attempt ledger v2 module is missing")

    def test_reservation_start_and_terminal_form_private_canonical_hash_chain(self) -> None:
        """Catches missing lifecycle evidence, plaintext capture, and broken chain links."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )

            reserved = ledger.reserve(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=ZERO_TIP,
            )
            started = ledger.start(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=reserved.entry_hash,
            )
            terminal = ledger.terminal(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                result="succeeded",
                response_metadata={
                    "http_status": 200,
                    "response_id": "response-1",
                    "actual_model": "deepseek-v4-flash",
                    "system_fingerprint": "fp-safe",
                    "finish_reason": "stop",
                    "retryable": False,
                    "duration_ms": 17,
                },
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 11,
                    "total_tokens": 18,
                },
                expected_tip=started.entry_hash,
            )

            snapshot = ledger.load()
            self.assertEqual(snapshot.tip, terminal.entry_hash)
            self.assertEqual([entry["event_type"] for entry in snapshot.entries], [
                "reservation",
                "start",
                "terminal",
            ])
            self.assertEqual(
                [entry["ledger_sequence"] for entry in snapshot.entries], [1, 2, 3]
            )
            previous = ZERO_TIP
            for entry in snapshot.entries:
                self.assertEqual(entry["previous_entry_hash"], previous)
                base = {key: value for key, value in entry.items() if key != "entry_hash"}
                expected_hash = hashlib.sha256(_canonical(base)).hexdigest()
                self.assertEqual(entry["entry_hash"], expected_hash)
                previous = expected_hash

            payload = ledger.path.read_bytes()
            self.assertNotIn(b"prompt text must never be stored", payload)
            self.assertNotIn(b"response text must never be stored", payload)
            self.assertNotIn(b"secret-value", payload)
            self.assertNotIn(b"response-1", payload)
            self.assertEqual(stat.S_IMODE(os.lstat(ledger.path).st_mode), 0o600)
            self.assertEqual(
                snapshot.entries[-1]["response_metadata_sha256"],
                hashlib.sha256(
                    _canonical(
                        {
                            "actual_model": "deepseek-v4-flash",
                            "duration_ms": 17,
                            "finish_reason": "stop",
                            "http_status": 200,
                            "response_id": "response-1",
                            "retryable": False,
                            "system_fingerprint": "fp-safe",
                        }
                    )
                ).hexdigest(),
            )

    def test_unknown_closes_a_started_external_attempt_without_inventing_a_result(self) -> None:
        """Catches crash recovery that silently treats an indeterminate call as unused."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            reserved = ledger.reserve(
                phase="semantic_validation",
                sequence=1,
                request_payload_sha256="c" * 64,
                expected_tip=ZERO_TIP,
            )
            started = ledger.start(
                phase="semantic_validation",
                sequence=1,
                request_payload_sha256="c" * 64,
                expected_tip=reserved.entry_hash,
            )

            unknown = ledger.unknown(
                phase="semantic_validation",
                sequence=1,
                request_payload_sha256="c" * 64,
                expected_tip=started.entry_hash,
            )

            entry = unknown.entry
            self.assertEqual(entry["event_type"], "unknown")
            self.assertEqual(entry["result"], "unknown_external_state")
            self.assertTrue(entry["external_attempt_made"])
            self.assertIsNone(entry["response_metadata_sha256"])
            self.assertEqual(entry["usage"], {key: 0 for key in (
                "prompt_tokens",
                "completion_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
                "total_tokens",
            )})
            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "ledger_closure_transition_invalid",
            ):
                ledger.terminal(
                    phase="semantic_validation",
                    sequence=1,
                    request_payload_sha256="c" * 64,
                    result="succeeded",
                    response_metadata={
                        "http_status": 200,
                        "response_id": None,
                        "actual_model": None,
                        "system_fingerprint": None,
                        "finish_reason": None,
                        "retryable": False,
                        "duration_ms": 0,
                    },
                    usage={key: 0 for key in (
                        "prompt_tokens",
                        "completion_tokens",
                        "prompt_cache_hit_tokens",
                        "prompt_cache_miss_tokens",
                        "total_tokens",
                    )},
                    expected_tip=unknown.entry_hash,
                )

            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "complete_manifest_has_unknown_attempt",
            ):
                ledger.build_manifest_binding(status="complete")
            blocked_binding = ledger.build_manifest_binding(status="blocked")
            self.assertEqual(blocked_binding["attempts"][0]["closure_event_type"], "unknown")

    def test_manifest_binding_closes_every_event_and_rejects_summary_drift(self) -> None:
        """Catches manifests that claim a different provider history than the ledger."""
        module = self._module()
        usage = {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 5,
            "total_tokens": 8,
        }
        metadata = {
            "http_status": 200,
            "response_id": "response-1",
            "actual_model": "deepseek-v4-flash",
            "system_fingerprint": None,
            "finish_reason": "stop",
            "retryable": False,
            "duration_ms": 21,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            reserved = ledger.reserve(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=ZERO_TIP,
            )
            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "ledger_open_attempt",
            ):
                ledger.build_manifest_binding(status="blocked")
            started = ledger.start(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=reserved.entry_hash,
            )
            ledger.terminal(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                result="succeeded",
                response_metadata=metadata,
                usage=usage,
                expected_tip=started.entry_hash,
            )

            binding = ledger.build_manifest_binding(status="complete")
            self.assertEqual(binding["schema_version"], "provider-attempt-ledger-binding-v2")
            self.assertEqual(binding["event_count"], 3)
            self.assertEqual(binding["authorization_id"], "auth-1")
            self.assertEqual(binding["release_sha256"], "a" * 64)
            self.assertEqual(binding["run_id"], "run-1")
            self.assertEqual(binding["attempt_id"], "attempt-1")
            self.assertEqual(binding["usage"], usage)
            self.assertEqual(binding["attempts"][0]["reservation_entry_hash"], reserved.entry_hash)
            self.assertEqual(binding["attempts"][0]["start_entry_hash"], started.entry_hash)
            self.assertEqual(binding["attempts"][0]["closure_event_type"], "terminal")

            manifest = {
                "status": "complete",
                "run_id": "run-1",
                "provider_authorization_id": "auth-1",
                "provider_call": True,
                "translation_provider_call": True,
                "translation_provider_attempt_made": True,
                "translation_phase_attempt_made": True,
                "semantic_validation_phase_attempt_made": False,
                "request_count": 1,
                "retry_count": 0,
                "usage": usage,
                "provider_attempt_ledger": binding,
            }
            ledger.verify_manifest_closure(manifest)
            drifted = {**manifest, "request_count": 2}
            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "manifest_request_count_mismatch",
            ):
                ledger.verify_manifest_closure(drifted)
            drifted_binding = {
                **binding,
                "ledger_tip": "d" * 64,
            }
            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "manifest_ledger_binding_mismatch",
            ):
                ledger.verify_manifest_closure(
                    {**manifest, "provider_attempt_ledger": drifted_binding}
                )
            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "manifest_retry_count_mismatch",
            ):
                ledger.verify_manifest_closure({**manifest, "retry_count": 1})

    def test_semantically_invalid_unknown_is_rejected_even_with_recomputed_hash(self) -> None:
        """Catches a hash-valid row that falsely resolves an indeterminate call."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            reserved = ledger.reserve(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=ZERO_TIP,
            )
            started = ledger.start(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=reserved.entry_hash,
            )
            ledger.unknown(
                phase="translation",
                sequence=1,
                request_payload_sha256="b" * 64,
                expected_tip=started.entry_hash,
            )
            rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
            rows[-1]["result"] = "succeeded"
            base = {key: value for key, value in rows[-1].items() if key != "entry_hash"}
            rows[-1]["entry_hash"] = hashlib.sha256(_canonical(base)).hexdigest()
            ledger.path.write_bytes(b"".join(_canonical(row) + b"\n" for row in rows))

            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "ledger_unknown_invalid",
            ):
                ledger.load()

    def test_lifecycle_adapter_maps_safe_evidence_and_recovers_open_boundaries(self) -> None:
        """Catches adapters that lose terminal evidence or retry an open boundary."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            lifecycle = module.ProviderAttemptLifecycle(ledger)
            lifecycle.reserve(
                sequence=1,
                phase="translation",
                request_payload_sha256="b" * 64,
            )
            lifecycle.start(
                sequence=1,
                phase="translation",
                request_payload_sha256="b" * 64,
            )
            lifecycle.terminal(
                sequence=1,
                phase="translation",
                request_payload_sha256="b" * 64,
                evidence=AttemptEvidence(
                    sequence=1,
                    phase="translation",
                    http_status=503,
                    outcome="http_status_503",
                    retryable=True,
                    duration_ms=19,
                    response_id=None,
                    actual_model=None,
                    system_fingerprint=None,
                    finish_reason=None,
                    usage=None,
                ),
            )
            lifecycle.reserve(
                sequence=2,
                phase="semantic_validation",
                request_payload_sha256="c" * 64,
            )
            lifecycle.start(
                sequence=2,
                phase="semantic_validation",
                request_payload_sha256="c" * 64,
            )

            closed = lifecycle.close_incomplete()

            self.assertEqual(closed, (2,))
            snapshot = ledger.load()
            self.assertEqual(
                [entry["event_type"] for entry in snapshot.entries],
                ["reservation", "start", "terminal", "reservation", "start", "unknown"],
            )
            terminal = snapshot.entries[2]
            self.assertEqual(terminal["result"], "http_status_503")
            self.assertEqual(terminal["usage"], {key: 0 for key in (
                "prompt_tokens",
                "completion_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
                "total_tokens",
            )})
            self.assertIsNotNone(terminal["response_metadata_sha256"])
            binding = ledger.build_manifest_binding(status="blocked")
            self.assertEqual(binding["external_attempt_count"], 2)
            self.assertEqual(binding["unknown_attempt_count"], 1)

    def test_reserved_but_not_started_is_closed_without_claiming_external_attempt(self) -> None:
        """Catches recovery that turns a pre-boundary reservation into a provider call."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            lifecycle = module.ProviderAttemptLifecycle(ledger)
            lifecycle.reserve(
                sequence=1,
                phase="translation",
                request_payload_sha256="b" * 64,
            )

            closed = lifecycle.close_incomplete()

            self.assertEqual(closed, (1,))
            binding = ledger.build_manifest_binding(status="blocked")
            self.assertEqual(binding["external_attempt_count"], 0)
            self.assertEqual(binding["attempts"][0]["result"], "cancelled_before_external")
            self.assertIsNone(binding["attempts"][0]["start_entry_hash"])

    def test_concurrent_budget_sequences_may_reserve_out_of_order_but_close_contiguously(self) -> None:
        """Catches a concurrency race between budget allocation and durable reservation."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            lifecycle = module.ProviderAttemptLifecycle(ledger)

            lifecycle.reserve(
                sequence=2,
                phase="translation",
                request_payload_sha256="c" * 64,
            )
            lifecycle.reserve(
                sequence=1,
                phase="translation",
                request_payload_sha256="b" * 64,
            )
            self.assertEqual(lifecycle.close_incomplete(), (1, 2))
            binding = ledger.build_manifest_binding(status="blocked")
            self.assertEqual(
                [attempt["sequence"] for attempt in binding["attempts"]], [1, 2]
            )

    def test_lock_and_cas_allow_exactly_one_writer_for_the_same_tip(self) -> None:
        """Catches check-then-append races that fork the hash chain."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )

            def append(sequence: int):
                try:
                    return ledger.reserve(
                        sequence=sequence,
                        phase="translation",
                        request_payload_sha256=("b" if sequence == 1 else "c") * 64,
                        expected_tip=ZERO_TIP,
                    )
                except module.ProviderAttemptLedgerCasError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(append, (1, 2)))

            self.assertEqual(
                sum(isinstance(outcome, module.ProviderAttemptLedgerCasError) for outcome in outcomes),
                1,
            )
            snapshot = ledger.load()
            self.assertEqual(len(snapshot.entries), 1)
            self.assertEqual(snapshot.entries[0]["previous_entry_hash"], ZERO_TIP)

    def test_broken_symlink_cannot_masquerade_as_an_empty_ledger(self) -> None:
        """Catches existence checks that follow a missing symlink target."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = module.ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            ledger.path.symlink_to(root / "missing-target")

            with self.assertRaisesRegex(
                module.ProviderAttemptLedgerError,
                "ledger_file_not_regular",
            ):
                ledger.load()


if __name__ == "__main__":
    unittest.main()
